"""Build landscape long-form GM-game videos (YouTube, 1920x1080).

    python make_longform.py --catalog                     # (re)build the game queue
    python make_longform.py --photos                      # fetch any missing player photos
    python make_longform.py --game kasparov-topalov-1999  # one game, TChess brand
    python make_longform.py --game kasparov-topalov-1999 --brand tahachess
    python make_longform.py --game kasparov-topalov-1999 --plies 20   # quick test
    python make_longform.py --game kasparov-topalov-1999 --brand tahachess --reel   # 9:16 FB reel

Publishing is longform_daily.py's job. Nothing here touches the shorts pipeline,
its ledger or its output folders. Output lands in output/longform/<id>_<brand>/.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from longform import catalog, players, render  # noqa: E402
from longform import lfconfig as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", help="catalogue game id")
    ap.add_argument("--brand", default="tchess", choices=sorted(C.BRANDS))
    ap.add_argument("--reel", action="store_true", help="9:16 Facebook reel instead of the 16:9 video")
    ap.add_argument("--plies", type=int, help="render only the first N plies (testing)")
    ap.add_argument("--catalog", action="store_true", help="rebuild data/longform/catalog.json")
    ap.add_argument("--photos", action="store_true", help="download missing player photos")
    args = ap.parse_args()

    if args.photos:
        players.fetch()
    if args.catalog:
        catalog.build()
    if not args.game:
        return
    entry = next((e for e in catalog.load() if e["id"] == args.game), None)
    if entry is None:
        sys.exit(f"unknown game id: {args.game}")
    print(f"[{entry['id']}]", flush=True)
    render.build(entry, brand=args.brand, limit_plies=args.plies, fmt="reel" if args.reel else "wide",
                 log=lambda s: print(s, flush=True))


if __name__ == "__main__":
    main()
