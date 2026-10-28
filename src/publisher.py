"""Posts one already-built reel to Facebook, Instagram and YouTube.

Each post_* function does exactly one platform for exactly one brand, and
returns that platform's post id, or raises. publish.py is the only caller and
decides what to do with failures (retry later, notify, move on) — this module
never swallows errors.

Every post_* function takes an `account` (see src/accounts.py) that defaults
to config.DEFAULT_ACCOUNT, so the call shape that existed before a second
brand did still resolves to exactly the same credentials it always has.
"""

import logging
import os
import time
from datetime import datetime, timezone

import requests

import config
from src import accounts
from src import hosting

log = logging.getLogger("publish.publisher")

GRAPH_ROOT = "https://graph.facebook.com"


class PublishError(RuntimeError):
    pass


def _graph_url(path: str) -> str:
    return f"{GRAPH_ROOT}/{config.FB_GRAPH_API_VERSION}/{path}"


def _fb_token(account: str = None) -> str:
    """The Meta token this brand posts with.

    Both brands currently resolve to the one "ChessReel Publisher" System User
    token, because @tahachesstv and @tchessapp are both assets in the same
    Taha Pages Business portfolio — accounts.credential() falls back to
    FB_PAGE_TOKEN when the per-brand override is unset.
    """
    token = accounts.credential(account or config.DEFAULT_ACCOUNT, "fb_token")
    if not token:
        var = accounts.env_var(account or config.DEFAULT_ACCOUNT, "fb_token")
        raise PublishError(f"{var or 'FB_PAGE_TOKEN'} is not set (see .env.example)")
    return token


def _page_token(page_id: str, account: str = None) -> str:
    """Exchange the System User token for a page-scoped one.

    The System User token works directly for reading the Page and for
    Instagram, but the Video Reels upload endpoint rejects it outright
    (`(#200) Subject does not have permission to post videos on this
    target`) — it needs the Page's own token, derived here.
    """
    resp = _check(requests.get(_graph_url(page_id), params={
        "fields": "access_token",
        "access_token": _fb_token(account),
    }), "FB page token exchange")
    return resp["access_token"]


def _check(resp: requests.Response, what: str) -> dict:
    if not resp.ok:
        raise PublishError(f"{what} failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()


# ── Facebook ──────────────────────────────────────────────────────────────

def post_facebook(video_path, caption: str, account: str = None, title: str = None) -> str:
    """Publish a Reel to this brand's Page through Meta Business Suite's
    composer, driven by Playwright — not through the Graph API.

    🔴 THE GRAPH API PATH IS GONE ON PURPOSE. Its Video Reels flow never
    produced a working post for these Pages, which is the whole reason
    FACEBOOK_ENABLED sat at 0 while Instagram and YouTube kept publishing. The
    composer does work, so Facebook is driven through the UI.

    ⚠️ Instagram and YouTube did NOT move with it. Both have APIs that hand
    back a post id, and that id is what per-post insights and the pinned promo
    comment are keyed off. The composer would happily crosspost to Instagram —
    these Pages are linked to their IG accounts — and that crosspost returns no
    media id at all, so it would put a duplicate, unmeasurable reel on a live
    account beside the one the Graph API already published. The browser layer
    deselects Instagram and refuses to post if it cannot prove it did.

    Returns the recovered reel id, or a config.FB_UNRESOLVED_PREFIX sentinel
    when the post demonstrably succeeded but its id could not be read back.
    """
    import json
    import subprocess

    account = account or config.DEFAULT_ACCOUNT
    if "fb" not in accounts.platform_ceiling(account):
        raise PublishError(f"account {account!r} has no Facebook Page — nothing to post to")

    page_id = accounts.credential(account, "fb_page_id")
    if not page_id:
        raise PublishError(f"{accounts.env_var(account, 'fb_page_id')} is not set (see .env.example)")

    profile_dir = config.BROWSER_PROFILE_DIR
    if not profile_dir:
        raise PublishError(
            "CHROME_PROFILE_DIR is not set — the browser publisher reuses an already "
            "signed-in Chrome profile and has no login of its own (see .env.example)"
        )
    if not os.path.isdir(profile_dir):
        raise PublishError(f"CHROME_PROFILE_DIR does not exist: {profile_dir}")

    # 🔴 REFUSING, NOT WARNING. Sharing a Chrome profile with the Jarvis
    # desktop app would make the two projects break each other at random:
    # Chrome permits one process per profile, so whichever posted second would
    # fail — and a Jarvis post lost this way surfaces as a Jarvis bug, in a
    # codebase whose owner has no reason to suspect ChessReel. ChessReel runs
    # on its own copy of the profile; nothing here may point back.
    if os.path.normcase(os.path.abspath(profile_dir)) == os.path.normcase(os.path.abspath(config.JARVIS_PROFILE_DIR)):
        raise PublishError(
            f"CHROME_PROFILE_DIR points at the Jarvis profile ({config.JARVIS_PROFILE_DIR}). "
            "Refusing to run: Jarvis posts its own Pages from there on its own schedule, and "
            "Chrome allows only one process per profile — sharing it would make the two "
            "projects break each other. Point CHROME_PROFILE_DIR at ChessReel's own "
            "signed-in profile instead, then prove it with "
            "`python scripts/check_browser_profile.py`."
        )
    if not config.BROWSER_PUBLISHER_SCRIPT.exists():
        raise PublishError(f"browser publisher missing: {config.BROWSER_PUBLISHER_SCRIPT}")

    # What the Page's newest reel is BEFORE posting. The composer gives back no
    # id of its own, so the new reel is identified by being one this id was not
    # already the newest of — cheaper and far more reliable than scraping it
    # out of a confirmation dialog.
    before_id = _newest_reel_id(page_id, account)

    request = {
        "account": account,
        "videoPath": str(video_path),
        "title": (title or "")[:100] or None,
        "description": caption,
        "userDataDir": profile_dir,
        "headless": config.BROWSER_HEADLESS,
        "dryRun": config.BROWSER_DRY_RUN,
        "screenshotDir": str(config.BROWSER_SHOT_DIR / account),
        "timeoutMs": config.BROWSER_TIMEOUT_SECONDS * 1000,
    }

    try:
        proc = subprocess.run(
            [config.BROWSER_NODE, str(config.BROWSER_PUBLISHER_SCRIPT), json.dumps(request)],
            capture_output=True, text=True,
            timeout=config.BROWSER_TIMEOUT_SECONDS + 120,
            cwd=str(config.ROOT),
            # No console window — see config.SUBPROCESS_NO_WINDOW. This is the
            # one that mattered most: node runs on every FB/IG post.
            creationflags=config.SUBPROCESS_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        # 🔴 A TIMEOUT IS NOT A FAILED POST. Playwright may well have clicked
        # Share before this process gave up waiting, so the reel can be live.
        # Saying "failed" here would have the next run publish it again.
        raise PublishError(
            f"browser publisher timed out after {config.BROWSER_TIMEOUT_SECONDS}s — "
            f"CHECK THE PAGE before retrying, the reel may already be live: {exc}"
        ) from None

    if proc.stderr:
        for line in proc.stderr.strip().splitlines():
            log.info("[fb/%s] %s", account, line)

    payload = (proc.stdout or "").strip().splitlines()
    try:
        result = json.loads(payload[-1]) if payload else {}
    except (json.JSONDecodeError, IndexError):
        raise PublishError(
            f"browser publisher returned unparseable output (exit {proc.returncode}): "
            f"{(proc.stdout or '')[:300]}"
        ) from None

    if not result.get("ok"):
        raise PublishError(
            f"browser publish failed at step {result.get('step')!r}: {result.get('error')}"
        )

    if not result.get("published"):
        # dryRun walked the whole flow and stopped. Report it as a distinct,
        # obviously-not-a-post value so nothing downstream records it as live.
        raise PublishError(
            "browser publisher ran in DRY RUN and posted nothing — "
            "set BROWSER_DRY_RUN=0 in .env to publish for real"
        )

    reel_id = _recover_reel_id(page_id, account, before_id)
    if reel_id:
        return reel_id

    sentinel = config.FB_UNRESOLVED_PREFIX + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.warning(
        "[fb/%s] reel published but its id could not be read back — recording %s. "
        "Insights and the promo comment will be skipped for this one.",
        account, sentinel,
    )
    return sentinel


def _newest_reel_id(page_id: str, account: str):
    """Newest reel id on the Page, or None if the edge cannot be read."""
    try:
        token = _page_token(page_id, account)
        resp = requests.get(_graph_url(f"{page_id}/video_reels"), params={
            "fields": "id,created_time", "limit": 1, "access_token": token,
        }, timeout=25)
        if not resp.ok:
            return None
        items = resp.json().get("data") or []
        return items[0]["id"] if items else None
    except Exception as exc:  # noqa: BLE001 — recovery is best-effort by design
        log.warning("[fb/%s] could not read newest reel id: %s", account, exc)
        return None


def _recover_reel_id(page_id: str, account: str, before_id):
    """Poll the Page until a reel newer than `before_id` shows up.

    A reel does not appear on the edge the instant Share is clicked — Meta
    processes it first — so this polls rather than reading once. Returns None
    if nothing new arrives in time, which the caller turns into a sentinel
    rather than an error.
    """
    for attempt in range(config.FB_ID_RECOVERY_ATTEMPTS):
        newest = _newest_reel_id(page_id, account)
        if newest and newest != before_id:
            log.info("[fb/%s] recovered reel id %s", account, newest)
            return newest
        time.sleep(config.FB_ID_RECOVERY_INTERVAL)
    return None


# ── Instagram ─────────────────────────────────────────────────────────────

def post_instagram(video_path, puzzle_id: str, caption: str, account: str = None) -> str:
    """Publish a Reel via the Content Publishing API.

    IG only accepts a public video_url (no direct upload), so the video is
    pushed to the GitHub CDN repo first (src/hosting.py).
    """
    account = account or config.DEFAULT_ACCOUNT
    # accounts.credential refuses to fall back on ig_user_id — an unset
    # IG_USER_ID_TCHESSAPP raises here rather than silently resolving to
    # @tahachesstv's id and publishing the app brand's reel to the wrong
    # audience.
    ig_user_id = accounts.credential(account, "ig_user_id")
    if not ig_user_id:
        raise PublishError(f"{accounts.env_var(account, 'ig_user_id')} is not set (see .env.example)")
    token = _fb_token(account)

    video_url = hosting.push(video_path, puzzle_id)

    created = _check(requests.post(_graph_url(f"{ig_user_id}/media"), data={
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": token,
    }), f"IG container create ({account})")
    container_id = created["id"]

    deadline = time.monotonic() + config.IG_CONTAINER_POLL_TIMEOUT
    status = None
    while time.monotonic() < deadline:
        poll = _check(requests.get(_graph_url(container_id), params={
            "fields": "status_code",
            "access_token": token,
        }), "IG container poll")
        status = poll.get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise PublishError(f"IG container {container_id} errored during processing")
        time.sleep(config.IG_CONTAINER_POLL_SECONDS)
    else:
        raise PublishError(f"IG container {container_id} did not finish within timeout (last status: {status})")

    published = _check(requests.post(_graph_url(f"{ig_user_id}/media_publish"), data={
        "creation_id": container_id,
        "access_token": token,
    }), "IG media publish")

    return published["id"]


# ── YouTube ───────────────────────────────────────────────────────────────

def youtube_scopes() -> list:
    """The one scope list every YouTube credential in this project is minted
    and refreshed with. Module-level so scripts/yt_auth_account.py cannot
    drift from it — see the warning in _youtube_credentials()."""
    return [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",  # needed to post the first comment
    ]


def _youtube_credentials(account: str = None, allow_interactive: bool = True):
    """Load (refreshing if needed) one brand's stored OAuth credentials,
    without making any YouTube API call — used by post_youtube, by
    watcher.py's read-only connectivity check, and by scripts/verify_accounts.py.

    🔴 ONE TOKEN FILE PER CHANNEL, NOT PER GOOGLE ACCOUNT. Taha Chess TV and
    TChess App are two channels behind the same Google login, but a YouTube
    OAuth credential is bound to whichever channel was chosen in the consent
    screen's channel picker, and videos.insert has no parameter to override
    that. Two brands therefore need two token files; resolving both to
    YT_TOKEN_PATH would upload every app reel to Taha Chess TV.

    `allow_interactive=False` turns a missing/invalid token into an error
    instead of opening a browser consent window — required for anything that
    runs unattended under Task Scheduler, where a blocked consent prompt would
    hang the run until its lock went stale.
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    account = account or config.DEFAULT_ACCOUNT
    client_secret = os.environ.get("YT_CLIENT_SECRET_PATH", "")
    # Refuses to fall back (see accounts._NEVER_FALL_BACK): a missing
    # YT_TOKEN_PATH_TCHESSAPP must not silently become Taha Chess TV's token.
    token_path = accounts.credential(account, "yt_token_path")
    if not client_secret or not token_path:
        raise PublishError(
            f"YT_CLIENT_SECRET_PATH / {accounts.env_var(account, 'yt_token_path')} "
            f"not set for account {account!r} (see .env.example)"
        )

    # All scopes must always be requested together — Credentials.from_authorized_user_file
    # sets the object's .scopes to exactly this list regardless of what the token file's
    # own "scopes" field says, and to_json() on a refresh writes that (possibly narrower)
    # list back to disk. A shorter list here silently downgrades a wider-scope token on
    # its very next refresh (this happened for real on 2026-08-22).
    scopes = youtube_scopes()
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif allow_interactive:
            # One-time interactive consent — only happens if token_path is
            # missing/invalid, which should not occur in unattended runs once
            # setup is complete.
            flow = InstalledAppFlow.from_client_secrets_file(client_secret, scopes)
            creds = flow.run_local_server(port=0)
        else:
            raise PublishError(
                f"no usable YouTube token at {token_path} for account {account!r} — "
                f"mint one with: python scripts/yt_auth_account.py {account}"
            )
        with open(token_path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
    return creds


def youtube_channel(account: str = None, creds=None) -> dict:
    """{"id", "title"} of the channel a brand's credential actually posts to.

    One quota unit, against videos.insert's 1600 — cheap enough to spend as a
    guard before every upload, and the only way to answer "which channel is
    this token bound to?", since the token file itself does not say.
    """
    from googleapiclient.discovery import build

    creds = creds or _youtube_credentials(account)
    yt = build("youtube", "v3", credentials=creds)
    items = yt.channels().list(part="snippet", mine=True).execute().get("items") or []
    if not items:
        raise PublishError(f"account {account!r}: YouTube token is bound to no channel")
    return {"id": items[0]["id"], "title": items[0]["snippet"].get("title", "")}


def _assert_expected_channel(account: str, creds):
    """Refuse to upload if the token is bound to a different channel than the
    one pinned in .env.

    🔴 THE ONE FAILURE THIS PROJECT CANNOT TAKE BACK. Every other mistake here
    is a loud error; picking the wrong channel in the OAuth consent picker is
    silent, and the result is the app brand's reels appearing on Taha Chess TV
    — public, to real subscribers, under the wrong identity. So the channel id
    is pinned per account in .env and checked before the bytes go up.

    Skipped when an account pins no channel id, which is how tahachesstv
    behaves by default: it has uploaded to the right place since day one, and
    making a new required variable the condition of it continuing to run would
    be breaking the working brand in order to add the new one.
    """
    expected = accounts.credential(account, "yt_channel_id", default="")
    if not expected:
        return
    actual = youtube_channel(account, creds=creds)
    if actual["id"] != expected:
        raise PublishError(
            f"account {account!r}: YouTube token is bound to channel "
            f"{actual['title']!r} ({actual['id']}), but "
            f"{accounts.env_var(account, 'yt_channel_id')} pins {expected}. "
            f"Refusing to upload to the wrong channel — re-run: "
            f"python scripts/yt_auth_account.py {account}"
        )


def post_youtube(video_path, title: str, description: str, account: str = None) -> str:
    """Upload as a Short via resumable videos.insert. Direct file upload."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    account = account or config.DEFAULT_ACCOUNT
    creds = _youtube_credentials(account, allow_interactive=False)
    _assert_expected_channel(account, creds)
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": config.YT_CATEGORY_ID,
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _, response = request.next_chunk()

    return response["id"]


# ── First comment (the closest automatable proxy for a pin) ────────────────

def post_first_comment(platform: str, post_id: str, text: str, account: str = None) -> str:
    """The promo comment, posted as the same brand that posted the reel.

    ⚠️ `account` is not cosmetic here. A comment left with the other brand's
    credential appears under the wrong name on a real, public post, so it is
    resolved exactly the way the publish call above it was.
    """
    account = account or config.DEFAULT_ACCOUNT
    if platform == "fb":
        page_id = accounts.credential(account, "fb_page_id")
        token = _page_token(page_id, account) if page_id else _fb_token(account)
        resp = _check(requests.post(_graph_url(f"{post_id}/comments"), data={
            "message": text,
            "access_token": token,
        }), "FB first comment")
    elif platform == "ig":
        resp = _check(requests.post(_graph_url(f"{post_id}/comments"), data={
            "message": text,
            "access_token": _fb_token(account),
        }), "IG first comment")
    elif platform == "yt":
        from googleapiclient.discovery import build

        creds = _youtube_credentials(account, allow_interactive=False)
        youtube = build("youtube", "v3", credentials=creds)
        resp = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": post_id,
                    "topLevelComment": {"snippet": {"textOriginal": text}},
                }
            },
        ).execute()
    else:
        raise PublishError(f"post_first_comment: unsupported platform {platform!r}")
    return resp["id"]
