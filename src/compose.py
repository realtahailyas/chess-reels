"""Canvas composition: board plus text, countdown, dots, watermark, band.

Every frame in the video is produced here. A frame is fully described by a
FrameState, which keeps the orchestrator free of drawing code.

This module never synthesizes cartoon reaction faces or emoji overlays (the
Section 0 rule). The variant-B reaction band shows real user-supplied video
clips, passed in via FrameState.band_content — not generated imagery.
"""

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path

import chess
import chess.engine
from PIL import Image, ImageDraw, ImageFont

import config
from src.board import square_center
from src.fonts import get_font

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def simple_eval(board: chess.Board) -> float:
    """Material balance in pawns, positive for White, with a mate override.

    Deliberately crude and Stockfish-free: it shows the sacrifice as a material
    dip followed by a mate spike, which is exactly the dramatic arc the format
    wants visible.
    """
    if board.is_checkmate():
        return -config.EVAL_CLAMP if board.turn == chess.WHITE else config.EVAL_CLAMP
    score = 0
    for _, piece in board.piece_map().items():
        v = PIECE_VALUES[piece.piece_type]
        score += v if piece.color == chess.WHITE else -v
    return max(-config.EVAL_CLAMP, min(config.EVAL_CLAMP, float(score)))


def _stockfish_path() -> str | None:
    env_path = (config.GM_STOCKFISH_PATH or os.environ.get("CHESS_REEL_STOCKFISH", "")).strip()
    if env_path and Path(env_path).is_file():
        return env_path
    candidates = [
        Path(r"C:\stockfish\stockfish.exe"),
        Path(r"C:\Program Files\Stockfish\stockfish.exe"),
        Path(r"C:\Program Files (x86)\Stockfish\stockfish.exe"),
        Path(r"C:\Program Files\stockfish\stockfish.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


@functools.lru_cache(maxsize=1)
def _gm_engine_path() -> str | None:
    return _stockfish_path()


@functools.lru_cache(maxsize=2048)
def _gm_eval_fen(fen: str) -> float | None:
    path = _gm_engine_path()
    if not path:
        return None
    board = chess.Board(fen)
    try:
        with chess.engine.SimpleEngine.popen_uci(path) as engine:
            info = engine.analyse(
                board,
                chess.engine.Limit(depth=config.GM_EVAL_DEPTH, time=config.GM_EVAL_TIME),
            )
    except Exception:
        return None

    score = info["score"].pov(chess.WHITE)
    mate = score.mate()
    if mate is not None:
        if mate > 0:
            return config.EVAL_CLAMP
        if mate < 0:
            return -config.EVAL_CLAMP
    cp = score.score(mate_score=100000)
    if cp is None:
        return None
    value = max(-config.EVAL_CLAMP, min(config.EVAL_CLAMP, cp / 100.0))
    return float(value)


def gm_eval(board: chess.Board) -> float:
    """Low-depth engine eval for the GM replay, with a safe fallback."""
    value = _gm_eval_fen(board.fen())
    if value is None:
        return simple_eval(board)
    return value


@dataclass
class FrameState:
    """Everything needed to draw one frame."""
    board_img: Image.Image
    series_label: str = ""
    theme_label: str = ""
    top_label: str = ""
    top_sub_label: str = ""
    bottom_label: str = ""
    bottom_sub_label: str = ""
    headline: str = ""
    headline_color: tuple = field(default_factory=lambda: config.WHITE)
    subtitle: str = ""
    subtitle_color: tuple = field(default_factory=lambda: config.MUTED)
    eval_value: float | None = None
    dots_total: int = 0
    dots_active: int = -1
    flash: float = 0.0            # 0..1 impact tint on the background
    countdown: str | None = None
    countdown_scale: float = 1.0
    countdown_progress: float = 1.0   # 1 -> 0, depletes the ring
    zoom: float = 1.0
    footer: str = ""
    brilliant_square: int | None = None   # draw the !! badge here
    brilliant_scale: float = 1.0           # pop-in scale, 0 hides it
    # Layout overrides; None means use the config default (variant A behaviour).
    board_y_offset: int | None = None
    headline_y: int | None = None
    band_content: object | None = None     # optional bottom-band overlay (RGB image)
    show_watermark: bool = True            # per-variant (Section 13.1: app = False)
    show_headline: bool = True             # per-variant; see VARIANTS show_headline
    show_eval_bar: bool = False
    show_promo_banner: bool = False        # per-variant TChess banner at the top


def board_rect(board_px: int = None, y_offset: int = None):
    """Return (x, y, size) of the board within the canvas."""
    board_px = board_px or config.BOARD_PX
    y_offset = config.BOARD_Y_OFFSET if y_offset is None else y_offset
    x = (config.CANVAS_W - board_px) // 2
    y = (config.CANVAS_H - board_px) // 2 + y_offset
    return x, y, board_px


def centred_text(draw, y, text, font, fill, shadow=True):
    """Draw horizontally centred text with a drop shadow for legibility."""
    if not text:
        return
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (config.CANVAS_W - (bbox[2] - bbox[0])) // 2 - bbox[0]
    if shadow:
        s = config.TEXT_SHADOW_PX
        draw.text((x + s, y + s), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=fill)


def _blend(a, b, t: float):
    t = max(0.0, min(1.0, t))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _zoom_board(img: Image.Image, zoom: float) -> Image.Image:
    """Scale about the centre and crop back to the original size."""
    if zoom <= 1.0001:
        return img
    w, h = img.size
    big = img.resize((int(w * zoom), int(h * zoom)), Image.LANCZOS)
    left = (big.width - w) // 2
    top = (big.height - h) // 2
    return big.crop((left, top, left + w, top + h))


def compose_frame(state: FrameState) -> Image.Image:
    """Render one 1080x1920 frame."""
    # Impact flash tints the background only; the board is never washed out.
    bg = _blend(config.BG, config.ACCENT, state.flash * 0.55) if state.flash > 0 \
        else config.BG
    canvas = Image.new("RGB", (config.CANVAS_W, config.CANVAS_H), bg)
    draw = ImageDraw.Draw(canvas)

    draw.rectangle([0, 0, config.CANVAS_W, config.ACCENT_BAR_H], fill=config.ACCENT)

    if state.series_label:
        centred_text(draw, config.SERIES_LABEL_Y, state.series_label.upper(),
                     get_font(config.FONT_SERIES, bold=True), config.WHITE)

    if state.theme_label:
        centred_text(draw, config.THEME_LABEL_Y, state.theme_label.upper(),
                     get_font(config.FONT_THEME), config.MUTED)

    # The banner and the theme label share the top row, so a promo variant
    # blanks theme_label rather than the two being drawn over each other
    # (build.build_one does that once, for every frame of the video).
    if state.show_promo_banner:
        _draw_promo_banner(canvas)

    headline_y = config.HEADLINE_Y if state.headline_y is None else state.headline_y
    if state.headline and state.show_headline:
        centred_text(draw, headline_y, state.headline,
                     get_font(config.FONT_HEADLINE), state.headline_color)

    # Bottom-band overlay (variant B), painted before the board so the board
    # always sits on top if they ever overlap.
    if state.band_content is not None:
        bx0, by0, bx1, by1 = config.REACTION_BAND
        canvas.paste(state.band_content.convert("RGB"), (bx0, by0))

    bx, by, bpx = board_rect(state.board_img.width, state.board_y_offset)
    board_img = _zoom_board(state.board_img, state.zoom)
    canvas.paste(board_img.convert("RGB"), (bx, by))

    if state.top_label:
        _draw_board_block(draw, bx, by - 94, bpx, state.top_label,
                          state.top_sub_label, align="top")

    if state.bottom_label:
        _draw_board_block(draw, bx, by + bpx + 18, bpx, state.bottom_label,
                          state.bottom_sub_label, align="bottom")

    # Badge is drawn on top of the board so it can overflow the square edge;
    # its corner placement keeps the piece underneath fully visible.
    if (config.SHOW_BRILLIANT and state.brilliant_square is not None
            and state.brilliant_scale > 0.01):
        _draw_brilliant(canvas, state.board_img.width, bx, by,
                        state.brilliant_square, state.brilliant_scale)

    if state.subtitle:
        centred_text(draw, by + bpx + config.SUBTITLE_GAP, state.subtitle,
                     get_font(config.FONT_SUBTITLE, bold=False), state.subtitle_color)

    if state.footer:
        centred_text(draw, by + bpx + config.SUBTITLE_GAP + config.FONT_SUBTITLE + 18,
                     state.footer, get_font(config.FONT_OUTRO_SMALL, bold=False),
                     config.MUTED)

    if state.eval_value is not None and state.show_eval_bar:
        _draw_eval_bar(draw, state.eval_value, bx, by, bpx)

    if state.countdown:
        _draw_countdown(canvas, draw, state)

    if state.dots_total:
        _draw_dots(draw, state.dots_total, state.dots_active)

    if state.show_watermark:
        _draw_watermark(canvas)
    return canvas


@functools.lru_cache(maxsize=4)
def _watermark_sprite(text, size, alpha):
    """Cached RGBA handle sprite: white text + soft shadow at given alpha."""
    font = get_font(size, bold=True)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    bbox = probe.textbbox((0, 0), text, font=font)
    pad = 6
    w = bbox[2] - bbox[0] + pad * 2
    h = bbox[3] - bbox[1] + pad * 2
    sprite = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    ox, oy = pad - bbox[0], pad - bbox[1]
    d.text((ox + 2, oy + 2), text, font=font, fill=(0, 0, 0, alpha))
    d.text((ox, oy), text, font=font, fill=(255, 255, 255, alpha))
    return sprite


def _draw_watermark(canvas):
    """Burn the channel handle onto a frame, bottom-centre, semi-transparent."""
    if not config.WATERMARK_TEXT:
        return
    wm = _watermark_sprite(config.WATERMARK_TEXT, config.WATERMARK_SIZE,
                           config.WATERMARK_ALPHA)
    x = (config.CANVAS_W - wm.width) // 2
    y = (config.CANVAS_H - config.SAFE_BOTTOM) - wm.height - config.WATERMARK_MARGIN
    canvas.paste(wm, (x, y), wm)


# ── TChess promo: top banner and end card ──────────────────────────────────
# Both are built once and cached, the same way the watermark is: they are
# identical on every frame they appear on, and a promo reel is ~600 frames.

@functools.lru_cache(maxsize=8)
def _brand_image(path: str, height: int = 0, width: int = 0) -> Image.Image:
    """Load a brand PNG as RGBA, scaled to a height OR a width.

    Missing assets are a build error rather than a silently unbranded video —
    a promo reel with no brand on it is the one outcome worth failing for.
    """
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(
            f"brand asset missing: {src}. See assets/brand/README.txt — it names "
            f"the source files and the two that must not be substituted.")
    img = Image.open(src).convert("RGBA")
    if height:
        width = max(1, round(img.width * height / img.height))
    elif width:
        height = max(1, round(img.height * width / img.width))
    else:
        return img
    return img.resize((width, height), Image.LANCZOS)


@functools.lru_cache(maxsize=8)
def _rook_mark(height: int) -> Image.Image:
    """The rook, trimmed to its own ink and scaled to `height`.

    The source is a 1024px adaptive-icon layer, so most of it is transparent
    padding for Android's mask. Scaling it without trimming makes the rook
    about half the size asked for, floating in empty space.
    """
    img = _brand_image(str(config.BRAND_MARK))
    box = img.getchannel("A").getbbox()
    if box:
        img = img.crop(box)
    return img.resize((max(1, round(img.width * height / img.height)), height),
                      Image.LANCZOS)


@functools.lru_cache(maxsize=8)
@functools.lru_cache(maxsize=8)
def _wordmark_sprite(height: int) -> Image.Image:
    """The DESIGNER'S wordmark — the chrome rook followed by "TChess".

    This used to compose its own lockup: the rook from mark.png standing beside
    the name typed in Sora Bold. That existed because the wordmark the app
    shipped at the time set the rook AS the letter T, so it read "♜Chess" to
    anyone who did not already know the brand. The delivered artwork has a real
    T, so the reason is gone and the app and the reels can finally be the same
    mark rather than two near-misses.

    The file is tight-cropped to its own ink (1463x384, aspect 3.82), so the
    height asked for is the height drawn — no trimming, no cap-height maths.
    """
    return _brand_image(str(config.BRAND_WORDMARK), height=height)


@functools.lru_cache(maxsize=2)
def _banner_sprite() -> Image.Image:
    """The TChess lockup over one line, in a violet-edged pill."""
    mark = _wordmark_sprite(config.PROMO_BANNER_WORDMARK_H)
    font = get_font(config.PROMO_BANNER_SUB_SIZE, bold=True)
    probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    sub = probe.textbbox((0, 0), config.PROMO_BANNER_SUB, font=font)
    sub_w, sub_h = sub[2] - sub[0], sub[3] - sub[1]

    w = max(mark.width, sub_w) + config.PROMO_BANNER_PAD * 2
    h = config.PROMO_BANNER_H
    sprite = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(sprite)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=config.PROMO_BANNER_RADIUS,
                        fill=config.APP_SURFACE + (235,),
                        outline=config.APP_VIOLET + (255,),
                        width=config.PROMO_BANNER_BORDER_W)

    block = mark.height + config.PROMO_BANNER_GAP + sub_h
    top = (h - block) // 2
    sprite.paste(mark, ((w - mark.width) // 2, top), mark)
    d.text(((w - sub_w) // 2 - sub[0],
            top + mark.height + config.PROMO_BANNER_GAP - sub[1]),
           config.PROMO_BANNER_SUB, font=font, fill=config.APP_VIOLET + (255,))
    return sprite


def _draw_promo_banner(canvas, y: int = None):
    """Paste the app banner, centred. `y` overrides the default top position.

    The mockups pass a bottom `y`: there the 108px section label is the header,
    so a banner above it is two headers arguing, and as a footer it is the one
    place a lockup does not compete with anything.
    """
    banner = _banner_sprite()
    canvas.paste(banner, ((config.CANVAS_W - banner.width) // 2,
                          config.PROMO_BANNER_Y if y is None else y), banner)


@functools.lru_cache(maxsize=4)
def _store_icon(px: int) -> Image.Image:
    """The real listing icon, rounded the way a store renders it."""
    icon = _brand_image(str(config.BRAND_STORE_ICON)).resize(
        (px, px), Image.LANCZOS)
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, px - 1, px - 1],
                                           radius=round(px * 0.22), fill=255)
    icon.putalpha(mask)
    return icon


def _draw_store_row(card: Image.Image, draw) -> None:
    """Icon + the exact listing title + developer, laid out like the store.

    The strings are the LIVE listing's, not a paraphrase — the row's whole job
    is that the Play page looks like this frame when it opens.
    """
    x0, y0, x1, y1 = config.ENDCARD_STORE_CARD
    draw.rounded_rectangle([x0, y0, x1, y1], radius=config.ENDCARD_STORE_RADIUS,
                           fill=config.APP_SURFACE, outline=config.APP_HAIRLINE,
                           width=1)

    px = config.ENDCARD_STORE_ICON_PX
    icon = _store_icon(px)
    card.paste(icon, (config.ENDCARD_STORE_ICON_X, (y0 + y1 - px) // 2), icon)

    title_font = get_font(config.ENDCARD_STORE_TITLE_SIZE, bold=True)
    dev_font = get_font(config.ENDCARD_STORE_DEV_SIZE, bold=False)
    lead = config.ENDCARD_STORE_TITLE_LEAD
    block = lead * len(config.ENDCARD_STORE_TITLE) + config.ENDCARD_STORE_DEV_SIZE + 14
    ty = (y0 + y1 - block) // 2

    for i, line in enumerate(config.ENDCARD_STORE_TITLE):
        draw.text((config.ENDCARD_STORE_TEXT_X, ty + i * lead), line,
                  font=title_font, fill=config.APP_TEXT_HI)
    draw.text((config.ENDCARD_STORE_TEXT_X, ty + lead * len(config.ENDCARD_STORE_TITLE) + 10),
              config.ENDCARD_STORE_DEV, font=dev_font, fill=config.PLAY_GREEN)


@functools.lru_cache(maxsize=2)
def _endcard_base() -> Image.Image:
    """The finished end card, drawn once.

    Deliberately countless: the app ships one puzzle total and the website
    another, so naming features instead of counting them is the only version
    that cannot be wrong. tests/test_promo.py enforces it.
    """
    card = Image.new("RGB", (config.CANVAS_W, config.CANVAS_H), config.BG)
    draw = ImageDraw.Draw(card)

    mark = _wordmark_sprite(config.ENDCARD_WORDMARK_H)
    card.paste(mark, ((config.CANVAS_W - mark.width) // 2,
                      config.ENDCARD_WORDMARK_Y), mark)

    centred_text(draw, config.ENDCARD_TAGLINE_Y, config.ENDCARD_TAGLINE,
                 get_font(config.ENDCARD_TAGLINE_SIZE, bold=True),
                 config.APP_TEXT_HI, shadow=False)

    for y in (config.ENDCARD_RULE_TOP_Y, config.ENDCARD_RULE_BOT_Y):
        draw.line([(config.ENDCARD_RULE_X0, y), (config.ENDCARD_RULE_X1, y)],
                  fill=config.APP_HAIRLINE, width=1)

    # Two columns, filled row by row so the reading order is left-to-right.
    feat_font = get_font(config.ENDCARD_FEAT_SIZE, bold=False)
    for i, name in enumerate(config.ENDCARD_FEATURES):
        bx = config.ENDCARD_FEAT_COL_X[i % 2]
        by = config.ENDCARD_FEAT_Y + (i // 2) * config.ENDCARD_FEAT_ROW_H
        cy = by + config.ENDCARD_FEAT_SIZE // 2
        r = config.ENDCARD_BULLET_R
        draw.ellipse([bx - r, cy - r, bx + r, cy + r], fill=config.APP_VIOLET)
        draw.text((bx + config.ENDCARD_FEAT_TEXT_DX, by), name,
                  font=feat_font, fill=config.APP_TEXT_HI)

    centred_text(draw, config.ENDCARD_PROMISE_Y, config.ENDCARD_PROMISE,
                 get_font(config.ENDCARD_PROMISE_SIZE, bold=False),
                 config.MUTED, shadow=False)

    _draw_store_row(card, draw)

    # Google Play's own green, not the app's violet. The whole row exists to be
    # recognised, and the viewer is about to look at a green Install button.
    x0, y0, x1, y1 = config.ENDCARD_PILL
    draw.rounded_rectangle([x0, y0, x1, y1], radius=config.ENDCARD_PILL_RADIUS,
                           fill=config.PLAY_GREEN)
    pill_font = get_font(config.ENDCARD_PLAY_SIZE, bold=True)
    pb = draw.textbbox((0, 0), config.ENDCARD_INSTALL, font=pill_font)
    draw.text(((config.CANVAS_W - (pb[2] - pb[0])) // 2 - pb[0],
               (y0 + y1 - (pb[3] - pb[1])) // 2 - pb[1]),
              config.ENDCARD_INSTALL, font=pill_font, fill=(255, 255, 255))

    # 🔴 NO ENDCARD_WEB LINE HERE ANY MORE, AND IT IS NOT AN OVERSIGHT.
    # The watermark below now prints the same string (WATERMARK_TEXT became
    # tchess.app/android, replacing the old @tchessapp handle), so drawing both
    # put the URL on the card twice, stacked. The watermark wins because it is
    # on EVERY frame of the reel, not just this one — a viewer who screenshots
    # mid-puzzle still gets the link. config.ENDCARD_WEB is kept for the
    # carousel, which has no watermark row of its own.
    _draw_watermark(card)
    return card


def endcard_frame(alpha: float = 1.0) -> Image.Image:
    """One end-card frame, faded up from the background over ENDCARD_FADE.

    Takes no FrameState and no board: it is not a board frame.
    """
    base = _endcard_base()
    if alpha >= 0.999:
        return base.copy()
    ground = Image.new("RGB", base.size, config.BG)
    return Image.blend(ground, base, max(0.0, alpha))


def _draw_eval_bar(draw, value, bx, by, bpx):
    """Vertical material/mate bar: White fills from the bottom."""
    x1 = bx - config.EVAL_BAR_GAP
    x0 = x1 - config.EVAL_BAR_W
    frac = (value + config.EVAL_CLAMP) / (2 * config.EVAL_CLAMP)
    frac = max(0.0, min(1.0, frac))
    split = by + bpx * (1.0 - frac)

    draw.rectangle([x0, by, x1, by + bpx], fill=(28, 28, 32))
    draw.rectangle([x0, split, x1, by + bpx], fill=config.WHITE)
    draw.rectangle([x0, by, x1, split], fill=(22, 22, 25))
    draw.line([x0, split, x1, split], fill=config.ACCENT, width=3)
    draw.rectangle([x0, by, x1, by + bpx], outline=(60, 60, 66), width=2)


def _draw_countdown(canvas, draw, state):
    """Large accent numeral with a depleting progress ring."""
    cy = config.COUNTDOWN_CY
    size = max(12, int(config.FONT_COUNTDOWN * state.countdown_scale))
    font = get_font(size)

    bbox = draw.textbbox((0, 0), state.countdown, font=font)
    x = (config.CANVAS_W - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = cy - (bbox[3] - bbox[1]) // 2 - bbox[1]
    s = config.TEXT_SHADOW_PX
    draw.text((x + s, y + s), state.countdown, font=font, fill=(0, 0, 0))
    draw.text((x, y), state.countdown, font=font, fill=config.ACCENT)

    r = config.COUNTDOWN_RING_R
    box = [config.CANVAS_W // 2 - r, cy - r, config.CANVAS_W // 2 + r, cy + r]
    draw.arc(box, start=0, end=360, fill=(45, 45, 50), width=config.COUNTDOWN_RING_W)
    sweep = 360 * max(0.0, min(1.0, state.countdown_progress))
    if sweep > 0:
        draw.arc(box, start=-90, end=-90 + sweep, fill=config.ACCENT,
                 width=config.COUNTDOWN_RING_W)


def _draw_dots(draw, total, active):
    """One dot per timeline beat; the current beat is accented and larger."""
    y = config.CANVAS_H - config.DOTS_FROM_BOTTOM
    gap, r = 34, 9
    width = (total - 1) * gap
    x0 = config.CANVAS_W // 2 - width // 2
    for i in range(total):
        cx = x0 + i * gap
        if i == active:
            draw.ellipse([cx - r - 2, y - r - 2, cx + r + 2, y + r + 2],
                         fill=config.ACCENT)
        elif i < active:
            draw.ellipse([cx - r, y - r, cx + r, y + r], fill=(110, 108, 104))
        else:
            draw.ellipse([cx - r + 2, y - r + 2, cx + r - 2, y + r - 2],
                         fill=(58, 57, 55))


def _draw_brilliant(canvas, board_px, bx, by, square, scale):
    """Chess.com-style '!!' badge on a square's top-right corner.

    Drawn supersampled on a transparent layer then downscaled, so the circle
    and text stay crisp. The badge overflows the square edge on purpose; its
    corner placement leaves the piece in the square centre fully visible.
    """
    sq_x, sq_y, cell = square_center(square, board_px)
    cx = bx + sq_x + cell * config.BRILLIANT_OFFSET
    cy = by + sq_y - cell * config.BRILLIANT_OFFSET
    r = cell * config.BRILLIANT_RADIUS * scale
    if r < 1:
        return

    ss = 4
    box = int(r * 2 * ss) + 4
    layer = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = box / 2
    rs = r * ss
    border = max(2 * ss, int(cell * 0.02 * ss))

    d.ellipse([c - rs, c - rs, c + rs, c + rs],
              fill=config.BRILLIANT_COLOR + (255,),
              outline=(255, 255, 255, 255), width=border)

    font = get_font(max(6, int(cell * 0.30 * scale * ss)), bold=True)
    bbox = d.textbbox((0, 0), "!!", font=font)
    tx = c - (bbox[2] - bbox[0]) / 2 - bbox[0]
    ty = c - (bbox[3] - bbox[1]) / 2 - bbox[1]
    d.text((tx, ty), "!!", font=font, fill=(255, 255, 255, 255))

    layer = layer.resize((box // ss, box // ss), Image.LANCZOS)
    canvas.paste(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)),
                 layer)


def render_band_strip(moves, band_size=None, highlight=None):
    """Render the 'line so far' strip for the reaction band's idle state.

    `moves` is the list of SAN tokens played so far; `highlight` is the index to
    accent (default: the last one). Keeps the band from reading as dead space.
    """
    w, h = band_size or (config.REACTION_BAND_W, config.REACTION_BAND_H)
    if highlight is None:
        highlight = len(moves) - 1

    panel = Image.new("RGB", (w, h), (20, 20, 24))
    draw = ImageDraw.Draw(panel)
    draw.rectangle([0, 0, w, 3], fill=config.ACCENT)     # top rule

    title_font = get_font(34, bold=True)
    draw.text((40, 26), "THE LINE", font=title_font, fill=config.MUTED)

    if not moves:
        return panel

    chip_font = get_font(52, bold=True)
    pad_x, pad_h, gap = 26, 74, 20
    margin = 40

    # Measure chips, then lay them out in centred, wrapping rows.
    chips = []
    for tok in moves:
        bbox = draw.textbbox((0, 0), tok, font=chip_font)
        chips.append((tok, bbox[2] - bbox[0]))

    rows, row, row_w = [], [], 0
    for tok, tw in chips:
        cw = tw + 2 * pad_x
        if row and row_w + gap + cw > w - 2 * margin:
            rows.append((row, row_w))
            row, row_w = [], 0
        row_w += (gap if row else 0) + cw
        row.append((tok, tw, cw))
    if row:
        rows.append((row, row_w))

    block_h = len(rows) * pad_h + (len(rows) - 1) * gap
    y = 90 + max(0, (h - 110 - block_h) // 2)
    idx = 0
    for row, row_w in rows:
        x = (w - row_w) // 2
        for tok, tw, cw in row:
            is_hi = idx == highlight
            bg = config.ACCENT if is_hi else (36, 36, 42)
            fg = (16, 16, 19) if is_hi else config.WHITE
            draw.rounded_rectangle([x, y, x + cw, y + pad_h], radius=16, fill=bg)
            tb = draw.textbbox((0, 0), tok, font=chip_font)
            draw.text((x + (cw - tw) // 2 - tb[0], y + (pad_h - (tb[3] - tb[1])) // 2 - tb[1]),
                      tok, font=chip_font, fill=fg)
            x += cw + gap
            idx += 1
        y += pad_h + gap
    return panel


def _draw_board_block(draw, bx, y, bpx, label, sublabel, align="top"):
    """Player label block placed directly above or below the board."""
    label_font = get_font(38, bold=True)
    sub_font = get_font(28, bold=False)
    label_box = draw.textbbox((0, 0), label, font=label_font)
    sub_box = draw.textbbox((0, 0), sublabel, font=sub_font) if sublabel else None
    block_w = max(label_box[2] - label_box[0], (sub_box[2] - sub_box[0]) if sub_box else 0)
    block_x = bx + (bpx - block_w) // 2
    label_y = y
    sub_y = y + 40
    if align == "bottom" and sublabel:
        label_y = y + 10
        sub_y = y - 24
    draw.text((block_x - label_box[0], label_y), label, font=label_font, fill=config.WHITE)
    if sublabel:
        draw.text((block_x - sub_box[0], sub_y), sublabel, font=sub_font, fill=config.MUTED)


def move_label(san: str, is_sacrifice: bool):
    """Return (label, colour) applying the !! rule.

    The sacrifice renders in the accent colour. When the brilliant badge is on
    (SHOW_BRILLIANT), the '!!' lives in the badge on the board, so the headline
    keeps just the SAN and does not duplicate it; with the badge off, the '!!'
    falls back into the headline. Checkmate also renders in accent.
    """
    if is_sacrifice:
        if config.SHOW_BRILLIANT:
            return san, config.ACCENT
        return f"{san} !!", config.ACCENT
    if "#" in san:
        return san, config.ACCENT
    return san, config.WHITE
