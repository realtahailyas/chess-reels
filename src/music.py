"""Background music bed.

Two sources, in priority order:

  1. Your own tracks in assets/music/ — used as-is, picked per video by hashing
     the puzzle id so consecutive posts do not share a bed.
  2. A procedurally generated lo-fi bed — the default, so the pipeline works
     with an empty assets folder and carries no Content ID or licensing risk.
"""

import hashlib

import numpy as np

import config
from src import audioutil

SR = config.SAMPLE_RATE

# Natural minor progression i - VI - III - VII, as semitone offsets from the
# root plus the triad quality. Moody and tension-appropriate.
_PROGRESSION = [
    (0, "min"), (8, "maj"), (3, "maj"), (10, "maj"),
]
_TRIADS = {"min": (0, 3, 7), "maj": (0, 4, 7)}

_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}


def _hash_index(key: str, n: int) -> int:
    """Stable index from a string — same puzzle always picks the same bed."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, n)


def user_tracks(mood: str | None = None):
    """Return sorted user-supplied music files, or an empty list.

    `mood` narrows the pool to config.MUSIC_MOODS[mood] — see that constant for
    why. A mood that matches no file falls back to the FULL pool: a variant
    whose track has not been dropped in yet should get some bed rather than a
    silent reel.
    """
    roots = [getattr(config, "MUSIC_DIR", None), getattr(config, "MUSIC_FALLBACK_DIR", None)]
    tracks = []
    seen = set()
    for root in roots:
        if root is None or not root.is_dir():
            continue
        for path in root.iterdir():
            if path.suffix.lower() in _AUDIO_EXT and path.is_file():
                key = path.resolve()
                if key in seen:
                    continue
                seen.add(key)
                tracks.append(path)
    tracks = sorted(tracks)
    if mood:
        patterns = [p.lower() for p in config.MUSIC_MOODS.get(mood, [])]
        picked = [t for t in tracks
                  if any(pat in t.stem.lower() for pat in patterns)]
        if picked:
            return picked
    return tracks


def _semitone(root_hz: float, steps: int) -> float:
    return root_hz * (2.0 ** (steps / 12.0))


def _adsr(n: int, attack: float, release: float) -> np.ndarray:
    """Simple attack/release envelope, lengths given as fractions of n."""
    env = np.ones(n)
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    env[:a] = np.linspace(0.0, 1.0, a)
    env[-r:] = np.linspace(1.0, 0.0, r)
    return env


def generate(duration: float, seed_key: str = "") -> np.ndarray:
    """Synthesize a lo-fi bed of `duration` seconds."""
    root = config.MUSIC_ROOTS[_hash_index(seed_key + "root", len(config.MUSIC_ROOTS))]
    bpm = config.MUSIC_BPMS[_hash_index(seed_key + "bpm", len(config.MUSIC_BPMS))]

    total = int(duration * SR) + SR
    out = np.zeros(total)

    beat = 60.0 / bpm
    bar = beat * 4
    n_bars = int(np.ceil(duration / bar)) + 1

    for b in range(n_bars):
        offset, quality = _PROGRESSION[b % len(_PROGRESSION)]
        start = int(b * bar * SR)
        n = int(bar * SR)
        if start >= total:
            break
        t = np.arange(n) / SR

        # Sustained chord pad — detuned sines, gentle swell across the bar.
        pad = np.zeros(n)
        for interval in _TRIADS[quality]:
            f = _semitone(root, offset + interval) * 4      # up two octaves
            pad += np.sin(2 * np.pi * f * t)
            pad += 0.5 * np.sin(2 * np.pi * f * 1.004 * t)  # slight detune
        pad *= _adsr(n, 0.18, 0.28) * 0.09

        # Bass root, one note per bar.
        bass_f = _semitone(root, offset)
        bass = np.sin(2 * np.pi * bass_f * t) * _adsr(n, 0.02, 0.45) * 0.20
        bass += 0.25 * np.sin(2 * np.pi * bass_f * 2 * t) * _adsr(n, 0.02, 0.45) * 0.20

        audioutil.add_at(out, pad + bass, start)

        # Soft kick on beats 1 and 3.
        for k in (0, 2):
            audioutil.add_at(out, _kick(beat), start + int(k * beat * SR), 0.55)
        # Closed hi-hat on the offbeats.
        for k in (0.5, 1.5, 2.5, 3.5):
            audioutil.add_at(out, _hat(), start + int(k * beat * SR), 0.22)

    # Low-level vinyl noise ties the layers together.
    out += np.random.randn(total) * 0.006

    peak = np.max(np.abs(out)) or 1.0
    if peak > 0.9:
        out *= 0.9 / peak
    return out[:int(duration * SR)]


def _kick(beat: float) -> np.ndarray:
    """Pitch-dropping sine thump."""
    n = int(min(0.28, beat * 0.9) * SR)
    t = np.arange(n) / SR
    f = np.linspace(110.0, 42.0, n)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 11.0)


def _hat() -> np.ndarray:
    """Short filtered noise burst."""
    n = int(0.045 * SR)
    t = np.arange(n) / SR
    noise = np.random.randn(n)
    # Crude highpass: subtract a running mean so only the hiss survives.
    kernel = 12
    smooth = np.convolve(noise, np.ones(kernel) / kernel, mode="same")
    return (noise - smooth) * np.exp(-t * 90.0) * 0.5


def _from_file(path, duration: float) -> np.ndarray:
    """Decode a user track, then loop or trim it to length with fades."""
    samples = audioutil.decode_to_mono(path, SR)
    need = int(duration * SR)
    if samples.size == 0:
        raise RuntimeError(f"empty audio file: {path}")
    if samples.size < need:
        reps = int(np.ceil(need / samples.size))
        samples = np.tile(samples, reps)
    samples = samples[:need]
    peak = np.max(np.abs(samples)) or 1.0
    if peak > 0.9:
        samples = samples * (0.9 / peak)
    return audioutil.fade(samples, config.MUSIC_FADE, SR,
                          in_seconds=config.MUSIC_FADE_IN)


def bed(duration: float, seed_key: str = "",
        mood: str | None = None) -> tuple[np.ndarray, str]:
    """Return (samples, source_label) for the music bed."""
    tracks = user_tracks(mood)
    if tracks:
        chosen = tracks[_hash_index(seed_key + "track", len(tracks))]
        try:
            return _from_file(chosen, duration), chosen.name
        except Exception:
            # A bad file must not kill the build; fall through to generated.
            pass
    return generate(duration, seed_key), "generated"
