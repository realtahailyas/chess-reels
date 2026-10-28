"""Audio mixing: an event timeline rendered to a single WAV.

Frame generation records when things happen; this module turns that list into
audio once, at the end. Keeping it declarative means audio and video stay in
sync by construction rather than by two parallel sets of timing code.
"""

import numpy as np

import config
from src import audioutil, music, sfx

SR = config.SAMPLE_RATE


class AudioEvent:
    """A scheduled sound. `payload` is an SFX name or a Voiceover."""

    __slots__ = ("time", "kind", "payload")

    def __init__(self, time: float, kind: str, payload):
        self.time = float(time)
        self.kind = kind
        self.payload = payload


def _segment_durations(events):
    """Yield (start_sec, dur_sec, floor_db) for each voiceover/reaction segment.

    Voiceover ducks the music a little; the reaction ducks it substantially and
    keeps the clip's own audio up front. Voiceover never overlaps the reaction,
    so a single min-combined envelope is enough.
    """
    for ev in events:
        if ev.kind == "vo" and ev.payload is not None and ev.payload.duration > 0:
            yield ev.time, ev.payload.duration, config.DUCK_DB
        elif ev.kind == "reaction" and ev.payload is not None and ev.payload.size:
            yield ev.time, ev.payload.size / SR, config.REACTION_DUCK_DB


def _duck_envelope(duration: float, events) -> np.ndarray:
    """Gain curve that dips the music under each voiceover and reaction segment."""
    n = int(duration * SR) + SR
    env = np.ones(n)
    attack = max(1, int(config.DUCK_ATTACK * SR))
    release = max(1, int(config.DUCK_RELEASE * SR))

    for start_sec, dur_sec, floor_db in _segment_durations(events):
        floor = 10.0 ** (floor_db / 20.0)
        start = int(start_sec * SR)
        end = start + int(dur_sec * SR)

        a0, a1 = max(0, start - attack), max(0, start)
        if a1 > a0:
            env[a0:a1] = np.minimum(env[a0:a1], np.linspace(1.0, floor, a1 - a0))
        b0, b1 = max(0, start), min(n, end)
        if b1 > b0:
            env[b0:b1] = np.minimum(env[b0:b1], floor)
        c0, c1 = min(n, end), min(n, end + release)
        if c1 > c0:
            env[c0:c1] = np.minimum(env[c0:c1], np.linspace(floor, 1.0, c1 - c0))
    return env


def verify(track: np.ndarray) -> dict:
    """Measure the mix and flag silence, clipping and dead air."""
    peak = float(np.max(np.abs(track))) if track.size else 0.0
    overall = audioutil.rms(track)

    window = int(config.AUDIO_DEAD_WINDOW * SR)
    dead = False
    if track.size >= window:
        # Sliding RMS via a cumulative sum of squares — one pass, no loop.
        squares = np.concatenate(([0.0], np.cumsum(track.astype(np.float64) ** 2)))
        step = max(1, window // 8)
        starts = np.arange(0, track.size - window + 1, step)
        win_rms = np.sqrt((squares[starts + window] - squares[starts]) / window)
        dead = bool(np.any(win_rms < config.AUDIO_DEAD_RMS))

    return {
        "peak": round(peak, 4),
        "rms": round(overall, 4),
        "dead_air": dead,
        "ok": (peak <= config.AUDIO_PEAK_MAX
               and config.AUDIO_RMS_MIN <= overall <= config.AUDIO_RMS_MAX
               and not dead),
    }


def mix(events, duration: float, out_path, seed_key: str = "",
        mood: str | None = None) -> dict:
    """Render the timeline to a 16-bit mono WAV and return a report."""
    total = int(duration * SR) + SR
    track = np.zeros(total, dtype=np.float64)

    bed, source = music.bed(duration, seed_key, mood=mood)
    ducked = bed * _duck_envelope(duration, events)[:bed.size]
    audioutil.add_at(track, ducked, 0, config.GAIN_MUSIC)

    for ev in events:
        at = int(ev.time * SR)
        if ev.kind == "sfx":
            audioutil.add_at(track, sfx.get(ev.payload), at, config.GAIN_SFX)
        elif ev.kind == "vo" and ev.payload is not None:
            audioutil.add_at(track, ev.payload.samples, at, config.GAIN_VO)
        elif ev.kind == "reaction" and ev.payload is not None and ev.payload.size:
            # Reaction audio goes into the same track at its offset; the music
            # is already ducked deep under it by _duck_envelope.
            audioutil.add_at(track, ev.payload, at, config.REACTION_GAIN)

    np.clip(track, -1.0, 1.0, out=track)
    peak = float(np.max(np.abs(track))) or 1.0
    track *= config.NORMALIZE_PEAK / peak

    audioutil.write_wav(out_path, track)

    report = verify(track)
    report["music"] = source
    report["duration"] = round(track.size / SR, 2)
    return report
