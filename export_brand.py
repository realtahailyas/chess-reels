"""Emit config.py's brand values as remotion/src/brand.json.

Run after ANY change to the brand block in config.py:

    python export_brand.py

Why this file exists at all: the Remotion formats need the same violet, the
same near-white, the same board green, the same store strings and the same
wordmark as the PIL reels. Typing them into a TypeScript file makes two
sources of truth, and the moment one moves the reels and the motion graphics
stop looking like the same product. This is generated, so there is one.

The wordmark and the store icon go across as base64 data URIs rather than as
paths — a Remotion render runs in headless Chrome from its own directory, and
a relative path into ../assets/ is exactly the kind of thing that resolves on
one machine and not another.
"""

import base64
import json
from pathlib import Path

import config

OUT = config.ROOT / "remotion" / "src" / "brand.json"


def rgb(t) -> str:
    return "#%02X%02X%02X" % tuple(t)


def data_uri(path: Path, mime: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"brand asset missing: {path}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def trimmed_uri(path: Path) -> str:
    """The rook, cropped to its own ink, as a PNG data URI.

    🔴 mark.png is a 1024px ADAPTIVE-ICON layer, so nearly half of it is
    transparent padding for Android's mask. PIL crops to the alpha bbox before
    scaling (compose._rook_mark); CSS cannot, so `height: 120px` on the raw
    file renders a rook about 55% of the size asked for — which is exactly the
    "logo too small" the Remotion lockup shipped with. Trim here, once, and
    both renderers get the same mark.
    """
    from io import BytesIO

    from PIL import Image

    img = Image.open(path).convert("RGBA")
    box = img.getchannel("A").getbbox()
    if box:
        img = img.crop(box)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def cap_ratio(probe: int = 400) -> float:
    """Cap height as a fraction of em, measured from the actual TTF."""
    from PIL import ImageFont

    f = ImageFont.truetype(str(config.BRAND_FONT), probe)
    b = f.getbbox("C")
    return round((b[3] - b[1]) / probe, 4)


def payload() -> dict:
    return {
        "_generated": "python export_brand.py — do not edit by hand",
        "canvas": {"w": config.CANVAS_W, "h": config.CANVAS_H, "fps": config.FPS},
        "color": {
            "bg": rgb(config.BG),
            "accent": rgb(config.ACCENT),
            "violet": rgb(config.APP_VIOLET),
            "textHi": rgb(config.APP_TEXT_HI),
            "muted": rgb(config.MUTED),
            "surface": rgb(config.APP_SURFACE),
            "hairline": rgb(config.APP_HAIRLINE),
            "playGreen": rgb(config.PLAY_GREEN),
            "boardLight": config.BOARD_COLORS["square light"],
            "boardDark": config.BOARD_COLORS["square dark"],
        },
        "brand": {
            "name": config.BRAND_NAME,
            "handle": config.WATERMARK_TEXT,
            "web": config.ENDCARD_WEB,
            "tagline": config.ENDCARD_TAGLINE,
            "promise": config.ENDCARD_PROMISE,
            "features": list(config.ENDCARD_FEATURES),
            "bannerSub": config.PROMO_BANNER_SUB,
            "storeTitle": list(config.ENDCARD_STORE_TITLE),
            "storeDev": config.ENDCARD_STORE_DEV,
            "install": config.ENDCARD_INSTALL,
        },
        "asset": {
            "mark": trimmed_uri(config.BRAND_MARK),
            "storeIcon": data_uri(config.BRAND_STORE_ICON, "image/png"),
            "font": data_uri(config.BRAND_FONT, "font/ttf"),
        },
        # Proportions the PIL lockup uses, so the Remotion one is the same
        # shape rather than a lookalike. See compose._wordmark_sprite.
        "lockup": {
            "rookCap": config.BRAND_ROOK_CAP,
            "capMatch": config.BRAND_CAP_MATCH,
            "gap": config.BRAND_GAP_RATIO,
            # PIL sizes the face so its CAP HEIGHT equals rook * capMatch. CSS
            # `font-size` is the em, not the cap, so the browser needs the
            # face's own cap ratio to reach the same optical size. Measured
            # from the TTF rather than guessed — it differs per face.
            "capRatio": cap_ratio(),
        },
        "endcard": {"duration": config.ENDCARD_DURATION},
        # Same beds and the same gain as the PIL reels. A silent motion piece
        # next to a scored one does not read as a quieter post, it reads as a
        # broken upload — people scroll with sound on.
        "music": {
            "tracks": sorted(p.name for p in config.MUSIC_DIR.glob("*.mp3")),
            "gain": config.GAIN_MUSIC,
            "fade": config.MUSIC_FADE,
        },
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = payload()
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT}  ({kb:.0f} KB — mostly the inlined font and artwork)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
