"""TikTok publishing through TikTok Studio's web uploader (browser/post_tiktok.js).

Replaces the Content Posting API path in src/tiktok.py, which was abandoned
on 2026-09-29: the app was rejected at review, and the only endpoint open to
it made inbox drafts rather than posts. This does what src/publisher.
post_facebook does for Facebook. Playwright drives the real web uploader from
an already signed-in Chrome profile, headless, with no password anywhere.

Account: TikTok @wwwtchessapp, which carries the tchessapp brand's reels. It
is signed in inside a dedicated Chrome profile (TIKTOK_PROFILE_DIR). That
profile belongs to ChessReel alone:
  * nature-reels refuses to open it (NEVER_USE_PROFILE_NAMES in its
    src/flow.ts, not configurable);
  * this module refuses to run on the Facebook profile or on Jarvis's, because
    Chrome allows one process per profile.

🔴 A TIKTOK FAILURE MUST NEVER HOLD UP FB/IG/YT. publish.py posts one reel per
slot, oldest pending first, so an entry left owing "tt" would be picked again
by the next slot, and that slot would publish nothing new anywhere else.
publish.py therefore records TT_FAILED_PREFIX on a failure (see
record_failure), which completes the entry. TikTok misses that one reel, and
the owner gets the notification.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import config
from src import accounts

log = logging.getLogger("publish")


class TikTokBrowserError(RuntimeError):
    pass


def _same_dir(a: str, b: str) -> bool:
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def post_tiktok(video_path, caption: str, account: str) -> str:
    """Post one reel. Returns the video URL, or a TT_UNRESOLVED sentinel when
    the post went through but its URL could not be read back. Raises on
    failure, and publish.py turns that into a TT_FAILED mark."""
    handle = accounts.handle(account, "tt").lstrip("@")
    if not handle:
        raise TikTokBrowserError(f"account {account!r} has no TikTok handle")
    profile = config.TIKTOK_PROFILE_DIR
    if not profile or not os.path.isdir(profile):
        raise TikTokBrowserError(f"TIKTOK_PROFILE_DIR does not exist: {profile!r}")
    for other, what in ((config.BROWSER_PROFILE_DIR, "the Facebook publisher's"),
                        (config.JARVIS_PROFILE_DIR, "Jarvis's")):
        if _same_dir(profile, other):
            raise TikTokBrowserError(
                f"TIKTOK_PROFILE_DIR is {what} Chrome profile ({profile}). Chrome allows one "
                "process per profile, so sharing it breaks both. Use ChessReel's own TikTok "
                "profile (Gmail_40).")
    if not config.TIKTOK_PUBLISHER_SCRIPT.exists():
        raise TikTokBrowserError(f"browser publisher missing: {config.TIKTOK_PUBLISHER_SCRIPT}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request = {
        "videoPath": str(video_path),
        "caption": with_promo(caption or "")[:config.TIKTOK_CAPTION_MAX],
        "userDataDir": profile,
        "handle": handle,
        "headless": config.BROWSER_HEADLESS,
        "dryRun": config.TIKTOK_DRY_RUN,
        "screenshotDir": str(config.TIKTOK_SHOT_DIR / f"{account}_{stamp}"),
        "timeoutMs": config.TIKTOK_TIMEOUT_SECONDS * 1000,
    }
    try:
        proc = subprocess.run(
            [config.BROWSER_NODE, str(config.TIKTOK_PUBLISHER_SCRIPT), json.dumps(request)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=config.TIKTOK_TIMEOUT_SECONDS + 180,
            cwd=str(config.ROOT), creationflags=config.SUBPROCESS_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        # Post may already have been clicked. Returning a sentinel (not
        # raising) records the platform as done, so it is never posted twice;
        # a person checks the profile.
        log.warning("[tt/%s] browser publisher timed out — CHECK @%s before re-posting", account, handle)
        return config.TT_UNRESOLVED_PREFIX + "timeout:" + stamp

    for line in (proc.stderr or "").strip().splitlines():
        log.info("[tt/%s] %s", account, line)
    lines = (proc.stdout or "").strip().splitlines()
    try:
        result = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError:
        raise TikTokBrowserError(f"unparseable publisher output (exit {proc.returncode}): {(proc.stdout or '')[:300]}")

    if not result.get("ok"):
        raise TikTokBrowserError(f"failed at step {result.get('step')!r}: {result.get('error')}")
    if not result.get("published"):
        raise TikTokBrowserError("TikTok publisher ran in DRY RUN and posted nothing "
                                 "(set TIKTOK_DRY_RUN=0 in .env to publish for real)")
    if result.get("postUrl"):
        return result["postUrl"]
    return config.TT_UNRESOLVED_PREFIX + ("unconfirmed:" if result.get("unconfirmed") else "") + stamp


def with_promo(caption: str) -> str:
    """The TikTok caption with the app line in it, before the hashtags.

    The comment is best-effort (TikTok may answer it with a CAPTCHA, which is
    never solved), so the promo also rides in the caption, where nothing can
    stop it and which more people see than a first comment anyway.
    """
    promo = config.TIKTOK_CAPTION_PROMO
    if not promo or promo in (caption or ""):
        return caption
    parts = (caption or "").rstrip().split("\n\n")
    if parts and parts[-1].lstrip().startswith("#"):
        return "\n\n".join(parts[:-1] + [promo, parts[-1]])
    return (caption.rstrip() + "\n\n" + promo) if caption else promo


def post_comment(video_url: str, text: str, account: str) -> bool:
    """Post (and try to pin) the promo comment. Best-effort: returns False,
    never raises, on a CAPTCHA or any other failure."""
    if not str(video_url).startswith("http"):
        return False
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request = {
        "commentOn": video_url, "text": text, "pin": True,
        "userDataDir": config.TIKTOK_PROFILE_DIR, "headless": config.BROWSER_HEADLESS,
        "screenshotDir": str(config.TIKTOK_SHOT_DIR / f"{account}_{stamp}_comment"),
    }
    try:
        proc = subprocess.run(
            [config.BROWSER_NODE, str(config.TIKTOK_PUBLISHER_SCRIPT), json.dumps(request, ensure_ascii=False)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            cwd=str(config.ROOT), creationflags=config.SUBPROCESS_NO_WINDOW,
        )
        for line in (proc.stderr or "").strip().splitlines():
            log.info("[tt/%s] %s", account, line)
        lines = (proc.stdout or "").strip().splitlines()
        result = json.loads(lines[-1]) if lines else {}
    except Exception as exc:  # noqa: BLE001 — a comment must never fail a publish
        log.warning("[tt/%s] promo comment skipped: %s", account, exc)
        return False
    if not result.get("ok"):
        log.warning("[tt/%s] promo comment skipped at %s: %s", account, result.get("step"), result.get("error"))
        return False
    log.info("[tt/%s] promo comment posted%s", account, " and pinned" if result.get("pinned") else "")
    return True


def record_failure(puzzle_id: str, error: str) -> str:
    """Complete the entry's "tt" slot with a failure mark (see module docstring)."""
    from src import queue as ledger
    mark = config.TT_FAILED_PREFIX + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.mark_platform(puzzle_id, "tt", mark)
    return mark
