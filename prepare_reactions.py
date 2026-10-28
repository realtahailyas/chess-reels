"""One-time normalisation of raw reaction clips.

Reads reactions_raw/<category>/<clip> and writes drop-in-ready copies to
reactions/<category>/<clip>.mp4 plus reactions/manifest.json. Run this whenever
you add or change raw clips; the build never touches the raw folder.

    python prepare_reactions.py

Each clip is:
  * trimmed to REACTION_MAX_DURATION from the START (the peak of a reaction is
    in the first moment) — after applying config.REACTION_CLIP_TRIM for the
    clips whose reaction is delayed,
  * scaled and centre-cropped to exactly the bottom-band dimensions (crop, not
    letterbox — clips arrive in mixed aspect ratios),
  * faded out over the final REACTION_FADE seconds (video and audio),
  * loudness-normalised (clips arrive at wildly different volumes),
  * re-encoded at the project frame rate so the build can composite it 1:1.

The manifest records each clip's actual duration; the build reads that and
never probes clip files itself.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config


def _probe_duration(path) -> float:
    cmd = [config.FFPROBE, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _clip_trim(src: Path) -> tuple[float, float]:
    """(head trim, max length) for this clip — see config.REACTION_CLIP_TRIM."""
    for key, spec in config.REACTION_CLIP_TRIM.items():
        if key.lower() in src.name.lower():
            if isinstance(spec, (tuple, list)):
                return float(spec[0]), float(spec[1])
            return float(spec), config.REACTION_MAX_DURATION
    return 0.0, config.REACTION_MAX_DURATION


def _normalise(src: Path, dst: Path) -> float | None:
    """Normalise one clip. Returns the output duration, or None on failure."""
    src_dur = _probe_duration(src)
    if src_dur <= 0:
        print(f"    skip (unreadable): {src.name}")
        return None

    # Head trim first, so REACTION_MAX_DURATION is measured from the moment the
    # reaction actually starts rather than from the clip's own first frame.
    start, max_dur = _clip_trim(src)
    if start >= src_dur:
        print(f"    skip (start offset {start}s past end): {src.name}")
        return None
    if start or max_dur != config.REACTION_MAX_DURATION:
        print(f"    trim: skip {start}s, keep at most {max_dur}s")

    dur = min(src_dur - start, max_dur)
    fade = min(config.REACTION_FADE, dur / 2)
    fade_start = max(0.0, dur - fade)
    w, h = config.REACTION_BAND_W, config.REACTION_BAND_H

    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
          f"crop={w}:{h},fps={config.FPS},"
          f"fade=t=out:st={fade_start:.3f}:d={fade:.3f}")
    af = (f"loudnorm={config.REACTION_LOUDNORM},"
          f"afade=t=out:st={fade_start:.3f}:d={fade:.3f}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.FFMPEG, "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
        "-vf", vf, "-af", af,
        "-r", str(config.FPS),
        "-c:v", config.VIDEO_CODEC, "-preset", config.PRESET, "-crf", str(config.CRF),
        "-pix_fmt", config.PIX_FMT,
        "-c:a", "aac", "-b:a", config.AUDIO_BITRATE, "-ar", str(config.SAMPLE_RATE),
        "-movflags", "+faststart",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        print(f"    FAILED {src.name}: {' / '.join(tail)}")
        return None

    # Record the ACTUAL output duration, not the requested one.
    return round(_probe_duration(dst), 3)


def main() -> int:
    raw = config.REACTION_RAW_DIR
    if not raw.is_dir():
        raw.mkdir(parents=True, exist_ok=True)
        print(f"created {raw} — drop raw clips into <category>/ subfolders, "
              f"then rerun")
        return 0

    # Each category is a subfolder; loose files in the root become "default",
    # so you can just drop clips in without organising them into categories.
    sources = {}
    loose = [p for p in sorted(raw.iterdir())
             if p.is_file() and p.suffix.lower() in config.REACTION_VIDEO_EXT]
    if loose:
        sources[config.REACTION_DEFAULT_CATEGORY] = loose
    for category_dir in sorted(p for p in raw.iterdir() if p.is_dir()):
        files = [p for p in sorted(category_dir.iterdir())
                 if p.suffix.lower() in config.REACTION_VIDEO_EXT]
        if files:
            sources.setdefault(category_dir.name, []).extend(files)

    manifest: dict[str, list] = {}
    total = 0
    for category, files in sorted(sources.items()):
        entries = []
        for src in files:
            dst = config.REACTION_DIR / category / (src.stem + ".mp4")
            print(f"  [{category}] {src.name}")
            dur = _normalise(src, dst)
            if dur:
                entries.append({"file": dst.name, "duration": dur})
                total += 1
        if entries:
            manifest[category] = entries

    config.REACTION_DIR.mkdir(parents=True, exist_ok=True)
    config.REACTION_MANIFEST.write_text(json.dumps(manifest, indent=2),
                                        encoding="utf-8")
    cats = ", ".join(f"{k}:{len(v)}" for k, v in manifest.items()) or "none"
    print(f"\nnormalised {total} clip(s) across categories [{cats}]")
    print(f"manifest: {config.REACTION_MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
