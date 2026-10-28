"""Move narration: SAN to spoken text, and text to audio.

Engines are tried in order and none of them raise:

  edge-tts  neural, free, no API key — needs speech.platform.bing.com
  piper     offline neural, near edge quality — needs a downloaded model
  sapi      Windows System.Speech, robotic but fully offline
  silence   correctly-sized silence, so a failed clip cannot desync the video

edge-tts alone would be enough on an unrestricted connection, but its endpoint
is blocked by some ISPs, and a silent reel is a wasted render.
"""

import asyncio
import functools
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import chess
import numpy as np

import config
from src import audioutil

PIECE_WORDS = {"K": "king", "Q": "queen", "R": "rook",
               "B": "bishop", "N": "knight", "P": "pawn"}
FILE_WORDS = {"a": "A", "b": "B", "c": "C", "d": "D",
              "e": "E", "f": "F", "g": "G", "h": "H"}

# Rough speaking rate used to size the silence fallback and to sanity-check
# clip lengths.
WORDS_PER_SECOND = 2.6


def move_to_speech(board: chess.Board, move: chess.Move):
    """Return (spoken_text, san) for a move in the given position.

    Built from the board state rather than by parsing the SAN string, so
    disambiguated notation like Nbd2 never leaks into the narration.
    """
    san = board.san(move)
    if board.is_castling(move):
        text = ("castles king side" if chess.square_file(move.to_square) > 4
                else "castles queen side")
    else:
        piece = board.piece_at(move.from_square)
        name = PIECE_WORDS[piece.symbol().upper()]
        verb = "takes" if board.is_capture(move) else "to"
        sq = chess.square_name(move.to_square)
        # Files are uppercased because TTS engines pronounce a lone lowercase
        # "h" as "aitch" inconsistently. Ranks stay as digits — those read fine.
        text = f"{name} {verb} {FILE_WORDS[sq[0]]} {sq[1]}"

    if move.promotion:
        text += f", promotes to {PIECE_WORDS[chess.piece_symbol(move.promotion).upper()]}"

    if "#" in san:
        text += ". Checkmate."
    elif "+" in san:
        text += ", check"
    return text, san


def estimate_duration(text: str) -> float:
    """Estimated spoken length, used when synthesis is unavailable."""
    words = max(1, len(text.split()))
    return max(0.6, words / WORDS_PER_SECOND)


async def _edge(text, path, voice, rate, pitch):
    import edge_tts
    tts = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await tts.save(str(path))


def edge_speak(text: str, path, voice=None) -> bool:
    """Synthesize to `path` with edge-tts. Returns True on success."""
    try:
        asyncio.run(_edge(text, path,
                          voice=voice or config.TTS_VOICE,
                          rate=config.TTS_RATE,
                          pitch=config.TTS_PITCH))
        return Path(path).exists() and Path(path).stat().st_size > 0
    except Exception:
        return False


_SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [IO.File]::ReadAllText($args[0], [Text.Encoding]::UTF8)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
foreach ($v in $synth.GetInstalledVoices()) {
  if ($v.VoiceInfo.Name -like "*$($args[2])*") { $synth.SelectVoice($v.VoiceInfo.Name); break }
}
$synth.Rate = [int]$args[3]
$synth.SetOutputToWaveFile($args[1])
$synth.Speak($text)
$synth.Dispose()
"""


def sapi_speak(text: str, path, voice=None) -> bool:
    """Synthesize with the Windows speech engine. Returns True on success.

    The text is passed via a file rather than the command line so quotes and
    non-ASCII characters cannot break or inject into the script.
    """
    if os.name != "nt":
        return False

    txt_file = script_file = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(text)
            txt_file = fh.name
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(_SAPI_SCRIPT)
            script_file = fh.name

        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", script_file,
             txt_file, str(Path(path).resolve()),
             voice or config.SAPI_VOICE, str(config.SAPI_RATE)],
            capture_output=True, timeout=config.TTS_TIMEOUT,
            creationflags=config.SUBPROCESS_NO_WINDOW,
        )
        return (proc.returncode == 0 and Path(path).exists()
                and Path(path).stat().st_size > 0)
    except Exception:
        return False
    finally:
        for tmp in (txt_file, script_file):
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


def _piper_paths():
    onnx = config.PIPER_DIR / f"{config.PIPER_VOICE}.onnx"
    cfg = config.PIPER_DIR / f"{config.PIPER_VOICE}.onnx.json"
    return onnx, cfg


@functools.lru_cache(maxsize=1)
def _piper_voice():
    """Load the Piper voice once, or return None if the model is absent."""
    onnx, cfg = _piper_paths()
    if not (onnx.exists() and cfg.exists()):
        return None
    try:
        from piper import PiperVoice
        return PiperVoice.load(str(onnx), str(cfg))
    except Exception:
        return None


def piper_speak(text: str, path) -> bool:
    """Synthesize with the offline Piper model. Returns True on success."""
    voice = _piper_voice()
    if voice is None:
        return False
    try:
        try:
            from piper import SynthesisConfig
            syn = SynthesisConfig(length_scale=config.PIPER_LENGTH_SCALE)
        except Exception:
            syn = None
        with wave.open(str(path), "wb") as wav:
            if syn is not None:
                voice.synthesize_wav(text, wav, syn_config=syn)
            else:
                voice.synthesize_wav(text, wav)
        return Path(path).exists() and Path(path).stat().st_size > 0
    except Exception:
        return False


def download_piper_model(log=print, attempts: int = 8) -> bool:
    """Fetch the Piper voice model + config, retrying past intermittent resets.

    The model host is subject to the same flaky network as edge-tts on some
    connections, so each file is retried rather than failing on the first drop.
    """
    import requests
    config.PIPER_DIR.mkdir(parents=True, exist_ok=True)
    onnx, cfg = _piper_paths()

    for target, min_size in ((onnx, 1_000_000), (cfg, 500)):
        if target.exists() and target.stat().st_size >= min_size:
            continue
        url = config.PIPER_VOICE_URL.format(file=target.name)
        for attempt in range(1, attempts + 1):
            try:
                with requests.get(url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(target, "wb") as fh:
                        for chunk in r.iter_content(1 << 20):
                            fh.write(chunk)
                if target.stat().st_size >= min_size:
                    log(f"  {target.name} ok ({target.stat().st_size/1e6:.1f} MB)")
                    break
            except Exception as exc:
                log(f"  {target.name} attempt {attempt} failed: {type(exc).__name__}")
                time.sleep(2)
        else:
            log(f"FAILED to download {target.name}")
            return False

    _piper_voice.cache_clear()
    return True


class Voiceover:
    """One narration clip: samples, duration, and how it was produced."""

    __slots__ = ("text", "samples", "duration", "source")

    def __init__(self, text, samples, duration, source):
        self.text = text
        self.samples = samples
        self.duration = duration
        self.source = source

    @property
    def ok(self) -> bool:
        """True when real narration was produced (any engine, not silence)."""
        return self.source != "silence" and self.samples.size > 0


def _try_engine(engine: str, text: str, path_base: Path, voice):
    """Run one engine and decode its output, or return None."""
    if engine == "edge":
        out = path_base.with_suffix(".mp3")
        ok = edge_speak(text, out, voice)
    elif engine == "piper":
        out = path_base.with_suffix(".piper.wav")
        ok = piper_speak(text, out)
    elif engine == "sapi":
        out = path_base.with_suffix(".sapi.wav")
        ok = sapi_speak(text, out, None)
    else:
        return None
    if not ok:
        return None
    try:
        samples = audioutil.decode_to_mono(out)
    except Exception:
        return None
    if not samples.size:
        return None
    return Voiceover(text, samples, samples.size / config.SAMPLE_RATE, engine)


def synthesize(text: str, path, voice=None) -> Voiceover:
    """Render one narration line, never raising.

    `path` is a base path; the extension is chosen by whichever engine wins.
    Falls back to silence of the estimated length so a failed clip cannot
    desync the video from its audio.
    """
    if not text:
        return Voiceover(text, np.zeros(0), 0.0, "silence")

    want = (config.TTS_ENGINE or "auto").lower()
    order = list(config.TTS_ORDER) if want == "auto" else [want]

    base = Path(path).with_suffix("")
    for engine in order:
        clip = _try_engine(engine, text, base, voice)
        if clip is not None:
            return clip

    seconds = estimate_duration(text)
    return Voiceover(text, np.zeros(int(seconds * config.SAMPLE_RATE)),
                     seconds, "silence")


def list_voices():
    """Return the configured edge-tts voice options."""
    return list(config.TTS_VOICES)
