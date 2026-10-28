"""One-time YouTube consent for one brand, writing that brand's own token file.

    python scripts/yt_auth_account.py tchessapp
    python scripts/yt_auth_account.py tchessapp --force   # overwrite an existing token

🔴 WHY THIS EXISTS AT ALL. Taha Chess TV and TChess App are two channels
behind the same Google login, and a YouTube OAuth credential is bound to
whichever channel is picked in the consent screen's channel chooser —
videos.insert has no parameter that can override it afterwards. So a second
channel needs a second token file, minted by a second consent, and the ONLY
moment the choice is made is the channel picker in the browser. This script
exists to make that moment deliberate: it says which brand it is minting for
before opening the browser, and prints the channel it actually bound to
afterwards, so a misclick is caught here rather than discovered later as the
app brand's reels sitting on Taha Chess TV.

The browser step needs a desktop session — run it by hand, not from Task
Scheduler.
"""

import argparse
import os
import sys
from pathlib import Path

# Windows' console codepage (cp1252) cannot encode the emoji in this script's
# warnings, and an unencodable character aborts the run — after the token has
# already been written, so it reads as a failure when it is not. Same guard,
# same reason, as publish.py:setup_logging().
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import config
from src import accounts
from src import publisher


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("account", choices=list(config.ACCOUNTS), help="which brand to mint a token for")
    ap.add_argument("--force", action="store_true", help="overwrite an existing token file")
    ap.add_argument("--yes", action="store_true",
                    help="skip the Enter prompt (for driving the consent from an automated browser)")
    args = ap.parse_args(argv)

    account = args.account
    token_var = accounts.env_var(account, "yt_token_path")
    token_path = os.environ.get(token_var, "").strip()

    if not token_path:
        print(f"ERROR: {token_var} is not set in .env — add it first, e.g.")
        print(f"       {token_var}=./data/youtube_token_{account}.json")
        return 2

    resolved = (ROOT / token_path).resolve() if not os.path.isabs(token_path) else Path(token_path)

    # A brand's live token is the only thing standing between an unattended
    # run and a consent prompt it cannot answer. Never replace one silently.
    if resolved.exists() and not args.force:
        print(f"A token already exists for {account!r}:")
        print(f"  {resolved}")
        print()
        print("Nothing was changed. Re-run with --force only if you intend to replace it,")
        print("and be aware that the running autopilot uses this file.")
        return 1

    other = [n for n in config.ACCOUNTS if n != account]
    print("=" * 70)
    print(f"  Minting a YouTube token for: {account}  ({accounts.label(account)})")
    print("=" * 70)
    print()
    print("  A browser window is about to open. In it:")
    print("    1. Sign in with the Google account that owns both channels.")
    print(f"    2. On the 'Choose an account / channel' screen, pick:  {accounts.handle(account, 'yt') or account}")
    if other:
        print(f"       NOT {', '.join(accounts.handle(n, 'yt') or n for n in other)}.")
    print("    3. Approve the requested YouTube permissions.")
    print()
    print("  The channel you pick here is the channel this brand will upload to")
    print("  forever after. This script prints what you picked when it finishes.")
    print()
    if args.yes:
        print("  --yes given: opening the consent flow now.")
    else:
        input("  Press Enter to open the browser... ")

    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists():
        backup = resolved.with_suffix(resolved.suffix + ".bak")
        backup.write_bytes(resolved.read_bytes())
        print(f"  (previous token backed up to {backup.name})")
        resolved.unlink()

    try:
        creds = publisher._youtube_credentials(account, allow_interactive=True)
    except Exception as exc:  # noqa: BLE001 — a failed consent is a normal outcome to report
        print(f"\nERROR: consent failed: {exc}")
        return 1

    try:
        channel = publisher.youtube_channel(account, creds=creds)
    except Exception as exc:  # noqa: BLE001
        print(f"\nToken written to {resolved}, but the channel could not be read back: {exc}")
        return 1

    print()
    print("=" * 70)
    print(f"  Token written: {resolved}")
    print(f"  Bound to channel: {channel['title']}")
    print(f"  Channel id:       {channel['id']}")
    print("=" * 70)
    print()

    channel_var = accounts.env_var(account, "yt_channel_id")
    pinned = os.environ.get(channel_var, "").strip()
    if pinned and pinned != channel["id"]:
        print(f"  ⚠️  {channel_var} in .env pins {pinned}, which is NOT this channel.")
        print("     Publishing will refuse to run until they agree. If you picked the")
        print("     right channel just now, update .env; if not, re-run with --force.")
        return 1
    if not pinned:
        print("  Add this line to .env so a future re-consent cannot silently")
        print("  bind this brand to the wrong channel:")
        print()
        print(f"      {channel_var}={channel['id']}")
        print()

    if channel["title"] and accounts.handle(account, "yt"):
        expected = accounts.handle(account, "yt")
        if expected.lower() not in channel["title"].lower():
            print(f"  ⚠️  Expected something like {expected!r} but got {channel['title']!r}.")
            print("     If that is the wrong channel, re-run with --force and pick again.")
            return 1

    print("  Looks right. Next: python scripts/verify_accounts.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
