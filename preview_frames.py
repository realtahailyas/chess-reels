"""Render layout preview frames — no speech, no encode. Fast iteration loop.

    python preview_frames.py

Writes preview/<name>.png plus a __safe copy with the platform UI zones tinted,
so "is the banner going to be cropped again" is answerable without a render.
"""
import sys
from pathlib import Path

import chess
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from src import board as board_mod, compose

OUT = Path(__file__).resolve().parent / "preview"
OUT.mkdir(exist_ok=True)

FEN = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2NBPN2/PPQ2PPP/R1B2RK1 w - - 0 9"


def _safe_overlay(img):
    """Red = the band each platform paints its own UI over."""
    o = img.convert("RGB").copy()
    d = ImageDraw.Draw(o, "RGBA")
    d.rectangle([0, 0, config.CANVAS_W, config.SAFE_TOP], fill=(255, 0, 0, 70))
    d.rectangle([0, config.CANVAS_H - config.SAFE_BOTTOM,
                 config.CANVAS_W, config.CANVAS_H], fill=(255, 0, 0, 70))
    for y in (config.SAFE_TOP, config.CANVAS_H - config.SAFE_BOTTOM):
        d.line([0, y, config.CANVAS_W, y], fill=(255, 60, 60), width=3)
    return o


def shot(name, img):
    img.save(OUT / f"{name}.png")
    _safe_overlay(img).save(OUT / f"{name}__safe.png")
    print(f"  {name}")


def frame(vname, **kw):
    V = config.variant(vname)
    b = chess.Board(FEN)
    bimg = board_mod.render_board(b, V["board_px"],
                                  lastmove=chess.Move.from_uci("d3h7"))
    band = None
    if V["reaction_band"]:
        band = Image.new("RGB", (config.REACTION_BAND_W,
                                 config.REACTION_BAND_H), (26, 26, 30))
        d = ImageDraw.Draw(band)
        d.text((config.REACTION_BAND_W // 2 - 90, 40),
               "[ reaction clip ]", fill=(140, 140, 150))
    base = dict(
        board_img=bimg, dots_total=3 if V["show_dots"] else 0, dots_active=1,
        subtitle="",
        board_y_offset=V["board_y_offset"], headline_y=V["headline_y"],
        band_content=band, show_watermark=V["show_watermark"],
        show_promo_banner=V.get("show_promo_banner", False),
        show_headline=V.get("show_headline", True),
    )
    base.update(kw)
    return compose.compose_frame(compose.FrameState(**base))


def main():
    # Countdown family: the opening beat and a move beat.
    shot("guess_countdown", frame("promo_guess", headline="WHITE TO PLAY",
                                  subtitle=("Can you find it?"
                                            if config.variant("promo_guess")["show_subtitle"]
                                            else ""),
                                  countdown="3", countdown_progress=0.7,
                                  dots_active=0))
    gv = config.variant("promo_guess")
    shot("guess_move", frame("promo_guess",
                             headline="Bxh7+" if gv.get("show_move_label", True) else "",
                             subtitle="Did you solve it?" if gv["show_subtitle"] else ""))
    # Reaction family: the watch hold and the sacrifice beat.
    shot("sac_watch", frame("promo_sac", headline="WATCH CLOSELY", dots_active=0))
    shot("sac_move", frame("promo_sac", headline="Bxh7+",
                           brilliant_square=chess.H7, brilliant_scale=1.0))
    shot("endcard", compose.endcard_frame(1.0))
    print(f"\nwrote to {OUT}")


if __name__ == "__main__":
    raise SystemExit(main())
