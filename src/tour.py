"""App tour reel: product mockups of the app, with voiceover.

This is the one variant that renders no chess at all. There is no puzzle, no
board and no engine — the subject is the app itself.

Each shot is a MOCKUP, not a screenshot: a phone, a one-word label and a
floating callout (src/mockup.py). The first version panned across the raw
capture full-bleed, which was honest and read as documentation — a screen with
nothing around it is a screen, and what is being sold is a product. The store
strip every serious chess app ships is built this way for that reason.

Everything below the frame loop is shared with the puzzle pipeline: the same
speech tiers, the same declarative audio timeline, the same encoder and the
same end card.
"""

import functools
import json
import shutil
import time
import traceback

from PIL import Image, ImageDraw

import config
from src import compose, encode, mixer, mockup, speech
from src.build import _render_endcard, _save, resolve_out_root
from src.fonts import get_font
from src.mixer import AudioEvent

__all__ = ["build_tour"]

TOUR_ID = "tour"


def _shot_frames(path, label: str, callout: str, n_frames: int, index: int):
    """Yield n_frames of one product mockup — phone, label, floating callout.

    This replaced a full-bleed pan across the raw screenshot. The pan was
    honest and it read as documentation: a screen with nothing around it is a
    screen, and the thing being sold is a product. See src/mockup.py.
    """
    accent = mockup.ACCENTS[index % len(mockup.ACCENTS)]
    for i in range(n_frames):
        yield mockup.phone_shot(str(path), label, callout, accent,
                                i / config.FPS, side=index % 2)


def _plan_shots(clips) -> list:
    """Per-shot hold, floored so a line is never cut off by the next shot.

    Same rule plan_timeline uses for move holds: a shot has to outlast its own
    narration, or the voice describing the solver is still talking while the
    themes grid is on screen. Config keeps the lines short so this floor is
    rarely the binding constraint — see the note on TOUR_SHOTS.
    """
    return [max(config.TOUR_SHOT_DURATION,
                config.VO_DELAY_AFTER_MOVE + clip.duration + config.VO_TAIL)
            for clip in clips]


@functools.lru_cache(maxsize=2)
def _hook_card() -> Image.Image:
    """Opening beat: the one claim that makes someone stay for the rest."""
    card = Image.new("RGB", (config.CANVAS_W, config.CANVAS_H), config.BG)
    draw = ImageDraw.Draw(card)
    mid = config.CANVAS_H // 2
    compose.centred_text(draw, mid - config.TOUR_HOOK_SIZE, config.TOUR_HOOK_TEXT,
                         get_font(config.TOUR_HOOK_SIZE, bold=True),
                         config.APP_TEXT_HI, shadow=False)
    compose.centred_text(draw, mid + 40, config.TOUR_HOOK_SUB,
                         get_font(config.TOUR_HOOK_SUB_SIZE, bold=False),
                         config.MUTED, shadow=False)
    compose._draw_promo_banner(card)
    compose._draw_watermark(card)
    return card


def _render_hook(frames_dir, hold, log) -> int:
    n = int(round(hold * config.FPS))
    card = _hook_card()
    for i in range(n):
        _save(card, frames_dir, i)
    return n


def _render_shots(frames_dir, events, holds, log, frame_no=0) -> int:
    """Render every shot with a cross-fade between consecutive ones."""
    fade = int(round(config.TOUR_CROSSFADE * config.FPS))
    previous_tail = []

    for idx, (name, label, callout, _vo) in enumerate(config.TOUR_SHOTS):
        per = int(round(holds[idx] * config.FPS))
        path = config.TOUR_SHOT_DIR / name
        if not path.is_file():
            raise FileNotFoundError(
                f"tour screenshot missing: {path}. TOUR_SHOT_DIR points at the "
                f"owner's real device captures; put the new ones there or "
                f"point the constant somewhere else.")

        frames = list(_shot_frames(path, label, callout, per, idx))
        events.append(AudioEvent(frame_no / config.FPS, "sfx", "whoosh"))

        for i, frame in enumerate(frames):
            if i < fade and previous_tail:
                # Blend against the outgoing shot's held last frame.
                frame = Image.blend(previous_tail[0], frame, (i + 1) / fade)
            _save(frame, frames_dir, frame_no)
            frame_no += 1

        previous_tail = [frames[-1]]
        log(f"        shot    {idx + 1}/{len(config.TOUR_SHOTS)} "
            f"{label.upper():10} {callout}")

    return frame_no


def build_tour(*, voice=None, keep_frames=False,
               output_dir=None, seq=None, log=print) -> dict:
    """Build one app-tour reel. Returns a result dict and never raises."""
    started = time.time()
    V = config.variant("promo_tour")
    out_root = resolve_out_root(output_dir or config.OUTPUT_DIR, TOUR_ID, seq)
    frames_dir = out_root / "frames"
    audio_dir = out_root / "audio"

    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)

        # 1. Narration first, so a shot can be held long enough for its line.
        # The hook is clip zero: it is a line like any other and its beat is
        # held to fit it the same way.
        lines = [config.TOUR_HOOK_VO] + [s[-1] for s in config.TOUR_SHOTS]
        clips, speech_meta = [], []
        for i, line in enumerate(lines):
            clip = speech.synthesize(line, audio_dir / f"vo_{i:02d}", voice)
            clips.append(clip)
            speech_meta.append({"text": line, "source": clip.source,
                                "duration": round(clip.duration, 2)})
        log(f"        speech  {len(clips)} clips ... "
            f"{', '.join(sorted({c.source for c in clips}))}")

        # 2. Frames. Each line is scheduled at its own shot's start, and the
        # hold is floored to fit it, so the times below stay true however the
        # copy is edited.
        hook_hold = max(config.TOUR_HOOK_DURATION,
                        config.VO_DELAY_AFTER_MOVE + clips[0].duration + config.VO_TAIL)
        holds = _plan_shots(clips[1:])
        log(f"        hook    {hook_hold:.1f}s  \"{config.TOUR_HOOK_TEXT}\"")
        log(f"        shots   {len(holds)} x {min(holds):.1f}-{max(holds):.1f}s "
            f"... {sum(holds):.1f}s")
        # The VO floor normally decides every hold, so "was it stretched at all"
        # is not worth reporting. A single long one IS: it means a line grew
        # into a paragraph and the reel is now paying for it.
        worst = max(holds)
        if worst > config.TOUR_SHOT_MAX_HOLD:
            i = holds.index(worst)
            log(f"        WARN    shot {i + 1} holds {worst:.1f}s for its line "
                f"({config.TOUR_SHOTS[i][-1]!r}) — shorten it")

        events = []
        at = config.VO_DELAY_AFTER_MOVE
        for i, hold in enumerate([hook_hold] + holds):
            events.append(AudioEvent(at, "vo", clips[i]))
            at += hold

        frame_no = _render_hook(frames_dir, hook_hold, log)
        frame_no = _render_shots(frames_dir, events, holds, log, frame_no)
        frame_no = _render_endcard(frames_dir, frame_no)

        actual_duration = frame_no / config.FPS
        log(f"        frames  {frame_no} ....... {actual_duration:.1f}s")

        # 3. Audio.
        wav_path = audio_dir / "mix.wav"
        report = mixer.mix(events, actual_duration, wav_path, seed_key=TOUR_ID)
        log(f"        audio   mixed ...... peak {report['peak']:.2f}  "
            f"rms {report['rms']:.3f}  {report['music']}  "
            f"{'ok' if report['ok'] else 'CHECK'}")

        # 4. Encode. The tour is longer than the 12-22s puzzle band by design,
        # so it is verified against the generous encode bounds only.
        mp4 = out_root / "video.mp4"
        info = encode.encode_and_verify(
            frames_dir, wav_path, mp4,
            crf=V.get("crf"), preset=V.get("preset"),
            audio_bitrate=V.get("audio_bitrate"),
            audio_channels=V.get("audio_channels"),
        )
        log(f"        encode  {info['width']}x{info['height']} ... "
            f"{info['filesize'] / 1e6:.1f} MB  {info['duration']:.1f}s")

        # 5. Caption. There is no puzzle to describe, so the copy is fixed and
        # the Claude path is not offered here — asking a model to write about
        # screens it cannot see is how a promo invents features.
        caption = _tour_caption()
        (out_root / "caption.txt").write_text(caption, encoding="utf-8")

        meta = {
            "puzzle_id": TOUR_ID,
            "variant": "promo_tour",
            "shots": [{"file": n, "label": l, "callout": c, "voiceover": v}
                      for n, l, c, v in config.TOUR_SHOTS],
            "video": {**info, "fps": config.FPS, "frames": frame_no},
            "audio": report,
            "speech": speech_meta,
            "build_seconds": round(time.time() - started, 1),
        }
        (out_root / "meta.json").write_text(json.dumps(meta, indent=2),
                                            encoding="utf-8")

        if not keep_frames:
            shutil.rmtree(frames_dir, ignore_errors=True)

        # Deliberately NOT recorded in the ledger: that ledger dedupes PUZZLES,
        # and the tour spends none. Recording it would reserve the id "tour"
        # forever and make the second run look already-posted.

        log(f"        OK      {mp4}")
        return {"status": "ok", "puzzle_id": TOUR_ID, "video": str(mp4),
                "duration": info["duration"], "filesize": info["filesize"],
                "seconds": round(time.time() - started, 1),
                "needs_caption": False}

    except Exception as exc:
        log(f"        FAILED  {type(exc).__name__}: {exc}")
        return {"status": "failed", "puzzle_id": TOUR_ID, "error": str(exc),
                "traceback": traceback.format_exc(),
                "seconds": round(time.time() - started, 1)}


def _tour_caption() -> str:
    """Fixed post caption. Countless, for the same reason the end card is."""
    features = ", ".join(f.lower() for f in config.ENDCARD_FEATURES)
    return (
        f"TChess — {config.ENDCARD_TAGLINE}\n\n"
        f"Puzzles, openings, bots, analysis, endgames and lessons, all on your "
        f"phone and all working offline. {config.ENDCARD_PROMISE}.\n\n"
        f"Google Play: search “TChess”\n"
        f"Browser: {config.ENDCARD_WEB}\n\n"
        f"#chess #chesstactics #chesspuzzles #chessapp #chesstraining "
        f"#chessopenings #endgame #chessimprovement #tchess #learnchess\n\n"
        f"[{features}]\n"
    )
