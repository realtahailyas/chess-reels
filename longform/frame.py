"""1920x1080 frame composition for the long-form game videos.

Layout: board on the left with the eval bar beside it; on the right a panel with
the brand row, black's card, the opening, the move list, the moment card and
white's card. Black sits on top because the board is drawn from White's side.

The expensive parts are cached by what they depend on: the static base once per
video, the right panel once per ply (it only changes when a move lands), so a
frame during a slide is just base + panel + board + eval bar.
"""

import functools
import math

import chess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config
from src import board as board_mod
from src.fonts import get_font
from longform import engine
from longform import lfconfig as C

START_COUNTS = {(c, t): len(chess.Board().pieces(t, c))
                for c in chess.COLORS for t in chess.PIECE_TYPES}


@functools.lru_cache(maxsize=64)
def sora(size: int):
    return ImageFont.truetype(str(C.SORA), size)


def body(size: int, bold: bool = False):
    return get_font(size, bold=bold)


def text_w(draw, text, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def draw_text(draw, xy, text, font, fill, anchor="la"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def spaced(draw, xy, text, font, fill, spacing=3, anchor_right=False):
    """Tracked-out small caps: labels read as labels, not sentences."""
    x, y = xy
    widths = [text_w(draw, ch, font) if ch != " " else font.size // 3 for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    if anchor_right:
        x -= total
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + spacing
    return total


def rounded(draw, box, radius, fill, outline=None, width=1, lit=True):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    if lit:
        x0, y0, x1, _ = box
        draw.line([(x0 + radius, y0), (x1 - radius, y0)], fill=C.BORDER_LIT, width=1)


@functools.lru_cache(maxsize=4)
def board_mask(px: int, radius: int = 18) -> Image.Image:
    m = Image.new("L", (px, px), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, px - 1, px - 1], radius=radius, fill=255)
    return m


@functools.lru_cache(maxsize=4)
def glow(size: int, colour: tuple, alpha: int) -> Image.Image:
    """Radial bloom with a little dither, so dark gradients do not band."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    r = np.hypot(xx - size / 2, yy - size / 2) / (size / 2)
    a = np.clip(1 - r, 0, 1) ** 2 * alpha
    a += np.random.default_rng(7).uniform(-1.2, 1.2, a.shape)
    out = Image.new("RGBA", (size, size), colour + (0,))
    out.putalpha(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "L"))
    return out


@functools.lru_cache(maxsize=8)
def brand_mark(px: int, path: str) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    im = im.crop(im.getchannel("A").getbbox())
    return im.resize((max(1, round(px * im.width / im.height)), px), Image.LANCZOS)


@functools.lru_cache(maxsize=16)
def avatar(slug, name: str, px: int, ring: tuple = None) -> Image.Image:
    """Round portrait from data/longform/photos, or initials when there is none."""
    from longform import players
    path = players.photo_path(slug)
    ss = 3                                   # supersample the circle edge
    big = px * ss
    if path:
        face = Image.open(path).convert("RGB").resize((big, big), Image.LANCZOS)
    else:
        face = Image.new("RGB", (big, big), (40, 30, 56))
        initials = "".join(w[0] for w in name.split()[:2]).upper()
        ImageDraw.Draw(face).text((big / 2, big / 2), initials, font=sora(int(big * 0.38)),
                                  fill=C.PRIMARY_BRIGHT, anchor="mm")
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(face, (0, 0), mask)
    if ring:
        w = max(2, big // 28)
        ImageDraw.Draw(out).ellipse([w // 2, w // 2, big - 1 - w // 2, big - 1 - w // 2],
                                    outline=ring, width=w)
    return out.resize((px, px), Image.LANCZOS)


def inner_board_box():
    margin, _ = board_mod.board_metrics(C.BOARD_PX)
    top = C.BOARD_Y + margin
    return top, C.BOARD_Y + C.BOARD_PX - margin


class Frames:
    # The 16:9 YouTube layout. frame_vertical.VFrames is the 9:16 one; render.py
    # only uses these attributes and the methods below, so either plugs in.
    W, H, board_px = C.W, C.H, C.BOARD_PX
    suffix = ""

    def __init__(self, game: dict, judgements: list, positions: list,
                 openings: list, brand: str = "tchess"):
        self.g = game
        self.j = judgements
        self.pos = positions
        self.openings = openings
        self.brand = C.BRANDS[brand]
        self.n = len(game["moves"])
        self.base = self._base()
        self._panel_cache = {}

    # ── static ────────────────────────────────────────────────────────────
    def _base(self) -> Image.Image:
        img = Image.new("RGBA", (C.W, C.H), C.BG + (255,))
        g = glow(1500, C.PRIMARY, 38)
        img.alpha_composite(g, (C.BOARD_X + C.BOARD_PX // 2 - 750, C.BOARD_Y + C.BOARD_PX // 2 - 750))
        d = ImageDraw.Draw(img)

        # Brand row.
        nx = C.PANEL_X
        if self.brand.get("mark"):
            mark = brand_mark(46, str(self.brand["mark"]))
            img.alpha_composite(mark, (C.PANEL_X + 2, C.BRAND_Y - 5))
            nx += mark.width + 16
        draw_text(d, (nx, C.BRAND_Y + 18), self.brand["name"], sora(34), C.TEXT_HI, "lm")
        where = " · ".join(x for x in (self.g["site"] or self.g["event"], self.g["year"]) if x).upper()
        spaced(d, (C.PANEL_X + C.PANEL_W, C.BRAND_Y + 8), where, body(22, True), C.TEXT_MID,
               spacing=2, anchor_right=True)

        # Player card shells and the move-area label.
        for y in (C.CARD_TOP_Y, C.CARD_BOTTOM_Y):
            rounded(d, [C.PANEL_X, y, C.PANEL_X + C.PANEL_W, y + C.CARD_H], 18,
                    C.SURFACE, C.BORDER)
        spaced(d, (C.PANEL_X + 4, C.OPENING_Y - 6), "OPENING", body(18, True), C.TEXT_LOW, 3)
        # Eval bar trough.
        top, bottom = inner_board_box()
        rounded(d, [C.EVAL_X - 3, top - 3, C.EVAL_X + C.EVAL_W + 3, bottom + 3], 8,
                C.SURFACE_ALT, C.BORDER, lit=False)
        return img.convert("RGB")

    # ── right panel (per ply) ─────────────────────────────────────────────
    def panel(self, ply: int, board: chess.Board, moment: dict | None) -> Image.Image:
        key = (ply, id(moment) if moment else None)
        hit = self._panel_cache.get(key)
        if hit is not None:
            return hit
        img = Image.new("RGBA", (C.PANEL_W, C.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        to_move = board.turn
        self._card(img, d, C.CARD_TOP_Y, chess.BLACK, board, active=to_move == chess.BLACK)
        self._card(img, d, C.CARD_BOTTOM_Y, chess.WHITE, board, active=to_move == chess.WHITE)
        name = self.openings[min(ply, len(self.openings) - 1)] or "Starting position"
        font = sora(30)
        while text_w(d, name, font) > C.PANEL_W - 10 and font.size > 20:
            font = sora(font.size - 2)
        draw_text(d, (4, C.OPENING_Y + 22), name, font, C.TEXT_HI)
        self._moves(d, ply)
        if moment:
            self._moment(img, d, moment)
        else:
            self._status(d, ply)
        if len(self._panel_cache) > 12:
            self._panel_cache.pop(next(iter(self._panel_cache)))
        self._panel_cache[key] = img
        return img

    def _card(self, img, d, y, colour, board, active):
        x = 0
        white = colour == chess.WHITE
        name = self.g["white"] if white else self.g["black"]
        slug = self.g.get("white_slug") if white else self.g.get("black_slug")
        elo = self.g["white_elo"] if white else self.g["black_elo"]
        if active:
            d.rounded_rectangle([x, y + 22, x + 6, y + C.CARD_H - 22], radius=3, fill=C.PRIMARY)
        av = 96
        ring = (233, 233, 234) if white else (70, 70, 76)
        img.alpha_composite(avatar(slug, name, av, ring), (x + 22, y + (C.CARD_H - av) // 2))
        # Which colour this player has: a small piece-coloured dot on the photo.
        dx, dy = x + 22 + av - 24, y + (C.CARD_H + av) // 2 - 24
        d.ellipse([dx, dy, dx + 24, dy + 24], fill=(233, 233, 234) if white else (0, 0, 0),
                  outline=C.SURFACE, width=3)
        sx = x + 22 + av + 20
        nf = sora(40)
        while text_w(d, name, nf) > C.PANEL_W - sx - 110 and nf.size > 26:
            nf = sora(nf.size - 2)
        draw_text(d, (sx, y + 44), name, nf, C.TEXT_HI, "lm")
        if elo:
            draw_text(d, (C.PANEL_W - 28, y + 44), elo, body(30, True), C.TEXT_MID, "rm")

        # Pieces this side has captured, on a light tray so both colours read.
        opp = not colour
        sprite_px = 34
        order = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]
        caps = []
        for t in order:
            missing = max(0, START_COUNTS[(opp, t)] - len(board.pieces(t, opp)))
            caps += [t] * missing
        cy = y + 78
        cx = sx
        if caps:
            step = sprite_px * 0.78
            tray_w = int(step * (len(caps) - 1) + sprite_px + 16)
            d.rounded_rectangle([cx, cy - 2, cx + tray_w, cy + sprite_px + 2], radius=10,
                                fill=(223, 227, 206))
            px = cx + 8
            for t in caps:
                spr = board_mod.piece_sprite(chess.Piece(t, opp), sprite_px)
                img.alpha_composite(spr, (int(px), cy))
                px += step
            cx += tray_w
        lead = self._material(board, colour) - self._material(board, opp)
        if lead > 0:
            draw_text(d, (cx + 14, cy + sprite_px / 2), f"+{lead}", body(28, True), C.TEXT_MID, "lm")

    @staticmethod
    def _material(board, colour):
        return sum(len(board.pieces(t, colour)) * engine.VALUE[t] for t in chess.PIECE_TYPES)

    def _moves(self, d, ply):
        rows = (ply + 1) // 2 if ply else 0
        cur = ply - 1
        if rows == 0:
            return
        last_row = (cur // 2) if cur >= 0 else 0
        start = max(0, min(last_row - (C.MOVE_ROWS - 3), rows - C.MOVE_ROWS))
        start = max(0, start)
        f_no = body(28)
        f_san = sora(30)
        for r in range(start, min(rows, start + C.MOVE_ROWS)):
            y = C.MOVES_Y + (r - start) * C.MOVE_ROW_H
            if r % 2 == 0:
                d.rounded_rectangle([0, y, C.PANEL_W, y + C.MOVE_ROW_H - 4], radius=8, fill=C.SURFACE)
            draw_text(d, (22, y + C.MOVE_ROW_H / 2 - 2), f"{r + 1}.", f_no, C.TEXT_LOW, "lm")
            for side, x in ((0, 110), (1, 400)):
                p = r * 2 + side
                if p > cur:
                    continue
                san = self.g["sans"][p]
                glyph = self.j[p]["glyph"]
                glyph = None if glyph == "#" else glyph
                wd = text_w(d, san, f_san) + (text_w(d, glyph, f_san) if glyph else 0)
                if p == cur:
                    d.rounded_rectangle([x - 12, y + 3, x + wd + 12, y + C.MOVE_ROW_H - 7],
                                        radius=8, fill=C.PRIMARY)
                draw_text(d, (x, y + C.MOVE_ROW_H / 2 - 2), san, f_san,
                          (255, 255, 255) if p == cur else C.TEXT_HI, "lm")
                if glyph:
                    gx = x + text_w(d, san, f_san)
                    draw_text(d, (gx, y + C.MOVE_ROW_H / 2 - 2), glyph, f_san,
                              (255, 255, 255) if p == cur else C.GLYPH_COLORS[glyph], "lm")

    def _moment(self, img, d, m):
        y0, y1 = C.MOMENT_Y, C.MOMENT_Y + C.MOMENT_H
        col = m["color"]
        rounded(d, [0, y0, C.PANEL_W, y1], 20, C.SURFACE, C.BORDER)
        d.rounded_rectangle([0, y0 + 24, 7, y1 - 24], radius=3, fill=col)
        cx, cy, r = 84, (y0 + y1) // 2, 50
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        big = m.get("big", "")
        draw_text(d, (cx, cy + 2), big, sora(44 if len(big) < 3 else 34), (255, 255, 255), "mm")
        tx = 160
        spaced(d, (tx, y0 + 30), m["title"], body(22, True), col, 3)
        draw_text(d, (tx, y0 + 64), m["headline"], sora(46), C.TEXT_HI)
        if m.get("sub"):
            draw_text(d, (tx, y0 + 128), m["sub"], body(26), C.TEXT_MID)

    def _status(self, d, ply):
        y0 = C.MOMENT_Y
        full = (self.n + 1) // 2
        move_no = max(1, (ply + 1) // 2) if ply else 0
        spaced(d, (4, y0 + 30), "MOVE", body(22, True), C.TEXT_LOW, 3)
        draw_text(d, (4, y0 + 62), f"{move_no}", sora(64), C.TEXT_HI)
        w = text_w(d, f"{move_no}", sora(64))
        draw_text(d, (14 + w, y0 + 96), f"/ {full}", sora(32), C.TEXT_LOW)
        ev = engine.fmt_eval(self.pos[ply]["score"]) if not self.pos[ply].get("terminal") else ""
        if ev:
            spaced(d, (C.PANEL_W - 4, y0 + 30), "ENGINE", body(22, True), C.TEXT_LOW, 3, anchor_right=True)
            draw_text(d, (C.PANEL_W - 4, y0 + 62), ev, sora(64), C.TEXT_HI, "ra")
        # Progress through the game.
        by = y0 + C.MOMENT_H - 22
        d.rounded_rectangle([4, by, C.PANEL_W - 4, by + 8], radius=4, fill=C.SURFACE_ALT)
        frac = ply / max(1, self.n)
        if frac > 0:
            d.rounded_rectangle([4, by, 4 + int((C.PANEL_W - 8) * frac), by + 8], radius=4, fill=C.PRIMARY)

    # ── per-frame ─────────────────────────────────────────────────────────
    def frame(self, board_img: Image.Image, panel: Image.Image, eval_frac: float,
              eval_label: str, badge=None, tint=None) -> Image.Image:
        img = self.base.copy()
        bimg = board_img
        if badge or tint:
            bimg = board_img.copy()
            if tint:
                self._tint(bimg, *tint)
            if badge:
                self._badge(bimg, *badge)
        img.paste(bimg.convert("RGB"), (C.BOARD_X, C.BOARD_Y), board_mask(C.BOARD_PX))
        img.paste(panel, (C.PANEL_X, 0), panel)
        self._eval(ImageDraw.Draw(img), eval_frac, eval_label)
        return img

    def _eval(self, d, frac, label):
        top, bottom = inner_board_box()
        x0, x1 = C.EVAL_X, C.EVAL_X + C.EVAL_W
        h = bottom - top
        split = top + h * (1 - frac)
        d.rectangle([x0, top, x1, bottom], fill=(40, 40, 44))
        d.rectangle([x0, split, x1, bottom], fill=(233, 233, 234))
        f = body(15, True)
        if frac >= 0.5:
            draw_text(d, ((x0 + x1) / 2, bottom - 8), label, f, (20, 20, 22), "md")
        else:
            draw_text(d, ((x0 + x1) / 2, top + 8), label, f, (233, 233, 234), "ma")

    @staticmethod
    def _tint(bimg, square, colour, alpha):
        x, y, cell = board_mod.square_center(square, bimg.width)   # any board size
        layer = Image.new("RGBA", bimg.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rectangle(
            [x - cell / 2, y - cell / 2, x + cell / 2, y + cell / 2], fill=colour + (alpha,))
        bimg.alpha_composite(layer)

    @staticmethod
    def _badge(bimg, square, glyph, scale):
        if scale <= 0.01:
            return
        x, y, cell = board_mod.square_center(square, bimg.width)
        r = cell * 0.24 * scale
        cx, cy = x + cell / 2 - cell * 0.14, y - cell / 2 + cell * 0.14
        d = ImageDraw.Draw(bimg)
        d.ellipse([cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3], fill=(255, 255, 255))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=C.GLYPH_COLORS[glyph])
        size = max(8, int(r * (1.15 if len(glyph) == 1 else 0.95)))
        d.text((cx, cy + 1), glyph, font=sora(size), fill=(255, 255, 255), anchor="mm")

    # ── bookends ──────────────────────────────────────────────────────────
    def _lockup(self, img, d, cy, mark_px=48, size=36, colour=None):
        """Brand mark (if the channel has one) + name, centred on the canvas."""
        name_w = text_w(d, self.brand["name"], sora(size))
        mark = brand_mark(mark_px, str(self.brand["mark"])) if self.brand.get("mark") else None
        total = name_w + (mark.width + 14 if mark else 0)
        x0 = C.W // 2 - total // 2
        if mark:
            img.alpha_composite(mark, (x0, cy - mark.height // 2))
            x0 += mark.width + 14
        draw_text(d, (x0, cy), self.brand["name"], sora(size), colour or C.TEXT_MID, "lm")

    def intro(self, first_frame: Image.Image) -> Image.Image:
        from longform.games import surname
        img = Image.blend(first_frame, Image.new("RGB", (C.W, C.H), (0, 0, 0)), 0.94).convert("RGBA")
        d = ImageDraw.Draw(img)
        cx = C.W // 2
        parts = [self.g["event"], self.g["site"]]
        if self.g["year"] and self.g["year"] not in self.g["event"]:
            parts.append(self.g["year"])        # "World Championship 2024" already says it
        where = " · ".join(x for x in parts if x).upper()
        f_where = body(28, True)
        w = spaced(ImageDraw.Draw(Image.new("L", (1, 1))), (0, 0), where, f_where, 0, 4)
        spaced(d, (cx - w / 2, 120), where, f_where, C.TEXT_MID, 4)
        title = self.g["title"] or f"{surname(self.g['white'])} vs {surname(self.g['black'])}"
        tf = sora(104)
        while text_w(d, title, tf) > C.W - 200:
            tf = sora(tf.size - 4)
        draw_text(d, (cx, 240), title, tf, C.TEXT_HI, "mm")
        d.rounded_rectangle([cx - 70, 318, cx + 70, 326], radius=4, fill=C.PRIMARY)

        # The two players, face to face.
        av = 300
        for side, (name, slug, elo, ring) in enumerate((
                (self.g["white"], self.g.get("white_slug"), self.g["white_elo"], (233, 233, 234)),
                (self.g["black"], self.g.get("black_slug"), self.g["black_elo"], (70, 70, 76)))):
            px = cx + (-420 if side == 0 else 420)
            img.alpha_composite(glow(700, C.PRIMARY, 70), (px - 350, 600 - 350))
            img.alpha_composite(avatar(slug, name, av, ring), (px - av // 2, 600 - av // 2))
            nf = sora(46)
            while text_w(d, name, nf) > 600 and nf.size > 28:
                nf = sora(nf.size - 2)
            draw_text(d, (px, 800), name, nf, C.TEXT_HI, "mm")
            sub = ("WHITE" if side == 0 else "BLACK") + (f"  ·  {elo}" if elo else "")
            sw = spaced(ImageDraw.Draw(Image.new("L", (1, 1))), (0, 0), sub, body(24, True), 0, 3)
            spaced(d, (px - sw / 2, 840), sub, body(24, True), C.TEXT_MID, 3)
        draw_text(d, (cx, 600), "VS", sora(96), C.PRIMARY_BRIGHT, "mm")
        self._lockup(img, d, 990)
        return img.convert("RGB")

    def endcard(self) -> Image.Image:
        img = Image.new("RGBA", (C.W, C.H), C.BG + (255,))
        img.alpha_composite(glow(1600, C.PRIMARY, 60), (C.W // 2 - 800, C.H // 2 - 800))
        d = ImageDraw.Draw(img)
        if self.brand.get("mark"):
            mark = brand_mark(190, str(self.brand["mark"]))
            img.alpha_composite(mark, (C.W // 2 - mark.width // 2, 250))
        draw_text(d, (C.W // 2, 540), self.brand["name"], sora(96), C.TEXT_HI, "mm")
        draw_text(d, (C.W // 2, 630), self.brand["tagline"], body(40), C.TEXT_MID, "mm")
        return img.convert("RGB")


def moment_for(ply_index: int, game: dict, j: dict) -> dict | None:
    """The moment-card content for an annotated ply, or None."""
    glyph = j["glyph"]
    if glyph not in ("!!", "!", "?", "??", "#"):
        return None
    move_no = ply_index // 2 + 1
    dots = "." if ply_index % 2 == 0 else "..."
    san = game["sans"][ply_index]
    headline = f"{move_no}{dots} {san}{'' if glyph == '#' else glyph}"
    before, after = engine.fmt_eval(j["eval_before"]), engine.fmt_eval(j["eval_after"])
    if glyph == "#":
        sub = "Checkmate on the board"
    elif glyph in ("!!", "!"):
        sub = j["text"]
    else:
        sub = f"Engine {before}  →  {after}"
    return {
        "glyph": glyph,
        "ply": ply_index,
        "big": glyph if glyph != "#" else "#",
        "title": C.GLYPH_TITLES[glyph],
        "headline": headline,
        "sub": sub,
        "color": C.GLYPH_COLORS[glyph],
    }


def result_moment(game: dict) -> dict:
    res = game["result"]
    final = game["final_board"]
    if res == "1-0":
        winner, loser = game["white"], game["black"]
    elif res == "0-1":
        winner, loser = game["black"], game["white"]
    else:
        winner = loser = None
    if final.is_checkmate():
        sub = f"{winner} wins by checkmate"
    elif winner:
        sub = f"{loser.split()[-1]} resigned"
    elif final.is_stalemate():
        sub = "Draw by stalemate"
    else:
        sub = "The game is drawn"
    return {
        "glyph": "result",
        "big": "1-0" if res == "1-0" else ("0-1" if res == "0-1" else "½"),
        "title": "RESULT",
        "headline": f"{winner} wins" if winner else "Draw",
        "sub": sub,
        "color": C.GOLD,
    }


def eval_bar(score: dict, terminal: str | None = None, result: str = "*"):
    """(fraction of the bar that is White's, label)."""
    if terminal == "mate":
        return (1.0, "1-0") if engine.as_cp(score) > 0 else (0.0, "0-1")
    cp = engine.as_cp(score)
    # Gentler than the win-probability curve, so a +1 edge visibly moves the bar.
    frac = 0.5 + 0.5 * math.tanh(cp / 350)
    frac = 0.03 + 0.94 * frac
    label = engine.fmt_eval(score).lstrip("+")
    if score.get("mate") is not None:
        label = f"M{abs(score['mate'])}"
    return frac, label


def ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))
