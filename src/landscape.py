"""The app tour, re-composed for 16:9 — the Google Play listing video.

🔴 This is NOT the vertical reel letterboxed. Play shows its promo video
landscape, and a 1080x1920 file dropped into a 16:9 slot becomes a stripe down
the middle of the store page with black either side. A screenshot 2340px tall
cannot fill a 1080px-tall frame by scaling, so the layout changes instead: the
phone takes one side, the label and its supporting line take the other. That is
the same reason every app's landscape store art looks like this.

Everything else the account posts stays 9:16. Play is the exception.

The CONTENT is shared with the vertical tour — same shots, same labels, same
voiceover lines, same music, same end card copy — so the two cannot drift into
being different films.
"""

import functools
import json
import shutil
import time
import traceback

from PIL import Image, ImageDraw, ImageFilter

import config
from src import compose, encode, mixer, mockup, speech
from src.build import _save, resolve_out_root
from src.fonts import get_font
from src.mixer import AudioEvent

__all__ = ["build_wide"]

WIDE_ID = "tour-wide"


def _centred(draw, y, text, font, fill, w=None):
    """compose.centred_text centres on the VERTICAL canvas width, so the wide
    frames need their own — a 1080-wide centre on a 1920 frame is left of it."""
    w = w or config.WIDE_W
    b = draw.textbbox((0, 0), text, font=font)
    draw.text(((w - (b[2] - b[0])) // 2 - b[0], y - b[1]), text, font=font, fill=fill)


@functools.lru_cache(maxsize=8)
def _ground(accent: tuple) -> Image.Image:
    """Gradient, an off-centre bloom behind the phone, and a vignette."""
    w, h = config.WIDE_W, config.WIDE_H
    top, bot = config.WIDE_GRAD_TOP, config.WIDE_GRAD_BOTTOM
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        t = y / (h - 1)
        px[0, y] = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    img = col.resize((w, h), Image.BILINEAR)

    g = mockup._glow(config.WIDE_GLOW_PX, accent, config.WIDE_GLOW_ALPHA)
    img.paste(g, config.WIDE_GLOW_XY, g)

    small = 90
    mask = Image.new("L", (small, small), 0)
    ImageDraw.Draw(mask).ellipse([-small * 0.14, -small * 0.24,
                                  small * 1.14, small * 1.24], fill=255)
    mask = mask.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(w / 11))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, config.WIDE_VIGNETTE / 255), mask)


@functools.lru_cache(maxsize=16)
def _phone(shot_path: str) -> Image.Image:
    """Handset sized by HEIGHT here, not width — height is the scarce axis."""
    shot = Image.open(shot_path).convert("RGB")
    screen_h = config.WIDE_PHONE_H - config.WIDE_BEZEL * 2
    screen_w = round(shot.width * screen_h / shot.height)
    shot = shot.resize((screen_w, screen_h), Image.LANCZOS)

    w = screen_w + config.WIDE_BEZEL * 2
    body = Image.new("RGBA", (w, config.WIDE_PHONE_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle([0, 0, w - 1, config.WIDE_PHONE_H - 1],
                        radius=config.WIDE_RADIUS,
                        fill=config.MOCKUP_BODY + (255,),
                        outline=config.MOCKUP_EDGE + (255,), width=2)
    mask = Image.new("L", (screen_w, screen_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, screen_w - 1, screen_h - 1],
        radius=max(2, config.WIDE_RADIUS - config.WIDE_BEZEL), fill=255)
    body.paste(shot, (config.WIDE_BEZEL, config.WIDE_BEZEL), mask)
    return body


def shot_frame(shot_path, label, callout, accent, t, index=0) -> Image.Image:
    """One landscape shot. Same staged entrance as the vertical mockups."""
    img = _ground(accent).copy()
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, config.WIDE_W, config.ACCENT_BAR_H], fill=config.ACCENT)

    lp = mockup._clamp(t / config.MOCKUP_LABEL_IN)
    if lp > 0:
        from src import animate
        y = config.WIDE_LABEL_Y + round((1 - animate.ease_in_out_cubic(lp)) * 26)
        f = get_font(config.WIDE_LABEL_SIZE, bold=True)
        b = draw.textbbox((0, 0), label.upper(), font=f)
        draw.text((config.WIDE_TEXT_X - b[0], y - b[1]), label.upper(),
                  font=f, fill=config.APP_TEXT_HI)
        ry = y + config.WIDE_LABEL_SIZE + config.WIDE_RULE_GAP
        draw.rounded_rectangle(
            [config.WIDE_TEXT_X, ry,
             config.WIDE_TEXT_X + round(config.WIDE_RULE_W * lp),
             ry + config.WIDE_RULE_H],
            radius=config.WIDE_RULE_H // 2, fill=accent)

    # The callout is plain text in the copy column here. In the vertical frames
    # it is a pill because it floats beside a phone that fills the width; with
    # a whole column to itself a pill would be a button nobody can press.
    cp = mockup._clamp((t - config.MOCKUP_CALLOUT_DELAY) / config.MOCKUP_CALLOUT_IN)
    if cp > 0 and callout:
        f = get_font(config.WIDE_CALLOUT_SIZE, bold=False)
        b = draw.textbbox((0, 0), callout, font=f)
        draw.text((config.WIDE_TEXT_X - b[0], config.WIDE_CALLOUT_Y - b[1]),
                  callout, font=f, fill=config.MUTED)

    pp = mockup._clamp((t - config.MOCKUP_PHONE_DELAY) / config.MOCKUP_PHONE_IN)
    if pp > 0:
        from src import animate
        phone = _phone(str(shot_path))
        drift = round(config.MOCKUP_DRIFT * min(1.0, t / config.MOCKUP_DRIFT_OVER))
        y = (config.WIDE_PHONE_Y
             + round((1 - animate.ease_in_out_cubic(pp)) * 40) - drift)
        img.paste(phone, (config.WIDE_PHONE_X, y), phone)

    banner = compose._banner_sprite()
    img.paste(banner, (config.WIDE_BANNER_X, config.WIDE_BANNER_Y), banner)
    return img


@functools.lru_cache(maxsize=2)
def _hook_card() -> Image.Image:
    img = _ground(config.APP_VIOLET).copy()
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, config.WIDE_W, config.ACCENT_BAR_H], fill=config.ACCENT)
    mid = config.WIDE_H // 2
    _centred(draw, mid - config.WIDE_HOOK_SIZE, config.TOUR_HOOK_TEXT,
             get_font(config.WIDE_HOOK_SIZE, bold=True), config.APP_TEXT_HI)
    _centred(draw, mid + 40, config.TOUR_HOOK_SUB,
             get_font(config.WIDE_HOOK_SUB_SIZE, bold=False), config.MUTED)
    banner = compose._banner_sprite()
    img.paste(banner, ((config.WIDE_W - banner.width) // 2,
                       config.WIDE_BANNER_Y), banner)
    return img


@functools.lru_cache(maxsize=2)
def _endcard() -> Image.Image:
    """Two columns: the brand on the left, the store row on the right.

    The vertical card stacks the same content; at 1080 tall a stack would run
    off the bottom, and shrinking it to fit is how a call to action becomes
    unreadable on a TV-shaped surface.
    """
    img = Image.new("RGB", (config.WIDE_W, config.WIDE_H), config.BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, config.WIDE_W, config.ACCENT_BAR_H], fill=config.ACCENT)

    mark = compose._wordmark_sprite(config.WIDE_ENDCARD_MARK_H)
    img.paste(mark, (config.WIDE_TEXT_X, 210), mark)
    f = get_font(config.WIDE_ENDCARD_TAGLINE_SIZE, bold=True)
    b = draw.textbbox((0, 0), config.ENDCARD_TAGLINE, font=f)
    draw.text((config.WIDE_TEXT_X - b[0], 450 - b[1]), config.ENDCARD_TAGLINE,
              font=f, fill=config.APP_TEXT_HI)

    ff = get_font(44, bold=False)
    for i, name in enumerate(config.ENDCARD_FEATURES):
        x = config.WIDE_TEXT_X + (i % 2) * 300
        y = 570 + (i // 2) * 74
        draw.ellipse([x, y + 16, x + 14, y + 30], fill=config.APP_VIOLET)
        draw.text((x + 34, y), name, font=ff, fill=config.APP_TEXT_HI)

    pf = get_font(38, bold=False)
    draw.text((config.WIDE_TEXT_X, 830), config.ENDCARD_PROMISE,
              font=pf, fill=config.MUTED)

    # Store column.
    cx = 1080
    card = [cx, 300, config.WIDE_W - 130, 470]
    draw.rounded_rectangle(card, radius=26, fill=config.APP_SURFACE,
                           outline=config.APP_HAIRLINE, width=1)
    icon = compose._store_icon(116)
    img.paste(icon, (cx + 30, 327), icon)
    tf = get_font(36, bold=True)
    for i, line in enumerate(config.ENDCARD_STORE_TITLE):
        draw.text((cx + 172, 330 + i * 44), line, font=tf, fill=config.APP_TEXT_HI)
    draw.text((cx + 172, 422), config.ENDCARD_STORE_DEV,
              font=get_font(28, bold=False), fill=config.PLAY_GREEN)

    pill = [cx, 508, config.WIDE_W - 130, 604]
    draw.rounded_rectangle(pill, radius=26, fill=config.PLAY_GREEN)
    bf = get_font(46, bold=True)
    bb = draw.textbbox((0, 0), config.ENDCARD_INSTALL, font=bf)
    draw.text(((pill[0] + pill[2] - (bb[2] - bb[0])) // 2 - bb[0],
               (pill[1] + pill[3] - (bb[3] - bb[1])) // 2 - bb[1]),
              config.ENDCARD_INSTALL, font=bf, fill=(255, 255, 255))
    wf = get_font(40, bold=True)
    wb = draw.textbbox((0, 0), config.ENDCARD_WEB, font=wf)
    draw.text(((pill[0] + pill[2] - (wb[2] - wb[0])) // 2 - wb[0], 640 - wb[1]),
              config.ENDCARD_WEB, font=wf, fill=config.MUTED)
    return img


def build_wide(*, voice=None, keep_frames=False, output_dir=None, seq=None,
               log=print) -> dict:
    """Build the landscape tour. Returns a result dict and never raises."""
    started = time.time()
    V = config.variant("promo_tour_wide")
    out_root = resolve_out_root(output_dir or config.OUTPUT_DIR, WIDE_ID, seq)
    frames_dir = out_root / "frames"
    audio_dir = out_root / "audio"

    try:
        frames_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)

        lines = [config.TOUR_HOOK_VO] + [s[-1] for s in config.TOUR_SHOTS]
        clips, speech_meta = [], []
        for i, line in enumerate(lines):
            clip = speech.synthesize(line, audio_dir / f"vo_{i:02d}", voice)
            clips.append(clip)
            speech_meta.append({"text": line, "source": clip.source,
                                "duration": round(clip.duration, 2)})
        log(f"        speech  {len(clips)} clips ... "
            f"{', '.join(sorted({c.source for c in clips}))}")

        floor = lambda c: max(config.TOUR_SHOT_DURATION,
                              config.VO_DELAY_AFTER_MOVE + c.duration + config.VO_TAIL)
        hook_hold = max(config.TOUR_HOOK_DURATION, floor(clips[0]))
        holds = [floor(c) for c in clips[1:]]
        log(f"        hook    {hook_hold:.1f}s  shots {len(holds)} x "
            f"{min(holds):.1f}-{max(holds):.1f}s")

        events, at = [], config.VO_DELAY_AFTER_MOVE
        for i, hold in enumerate([hook_hold] + holds):
            events.append(AudioEvent(at, "vo", clips[i]))
            at += hold

        frame_no = 0
        hook = _hook_card()
        for _ in range(int(round(hook_hold * config.FPS))):
            _save(hook, frames_dir, frame_no)
            frame_no += 1

        fade = int(round(config.TOUR_CROSSFADE * config.FPS))
        prev = None
        for idx, (name, label, callout, _vo) in enumerate(config.TOUR_SHOTS):
            path = config.TOUR_SHOT_DIR / name
            if not path.is_file():
                raise FileNotFoundError(f"tour screenshot missing: {path}")
            accent = mockup.ACCENTS[idx % len(mockup.ACCENTS)]
            n = int(round(holds[idx] * config.FPS))
            events.append(AudioEvent(frame_no / config.FPS, "sfx", "whoosh"))
            frames = [shot_frame(path, label, callout, accent, i / config.FPS, idx)
                      for i in range(n)]
            for i, fr in enumerate(frames):
                if i < fade and prev is not None:
                    fr = Image.blend(prev, fr, (i + 1) / fade)
                _save(fr, frames_dir, frame_no)
                frame_no += 1
            prev = frames[-1]
            log(f"        shot    {idx + 1}/{len(config.TOUR_SHOTS)} "
                f"{label.upper():10} {callout}")

        card = _endcard()
        n = int(round(config.ENDCARD_DURATION * config.FPS))
        fade_n = max(1, int(round(config.ENDCARD_FADE * config.FPS)))
        ground = Image.new("RGB", card.size, config.BG)
        for i in range(n):
            a = min(1.0, (i + 1) / fade_n)
            _save(card if a >= 0.999 else Image.blend(ground, card, a),
                  frames_dir, frame_no)
            frame_no += 1

        actual = frame_no / config.FPS
        log(f"        frames  {frame_no} ....... {actual:.1f}s")

        wav = audio_dir / "mix.wav"
        report = mixer.mix(events, actual, wav, seed_key=WIDE_ID)
        log(f"        audio   mixed ...... peak {report['peak']:.2f}  "
            f"rms {report['rms']:.3f}  {report['music']}  "
            f"{'ok' if report['ok'] else 'CHECK'}")

        mp4 = out_root / "video.mp4"
        info = encode.encode_and_verify(
            frames_dir, wav, mp4, crf=V.get("crf"), preset=V.get("preset"),
            audio_bitrate=V.get("audio_bitrate"),
            audio_channels=V.get("audio_channels"),
            size=(config.WIDE_W, config.WIDE_H))
        log(f"        encode  {info['width']}x{info['height']} ... "
            f"{info['filesize'] / 1e6:.1f} MB  {info['duration']:.1f}s")

        (out_root / "caption.txt").write_text(_caption(), encoding="utf-8")
        (out_root / "meta.json").write_text(json.dumps({
            "puzzle_id": WIDE_ID,
            "variant": "promo_tour_wide",
            "purpose": "Google Play listing promo video (landscape)",
            "size": [config.WIDE_W, config.WIDE_H],
            "shots": [{"file": n, "label": l, "callout": c, "voiceover": v}
                      for n, l, c, v in config.TOUR_SHOTS],
            "video": {**info, "fps": config.FPS, "frames": frame_no},
            "audio": report,
            "speech": speech_meta,
            "build_seconds": round(time.time() - started, 1),
        }, indent=2), encoding="utf-8")

        if not keep_frames:
            shutil.rmtree(frames_dir, ignore_errors=True)

        log(f"        OK      {mp4}")
        return {"status": "ok", "puzzle_id": WIDE_ID, "video": str(mp4),
                "duration": info["duration"], "filesize": info["filesize"],
                "seconds": round(time.time() - started, 1), "needs_caption": False}

    except Exception as exc:
        log(f"        FAILED  {type(exc).__name__}: {exc}")
        return {"status": "failed", "puzzle_id": WIDE_ID, "error": str(exc),
                "traceback": traceback.format_exc(),
                "seconds": round(time.time() - started, 1)}


def _caption() -> str:
    """YouTube description. This upload exists to be LINKED, not to be found —
    Play reads the URL — so it says what the app is and nothing else."""
    return (
        f"{config.BRAND_NAME} — {config.ENDCARD_TAGLINE}\n\n"
        f"{', '.join(f.lower() for f in config.ENDCARD_FEATURES)}. "
        f"{config.ENDCARD_PROMISE}.\n\n"
        f"Google Play: https://play.google.com/store/apps/details?id=app.tchess\n"
        f"Browser: https://{config.ENDCARD_WEB}\n\n"
        f"Analysis is Stockfish, GPL-3.\n"
    )
