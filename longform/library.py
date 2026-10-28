"""The game library: every archive PGN, indexed by header, deduplicated.

Two archive folders feed it:
  data/longform/pgn/   legends (pgnmentor player archives)
  data/gm_games/       the modern elite, already cached for the shorts' gm_games

The shorts folder is only READ. The index lives at data/longform/library.json
and records each game's file and byte offset, so loading one game later is a
seek, not a re-parse of a 10,000-game archive.
"""

import hashlib
import json
import re

import chess.pgn

import config
from longform import lfconfig as C

INDEX = C.DATA / "library.json"
SOURCES = [C.PGN_DIR, config.DATA_DIR / "gm_games"]
KEEP = ("Event", "Site", "Date", "Round", "White", "Black", "Result",
        "WhiteElo", "BlackElo", "ECO", "PlyCount")


def _key(h: dict) -> str:
    """Same game from two players' archives -> same key."""
    def norm(name):
        name = (name or "").lower()
        return re.sub(r"[^a-z]", "", name.split(",")[0])
    raw = "|".join([norm(h.get("White")), norm(h.get("Black")),
                    (h.get("Date") or "")[:10], h.get("Result", ""), h.get("Round", "")])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def build(log=print) -> list:
    games, seen = [], set()
    for folder in SOURCES:
        for path in sorted(folder.glob("*.pgn")):
            n = 0
            with open(path, encoding="latin-1") as fh:
                while True:
                    off = fh.tell()
                    h = chess.pgn.read_headers(fh)
                    if h is None:
                        break
                    rec = {k: h.get(k, "") for k in KEEP}
                    k = _key(rec)
                    if k in seen:
                        continue
                    seen.add(k)
                    rec.update(key=k, file=str(path.relative_to(config.ROOT)), offset=off)
                    games.append(rec)
                    n += 1
            log(f"  {path.name:28} {n:6} new")
    INDEX.write_text(json.dumps(games), encoding="utf-8")
    log(f"  {len(games)} unique games")
    return games


_cache = None


def all_games() -> list:
    global _cache
    if _cache is None:
        _cache = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.is_file() else build()
    return _cache


def search(**match) -> list:
    """Substring match on headers, case-insensitive: search(White="Byrne", Date="1956")."""
    out = []
    for g in all_games():
        if all(str(v).lower() in str(g.get(k, "")).lower() for k, v in match.items()):
            out.append(g)
    return out


def read(rec: dict) -> chess.pgn.Game:
    with open(config.ROOT / rec["file"], encoding="latin-1") as fh:
        fh.seek(rec["offset"])
        return chess.pgn.read_game(fh)
