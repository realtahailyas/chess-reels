"""What gets made, in what order, for which channel.

Two sources:
  CURATED  the famous games, hand-picked, with their known names. They go
           first, alternating legends and modern games.
  scored   every decisive game between two stars in the library, ranked by
           who played, where and how long it lasted. These follow the curated
           games, and the ranking is interleaved so no player runs on for days.

The two channels NEVER get the same game. The combined order is dealt out
alternately (A, B, A, B...), so each channel gets a mix of both sources.
The queue is written to data/longform/catalog.json. Build/publish state lives
in the ledger (publisher.py), not here, so rebuilding the catalogue never
forgets what has been posted.
"""

import json
import re

from longform import lfconfig as C
from longform import library, players

CATALOG = C.DATA / "catalog.json"

# Match values are substrings, except a leading "=" which means exact.
CURATED = [
    ("kasparov-topalov-1999", "Kasparov's Immortal",
     dict(White="Kasparov", Black="Topalov", Date="1999.01.20")),
    ("byrne-fischer-1956", "The Game of the Century",
     dict(White="Byrne, Donald", Black="Fischer", Date="1956")),
    ("ding-gukesh-2024-g14", "The Game That Made Gukesh World Champion",
     dict(White="Ding", Black="Gukesh", Round="=14.1")),
    ("anderssen-kieseritzky-1851", "The Immortal Game",
     dict(White="Anderssen", Black="Kieseritzky", Event="Immortal")),
    ("pragg-carlsen-2024", "Praggnanandhaa Beats Magnus Carlsen in Classical Chess",
     dict(White="Praggnanandhaa", Black="Carlsen", Event="Norway Chess 2024")),
    ("morphy-opera-1858", "The Opera Game",
     dict(White="Morphy", Black="Duke Karl", Date="1858")),
    ("carlsen-ernst-2004", "13-Year-Old Magnus Carlsen's Brilliancy",
     dict(White="Carlsen", Black="Ernst", Date="2004.01.24")),
    ("fischer-spassky-1972-g6", "Fischer's Masterpiece: World Championship 1972, Game 6",
     dict(White="Fischer", Black="Spassky", Date="1972", Round="=6")),
    ("anand-carlsen-2013-g9", "Anand vs Carlsen: World Championship 2013, Game 9",
     dict(White="Anand", Black="Carlsen", Round="=9", Date="2013.11")),
    ("karpov-kasparov-1985-g16", "Kasparov's Octopus Knight",
     dict(White="Karpov", Black="Kasparov", Date="1985", Round="=16")),
    ("aronian-anand-2013", "Anand's Tata Steel Masterpiece",
     dict(White="Aronian", Black="Anand", Date="2013.01.15")),
    ("anderssen-dufresne-1852", "The Evergreen Game",
     dict(White="Anderssen", Black="Dufresne", Event="Evergreen")),
    ("gukesh-ding-2024-g3", "Gukesh's First Win in the World Championship",
     dict(White="Gukesh", Black="Ding", Round="=3.1")),
    ("topalov-shirov-1998", "Shirov's Impossible Bishop Move",
     dict(White="Topalov", Black="Shirov", Event="Linares", Date="1998")),
    ("carlsen-anand-2013-g5", "Carlsen Breaks Through: World Championship 2013, Game 5",
     dict(White="Carlsen", Black="Anand", Round="=5", Date="2013.11")),
    ("rotlewi-rubinstein-1907", "Rubinstein's Immortal",
     dict(White="Rotlewi", Black="Rubinstein", Date="1907")),
    ("polgar-kasparov-2002", "The Day Judit Polgar Beat Garry Kasparov",
     dict(White="Polgar", Black="Kasparov", Date="2002.09")),
    ("polugaevsky-nezhmetdinov-1958", "Nezhmetdinov's Masterpiece",
     dict(White="Polugaevsky", Black="Nezhmetdinov")),
    ("karpov-kasparov-1985-g24", "The Game That Made Kasparov World Champion",
     dict(White="Karpov", Black="Kasparov", Date="1985", Round="=24")),
    ("byrne-fischer-1963", "Fischer's Brilliancy at the 1963 US Championship",
     dict(White="Byrne, Robert", Black="Fischer", Date="1963")),
    ("deepblue-kasparov-1997-g6", "Deep Blue vs Kasparov: The Final Game",
     dict(White="Deep Blue", Black="Kasparov", Date="1997", Round="=6")),
    ("tal-larsen-1965-g10", "Tal vs Larsen: 1965 Candidates, Game 10",
     dict(White="Tal", Black="Larsen", Date="1965", Round="=10")),
    ("short-timman-1991", "Short's King Walk",
     dict(White="Short", Black="Timman", Event="Tilburg", Date="1991")),
    ("spassky-fischer-1972-g3", "Fischer's First Ever Win Against Spassky",
     dict(White="Spassky", Black="Fischer", Date="1972", Round="=3")),
    ("botvinnik-capablanca-1938", "Botvinnik vs Capablanca, AVRO 1938",
     dict(White="Botvinnik", Black="Capablanca", Date="1938")),
    ("reti-alekhine-1925", "Alekhine's Baden-Baden Brilliancy",
     dict(White="Reti", Black="Alekhine", Date="1925")),
    ("lasker-bauer-1889", "Lasker's Double Bishop Sacrifice",
     dict(White="Lasker", Black="Bauer", Date="1889")),
    ("steinitz-bardeleben-1895", "Steinitz vs von Bardeleben, Hastings 1895",
     dict(White="Steinitz", Black="Bardeleben")),
    ("capablanca-marshall-1918", "Capablanca vs Marshall: The First Marshall Attack",
     dict(White="Capablanca", Black="Marshall", Date="1918")),
]

LEGEND_BEFORE = 2000   # a game older than this counts as "legends" for interleaving

# Star power for ranking. Everyone else in players.STARS scores FAME_DEFAULT.
FAME = {
    "carlsen": 12, "kasparov": 12, "fischer": 12, "nakamura": 11, "tal": 11,
    "gukesh": 10, "anand": 10, "karpov": 9, "morphy": 9, "capablanca": 9,
    "pragg": 9, "firouzja": 8, "caruana": 8, "ding": 8, "arjun": 8,
    "kramnik": 8, "alekhine": 8, "spassky": 7, "polgar": 8, "nepo": 7,
    "abdusattorov": 7, "botvinnik": 6, "petrosian": 6, "shirov": 7,
}
FAME_DEFAULT = 4
PRESTIGE = [
    (r"world ?ch|wch|world championship", 30), (r"candidat", 20), (r"olympiad", 8),
    (r"tata|corus|hoogovens|wijk", 10), (r"norway", 10), (r"sinquefield|grand chess tour|gct", 8),
    (r"linares|dortmund|london classic|zurich|bled", 8),
]
SKIP_EVENT = re.compile(
    r"blitz|bullet|banter|blind|simul|armageddon|odds|960|random|freestyle|consult|exhib|"
    r"titled|bundesliga|lichess|chess\.com|online|speed|basque|puzzle", re.I)


def _match(rec: dict, spec: dict) -> bool:
    for k, v in spec.items():
        have = str(rec.get(k, ""))
        if v.startswith("="):
            if have != v[1:]:
                return False
        elif v.lower() not in have.lower():
            return False
    return True


def resolve_curated(log=print) -> list:
    out = []
    games = library.all_games()
    for gid, title, spec in CURATED:
        hits = [g for g in games if _match(g, spec)]
        if len(hits) != 1:
            log(f"  curated {gid}: {len(hits)} matches — skipped")
            continue
        out.append({"id": gid, "title": title, "rec": hits[0], "source": "curated"})
    return out


def _year(rec) -> int:
    y = (rec.get("Date") or "")[:4]
    return int(y) if y.isdigit() else 0


def score(rec: dict) -> float | None:
    if rec.get("Result") not in ("1-0", "0-1"):
        return None
    if SKIP_EVENT.search(rec.get("Event", "")) or SKIP_EVENT.search(rec.get("Site", "")):
        return None
    w, b = players.identify(rec["White"]), players.identify(rec["Black"])
    if not w or not b or w == b or "deepblue" in (w, b):
        return None
    if not players.photo_path(w) or not players.photo_path(b):
        return None
    s = FAME.get(w, FAME_DEFAULT) + FAME.get(b, FAME_DEFAULT)
    ev = f"{rec.get('Event', '')} {rec.get('Site', '')}".lower()
    s += max([pts for pat, pts in PRESTIGE if re.search(pat, ev)] or [0])
    pc = rec.get("PlyCount", "")
    if pc.isdigit():
        n = int(pc)
        if n < 30 or n > 150:
            return None
        s += 4 if n <= 80 else 0      # sharp, decisive games keep a viewer
    return s


def build(per_pair: int = 2, limit: int = 1200, log=print) -> list:
    curated = resolve_curated(log)
    taken = {c["rec"]["key"] for c in curated}
    ranked = []
    for rec in library.all_games():
        if rec["key"] in taken:
            continue
        s = score(rec)
        if s is not None:
            ranked.append((s, _year(rec), rec))
    ranked.sort(key=lambda t: (-t[0], -t[1]))

    # Cap each pairing so the list is not 40 Carlsen-Nakamura games.
    pairs, picked = {}, []
    for s, _, rec in ranked:
        pair = tuple(sorted((players.identify(rec["White"]), players.identify(rec["Black"]))))
        if pairs.get(pair, 0) >= per_pair:
            continue
        pairs[pair] = pairs.get(pair, 0) + 1
        w, b = pair
        picked.append({"id": f"{w}-{b}-{rec['key']}", "title": "", "rec": rec,
                       "source": "scored", "score": s})
        if len(picked) >= limit:
            break

    # Interleave legends and modern games, and keep the same player from
    # appearing in two games that are next to each other.
    legends = [p for p in picked if _year(p["rec"]) < LEGEND_BEFORE]
    modern = [p for p in picked if _year(p["rec"]) >= LEGEND_BEFORE]
    order, recent = [], []
    pools = [modern, legends]
    turn = 0
    while legends or modern:
        pool = pools[turn % 2] or pools[(turn + 1) % 2]
        pick = next((p for p in pool if not ({players.identify(p["rec"]["White"]),
                                               players.identify(p["rec"]["Black"])} & set(recent))), pool[0])
        pool.remove(pick)
        order.append(pick)
        recent = ([players.identify(pick["rec"]["White"]), players.identify(pick["rec"]["Black"])] + recent)[:6]
        turn += 1

    queue = curated + order
    CATALOG.write_text(json.dumps(queue, indent=1), encoding="utf-8")
    log(f"  catalogue: {len(curated)} curated + {len(order)} scored = {len(queue)} games")
    return queue


def load() -> list:
    return json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.is_file() else build()


def for_brand(brand: str) -> list:
    """This channel's half of the queue: even positions to one, odd to the other."""
    idx = sorted(C.BRANDS).index(brand)
    return [e for i, e in enumerate(load()) if i % len(C.BRANDS) == idx]
