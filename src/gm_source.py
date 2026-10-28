"""Real GM game sourcing for the full-game replay variant ("gm_games").

The Lichess puzzle CSV only tags 2-5 ply sacrifice puzzles pulled from
anonymous online games — the White/Black PGN headers are Lichess usernames
("nelubin", "aanreitaylor"), never FIDE names. Filtering that CSV for
`config.GM_TOP_PLAYERS` (as the old `puzzles.select(..., full_game=True)`
path did) makes one HTTP call per candidate and almost never matches, which
is why a scan could run for a long time and still come back empty.

Real named games for these players come from pgnmentor.com's per-player PGN
archives instead: one small zip download per player, cached under
GM_SOURCE_DIR forever, then sampled locally. A bulk run after the first
build touches the network only for players not yet cached.

Parsing a PGN archive (generating SAN for every move of every game, to
support instant replay-and-caption rendering later) is the slow part —
thousands of games per top player — so each archive is indexed to a JSON
sidecar the first time it's used. Every later bulk run, with any player/ECO
selection, just filters that JSON in memory: no PGN re-parsing, no network.
"""

import hashlib
import io
import json
import random
import re
import zipfile

import chess
import chess.pgn
import requests

import config

# config.GM_TOP_PLAYERS display name -> pgnmentor.com/players/<slug>.zip.
# Not every top-30 player has an archive there (mostly the newest 2400+
# juniors) — those are simply skipped rather than guessed at.
PLAYER_ARCHIVES = {
    "Magnus Carlsen": "Carlsen",
    "Hikaru Nakamura": "Nakamura",
    "Fabiano Caruana": "Caruana",
    "Arjun Erigaisi": "Erigaisi",
    "Nodirbek Abdusattorov": "Abdusattorov",
    "D Gukesh": "Gukesh",
    "Gukesh D": "Gukesh",
    "Alireza Firouzja": "Firouzja",
    "Ian Nepomniachtchi": "Nepomniachtchi",
    "Wei Yi": "Wei",
    "R Praggnanandhaa": "Praggnanandhaa",
    "Praggnanandhaa R": "Praggnanandhaa",
    "Praggnanandhaa Rameshbabu": "Praggnanandhaa",
    "Wesley So": "So",
    "Leinier Dominguez Perez": "DominguezPerez",
    "Leinier Dominguez": "DominguezPerez",
    "Ding Liren": "Ding",
    "Vincent Keymer": "Keymer",
    "Jan-Krzysztof Duda": "Duda",
    "Anish Giri": "Giri",
    "Shakhriyar Mamedyarov": "Mamedyarov",
    "Maxime Vachier-Lagrave": "VachierLagrave",
    "Levon Aronian": "Aronian",
    "Richard Rapport": "Rapport",
    "Viswanathan Anand": "Anand",
}

# pgnmentor.com blocks the default python-requests user-agent as a bot;
# a plain browser UA is enough to pass.
_HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
}

_TERMINATION_LABELS = {
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


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _termination_phrase(value: str) -> str:
    key = _norm(value).casefold()
    return _TERMINATION_LABELS.get(key, key or "unknown result")


def _clean_name(pgn_name: str) -> str:
    """"Carlsen,Magnus" -> "Magnus Carlsen"; passes through names with no comma."""
    name = _norm(pgn_name)
    if "," in name:
        last, _, first = name.partition(",")
        name = f"{first.strip()} {last.strip()}".strip()
    return name


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


# ── Download ──────────────────────────────────────────────────────────────

def download_archive(slug: str, force: bool = False, log=print):
    """Fetch and cache one player's PGN archive, skipping if already present."""
    config.GM_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    target = config.GM_SOURCE_DIR / f"{slug}.pgn"

    if target.exists() and target.stat().st_size > 0 and not force:
        return target

    url = f"{config.PGNMENTOR_PLAYERS_URL}{slug}.zip"
    log(f"  downloading {url}")
    resp = requests.get(url, headers=_HTTP_HEADERS, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        pgn_names = [n for n in zf.namelist() if n.lower().endswith(".pgn")]
        if not pgn_names:
            raise ValueError(f"no .pgn file inside {url}")
        data = zf.read(pgn_names[0])

    tmp = target.with_suffix(".pgn.partial")
    tmp.write_bytes(data)
    tmp.replace(target)
    log(f"  cached {target.name} ({target.stat().st_size / 1e6:.1f} MB)")
    return target


# ── PGN -> game_meta ────────────────────────────────────────────────────────

def _game_id(headers) -> str:
    key = "|".join(str(headers.get(k, "")) for k in
                   ("Event", "Site", "Date", "Round", "White", "Black"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def game_to_meta(game: "chess.pgn.Game"):
    """Convert a parsed PGN game into the game_meta dict build_one() expects.

    Same shape as puzzles.load_full_game() / custom_gm.parse_pgn() so it can
    flow through the existing full-game replay path untouched. Returns None
    for an empty game (e.g. a bye round with no moves).
    """
    headers = dict(game.headers)
    board = game.board()
    uci_moves, san_moves = [], []
    try:
        for move in game.mainline_moves():
            san_moves.append(board.san(move))
            uci_moves.append(move.uci())
            board.push(move)
    except (ValueError, AssertionError):
        return None  # corrupt move text somewhere in this game — skip it

    if not uci_moves:
        return None

    # Only games with a definitive recorded result — an adjourned/interrupted
    # game marked "*" has no checkmate or resignation to end the replay on,
    # which would read as the video cutting off mid-game.
    if headers.get("Result") not in {"1-0", "0-1", "1/2-1/2"}:
        return None

    white = _clean_name(headers.get("White", "?")) or "?"
    black = _clean_name(headers.get("Black", "?")) or "?"
    white_title = str(headers.get("WhiteTitle", "")).strip()
    black_title = str(headers.get("BlackTitle", "")).strip()
    white_label = f"{white_title} {white}".strip() if white_title else white
    black_label = f"{black_title} {black}".strip() if black_title else black
    white_elo = str(headers.get("WhiteElo", "")).strip()
    black_elo = str(headers.get("BlackElo", "")).strip()
    termination = str(headers.get("Termination", "")).strip()
    result = headers.get("Result", "*")

    if result == "1-0":
        winner, winner_name, winner_label = "white", white, white_label
    elif result == "0-1":
        winner, winner_name, winner_label = "black", black, black_label
    else:
        winner = winner_name = winner_label = None

    if termination and termination.casefold() not in {"", "normal"}:
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
        "result": result,
        "event": headers.get("Event", ""),
        "site": headers.get("Site", ""),
        "eco": headers.get("ECO", ""),
        "opening": headers.get("Opening", ""),
        "headers": headers,
        "_id": _game_id(headers),
        "_plies": len(uci_moves),
    }


def _build_puzzle(game_meta: dict) -> dict:
    gid = game_meta.pop("_id")
    game_meta.pop("_plies", None)
    rating = max(_safe_int(game_meta["white_elo"]), _safe_int(game_meta["black_elo"]))
    label = game_meta.get("opening") or game_meta.get("eco") or "GM Classic"
    return {
        "id": gid,
        "fen": game_meta["start_fen"],
        "solution": game_meta["moves"],
        "rating": rating,
        "themes": [],
        "popularity": 99,
        "game_url": "https://www.pgnmentor.com/",
        "theme_label": label,
        "series_label": game_meta.get("black_title") or "GM",
        "sacrificed_piece": None,
        "brilliant_index": None,
        "lichess_fen": game_meta["start_fen"],
        "lichess_moves": " ".join(game_meta["moves"]),
        "game_meta": game_meta,
    }


def iter_player_games(slug: str, force: bool = False, log=print):
    """Stream chess.pgn.Game objects from one player's cached archive."""
    path = download_archive(slug, force=force, log=log)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        while True:
            game = chess.pgn.read_game(fh)
            if game is None:
                return
            yield game


# ── Index cache ──────────────────────────────────────────────────────────
# Generating SAN for every move of every game (thousands per top player) is
# the slow part of sourcing — not the download. So each archive is parsed
# into a JSON index once; every later call, with any player/ECO/ply
# selection, just filters that JSON in memory instead of re-parsing PGN.

def _index_path(slug: str):
    return config.GM_SOURCE_DIR / f"{slug}.index.json"


def _load_or_build_index(slug: str, force: bool = False, log=print) -> list:
    pgn_path = download_archive(slug, force=force, log=log)
    idx_path = _index_path(slug)

    if idx_path.exists() and not force and idx_path.stat().st_mtime >= pgn_path.stat().st_mtime:
        with open(idx_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    log(f"  indexing {slug} (one-time; every later run reuses this)")
    games = []
    for game in iter_player_games(slug, force=False, log=log):
        meta = game_to_meta(game)
        if meta is not None:
            games.append(meta)

    tmp = idx_path.with_suffix(".json.partial")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(games, fh)
    tmp.replace(idx_path)
    log(f"  indexed {slug}: {len(games)} game(s) -> {idx_path.name}")
    return games


# ── Selection ────────────────────────────────────────────────────────────

def select_games(count: int, players=None, exclude=(), eco_prefix=None,
                  min_plies=None, max_plies=None, force_download=False,
                  seed=None, log=print) -> list:
    """Return up to `count` real GM games as puzzle-shaped dicts.

    Every returned dict already carries `game_meta`, so build_one() never
    hits the network for it (see the `if game_meta is None` guard in
    src/build.py) — sourcing happens once per player archive (download +
    index), not once per video. Sampled randomly across players/games so a
    batch stays varied.
    """
    min_plies = config.GM_SOURCE_MIN_PLIES if min_plies is None else min_plies
    max_plies = config.GM_SOURCE_MAX_PLIES if max_plies is None else max_plies
    exclude = set(exclude)

    names = players or list(PLAYER_ARCHIVES)
    unknown = sorted({n for n in names if n not in PLAYER_ARCHIVES})
    if unknown:
        log(f"  no pgnmentor archive for: {', '.join(unknown)} — skipping")
    slugs = sorted({PLAYER_ARCHIVES[n] for n in names if n in PLAYER_ARCHIVES})
    if not slugs:
        log("no known pgnmentor archive for the requested player(s)")
        return []

    pool = []
    for slug in slugs:
        games = _load_or_build_index(slug, force=force_download, log=log)
        kept = 0
        for meta in games:
            if not (min_plies <= meta["_plies"] <= max_plies):
                continue
            if eco_prefix and not meta["eco"].upper().startswith(eco_prefix.upper()):
                continue
            if meta["_id"] in exclude:
                continue
            pool.append(meta)
            kept += 1
        log(f"        {slug:16} {kept}/{len(games)} candidate game(s) after filtering")

    log(f"{len(pool):,} candidate games across {len(slugs)} player(s)")
    rng = random.Random(seed)
    rng.shuffle(pool)

    chosen = []
    seen = set()
    for meta in pool:
        if len(chosen) >= count:
            break
        if meta["_id"] in seen:
            continue
        seen.add(meta["_id"])
        chosen.append(_build_puzzle(dict(meta)))
    return chosen
