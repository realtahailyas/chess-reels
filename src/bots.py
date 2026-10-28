"""The bot ladder reel: eight real opponents, weakest to strongest.

"Sirf puzzles nahi, khel bhi sakte ho" — the one thing a puzzle-shaped promo
never says. Every figure and every portrait here is read out of the APP at build
time, so this reel cannot advertise a roster the app does not ship.

⚠️ The portraits are read from `constants/botPortraits.ts`, NOT from the eight
files in `assets/bots/`. Those filenames do not all match the characters:
`assets/bots/` has an `ayan.svg` and no bot is called Ayan (the character was
renamed to Boa), so mapping by filename means one bot silently gets somebody
else's face. The TS map is keyed by bot id and is what the app itself renders.
"""

import json
import re
import time
import traceback
from pathlib import Path

from PIL import Image, ImageDraw

import config
from src import compose, encode, mixer, speech, svgrender
from src.build import _render_endcard, _save, resolve_out_root
from src.fonts import get_font
from src.mixer import AudioEvent

__all__ = ["build_bots"]

BOTS_ID = "bots"

_ENTRY = re.compile(
    r"id:\s*'([^']+)'[\s\S]*?name:\s*'([^']+)'[\s\S]*?tagline:\s*'([^']+)'"
    r"[\s\S]*?elo:\s*(\d+)")


def roster() -> list:
    """(id, name, elo, tagline) for the eight ladder bots, weakest first."""
    src = _read(config.BOTS_DEFS)
    found = _ENTRY.findall(src)[:config.BOTS_COUNT]
    if len(found) != config.BOTS_COUNT:
        raise RuntimeError(
            f"parsed {len(found)} bots from {config.BOTS_DEFS}, wanted "
            f"{config.BOTS_COUNT} — the file's shape changed")
    out = [(i, n, int(e), t) for i, n, t, e in found]

    # The ladder is the whole point of the reel; out of order it is a roster.
    elos = [e for _i, _n, e, _t in out]
    if elos != sorted(elos):
        raise RuntimeError(f"bot ratings are not ascending: {elos}")
    return out


def portraits() -> dict:
    """{bot id: svg text}, read from the map the app itself renders."""
    src = _read(config.BOTS_PORTRAITS)
    body = src.split("BOT_PORTRAITS: Record<string, string> = {", 1)[1]
    # A hyphenated key has to be QUOTED in TS, so 'the-archivist' is written
    # differently from every other entry. Matching bare keys only drops it, and
    # the roster then renders seven bots with no error.
    out = {}
    for quoted_key, bare_key, svg in re.findall(
            r"(?:'([\w-]+)'|([\w-]+)):\s*(\"(?:\\.|[^\"\\])*\")", body):
        out[quoted_key or bare_key] = json.loads(svg)
    return out


def _read(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(
            f"the app's own data is missing: {path}. This reel reads the roster "
            f"and the portraits out of the app so it cannot advertise bots that "
            f"do not ship.")
    return path.read_text(encoding="utf-8")


def _card(bot, svg: str, index: int, total: int) -> Image.Image:
    """One rung: portrait, name, rating, and what the bot actually does."""
    _id, name, elo, tagline = bot
    img = Image.new("RGB", (config.CANVAS_W, config.CANVAS_H), config.BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, config.CANVAS_W, config.ACCENT_BAR_H], fill=config.ACCENT)
    compose._draw_promo_banner(img)

    # The portraits carry their own #17171B ground, which is a shade lighter
    # than the reel's, so a square paste reads as a stray rectangle rather than
    # a portrait. Rounded, the same ground reads as the card it is.
    px = config.BOTS_PORTRAIT_PX
    art = svgrender.rasterize(svg, px, supersample=config.PIL_SUPERSAMPLE)
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, px - 1, px - 1], radius=round(px * config.BOTS_PORTRAIT_RADIUS),
        fill=255)
    img.paste(art.convert("RGB"), ((config.CANVAS_W - px) // 2,
                                   config.BOTS_PORTRAIT_Y), mask)

    compose.centred_text(draw, config.BOTS_NAME_Y, name,
                         get_font(config.BOTS_NAME_SIZE, bold=True),
                         config.APP_TEXT_HI, shadow=False)

    # Rating pill. The number IS the product here — a ladder with no rungs
    # marked is just eight faces.
    pill_font = get_font(config.BOTS_ELO_SIZE, bold=True)
    label = str(elo)
    pb = draw.textbbox((0, 0), label, font=pill_font)
    pw, ph = pb[2] - pb[0], pb[3] - pb[1]
    px, py = config.BOTS_ELO_PAD
    x0 = (config.CANVAS_W - (pw + px * 2)) // 2
    y0 = config.BOTS_ELO_Y
    draw.rounded_rectangle([x0, y0, x0 + pw + px * 2, y0 + ph + py * 2],
                           radius=(ph + py * 2) // 2, fill=config.APP_VIOLET)
    draw.text((x0 + px - pb[0], y0 + py - pb[1]), label, font=pill_font,
              fill=config.BG)

    compose.centred_text(draw, config.BOTS_TAGLINE_Y, tagline,
                         get_font(config.BOTS_TAGLINE_SIZE, bold=False),
                         config.MUTED, shadow=False)

    _draw_rungs(draw, index, total)
    compose._draw_watermark(img)
    return img


def _draw_rungs(draw, index: int, total: int) -> None:
    """A ladder drawn as a ladder: every rung visible, the current one lit."""
    w, gap, h = config.BOTS_RUNG
    span = total * w + (total - 1) * gap
    x = (config.CANVAS_W - span) // 2
    y = config.BOTS_RUNG_Y
    for i in range(total):
        lit = i <= index
        draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2,
                               fill=config.APP_VIOLET if lit else config.APP_HAIRLINE)
        x += w + gap


def build_bots(*, voice=None, keep_frames=False, output_dir=None, seq=None,
               log=print) -> dict:
    """Build the ladder reel. Returns a result dict and never raises."""
    started = time.time()
    V = config.variant("promo_bots")
    out_root = resolve_out_root(output_dir or config.OUTPUT_DIR, BOTS_ID, seq)
    frames_dir = out_root / "frames"
    audio_dir = out_root / "audio"

    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)

        bots = roster()
        art = portraits()
        missing = [b[0] for b in bots if b[0] not in art]
        if missing:
            raise RuntimeError(f"no portrait for {missing} in {config.BOTS_PORTRAITS}")
        log(f"        roster  {len(bots)} bots ... "
            f"{bots[0][1]} {bots[0][2]} -> {bots[-1][1]} {bots[-1][2]}")

        # 1. Narration. Comma form, no full stops — see the note on TOUR_SHOTS.
        lines = [config.BOTS_HOOK_VO] + [f"{n}, {t.lower()}" for _i, n, _e, t in bots]
        clips, speech_meta = [], []
        for i, line in enumerate(lines):
            clip = speech.synthesize(line, audio_dir / f"vo_{i:02d}", voice)
            clips.append(clip)
            speech_meta.append({"text": line, "source": clip.source,
                                "duration": round(clip.duration, 2)})
        log(f"        speech  {len(clips)} clips ... "
            f"{', '.join(sorted({c.source for c in clips}))}")

        holds = [max(config.BOTS_CARD_DURATION,
                     config.VO_DELAY_AFTER_MOVE + c.duration + config.VO_TAIL)
                 for c in clips[1:]]
        hook_hold = max(config.BOTS_HOOK_DURATION,
                        config.VO_DELAY_AFTER_MOVE + clips[0].duration + config.VO_TAIL)

        events, at = [], config.VO_DELAY_AFTER_MOVE
        for i, hold in enumerate([hook_hold] + holds):
            events.append(AudioEvent(at, "vo", clips[i]))
            at += hold

        # 2. Frames.
        frame_no = 0
        hook = _hook_card()
        for _ in range(int(round(hook_hold * config.FPS))):
            _save(hook, frames_dir, frame_no)
            frame_no += 1

        for i, bot in enumerate(bots):
            card = _card(bot, art[bot[0]], i, len(bots))
            events.append(AudioEvent(frame_no / config.FPS, "sfx", "move"))
            for _ in range(int(round(holds[i] * config.FPS))):
                _save(card, frames_dir, frame_no)
                frame_no += 1

        frame_no = _render_endcard(frames_dir, frame_no)
        actual = frame_no / config.FPS
        log(f"        frames  {frame_no} ....... {actual:.1f}s")

        # 3. Audio + encode.
        wav = audio_dir / "mix.wav"
        report = mixer.mix(events, actual, wav, seed_key=BOTS_ID)
        log(f"        audio   mixed ...... peak {report['peak']:.2f}  "
            f"rms {report['rms']:.3f}  {report['music']}  "
            f"{'ok' if report['ok'] else 'CHECK'}")

        mp4 = out_root / "video.mp4"
        info = encode.encode_and_verify(
            frames_dir, wav, mp4, crf=V.get("crf"), preset=V.get("preset"),
            audio_bitrate=V.get("audio_bitrate"),
            audio_channels=V.get("audio_channels"))
        log(f"        encode  {info['width']}x{info['height']} ... "
            f"{info['filesize'] / 1e6:.1f} MB  {info['duration']:.1f}s")

        (out_root / "caption.txt").write_text(_caption(bots), encoding="utf-8")
        (out_root / "meta.json").write_text(json.dumps({
            "puzzle_id": BOTS_ID,
            "variant": "promo_bots",
            "bots": [{"id": i, "name": n, "elo": e, "tagline": t}
                     for i, n, e, t in bots],
            "video": {**info, "fps": config.FPS, "frames": frame_no},
            "audio": report,
            "speech": speech_meta,
            "build_seconds": round(time.time() - started, 1),
        }, indent=2), encoding="utf-8")

        if not keep_frames:
            import shutil
            shutil.rmtree(frames_dir, ignore_errors=True)

        log(f"        OK      {mp4}")
        return {"status": "ok", "puzzle_id": BOTS_ID, "video": str(mp4),
                "duration": info["duration"], "filesize": info["filesize"],
                "seconds": round(time.time() - started, 1), "needs_caption": False}

    except Exception as exc:
        log(f"        FAILED  {type(exc).__name__}: {exc}")
        return {"status": "failed", "puzzle_id": BOTS_ID, "error": str(exc),
                "traceback": traceback.format_exc(),
                "seconds": round(time.time() - started, 1)}


def _hook_card() -> Image.Image:
    img = Image.new("RGB", (config.CANVAS_W, config.CANVAS_H), config.BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, config.CANVAS_W, config.ACCENT_BAR_H], fill=config.ACCENT)
    mid = config.CANVAS_H // 2
    compose.centred_text(draw, mid - config.BOTS_HOOK_SIZE, config.BOTS_HOOK_TEXT,
                         get_font(config.BOTS_HOOK_SIZE, bold=True),
                         config.APP_TEXT_HI, shadow=False)
    compose.centred_text(draw, mid + 40, config.BOTS_HOOK_SUB,
                         get_font(config.BOTS_HOOK_SUB_SIZE, bold=False),
                         config.MUTED, shadow=False)
    compose._draw_promo_banner(img)
    compose._draw_watermark(img)
    return img


def _caption(bots) -> str:
    rows = "\n".join(f"{n} · {e} — {t.lower()}" for _i, n, e, t in bots)
    return (
        f"{config.BOTS_HOOK_TEXT}\n\n{rows}\n\n"
        f"Each one plays differently, not just worse — one really will sacrifice "
        f"a rook for an attack, because that is how it evaluates the position.\n\n"
        f"All offline, all free, in TChess.\n"
        f"Google Play: search “{config.BRAND_NAME}”\n"
        f"Browser: {config.ENDCARD_WEB}\n\n"
        "#chess #chessbot #playchess #chessapp #chesstraining #chessonline "
        "#chessimprovement #tchess #learnchess #chessdaily\n"
    )
