"""Shared audio helpers: decoding via ffmpeg and WAV writing."""

import subprocess
import wave

import numpy as np

import config


def decode_to_mono(path, sr: int = None) -> np.ndarray:
    """Decode any audio file to a mono float32 array at `sr`.

    Streams raw floats straight out of ffmpeg rather than via a temp WAV, which
    keeps voiceover assembly cheap when a batch generates hundreds of clips.
    """
    sr = sr or config.SAMPLE_RATE
    cmd = [
        config.FFMPEG, "-v", "error", "-i", str(path),
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ac", "1", "-ar", str(sr), "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, creationflags=config.SUBPROCESS_NO_WINDOW)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(
            f"ffmpeg could not decode {path}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()[:300]}"
        )
    return np.frombuffer(proc.stdout, dtype=np.float32).astype(np.float64)


def write_wav(path, samples: np.ndarray, sr: int = None):
    """Write a mono float array in [-1, 1] as a 16-bit PCM WAV."""
    sr = sr or config.SAMPLE_RATE
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(pcm.tobytes())


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples))))


def add_at(track: np.ndarray, clip: np.ndarray, start_sample: int, gain: float = 1.0):
    """Mix `clip` into `track` at a sample offset, truncating at the end."""
    if clip.size == 0 or start_sample >= track.size:
        return
    start = max(0, start_sample)
    end = min(track.size, start + clip.size)
    if end <= start:
        return
    track[start:end] += clip[:end - start] * gain


def fade(samples: np.ndarray, seconds: float, sr: int = None,
         in_seconds: float = None) -> np.ndarray:
    """Apply a linear fade in and out, in place-safe fashion.

    `in_seconds` overrides the fade IN only. The two ends want different
    lengths: a reel opens on its music, so ramping the first half-second up
    from silence wastes the half-second that decides retention, while the tail
    still needs a real fade because it lands under the end card.
    """
    sr = sr or config.SAMPLE_RATE
    n_out = int(seconds * sr)
    n_in = int((seconds if in_seconds is None else in_seconds) * sr)
    if samples.size < n_in + n_out or (n_in <= 0 and n_out <= 0):
        return samples
    out = samples.copy()
    if n_in > 0:
        out[:n_in] *= np.linspace(0.0, 1.0, n_in)
    if n_out > 0:
        out[-n_out:] *= np.linspace(1.0, 0.0, n_out)
    return out
