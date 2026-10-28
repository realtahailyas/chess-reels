"""Custom GM Game Video Generator — paste a PGN, get a video.

    python custom_gm.py --pgn-file game.pgn
    python custom_gm.py --pgn-string "[Event ...] 1. d4 d5 ..."

No Lichess CSV, no API calls, no filtering — just your own PGN straight to
the GM replay renderer. PGN can be from any source: a file, a clipboard
paste, or a raw string on the command line.
"""

import argparse
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chess
import config
from src import board as board_mod
from src import build as builder


def parse_pgn_header(value: str, default: str = "") -> str:
    return re.sub(r'\s+', ' ', str(value)).strip() or default


def _termination_phrase(value: str) -> str:
    key = re.sub(r'\s+', ' ', str(value)).strip().casefold()
    mapping = {
        "normal": "checkmate",
        "checkmate": "checkmate",
        "resign": "resignation",
        "resignation": "resignation",
        "time forfeit": "time forfeit",
        "abandoned": "abandonment",
        "rules infraction": "rules infraction",
        "stalemate": "stalemate",
        "threefold repetition": "threefold repetition",
        "repetition": "threefold repetition",
        "insufficient material": "insufficient material",
        "50 move rule": "50-move rule",
        "draw": "draw",
    }
    return mapping.get(key, key or "unknown result")


def parse_pgn(pgn_text: str, log=print) -> dict:
    """Parse a raw PGN string into the game_meta dict build_one expects.

    Headers come from the [Key "Value"] block; moves are parsed into
    both SAN and UCI so the render pipeline can replay the whole game.
    """
    text = pgn_text.strip()

    header_re = re.compile(r'^\[(\w+)\s+"(.*)"\]$')
    headers = {}
    move_text = ""

    lines = text.splitlines()
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        match = header_re.match(line_stripped)
        if match:
            headers[match.group(1)] = match.group(2)
        else:
            move_text = "\n".join(lines[lines.index(line):])
            break

    if not move_text:
        if "\n\n" in text:
            move_text = text.split("\n\n", 1)[1]
        else:
            move_text = text

    start_fen = headers.get("FEN", chess.STARTING_FEN)
    board = chess.Board(start_fen)
    tokens = re.split(r'\s+', move_text)
    uci_moves = []
    san_moves = []

    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token.endswith(".") or token in {"*", "1-0", "0-1", "1/2-1/2"}:
            continue
        if token.startswith("{") or token.startswith("("):
            break
        try:
            move = board.parse_san(token)
            san_moves.append(token)
            uci_moves.append(move.uci())
            board.push(move)
        except ValueError:
            continue

    if not uci_moves:
        raise ValueError("no legal moves found in PGN move text")

    white_title = str(headers.get("WhiteTitle", "")).strip()
    black_title = str(headers.get("BlackTitle", "")).strip()
    white = str(headers.get("White", "?")).strip() or "?"
    black = str(headers.get("Black", "?")).strip() or "?"
    white_label = f"{white_title} {white}".strip() if white_title else white
    black_label = f"{black_title} {black}".strip() if black_title else black
    white_elo = str(headers.get("WhiteElo", "")).strip()
    black_elo = str(headers.get("BlackElo", "")).strip()
    termination = str(headers.get("Termination", "")).strip()
    result = headers.get("Result", "*")

    if result == "1-0":
        winner = "white"
        winner_name = white
        winner_label = white_label
    elif result == "0-1":
        winner = "black"
        winner_name = black
        winner_label = black_label
    else:
        winner = None
        winner_name = ""
        winner_label = ""

    if termination and _termination_phrase(termination) not in {"", "normal"}:
        result_phrase = _termination_phrase(termination)
    elif board.is_checkmate():
        result_phrase = "checkmate"
    elif result in {"1-0", "0-1"}:
        result_phrase = "resignation"
    else:
        result_phrase = "draw"

    outcome = (f"{winner_label} won by {result_phrase}"
               if winner_label and result in {"1-0", "0-1"}
               else f"Draw by {result_phrase}" if result == "1/2-1/2"
               else result_phrase)

    log(f"  {white_label} ({white_elo}) vs {black_label} ({black_elo})")
    log(f"  Result: {result} ({outcome})")
    log(f"  Moves:  {len(uci_moves)} plies")

    return {
        "start_fen": start_fen,
        "moves": uci_moves,
        "sans": san_moves,
        "white": white,
        "black": black,
        "white_title": white_title,
        "black_title": black_title,
        "white_label": white_label,
        "black_label": black_label,
        "white_elo": white_elo,
        "black_elo": black_elo,
        "winner": winner,
        "winner_name": winner_name,
        "winner_label": winner_label,
        "termination": termination,
        "termination_phrase": result_phrase,
        "outcome": outcome,
        "result": headers.get("Result", "*"),
        "event": headers.get("Event", ""),
        "site": headers.get("Site", ""),
        "eco": headers.get("ECO", ""),
        "opening": headers.get("Opening", ""),
        "headers": headers,
    }


def build_pseudo_puzzle(game_meta: dict) -> dict:
    """Build a minimal puzzle dict that build_one() can consume directly."""

    return {
        "id": game_meta.get("headers", {}).get("Site", "custom_gm").replace("/", "_").strip() or "custom_gm",
        "fen": game_meta["start_fen"],
        "solution": game_meta["moves"],
        "rating": max(
            int(game_meta["white_elo"] or "0"),
            int(game_meta["black_elo"] or "0")
        ),
        "themes": [],
        "popularity": 99,
        "game_url": game_meta.get("site", "https://lichess.org/"),
        "theme_label": game_meta.get("opening", "GM Classic"),
        "series_label": game_meta.get("black_title") or "GM",
        "sacrificed_piece": None,
        "brilliant_index": None,
        "lichess_fen": game_meta["start_fen"],
        "lichess_moves": " ".join(game_meta["moves"]),
        "game_meta": game_meta,
    }


def generate(pgn_text: str, *, output_dir=None, log=print) -> str:
    """Generate a GM replay video from a PGN string.

    Returns the path to the resulting ``video.mp4``.
    """
    import chess

    # Force UTF-8 output on Windows so box-drawing chars don't crash.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    started = time.time()
    log("== parsing PGN ==")
    game_meta = parse_pgn(pgn_text, log=log)
    puzzle = build_pseudo_puzzle(game_meta)
    puzzle["id"] = game_meta.get("headers", {}).get("Site", "").replace("/", "_").strip() or \
        f"{game_meta['white'].replace(' ', '_')}_vs_{game_meta['black'].replace(' ', '_')}"
    puzzle["id"] = puzzle["id"].replace(" ", "_").replace(".", "_")[:64] or "custom_gm"
    log(f"  puzzle ID: {puzzle['id']}")

    log("== building video ==")
    result = builder.build_one(
        puzzle,
        variant="gm_games",
        output_dir=output_dir or config.OUTPUT_DIR,
        use_api=False,
        seq=1,
        log=log,
    )

    if result["status"] != "ok":
        log(f"BUILD FAILED: {result['error']}")
        return ""

    elapsed = time.time() - started
    log(f"== done in {elapsed:.1f}s: {result['video']}")
    if result.get("needs_caption"):
        log("   (caption is a placeholder — rerun with --with-captions to fill)")

    return result["video"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Turn a real PGN into a video using the GM game replay renderer."
    )
    parser.add_argument("--pgn-file", type=Path, default=None,
                        help="Path to a .pgn file")
    parser.add_argument("--pgn-string", type=str, default=None,
                        help="Raw PGN text (quote it!)")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Output root directory (default: output/)")
    parser.add_argument("--with-captions", action="store_true",
                        help="Generate Claude captions for this video")
    args = parser.parse_args(argv)

    if args.pgn_file:
        pgn_text = Path(args.pgn_file).read_text(encoding="utf-8")
    elif args.pgn_string:
        pgn_text = args.pgn_string
    else:
        print("ERROR: pass --pgn-file <path> or --pgn-string \"<pgn>\"")
        return 2

    import shutil
    print(f"renderer: {board_mod.active_renderer()}")
    print(f"ffmpeg  : {config.FFMPEG}")
    if shutil.which(config.FFMPEG) is None and not Path(config.FFMPEG).is_file():
        print("ERROR: ffmpeg not found. Install it and ensure it is on PATH.")
        return 3

    video_path = generate(
        pgn_text,
        output_dir=args.output_dir,
        log=print,
    )
    if video_path:
        print(f"\nSUCCESS -> {video_path}")
    else:
        print("\nFAILED")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())