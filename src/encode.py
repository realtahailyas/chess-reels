"""FFmpeg encoding and post-encode verification.

A file existing is not proof of a good render: a missing audio stream or a
truncated video both leave a plausible-looking MP4 behind. Everything is
checked with ffprobe before a puzzle counts as done.
"""

import json
import subprocess

import config


class EncodeError(RuntimeError):
    pass


def encode(frames_dir, audio_wav, output_mp4, fps: int = None, crf=None,
          preset=None, audio_bitrate=None, audio_channels=None) -> "config.Path":
    """Encode a PNG frame sequence plus a WAV into an H.264/AAC MP4.

    `crf`/`preset`/`audio_bitrate`/`audio_channels` default to the module-wide
    config values, so existing callers (and the "simple"/"reaction" variants)
    get the exact command they always have. `audio_channels` only appends
    `-ac` when given — omitting it (None) leaves ffmpeg to keep the source WAV's
    channel layout, which is already mono today.
    """
    fps = fps or config.FPS
    crf = config.CRF if crf is None else crf
    preset = config.PRESET if preset is None else preset
    audio_bitrate = config.AUDIO_BITRATE if audio_bitrate is None else audio_bitrate
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        config.FFMPEG, "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "f%05d.png"),
        "-i", str(audio_wav),
        "-c:v", config.VIDEO_CODEC,
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", config.PIX_FMT,
        "-c:a", "aac",
        "-b:a", audio_bitrate,
    ]
    if audio_channels:
        cmd += ["-ac", str(audio_channels)]
    cmd += [
        "-movflags", "+faststart",
        "-shortest",
        str(output_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        raise EncodeError("ffmpeg failed:\n" + "\n".join(tail))
    return output_mp4


def probe(path) -> dict:
    """Return width, height, codecs, duration and size for an encoded file."""
    cmd = [
        config.FFPROBE, "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    if proc.returncode != 0:
        raise EncodeError(
            "ffprobe failed: " + proc.stderr.decode("utf-8", "replace").strip()[:300]
        )
    data = json.loads(proc.stdout.decode("utf-8", "replace"))

    video = next((s for s in data.get("streams", [])
                  if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", [])
                  if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})

    return {
        "width": int(video["width"]) if video else 0,
        "height": int(video["height"]) if video else 0,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "audio_channels": int(audio["channels"]) if audio and "channels" in audio else None,
        "duration": float(fmt.get("duration", 0.0)),
        "filesize": int(fmt.get("size", 0)),
    }


def verify(path, duration_min=None, duration_max=None, size=None) -> dict:
    """Raise EncodeError unless the file meets the output spec.

    `size` is (w, h) for output that is deliberately not the vertical canvas —
    the Play Store promo video is landscape, and Play is the one surface that
    will not take 9:16. Everything else leaves it None and gets the hard
    1080x1920 check, which is what catches a frame-size mistake before upload.
    """
    info = probe(path)
    problems = []

    dur_min = config.ENCODE_DURATION_MIN if duration_min is None else duration_min
    dur_max = config.ENCODE_DURATION_MAX if duration_max is None else duration_max

    want_w, want_h = size or (config.CANVAS_W, config.CANVAS_H)
    if info["width"] != want_w or info["height"] != want_h:
        problems.append(
            f"expected {want_w}x{want_h}, "
            f"got {info['width']}x{info['height']}"
        )
    if info["video_codec"] != "h264":
        problems.append(f"video codec is {info['video_codec']}, expected h264")
    if info["audio_codec"] != "aac":
        problems.append(f"audio codec is {info['audio_codec']}, expected aac")
    if not (dur_min < info["duration"] < dur_max):
        problems.append(f"duration {info['duration']:.1f}s out of range")
    if info["filesize"] <= config.MIN_FILESIZE:
        problems.append(f"file is only {info['filesize']} bytes")

    if problems:
        raise EncodeError("; ".join(problems))
    return info


def encode_and_verify(frames_dir, audio_wav, output_mp4, fps=None, crf=None,
                      preset=None, audio_bitrate=None, audio_channels=None,
                      duration_min=None, duration_max=None, size=None) -> dict:
    encode(frames_dir, audio_wav, output_mp4, fps, crf=crf, preset=preset,
           audio_bitrate=audio_bitrate, audio_channels=audio_channels)
    return verify(output_mp4, duration_min=duration_min,
                  duration_max=duration_max, size=size)
