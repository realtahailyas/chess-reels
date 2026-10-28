"""Synthesized sound effects.

Everything is generated with numpy — no sample files, so there is no licensing
exposure and nothing to ship alongside the code.
"""

import functools

import numpy as np

import config

SR = config.SAMPLE_RATE


def _t(seconds: float, sr: int):
    n = int(seconds * sr)
    return n, np.arange(n) / sr


def sfx_move(sr=SR):
    """Short wooden click, ~90 ms."""
    n, t = _t(0.09, sr)
    sig = np.random.randn(n) * np.exp(-t * 55) * 0.5        # attack noise
    sig += 0.4 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 40)   # wood body
    sig += 0.2 * np.sin(2 * np.pi * 420 * t) * np.exp(-t * 60)   # overtone
    return sig * 0.8


def sfx_capture(sr=SR):
    """Heavier thud with low body, ~160 ms."""
    n, t = _t(0.16, sr)
    sig = np.random.randn(n) * np.exp(-t * 22) * 0.6
    sig += 0.55 * np.sin(2 * np.pi * 110 * t) * np.exp(-t * 18)
    sig += 0.30 * np.sin(2 * np.pi * 70 * t) * np.exp(-t * 12)
    return sig * 0.9


def sfx_check(sr=SR):
    """Rising two-tone sting, ~420 ms."""
    n, t = _t(0.42, sr)
    f = np.linspace(600, 1250, n)                            # rising sweep
    sig = 0.5 * np.sin(2 * np.pi * np.cumsum(f) / sr)
    sig += 0.3 * np.sin(2 * np.pi * np.cumsum(f * 1.5) / sr)
    return sig * np.exp(-t * 4.5) * 0.75


def sfx_mate(sr=SR):
    """Low boom plus a G minor stab, ~1.1 s."""
    n, t = _t(1.1, sr)
    sig = 0.7 * np.sin(2 * np.pi * np.linspace(90, 45, n) * t) * np.exp(-t * 3.2)
    for f in (196, 233, 294, 392):                           # G minor
        sig += 0.22 * np.sin(2 * np.pi * f * t) * np.exp(-t * 2.6)
    sig += np.random.randn(n) * np.exp(-t * 30) * 0.3
    return sig * 0.85


def sfx_tick(sr=SR):
    """Sharp high click for each countdown numeral, ~60 ms."""
    n, t = _t(0.06, sr)
    sig = np.random.randn(n) * np.exp(-t * 120) * 0.4
    sig += 0.5 * np.sin(2 * np.pi * 1400 * t) * np.exp(-t * 90)
    return sig * 0.7


def sfx_whoosh(sr=SR):
    """Filtered noise sweep as a piece starts moving, ~300 ms.

    A one-pole lowpass whose cutoff rides a 300->3000 Hz sweep, shaped by a
    Hann-squared envelope so it swells and dies rather than clicking.
    """
    n, t = _t(0.30, sr)
    noise = np.random.randn(n)
    cutoff = np.linspace(300.0, 3000.0, n)
    alpha = 1.0 - np.exp(-2 * np.pi * cutoff / sr)
    out = np.empty(n)
    prev = 0.0
    for i in range(n):
        prev += alpha[i] * (noise[i] - prev)
        out[i] = prev
    env = np.hanning(n) ** 2
    peak = np.max(np.abs(out)) or 1.0
    return out / peak * env * 0.55


_REGISTRY = {
    "move": sfx_move,
    "capture": sfx_capture,
    "check": sfx_check,
    "mate": sfx_mate,
    "tick": sfx_tick,
    "whoosh": sfx_whoosh,
}


# Noise-driven synths overshoot 1.0 on some seeds, and the mix gain alone does
# not tame that, so each effect is peak-normalized to keep its shape without
# distorting when several land together.
PEAK_TARGET = 0.9


@functools.lru_cache(maxsize=16)
def get(name: str) -> np.ndarray:
    """Return a cached, peak-normalized SFX buffer by name."""
    if name not in _REGISTRY:
        raise KeyError(f"unknown sfx: {name}")
    buf = _REGISTRY[name]()
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > PEAK_TARGET:
        buf = buf * (PEAK_TARGET / peak)
    return buf


def names():
    return sorted(_REGISTRY)
