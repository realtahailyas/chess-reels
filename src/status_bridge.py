"""Async status/control bridge between this laptop and the Vercel dashboard.

The laptop can't accept inbound connections, so a private GitHub repo
(config.GITHUB_STATUS_REPO) stands in for a server:

  - history.json  append-only event log, written incrementally during a
                   publish.py run (one entry per platform publish/comment
                   attempt) — the source of truth for Logs/Publishing History.
  - status.json    a full snapshot, REBUILT FROM SCRATCH at the end of every
                   publish.py run and every watcher.py tick (from the local
                   ledger + history.json + machine facts) — what the
                   dashboard's Overview/Queue/System Health pages read.
  - control.json   written by the dashboard's Vercel API routes, read here to
                   pick up pause/resume/run-now/retry commands.

Every public function is best-effort: a GitHub outage or missing token must
never break real publishing, so failures are caught and logged, never raised,
mirroring publish.py's own notify() pattern.
"""

import base64
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import config
from src import accounts as accounts_mod
from src import queue as ledger

log = logging.getLogger("publish.status_bridge")

API_ROOT = "https://api.github.com"

# Commits written through the Contents API are attributed to a bot identity,
# not the token owner, so automated status/CDN writes stay off the owner's
# contribution graph.
BOT_IDENTITY = {"name": "chessreel-bot", "email": "chessreel-bot@users.noreply.github.com"}

STATUS_FILE = "status.json"
HISTORY_FILE = "history.json"
CONTROL_FILE = "control.json"
ANALYTICS_FILE = "analytics.json"
ACCOUNT_FILE = "account.json"

_EMPTY_HISTORY = {"entries": []}
# `paused_reason` distinguishes a person pressing Pause from the pipeline
# stopping itself because it ran out of built reels. They look identical on a
# status board otherwise, and they call for opposite responses — one wants a
# Resume, the other wants new content generated first.
_EMPTY_CONTROL = {
    "paused": False, "paused_reason": None,
    "command": None, "command_id": None, "issued_at": None,
}


def _token() -> str:
    return os.environ.get("GITHUB_STATUS_TOKEN", "")


def _enabled() -> bool:
    return bool(_token() and config.GITHUB_STATUS_REPO)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_file(filename: str):
    """Return (parsed_json_or_None, sha_or_None). Never raises."""
    url = f"{API_ROOT}/repos/{config.GITHUB_STATUS_REPO}/contents/{filename}"
    try:
        resp = requests.get(
            url, headers=_headers(),
            params={"ref": config.GITHUB_STATUS_BRANCH}, timeout=20,
        )
    except requests.RequestException as exc:
        log.warning("status_bridge: GET %s failed: %s", filename, exc)
        return None, None

    if resp.status_code == 404:
        return None, None
    if resp.status_code != 200:
        log.warning("status_bridge: GET %s -> %s: %s", filename, resp.status_code, resp.text[:200])
        return None, None

    body = resp.json()
    try:
        content = base64.b64decode(body["content"]).decode("utf-8")
        return json.loads(content), body.get("sha")
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("status_bridge: %s unparseable: %s", filename, exc)
        return None, body.get("sha")


def _put_file(filename: str, data: dict, message: str):
    """Write filename to the status repo once. Never raises.

    Returns (ok, status_code). A 409 means the sha this call fetched was
    already stale by the time the PUT landed — GitHub's Contents API can lag
    briefly right after this same process wrote the same file moments
    earlier (e.g. several record_event() calls back-to-back within one
    publish.py run). Callers that can safely redo their write on a fresh
    fetch should retry on 409 — see _put_with_retry / record_event.
    """
    if not _enabled():
        log.debug("status_bridge: disabled (no GITHUB_STATUS_TOKEN/REPO), skipping %s", filename)
        return False, None

    url = f"{API_ROOT}/repos/{config.GITHUB_STATUS_REPO}/contents/{filename}"
    _, sha = _get_file(filename)
    content_b64 = base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("ascii")
    body = {"message": message, "content": content_b64, "branch": config.GITHUB_STATUS_BRANCH,
            "author": BOT_IDENTITY, "committer": BOT_IDENTITY}
    if sha:
        body["sha"] = sha

    try:
        resp = requests.put(url, headers=_headers(), json=body, timeout=20)
    except requests.RequestException as exc:
        log.warning("status_bridge: PUT %s failed: %s", filename, exc)
        return False, None

    if resp.status_code not in (200, 201):
        log.warning("status_bridge: PUT %s -> %s: %s", filename, resp.status_code, resp.text[:200])
        return False, resp.status_code
    return True, resp.status_code


def _put_with_retry(filename: str, data: dict, message: str, retries: int = 3) -> bool:
    """_put_file with retry-on-409, reusing the same (already-final) data —
    correct for status.json, which is rebuilt from the ledger from scratch
    each call and never depends on what was there before."""
    for attempt in range(retries + 1):
        ok, status = _put_file(filename, data, message)
        if ok:
            return True
        if status != 409 or attempt == retries:
            return False
        time.sleep(0.5 * (attempt + 1))
    return False


# ── control.json (dashboard -> laptop) ──────────────────────────────────────

def get_control() -> dict:
    if not _enabled():
        return dict(_EMPTY_CONTROL)
    data, _ = _get_file(CONTROL_FILE)
    if not isinstance(data, dict):
        return dict(_EMPTY_CONTROL)
    out = dict(_EMPTY_CONTROL)
    out.update(data)
    return out


def is_paused() -> bool:
    return bool(get_control().get("paused"))


def pause_for_content_exhaustion() -> bool:
    """Stop the autopilot and record why. Returns True if the pause landed.

    Writes the same control.json the dashboard writes, so the stop shows up
    everywhere a manual pause would — except it carries a reason, which is
    what lets the Overview say "out of content" instead of the much less
    useful "someone paused this". Never raises: failing to record the stop
    must not turn into a crash on top of an already-empty queue.
    """
    for attempt in range(4):
        control = get_control()
        if control.get("paused"):
            return False
        control["paused"] = True
        control["paused_reason"] = "content_exhausted"
        control["paused_at"] = _now()
        ok, status = _put_file(CONTROL_FILE, control, "autopause: content exhausted")
        if ok:
            record_event("autopaused", reason="content_exhausted")
            return True
        if status != 409:
            log.warning("status_bridge: content-exhaustion autopause failed (status=%s)", status)
            return False
        time.sleep(0.5 * (attempt + 1))
    log.warning("status_bridge: content-exhaustion autopause gave up after 409 retries")
    return False


def clear_command(result: str = "done"):
    """After executing a dashboard command, clear it so it doesn't re-fire."""
    for attempt in range(4):
        control = get_control()
        control["command"] = None
        control["last_command_id"] = control.get("command_id")
        control["last_command_result"] = result
        control["last_command_at"] = _now()
        control["command_id"] = None
        ok, status = _put_file(CONTROL_FILE, control, "clear executed command")
        if ok or status != 409:
            return
        time.sleep(0.5 * (attempt + 1))


# ── history.json (append-only event log) ────────────────────────────────────

def record_event(event_type: str, **fields):
    """Append one event to history.json. puzzle_id/platform/error/etc go in fields.

    Re-fetches history.json fresh on each attempt (not just the sha) and
    re-appends the same entry, so a 409 — e.g. this same run already wrote
    fb/ig events moments earlier and GitHub's read-after-write lagged behind
    — can't silently drop a real event (this dropped a real YouTube publish
    from the dashboard once; see publish.py's 2026-08-22 15:02 log)."""
    if not _enabled():
        return

    entry = {"timestamp": _now(), "type": event_type}
    entry.update(fields)

    for attempt in range(4):
        data, _ = _get_file(HISTORY_FILE)
        if not isinstance(data, dict) or "entries" not in data:
            data = dict(_EMPTY_HISTORY)
        data["entries"] = data["entries"] + [entry]
        data["entries"] = data["entries"][-config.STATUS_HISTORY_MAX:]

        ok, status = _put_file(HISTORY_FILE, data, f"event: {event_type}")
        if ok:
            return
        if status != 409:
            log.warning("status_bridge: record_event(%s) failed (status=%s)", event_type, status)
            return
        time.sleep(0.5 * (attempt + 1))
    log.warning("status_bridge: record_event(%s) gave up after 409 retries", event_type)


def _recent_history(limit: int = 200) -> list:
    data, _ = _get_file(HISTORY_FILE)
    if not isinstance(data, dict):
        return []
    return data.get("entries", [])[-limit:]


# ── status.json (full snapshot, rebuilt each call) ──────────────────────────

# One task per brand — see scripts/setup_tchessapp_schedule.ps1 for why the
# second brand got its own rather than extra triggers on the first one.
TASK_NAMES = {
    "tahachesstv": "ChessReel Autopilot",
    "tchessapp": "ChessReel Autopilot (tchessapp)",
}


def _one_task_state(task_name: str) -> str:
    try:
        out = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if out.returncode != 0:
            return "not registered"
        for line in out.stdout.splitlines():
            if line.strip().lower().startswith("status:"):
                return line.split(":", 1)[1].strip()
        return "unknown"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable ({exc})"


def _task_scheduler_states() -> dict:
    """Every brand's task, so a brand that is enabled in .env but has no
    scheduled task — the exact state right after switching one on and
    forgetting to register its slots — is visible rather than silent."""
    return {
        name: _one_task_state(task)
        for name, task in TASK_NAMES.items()
        if name in config.ACCOUNTS
    }


def _task_scheduler_state() -> str:
    """The default brand's task state, kept as a plain string for the
    dashboard's existing System Health row."""
    return _one_task_state(TASK_NAMES[config.DEFAULT_ACCOUNT])


def _next_run_pkt(now: datetime) -> str:
    times_today = sorted(config.PUBLISH_TIMES_PKT)
    hm = now.strftime("%H:%M")
    for t in times_today:
        if t > hm:
            return f"{now.strftime('%Y-%m-%d')} {t}"
    tomorrow = now + timedelta(days=1)
    return f"{tomorrow.strftime('%Y-%m-%d')} {times_today[0]}"


def _account_blocks(history_entries: list, ledger_entries: list, eligible: list) -> list:
    """One block per brand: where it posts, when, how much of the queue is
    already claimed for it, and when it last actually posted.

    Built for every configured account, not just the enabled ones — a
    disabled brand still has posted reels and analytics behind it, and
    dropping it from the snapshot would make the dashboard look like that
    history never happened.
    """
    name_map = {"fb": "facebook", "ig": "instagram", "yt": "youtube", "tt": "tiktok"}
    today_str = datetime.now().strftime("%Y-%m-%d")
    blocks = []

    for name in accounts_mod.all_names():
        active = set(ledger.active_platforms(name))
        platforms = {}
        for p in accounts_mod.platform_ceiling(name):
            platforms[name_map.get(p, p)] = {
                "key": p,
                "handle": accounts_mod.handle(name, p),
                "publishing": p in active,
                # How this platform is published. Facebook is the odd one out —
                # it goes through Meta Business Suite's composer in a real
                # browser because the Graph API's Reels flow never worked for
                # these Pages. Worth surfacing: a browser path fails for
                # entirely different reasons (a Chrome profile held open by a
                # person, a moved selector) than an API one, and someone
                # reading a failure needs to know which kind they are looking
                # at before they start debugging.
                "via": "browser" if p in ("fb", "tt") else "api",
                "last_post_at": None,
            }

        last_post = None
        claimed = 0
        posted_today = 0
        for entry in ledger_entries:
            if accounts_mod.entry_account(entry) != name:
                continue
            if entry.get("status") == "pending":
                # Only entries explicitly stamped for this brand count as
                # "claimed" — the unstamped pool belongs to neither yet.
                if entry.get("account") == name:
                    claimed += 1
                continue
            if entry.get("status") != "posted" or not entry.get("posted_at"):
                continue
            if str(entry["posted_at"]).startswith(today_str):
                posted_today += 1
            if not last_post or entry["posted_at"] > last_post:
                last_post = entry["posted_at"]
            for p, key in name_map.items():
                if p in platforms_of(entry) and key in platforms:
                    if (platforms[key]["last_post_at"] or "") < entry["posted_at"]:
                        platforms[key]["last_post_at"] = entry["posted_at"]

        # history.json is best-effort and can drop an event (see below), so it
        # only ever moves a timestamp forward, never backwards.
        for e in history_entries:
            if e.get("type") != "published" or e.get("account") != name:
                continue
            key = name_map.get(e.get("platform"))
            if key in platforms and (platforms[key]["last_post_at"] or "") < e["timestamp"]:
                platforms[key]["last_post_at"] = e["timestamp"]
            if not last_post or e["timestamp"] > last_post:
                last_post = e["timestamp"]

        blocks.append({
            "name": name,
            "label": accounts_mod.label(name),
            "enabled": accounts_mod.is_enabled(name),
            "publish_times_pkt": accounts_mod.slots(name),
            "platforms": platforms,
            "claimed_queue": claimed,
            "eligible_now": sum(
                1 for e in eligible
                if e.get("account") == name or e.get("account") is None
            ) if accounts_mod.is_enabled(name) else 0,
            "posted_today": posted_today,
            "last_post_at": last_post,
        })
    return blocks


def platforms_of(entry: dict) -> set:
    """The platform keys this entry actually has a post id for. A failure or
    skip mark (config.NOT_A_POST_PREFIXES) completes the ledger entry but is
    not a post, so it is left out."""
    return {k for k, v in (entry.get("platforms") or {}).items()
            if v and not str(v).startswith(config.NOT_A_POST_PREFIXES)}


def _platform_health(history_entries: list, ledger_entries: list) -> dict:
    # ⚠️ `connected` and `publishing` are two different questions, and the
    # dashboard was only ever told the first. Facebook posting was paused on
    # 2026-09-01 while its page token stayed valid — so the panel would have
    # shown a healthy green "Connected" beside a platform that has silently
    # stopped receiving reels, which is the most misleading state a status
    # board can be in. `publishing` comes from the same flags publish.py
    # obeys, so the two cannot drift.
    active = set(ledger.active_platforms())
    health = {
        "facebook": {
            "connected": bool(os.environ.get("FB_PAGE_TOKEN")),
            "publishing": "fb" in active,
            "last_post_at": None,
        },
        "instagram": {
            "connected": bool(os.environ.get("IG_USER_ID")),
            "publishing": "ig" in active,
            "last_post_at": None,
        },
        "youtube": {
            "connected": os.path.exists(os.environ.get("YT_TOKEN_PATH", "")),
            "publishing": "yt" in active,
            "last_post_at": None,
        },
        # TikTok (tchessapp only, since 2026-09-29) is published through the
        # web uploader in Chrome profile TIKTOK_PROFILE_DIR, so "connected"
        # can only mean the profile exists; whether its session is still
        # signed in shows up as a failed publish, not here.
        "tiktok": {
            "connected": os.path.isdir(config.TIKTOK_PROFILE_DIR),
            "publishing": "tt" in set(ledger.active_platforms("tchessapp")),
            "via": "browser",
            "last_post_at": None,
        },
        "github_cdn": {
            "connected": bool(os.environ.get("GITHUB_TOKEN")),
            # Not a publishing target — it hosts the files Instagram pulls from.
            "publishing": None,
            "last_post_at": None,
        },
    }
    name_map = {"fb": "facebook", "ig": "instagram", "yt": "youtube", "tt": "tiktok"}
    for e in history_entries:
        if e.get("type") == "published" and e.get("platform") in name_map:
            health[name_map[e["platform"]]]["last_post_at"] = e["timestamp"]

    # history.json is best-effort (a transient GitHub write conflict can drop
    # an event — this happened for real on 2026-08-22, a successful YouTube
    # post showed as "never" on the dashboard). The ledger is the actual
    # source of truth, so a fully-posted entry must never be shadowed by a
    # missing history event.
    for entry in ledger_entries:
        if entry.get("status") != "posted" or not entry.get("posted_at"):
            continue
        platforms = entry.get("platforms") or {}
        for p, key in name_map.items():
            value = str(platforms.get(p) or "")
            if value.startswith(config.NOT_A_POST_PREFIXES):
                continue                       # a skipped post is not a post
            if value and (health[key]["last_post_at"] or "") < entry["posted_at"]:
                health[key]["last_post_at"] = entry["posted_at"]

    return health


def _load_meta_safe(video_path: str) -> dict:
    try:
        from pathlib import Path
        meta_path = Path(video_path).parent / "meta.json"
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def build_status(kind: str = "run", last_error: str = None, note: str = None) -> dict:
    """Assemble the full status.json snapshot from the ledger + history + machine facts."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    data = ledger.load()
    all_pending = ledger.pending()

    try:
        from publish import is_eligible, get_or_init_cutoff  # local import: avoid a cycle at module load
        cutoff = get_or_init_cutoff()
        eligible = [p for p in all_pending if is_eligible(p, cutoff)]
    except Exception:  # noqa: BLE001
        eligible = list(all_pending)

    # 🔴 THE PREVIEW HAS TO SIMULATE THE CLAIM, NOT LIST THE POOL TWICE.
    # Both brands draw from one shared pile of unstamped reels, so asking each
    # brand independently for "your next 3" returns the SAME three reels under
    # two names — a queue that shows a reel going out on both accounts is
    # exactly the thing this whole design exists to make impossible, and
    # showing it would teach the owner to distrust the page. Instead the day's
    # six slots are walked in time order and each one consumes an entry, the
    # same way the real runs will.
    slot_plan = sorted(
        (slot, name)
        for name in accounts_mod.enabled_names()
        for slot in accounts_mod.slots(name)
    )
    taken = set()
    queue = []
    for slot, name in slot_plan:
        pick = None
        for entry in eligible:
            pid = entry["puzzle_id"]
            if pid in taken:
                continue
            owner = entry.get("account")
            if owner is not None and owner != name:
                continue
            pick = entry
            break
        if pick is None:
            continue  # pool ran dry partway through the day — show fewer slots
        taken.add(pick["puzzle_id"])

        active = ledger.active_platforms(name)
        platforms = pick.get("platforms") or {}
        meta = _load_meta_safe(pick["video_path"])
        cap = meta.get("caption", {}) if meta else {}
        queue.append({
            "puzzle_id": pick["puzzle_id"],
            "video_path": pick["video_path"],
            "account": name,
            "account_label": accounts_mod.label(name),
            "scheduled_time_pkt": slot,
            "hook": cap.get("hook"),
            "caption": cap.get("caption"),
            "hashtags": cap.get("hashtags"),
            # Only this brand's own platforms — a tchessapp row must not show
            # an "FB …" pill for a Page that brand does not have.
            "platforms": {p: (platforms.get(p) is not None) for p in active},
            "status": "posted" if all(platforms.get(p) for p in active)
                       else ("partial" if any(platforms.get(p) for p in active) else "pending"),
        })

    posted_today = [
        p for p in data.get("pending", [])
        if p.get("status") == "posted" and str(p.get("posted_at", "")).startswith(today_str)
    ]

    history_entries = _recent_history(200)
    _success_type = {"publish_failed": "published", "comment_failed": "comment_posted"}
    failed_today = [
        e for e in history_entries
        if e.get("type") in _success_type and str(e.get("timestamp", "")).startswith(today_str)
        # A failure later resolved by a successful retry (same puzzle+platform,
        # later timestamp) isn't a current problem — exclude it so "Failed
        # Today" reflects what's actually still broken, not settled history.
        and not any(
            o.get("type") == _success_type[e["type"]]
            and o.get("puzzle_id") == e.get("puzzle_id")
            and o.get("platform") == e.get("platform")
            and o.get("timestamp", "") > e.get("timestamp", "")
            for o in history_entries
        )
    ]

    control = get_control()

    disk_free_gb = None
    try:
        disk_free_gb = round(shutil.disk_usage(str(config.ROOT.anchor)).free / (1024 ** 3), 1)
    except Exception:  # noqa: BLE001
        pass

    lock_active = config.PUBLISH_LOCK.exists()

    try:
        from publish import content_runway  # local import: avoid a cycle at module load
        runway = content_runway()
    except Exception as exc:  # noqa: BLE001 — a status snapshot must survive this
        log.warning("status_bridge: content runway unavailable: %s", exc)
        runway = None

    status = {
        "updated_at": _now(),
        "autopilot": {
            "enabled": not control.get("paused", False),
            "paused": bool(control.get("paused", False)),
            # "someone pressed pause" and "the pipeline ran out of reels" are
            # different problems with different fixes; the dashboard needs to
            # be able to tell them apart.
            "paused_reason": control.get("paused_reason"),
            "paused_at": control.get("paused_at"),
            "publish_times_pkt": config.PUBLISH_TIMES_PKT,
            "per_run_cap": config.PUBLISH_PER_RUN_CAP,
            "next_run_pkt": _next_run_pkt(now),
        },
        "today": {
            "date": today_str,
            "scheduled": len(queue),
            "published": len(posted_today),
            "failed": len(failed_today),
        },
        "queue": queue,
        "accounts": _account_blocks(history_entries, data.get("pending", []), eligible),
        "content": runway,
        "platform_health": _platform_health(history_entries, data.get("pending", [])),
        "system": {
            "kind": kind,
            "note": note,
            "last_error": last_error,
            "task_scheduler": _task_scheduler_state(),
            "task_scheduler_by_account": _task_scheduler_states(),
            "python_env": f"{platform.python_implementation()} {platform.python_version()} ({sys.executable})",
            "project_path": str(config.ROOT),
            "ledger_pending_count": len(all_pending),
            "ledger_posted_count": len(data.get("posted", [])),
            "eligible_count": len(eligible),
            "disk_free_gb": disk_free_gb,
            "lock_active": lock_active,
        },
    }
    if kind == "run":
        status["system"]["last_run_at"] = status["updated_at"]
    else:
        # status.json is fully rebuilt on every call, including watcher.py's
        # heartbeat every ~5min — without carrying this forward, the very
        # next heartbeat after a real run wipes last_run_at back to absent,
        # and the dashboard shows "Last successful run: never" almost always.
        prev, _ = _get_file(STATUS_FILE)
        if isinstance(prev, dict):
            prev_last_run = prev.get("system", {}).get("last_run_at")
            if prev_last_run:
                status["system"]["last_run_at"] = prev_last_run
    return status


def sync_status(kind: str = "run", last_error: str = None, note: str = None):
    """Rebuild and push status.json. Call once at the end of a publish.py run
    and once per watcher.py tick. Never raises."""
    if not _enabled():
        return
    try:
        status = build_status(kind=kind, last_error=last_error, note=note)
        _put_with_retry(STATUS_FILE, status, f"status: {kind}")
    except Exception as exc:  # noqa: BLE001 — a status push failing must never break publishing
        log.warning("status_bridge: sync_status failed: %s", exc)


# ── analytics.json (per-post FB/IG/YouTube metrics) ─────────────────────────

def _merge_analytics_entry(previous: dict, incoming: dict) -> dict:
    """Keep last successful platform values when a refresh fails.

    Success timestamps belong to each platform, not the entire batch.
    Errors exposed to the dashboard are deliberately generic: requests
    exception strings can contain access tokens in their URL.
    """
    merged = {**previous, **incoming}
    merged["posted_at"] = previous.get("posted_at") or incoming.get("posted_at")
    metrics = dict(previous.get("metrics") or {})
    for platform_name, value in (incoming.get("metrics") or {}).items():
        old = metrics.get(platform_name) or {}
        stamp = value.get("last_success_at") or incoming.get("fetched_at", "")
        old_stamp = old.get("last_success_at") or previous.get("fetched_at", "")
        if value.get("error"):
            if old and not old.get("error"):
                metrics[platform_name] = {
                    **old, "last_success_at": old_stamp,
                    "refresh_error": "Platform refresh failed; retaining last successful metrics",
                    "last_attempt_at": incoming.get("fetched_at"),
                }
            else:
                metrics[platform_name] = {"error": "Platform metrics unavailable", "last_attempt_at": incoming.get("fetched_at")}
        elif old.get("error") or not old or stamp >= old_stamp:
            metrics[platform_name] = {**value, "last_success_at": stamp}
            metrics[platform_name].pop("refresh_error", None)
    merged["metrics"] = metrics
    merged["fetched_at"] = max(previous.get("fetched_at", ""), incoming.get("fetched_at", ""))
    return merged


def _save_analytics(updates: dict, message: str) -> bool:
    """Read, merge, and write against the SAME SHA; re-merge on conflict.

    Never treat an unavailable catalogue as empty. Snapshot writers may
    replace status.json, but reporting data must survive failed reads and
    simultaneous writers.
    """
    for attempt in range(4):
        current, sha = _get_file(ANALYTICS_FILE)
        if not isinstance(current, dict) or not current or not sha:
            log.warning("analytics: refusing write because catalogue read was unavailable or empty")
            return False
        merged = dict(current)
        for pid, entry in updates.items():
            merged[pid] = _merge_analytics_entry(current.get(pid, {}), entry)
        body = {
            "message": message, "branch": config.GITHUB_STATUS_BRANCH, "sha": sha,
            "author": BOT_IDENTITY, "committer": BOT_IDENTITY,
            "content": base64.b64encode(json.dumps(merged, indent=2).encode()).decode("ascii"),
        }
        resp = requests.put(
            f"{API_ROOT}/repos/{config.GITHUB_STATUS_REPO}/contents/{ANALYTICS_FILE}",
            headers=_headers(), json=body, timeout=20,
        )
        if resp.status_code in (200, 201):
            backup = config.DATA_DIR / "analytics-last-good.json"
            temporary = backup.with_suffix(".tmp")
            temporary.write_text(json.dumps(merged, indent=2), encoding="utf-8")
            temporary.replace(backup)
            return True
        if resp.status_code != 409:
            log.warning("analytics: write failed (HTTP %s)", resp.status_code)
            return False
        time.sleep(0.5 * (attempt + 1))
    return False


def sync_analytics():
    """Refresh analytics for a handful of recently-posted entries and push.

    Self-pacing across watcher.py ticks: only entries posted within
    config.ANALYTICS_LOOKBACK_DAYS are candidates, only ones whose last fetch
    is older than config.ANALYTICS_REFRESH_COOLDOWN_MIN get refreshed, and at
    most config.ANALYTICS_MAX_PER_TICK per call — a full sweep of the whole
    recent-posts window happens gradually over several ticks, not in one
    burst that could trip a platform rate limit. Never raises.
    """
    if not _enabled():
        return
    try:
        from src import analytics as analytics_mod

        existing, _ = _get_file(ANALYTICS_FILE)
        if not isinstance(existing, dict) or not existing:
            log.warning("analytics: catalogue unavailable; skipping refresh to preserve history")
            return

        now = datetime.now(timezone.utc)
        cutoff_dt = now - timedelta(days=config.ANALYTICS_LOOKBACK_DAYS)
        cooldown = timedelta(minutes=config.ANALYTICS_REFRESH_COOLDOWN_MIN)

        recent = [
            e for e in ledger.load().get("pending", [])
            if e.get("status") == "posted" and str(e.get("posted_at", "")) >= cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        ]

        due = []
        for entry in recent:
            pid = entry["puzzle_id"]
            last = existing.get(pid, {}).get("fetched_at")
            if last:
                try:
                    last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    if now - last_dt < cooldown:
                        continue
                except ValueError:
                    pass
            due.append(entry)

        # The old ledger order is build order, not posting order. Once the
        # queue grew, every tick spent its budget walking the oldest entries
        # first, while the newest posts stayed visibly stuck at "not fetched
        # yet". Live analytics must win over historical backfill: fetch never
        # seen entries first, then refresh the oldest stale entries so the
        # catalogue still converges without starving today's posts.
        # Stable two-pass sort: newest posts first within each group, while
        # never-fetched entries remain ahead of stale refreshes.
        due.sort(key=lambda e: str(e.get("posted_at", "")), reverse=True)
        due.sort(key=lambda e: existing.get(e["puzzle_id"], {}).get("fetched_at") or "")
        due = due[: config.ANALYTICS_MAX_PER_TICK]

        if not due:
            return

        refreshed = 0
        updates = {}
        for entry in due:
            # googleapiclient's execute() does not inherit requests' timeout.
            # A stalled YouTube/Meta call used to hold the watcher open until
            # the next scheduled tick, so Task Scheduler ignored every new
            # analytics run while the dashboard stayed stale. Keep the fetch
            # bounded; an unfinished entry remains due and is retried next
            # tick instead of poisoning the whole batch.
            result = []
            failure = []

            def _fetch():
                try:
                    result.append(analytics_mod.fetch_for_entry(entry))
                except Exception as exc:  # noqa: BLE001
                    failure.append(exc)

            import threading
            worker = threading.Thread(target=_fetch, name=f"analytics-{entry['puzzle_id']}", daemon=True)
            worker.start()
            worker.join(timeout=75)
            if worker.is_alive():
                log.warning("[%s] analytics fetch timed out; leaving it due for retry", entry["puzzle_id"])
                continue
            if failure:
                log.warning("[%s] analytics fetch failed; leaving it due for retry: %s", entry["puzzle_id"], failure[0])
                continue
            if not result:
                continue
            metrics = result[0]
            updates[entry["puzzle_id"]] = {
                "fetched_at": _now(),
                # Keep the immutable publication timestamp beside the metrics.
                # history.json is an operational event log and can be pruned;
                # analytics.json must remain sufficient for honest all-time and
                # date-range dashboard totals.
                "posted_at": entry.get("posted_at"),
                "account": accounts_mod.entry_account(entry),
                "metrics": metrics,
            }
            refreshed += 1

        if refreshed:
            _save_analytics(updates, f"analytics: refreshed {refreshed} entr{'y' if refreshed == 1 else 'ies'}")
    except Exception as exc:  # noqa: BLE001 — analytics must never break publishing/watching
        log.warning("status_bridge: sync_analytics failed: %s", exc)


def sync_account_stats():
    """Refresh page/account-level follower counts. Cheap (2 calls) but still
    cooldown-gated on ANALYTICS_REFRESH_COOLDOWN_MIN — follower counts don't
    need per-tick freshness. Never raises."""
    if not _enabled():
        return
    try:
        from src import analytics as analytics_mod

        existing, _ = _get_file(ACCOUNT_FILE)
        if not isinstance(existing, dict):
            existing = {}

        last = existing.get("fetched_at")
        if last:
            try:
                last_dt = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last_dt < timedelta(minutes=config.ANALYTICS_REFRESH_COOLDOWN_MIN):
                    return
            except ValueError:
                pass

        # Per brand, keyed by account name. The flat top-level keys are kept
        # alongside for tahachesstv so anything still reading the old shape
        # (an older dashboard deploy, mid-rollout) keeps working.
        per_account = {}
        for name in accounts_mod.enabled_names():
            try:
                per_account[name] = analytics_mod.fetch_account_stats(account=name)
            except Exception as exc:  # noqa: BLE001
                log.warning("account stats: %s failed: %s", name, exc)
                per_account[name] = {"error": str(exc)}

        legacy = per_account.get(config.DEFAULT_ACCOUNT, {})
        _put_with_retry(
            ACCOUNT_FILE,
            {"fetched_at": _now(), "accounts": per_account,
             **{k: v for k, v in legacy.items() if k != "error"}},
            "account stats refresh",
        )
    except Exception as exc:  # noqa: BLE001 — account stats must never break publishing/watching
        log.warning("status_bridge: sync_account_stats failed: %s", exc)
