"""Per-post analytics fetchers for Facebook, Instagram and YouTube.

Read-only — never touches posting/eligibility. A metric being sparse or zero
on a fresh post is real data, not an error: Meta and YouTube both take up to
~24h to populate insights for a new post, so callers should show "insights
available ~24h after posting" rather than treating a zero as a failure.

⚠️ EVERY FETCH IS SCOPED TO THE BRAND THAT POSTED. A YouTube credential only
sees its own channel's videos and an IG token only its own media, so reading a
@tchessapp post with @tahachesstv's credentials does not return that post's
numbers — it returns an error, or worse, nothing that looks like one. The
account comes from the ledger entry's own stamp (accounts.entry_account), the
same stamp that decided where it was published.
"""

import logging
import os
from datetime import datetime

import requests

import config
from src import accounts
from src import publisher

log = logging.getLogger("publish.analytics")

FB_VIDEO_METRICS = [
    "post_video_avg_time_watched",
    "post_video_likes_by_reaction_type",
    "post_video_social_actions",
    "blue_reels_play_count",  # the actual Reels "views" count — post_video_views doesn't apply to Reels-type posts
]
IG_MEDIA_METRICS = ["reach", "likes", "comments", "shares", "saved", "views"]


class AnalyticsError(RuntimeError):
    pass


def _graph_get(path: str, params: dict) -> dict:
    resp = requests.get(publisher._graph_url(path), params=params, timeout=20)
    if not resp.ok:
        raise AnalyticsError(f"GET {path} failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def fetch_facebook(fb_post_id: str, account: str = None) -> dict:
    """Reel insights for one Page video post. Returns a flat metric->value dict."""
    account = account or config.DEFAULT_ACCOUNT
    page_id = accounts.credential(account, "fb_page_id")
    token = publisher._page_token(page_id, account)
    data = _graph_get(f"{fb_post_id}/video_insights", {
        "metric": ",".join(FB_VIDEO_METRICS),
        "access_token": token,
    })
    out = {}
    for item in data.get("data", []):
        name = item.get("name")
        values = item.get("values", [])
        out[name] = values[0].get("value") if values else None
    return out


def fetch_instagram(ig_media_id: str, account: str = None) -> dict:
    """Reel insights for one IG media object."""
    token = publisher._fb_token(account)
    data = _graph_get(f"{ig_media_id}/insights", {
        "metric": ",".join(IG_MEDIA_METRICS),
        "access_token": token,
    })
    out = {}
    for item in data.get("data", []):
        name = item.get("name")
        values = item.get("values", [])
        out[name] = values[0].get("value") if values else None
    return out


def fetch_account_stats(account: str = None) -> dict:
    """Page/account-level follower counts for ONE brand. Cheap — a handful of
    calls, no per-post loop. Only asks for the platforms that brand actually
    has, so tchessapp is never queried for a Facebook Page it does not own."""
    account = account or config.DEFAULT_ACCOUNT
    ceiling = accounts.platform_ceiling(account)
    out = {}

    if "fb" in ceiling:
        try:
            page_id = accounts.credential(account, "fb_page_id")
            token = publisher._page_token(page_id, account)
            data = _graph_get(page_id, {"fields": "followers_count", "access_token": token})
            out["facebook_followers"] = data.get("followers_count")
        except Exception as exc:  # noqa: BLE001
            log.warning("account stats [%s]: FB followers failed: %s", account, exc)

    if "ig" in ceiling:
        try:
            ig_id = accounts.credential(account, "ig_user_id")
            token = publisher._fb_token(account)
            data = _graph_get(ig_id, {"fields": "followers_count,username", "access_token": token})
            out["instagram_followers"] = data.get("followers_count")
            out["instagram_username"] = data.get("username")
        except Exception as exc:  # noqa: BLE001
            log.warning("account stats [%s]: IG followers failed: %s", account, exc)

    if "yt" in ceiling:
        try:
            from googleapiclient.discovery import build

            creds = publisher._youtube_credentials(account, allow_interactive=False)
            yt = build("youtube", "v3", credentials=creds)
            data = yt.channels().list(part="statistics,snippet", mine=True).execute()
            item = data["items"][0]
            stats = item["statistics"]
            out["youtube_subscribers"] = int(stats.get("subscriberCount", 0))
            out["youtube_views"] = int(stats.get("viewCount", 0))
            # Recorded so a mis-bound token shows up on the dashboard as the
            # wrong channel name rather than as quietly plausible numbers.
            out["youtube_channel_title"] = item["snippet"].get("title")
            out["youtube_channel_id"] = item.get("id")
        except Exception as exc:  # noqa: BLE001
            log.warning("account stats [%s]: YouTube failed: %s", account, exc)

    return out


def fetch_youtube(video_id: str, since_date: str, until_date: str, account: str = None) -> dict:
    """Views/likes/comments come from the public Data API — near-real-time,
    unlike the YouTube Analytics reporting API, which can take 24-72h to
    populate a video on a small/new channel (confirmed for real on
    2026-08-24: videos with 200-370 public views were still reporting 0
    there). Watch-time has no public equivalent, so it still comes from
    Analytics — best-effort, since it lags behind the other three.

    since_date/until_date are 'YYYY-MM-DD' strings — the ledger's created_at
    date through today is a safe, cheap default range for that call.
    """
    from googleapiclient.discovery import build

    creds = publisher._youtube_credentials(account, allow_interactive=False)
    youtube = build("youtube", "v3", credentials=creds)
    items = youtube.videos().list(part="statistics", id=video_id).execute().get("items") or []
    stats = items[0]["statistics"] if items else {}

    out = {
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
        "estimatedMinutesWatched": 0,
    }

    try:
        yta = build("youtubeAnalytics", "v2", credentials=creds)
        report = yta.reports().query(
            ids="channel==MINE",
            startDate=since_date,
            endDate=until_date,
            metrics="estimatedMinutesWatched",
            filters=f"video=={video_id}",
        ).execute()
        rows = report.get("rows") or [[0]]
        out["estimatedMinutesWatched"] = rows[0][0]
    except Exception as exc:  # noqa: BLE001 — watch-time is a bonus; views/likes/comments already landed
        log.warning("[%s] watch-time fetch failed (non-fatal): %s", video_id, exc)

    return out


def fetch_for_entry(entry: dict) -> dict:
    """Fetch whatever platforms are actually posted for one ledger entry,
    using the credentials of the brand that posted it.
    Never raises — a failed platform is recorded as {"error": "..."} so one
    bad call can't blank out the others."""
    # A skip mark is not a post id — there is nothing to fetch for it.
    platforms = {k: v for k, v in (entry.get("platforms") or {}).items()
                 if not str(v or "").startswith(config.NOT_A_POST_PREFIXES)}
    account = accounts.entry_account(entry)
    out = {}

    fb_id = platforms.get("fb")
    if fb_id and str(fb_id).startswith(config.FB_UNRESOLVED_PREFIX):
        # The reel published through the browser but its id could not be read
        # back off the Page. There is nothing to query, and pretending
        # otherwise would fill the dashboard with permanent errors for a post
        # that is perfectly fine — it just has no handle.
        out["facebook"] = {"error": "published via browser; reel id not recovered, no insights available"}
        fb_id = None

    if fb_id:
        try:
            out["facebook"] = fetch_facebook(fb_id, account=account)
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s/%s] FB analytics failed (%s)", entry.get("puzzle_id"), account, type(exc).__name__)
            out["facebook"] = {"error": "Facebook metrics unavailable"}

    if platforms.get("ig"):
        try:
            out["instagram"] = fetch_instagram(platforms["ig"], account=account)
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s/%s] IG analytics failed (%s)", entry.get("puzzle_id"), account, type(exc).__name__)
            out["instagram"] = {"error": "Instagram metrics unavailable"}

    if platforms.get("yt"):
        try:
            since = str(entry.get("created_at", ""))[:10] or "2026-01-01"
            until = datetime.now().strftime("%Y-%m-%d")
            out["youtube"] = fetch_youtube(platforms["yt"], since, until, account=account)
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s/%s] YouTube analytics failed (%s)", entry.get("puzzle_id"), account, type(exc).__name__)
            out["youtube"] = {"error": "YouTube metrics unavailable"}

    return out
