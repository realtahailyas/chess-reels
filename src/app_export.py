"""Derived artifacts for the "app" variant: thumbnail, silent preview clip,
and the manifest.json entry that wires the generator into the PuzzleFlow app
(CHESS_APP_BLUEPRINT.md Section 13.2/13.3).

R2 upload is a separate, later step — nothing in this module touches the
network. It only produces local files (thumb/preview) and R2 *key strings*
plus a manifest.json that `scripts/import-videos.ts` reads.
"""

import json
import subprocess

import config


class ExportError(RuntimeError):
    pass


# ── Thumbnail: single frame at t=0.5s, scaled to 720x1280 ───────────────────

def thumb_command(video_path, out_path, at=None, width=None, height=None):
    """Pure ffmpeg command builder — unit-testable without invoking ffmpeg."""
    at = config.APP_THUMB_TIME if at is None else at
    width = config.APP_THUMB_W if width is None else width
    height = config.APP_THUMB_H if height is None else height
    return [
        config.FFMPEG, "-y",
        "-ss", str(at),
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}",
        "-q:v", "3",
        str(out_path),
    ]


def make_thumb(video_path, out_path, at=None, width=None, height=None):
    """Grab a single frame as a JPEG poster (720x1280 by default)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = thumb_command(video_path, out_path, at, width, height)
    proc = subprocess.run(cmd, capture_output=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise ExportError("ffmpeg thumb failed:\n" + "\n".join(tail))
    return out_path


# ── Preview: first 3s, video-only, aggressively compressed ──────────────────

def preview_command(video_path, out_path, duration=None, width=None,
                    height=None, crf=None, preset=None):
    """Pure ffmpeg command builder — unit-testable without invoking ffmpeg."""
    duration = config.APP_PREVIEW_DURATION if duration is None else duration
    width = config.APP_PREVIEW_W if width is None else width
    height = config.APP_PREVIEW_H if height is None else height
    crf = config.APP_PREVIEW_CRF if crf is None else crf
    preset = config.APP_PREVIEW_PRESET if preset is None else preset
    return [
        config.FFMPEG, "-y",
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", f"scale={width}:{height}",
        "-an",
        "-c:v", config.VIDEO_CODEC,
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", config.PIX_FMT,
        "-movflags", "+faststart",
        str(out_path),
    ]


def make_preview(video_path, out_path, duration=None, width=None, height=None,
                 crf=None, preset=None):
    """First N seconds, no audio, small/looped-friendly (~120 KB target)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = preview_command(video_path, out_path, duration, width, height, crf, preset)
    proc = subprocess.run(cmd, capture_output=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise ExportError("ffmpeg preview failed:\n" + "\n".join(tail))
    return out_path


# ── Manifest (Section 13.3) ──────────────────────────────────────────────────

def manifest_theme(themes) -> str:
    """Pick the PuzzleFlow theme slug (Section 3.3) best matching this puzzle.

    This reel pipeline's own Lichess filter is sacrifice-only, so a puzzle
    usually carries several tags; the app's fixed 17-slug taxonomy wants
    exactly one. First match, in the fixed list's order, wins — "sacrifice"
    is always a safe fallback since every puzzle here already qualifies.
    """
    tags = set(themes or [])
    for slug in config.APP_THEME_SLUGS:
        if slug in tags:
            return slug
    return "sacrifice"


def manifest_entry(meta: dict) -> dict:
    """Build one manifest.json record (Section 13.3) from a finished build's
    meta.json.

    `fen`/`solution_uci` are the RAW pre-setup Lichess pair (setup move
    first) — the app auto-plays moves[0] before the player takes over — NOT
    the post-setup `fen`/`solution` this renderer itself animates.
    """
    pid = meta["puzzle_id"]
    caption = meta.get("caption", {})
    return {
        "puzzle_id": pid,
        "fen": meta["lichess_fen"],
        "solution_uci": meta["lichess_moves"],
        "theme": manifest_theme(meta.get("themes", [])),
        "rating": meta["rating"],
        "duration_ms": int(round(meta["video"]["duration"] * 1000)),
        "r2_key": f"{config.R2_APP_PREFIX}/{pid}.mp4",
        "thumb_key": f"{config.R2_THUMB_PREFIX}/{pid}.jpg",
        "preview_key": f"{config.R2_PREVIEW_PREFIX}/{pid}.mp4",
        "caption": caption.get("caption", ""),
        "hook_text": caption.get("hook", ""),
    }


def load_manifest(path=None) -> list:
    path = config.MANIFEST_PATH if path is None else path
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def write_manifest(entries, path=None):
    path = config.MANIFEST_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return path


def merge_manifest(new_entries, path=None) -> list:
    """Upsert entries by puzzle_id: existing order is kept, new ids append."""
    path = config.MANIFEST_PATH if path is None else path
    existing = load_manifest(path)
    by_id = {e["puzzle_id"]: e for e in existing}
    order = [e["puzzle_id"] for e in existing]
    for entry in new_entries:
        pid = entry["puzzle_id"]
        if pid not in by_id:
            order.append(pid)
        by_id[pid] = entry
    merged = [by_id[pid] for pid in order]
    write_manifest(merged, path)
    return merged


def export_one(meta: dict, video_path, variant_dir, log=print) -> dict:
    """Build thumb + preview for one finished app-variant video.

    Returns the manifest entry; does not write manifest.json itself — the
    caller merges once after a whole batch so one bad video cannot clobber
    entries already written for others in the same run.
    """
    pid = meta["puzzle_id"]
    thumb_path = variant_dir / "thumb" / f"{pid}.jpg"
    preview_path = variant_dir / "preview" / f"{pid}.mp4"

    make_thumb(video_path, thumb_path)
    log(f"        thumb   {thumb_path}")

    make_preview(video_path, preview_path)
    size_kb = preview_path.stat().st_size / 1e3
    log(f"        preview {preview_path} ... {size_kb:.0f} KB")

    return manifest_entry(meta)
