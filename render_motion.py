"""Render a Remotion composition from the Python side.

    python render_motion.py TopFive
    python render_motion.py TopFive --props '{"title": "..."}'
    python render_motion.py --list

Exists so `content_plan.py --build` can schedule motion pieces the same way it
schedules board reels: one command per item, one folder for the output, and a
non-zero exit when something breaks. Without it the calendar would have half
its items runnable and half needing a different shell.

⚠️ Re-exports brand.json first. The Remotion side reads its colours, strings
and artwork from that file, so a config.py edit that is not exported is a
motion piece rendered with the previous brand — and nothing would fail.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REMOTION = ROOT / "remotion"
OUT = ROOT / "output" / "promo" / "motion"

# Kept in step with remotion/src/Root.tsx. Listed here so --list works and a
# typo is caught before Remotion spends a minute booting Chrome to say so.
COMPOSITIONS = [
    "KineticHook", "TopFive", "MythFact", "StatRise", "ThisOrThat",
    "OfflineFlex", "FeatureSpot", "ChatStory", "StreakCalendar", "QuoteCard",
    "RejectApprove", "Pov", "TierList", "TwoBeat", "BaitCard",
]


def render(comp: str, props: dict | None, out_dir: Path, log=print) -> int:
    out = out_dir / f"{comp}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["npx", "remotion", "render", comp, str(out.resolve())]
    if props:
        cmd += ["--props", json.dumps(props)]

    log(f"        render  {comp}")
    # shell=True on Windows: npx is a .cmd shim and is not directly executable.
    r = subprocess.run(cmd, cwd=REMOTION, shell=(sys.platform == "win32"),
                       capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-6:]
        log("        FAILED  " + " | ".join(tail))
        return r.returncode

    size = out.stat().st_size / 1e6 if out.is_file() else 0
    log(f"        OK      {out}  ({size:.1f} MB)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("composition", nargs="?")
    ap.add_argument("--props", help="JSON passed to the composition")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--all", action="store_true", help="render every composition")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--skip-export", action="store_true",
                    help="do not refresh brand.json first")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    if args.list:
        for c in COMPOSITIONS:
            print(c)
        return 0

    if not args.skip_export:
        subprocess.run([sys.executable, str(ROOT / "export_brand.py")],
                       cwd=ROOT, capture_output=True)

    todo = COMPOSITIONS if args.all else [args.composition]
    if not args.all:
        if not args.composition:
            ap.error("name a composition, or pass --all / --list")
        if args.composition not in COMPOSITIONS:
            ap.error(f"unknown composition {args.composition!r}; "
                     f"one of: {', '.join(COMPOSITIONS)}")

    props = json.loads(args.props) if args.props else None
    failed = sum(render(c, props, args.out) != 0 for c in todo)
    if failed:
        print(f"\n{failed} of {len(todo)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
