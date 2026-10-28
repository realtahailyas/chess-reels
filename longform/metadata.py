"""YouTube title, description and tags for a rendered long-form video.

Everything written here comes from the PGN headers, the engine's marks and the
photo credits, and nothing else. There is no invented story and no quote. A
wrong fact under a famous game is the kind of thing a chess audience corrects
in the comments, forever.
"""

import json
import re

import config
from longform import lfconfig as C
from longform import players
from longform.games import surname

APP_LINK = f"https://{config.ENDCARD_WEB}"
FEMALE = {"polgar"}


def clean_author(raw: str) -> str:
    """Commons 'Artist' fields are often a sentence in two languages run
    together ("This photo was taken by X JahrAutorem zdjęcia jest X…"). Keep
    the first name-like credit."""
    a = re.sub(r"\s+", " ", raw or "").strip()
    a = re.sub(r"^(this photo was taken by|photo by|photographed by)\s+", "", a, flags=re.I)
    # "Przemysław JahrAutorem…" -> "Przemysław Jahr". Only after a multi-word
    # name, so usernames like "GibChess" or "TheBoburshokh" stay whole.
    for m in re.finditer(r"(?<=[a-ząćęłńóśźż.])(?=[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż])", a):
        if " " in a[:m.start()].strip():
            a = a[:m.start()]
            break
    a = a.split(". ")[0].rstrip(".…").strip()
    a = re.sub(r"(Unknown author)+", "Unknown author", a)
    return a or "Unknown author"


def _ts(t: int) -> str:
    return f"{t // 60}:{t % 60:02d}"


def _winner(meta):
    if meta["result"] == "1-0":
        return meta["white"], meta["black"], "white", meta.get("white_slug")
    if meta["result"] == "0-1":
        return meta["black"], meta["white"], "black", meta.get("black_slug")
    return None, None, None, None


def _event_tag(meta) -> str:
    ev = meta["event"] or meta["site"]
    year = meta["year"]
    if year and year not in ev:
        ev = f"{ev} {year}".strip()
    return ev


def title(meta: dict) -> str:
    w, b = meta["white"], meta["black"]
    if meta.get("title"):
        full = f"{meta['title']} | {w} vs {b}, {meta['year']}".strip(", ")
        return full if len(full) <= 100 else f"{meta['title']} | {surname(w)} vs {surname(b)} {meta['year']}"[:100]

    winner, loser, side, wslug = _winner(meta)
    pron = "Her" if wslug in FEMALE else "His"
    marks = meta.get("marks", [])
    sac = next((m for m in marks if m["glyph"] == "!!" and m["mover"] == side), None)
    blunder = next((m for m in marks if m["glyph"] == "??" and m["mover"] != side), None)
    if winner and sac and sac["text"].endswith("sacrifice"):
        piece = sac["text"].split()[0]
        head = f"{winner} Sacrifices {pron} {piece} Against {loser}"
    elif winner and meta.get("final_mate"):
        head = f"{winner} Checkmates {loser}"
    elif winner and blunder:
        head = f"{winner} Punishes {loser}'s Blunder"
    elif winner:
        head = f"{winner} Beats {loser}"
    else:
        head = f"{w} vs {b}"
    full = f"{head} | {_event_tag(meta)}"
    if len(full) > 100:
        full = f"{head} | {meta['year']}"
    if len(full) > 100:
        full = head.replace(winner or "", surname(winner or "")).replace(loser or "", surname(loser or ""))
    return full[:100]


def description(meta: dict) -> str:
    w, b = meta["white"], meta["black"]
    we = f" ({meta['white_elo']})" if meta.get("white_elo") else ""
    be = f" ({meta['black_elo']})" if meta.get("black_elo") else ""
    where = ", ".join(x for x in (meta["event"], meta["site"], meta["year"]) if x)
    winner, loser, _, _ = _winner(meta)
    if winner:
        how = " by checkmate" if meta.get("final_mate") else f" ({surname(loser)} resigned)"
        result = f"{meta['result']}: {winner} wins{how}"
    else:
        result = f"{meta['result']}: draw"

    lines = [f"{w}{we} vs {b}{be}", where, result]
    if meta.get("opening"):
        lines.append(f"Opening: {meta['opening']}")
    lines += ["", "The full game, every move, with no commentary. Stockfish marks the "
                  "brilliant moves (!!), the only moves (!) and the mistakes (?, ??)."]

    chapters = meta.get("chapters", [])
    if len(chapters) >= 3:
        lines += ["", "Chapters"]
        for c in chapters:
            label = "Start" if c["t"] == 0 else c["label"]
            lines.append(f"{_ts(c['t'])} {label}")

    loud = [m for m in meta.get("marks", []) if m["glyph"] in ("!!", "??", "#")]
    quiet = [m for m in meta.get("marks", []) if m["glyph"] == "!"]
    keys = sorted((loud + quiet)[:8], key=lambda m: m["ply"])   # the big moments always make the cut
    if keys:
        lines += ["", "Key moments"]
        for m in keys:
            n = m["ply"] // 2 + 1
            dots = "." if m["ply"] % 2 == 0 else "..."
            who = surname(w if m["mover"] == "white" else b)
            what = {"!!": "brilliant", "!": "only move", "??": "blunder", "#": "checkmate"}[m["glyph"]]
            glyph = "" if m["glyph"] == "#" else m["glyph"]
            extra = f", {m['text'].lower()}" if m["glyph"] == "!!" and m.get("text") else ""
            lines.append(f"{n}{dots} {m['san']}{glyph} ({who}, {what}{extra})")

    lines += ["", f"Train with free puzzles and bots in the TChess app: {APP_LINK}"]

    cred = players.credits()
    photo_lines = []
    for slug in (meta.get("white_slug"), meta.get("black_slug")):
        c = cred.get(slug) if slug else None
        if c and players.photo_path(slug):
            author = clean_author(c["author"])
            photo_lines.append(f"{c['name']}: {author}, {c['license']}, via Wikimedia Commons ({c['source']})")
    if photo_lines:
        lines += ["", "Photos"] + photo_lines

    tags = " ".join(f"#{re.sub(r'[^A-Za-z0-9]', '', surname(n))}" for n in (w, b))
    lines += ["", f"#chess {tags} #chessgame"]
    text = "\n".join(lines)
    return text.replace("<", "(").replace(">", ")")[:4900]   # YouTube rejects angle brackets


def tags(meta: dict) -> list:
    out = ["chess", "chess game", "grandmaster", "brilliant move", "chess highlights",
           meta["white"], meta["black"], surname(meta["white"]), surname(meta["black"])]
    for x in (meta.get("event"), meta.get("opening"), meta.get("year")):
        if x:
            out.append(x)
    seen, clean = set(), []
    total = 0
    for t in out:
        t = t.replace("<", "").replace(">", "").replace(",", " ").strip()
        if t and t.lower() not in seen and total + len(t) < 450:
            seen.add(t.lower())
            clean.append(t)
            total += len(t) + 1
    return clean


def fb_caption(meta: dict) -> str:
    """Facebook reel description: the YouTube one, minus what Facebook lacks.

    No chapters (Facebook reels have none) and fewer lines: the caption
    shows two lines before "See more". Photo credits stay, because CC BY
    requires them wherever the photo appears.
    """
    text = description(meta)
    out, skip = [], False
    for line in text.splitlines():
        if line == "Chapters":
            skip = True
            continue
        if skip:
            if line.strip() == "":
                skip = False
            continue
        out.append(line)
    head = title(meta)
    return (head + "\n\n" + "\n".join(out)).strip()[:4900]


def for_dir(out_dir) -> dict:
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    return {"title": title(meta), "description": description(meta), "tags": tags(meta), "meta": meta}
