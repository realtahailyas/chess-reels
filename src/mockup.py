"""Store-style product mockups: a phone, a big label, a floating callout.

The reference is the Play Store feature strip every serious chess app ships —
Chess.com's is the well-known one. What makes those read as a PRODUCT rather
than a screen recording is three things, and none of them is the screenshot:

  1. the screen sits in a PHONE, so it reads as something you hold;
  2. a huge one-word LABEL says what you are looking at before you look;
  3. a floating CALLOUT lifts one detail off the glass, so the eye has a place
     to land instead of scanning a whole UI.

A full-bleed screenshot has none of that, which is why a pan across one reads
as documentation. Everything here is PIL compositing — the same renderer that
draws the boards — so there is one brand implementation, not two.

The accent rotates per shot. On a near-black ground a single coloured glow is
what separates "designed" from "dark"; using the same one eight times in a row
makes the reel look like one long screen.
"""

import functools

from PIL import Image, ImageDraw, ImageFilter

import config
from src import animate, compose
from src.fonts import get_font

__all__ = ["phone_shot", "ACCENTS"]

# Drawn from the app's own tokens plus the brilliant-badge cyan, so every glow
# on screen is a colour the product already uses somewhere.
ACCENTS = [
    config.APP_VIOLET,          # primary
    (110, 138, 84),             # board dark square
    (245, 165, 36),             # warning / streak
    (38, 198, 218),             # the !! badge cyan
]


@functools.lru_cache(maxsize=8)
def _glow(size: int, colour: tuple, strength: int) -> Image.Image:
    """A soft radial bloom. Cached — it is identical on every frame of a shot."""
    small = max(8, size // 8)
    img = Image.new("L", (small, small), 0)
    ImageDraw.Draw(img).ellipse([small * 0.12, small * 0.12,
                                 small * 0.88, small * 0.88], fill=strength)
    img = img.resize((size, size), Image.BICUBIC).filter(
        ImageFilter.GaussianBlur(size / 14))
    bloom = Image.new("RGBA", (size, size), colour + (0,))
    bloom.putalpha(img)
    return bloom


@functools.lru_cache(maxsize=8)
def _ground(accent: tuple) -> Image.Image:
    """Gradient, accent bloom and vignette — built once per accent.

    Flat black with one glow reads as "dark". What makes a product shot read as
    COMPOSED is the vignette: it puts the phone in a room rather than on a
    colour, and it is the difference between this and a slide.
    """
    w, h = config.CANVAS_W, config.CANVAS_H
    top, bot = config.MOCKUP_GRAD_TOP, config.MOCKUP_GRAD_BOTTOM

    # One column, stretched — a per-pixel loop over 1080x1920 is 2M writes.
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        t = y / (h - 1)
        px[0, y] = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    img = col.resize((w, h), Image.BILINEAR)

    g = _glow(config.MOCKUP_GLOW_PX, accent, config.MOCKUP_GLOW_ALPHA)
    img.paste(g, ((w - g.width) // 2, config.MOCKUP_GLOW_Y), g)

    # Vignette: a blurred white ellipse becomes the KEEP mask, so the corners
    # fall away smoothly instead of banding.
    small = 90
    mask = Image.new("L", (small, small), 0)
    ImageDraw.Draw(mask).ellipse([-small * 0.24, -small * 0.06,
                                  small * 1.24, small * 1.06], fill=255)
    mask = mask.resize((w, h), Image.BILINEAR).filter(
        ImageFilter.GaussianBlur(w / 9))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    img = Image.composite(img, Image.blend(img, dark,
                                           config.MOCKUP_VIGNETTE / 255), mask)
    return img


@functools.lru_cache(maxsize=16)
def _phone(shot_path: str) -> Image.Image:
    """The screenshot inside a rounded handset body."""
    screen_w = config.MOCKUP_PHONE_W - config.MOCKUP_BEZEL * 2
    shot = Image.open(shot_path).convert("RGB")
    screen_h = round(shot.height * screen_w / shot.width)
    shot = shot.resize((screen_w, screen_h), Image.LANCZOS)

    w = config.MOCKUP_PHONE_W
    h = screen_h + config.MOCKUP_BEZEL * 2
    body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    r = config.MOCKUP_RADIUS
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r,
                        fill=config.MOCKUP_BODY + (255,),
                        outline=config.MOCKUP_EDGE + (255,), width=2)

    # Round the screen's own corners so it sits INSIDE the body rather than
    # poking out of it — a square screen in a rounded shell is the giveaway
    # that a mockup was pasted together.
    mask = Image.new("L", (screen_w, screen_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, screen_w - 1, screen_h - 1],
        radius=max(2, r - config.MOCKUP_BEZEL), fill=255)
    body.paste(shot, (config.MOCKUP_BEZEL, config.MOCKUP_BEZEL), mask)
    return body


@functools.lru_cache(maxsize=32)
def _callout(text: str, accent: tuple) -> Image.Image:
    """A light pill that lifts one fact off the glass."""
    font = get_font(config.MOCKUP_CALLOUT_SIZE, bold=True)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    b = probe.textbbox((0, 0), text, font=font)
    tw, th = b[2] - b[0], b[3] - b[1]
    px, py = config.MOCKUP_CALLOUT_PAD
    dot = config.MOCKUP_CALLOUT_DOT

    w = px * 2 + dot * 2 + config.MOCKUP_CALLOUT_GAP + tw
    h = py * 2 + max(th, dot * 2)
    pill = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(pill)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2,
                        fill=config.MOCKUP_CALLOUT_BG + (255,))
    cy = h // 2
    d.ellipse([px, cy - dot, px + dot * 2, cy + dot], fill=accent)
    d.text((px + dot * 2 + config.MOCKUP_CALLOUT_GAP - b[0], (h - th) // 2 - b[1]),
           text, font=font, fill=config.MOCKUP_CALLOUT_INK)
    return pill


def phone_shot(shot_path: str, label: str, callout: str, accent: tuple,
               t: float, side: int = 0, chrome: bool = None) -> Image.Image:
    """One mockup frame. `t` is seconds since the shot started.

    The entrance is staged — label, then phone, then callout — because three
    things arriving together is a flash, and three things arriving in order is
    something the eye can follow.
    """
    img = _ground(accent).copy()
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, config.CANVAS_W, config.ACCENT_BAR_H], fill=config.ACCENT)

    # 1. Label — rises into place.
    lp = _clamp(t / config.MOCKUP_LABEL_IN)
    ly = config.MOCKUP_LABEL_Y + round((1 - animate.ease_in_out_cubic(lp)) * 28)
    if lp > 0:
        compose.centred_text(draw, ly, label.upper(),
                             get_font(config.MOCKUP_LABEL_SIZE, bold=True),
                             config.APP_TEXT_HI, shadow=False)
        rule_w = round(config.MOCKUP_RULE_W * lp)
        ry = ly + config.MOCKUP_LABEL_SIZE + config.MOCKUP_RULE_GAP
        draw.rounded_rectangle(
            [(config.CANVAS_W - rule_w) // 2, ry,
             (config.CANVAS_W + rule_w) // 2, ry + config.MOCKUP_RULE_H],
            radius=config.MOCKUP_RULE_H // 2, fill=accent)

    # 2. Phone — rises, then keeps drifting up a few px for the whole hold, so
    # a three-second shot is never actually still.
    pp = _clamp((t - config.MOCKUP_PHONE_DELAY) / config.MOCKUP_PHONE_IN)
    if pp > 0:
        phone = _phone(shot_path)
        drift = round(config.MOCKUP_DRIFT * min(1.0, t / config.MOCKUP_DRIFT_OVER))
        # Off-centre, so the callout has a margin of its own to sit in.
        dx = config.MOCKUP_PHONE_DX if side == 0 else -config.MOCKUP_PHONE_DX
        phone_x = (config.CANVAS_W - phone.width) // 2 + dx
        py = (config.MOCKUP_PHONE_Y
              + round((1 - animate.ease_in_out_cubic(pp)) * 46) - drift)
        img.paste(phone, (phone_x, py), phone)

        # 3. Callout — pops in the margin BESIDE the handset. It used to
        # overlap the glass, which covered the very UI it was pointing at; a
        # product shot must never hide the product.
        cp = _clamp((t - config.MOCKUP_CALLOUT_DELAY) / config.MOCKUP_CALLOUT_IN)
        if config.MOCKUP_CALLOUT and cp > 0 and callout:
            pill = _callout(callout, accent)
            s = animate.ease_out_back(cp, config.MOCKUP_CALLOUT_OVERSHOOT)
            s = max(0.05, min(1.0, s))
            sw, sh = max(1, round(pill.width * s)), max(1, round(pill.height * s))
            small = pill.resize((sw, sh), Image.LANCZOS)
            if side == 0:                      # phone right, pill left
                cx = config.MOCKUP_CALLOUT_EDGE
            else:                              # phone left, pill right
                cx = config.CANVAS_W - config.MOCKUP_CALLOUT_EDGE - sw
            cy = py + round(phone.height * config.MOCKUP_CALLOUT_AT)
            img.paste(small, (cx, cy - sh // 2), small)

    # Banner as a FOOTER, under the phone. No handle: the lockup already names
    # the brand, and a handle under it would be a second line saying the same
    # thing in the same place.
    if config.MOCKUP_CHROME if chrome is None else chrome:
        compose._draw_promo_banner(img, y=config.MOCKUP_BANNER_BOTTOM)
    return img


def _clamp(v: float) -> float:
    return 0.0 if v < 0 else (1.0 if v > 1 else v)
