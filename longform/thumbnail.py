"""1280x720 YouTube thumbnail: the real key position, a big claim, the players.

The board is always rendered from the game — an AI-drawn board is the one
thing a chess audience spots instantly (wrong squares, six-legged knights).
AI only paints the BACKGROUND, and only when the OpenAI project has image
access; otherwise a generated glow stands in, so a thumbnail is never missing.
"""

import base64
import io
import os

import chess
import chess.svg
import requests
from PIL import Image, ImageDraw, ImageFilter

import config
from src import board as board_mod
from longform import engine
from longform import frame as F
from longform import lfconfig as C

TW, TH = 1280, 720
BG_PROMPT = (
    "Dramatic dark cinematic background for a chess video thumbnail: a stone "
    "chess arena at night, deep black with violet rim light and a cyan spark "
    "on the left, shallow depth of field, smoky atmosphere. No text, no letters, "
    "no people, no chessboard, no chess pieces in the foreground. 16:9."
)


def _openai_key():
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    env = config.ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def ai_background(cache_path, log=print):
    """An AI-painted backdrop, cached per game. None when unavailable or off."""
    if not C.THUMB_IMAGE_MODELS:
        return None
    if cache_path.is_file():
        return Image.open(cache_path).convert("RGB")
    key = _openai_key()
    if not key:
        return None
    for model in C.THUMB_IMAGE_MODELS:
        try:
            r = requests.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "prompt": BG_PROMPT,
                      "size": "1536x1024", "quality": "medium", "n": 1},
                timeout=240,
            )
        except requests.RequestException as e:
            log(f"  thumbnail: {model} unreachable ({e.__class__.__name__})")
            continue
        if r.status_code == 200:
            img = Image.open(io.BytesIO(base64.b64decode(r.json()["data"][0]["b64_json"]))).convert("RGB")
            img.save(cache_path)
            log(f"  thumbnail: AI background from {model}")
            return img
        msg = r.json().get("error", {}).get("message", r.text[:120]) if r.content else r.status_code
        log(f"  thumbnail: {model} skipped — {str(msg)[:120]}")
    return None


def _cover(img, w, h):
    s = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _free_bg(board: chess.Board, accent: tuple) -> Image.Image:
    """Zero-cost backdrop made from the game itself.

    The same position, blown up past the frame and blurred into bokeh, then
    darkened and lit with the brand purple and the moment's colour. Every
    video gets a different background, no API is called, and it can never
    show something that is not in the game.
    """
    big = board_mod.render_board(board, 1400).convert("RGB")
    big = _cover(big, TW, TH).filter(ImageFilter.GaussianBlur(22))
    img = Image.blend(big, Image.new("RGB", (TW, TH), (0, 0, 0)), 0.72).convert("RGBA")
    img.alpha_composite(F.glow(1300, C.PRIMARY, 150), (TW - 820, -520))
    img.alpha_composite(F.glow(1000, accent, 90), (-260, TH - 640))
    # Vignette, so the edges fall off to black like a stage.
    vig = Image.new("L", (TW, TH), 0)
    ImageDraw.Draw(vig).ellipse([-TW * 0.15, -TH * 0.25, TW * 1.15, TH * 1.25], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(140))
    black = Image.new("RGBA", (TW, TH), (0, 0, 0, 255))
    black.putalpha(Image.eval(vig, lambda v: 255 - v))
    img.alpha_composite(black)
    return img.convert("RGB")


def key_ply(judg: list) -> int:
    """The moment the thumbnail sells: the biggest !! (a queen sac beats a
    knight sac), else the decisive ??, else mate."""
    # Ranked by the piece given up, and the earliest wins a tie: the first
    # rook sacrifice is the one a game is remembered for.
    value = {f"{n} sacrifice": engine.VALUE[t] for t, n in engine.PIECE_NAME.items()}
    sacs = [(value.get(j["text"], 0), -i) for i, j in enumerate(judg) if j["glyph"] == "!!"]
    if sacs:
        return -max(sacs)[1]
    for want in ("??", "#"):
        for i, j in enumerate(judg):
            if j["glyph"] == want:
                return i
    return len(judg) - 1


# What the chess world actually calls them, for the one place a long surname
# does not fit: the thumbnail's big words.
SHORT_NAMES = {"pragg": "Pragg", "mvl": "MVL", "nepo": "Nepo", "abdusattorov": "Nodirbek"}


def headline(game: dict, judg: list, i: int) -> tuple[str, str]:
    """(main words, accent glyph)."""
    g = judg[i]["glyph"]
    if g == "!!":
        # The piece GIVEN UP, from the judgement: for Be6!! that is the queen,
        # not the bishop that moved.
        return f"{judg[i]['text'].split()[0].upper()} SAC", "!!"
    if g == "??":
        return "ONE MOVE", "??"
    if g == "#":
        return "CHECKMATE", ""
    # Nothing loud in the game: two or three big words, never the full title,
    # which only fits a thumbnail at a size nobody can read.
    from longform.games import surname
    if game["result"] in ("1-0", "0-1"):
        white_won = game["result"] == "1-0"
        winner = game["white"] if white_won else game["black"]
        slug = game.get("white_slug") if white_won else game.get("black_slug")
        name = SHORT_NAMES.get(slug, surname(winner)).upper()
        return f"{name} WINS", ""
    return "WHAT A GAME", ""


def build(game: dict, judg: list, out_path, brand: str = "tchess", log=print):
    i = key_ply(judg)
    board = chess.Board(game["start_fen"])
    for mv in game["moves"][:i]:
        board.push(mv)
    mv = game["moves"][i]
    glyph = judg[i]["glyph"]

    bg = ai_background(out_path.parent / "thumb_bg.png", log=log)
    img = _cover(bg, TW, TH) if bg else _free_bg(board, C.GLYPH_COLORS.get(glyph or "!!", C.GLYPH_COLORS["!!"]))
    img = img.convert("RGBA")
    # Darken the text side so the words always win against the art.
    shade = Image.new("L", (TW, TH), 0)
    ImageDraw.Draw(shade).rectangle([560, 0, TW, TH], fill=150)
    shade = shade.filter(ImageFilter.GaussianBlur(120))
    img.alpha_composite(Image.merge("RGBA", [Image.new("L", (TW, TH), 0)] * 3 + [shade]))

    # The position BEFORE the move, with the move drawn as an arrow: the
    # thumbnail asks "what happens here?", the video answers it.
    bpx = 640
    colour = "#%02x%02x%02x" % C.GLYPH_COLORS.get(glyph or "!!", C.GLYPH_COLORS["!!"])
    bimg = board_mod.render_board(board, bpx, arrows=[chess.svg.Arrow(mv.from_square, mv.to_square,
                                                                        color=colour)])
    halo = Image.new("RGBA", (bpx + 120, bpx + 120), (0, 0, 0, 0))
    ImageDraw.Draw(halo).rounded_rectangle([60, 60, bpx + 60, bpx + 60], radius=24,
                                          fill=C.GLYPH_COLORS.get(glyph or "!!") + (150,))
    halo = halo.filter(ImageFilter.GaussianBlur(28))
    bx, by = 30, (TH - bpx) // 2
    img.alpha_composite(halo, (bx - 60, by - 60))
    img.paste(bimg.convert("RGB"), (bx, by), F.board_mask(bpx, 22))

    d = ImageDraw.Draw(img)
    words, accent = headline(game, judg, i)
    x = 710
    f = F.sora(150)
    while F.text_w(d, words + accent, f) > TW - x - 40 and f.size > 70:
        f = F.sora(f.size - 6)
    lines = [words]
    if f.size < 110 and " " in words:
        f = F.sora(130)
        lines = words.rsplit(" ", 1)
        while (max(F.text_w(d, ln, f) for ln in lines) + F.text_w(d, accent, f) > TW - x - 40
               and f.size > 40):
            f = F.sora(f.size - 6)
    y = 60 if len(lines) > 1 else 110
    for n, ln in enumerate(lines):
        _outlined(d, (x, y), ln, f, (255, 255, 255))
        if n == len(lines) - 1 and accent:
            _outlined(d, (x + F.text_w(d, ln, f) + 6, y), accent, f, C.GLYPH_COLORS[accent])
        y += int(f.size * 1.02)

    # The two faces, winner-coloured ring on the winner. Faces lift a chess
    # thumbnail more than anything else on it.
    from longform.games import surname
    av = 190
    fy = max(y + 20, 330)
    slots = [(game["white"], game.get("white_slug"), "1-0"), (game["black"], game.get("black_slug"), "0-1")]
    for k, (name, slug, win) in enumerate(slots):
        fx = x + k * 300
        ring = C.GOLD if game["result"] == win else (233, 233, 234)
        img.alpha_composite(F.avatar(slug, name, av, ring), (fx, fy))
        sn = surname(name).upper()
        ff = F.sora(38)
        while F.text_w(d, sn, ff) > 270 and ff.size > 22:
            ff = F.sora(ff.size - 2)
        _outlined(d, (fx + av // 2 - F.text_w(d, sn, ff) // 2, fy + av + 12), sn, ff, (233, 233, 234))
    _outlined(d, (x + av + 38, fy + av // 2 - 30), "VS", F.sora(52), C.PRIMARY_BRIGHT)
    if game["year"]:
        d.rounded_rectangle([TW - 168, 24, TW - 24, 80], radius=14, fill=C.PRIMARY)
        d.text((TW - 96, 52), game["year"], font=F.sora(36), fill=(255, 255, 255), anchor="mm")

    img.convert("RGB").save(out_path, quality=92)
    return out_path


def _outlined(d, xy, text, font, fill):
    d.text(xy, text, font=font, fill=fill, stroke_width=max(3, font.size // 22),
           stroke_fill=(0, 0, 0))
