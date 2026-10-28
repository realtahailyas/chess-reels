"""The long-form game as a 9:16 Facebook Reel on the Taha Chess TV Page.

Same content as the Taha Chess YouTube channel. The game that went public
there last night is re-cut 9:16 (frame_vertical.py) and posted to the Page
the next morning. The engine analysis is cached, so a reel only costs a
render, about 2-3 minutes.

Posting reuses the shorts' Facebook path unchanged:
src.publisher.post_facebook(), which drives Meta Business Suite's reel
composer with Playwright from ChessReel's own signed-in Chrome profile. It
deselects the Instagram crosspost, refuses to post on the Jarvis profile, and
recovers the reel id afterwards. The composer only offers "Share now", so a
reel goes out live when this runs. That is why it has its own task time.

Two rules protect the shorts, which use the same Chrome profile:
  * wait while the shorts autopilot holds its lock (publish.lock);
  * at most one long-form reel per PKT day, so the retry trigger never
    double-posts.
"""

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config
from longform import catalog, metadata, render
from longform import lfconfig as C
from longform import publisher

PKT = ZoneInfo("Asia/Karachi")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reels(led, status=None):
    return [v for v in led["videos"].values()
            if v.get("fmt") == "reel" and (status is None or v["status"] == status)]


def prepare(led: dict, log=print, dry_run=False) -> dict | None:
    """Render the reel for the next game, if one is not already waiting.

    The next game is the oldest one from the FB brand's YouTube queue that
    has a YouTube upload (scheduled or published) and no reel yet. So
    Facebook always follows YouTube, and it never posts a game YouTube did
    not also get.
    """
    fb = C.FACEBOOK
    if reels(led, "built"):
        return None
    done = {v["game"] for v in reels(led)}
    candidates = sorted(
        (v for v in led["videos"].values()
         if v.get("brand") == fb["brand"] and v.get("fmt") != "reel"
         and v["status"] in ("scheduled", "published") and v["game"] not in done),
        key=lambda v: v.get("publish_at", ""))
    if not candidates:
        log("[fb] no YouTube game waiting for a reel")
        return None
    game = candidates[0]["game"]
    entry = next((e for e in catalog.load() if e["id"] == game), None)
    if entry is None:
        log(f"[fb] {game} is no longer in the catalogue")
        return None
    if dry_run:
        log(f"[fb] would render the reel for {game}")
        return None
    log(f"[fb] rendering reel for {game}")
    meta = render.build(entry, brand=fb["brand"], fmt="reel", log=lambda s: log(f"[fb] {s.strip()}"))
    key = f"{game}_{fb['brand']}_reel"
    rec = {"game": game, "brand": fb["brand"], "fmt": "reel", "status": "built", "at": _now(),
           "dir": str((C.OUTPUT_DIR / key).relative_to(config.ROOT)), "duration_s": meta["duration_s"]}
    led["videos"][key] = rec
    publisher.save_ledger(led)
    return rec


def posted_today(led) -> bool:
    today = datetime.now(PKT).date().isoformat()
    return any(v.get("posted_pkt_date") == today for v in reels(led))


def _wait_for_shorts(log, max_wait_s=1200) -> bool:
    """True once the shorts autopilot is not mid-run (it shares the profile)."""
    lock = config.PUBLISH_LOCK
    waited = 0
    while lock.exists() and time.time() - lock.stat().st_mtime < config.PUBLISH_LOCK_MAX_AGE_HOURS * 3600:
        if waited >= max_wait_s:
            return False
        if waited == 0:
            log("[fb] shorts autopilot is running — waiting for it to finish")
        time.sleep(30)
        waited += 30
    return True


def post(led: dict, log=print, dry_run=False) -> dict | None:
    """Post the oldest rendered reel to the Taha Chess TV Page, once per day."""
    from src import publisher as shorts_pub

    fb = C.FACEBOOK
    if posted_today(led):
        log("[fb] today's reel is already posted")
        return None
    ready = sorted(reels(led, "built"), key=lambda v: v["at"])
    if not ready:
        log("[fb] no reel rendered — nothing to post")
        return None
    rec = ready[0]
    # Facebook follows YouTube: never post a game before its YouTube video is
    # public, or the Page would spoil tonight's upload.
    yt = led["videos"].get(f"{rec['game']}_{fb['brand']}", {})
    if yt.get("publish_at", "9999") > _now():
        log(f"[fb] {rec['game']} is not public on YouTube until {yt.get('publish_at')} — waiting")
        return None
    out_dir = config.ROOT / rec["dir"]
    md = metadata.for_dir(out_dir)
    caption = metadata.fb_caption(md["meta"])
    if dry_run:
        log(f"[fb] would post {rec['game']}: {md['title']}")
        return None
    if not _wait_for_shorts(log):
        raise RuntimeError("shorts autopilot still holds publish.lock after 20 min — try the next trigger")

    # A 7-minute reel uploads and processes slower than a 20-second short, so
    # the composer gets a longer budget. This changes the value for THIS
    # process only; the shorts read config fresh in their own process.
    config.BROWSER_TIMEOUT_SECONDS = max(config.BROWSER_TIMEOUT_SECONDS, fb["timeout_s"])
    log(f"[fb] posting {rec['game']} to {fb['account']} (dry run: {config.BROWSER_DRY_RUN})")
    rec["attempted_at"] = _now()
    publisher.save_ledger(led)
    try:
        reel_id = shorts_pub.post_facebook(out_dir / "video.mp4", caption,
                                           account=fb["account"], title=md["title"])
    except Exception as e:
        msg = f"{e.__class__.__name__}: {e}"[:400]
        # A timeout means Share may already have been clicked: do NOT retry by
        # itself, or the Page gets the same reel twice. A person checks it.
        rec["status"] = "check_page" if "timed out" in msg else "built"
        rec["last_error"] = msg
        publisher.save_ledger(led)
        raise
    rec.update(status="posted", fb_id=reel_id, posted_at=_now(),
               posted_pkt_date=datetime.now(PKT).date().isoformat(), title=md["title"])
    rec.pop("last_error", None)
    publisher.save_ledger(led)
    log(f"[fb] posted {rec['game']} -> {reel_id}")
    return rec
