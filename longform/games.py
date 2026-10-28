"""Game loading: the featured catalogue, PGN lookup, names and opening names."""

import csv
import functools
import re

import chess

from longform import lfconfig as C
from longform import library, players

# Archive spellings that are wrong or unfamiliar to viewers, for players who
# are not in players.STARS (stars get their canonical name from there).
NAME_FIX = {
    "Gary Kasparov": "Garry Kasparov",
    "Robert James Fischer": "Bobby Fischer",
}


def display_name(raw: str) -> str:
    """"Kasparov, Gary" -> "Garry Kasparov"; unknown "Ernst,S" -> "S Ernst"."""
    star = players.canonical(raw)
    if star:
        return star
    raw = re.sub(r"\s+", " ", (raw or "?")).strip()
    raw = re.sub(r"^Comp\s+", "", raw)
    if "," in raw:
        last, first = [p.strip() for p in raw.split(",", 1)]
        first = first.rstrip(".")
        raw = f"{first} {last}".strip()
    return NAME_FIX.get(raw, raw)


def surname(name: str) -> str:
    """Last word, except for names that lead with the family name."""
    if name in ("Ding Liren", "Wei Yi"):
        return name.split()[0]
    if name == "Gukesh D":
        return "Gukesh"
    if name == "R Praggnanandhaa":
        return "Praggnanandhaa"
    return name.split()[-1] if name.strip() else name


def load(entry: dict) -> dict:
    """Resolve a catalogue entry (it carries a library record) for the renderer."""
    game = library.read(entry["rec"])
    h = game.headers
    board = game.board()
    moves, sans = [], []
    for mv in game.mainline_moves():
        sans.append(board.san(mv))
        moves.append(mv)
        board.push(mv)
    year = (h.get("Date", "") or "")[:4]
    white, black = display_name(h.get("White")), display_name(h.get("Black"))
    return {
        "id": entry["id"],
        "title": entry.get("title") or "",
        "curated": bool(entry.get("title")),
        "white": white,
        "black": black,
        "white_slug": players.identify(h.get("White")),
        "black_slug": players.identify(h.get("Black")),
        "white_elo": h.get("WhiteElo", "").strip(),
        "black_elo": h.get("BlackElo", "").strip(),
        "event": clean_event(h.get("Event", "")),
        # "Singapore SIN" -> "Singapore": the archive's country code reads as noise.
        "site": re.sub(r"\s+[A-Z]{3}$", "", h.get("Site", "").strip().strip("?")),
        "year": year if year.isdigit() else "",
        "round": h.get("Round", "").strip("?"),
        "result": h.get("Result", "*"),
        "eco": h.get("ECO", ""),
        "start_fen": game.board().fen(),
        "moves": moves,
        "sans": sans,
        "final_board": board,
    }


def clean_event(event: str) -> str:
    e = re.sub(r"'[^']*'", "", event or "")          # archive nicknames: London 'Immortal game'
    e = re.sub(r"\s+", " ", e).strip().strip("?").strip()
    e = e.replace("WCh", "World Championship").replace("Candidats", "Candidates")
    e = re.sub(r"^\d+(st|nd|rd|th) ", "", e)
    return e


# ── Opening names (lichess-org/chess-openings, CC0) ────────────────────────

@functools.lru_cache(maxsize=1)
def _opening_table() -> dict:
    table = {}
    for tsv in sorted(C.OPENINGS_DIR.glob("*.tsv")):
        with open(tsv, encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                b = chess.Board()
                try:
                    for tok in row["pgn"].split():
                        if tok.endswith("."):
                            continue
                        b.push_san(tok)
                except ValueError:
                    continue
                table[b.epd()] = (row["eco"], row["name"])
    return table


def opening_names(start_fen: str, moves) -> list:
    """Per ply (index = plies played), the most specific opening name so far."""
    table = _opening_table()
    b = chess.Board(start_fen)
    current = ""
    out = [current]
    for mv in moves:
        b.push(mv)
        hit = table.get(b.epd())
        if hit:
            current = hit[1]
        out.append(current)
    return out


def book_depth(start_fen: str, moves) -> int:
    """Plies that are still a named opening position — the fast-forward span."""
    table = _opening_table()
    b = chess.Board(start_fen)
    depth = 0
    for i, mv in enumerate(moves):
        b.push(mv)
        if b.epd() in table:
            depth = i + 1
    return depth
