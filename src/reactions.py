"""Reaction clip selection and decoding for variant B.

Selection is deterministic (same puzzle -> same clip) and reads durations from
the manifest written by prepare_reactions.py. Decoding a chosen clip into frames
and audio happens at build time, but the *timing* decision (how long to hold)
always comes from the manifest, never from probing files.

Everything here degrades gracefully: a missing manifest, empty category, or a
decode failure returns "no reaction" so the build still produces a video.
"""

import json
import random
import subprocess

import numpy as np
from PIL import Image

import config
from src import audioutil


def load_manifest(path=None) -> dict:
    """Read the reaction manifest, or {} if absent/unreadable."""
    path = path or config.REACTION_MANIFEST
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


class Reaction:
    """A selected clip: file path and its manifest duration."""

    __slots__ = ("path", "duration", "category", "file")

    def __init__(self, path, duration, category, file):
        self.path = path
        self.duration = float(duration)
        self.category = category
        self.file = file


def select(puzzle: dict, manifest=None, rng=None) -> Reaction | None:
    """Pick one clip for a puzzle at random. None if none available.

    Uses the puzzle's category, falling back to the whole pool if that category
    is empty, so a category with no clips never means "no reaction" when other
    clips exist. Selection is random per build (pass `rng` for reproducible
    tests).
    """
    manifest = load_manifest() if manifest is None else manifest
    if not manifest:
        return None

    category = config.reaction_category(puzzle)
    # (category, entry) pairs so the fallback pool keeps each clip's folder.
    scoped = [(category, e) for e in manifest.get(category, [])]
    pool = scoped or [(cat, e) for cat, entries in sorted(manifest.items())
                      for e in entries]
    if not pool:
        return None

    picker = rng or random
    cat, entry = picker.choice(pool)
    path = config.REACTION_DIR / cat / entry["file"]
    if not path.exists():
        return None
    return Reaction(path, entry["duration"], cat, entry["file"])


def load_frames(reaction: Reaction, fps=None):
    """Decode the clip to a list of band-sized RGB PIL images at `fps`.

    Streams raw RGB straight from ffmpeg (no temp PNGs). Returns [] on failure
    so the caller can fall back to the idle band.
    """
    fps = fps or config.FPS
    w, h = config.REACTION_BAND_W, config.REACTION_BAND_H
    cmd = [
        config.FFMPEG, "-v", "error", "-i", str(reaction.path),
        "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
        "-pix_fmt", "rgb24", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    if proc.returncode != 0 or not proc.stdout:
        return []
    frame_bytes = w * h * 3
    count = len(proc.stdout) // frame_bytes
    if count == 0:
        return []
    arr = np.frombuffer(proc.stdout[:count * frame_bytes], dtype=np.uint8)
    arr = arr.reshape(count, h, w, 3)
    return [Image.fromarray(arr[i]) for i in range(count)]


def load_audio(reaction: Reaction):
    """Decode the clip's audio to a mono float array at the project rate."""
    try:
        return audioutil.decode_to_mono(reaction.path)
    except Exception:
        return np.zeros(0)
