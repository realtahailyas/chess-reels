"""ABANDONED 2026-09-29 — nothing imports this any more. TikTok is published
through the web uploader instead: src/tiktok_browser.py. The Content Posting
API app was rejected at review. Kept only as a record.

TikTok upload — the draft/inbox half of the Content Posting API.

WHY THIS IS THE INBOX ENDPOINT AND NOT DIRECT POST

TikTok offers two ways in, and only one of them fits an unattended publisher:

  * `video.publish` (Direct Post) posts immediately, but its UX rules require a
    human-facing screen before every post — the creator's nickname, a privacy
    dropdown with NO default selected, comment/duet/stitch toggles all off by
    default, a commercial-content disclosure, and the Music Usage Confirmation
    notice. A cron job cannot satisfy any of that, and posting from one anyway
    is what gets an app pulled at audit.
  * `video.upload` (this module) drops the file into the creator's TikTok inbox
    as a DRAFT. No UX requirements apply, so it runs unattended exactly like
    the Facebook, Instagram and YouTube publishers already do.

⚠️ THE CAPTION CANNOT TRAVEL WITH THE DRAFT. The inbox endpoint accepts
`source_info` and nothing else — no title, no description, no privacy. The
creator types those in the TikTok app when finishing the post. `post_tiktok`
therefore takes the caption only to LOG it, so the text the pipeline wrote is
recoverable at the moment it is needed rather than being silently thrown away.

Nothing here touches the Facebook, Instagram or YouTube paths.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

import config

log = logging.getLogger("publish")

AUTH_ROOT = "https://www.tiktok.com/v2/auth/authorize/"
API_ROOT = "https://open.tiktokapis.com/v2"

# The only scope this module needs. `video.publish` is deliberately NOT here —
# see the module docstring. Adding it would also make app review materially
# stricter for a capability nothing calls.
SCOPES = ["video.upload"]

# Chunk rules from the Media Transfer Guide, in bytes. A file under the minimum
# must go up whole, as a single chunk whose chunk_size IS the file size.
MIN_CHUNK = 5 * 1024 * 1024          # 5 MB
MAX_CHUNK = 64 * 1024 * 1024         # 64 MB
MAX_FINAL_CHUNK = 128 * 1024 * 1024  # 128 MB — the last chunk may run over
MAX_CHUNKS = 1000


class TikTokError(RuntimeError):
    """Raised for any TikTok failure. publish.py already treats a raised
    exception from a platform as 'this platform failed, keep the others'."""


# ── Credentials ────────────────────────────────────────────────────────────

def _client() -> tuple[str, str]:
    key = os.environ.get("TIKTOK_CLIENT_KEY", "")
    secret = os.environ.get("TIKTOK_CLIENT_SECRET", "")
    if not key or not secret:
        raise TikTokError("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET not set (see .env.example)")
    return key, secret


def _token_path() -> Path:
    p = os.environ.get("TIKTOK_TOKEN_PATH", "")
    if not p:
        raise TikTokError("TIKTOK_TOKEN_PATH not set (see .env.example)")
    return Path(p)


def _read_token() -> dict:
    path = _token_path()
    if not path.is_file():
        raise TikTokError(
            f"No TikTok token at {path}. Run `python -m src.tiktok auth` once to create it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _write_token(data: dict) -> None:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # `expires_at` is stored rather than `expires_in` because a duration is
    # only meaningful next to the moment it was issued, and that moment is not
    # in the response. Everything downstream compares against the clock.
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _post_form(url: str, data: dict) -> dict:
    resp = requests.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    try:
        body = resp.json()
    except ValueError:
        raise TikTokError(f"{url} returned non-JSON ({resp.status_code}): {resp.text[:200]}")
    # TikTok reports OAuth failures with HTTP 200 and an `error` key, so the
    # status code alone is not the check.
    if body.get("error") and body.get("error") != "ok":
        raise TikTokError(f"{url}: {body.get('error')} — {body.get('error_description', '')}")
    return body


def access_token() -> str:
    """A currently-valid access token, refreshing on disk if needed.

    Access tokens last 24h and refresh tokens 365 days, so an unattended box
    that runs at least once a year never needs a human. The 5-minute skew stops
    a token that expires mid-upload from being treated as good at init time.
    """
    tok = _read_token()
    if time.time() < tok.get("expires_at", 0) - 300:
        return tok["access_token"]

    key, secret = _client()
    body = _post_form(f"{API_ROOT}/oauth/token/", {
        "client_key": key,
        "client_secret": secret,
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
    })
    _write_token({
        "access_token": body["access_token"],
        # ⚠️ The refresh token can be ROTATED on any refresh. Writing back the
        # old one would work until it silently stopped, months later, with no
        # way to tell what changed.
        "refresh_token": body.get("refresh_token", tok["refresh_token"]),
        "expires_at": time.time() + int(body.get("expires_in", 86400)),
        "open_id": body.get("open_id", tok.get("open_id")),
        "scope": body.get("scope", tok.get("scope")),
    })
    return body["access_token"]


# ── One-time authorisation ─────────────────────────────────────────────────

def authorize_url(redirect_uri: str, state: str = "chessreel") -> str:
    key, _ = _client()
    return AUTH_ROOT + "?" + urlencode({
        "client_key": key,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    })


def exchange_code(code: str, redirect_uri: str) -> dict:
    key, secret = _client()
    body = _post_form(f"{API_ROOT}/oauth/token/", {
        "client_key": key,
        "client_secret": secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    token = {
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at": time.time() + int(body.get("expires_in", 86400)),
        "open_id": body.get("open_id"),
        "scope": body.get("scope"),
    }
    _write_token(token)
    return token


# ── Upload ─────────────────────────────────────────────────────────────────

def _plan_chunks(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) obeying the Media Transfer Guide.

    A file under 5 MB is one chunk of exactly its own size — passing the 5 MB
    minimum for a 3 MB file is rejected, because chunk_size may not exceed the
    video. Above that, the trailing bytes are folded INTO the final chunk
    rather than becoming a short chunk of their own, which is the rule the
    guide states and the one most implementations get wrong.
    """
    if size <= 0:
        raise TikTokError("video file is empty")
    if size < MIN_CHUNK:
        return size, 1

    chunk = MIN_CHUNK
    count = size // chunk          # floor: the remainder joins the last chunk
    if count == 1:
        # 🔴 A 7 MB file floors to ONE chunk, and declaring chunk_size = 5 MB
        # while sending 7 MB is a contradiction the API is entitled to reject:
        # with a single chunk there is no "final chunk may exceed" case to
        # appeal to, because that chunk is also the first one. Whenever the
        # whole file rides in one request, chunk_size IS the file size — the
        # same rule the guide states for files under 5 MB. Caught by the
        # planner's own test table, not by a failed upload.
        return size, 1
    if count > MAX_CHUNKS:
        # Grow the chunk so the count fits, still capped at the 64 MB maximum.
        chunk = min(MAX_CHUNK, -(-size // MAX_CHUNKS))
        count = max(1, size // chunk)
    # The final chunk carries the remainder and may exceed chunk_size, but not
    # 128 MB. With a 5 MB chunk and a floor'd count this can only be breached
    # by an absurd file, so it is checked rather than assumed.
    final = size - chunk * (count - 1)
    if final > MAX_FINAL_CHUNK:
        raise TikTokError(f"video too large to chunk within TikTok's limits ({size} bytes)")
    return chunk, count


def _init_upload(token: str, size: int, chunk: int, count: int) -> tuple[str, str]:
    resp = requests.post(
        f"{API_ROOT}/post/publish/inbox/video/init/",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        json={"source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk,
            "total_chunk_count": count,
        }},
        timeout=60,
    )
    body = resp.json()
    err = body.get("error") or {}
    if err.get("code") not in (None, "ok"):
        raise TikTokError(f"init failed: {err.get('code')} — {err.get('message')} (logid {err.get('log_id')})")
    data = body.get("data") or {}
    if not data.get("upload_url") or not data.get("publish_id"):
        raise TikTokError(f"init returned no upload_url/publish_id: {body}")
    return data["publish_id"], data["upload_url"]


def _send_chunks(upload_url: str, path: Path, size: int, chunk: int, count: int) -> None:
    with path.open("rb") as fh:
        for i in range(count):
            first = i * chunk
            # The last chunk takes everything that is left, which is why this
            # is not simply `chunk` bytes every time.
            length = (size - first) if i == count - 1 else chunk
            payload = fh.read(length)
            if len(payload) != length:
                raise TikTokError(f"short read on chunk {i + 1}/{count}")
            last = first + length - 1
            r = requests.put(
                upload_url,
                data=payload,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(length),
                    "Content-Range": f"bytes {first}-{last}/{size}",
                },
                timeout=300,
            )
            # 201 ends the transfer; 206 acknowledges a partial one.
            if r.status_code not in (200, 201, 206):
                raise TikTokError(
                    f"chunk {i + 1}/{count} rejected: HTTP {r.status_code} {r.text[:200]}"
                )


def upload_status(publish_id: str, token: str | None = None) -> dict:
    """Poll one publish_id. Exposed for the dashboard and for watcher checks."""
    tok = token or access_token()
    resp = requests.post(
        f"{API_ROOT}/post/publish/status/fetch/",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"},
        json={"publish_id": publish_id},
        timeout=30,
    )
    return resp.json().get("data") or {}


def post_tiktok(video_path, caption: str = "") -> str:
    """Send the video to the creator's TikTok inbox as a draft.

    Returns the `publish_id`. That is NOT a post id — nothing is public yet;
    the draft waits in the TikTok app until the creator opens it, adds the
    caption and publishes. `publish.py` records it the same way it records the
    other platforms' ids, so the ledger still knows this reel has been handled
    and will not send it again.
    """
    path = Path(video_path)
    if not path.is_file():
        raise TikTokError(f"video not found: {path}")

    size = path.stat().st_size
    chunk, count = _plan_chunks(size)
    token = access_token()

    publish_id, upload_url = _init_upload(token, size, chunk, count)
    _send_chunks(upload_url, path, size, chunk, count)

    # ⚠️ The caption cannot be sent with an inbox upload — see the module
    # docstring. Logging it is the only thing that keeps the generated text
    # within reach when the draft is finished by hand in the app.
    if caption:
        log.info("[tiktok] draft %s uploaded. Caption to paste in the app:\n%s", publish_id, caption)
    else:
        log.info("[tiktok] draft %s uploaded", publish_id)

    return publish_id


# ── One-time setup, run by hand ────────────────────────────────────────────

def _demo(video_arg: str | None) -> int:
    """`python -m src.tiktok demo [path]` — the run recorded for app review.

    A dedicated entry point rather than "just run publish.py" for two reasons:
    publish.py would post to Facebook, Instagram and YouTube in the same breath,
    which has no place in a TikTok demo; and it prints a wall of queue
    bookkeeping that buries the one thing a reviewer is looking for. This does
    exactly the TikTok half, out loud, and stops.
    """
    from src import queue as ledger  # noqa: F401 — kept out of module import cost

    video = Path(video_arg) if video_arg else None
    if video is None:
        # Smallest finished promo reel: quickest upload on camera, and it is a
        # real published-format video rather than a fixture.
        found = sorted(
            (p for p in Path("output/promo").rglob("video.mp4")),
            key=lambda p: p.stat().st_size,
        )
        if not found:
            print("No video found under output/promo/. Pass a path explicitly.")
            return 1
        video = found[min(1, len(found) - 1)]

    if not video.is_file():
        print(f"Not a file: {video}")
        return 1

    size = video.stat().st_size
    chunk, count = _plan_chunks(size)

    print()
    print("=" * 66)
    print("  ChessReel -> TikTok   (Content Posting API, video.upload)")
    print("=" * 66)
    print(f"  video        : {video}")
    print(f"  size         : {size:,} bytes ({size / 1048576:.2f} MB)")
    print(f"  transfer     : FILE_UPLOAD, {count} chunk(s) of {chunk:,} bytes")
    print(f"  endpoint     : {API_ROOT}/post/publish/inbox/video/init/")
    print(f"  destination  : creator inbox as a DRAFT (nothing is published)")
    print("-" * 66)

    print("  [1/3] refreshing access token ...")
    token = access_token()
    print("        ok")

    print("  [2/3] initialising upload ...")
    publish_id, upload_url = _init_upload(token, size, chunk, count)
    print(f"        publish_id = {publish_id}")

    print(f"  [3/3] sending {count} chunk(s) ...")
    _send_chunks(upload_url, video, size, chunk, count)
    print("        all bytes accepted")

    print("-" * 66)
    print("  polling status ...")
    for _ in range(20):
        st = upload_status(publish_id, token)
        status = st.get("status", "?")
        print(f"    {status}")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            print("-" * 66)
            print("  DONE. The draft is now in the TikTok app inbox.")
            print("  Open TikTok -> Inbox -> the notification, add the caption,")
            print("  choose the privacy setting there, and post.")
            print("=" * 66)
            print()
            return 0
        if status == "FAILED":
            print(f"  FAILED: {st}")
            return 1
        time.sleep(5)

    print("  still processing; check the TikTok inbox shortly.")
    return 0


def _cli() -> int:
    """`python -m src.tiktok auth` — the interactive consent, done once.

    A paste-back flow rather than a local web server on purpose: TikTok will
    only redirect to a URI registered on the app, and a sandbox app's registered
    URI usually is not something this machine can serve. Copying the redirected
    URL out of the browser works whatever that URI is, including one that does
    not resolve at all.
    """
    import sys

    # `publish.py` loads .env before importing this module; running it directly
    # has no such parent, and every credential here lives in that file. Without
    # this, `python -m src.tiktok` fails on a missing variable that is in fact
    # set — the most confusing possible error.
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass

    if len(sys.argv) < 2 or sys.argv[1] not in ("auth", "demo"):
        print("usage: python -m src.tiktok auth")
        print("       python -m src.tiktok demo [video.mp4]")
        return 2

    if sys.argv[1] == "demo":
        return _demo(sys.argv[2] if len(sys.argv) > 2 else None)

    redirect_uri = os.environ.get("TIKTOK_REDIRECT_URI", "")
    if not redirect_uri:
        print("TIKTOK_REDIRECT_URI is not set. Put the exact URI registered on the")
        print("TikTok app (Sandbox -> Redirect URI) into .env, then re-run.")
        return 1

    print("\n1. Open this URL in the browser signed in to the TikTok account:\n")
    print("   " + authorize_url(redirect_uri) + "\n")
    print("2. Approve. The browser will be sent to your redirect URI — it does not")
    print("   matter if that page fails to load.")
    print("3. Copy the FULL address bar contents and paste it below.\n")

    raw = input("redirected URL: ").strip()
    qs = parse_qs(urlparse(raw).query)
    code = (qs.get("code") or [""])[0]
    if not code:
        print("No ?code= in that URL. Check you pasted the address after the redirect.")
        return 1

    tok = exchange_code(code, redirect_uri)
    print(f"\nSaved to {_token_path()}")
    print(f"  open_id : {tok.get('open_id')}")
    print(f"  scope   : {tok.get('scope')}")
    print("  refresh : valid 365 days; access tokens refresh automatically.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_cli())
    except TikTokError as exc:
        # Deliberately not a traceback: this entry point is run on camera for
        # app review, and a stack dump reads as a broken integration even when
        # the cause is a missing line in .env.
        print(f"\n  TikTok setup problem: {exc}\n")
        raise SystemExit(1)
