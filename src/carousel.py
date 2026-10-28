"""Still-image carousels: cover, N puzzle slides, CTA. No video, no audio.

The cheapest promo the pipeline can make. There is no encode, no TTS and no
music, so a set builds in seconds rather than a minute a video — and a carousel
is posted in one action, which makes it the format to lean on for volume.

The format is deliberately a QUIZ with the answers in the caption: a still that
asks something gets comments, and comments are the only engagement signal a
still post can earn. Nothing here reveals the solution on the image.

Canvas is 1080x1350 (4:5), NOT the reel's 1080x1920 — so this module draws its
own watermark rather than calling compose._draw_watermark, which positions from
config.CANVAS_H and would place it 570px off the bottom of the slide.
"""

import json
import time
import traceback
from datetime import date

import chess
from PIL import Image, ImageDraw

import config
from src import board as board_mod, captions, compose
from src import puzzles as puzzles_mod, queue as ledger
from src.build import next_index
from src.fonts import get_font

__all__ = ["build_carousel"]


def _blank() -> tuple:
    img = Image.new("RGB", (config.CAROUSEL_W, config.CAROUSEL_H), config.BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, config.CAROUSEL_W, config.ACCENT_BAR_H], fill=config.ACCENT)
    compose._draw_promo_banner(img)
    return img, draw


def _centred(draw, y, text, font, fill):
    """compose.centred_text centres on CANVAS_W, which happens to match."""
    compose.centred_text(draw, y, text, font, fill, shadow=False)


def _watermark(img, draw):
    _centred(draw, config.CAROUSEL_H - 70, config.WATERMARK_TEXT,
             get_font(config.WATERMARK_SIZE, bold=True), config.MUTED)


def _cover() -> Image.Image:
    img, draw = _blank()
    mark = compose._wordmark_sprite(config.CAROUSEL_COVER_MARK_H)
    img.paste(mark, ((config.CAROUSEL_W - mark.width) // 2, 300), mark)

    font = get_font(config.CAROUSEL_COVER_SIZE, bold=True)
    y = 660
    for line in config.CAROUSEL_COVER_TITLE:
        _centred(draw, y, line, font, config.APP_TEXT_HI)
        y += int(config.CAROUSEL_COVER_SIZE * 1.22)

    _centred(draw, y + 40, config.CAROUSEL_COVER_SUB,
             get_font(config.CAROUSEL_COVER_SUB_SIZE, bold=True), config.APP_VIOLET)
    _watermark(img, draw)
    return img


def _puzzle_slide(puzzle: dict, index: int, total: int) -> Image.Image:
    img, draw = _blank()
    board = chess.Board(puzzle["fen"])

    _centred(draw, config.CAROUSEL_KICKER_Y, puzzle["theme_label"].upper(),
             get_font(config.CAROUSEL_KICKER_SIZE), config.MUTED)
    _centred(draw, config.CAROUSEL_HEADLINE_Y,
             config.CAROUSEL_PROMPT[board.turn == chess.WHITE],
             get_font(config.CAROUSEL_HEADLINE_SIZE, bold=True), config.APP_TEXT_HI)

    # No lastmove tint and no check glow: both point at the answer.
    board_img = board_mod.render_board(board, config.CAROUSEL_BOARD_PX)
    img.paste(board_img.convert("RGB"),
              ((config.CAROUSEL_W - config.CAROUSEL_BOARD_PX) // 2,
               config.CAROUSEL_BOARD_Y))

    _centred(draw, config.CAROUSEL_FOOTER_Y, f"{index} of {total}",
             get_font(config.CAROUSEL_FOOTER_SIZE, bold=True), config.MUTED)
    _watermark(img, draw)
    return img


def _cta() -> Image.Image:
    """The end card, cropped to the carousel's shorter canvas.

    Reuses compose._endcard_base rather than laying the same thing out twice —
    the two must not drift, and the reel's card is the one with the store row
    that has already been checked.
    """
    card = compose._endcard_base()
    # The card's content runs from the wordmark to the tchess.app/android line. Crop so
    # ALL of it lands above the carousel's watermark row — at a shallower crop
    # the handle prints straight over tchess.app/android.
    top = config.ENDCARD_WORDMARK_Y - config.CAROUSEL_CTA_HEADROOM
    slide = card.crop((0, top, config.CAROUSEL_W, top + config.CAROUSEL_H))
    draw = ImageDraw.Draw(slide)
    draw.rectangle([0, 0, config.CAROUSEL_W, config.ACCENT_BAR_H], fill=config.ACCENT)

    bottom = config.ENDCARD_WEB_Y + config.ENDCARD_WEB_SIZE - top
    if bottom > config.CAROUSEL_H - 100:
        raise RuntimeError(
            f"CTA content ends at {bottom} of {config.CAROUSEL_H} — it would sit "
            f"under the watermark. Lower CAROUSEL_CTA_HEADROOM.")
    _watermark(slide, draw)
    return slide


def build_carousel(*, count=None, output_dir=None, seq=None, use_api=True,
                   log=print, **filter_kw) -> dict:
    """Build one carousel: cover + N puzzle slides + CTA, plus caption.txt."""
    started = time.time()
    count = count or config.CAROUSEL_SLIDES
    out_root = (output_dir or config.OUTPUT_DIR)
    stamp = date.today().isoformat()
    seq = seq if seq is not None else next_index(out_root)
    root = out_root / f"{seq:0{config.OUTPUT_INDEX_WIDTH}d}_{stamp}"

    try:
        root.mkdir(parents=True, exist_ok=True)

        # Degrade rather than fail. A themed, banded slice can come up short —
        # the corpus is sacrifice-filtered, so some motifs are thin at some
        # ratings — and a scheduled post that produces nothing is worse than
        # one that quietly widens its net. Each step is logged, so a set that
        # drifted off its brief is visible rather than silent.
        puzzles = puzzles_mod.select(count, exclude=ledger.posted_ids(),
                                     log=log, **filter_kw)
        if len(puzzles) < count and ("rating_min" in filter_kw or "rating_max" in filter_kw):
            log(f"        widen   only {len(puzzles)} at this rating — dropping the band")
            wider = {k: v for k, v in filter_kw.items()
                     if k not in ("rating_min", "rating_max")}
            puzzles = puzzles_mod.select(count, exclude=ledger.posted_ids(),
                                         log=log, **wider)
        if len(puzzles) < count and filter_kw.get("theme"):
            log(f"        widen   only {len(puzzles)} for theme "
                f"{filter_kw['theme']!r} — dropping the theme")
            puzzles = puzzles_mod.select(count, exclude=ledger.posted_ids(), log=log)
        if len(puzzles) < count:
            raise RuntimeError(
                f"only {len(puzzles)} puzzles selected, wanted {count}, even "
                f"with no theme and no rating band — the ledger may be exhausted")

        slides = [("01_cover", _cover())]
        for i, p in enumerate(puzzles, 1):
            slides.append((f"{i + 1:02d}_{p['id']}", _puzzle_slide(p, i, count)))
        slides.append((f"{count + 2:02d}_cta", _cta()))

        for name, img in slides:
            img.save(root / f"{name}.png", optimize=True)
        log(f"        slides  {len(slides)} ... {config.CAROUSEL_W}x{config.CAROUSEL_H}")

        answers = [
            {"id": p["id"], "rating": p["rating"], "theme": p["theme_label"],
             "san": captions.san_solution(p["fen"], p["solution"])}
            for p in puzzles
        ]
        (root / "caption.txt").write_text(_caption(answers), encoding="utf-8")

        meta = {
            "kind": "carousel",
            "date": stamp,
            "slides": [n for n, _ in slides],
            "size": [config.CAROUSEL_W, config.CAROUSEL_H],
            "answers": answers,
            "build_seconds": round(time.time() - started, 1),
        }
        (root / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Carousels DO spend puzzles — the same position posted as a still and
        # then as a reel is a repeat to anyone who follows both.
        for p in puzzles:
            ledger.record_success(p, root / "caption.txt", root / "caption.txt", 0.0)

        log(f"        OK      {root}")
        return {"status": "ok", "puzzle_id": f"carousel-{stamp}",
                "video": str(root), "duration": 0.0,
                "filesize": sum(f.stat().st_size for f in root.glob("*.png")),
                "seconds": round(time.time() - started, 1), "needs_caption": False}

    except Exception as exc:
        log(f"        FAILED  {type(exc).__name__}: {exc}")
        return {"status": "failed", "puzzle_id": f"carousel-{stamp}",
                "error": str(exc), "traceback": traceback.format_exc(),
                "seconds": round(time.time() - started, 1)}


def _caption(answers) -> str:
    """Answers go HERE, never on the slides — that is what earns the comments."""
    lines = [f"{i}. {a['san']}   ({a['theme']}, rated {a['rating']})"
             for i, a in enumerate(answers, 1)]
    return (
        f"{config.CAROUSEL_COVER_TITLE[0]} {config.CAROUSEL_COVER_TITLE[1]}\n\n"
        "Answers below — no peeking until you have all five.\n\n"
        + "\n".join(lines)
        + f"\n\nMore of these in TChess — {config.ENDCARD_TAGLINE}\n"
        f"Google Play: search “{config.BRAND_NAME}”\n"
        f"Browser: {config.ENDCARD_WEB}\n"
        f"{config.ENDCARD_PROMISE}\n\n"
        "#chess #chesstactics #chesspuzzles #chessapp #tchess\n"
    )
