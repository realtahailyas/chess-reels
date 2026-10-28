"""Piece slide animation.

Produces board-layer images only. Placing them on the 1080x1920 canvas with
text, eval bar and dots is compose.py's job, which keeps the animation math
independent of layout.
"""

import math

import chess

import config
from src.board import piece_sprite, render_board, square_center


def ease_in_out_cubic(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    """Overshoot-and-settle easing, used for the badge pop-in.

    Returns ~0 at t=0, peaks above 1.0, and settles to 1.0 at t=1. A larger
    `overshoot` gives a bigger peak.
    """
    t = max(0.0, min(1.0, t))
    c1 = overshoot
    c3 = c1 + 1.0
    return 1.0 + c3 * pow(t - 1.0, 3) + c1 * pow(t - 1.0, 2)


# Rook travel for castling, keyed by the king's destination square.
_CASTLE_ROOK = {
    chess.G1: (chess.H1, chess.F1),
    chess.C1: (chess.A1, chess.D1),
    chess.G8: (chess.H8, chess.F8),
    chess.C8: (chess.A8, chess.D8),
}


def captured_square(board: chess.Board, move: chess.Move) -> int | None:
    """Square the captured piece actually occupies.

    For en passant the captured pawn is not on the destination square; missing
    this leaves a ghost pawn on the board.
    """
    if not board.is_capture(move):
        return None
    if board.is_en_passant(move):
        return move.to_square + (-8 if board.turn == chess.WHITE else 8)
    return move.to_square


def build_slide_frames(board: chess.Board, move: chess.Move, board_px: int = None,
                       fps: int = None, duration: float = None):
    """Yield board images animating `move` from the given position.

    The staging board omits the moving piece and any captured piece, so the
    sprite pasted on top is the only copy visible — no ghost on the source
    square.
    """
    board_px = board_px or config.BOARD_PX
    fps = fps or config.FPS
    duration = config.SLIDE_DURATION if duration is None else duration

    piece = board.piece_at(move.from_square)
    if piece is None:                      # illegal input; nothing to animate
        yield render_board(board, board_px)
        return

    stage = board.copy()
    stage.remove_piece_at(move.from_square)
    victim = captured_square(board, move)
    if victim is not None:
        stage.remove_piece_at(victim)

    # Castling moves the rook too, so it must also be lifted off the staging
    # board and animated rather than appearing twice.
    rook_from = rook_to = None
    rook_piece = None
    if board.is_castling(move):
        squares = _CASTLE_ROOK.get(move.to_square)
        if squares:
            rook_from, rook_to = squares
            rook_piece = stage.remove_piece_at(rook_from)

    base = render_board(stage, board_px)

    x0, y0, cell = square_center(move.from_square, board_px)
    x1, y1, _ = square_center(move.to_square, board_px)
    sprite_px = int(round(cell))
    sprite = piece_sprite(piece, sprite_px)

    rook_sprite = None
    if rook_piece is not None:
        rx0, ry0, _ = square_center(rook_from, board_px)
        rx1, ry1, _ = square_center(rook_to, board_px)
        rook_sprite = piece_sprite(rook_piece, sprite_px)

    n = max(1, int(round(duration * fps)))
    for k in range(n):
        p = ease_in_out_cubic(k / n)
        cx = x0 + (x1 - x0) * p
        cy = y0 + (y1 - y0) * p
        arc = -math.sin(p * math.pi) * cell * config.ARC_LIFT

        frame = base.copy()
        if rook_sprite is not None:
            frame.paste(
                rook_sprite,
                (int(rx0 + (rx1 - rx0) * p - cell / 2),
                 int(ry0 + (ry1 - ry0) * p - cell / 2)),
                rook_sprite,
            )
        frame.paste(sprite,
                    (int(cx - cell / 2), int(cy - cell / 2 + arc)),
                    sprite)
        yield frame


def landed_board(board: chess.Board, move: chess.Move):
    """Return (board_after, lastmove, check_square) for the settled position."""
    after = board.copy()
    after.push(move)
    check_sq = after.king(after.turn) if after.is_check() else None
    return after, move, check_sq
