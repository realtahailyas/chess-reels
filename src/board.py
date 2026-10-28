"""Board rendering, coordinate math, and piece sprites.

Two renderers are available and produce the same geometry:

  cairo — chess.svg + cairosvg, the reference path from the spec
  pil   — the bundled rasterizer, used when no Cairo system library is present

Both are driven by the exact 390-unit viewBox math in Section 5.2, so a piece
animated with square_center() lands on the right square under either renderer.
"""

import functools
import io
import math

import chess
import chess.svg
from PIL import Image, ImageDraw

import config
from src import svgrender
from src.fonts import get_font

# ── Coordinate math — EXACT, DO NOT GUESS (Section 5.2) ───────────────────
# python-chess emits viewBox="0 0 390 390" whenever coordinates are enabled,
# regardless of the size parameter: 15 margin + 360 board + 15 margin, so each
# cell is 45 units. Coordinates must stay on for this to hold.
VIEWBOX = 390.0
MARGIN_UNITS = 15.0
CELL_UNITS = 45.0


def square_center(square: int, board_px: int):
    """Return (x, y, cell_px) — pixel centre of a square within the board image."""
    scale = board_px / VIEWBOX
    margin = MARGIN_UNITS * scale
    cell = CELL_UNITS * scale
    f = chess.square_file(square)           # 0..7, a..h
    r = chess.square_rank(square)           # 0..7, rank1..rank8
    x = margin + cell * f + cell / 2
    y = margin + cell * (7 - r) + cell / 2  # SVG y-axis is inverted
    return x, y, cell


def board_metrics(board_px: int):
    """Return (margin_px, cell_px) for a board image."""
    scale = board_px / VIEWBOX
    return MARGIN_UNITS * scale, CELL_UNITS * scale


# ── Renderer selection ────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _cairo():
    """Return a working cairosvg module, or None.

    Importing cairosvg succeeds even when the native Cairo library is absent;
    the failure only surfaces on first render, so this probes a real render.
    """
    try:
        import cairosvg
        cairosvg.svg2png(
            bytestring=b'<svg xmlns="http://www.w3.org/2000/svg" width="4" '
                       b'height="4"><rect width="4" height="4"/></svg>',
            output_width=4, output_height=4,
        )
        return cairosvg
    except Exception:
        return None


@functools.lru_cache(maxsize=1)
def active_renderer() -> str:
    """Return "cairo" or "pil" based on config and what actually works."""
    want = config.BOARD_RENDERER.lower()
    if want == "pil":
        return "pil"
    if want == "cairo":
        if _cairo() is None:
            raise RuntimeError(
                "BOARD_RENDERER='cairo' but the Cairo library failed to load. "
                "Install it, or set BOARD_RENDERER='auto'."
            )
        return "cairo"
    return "cairo" if _cairo() is not None else "pil"


def _svg_to_image(svg: str, px: int) -> Image.Image:
    if active_renderer() == "cairo":
        png = _cairo().svg2png(bytestring=svg.encode(),
                               output_width=px, output_height=px)
        return Image.open(io.BytesIO(png)).convert("RGBA")
    return svgrender.rasterize(svg, px, config.PIL_SUPERSAMPLE)


# ── Piece sprites ─────────────────────────────────────────────────────────

_sprite_cache: dict[tuple[str, int], Image.Image] = {}


def piece_sprite(piece: chess.Piece, px: int) -> Image.Image:
    """Return a piece on a transparent background, sized px by px.

    Cached: regenerating sprites every frame is the single biggest performance
    mistake in this pipeline (Section 5.3).
    """
    key = (piece.symbol(), px)
    hit = _sprite_cache.get(key)
    if hit is None:
        svg = chess.svg.piece(piece, size=px)
        hit = _svg_to_image(svg, px)
        _sprite_cache[key] = hit
    return hit


def clear_sprite_cache():
    _sprite_cache.clear()


# ── Board rendering ───────────────────────────────────────────────────────

def render_board(board: chess.Board, board_px: int = None, lastmove=None,
                 check=None, arrows=()) -> Image.Image:
    """Render a position to an RGBA image of board_px x board_px."""
    board_px = board_px or config.BOARD_PX
    if active_renderer() == "cairo":
        svg = chess.svg.board(
            board,
            size=board_px,
            lastmove=lastmove,
            check=check,
            arrows=list(arrows),
            colors=config.BOARD_COLORS,
            coordinates=True,     # required for the 390-unit viewBox
        )
        return _svg_to_image(svg, board_px)
    return _render_board_pil(board, board_px, lastmove, check, arrows)


def _hex(name: str):
    value = config.BOARD_COLORS[name]
    return svgrender.parse_color(value) or (0, 0, 0)


def _render_board_pil(board, board_px, lastmove, check, arrows):
    """Draw the board with PIL using the same 390-unit geometry as chess.svg."""
    margin, cell = board_metrics(board_px)
    img = Image.new("RGBA", (board_px, board_px), _hex("margin") + (255,))
    draw = ImageDraw.Draw(img)

    light, dark = _hex("square light"), _hex("square dark")
    light_lm, dark_lm = _hex("square light lastmove"), _hex("square dark lastmove")
    lastmove_squares = {lastmove.from_square, lastmove.to_square} if lastmove else set()

    for square in chess.SQUARES:
        f, r = chess.square_file(square), chess.square_rank(square)
        x0 = margin + cell * f
        y0 = margin + cell * (7 - r)
        is_light = (f + r) % 2 == 1
        if square in lastmove_squares:
            colour = light_lm if is_light else dark_lm
        else:
            colour = light if is_light else dark
        draw.rectangle([x0, y0, x0 + cell, y0 + cell], fill=colour + (255,))

    if check is not None:
        _draw_check_glow(img, check, board_px)

    # Coordinates in the margin, matching chess.svg's placement.
    coord = _hex("coord") + (255,)
    fsize = max(8, int(cell * 0.26))
    font = get_font(fsize, bold=True)
    for f in range(8):
        letter = chr(ord("a") + f)
        cx = margin + cell * f + cell / 2
        _centre_text(draw, cx, board_px - margin / 2, letter, font, coord)
    for r in range(8):
        cy = margin + cell * (7 - r) + cell / 2
        _centre_text(draw, margin / 2, cy, str(r + 1), font, coord)

    for square, piece in board.piece_map().items():
        sprite = piece_sprite(piece, int(round(cell)))
        cx, cy, _ = square_center(square, board_px)
        img.paste(sprite, (int(cx - sprite.width / 2), int(cy - sprite.height / 2)), sprite)

    for arrow in arrows:
        _draw_arrow(img, arrow, board_px)

    return img


def _centre_text(draw, cx, cy, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (bbox[2] - bbox[0]) / 2 - bbox[0],
               cy - (bbox[3] - bbox[1]) / 2 - bbox[1]), text, font=font, fill=fill)


def _draw_check_glow(img, square, board_px):
    """Radial red glow on the checked king, mirroring chess.svg's gradient."""
    cx, cy, cell = square_center(square, board_px)
    colour = svgrender.parse_color(config.CHECK_COLOR) or (229, 83, 61)
    steps = 12
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for i in range(steps, 0, -1):
        r = cell / 2 * (i / steps)
        alpha = int(210 * (1 - (i / steps) ** 2) + 45)
        gdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour + (alpha,))
    img.alpha_composite(glow)


def _draw_arrow(img, arrow, board_px):
    """Draw a chess.svg.Arrow as a line with a triangular head."""
    tail = getattr(arrow, "tail", None)
    head = getattr(arrow, "head", None)
    if tail is None or head is None or tail == head:
        return
    colour = svgrender.parse_color(getattr(arrow, "color", "#00A000")) or (0, 160, 0)
    x0, y0, cell = square_center(tail, board_px)
    x1, y1, _ = square_center(head, board_px)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    angle = math.atan2(y1 - y0, x1 - x0)
    head_len = cell * 0.38
    bx, by = x1 - math.cos(angle) * head_len, y1 - math.sin(angle) * head_len
    d.line([(x0, y0), (bx, by)], fill=colour + (200,), width=max(3, int(cell * 0.14)))
    wing = cell * 0.22
    d.polygon([
        (x1, y1),
        (bx - math.sin(angle) * wing, by + math.cos(angle) * wing),
        (bx + math.sin(angle) * wing, by - math.cos(angle) * wing),
    ], fill=colour + (200,))
    img.alpha_composite(layer)
