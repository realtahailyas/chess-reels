"""Long-form autopilot: keep each channel's next YouTube slots filled.

    python longform_daily.py              # build what is missing, upload, schedule
    python longform_daily.py --dry-run    # print the plan; no render, no upload
    python longform_daily.py --brand tchess
    python longform_daily.py --no-upload  # build ahead only

Run by the "ChessReel Longform" scheduled task (scripts/setup_longform_schedule.ps1),
twice a day. Each run, per channel:
  1. works out the channel's publish slots over the next HORIZON_H hours;
  2. for every slot with no video scheduled yet, takes the next rendered
     video (or renders the next game in that channel's queue) and uploads it
     PRIVATE with publishAt set to the slot. YouTube makes it public on time;
  3. keeps one more video rendered in reserve;
  4. deletes the mp4 of videos public for more than KEEP_DAYS days (meta.json
     and the thumbnail stay).

Completely separate from publish.py: own lock, own ledger, own log, own task.
"""

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from src import accounts  # noqa: E402
from longform import catalog, facebook, publisher, render  # noqa: E402
from longform import lfconfig as C  # noqa: E402

HORIZON_H = 50          # schedule up to two daily slots ahead
MIN_LEAD_MIN = 45       # YouTube needs publishAt in the future; keep a margin
RESERVE = 1             # rendered-but-unscheduled videos kept per channel
MAX_TRIES = 6           # games tried per build before giving up for this run
KEEP_DAYS = 3
PREFETCH_AHEAD = 4      # games per channel kept analysed ahead of their day
PREFETCH_BUDGET_S = 15 * 60
LOCK = C.DATA / "daily.lock"
LOG = C.DATA / "publish.log"
STATUS = C.DATA / "status.json"

log = logging.getLogger("longform")


def setup_logging():
    C.DATA.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.handlers[:] = [fh, sh]
    log.setLevel(logging.INFO)


def slots(brand: str, now: datetime) -> list:
    """This channel's publish times (UTC) between now+lead and now+horizon."""
    tz = ZoneInfo(C.SLOT_TZ)
    local_now = now.astimezone(tz)
    out = []
    for day in range(0, 4):
        d = (local_now + timedelta(days=day)).date()
        for hhmm in C.BRANDS[brand]["slots_et"]:
            h, m = map(int, hhmm.split(":"))
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=tz).astimezone(timezone.utc)
            if now + timedelta(minutes=MIN_LEAD_MIN) <= t <= now + timedelta(hours=HORIZON_H):
                out.append(t)
    return sorted(out)


def entries(led, brand, status=None):
    """This channel's YOUTUBE videos. Facebook reels share the brand key but
    are never YouTube uploads, so they are excluded here: counting a rendered
    reel as a ready video would put a 9:16 file on the YouTube channel."""
    return [v for v in led["videos"].values()
            if v["brand"] == brand and v.get("fmt") != "reel"
            and (status is None or v["status"] == status)]


def drop_lost_builds(led: dict, dry_run=False) -> list:
    """Forget built videos and reels whose files are gone from disk.

    A `built` entry whose folder was deleted would otherwise be picked as the
    next upload on every run and fail with FileNotFoundError, blocking its
    channel for good. Dropping the entry puts the game back in the queue; its
    engine analysis is cached, so the re-render only costs a few minutes.
    """
    lost = [k for k, v in led["videos"].items()
            if v["status"] == "built" and v.get("dir")
            and not all((ROOT / v["dir"] / f).is_file() for f in ("video.mp4", "meta.json"))]
    for key in lost:
        log.warning("%s: files missing from %s — back in the queue for a re-render",
                    key, led["videos"][key]["dir"])
        if not dry_run:
            del led["videos"][key]
    if lost and not dry_run:
        publisher.save_ledger(led)
    return lost


def build_next(led: dict, brand: str, dry_run: bool) -> dict | None:
    used = publisher.used_game_ids(led)
    tries = 0
    for entry in catalog.for_brand(brand):
        if entry["id"] in used:
            continue
        if dry_run:
            log.info("[%s] would render %s", brand, entry["id"])
            return None
        tries += 1
        key = f"{entry['id']}_{brand}"
        log.info("[%s] rendering %s", brand, entry["id"])
        try:
            meta = render.build(entry, brand=brand, log=lambda s: log.info("[%s] %s", brand, s.strip()))
        except render.DullGame as e:
            led["videos"][key] = {"game": entry["id"], "brand": brand, "status": "dull",
                                  "at": _now(), "note": str(e)}
            publisher.save_ledger(led)
            log.info("[%s] skipped dull game %s", brand, entry["id"])
            if tries >= MAX_TRIES:
                return None
            continue
        except Exception as e:
            led["videos"][key] = {"game": entry["id"], "brand": brand, "status": "failed",
                                  "at": _now(), "error": f"{e.__class__.__name__}: {e}"[:400]}
            publisher.save_ledger(led)
            log.error("[%s] render failed for %s: %s\n%s", brand, entry["id"], e, traceback.format_exc())
            if tries >= MAX_TRIES:
                return None
            continue
        rec = {"game": entry["id"], "brand": brand, "status": "built", "at": _now(),
               "dir": str((C.OUTPUT_DIR / f"{entry['id']}_{brand}").relative_to(ROOT)),
               "duration_s": meta["duration_s"]}
        led["videos"][key] = rec
        publisher.save_ledger(led)
        return rec
    log.warning("[%s] catalogue exhausted — rebuild it with: python make_longform.py --catalog", brand)
    return None


def prefetch(led: dict, brand: str, ahead: int, time_budget_s: float, dry_run=False) -> int:
    """Run the engine on this channel's next `ahead` games before they are due.

    Analysis is the slow half of a new video, and it is cached per game, so
    doing it in advance makes the render on the day about 2 minutes. It also
    finds dull auto-picked games early: they are marked `dull` here, so the
    daily run never spends its time on them. Stops at `time_budget_s`.
    """
    from longform import engine, games
    used = publisher.used_game_ids(led)
    t0 = time.time()
    done = 0
    for entry in catalog.for_brand(brand):
        if done >= ahead or time.time() - t0 > time_budget_s:
            break
        if entry["id"] in used:
            continue
        g = games.load(entry)
        cached = engine.is_cached(g)
        if dry_run:
            log.info("[%s] prefetch %s (%s)", brand, entry["id"], "cached" if cached else "needs engine")
            done += 1
            continue
        if not cached:
            log.info("[%s] prefetch: analysing %s", brand, entry["id"])
        pos = engine.analyse(g, log=lambda s: None)
        judg = engine.judge(g, pos, games.book_depth(g["start_fen"], g["moves"]))
        if entry.get("source") == "scored" and not render.interesting(judg):
            led["videos"][f"{entry['id']}_{brand}"] = {
                "game": entry["id"], "brand": brand, "status": "dull", "at": _now(),
                "note": "prefetch: no brilliant move, blunder or mate"}
            publisher.save_ledger(led)
            log.info("[%s] prefetch: %s is dull — skipped for good", brand, entry["id"])
            continue
        done += 1
    return done


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_brand(led: dict, brand: str, now: datetime, dry_run: bool, upload: bool):
    account = C.BRANDS[brand]["account"]
    if not accounts.is_enabled(account):
        log.info("[%s] account %s is not enabled — skipped", brand, account)
        return
    # Only a video still scheduled holds its slot; a withdrawn or cancelled
    # one frees it for the next run to fill.
    taken = {v["publish_at"] for v in entries(led, brand, "scheduled") if v.get("publish_at")}
    for slot in slots(brand, now):
        at = slot.strftime("%Y-%m-%dT%H:%M:%SZ")
        if at in taken:
            continue
        ready = sorted(entries(led, brand, "built"), key=lambda v: v["at"])
        rec = ready[0] if ready else build_next(led, brand, dry_run)
        if rec is None:
            if not dry_run:
                log.error("[%s] nothing to schedule for %s", brand, at)
            continue
        pkt = slot.astimezone(ZoneInfo("Asia/Karachi")).strftime("%a %H:%M PKT")
        if dry_run or not upload:
            log.info("[%s] would schedule %s for %s (%s)", brand, rec["game"], at, pkt)
            continue
        try:
            res = publisher.upload(ROOT / rec["dir"], brand, slot, led, log=log.info)
        except Exception as e:
            rec["last_error"] = f"{e.__class__.__name__}: {e}"[:400]
            publisher.save_ledger(led)
            log.error("[%s] upload failed for %s: %s", brand, rec["game"], e)
            return                       # do not burn the next slot's video on the same error
        rec.update(res, status="scheduled", uploaded_at=_now())
        rec.pop("last_error", None)
        publisher.save_ledger(led)
        log.info("[%s] scheduled %s -> https://youtu.be/%s at %s (%s)",
                 brand, rec["game"], res["youtube_id"], at, pkt)

    # A video in reserve, so tomorrow's run only has to upload.
    if not dry_run and len(entries(led, brand, "built")) < RESERVE:
        build_next(led, brand, dry_run)


def verify_public(led: dict, now: datetime):
    """Confirm with YouTube that videos past their slot actually went public.

    publishAt is YouTube's job, and nothing else would notice if it silently
    did not happen. One videos.list call (1 unit) per channel, and only for
    videos whose slot passed at least 30 min ago and are not yet confirmed.
    """
    due = {}
    for key, v in led["videos"].items():
        if v.get("fmt") == "reel" or v["status"] != "scheduled" or v.get("public_confirmed"):
            continue
        at = datetime.strptime(v["publish_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if now - at > timedelta(minutes=30):
            due.setdefault(v["account"], []).append((key, v))
    for account, items in due.items():
        try:
            yt = publisher._client(account)
            resp = yt.videos().list(part="status", id=",".join(v["youtube_id"] for _, v in items)).execute()
        except Exception as e:
            log.warning("could not check public status for %s: %s", account, e)
            continue
        status = {it["id"]: it["status"]["privacyStatus"] for it in resp.get("items", [])}
        for key, v in items:
            s = status.get(v["youtube_id"], "missing")
            if s == "public":
                v["public_confirmed"] = _now()
                log.info("confirmed public: %s -> https://youtu.be/%s", key, v["youtube_id"])
            else:
                log.error("NOT PUBLIC after its slot: %s (%s) is %s — check YouTube Studio",
                          key, v["youtube_id"], s)
    publisher.save_ledger(led)


def cleanup(led: dict, now: datetime):
    for v in led["videos"].values():
        if v.get("fmt") == "reel":
            # A posted reel's file goes after KEEP_DAYS too.
            if v["status"] == "posted" and v.get("posted_at"):
                at = datetime.strptime(v["posted_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                mp4 = ROOT / v["dir"] / "video.mp4"
                if now - at > timedelta(days=KEEP_DAYS) and mp4.is_file():
                    mp4.unlink()
                    log.info("removed %s (posted %s)", mp4.relative_to(ROOT), v["posted_at"])
            continue
        if v["status"] != "scheduled" or not v.get("publish_at"):
            continue
        at = datetime.strptime(v["publish_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if now - at > timedelta(days=KEEP_DAYS):
            mp4 = ROOT / v["dir"] / "video.mp4"
            if mp4.is_file():
                mp4.unlink()
                log.info("removed %s (public since %s)", mp4.relative_to(ROOT), v["publish_at"])
            v["status"] = "published"
    publisher.save_ledger(led)


def write_status(led: dict, now: datetime):
    """A small machine-readable summary, for the dashboard to show."""
    out = {"updated": _now(), "channels": {}}
    for brand in C.BRANDS:
        vids = entries(led, brand)
        upcoming = sorted((v for v in vids if v["status"] == "scheduled" and v.get("publish_at", "") > _now()),
                          key=lambda v: v["publish_at"])
        out["channels"][brand] = {
            "account": C.BRANDS[brand]["account"],
            "slots_et": C.BRANDS[brand]["slots_et"],
            "upcoming": [{"game": v["game"], "title": v.get("title"), "publish_at": v["publish_at"],
                          "youtube_id": v.get("youtube_id")} for v in upcoming],
            "ready": len([v for v in vids if v["status"] == "built"]),
            "published": len([v for v in vids if v["status"] == "published"]),
            "queue_left": len([e for e in catalog.for_brand(brand)
                               if e["id"] not in publisher.used_game_ids(led)]),
        }
    fb_reels = [v for v in led["videos"].values() if v.get("fmt") == "reel"]
    last = max((v for v in fb_reels if v["status"] == "posted"), key=lambda v: v["posted_at"], default=None)
    out["facebook"] = {
        "account": C.FACEBOOK["account"],
        "enabled": C.FACEBOOK["enabled"],
        "slot_pkt": C.FACEBOOK["slot_pkt"],
        "ready": len([v for v in fb_reels if v["status"] == "built"]),
        "posted": len([v for v in fb_reels if v["status"] == "posted"]),
        "needs_check": [v["game"] for v in fb_reels if v["status"] == "check_page"],
        "last_posted": ({"game": last["game"], "title": last.get("title"), "posted_at": last["posted_at"],
                         "fb_id": last.get("fb_id")} if last else None),
    }
    STATUS.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    # Also into the dashboard's GitHub status repo, as its own file beside the
    # shorts' status.json (which is never written from here). Best-effort,
    # like every status_bridge write: no token, no network -> just skipped.
    try:
        from src import status_bridge
        status_bridge._put_with_retry("longform.json", out, "longform status")
    except Exception as e:
        log.warning("dashboard status push skipped: %s", e)


def low_priority():
    """Run below normal priority, so the laptop stays responsive.

    Windows hands BELOW_NORMAL on to child processes, so the ten Stockfish
    engines and ffmpeg inherit it too. Anything the owner is doing, and the
    shorts autopilot, takes the CPU first; the render just takes a bit longer.
    """
    if sys.platform == "win32":
        import ctypes
        BELOW_NORMAL_PRIORITY_CLASS = 0x4000
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                                BELOW_NORMAL_PRIORITY_CLASS)


def main():
    low_priority()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--brand", choices=sorted(C.BRANDS))
    ap.add_argument("--retry-thumbnail", metavar="GAME_BRAND", action="append", default=[],
                    help="set a scheduled video's local JPEG through the pinned YouTube channel token")
    ap.add_argument("--withdraw", metavar="GAME_BRAND", action="append", default=[],
                    help="delete a still-PRIVATE upload and put the video back in the queue "
                         "(e.g. kasparov-topalov-1999_tahachess); the next run re-uploads it")
    ap.add_argument("--cancel", metavar="GAME_BRAND", action="append", default=[],
                    help="like --withdraw, but the game is never used again")
    ap.add_argument("--prefetch", type=int, metavar="N",
                    help="only run the engine on each channel's next N games (no render, no upload)")
    ap.add_argument("--facebook", action="store_true",
                    help="post today's 9:16 reel to the Taha Chess TV Page (the FB task runs this); "
                         "with --dry-run it only says what it would post")
    args = ap.parse_args()
    setup_logging()

    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 3 * 3600:
        log.error("another run holds %s — exiting", LOCK)
        sys.exit(1)
    LOCK.write_text(_now(), encoding="utf-8")
    try:
        now = datetime.now(timezone.utc)
        led = publisher.load_ledger()
        drop_lost_builds(led, dry_run=args.dry_run)
        if args.prefetch:
            for brand in ([args.brand] if args.brand else sorted(C.BRANDS)):
                n = prefetch(led, brand, args.prefetch, time_budget_s=6 * 3600, dry_run=args.dry_run)
                log.info("[%s] prefetch: %d game(s) analysed ahead", brand, n)
            write_status(led, now)
            return
        if args.facebook:
            if not C.FACEBOOK["enabled"]:
                log.info("[fb] long-form Facebook posting is disabled in lfconfig.FACEBOOK")
                return
            try:
                facebook.prepare(led, log=log.info, dry_run=args.dry_run)   # normally done at 04:00
                facebook.post(led, log=log.info, dry_run=args.dry_run)
            except Exception as e:
                log.error("[fb] post failed: %s", e)
            write_status(led, now)
            return
        if args.retry_thumbnail:
            for key in args.retry_thumbnail:
                publisher.retry_thumbnail(led, key, log=log.info)
            return
        if args.withdraw or args.cancel:
            for key in args.withdraw + args.cancel:
                if key not in led["videos"]:
                    log.error("no ledger entry %r", key)
                    continue
                publisher.withdraw(led, key, log=log.info)   # refuses anything already public
                if key in args.cancel:
                    led["videos"][key]["status"] = "cancelled"
                    publisher.save_ledger(led)
                log.info("%s %s", "cancelled" if key in args.cancel else "withdrawn", key)
            write_status(led, now)
            return
        log.info("run start%s", " (dry run)" if args.dry_run else "")
        for brand in ([args.brand] if args.brand else sorted(C.BRANDS)):
            run_brand(led, brand, now, args.dry_run, upload=not args.no_upload)
        if C.FACEBOOK["enabled"] and not args.brand:
            try:
                # Render tomorrow morning's reel now, while the machine is idle;
                # the FB task then only has to post it.
                facebook.prepare(led, log=log.info, dry_run=args.dry_run)
            except Exception as e:
                log.error("[fb] reel render failed: %s\n%s", e, traceback.format_exc())
        if not args.dry_run:
            verify_public(led, now)
            cleanup(led, now)
            # Keep the engine a few games ahead, so the day a game is due its
            # video only needs a render. Bounded, so a run never drags on.
            for brand in ([args.brand] if args.brand else sorted(C.BRANDS)):
                try:
                    prefetch(led, brand, PREFETCH_AHEAD, time_budget_s=PREFETCH_BUDGET_S)
                except Exception as e:
                    log.warning("[%s] prefetch stopped: %s", brand, e)
        write_status(led, now)
        log.info("run end")
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
