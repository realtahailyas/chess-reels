"""9:16 (1080x1920) layout of the long-form game, for Facebook Reels.

Same game, pacing, engine marks, audio and photos as the YouTube video. Only
the frame changes, to a clean vertical screen:

    brand lockup
    title (one or two lines) + event
    black's card   (photo, name, rating, captured pieces)
    the board      (960 px, badges and the !! tint as on YouTube)
    white's card
    the last move, big ("24. Rxd4!!"), and what it was ("BRILLIANT MOVE")

No eval bar and no move list: the owner asked for gameplay only. The bottom
of the frame stays clear, because Facebook lays its caption and buttons over
it, and the top clear of its header.
"""

import chess
from PIL import Image, ImageDraw

from longform import lfconfig as C
from longform import frame as F
from longform.frame import avatar, body, brand_mark, draw_text, glow, rounded, sora, spaced, text_w
from src import board as board_mod

VW, VH = 1080, 1920
BOARD = 960
BX = (VW - BOARD) // 2
BRAND_CY = 180
TITLE_TOP = 232
CARD_H = 110
CARD1_Y = 400
BY = CARD1_Y + CARD_H + 20            # 530
CARD2_Y = BY + BOARD + 20             # 1510
MOVE_CY = CARD2_Y + CARD_H + 70       # 1690
MOMENT_Y = MOVE_CY + 52


def _wrap(d, text, max_w, start, floor, lines_max=2):
    """Largest font that fits `text` on one line, else two balanced lines."""
    f = sora(start)
    while text_w(d, text, f) > max_w and f.size > floor:
        f = sora(f.size - 2)
    if text_w(d, text, f) <= max_w or " " not in text or lines_max < 2:
        return f, [text]
    words = text.split()
    best = min(range(1, len(words)),
               key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
    lines = [" ".join(words[:best]), " ".join(words[best:])]
    f = sora(start)
    while max(text_w(d, ln, f) for ln in lines) > max_w and f.size > floor:
        f = sora(f.size - 2)
    return f, lines


class VFrames(F.Frames):
    W, H, board_px = VW, VH, BOARD
    suffix = "_reel"

    def _title(self):
        from longform.games import surname
        return self.g["title"] or f"{surname(self.g['white'])} vs {surname(self.g['black'])}"

    def _lockup(self, img, d, cy, mark_px=44, size=36, colour=None, cx=VW // 2):
        name_w = text_w(d, self.brand["name"], sora(size))
        mark = brand_mark(mark_px, str(self.brand["mark"])) if self.brand.get("mark") else None
        total = name_w + (mark.width + 12 if mark else 0)
        x0 = cx - total // 2
        if mark:
            img.alpha_composite(mark, (x0, cy - mark.height // 2))
            x0 += mark.width + 12
        draw_text(d, (x0, cy), self.brand["name"], sora(size), colour or C.TEXT_HI, "lm")

    # ── static ────────────────────────────────────────────────────────────
    def _base(self) -> Image.Image:
        img = Image.new("RGBA", (VW, VH), C.BG + (255,))
        img.alpha_composite(glow(1500, C.PRIMARY, 42), (VW // 2 - 750, BY + BOARD // 2 - 750))
        d = ImageDraw.Draw(img)
        self._lockup(img, d, BRAND_CY)

        f, lines = _wrap(d, self._title(), VW - 100, 60, 34)
        y = TITLE_TOP
        for ln in lines:
            draw_text(d, (VW // 2, y), ln, f, C.TEXT_HI, "ma")
            y += int(f.size * 1.15)
        parts = [self.g["event"], self.g["site"]]
        if self.g["year"] and self.g["year"] not in self.g["event"]:
            parts.append(self.g["year"])
        where = " · ".join(x for x in parts if x).upper()
        fw = body(22, True)
        while text_w(d, where, fw) + 3 * len(where) > VW - 100 and fw.size > 14:
            fw = body(fw.size - 1, True)
        w = spaced(ImageDraw.Draw(Image.new("L", (1, 1))), (0, 0), where, fw, 0, 3)
        spaced(d, (VW // 2 - w / 2, y + 6), where, fw, C.TEXT_MID, 3)

        for cy in (CARD1_Y, CARD2_Y):
            rounded(d, [BX, cy, BX + BOARD, cy + CARD_H], 18, C.SURFACE, C.BORDER)
        return img.convert("RGB")

    # ── per ply ───────────────────────────────────────────────────────────
    def panel(self, ply: int, board: chess.Board, moment) -> Image.Image:
        key = (ply, id(moment) if moment else None)
        hit = self._panel_cache.get(key)
        if hit is not None:
            return hit
        img = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        self._vcard(img, d, CARD1_Y, chess.BLACK, board, board.turn == chess.BLACK)
        self._vcard(img, d, CARD2_Y, chess.WHITE, board, board.turn == chess.WHITE)

        if moment and moment.get("glyph") == "result":
            f, lines = _wrap(d, moment["headline"], VW - 120, 64, 36, lines_max=1)
            draw_text(d, (VW // 2, MOVE_CY), lines[0], f, C.GOLD, "mm")
            sub = f"{moment['big']}  ·  {moment['sub']}".upper()
            sw = spaced(ImageDraw.Draw(Image.new("L", (1, 1))), (0, 0), sub, body(24, True), 0, 3)
            spaced(d, (VW // 2 - sw / 2, MOMENT_Y), sub, body(24, True), C.TEXT_MID, 3)
        elif ply > 0:
            i = ply - 1
            glyph = self.j[i]["glyph"]
            glyph = None if glyph == "#" else glyph
            n = i // 2 + 1
            label = f"{n}{'.' if i % 2 == 0 else '...'} {self.g['sans'][i]}"
            f = sora(64)
            total = text_w(d, label, f) + (text_w(d, glyph, f) if glyph else 0)
            x = VW // 2 - total // 2
            draw_text(d, (x, MOVE_CY), label, f, C.TEXT_HI, "lm")
            if glyph:
                draw_text(d, (x + text_w(d, label, f), MOVE_CY), glyph, f, C.GLYPH_COLORS[glyph], "lm")
            # Only under the move it belongs to: the wide layout keeps a moment
            # card up for two more plies, but here the line sits right under
            # the LAST move, and "BLUNDER" under the reply would blame the wrong one.
            if moment and moment.get("ply") == i:
                title = moment["title"]
                if moment.get("sub") and moment["glyph"] in ("!!", "!"):
                    title = f"{title}  ·  {moment['sub']}"
                title = title.upper()
                ft = body(24, True)
                tw = spaced(ImageDraw.Draw(Image.new("L", (1, 1))), (0, 0), title, ft, 0, 3)
                spaced(d, (VW // 2 - tw / 2, MOMENT_Y), title, ft, moment["color"], 3)

        if len(self._panel_cache) > 12:
            self._panel_cache.pop(next(iter(self._panel_cache)))
        self._panel_cache[key] = img
        return img

    def _vcard(self, img, d, y, colour, board, active):
        white = colour == chess.WHITE
        name = self.g["white"] if white else self.g["black"]
        slug = self.g.get("white_slug") if white else self.g.get("black_slug")
        elo = self.g["white_elo"] if white else self.g["black_elo"]
        if active:
            d.rounded_rectangle([BX, y + 20, BX + 6, y + CARD_H - 20], radius=3, fill=C.PRIMARY)
        av = 84
        ring = (233, 233, 234) if white else (70, 70, 76)
        ax, ay = BX + 22, y + (CARD_H - av) // 2
        img.alpha_composite(avatar(slug, name, av, ring), (ax, ay))
        d.ellipse([ax + av - 22, ay + av - 22, ax + av, ay + av],
                  fill=(233, 233, 234) if white else (0, 0, 0), outline=C.SURFACE, width=3)
        sx = ax + av + 18
        nf = sora(36)
        while text_w(d, name, nf) > BOARD - (sx - BX) - 110 and nf.size > 22:
            nf = sora(nf.size - 2)
        draw_text(d, (sx, y + 38), name, nf, C.TEXT_HI, "lm")
        if elo:
            draw_text(d, (BX + BOARD - 24, y + 38), elo, body(28, True), C.TEXT_MID, "rm")

        opp = not colour
        sp = 28
        caps = []
        for t in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN):
            caps += [t] * max(0, F.START_COUNTS[(opp, t)] - len(board.pieces(t, opp)))
        cy = y + 64
        cx = sx
        if caps:
            step = sp * 0.78
            tray_w = int(step * (len(caps) - 1) + sp + 14)
            d.rounded_rectangle([cx, cy - 2, cx + tray_w, cy + sp + 2], radius=8, fill=(223, 227, 206))
            px = cx + 7
            for t in caps:
                img.alpha_composite(board_mod.piece_sprite(chess.Piece(t, opp), sp), (int(px), cy))
                px += step
            cx += tray_w
        lead = self._material(board, colour) - self._material(board, opp)
        if lead > 0:
            draw_text(d, (cx + 12, cy + sp / 2), f"+{lead}", body(24, True), C.TEXT_MID, "lm")

    def frame(self, board_img, panel, eval_frac=None, eval_label=None, badge=None, tint=None):
        img = self.base.copy()
        bimg = board_img
        if badge or tint:
            bimg = board_img.copy()
            if tint:
                self._tint(bimg, *tint)
            if badge:
                self._badge(bimg, *badge)
        img.paste(bimg.convert("RGB"), (BX, BY), F.board_mask(BOARD))
        img.paste(panel, (0, 0), panel)
        return img

    # ── bookends ──────────────────────────────────────────────────────────
    def intro(self, first_frame: Image.Image) -> Image.Image:
        # A clean black card, not the dimmed first frame: at 9:16 the dimmed
        # title and cards sat right behind the intro's own title and read as a
        # double image.
        img = Image.new("RGBA", (VW, VH), C.BG + (255,))
        img.alpha_composite(glow(1600, C.PRIMARY, 45), (VW // 2 - 800, 250))
        d = ImageDraw.Draw(img)
        cx = VW // 2
        parts = [self.g["event"], self.g["site"]]
        if self.g["year"] and self.g["year"] not in self.g["event"]:
            parts.append(self.g["year"])
        where = " · ".join(x for x in parts if x).upper()
        fw = body(26, True)
        while text_w(d, where, fw) + 4 * len(where) > VW - 100 and fw.size > 14:
            fw = body(fw.size - 1, True)
        w = spaced(ImageDraw.Draw(Image.new("L", (1, 1))), (0, 0), where, fw, 0, 4)
        spaced(d, (cx - w / 2, 470), where, fw, C.TEXT_MID, 4)
        f, lines = _wrap(d, self._title(), VW - 100, 88, 44)
        y = 530
        for ln in lines:
            draw_text(d, (cx, y), ln, f, C.TEXT_HI, "ma")
            y += int(f.size * 1.12)
        d.rounded_rectangle([cx - 60, y + 18, cx + 60, y + 26], radius=4, fill=C.PRIMARY)

        av, pcy = 330, y + 280
        for side, (name, slug, elo, ring) in enumerate((
                (self.g["white"], self.g.get("white_slug"), self.g["white_elo"], (233, 233, 234)),
                (self.g["black"], self.g.get("black_slug"), self.g["black_elo"], (70, 70, 76)))):
            px = cx + (-255 if side == 0 else 255)
            img.alpha_composite(glow(640, C.PRIMARY, 70), (px - 320, pcy - 320))
            img.alpha_composite(avatar(slug, name, av, ring), (px - av // 2, pcy - av // 2))
            nf = sora(40)
            while text_w(d, name, nf) > 470 and nf.size > 24:
                nf = sora(nf.size - 2)
            draw_text(d, (px, pcy + av // 2 + 50), name, nf, C.TEXT_HI, "mm")
            sub = ("WHITE" if side == 0 else "BLACK") + (f"  ·  {elo}" if elo else "")
            sw = spaced(ImageDraw.Draw(Image.new("L", (1, 1))), (0, 0), sub, body(22, True), 0, 3)
            spaced(d, (px - sw / 2, pcy + av // 2 + 86), sub, body(22, True), C.TEXT_MID, 3)
        draw_text(d, (cx, pcy), "VS", sora(80), C.PRIMARY_BRIGHT, "mm")
        self._lockup(img, d, 1560, mark_px=52, size=42)
        return img.convert("RGB")

    def endcard(self) -> Image.Image:
        img = Image.new("RGBA", (VW, VH), C.BG + (255,))
        img.alpha_composite(glow(1600, C.PRIMARY, 60), (VW // 2 - 800, VH // 2 - 900))
        d = ImageDraw.Draw(img)
        if self.brand.get("mark"):
            mark = brand_mark(220, str(self.brand["mark"]))
            img.alpha_composite(mark, (VW // 2 - mark.width // 2, 600))
        draw_text(d, (VW // 2, 960), self.brand["name"], sora(110), C.TEXT_HI, "mm")
        draw_text(d, (VW // 2, 1060), self.brand["tagline"], body(42), C.TEXT_MID, "mm")
        return img.convert("RGB")
