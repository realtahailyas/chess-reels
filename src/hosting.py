"""Free, instant public hosting for the one file Instagram insists on fetching
itself.

Instagram's Content Publishing API takes a `video_url` and fetches it
server-side — there is no direct file-upload path, unlike Facebook and
YouTube. With Supabase and Cloudflare both ruled out, the cheapest reliable
public host that needs zero new infrastructure is a public GitHub repo: the
Contents API accepts a base64 PUT and the file is live at
raw.githubusercontent.com immediately, no deploy/build step to wait on.

Files are left in the repo afterward — cleanup isn't worth the complexity,
and the content is public on social media seconds later anyway.
"""

import base64
import os

import requests

import config

API_ROOT = "https://api.github.com"

# Reel uploads are committed as the token owner: one commit per published
# reel. High-frequency status writes use a bot identity instead
# (see status_bridge.BOT_IDENTITY).


class HostingError(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise HostingError("GITHUB_TOKEN is not set (see .env.example)")
    return token


def push(video_path, puzzle_id: str) -> str:
    """Upload video_path to the CDN repo, return its raw.githubusercontent.com URL."""
    repo = config.GITHUB_REPO
    if not repo:
        raise HostingError("GITHUB_REPO is not set (see .env.example)")

    video_path = str(video_path)
    remote_path = f"reels/{puzzle_id}.mp4"
    with open(video_path, "rb") as fh:
        content_b64 = base64.b64encode(fh.read()).decode("ascii")

    url = f"{API_ROOT}/repos/{repo}/contents/{remote_path}"
    headers = {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
    }

    # If it's already there (a retry), the update needs the existing blob's
    # sha — GitHub rejects a PUT that omits it for an existing file.
    sha = None
    existing = requests.get(url, headers=headers, params={"ref": config.GITHUB_BRANCH})
    if existing.status_code == 200:
        sha = existing.json().get("sha")

    body = {
        "message": f"reel: {puzzle_id}",
        "content": content_b64,
        "branch": config.GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha

    resp = requests.put(url, headers=headers, json=body, timeout=60)
    if resp.status_code not in (200, 201):
        raise HostingError(f"GitHub upload failed ({resp.status_code}): {resp.text[:300]}")

    return f"https://raw.githubusercontent.com/{repo}/{config.GITHUB_BRANCH}/{remote_path}"
