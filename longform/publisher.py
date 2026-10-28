"""Upload rendered long-form videos to YouTube, scheduled with publishAt.

Uses the SHORTS' OWN credential plumbing: src.publisher._youtube_credentials()
(one token file per channel) and _assert_expected_channel() (refuses to upload
if the token is bound to a channel other than the one pinned in .env). That
check is the reason a TChess video cannot land on Taha Chess, or the other way
round, and it is reused here, not re-implemented.

A video goes up PRIVATE with status.publishAt set to its slot, and YouTube
makes it public at that exact time. So the laptop only has to be awake some
time before the slot, not at it. The run uploads up to two slots ahead, which
means a whole day with the machine off still publishes on time.

Quota (developers.google.com/youtube/v3/determine_quota_cost, checked
2026-09-29): videos.insert has its own bucket of 100 uploads/day and does not
share the 10,000-unit pool. thumbnails.set 50, playlistItems.insert 50,
playlists.insert 50, playlists.list 1. One long video costs about 150 units.
"""

import json
import time
from datetime import datetime, timezone

from longform import lfconfig as C
from longform import metadata

LEDGER = C.DATA / "ledger.json"


# ── Ledger ────────────────────────────────────────────────────────────────

def load_ledger() -> dict:
    if LEDGER.is_file():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"videos": {}, "playlists": {}}


def save_ledger(led: dict):
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(led, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(LEDGER)                  # atomic: a crash never leaves half a ledger


def used_game_ids(led: dict) -> set:
    """Games already spoken for by EITHER channel, in any state."""
    return {v["game"] for v in led["videos"].values()}


# ── YouTube ───────────────────────────────────────────────────────────────

def _client(account: str):
    from googleapiclient.discovery import build
    from src import publisher as shorts_pub
    creds = shorts_pub._youtube_credentials(account, allow_interactive=False)
    shorts_pub._assert_expected_channel(account, creds)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _playlist_id(yt, led: dict, account: str, title: str, description: str) -> str:
    cache = led["playlists"].setdefault(account, {})
    if title in cache:
        return cache[title]
    page = None
    while True:
        resp = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=page).execute()
        for p in resp.get("items", []):
            if p["snippet"]["title"] == title:
                cache[title] = p["id"]
                return p["id"]
        page = resp.get("nextPageToken")
        if not page:
            break
    made = yt.playlists().insert(part="snippet,status", body={
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": "public"},
    }).execute()
    cache[title] = made["id"]
    return made["id"]


def playlists_for(meta: dict) -> list:
    """(title, description) of the series this video belongs in."""
    out = []
    if meta.get("source") == "curated":
        out.append(("Greatest Chess Games of All Time",
                    "The most famous games ever played, move by move."))
    winner = meta["white"] if meta["result"] == "1-0" else meta["black"] if meta["result"] == "0-1" else None
    if winner:
        out.append((f"{winner}: Best Games", f"{winner}'s wins, every move, marked by Stockfish."))
    return out


def withdraw(led: dict, key: str, log=print):
    """Delete a video that is still PRIVATE/scheduled and put it back to "built".

    For replacing an upload with a re-render (YouTube cannot swap the file of
    an existing video). Refuses anything already public: deleting a live video
    loses its views and comments, and that is never an automatic decision.
    """
    rec = led["videos"][key]
    vid = rec.get("youtube_id")
    if vid:
        yt = _client(rec["account"])
        items = yt.videos().list(part="status", id=vid).execute().get("items", [])
        if items and items[0]["status"]["privacyStatus"] != "private":
            raise RuntimeError(f"{vid} is already {items[0]['status']['privacyStatus']} — not deleting")
        if items:
            yt.videos().delete(id=vid).execute()
            log(f"    deleted private upload {vid}")
    for k in ("youtube_id", "publish_at", "uploaded_at", "thumbnail", "playlists", "title"):
        rec.pop(k, None)
    rec["status"] = "built"
    save_ledger(led)


def retry_thumbnail(led: dict, key: str, log=print):
    """Set a scheduled video's local thumbnail through its pinned channel token."""
    from googleapiclient.http import MediaFileUpload

    rec = led["videos"][key]
    vid = rec.get("youtube_id")
    if rec.get("status") != "scheduled" or not vid:
        raise ValueError(f"{key} has no scheduled YouTube upload")
    thumb = C.ROOT / rec["dir"] / "thumbnail.jpg"
    if not thumb.is_file():
        raise FileNotFoundError(thumb)
    yt = _client(rec["account"])
    yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
    rec["thumbnail"] = "set"
    save_ledger(led)
    log(f"    thumbnail set for {key} -> {vid}")


def upload(out_dir, brand: str, publish_at: datetime, led: dict, log=print) -> dict:
    """Upload one rendered video as private, scheduled for `publish_at` (UTC)."""
    from googleapiclient.http import MediaFileUpload

    account = C.BRANDS[brand]["account"]
    md = metadata.for_dir(out_dir)
    yt = _client(account)
    at = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "snippet": {
            "title": md["title"],
            "description": md["description"],
            "tags": md["tags"],
            "categoryId": "20",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": at,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": False,
        },
    }
    media = MediaFileUpload(str(out_dir / "video.mp4"), chunksize=16 * 1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, tries = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except Exception as e:                       # transient network / 5xx
            tries += 1
            if tries > 5:
                raise
            log(f"    upload retry {tries}: {e.__class__.__name__}")
            time.sleep(5 * tries)
    vid = resp["id"]
    log(f"    uploaded {vid} as {account}, public at {at}")

    result = {"youtube_id": vid, "title": md["title"], "publish_at": at, "account": account}
    thumb = out_dir / "thumbnail.jpg"
    if thumb.is_file():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute()
            result["thumbnail"] = "set"
        except Exception as e:
            # Custom thumbnails need a phone-verified channel; the video still
            # goes out, with YouTube's own frame grab.
            result["thumbnail"] = f"failed: {str(e)[:160]}"
            log(f"    thumbnail not set: {str(e)[:160]}")
    added = []
    for ptitle, pdesc in playlists_for(md["meta"]):
        try:
            pid = _playlist_id(yt, led, account, ptitle, pdesc)
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            added.append(ptitle)
        except Exception as e:
            log(f"    playlist {ptitle!r} skipped: {str(e)[:160]}")
    result["playlists"] = added
    return result
