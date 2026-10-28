"""Local JSON ledger for dedupe and post tracking.

A puzzle id is recorded only after its video encodes and verifies, so a crash
mid-build never burns a puzzle. Writes go to a temp file and are moved into
place, so an interrupted write cannot corrupt the ledger.
"""

import json
import os
import tempfile
from datetime import datetime, timezone

import config
from src import accounts

_EMPTY = {"posted": [], "pending": []}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path=None) -> dict:
    """Read the ledger, tolerating a missing or corrupt file."""
    path = path or config.POSTED_JSON
    if not path.exists():
        return json.loads(json.dumps(_EMPTY))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_EMPTY))

    # Older runs stored a bare list of ids.
    if isinstance(data, list):
        return {"posted": [str(x) for x in data], "pending": []}
    data.setdefault("posted", [])
    data.setdefault("pending", [])
    return data


def save(data: dict, path=None):
    """Write the ledger atomically."""
    path = path or config.POSTED_JSON
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def posted_ids(path=None) -> set:
    return set(load(path).get("posted", []))


def record_success(puzzle, video_path, caption_path, duration, path=None):
    """Mark a puzzle posted and queue its artefacts. Call only after verify."""
    data = load(path)
    pid = puzzle["id"]
    if pid not in data["posted"]:
        data["posted"].append(pid)

    data["pending"] = [p for p in data["pending"] if p.get("puzzle_id") != pid]
    data["pending"].append({
        "puzzle_id": pid,
        "video_path": str(video_path),
        "caption_path": str(caption_path),
        "created_at": _now(),
        "status": "pending",
        "rating": puzzle.get("rating"),
        "theme": puzzle.get("theme_label"),
        "duration": round(float(duration), 2),
        "platforms": {"fb": None, "ig": None, "yt": None},
    })
    save(data, path)
    return data


def mark_status(puzzle_id: str, status: str, path=None):
    """Update a pending entry's status, e.g. to 'posted'."""
    data = load(path)
    for entry in data["pending"]:
        if entry.get("puzzle_id") == puzzle_id:
            entry["status"] = status
            if status == "posted":
                entry["posted_at"] = _now()
    save(data, path)
    return data


def mark_platform(puzzle_id: str, platform: str, post_id: str, path=None):
    """Record a successful publish to one platform ('fb' / 'ig' / 'yt' / 'tt').

    A partial failure (e.g. YT posts fine, IG times out) must not re-post to
    platforms that already succeeded, so each platform is tracked
    independently. Once every ACTIVE platform is set, the entry's overall
    status flips to 'posted' the same way mark_status does.

    🔴 COMPLETION IS MEASURED AGAINST `active_platforms()`, NOT A HARDCODED
    ("fb","ig","yt"). This line read `("fb", "ig", "yt")` and it silently broke
    the moment Facebook was paused: an entry posted to IG and YouTube could
    never satisfy `fb`, so it stayed `pending` forever, never got a
    `posted_at`, and `status_bridge.sync_analytics()` — which only considers
    entries with status "posted" — skipped it. The visible symptom was a reel
    stuck on "not fetched yet" in the dashboard with no error anywhere. Any
    platform toggle has to move this test with it.
    """
    data = load(path)
    for entry in data["pending"]:
        if entry.get("puzzle_id") == puzzle_id:
            # Per ENTRY, not per install: tchessapp entries are complete at
            # ig+yt, tahachesstv's at fb+ig+yt. A single global active list
            # would leave every app-brand entry permanently short an "fb" it
            # can never have, i.e. exactly the never-flips-to-posted bug the
            # docstring above describes, reintroduced one layer up.
            active = active_platforms(accounts.entry_account(entry))
            entry.setdefault("platforms", {p: None for p in active})
            entry["platforms"][platform] = post_id
            if all(entry["platforms"].get(p) for p in active):
                entry["status"] = "posted"
                entry["posted_at"] = _now()
    save(data, path)
    return data


def record_platform_failure(puzzle_id: str, platform: str, path=None):
    """Count one failed publish of this entry to this platform.

    Returns the skip mark once the count reaches config.PLATFORM_MAX_FAILURES
    (the platform slot is then filled with it, so the entry can complete),
    otherwise None. See config.PLATFORM_MAX_FAILURES for why this exists.
    """
    data = load(path)
    count = None
    for entry in data["pending"]:
        if entry.get("puzzle_id") == puzzle_id:
            fails = entry.setdefault("fail_counts", {})
            fails[platform] = count = int(fails.get(platform, 0)) + 1
    if count is None:
        return None
    save(data, path)
    if count < config.PLATFORM_MAX_FAILURES:
        return None
    mark = f"{config.PUBLISH_SKIPPED_PREFIX}{count}x:{_now()}"
    mark_platform(puzzle_id, platform, mark, path=path)
    return mark


def active_platforms(account: str = None) -> tuple:
    """The platforms one account actually publishes to.

    Starts from that brand's ceiling (config.ACCOUNTS[...]["platforms"]) and
    subtracts whatever the global flags have switched off, so an account can
    only ever lose a platform here, never gain one — tchessapp has no
    Facebook Page, and no value of FACEBOOK_ENABLED may invent one for it.

    ⚠️ "tt" is gated on config.TIKTOK_ENABLED rather than being listed
    unconditionally, because this function is what decides whether an entry
    still has work left. Adding a platform here retroactively marks every
    pending entry as owing that platform a post — which is correct, but it
    means switching TikTok on releases the whole backlog into the inbox one
    run at a time. That should be a decision, not a side effect of a deploy.
    """
    ceiling = accounts.platform_ceiling(account)
    out = []
    if "fb" in ceiling and config.FACEBOOK_ENABLED:
        out.append("fb")
    out += [p for p in ("ig", "yt") if p in ceiling]
    if "tt" in ceiling and config.TIKTOK_ENABLED:
        out.append("tt")
    return tuple(out)


def assign_account(puzzle_id: str, account: str, path=None) -> bool:
    """Claim one unassigned entry for one brand, permanently.

    🔴 THIS IS THE WHOLE UNIQUENESS GUARANTEE. The two accounts must never
    post the same reel, and the way that is enforced is that a reel is stamped
    with an owner the first time a run picks it up, before anything is posted.
    After that no other account's run will even consider it (see
    `pending(account=...)`), so "did the other brand already use this one?" is
    never a question anybody has to re-derive from captions, files or history.

    Returns False and changes nothing if the entry is already stamped —
    re-stamping is the one operation that could hand a reel to both brands, so
    it is refused rather than allowed to overwrite.
    """
    data = load(path)
    for entry in data["pending"]:
        if entry.get("puzzle_id") != puzzle_id:
            continue
        current = entry.get("account")
        if current and current != account:
            return False
        if current == account:
            return True
        entry["account"] = account
        entry["assigned_at"] = _now()
        save(data, path)
        return True
    return False


def pending(path=None, account: str = None, include_unassigned: bool = True):
    """Entries still waiting to be published.

    With no `account`, this is every pending entry — the historical meaning,
    which the dashboard's backlog counts and watcher.py's retry sweep still
    want.

    With an `account`, it is that brand's own queue: entries already stamped
    for it, plus (unless `include_unassigned` is False) the shared unclaimed
    pool both brands draw from. Entries stamped for the OTHER brand are never
    returned — that exclusion is what stops a reel being posted twice.
    """
    items = [p for p in load(path).get("pending", []) if p.get("status") == "pending"]
    if account is None:
        return items
    out = []
    for entry in items:
        owner = entry.get("account")
        if owner == account:
            out.append(entry)
        elif owner is None and include_unassigned:
            out.append(entry)
    return out


def due_platforms(entry: dict) -> list:
    """Which of this entry's own account's platforms still need a publish call."""
    active = active_platforms(accounts.entry_account(entry))
    platforms = entry.get("platforms") or {p: None for p in active}
    return [p for p in active if not platforms.get(p)]
