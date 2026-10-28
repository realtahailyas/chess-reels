"""Verify a Chrome profile can publish, without touching either Page.

    python scripts/check_browser_profile.py                 # both brands
    python scripts/check_browser_profile.py tchessapp

Launches the profile, opens each brand's composer, confirms the Facebook
session is alive, confirms the composer landed on the right Page, and proves
Instagram can be deselected — then stops, before any upload. Nothing is
posted and nothing is left behind.

This is the check to run when a NEW profile is set up: every one of those four
things is a way a fresh profile can be wrong, and all four fail with the same
unhelpful selector timeout if you only find out mid-publish.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:  # noqa: BLE001
        pass

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import config


def probe(account: str) -> bool:
    profile = config.BROWSER_PROFILE_DIR
    print(f"\n=== {account} ===")
    print(f"  profile: {profile or '(CHROME_PROFILE_DIR not set)'}")
    if not profile:
        print("  [FAIL] CHROME_PROFILE_DIR is not set in .env")
        return False

    # This script LAUNCHES Chrome, so it needs the same refusal publisher.py
    # has: Jarvis posts its own Pages from its profile on its own schedule, and
    # one Chrome process per profile means probing there could take Jarvis's
    # next post down. A check that breaks the thing it is checking around is
    # not a check.
    if os.path.normcase(os.path.abspath(profile)) == os.path.normcase(os.path.abspath(config.JARVIS_PROFILE_DIR)):
        print(f"  [FAIL] this is the Jarvis profile ({config.JARVIS_PROFILE_DIR}).")
        print("         ChessReel needs its own — Chrome allows one process per profile,")
        print("         and sharing it would make the two projects break each other.")
        return False

    request = {
        "account": account,
        "probeOnly": True,
        "userDataDir": profile,
        "headless": config.BROWSER_HEADLESS,
        "screenshotDir": str(config.BROWSER_SHOT_DIR / "probe" / account),
        "timeoutMs": 120000,
    }
    proc = subprocess.run(
        [config.BROWSER_NODE, str(config.BROWSER_PUBLISHER_SCRIPT), json.dumps(request)],
        capture_output=True, text=True, timeout=300, cwd=str(ROOT),
        creationflags=config.SUBPROCESS_NO_WINDOW,
    )
    for line in (proc.stderr or "").strip().splitlines():
        print(f"    {line}")

    lines = (proc.stdout or "").strip().splitlines()
    try:
        result = json.loads(lines[-1])
    except (json.JSONDecodeError, IndexError):
        print(f"  [FAIL] unreadable output: {(proc.stdout or '')[:200]}")
        return False

    if result.get("ok"):
        print("  [ OK ] session valid, composer on the right Page, Instagram deselected")
        return True
    print(f"  [FAIL] {result.get('step')}: {result.get('error')}")
    for shot in result.get("screenshots", []):
        print(f"         screenshot: {shot}")
    return False


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    names = argv or [n for n in config.ACCOUNTS if "fb" in config.ACCOUNTS[n]["platforms"]]
    results = {n: probe(n) for n in names}
    print()
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("=" * 60)
    if all(results.values()):
        print("\n  Profile is ready. Next: python publish.py --account <name> --dry-run --verbose")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
