"""Task Scheduler entrypoint: posts due reels for ONE brand to Facebook,
Instagram and YouTube, then drops the TChess promo comment on FB/IG/YT.

Usage:
    python publish.py                         # infer the brand from the clock
    python publish.py --account tchessapp     # explicit brand (what the tasks pass)
    python publish.py --dry-run               # resolve + print, no real POSTs
    python publish.py --once <id>             # force one specific pending item

Source of truth is the ledger (data/posted.json via src/queue.py). Windows
Task Scheduler fires this six times a day — three slots per brand, two hours
apart so the two never post together (see config.ACCOUNTS) — and each run
posts config.PUBLISH_PER_RUN_CAP items (default 1), oldest eligible first.
Six runs/day * one each = six reels/day, three per brand.

🔴 ONE RUN SERVES EXACTLY ONE BRAND. Both brands draw from a single pool of
built reels, and a reel is stamped with its brand (queue.assign_account) the
moment a run claims it, before anything is posted. That stamp is the entire
reason a person following both accounts never sees the same reel twice — no
caption comparison, no filename convention, no history scan. Anything here
that picked entries without going through `ledger.pending(account=...)` would
quietly break that guarantee.

Only entries whose video_path ends in .mp4 are auto-published. Stills
(promo_carousel) use a different posting shape on every platform and are not
automated yet — they're skipped and logged for manual posting.
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import config
from src import accounts
from src import publisher
from src import autogen
from src import queue as ledger
from src import status_bridge
from src import tiktok_browser

log = logging.getLogger("publish")


def setup_logging(verbose: bool):
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    # Windows' console codepage (cp1252) can't encode emoji that now show up
    # in captions/titles by design; without this a caption with an emoji
    # crashes the console handler (silently, since logging swallows handler
    # errors) and the dry-run preview never prints.
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:
            pass
    console = logging.StreamHandler(stream)
    console.setFormatter(fmt)
    log.addHandler(console)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(config.PUBLISH_LOG, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)


def notify(summary: str, title: str = "ChessReel publish failed"):
    try:
        from plyer import notification
        notification.notify(title=title, message=summary[:250], timeout=15)
    except Exception as exc:  # noqa: BLE001 — a broken toast must never crash the run
        log.warning("toast notification unavailable: %s", exc)


def resolve_account(explicit: str = None) -> str:
    """Which brand this run publishes as.

    Explicit `--account` wins, always — the six scheduled tasks each pass
    their own, and that is the only thing a run should ever trust. The clock
    is a fallback so a manual `python publish.py` at 17:05, or the dashboard's
    "Run Next Now", does the obviously-intended thing rather than silently
    defaulting to the other brand.
    """
    if explicit:
        if not accounts.exists(explicit):
            log.error("unknown account %r (known: %s)", explicit, ", ".join(accounts.all_names()))
            sys.exit(2)
        if not accounts.is_enabled(explicit):
            log.error(
                "account %r is not enabled — set %s=1 in .env once "
                "`python scripts/verify_accounts.py` passes for it",
                explicit, "TCHESSAPP_ENABLED" if explicit == "tchessapp" else f"{explicit.upper()}_ENABLED",
            )
            sys.exit(2)
        return explicit

    inferred = accounts.infer_from_clock()
    if inferred:
        log.info("account inferred from the clock: %s (%s)", inferred, accounts.label(inferred))
        return inferred

    log.info(
        "no account slot within %d min of now — falling back to %s",
        config.ACCOUNT_SLOT_TOLERANCE_MIN, config.DEFAULT_ACCOUNT,
    )
    return config.DEFAULT_ACCOUNT


class Lock:
    """Prevents an overlapping/stuck run from double-posting."""

    def __init__(self, path, max_age_hours):
        self.path = Path(path)
        self.max_age_hours = max_age_hours

    def __enter__(self):
        if self.path.exists():
            age_hours = (time.time() - self.path.stat().st_mtime) / 3600
            if age_hours < self.max_age_hours:
                log.error("lock %s is %.1fh old — another run in progress, exiting", self.path, age_hours)
                sys.exit(1)
            log.warning("stale lock (%.1fh old) — removing and continuing", age_hours)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(datetime.now().isoformat(), encoding="utf-8")
        return self

    def __exit__(self, *exc_info):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def get_or_init_cutoff() -> str:
    """ISO timestamp: entries built before this are historical backlog, never
    auto-published. Set once, to "now", the first time this ever runs."""
    marker = config.PUBLISH_CUTOFF_MARKER
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip()
    # Same format as src/queue.py's _now() (UTC, "...Z") — entry["created_at"]
    # is stamped that way, and the two need to compare correctly as strings.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(now, encoding="utf-8")
    log.info("first run - publish cutoff set to %s; everything built before this stays untouched", now)
    return now


def is_eligible(entry: dict, cutoff: str) -> bool:
    """Filters out content this ledger was never meant to hand to a publisher:
    in-app-feed builds (must never carry branding, never social — see
    config.py), anything outside this project (a stray path from some other
    session), anything built before the autopilot cutoff (the historical
    dev/test backlog — see config.PUBLISH_CUTOFF_MARKER) — except
    output/promo/**, the user's own curated backlog, which is cutoff-exempt —
    and non-video entries (promo_carousel stills), which publish_one() can
    never actually post. That last exclusion matters here, not just in
    publish_one(): main()'s "backlog exhausted" notification is driven off
    this same eligibility check, so a still counted as "eligible" would mask
    real video exhaustion forever."""
    video_path = Path(entry["video_path"])
    norm = video_path.as_posix().lower()

    if video_path.suffix.lower() != ".mp4":
        return False
    if "/output/app/" in norm:
        return False
    if "/_posted/" in norm:
        return False  # the user's own manual marker for "already shared"
    try:
        video_path.relative_to(config.ROOT)
    except ValueError:
        log.warning("[%s] video_path is outside the project, skipping: %s", entry["puzzle_id"], video_path)
        return False
    try:
        video_path.relative_to(config.PUBLISH_CUTOFF_EXEMPT_DIR)
        return True
    except ValueError:
        pass
    if entry.get("created_at", "") < cutoff:
        return False
    # A stub caption makes an entry unpublishable, so it is not runway either.
    # Checking it HERE and not only in is_structurally_publishable keeps
    # content_runway honest: an entry counted as "eligible" that can never be
    # posted is exactly the kind of phantom backlog that hides a real run-out.
    if not has_real_caption(entry):
        return False
    return True


def has_real_caption(entry: dict) -> bool:
    """False when the entry's caption is captions.py's needs_caption stub."""
    try:
        meta = load_meta(entry.get("video_path", ""))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return True      # unreadable meta is is_structurally_publishable's call
    return not (meta.get("caption") or {}).get("needs_caption")


def load_meta(video_path: str) -> dict:
    meta_path = Path(video_path).parent / "meta.json"
    return json.loads(meta_path.read_text(encoding="utf-8"))


def compose_caption(meta: dict) -> str:
    """FB/IG post text: the caption body already opens with its own hook line
    (2026-08-26 prompt rewrite) — prepending the separate on-screen `hook`
    here duplicated it and was a chunk of why these read as bloated."""
    c = meta.get("caption", {})
    body = c.get("caption", "")
    hashtags = " ".join(c.get("hashtags", []))
    return "\n\n".join(part for part in (body, hashtags) if part)


def compose_youtube_description(meta: dict) -> str:
    """YouTube gets its own description, distinct from the FB/IG caption.

    Falls back to compose_caption() for content built before 2026-08-26,
    whose meta.json has no `youtube_description`.
    """
    c = meta.get("caption", {})
    body = c.get("youtube_description") or c.get("caption", "")
    hashtags = " ".join(c.get("hashtags", []))
    return "\n\n".join(part for part in (body, hashtags) if part)


def publish_one(entry: dict, dry_run: bool, account: str = None) -> bool:
    """Returns True if this entry was actually attempted (real work or a
    dry-run preview), False if it was structurally skipped (not a video,
    missing file, unreadable meta) — so callers can tell a "did nothing
    because the queue is empty" run apart from "burned its slot on junk".

    `account` is the brand this run is posting as. An entry already stamped
    for a brand always uses its own stamp instead, so a `--once` retry of a
    half-posted reel can never finish on a different account than it started
    on.
    """
    puzzle_id = entry["puzzle_id"]
    video_path = entry["video_path"]
    account = entry.get("account") or account or config.DEFAULT_ACCOUNT

    if Path(video_path).suffix.lower() != ".mp4":
        log.info("[%s] not a video (stills/carousel) — skipping, post manually", puzzle_id)
        return False

    if not Path(video_path).exists():
        log.error("[%s] video file missing on disk, skipping: %s", puzzle_id, video_path)
        notify(f"{puzzle_id}: video file missing on disk — {video_path}")
        return False

    try:
        meta = load_meta(video_path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.error("[%s] meta.json unreadable, skipping: %s", puzzle_id, exc)
        notify(f"{puzzle_id}: meta.json unreadable — {exc}")
        return False
    caption = compose_caption(meta)
    due = ledger.due_platforms(entry)

    if dry_run:
        cap = meta.get("caption", {})
        title = f"{cap.get('youtube_title') or cap.get('hook', puzzle_id)} #Shorts"
        description = compose_youtube_description(meta)
        log.info(
            "[%s] DRY RUN - would publish as %s (%s) to %s\n"
            "--- FB/IG caption ---\n%s\n"
            "--- YT title ---\n%s\n"
            "--- YT description ---\n%s\n---",
            puzzle_id, account, accounts.label(account), due, caption, title, description,
        )
        return True

    for platform in due:
        try:
            if platform == "fb":
                cap = meta.get("caption", {})
                # The composer has its own Title field, separate from the post
                # text. Reusing the YouTube title keeps one voice across
                # platforms rather than inventing a third.
                fb_title = cap.get("youtube_title") or cap.get("hook") or puzzle_id
                post_id = publisher.post_facebook(
                    video_path, caption, account=account, title=fb_title)
            elif platform == "ig":
                post_id = publisher.post_instagram(video_path, puzzle_id, caption, account=account)
            elif platform == "yt":
                cap = meta.get("caption", {})
                # youtube_title postdates some already-built content (2026-08-22);
                # fall back to the on-screen hook for anything built before then.
                title = f"{cap.get('youtube_title') or cap.get('hook', puzzle_id)} #Shorts"
                description = compose_youtube_description(meta)
                post_id = publisher.post_youtube(video_path, title, description, account=account)
            elif platform == "tt":
                # TikTok Studio's web uploader, driven headless from the
                # Gmail_40 profile (src/tiktok_browser.py). Same caption as
                # FB/IG. Returns the video URL, or a TT_UNRESOLVED sentinel
                # when it posted but the URL could not be read back.
                post_id = tiktok_browser.post_tiktok(video_path, caption, account)
            else:
                continue

            log.info("[%s] posted to %s as %s -> %s", puzzle_id, platform, account, post_id)
            ledger.mark_platform(puzzle_id, platform, post_id)
            cap_meta = meta.get("caption", {})
            status_bridge.record_event(
                "published", puzzle_id=puzzle_id, platform=platform, post_id=post_id,
                account=account,
                hook=cap_meta.get("hook"), caption=cap_meta.get("caption"),
                hashtags=cap_meta.get("hashtags"), video_path=video_path,
            )

            # No TikTok comment, by the owner's call (2026-09-29): TikTok put the
            # comment box behind a CAPTCHA, which is never solved. The promo line
            # is in the caption instead (config.TIKTOK_CAPTION_PROMO).
            # src/tiktok_browser.post_comment() stays available but is not called.

            if platform in ("fb", "ig", "yt") and not str(post_id).startswith(config.FB_UNRESOLVED_PREFIX):
                # A sentinel id means the reel is live but unidentified, so
                # there is no object to comment on. Skipping is right: the
                # alternative is a guaranteed error every single run.
                #
                # Identical wording for both brands, on purpose: the promo
                # points at the same app either way, and the account it is
                # posted *as* is what differs.
                comment_text = {
                    "fb": config.PROMO_COMMENT_FB,
                    "ig": config.PROMO_COMMENT_IG,
                    "yt": config.PROMO_COMMENT_YT,
                }[platform]
                try:
                    publisher.post_first_comment(platform, post_id, comment_text, account=account)
                    log.info("[%s] promo comment posted on %s as %s", puzzle_id, platform, account)
                    status_bridge.record_event(
                        "comment_posted", puzzle_id=puzzle_id, platform=platform, account=account)
                except Exception as exc:  # noqa: BLE001
                    log.error("[%s] promo comment FAILED on %s: %s", puzzle_id, platform, exc)
                    notify(f"{puzzle_id}: promo comment failed on {platform} ({account}): {exc}")
                    status_bridge.record_event(
                        "comment_failed", puzzle_id=puzzle_id, platform=platform,
                        account=account, error=str(exc))

        except Exception as exc:  # noqa: BLE001 — one platform's failure must not block the others
            log.error("[%s] publish FAILED on %s (%s): %s", puzzle_id, platform, account, exc)
            if platform == "tt":
                # 🔴 Complete the entry anyway. Left owing "tt", it would be
                # the oldest pending reel at the next slot and be picked
                # again for TikTok alone, so that slot would publish nothing
                # new on FB/IG/YT. TikTok skips this one reel; the rest
                # carries on. See src/tiktok_browser.py.
                try:
                    mark = tiktok_browser.record_failure(puzzle_id, str(exc))
                    log.warning("[%s] TikTok marked %s so FB/IG/YT are not held up", puzzle_id, mark)
                except Exception as mark_exc:  # noqa: BLE001
                    log.error("[%s] could not record the TikTok failure: %s", puzzle_id, mark_exc)
            else:
                # Retried on later slots, but only PLATFORM_MAX_FAILURES times:
                # after that this reel skips the platform so the queue moves.
                try:
                    mark = ledger.record_platform_failure(puzzle_id, platform)
                    if mark:
                        log.warning("[%s] giving up on %s after %d failures (%s) — "
                                    "the queue moves on", puzzle_id, platform,
                                    config.PLATFORM_MAX_FAILURES, mark)
                except Exception as mark_exc:  # noqa: BLE001
                    log.error("[%s] could not record the %s failure: %s", puzzle_id, platform, mark_exc)
            notify(f"{puzzle_id}: publish failed on {platform} ({account}): {exc}")
            status_bridge.record_event(
                "publish_failed", puzzle_id=puzzle_id, platform=platform,
                account=account, error=str(exc))

    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", metavar="PUZZLE_ID", help="force-publish one specific pending item")
    ap.add_argument(
        "--account", metavar="NAME",
        help=f"which brand to publish as ({', '.join(accounts.all_names())}); "
             "defaults to whichever brand's slot is closest to now",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)

    if not args.once and status_bridge.is_paused():
        control = status_bridge.get_control()
        reason = control.get("paused_reason")
        if reason == "content_exhausted":
            # ⚠️ THIS PAUSE IS A LEFTOVER STATE NOW. It was written when running
            # out of built reels was the end of the line; _run() generates on
            # demand since 2026-09-08, so a stop recorded under this reason is
            # almost always an OLD one that nobody cleared, not a live fault.
            # Resuming is safe and is the whole fix — the next slot will build
            # its own reel. A genuinely new content_exhausted pause means
            # AUTOGEN_MAX_ATTEMPTS builds failed in a row, which the log above
            # it will show.
            log.warning(
                "autopilot is paused with reason=content_exhausted. Reels are "
                "generated on demand now, so Resume from the dashboard is all "
                "this needs — the next slot will build its own."
            )
            status_bridge.sync_status(
                kind="paused",
                note="run skipped: paused (content_exhausted) — resume to let it "
                     "generate on demand")
        else:
            log.info("autopilot is paused via the dashboard — skipping this run")
            status_bridge.sync_status(kind="paused", note="run skipped: paused via dashboard")
        return 0

    last_error = None
    result = 0
    try:
        with Lock(config.PUBLISH_LOCK, config.PUBLISH_LOCK_MAX_AGE_HOURS):
            result = _run(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — always push a status snapshot, even on a crash
        last_error = str(exc)
        raise
    finally:
        if not args.dry_run:
            status_bridge.sync_status(kind="run", last_error=last_error)

    return result


def is_structurally_publishable(entry: dict) -> bool:
    """Cheap, side-effect-free version of publish_one()'s own preconditions.

    Exists so a run can find out whether an entry is real BEFORE stamping it
    with a brand. Stamping has to happen before the first POST — an entry
    posted but not yet stamped could be picked up and posted again by the
    other brand's next run, which is the one outcome this design exists to
    prevent — so the order is: check, stamp, post. Without this check a reel
    whose file has gone missing would be permanently consumed from the shared
    pool by whichever brand happened to look at it first.
    """
    video_path = Path(entry.get("video_path", ""))
    if video_path.suffix.lower() != ".mp4" or not video_path.exists():
        return False
    try:
        meta = load_meta(str(video_path))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False

    # 🔴 A PLACEHOLDER CAPTION MUST NEVER REACH A REAL ACCOUNT. captions.py
    # degrades to a stub when the OpenAI call is unavailable — deliberately, so
    # one network failure cannot kill a build — and stamps needs_caption on it.
    # The stub's own text reads "Caption generation was unavailable for this
    # post. Re-run with the OpenAI API enabled before publishing", which is a
    # sentence about the pipeline printed under a chess reel.
    #
    # This became a live hazard the moment builds started happening
    # unattended: run_batch.py reads OPENAI_API_KEY off os.environ, so any
    # build whose process never loaded .env produced one of these silently. The
    # .env load in run_batch.py fixes the cause; this is the net under it.
    if (meta.get("caption") or {}).get("needs_caption"):
        log.warning("[%s] caption is a placeholder — not publishing. Rebuild it "
                    "with OPENAI_API_KEY available.", entry.get("puzzle_id"))
        return False
    return True


def content_runway(cutoff: str = None) -> dict:
    """How much publishable content is left, and how long it lasts.

    Counts EVERY eligible pending entry, whichever brand it is stamped for
    plus the unstamped shared pool, because "are we about to run out?" is a
    question about the pipeline, not about one account. Per-brand numbers are
    broken out alongside for the dashboard.
    """
    cutoff = cutoff or get_or_init_cutoff()
    eligible = [p for p in ledger.pending() if is_eligible(p, cutoff)]

    by_account = {n: 0 for n in accounts.all_names()}
    unassigned = 0
    for entry in eligible:
        owner = entry.get("account")
        if owner in by_account:
            by_account[owner] += 1
        else:
            unassigned += 1

    # Derived from the schedule rather than hardcoded, so pausing a brand or
    # changing its slots moves the estimate with it instead of leaving the
    # dashboard quoting a cadence nobody runs any more.
    burn = sum(len(accounts.slots(n)) for n in accounts.enabled_names()) * config.PUBLISH_PER_RUN_CAP

    total = len(eligible)
    if total <= 0:
        level = "exhausted"
    elif total <= config.CONTENT_CRITICAL_WATERMARK:
        level = "critical"
    elif total <= config.CONTENT_LOW_WATERMARK:
        level = "low"
    else:
        level = "ok"

    return {
        "total": total,
        "unassigned": unassigned,
        "by_account": by_account,
        "daily_burn": burn,
        "days_left": round(total / burn, 1) if burn else None,
        "level": level,
    }


def _announce_runway(runway: dict):
    """Log/toast/record the content level, but only make noise when it CHANGES.

    Six runs a day against a shrinking backlog would otherwise fire six
    identical "running low" toasts a day for two days straight, which is how a
    warning gets ignored right before it matters. The last announced level is
    remembered on disk, so each level is announced once, on the run that
    crosses into it.
    """
    level = runway["level"]
    marker = config.CONTENT_LEVEL_MARKER
    try:
        previous = marker.read_text(encoding="utf-8").strip()
    except OSError:
        previous = ""

    detail = ", ".join(f"{n}: {c}" for n, c in runway["by_account"].items())
    log.info(
        "content runway: %d reel(s) left (%d unassigned; %s) — about %s day(s) at %d/day [%s]",
        runway["total"], runway["unassigned"], detail,
        runway["days_left"], runway["daily_burn"], level,
    )

    if level == previous:
        return
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(level, encoding="utf-8")
    except OSError as exc:
        log.warning("could not record content level: %s", exc)

    if level == "ok":
        return

    if level == "exhausted":
        message = (
            "ChessReel has published the last built reel. Nothing is left for either "
            "account. Generate new content, then Resume from the dashboard."
        )
        log.info("queue empty — the next slot will build its own reel "
                 "(see src/autogen.py). Top it up from the dashboard if you "
                 "would rather posts did not wait on a build.")
    else:
        message = (
            f"ChessReel content is {level}: {runway['total']} reel(s) left, "
            f"about {runway['days_left']} day(s) at {runway['daily_burn']}/day."
        )
        log.warning(message)

    notify(message, title="ChessReel content")
    status_bridge.record_event("content_" + level, **runway)


def _is_retry(entry: dict) -> bool:
    """Already published to at least one platform; only owes the rest."""
    return any((entry.get("platforms") or {}).values())


def _run(args) -> int:
    account = resolve_account(args.account)
    all_pending = ledger.pending()

    if args.once:
        # Explicit manual override — bypasses the cutoff/eligibility filter
        # on purpose, so a specific backlog item can still be posted on
        # demand, or a single failed platform retried from the dashboard
        # (due_platforms() inside publish_one already skips platforms that
        # already succeeded, so this naturally retries only what's missing).
        # publish_one prefers the entry's OWN stamp over `account`, so
        # retrying a half-posted reel always finishes it on the brand it
        # started on, whatever brand's slot the retry happens to land in.
        pending = [p for p in all_pending if p["puzzle_id"] == args.once]
        if not pending:
            log.error("no pending entry with puzzle_id=%s", args.once)
            return 1
        for entry in pending:
            # 🔴 STAMP EVEN HERE. A --once on an entry that carries no stamp
            # yet — a pre-2026-09-02 backlog item, or a manual push of
            # something the scheduled runs never claimed — would otherwise
            # post it and leave it unclaimed, so the OTHER brand's next
            # scheduled run would find it in the shared pool and post it
            # again. That is the one duplicate this whole design exists to
            # prevent, arriving through the manual door.
            if not args.dry_run and not entry.get("account"):
                if ledger.assign_account(entry["puzzle_id"], account):
                    entry["account"] = account
                    log.info("[%s] claimed for %s (manual --once)", entry["puzzle_id"], account)
            publish_one(entry, args.dry_run, account=account)
        return 0

    cutoff = get_or_init_cutoff()
    # An entry that owes nothing any more — every remaining platform was
    # switched off or given up on — is finished. Left "pending" it would be
    # picked again every slot and publish to nothing.
    if not args.dry_run:
        for e in all_pending:
            if e.get("account") == account and not ledger.due_platforms(e):
                ledger.mark_status(e["puzzle_id"], "posted")
                log.info("[%s] nothing left to publish for it — marked done", e["puzzle_id"])
    # This brand's own queue: entries already stamped for it, plus the shared
    # unstamped pool. Entries belonging to the other brand are not returned,
    # which is what makes "never the same reel twice" structural rather than
    # a thing this loop has to remember.
    eligible = [p for p in ledger.pending(account=account) if is_eligible(p, cutoff)]
    mine = sum(1 for e in eligible if e.get("account") == account)
    log.info(
        "publishing as %s (%s) — per-run cap: %d, %d pending total, "
        "%d eligible for this brand (%d already stamped, %d from the shared pool)",
        account, accounts.label(account), config.PUBLISH_PER_RUN_CAP,
        len(all_pending), len(eligible), mine, len(eligible) - mine,
    )

    # Only RETRIES left (reels that went out somewhere and still owe a
    # platform) is the same as an empty queue for the purpose of this slot:
    # retries do not count against the cap, so without a fresh reel the slot
    # would publish nothing new. Build one and keep the retries alongside it.
    if eligible and all(_is_retry(e) for e in eligible) \
            and not args.dry_run and config.AUTOGEN_ENABLED:
        log.info("only retries queued for %s — generating a fresh reel too", account)
        status_bridge.record_event("autogen_started", account=account)
        built = autogen.generate_until_eligible(log, is_eligible, cutoff)
        if built is None:
            log.error("autogen failed — %s will only retry this slot", account)
            status_bridge.record_event("autogen_failed", account=account)
        else:
            status_bridge.record_event("autogen_built", account=account,
                                       puzzle_id=built["puzzle_id"],
                                       video_path=built["video_path"])
            eligible = [p for p in ledger.pending(account=account)
                        if is_eligible(p, cutoff)]

    if not eligible:
        # 🔴 BUILD ONE, DO NOT GIVE UP. This used to log "nothing to publish",
        # autopause and return — which is how the accounts went quiet for a day
        # and a half on 2026-09-07. An empty queue is now a normal state that
        # triggers a build, not an incident. See src/autogen.py.
        #
        # A dry run never generates: it exists to answer "what WOULD go out",
        # and a build has real side effects (a ledger entry, ~2 MB on disk, an
        # OpenAI caption call). Nor does it generate for a --once retry — that
        # path returned long before here.
        if args.dry_run or not config.AUTOGEN_ENABLED:
            log.info("nothing to publish for %s%s", account,
                     "" if args.dry_run else " (autogen disabled)")
            if not args.dry_run:
                _announce_runway(content_runway(cutoff))
                _stop_if_exhausted(content_runway(cutoff))
            return 0

        log.info("nothing queued for %s — generating one now", account)
        status_bridge.record_event("autogen_started", account=account)
        built = autogen.generate_until_eligible(log, is_eligible, cutoff)
        if built is None:
            # The queue is empty AND the generator cannot refill it. That is a
            # real fault rather than a routine run-out, so the autopause still
            # exists — it just means something quite different now.
            log.error("autogen failed — nothing to publish for %s", account)
            status_bridge.record_event("autogen_failed", account=account)
            _announce_runway(content_runway(cutoff))
            _stop_if_exhausted(content_runway(cutoff))
            return 1
        status_bridge.record_event("autogen_built", account=account,
                                   puzzle_id=built["puzzle_id"],
                                   video_path=built["video_path"])
        eligible = [p for p in ledger.pending(account=account)
                    if is_eligible(p, cutoff)]
        if not eligible:
            log.error("[%s] built but did not land in %s's queue",
                      built["puzzle_id"], account)
            return 1

    # A broken entry (missing file, unreadable meta) must not burn the run's
    # quota — keep trying eligible entries until PUBLISH_PER_RUN_CAP of them
    # were actually attempted, or the eligible list runs out.
    attempted = 0
    for entry in eligible:
        if attempted >= config.PUBLISH_PER_RUN_CAP:
            break

        if not args.dry_run and not entry.get("account"):
            if not is_structurally_publishable(entry):
                # Leave it unstamped: publish_one will log precisely why it is
                # unusable, and an unusable reel should not be charged to
                # either brand's share of the pool.
                publish_one(entry, args.dry_run, account=account)
                continue
            if not ledger.assign_account(entry["puzzle_id"], account):
                log.warning(
                    "[%s] could not claim for %s (already claimed by another brand) — skipping",
                    entry["puzzle_id"], account,
                )
                continue
            entry["account"] = account
            log.info("[%s] claimed for %s", entry["puzzle_id"], account)

        # A reel that already went out somewhere is only being RETRIED for the
        # platforms it still owes. That retry must not use up the slot, or one
        # failing platform stops every new reel (2026-10-16..20).
        retry = _is_retry(entry)
        if publish_one(entry, args.dry_run, account=account) and not retry:
            attempted += 1

    if not args.dry_run:
        # 🔴 NO AUTOPAUSE HERE, AND THIS LINE IS THE BUG THAT KILLED THE FIRST
        # LIVE NIGHT. The 23:00 run on 2026-09-08 posted davJ8 to all three
        # platforms, comments and all — and then reached this point, saw the
        # queue it had just drained to zero, and paused itself. Every later slot
        # then skipped on "paused".
        #
        # Draining to zero USED to mean "out of content". Since publish.py
        # generates on demand it means the opposite: the queue did its job and
        # the next slot will build its own reel. The only genuine dead end is
        # AUTOGEN_MAX_ATTEMPTS builds failing in a row, and the `not eligible`
        # branch above already pauses for exactly that.
        #
        # _announce_runway stays — the dashboard's buffer gauge is still real
        # information, it just is not a reason to stop.
        _announce_runway(content_runway(cutoff))

    return 0


def _stop_if_exhausted(runway: dict):
    """Stop the autopilot once the queue is empty AND cannot be refilled.

    ⚠️ THIS USED TO SAY "STOP, DO NOT GENERATE", and that is no longer the
    instruction. The old rule existed so an un-reviewed generator could not push
    to two live accounts on its own; the reels have since been reviewed and
    signed off, and _run() now builds one when the queue is empty. So reaching
    this function means something stronger than "the backlog ran out": it means
    AUTOGEN_MAX_ATTEMPTS builds were tried and none produced a publishable reel.
    The safety it provides is unchanged — only un-reviewed formats still never
    ship, which src/autogen.AUTO_VARIANTS enforces rather than this pause.

    Pausing rather than merely logging is what makes this visible: an unpaused
    autopilot with an empty queue just writes "nothing to publish" six times a
    day, whereas a pause with a reason renders as a deliberate stop on the
    dashboard. Resuming clears it; if the queue is still empty the next run
    simply stops again.
    """
    if runway["level"] != "exhausted" or not config.CONTENT_EXHAUSTED_AUTOPAUSE:
        return
    if status_bridge.is_paused():
        return
    if status_bridge.pause_for_content_exhaustion():
        log.warning("autopilot stopped: no content left. Resume from the dashboard once new reels exist.")


if __name__ == "__main__":
    raise SystemExit(main())
