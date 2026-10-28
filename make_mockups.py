"""Write the tour's mockups out as standalone PNGs.

    python make_mockups.py                 # -> output/promo/mockups/
    python make_mockups.py --no-chrome     # no banner at all

These are the same frames the tour reel is built from (src/mockup.py), saved as
stills so they can be used as Play Store feature graphics, a website strip, or
anywhere a set of product shots is wanted. Rendering them from the same
function is the point — a separately drawn set would drift from the reel the
first time either was edited.

The banner sits at the BOTTOM, under the phone. At the top it fought this
format's own 108px label — two headers stacked — and dropping it altogether
left the frame unbranded. As a footer it competes with nothing. There is no
burnt-in handle here: the lockup already names the brand, and a handle beneath
it would repeat that in the same place.
"""

import argparse
from pathlib import Path

import config
from src import mockup

OUT = config.OUTPUT_DIR / "promo" / "mockups"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-chrome", action="store_true",
                    help="drop the bottom banner (rarely wanted)")
    ap.add_argument("--at", type=float, default=3.0,
                    help="seconds into the shot; the entrance is over by ~1.0")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, (name, label, callout, _vo) in enumerate(config.TOUR_SHOTS):
        src = config.TOUR_SHOT_DIR / name
        if not src.is_file():
            raise FileNotFoundError(f"screenshot missing: {src}")
        img = mockup.phone_shot(str(src), label, callout,
                                mockup.ACCENTS[i % len(mockup.ACCENTS)],
                                args.at, side=i % 2,
                                chrome=False if args.no_chrome else None)
        suffix = "-plain" if args.no_chrome else ""
        path = args.out / f"{i + 1:02d}-{label.lower()}{suffix}.png"
        img.save(path, optimize=True)
        written.append(path)
        print(f"  {path.name:22} {label.upper():10} {callout}")

    total = sum(p.stat().st_size for p in written)
    print(f"\n{len(written)} mockups · {config.CANVAS_W}x{config.CANVAS_H} · "
          f"{total / 1e6:.1f} MB\n{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
