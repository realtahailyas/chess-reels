"""Font resolution with a platform-aware fallback chain.

Section 7.2 specifies bundled asset -> DejaVu -> PIL default. The bare PIL
default is a small bitmap face that looks wrong at 92 px, so the chain also
covers the standard Windows and macOS bold faces before giving up.
"""

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

import config

_BOLD_CANDIDATES = [
    config.ASSETS_DIR / "font-bold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]

_REGULAR_CANDIDATES = [
    config.ASSETS_DIR / "font-regular.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
]


@lru_cache(maxsize=64)
def get_font(size: int, bold: bool = True):
    """Return a PIL font of the requested size, using the first face found."""
    for path in (_BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES):
        try:
            if path.is_file():
                return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:      # Pillow < 10.1 has no size argument
        return ImageFont.load_default()


def font_path(bold: bool = True):
    """Path of the face that get_font would pick, or None if falling back."""
    for path in (_BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES):
        if path.is_file():
            return path
    return None
