"""Lichess puzzle sourcing: download, filter, validate, select.

The Lichess puzzle database is CC0, so there is no attribution or licensing
constraint on the videos built from it.
"""

import io
import random
import re
import sys

import chess
import pandas as pd
import requests
import zstandard

import config

CSV_COLUMNS = ["PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation",
               "Popularity", "NbPlays", "Themes", "GameUrl", "OpeningTags"]

# Raw Lichess tags mapped to display names, most specific first.
THEME_LABELS = {
    "greekGift": "Greek Gift Sacrifice",
    "smotheredMate": "Smothered Mate",
    "doubleCheck": "Double Check",
    "deflection": "Deflection Sacrifice",
    "attraction": "King Attraction",
    "clearance": "Clearance Sacrifice",
    "sacrifice": "Queen Sacrifice",   # only when a queen is the piece given up
    "mateIn2": "Mate in 2",
    "mateIn3": "Mate in 3",
}
FALLBACK_LABEL = "Sacrifice"

PIECE_NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
               chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


GM_TOP_NAMES = {_norm_name(name) for name in config.GM_TOP_PLAYERS}


def _format_player_name(headers, color: str) -> str:
    title = str(headers.get(f"{color}Title", "")).strip()
    name = str(headers.get(color, "")).strip()
    if title and name:
        return f"{title} {name}"
    return name or title or color


def _termination_phrase(value: str) -> str:
    key = re.sub(r"\s+", " ", str(value)).strip().casefold()
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


def is_top_gm_game(meta: dict) -> bool:
    names = {_norm_name(meta.get("white", "")), _norm_name(meta.get("black", ""))}
    return bool(names & GM_TOP_NAMES)


def _game_id_from_url(game_url: str) -> str:
    match = re.search(r"lichess\.org/([A-Za-z0-9]+)", game_url)
    if not match:
        raise ValueError(f"could not parse Lichess game id from {game_url!r}")
    return match.group(1)


def load_full_game(game_url: str, log=print) -> dict:
    """Fetch and parse the full public PGN for a Lichess game.

    Returns the start FEN, SAN/uci mainline, and player names so a build can
    replay the whole game instead of just the puzzle line.
    """
    game_id = _game_id_from_url(game_url)
    url = f"https://lichess.org/game/export/{game_id}"
    resp = requests.get(url, params={
        "moves": "true",
        "clocks": "false",
        "evals": "false",
        "opening": "true",
        "tags": "true",
        "literate": "false",
    }, timeout=30)
    resp.raise_for_status()

    header_re = re.compile(r'^\[(\w+)\s+"(.*)"\]$')
    headers = {}
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            break
        match = header_re.match(line)
        if match:
            headers[match.group(1)] = match.group(2)

    board = chess.Board(headers.get("FEN", chess.STARTING_FEN))
    move_text = resp.text.split("\n\n", 1)[1] if "\n\n" in resp.text else ""
    tokens = move_text.replace("\n", " ").split()
    uci_moves = []
    san_moves = []
    for token in tokens:
        if token.endswith(".") or token in {"*", "1-0", "0-1", "1/2-1/2"}:
            continue
        move = board.parse_san(token)
        san_moves.append(token)
        uci_moves.append(move.uci())
        board.push(move)

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
    if termination and _norm_name(termination) not in {"", "normal"}:
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
    log(f"        game    {white_label} vs {black_label} ... {len(uci_moves)} plies")
    return {
        "start_fen": headers.get("FEN", chess.STARTING_FEN),
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
        "site": headers.get("Site", game_url),
        "headers": headers,
    }


# ── Download ──────────────────────────────────────────────────────────────

def download(force: bool = False, log=print) -> "config.Path":
    """Fetch and decompress the puzzle database, skipping if already present.

    Streams through the zstd decompressor rather than buffering the archive, so
    peak memory stays flat on the ~250 MB download / ~1 GB output.
    """
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = config.PUZZLE_CSV

    if target.exists() and target.stat().st_size > 0 and not force:
        log(f"puzzle database present ({target.stat().st_size / 1e6:.0f} MB)")
        return target

    log(f"downloading {config.PUZZLE_URL} (~250 MB, several minutes)")
    tmp = target.with_suffix(".csv.partial")
    dctx = zstandard.ZstdDecompressor()

    with requests.get(config.PUZZLE_URL, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        seen = 0
        with open(tmp, "wb") as out:
            with dctx.stream_writer(out, closefd=False) as decomp:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if not chunk:
                        continue
                    decomp.write(chunk)
                    seen += len(chunk)
                    if total:
                        pct = seen / total * 100
                        print(f"\r  {pct:5.1f}%  {seen/1e6:6.0f}/{total/1e6:.0f} MB",
                              end="", file=sys.stderr, flush=True)
        print("", file=sys.stderr)

    tmp.replace(target)
    log(f"decompressed to {target} ({target.stat().st_size / 1e6:.0f} MB)")
    return target


# ── Filter ────────────────────────────────────────────────────────────────

def load_and_filter(path=None, rating_min=None, rating_max=None,
                    theme=None, log=print) -> pd.DataFrame:
    """Return puzzles matching the content filter.

    Read in chunks because the decompressed CSV is ~1 GB and the target machine
    has 8 GB of RAM; only matching rows are ever retained.
    """
    path = path or config.PUZZLE_CSV
    rating_min = config.RATING_MIN if rating_min is None else rating_min
    rating_max = config.RATING_MAX if rating_max is None else rating_max

    keep = []
    scanned = 0
    for chunk in pd.read_csv(path, chunksize=200_000, usecols=CSV_COLUMNS):
        scanned += len(chunk)
        mask = (
            # the content niche
            chunk.Themes.str.contains("sacrifice", na=False, case=False)
            # caps the solution at 2-5 plies, which keeps videos 12-22 s
            & chunk.Themes.str.contains("short|mateIn2|mateIn3", na=False, regex=True)
            # hard enough to feel clever, easy enough that viewers can solve
            # it — that is what drives comments
            & chunk.Rating.between(rating_min, rating_max)
            # community-upvoted, filters out ugly positions
            & (chunk.Popularity > config.MIN_POPULARITY)
            # battle-tested, low chance of a broken puzzle
            & (chunk.NbPlays > config.MIN_PLAYS)
        )
        if theme:
            mask &= chunk.Themes.str.contains(theme, na=False, case=False)
        matched = chunk[mask]
        if len(matched):
            keep.append(matched)

    df = pd.concat(keep, ignore_index=True) if keep else pd.DataFrame(columns=CSV_COLUMNS)
    log(f"filtered {len(df):,} puzzles from {scanned:,} scanned")
    return df


# ── Validation ────────────────────────────────────────────────────────────

def validate(fen: str, solution) -> bool:
    """Every move must be legal from the puzzle position, 2-5 plies long."""
    try:
        board = chess.Board(fen)
    except ValueError:
        return False
    if len(solution) < config.SOLUTION_MIN or len(solution) > config.SOLUTION_MAX:
        return False
    for uci in solution:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return False
        if move not in board.legal_moves:
            return False
        board.push(move)
    return True


def is_visual_sacrifice(fen: str, first_uci: str) -> bool:
    """True when the first move reads as a sacrifice on screen.

    Either it captures, or the moving piece lands on a square the opponent
    attacks. Without one of those the "sacrifice" tag is not visually legible
    and the video has no payoff.
    """
    board = chess.Board(fen)
    move = chess.Move.from_uci(first_uci)
    if move not in board.legal_moves:
        return False
    if board.is_capture(move):
        return True
    return board.is_attacked_by(not board.turn, move.to_square)


def theme_label(fen: str, first_uci: str, themes) -> str:
    """Human-readable label, preferring the strongest hook."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(first_uci)
    piece = board.piece_at(move.from_square)

    # A queen sacrifice outranks every other tag as a hook.
    if piece is not None and piece.piece_type == chess.QUEEN:
        return "Queen Sacrifice"

    for tag, label in THEME_LABELS.items():
        if tag in themes:
            if tag == "sacrifice":
                continue          # only meaningful for a queen, handled above
            return label
    return FALLBACK_LABEL


def sacrificed_piece(fen: str, first_uci: str) -> str:
    board = chess.Board(fen)
    piece = board.piece_at(chess.Move.from_uci(first_uci).from_square)
    return PIECE_NAMES.get(piece.piece_type, "piece") if piece else "piece"


# Material values for judging brilliance — Section 4.4 / badge detection. Kept
# independent of the Lichess theme tags, which are noisy.
BRILLIANT_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def brilliant_index(fen: str, solution):
    """Index of the brilliant move in the solution, or None.

    A move is brilliant when the piece is genuinely given up: it either lands
    on a square the opponent defends or captures, AND the moving piece is worth
    more than whatever it takes (or takes nothing). Only the first solution
    move is ever considered — that is the puzzle's point.
    """
    if not solution:
        return None
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(solution[0])
    except ValueError:
        return None
    if move not in board.legal_moves:
        return None

    piece = board.piece_at(move.from_square)
    if piece is None:
        return None

    is_capture = board.is_capture(move)
    lands_defended = board.is_attacked_by(not board.turn, move.to_square)
    if not (is_capture or lands_defended):
        return None

    moved_value = BRILLIANT_VALUES[piece.piece_type]
    if not is_capture:
        return 0                      # piece offered on a defended square

    if board.is_en_passant(move):
        captured_value = BRILLIANT_VALUES[chess.PAWN]
    else:
        victim = board.piece_at(move.to_square)
        captured_value = BRILLIANT_VALUES[victim.piece_type] if victim else 0

    # Giving up more than you take (on a defended square) is the sacrifice.
    if moved_value > captured_value and lands_defended:
        return 0
    return None


# ── Row -> puzzle dict ────────────────────────────────────────────────────

def build_puzzle(row) -> dict | None:
    """Convert one CSV row into a puzzle dict, or None if unusable.

    The FEN in the file is the position BEFORE the opponent's setup move, and
    Moves[0] is played by the opponent. The position the viewer sees is the one
    after that move, and the solution is Moves[1:]. Getting this backwards
    makes every single puzzle wrong.
    """
    moves = str(row.Moves).split()
    if len(moves) < 2:
        return None

    try:
        board = chess.Board(str(row.FEN))
        board.push_uci(moves[0])          # opponent setup move
    except (ValueError, AssertionError):
        return None

    puzzle_fen = board.fen()              # THIS is what the viewer sees
    solution = moves[1:]                  # THIS is what we animate

    if not validate(puzzle_fen, solution):
        return None
    if not is_visual_sacrifice(puzzle_fen, solution[0]):
        return None

    themes = str(row.Themes).split()
    return {
        "id": str(row.PuzzleId),
        "fen": puzzle_fen,
        "solution": solution,
        "rating": int(row.Rating),
        "plays": int(row.NbPlays),
        "themes": themes,
        "popularity": int(row.Popularity),
        "game_url": str(row.GameUrl),
        "theme_label": theme_label(puzzle_fen, solution[0], themes),
        "sacrificed_piece": sacrificed_piece(puzzle_fen, solution[0]),
        "brilliant_index": brilliant_index(puzzle_fen, solution),
        # Raw Lichess pair, setup move first — this is what the PuzzleFlow app
        # expects (it auto-plays moves[0] before the player takes over), as
        # opposed to `fen`/`solution` above which this renderer animates.
        "lichess_fen": str(row.FEN),
        "lichess_moves": str(row.Moves),
    }


def select(count: int, exclude=(), df=None, seed=None, log=print,
           ranked: bool = False, full_game: bool = False, **filter_kw):
    """Return up to `count` validated puzzles, excluding already-used ids.

    Sampled randomly rather than top-N so repeated runs stay varied.
    """
    if df is None:
        df = load_and_filter(log=log, **filter_kw)
    if df.empty:
        return []

    exclude = set(exclude)
    pool = df[~df.PuzzleId.isin(exclude)]
    log(f"{len(pool):,} available after excluding {len(exclude):,} already used")

    rng = random.Random(seed)
    if ranked:
        ordered = pool.sort_values(
            by=["Rating", "Popularity", "NbPlays", "PuzzleId"],
            ascending=[False, False, False, True],
        )
        order = list(ordered.index)
    else:
        order = list(pool.index)
        rng.shuffle(order)

    chosen = []
    rejected = 0
    for idx in order:
        if len(chosen) >= count:
            break
        puzzle = build_puzzle(pool.loc[idx])
        if puzzle is None:
            rejected += 1
            continue
        if full_game:
            try:
                game_meta = load_full_game(puzzle["game_url"], log=log)
            except Exception:
                rejected += 1
                continue
            if not is_top_gm_game(game_meta):
                rejected += 1
                continue
            puzzle = dict(puzzle, game_meta=game_meta)
        chosen.append(puzzle)

    if rejected:
        log(f"rejected {rejected} puzzles during validation")
    return chosen
