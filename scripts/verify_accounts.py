"""Read-only preflight: can each brand actually publish? Never posts anything.

    python scripts/verify_accounts.py                # every configured brand
    python scripts/verify_accounts.py tchessapp      # just one

Checks, per brand, the things that are silently wrong rather than loudly
wrong:

  - Instagram: is the account id set, reachable with this brand's token, and
    is it the username we think it is? An id that resolves to the *other*
    brand's account is the failure this catches — it would publish
    successfully, to the wrong audience.
  - YouTube: does a token exist, does it refresh without a browser, and which
    channel is it bound to? The consent screen's channel picker is a click
    that nothing downstream can second-guess, so it is verified here.
  - Facebook: only for brands that have a Page at all.

Exit code 0 means every checked brand is publishable. Anything else means do
not switch that brand on yet.
"""

import argparse
import sys
from pathlib import Path

# Windows' console codepage (cp1252) cannot encode the arrows and box glyphs
# this report uses, and an unencodable character here aborts the run midway
# through — hiding the very diagnosis it was printing. Same guard, same
# reason, as publish.py:setup_logging().
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import requests

import config
from src import accounts
from src import publisher

OK = "  [ OK ]"
BAD = "  [FAIL]"
WARN = "  [warn]"


def _graph(path, params, timeout=15):
    return requests.get(publisher._graph_url(path), params=params, timeout=timeout)


def check_instagram(name: str) -> bool:
    var = accounts.env_var(name, "ig_user_id")
    try:
        ig_id = accounts.credential(name, "ig_user_id")
    except accounts.MissingCredential as exc:
        print(f"{BAD} Instagram: {exc}")
        return False
    if not ig_id:
        print(f"{BAD} Instagram: {var} is empty")
        return False

    try:
        token = publisher._fb_token(name)
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} Instagram: no usable Meta token — {exc}")
        return False

    resp = _graph(ig_id, {"fields": "id,username,followers_count,media_count", "access_token": token})
    if resp.status_code != 200:
        detail = resp.text[:300]
        print(f"{BAD} Instagram: {ig_id} not reachable ({resp.status_code})")
        print(f"         {detail}")
        if "does not exist" in detail or "missing permissions" in detail:
            _diagnose_unreachable_ig(name, ig_id, token)
        return False

    body = resp.json()
    expected = (accounts.handle(name, "ig") or "").lstrip("@").lower()
    actual = (body.get("username") or "").lower()
    print(f"{OK} Instagram: @{body.get('username')} "
          f"({body.get('followers_count')} followers, {body.get('media_count')} posts)")
    if expected and actual and expected != actual:
        # The dangerous case: a perfectly valid id belonging to the other brand.
        print(f"{BAD}   → expected @{expected}, but {var} points at @{actual}")
        return False

    # Publishing permission is a separate grant from reading. Ask for the
    # publishing-limit edge, which only an account with content-publish access
    # can answer.
    limit = _graph(f"{ig_id}/content_publishing_limit", {"access_token": token})
    if limit.status_code != 200:
        print(f"{WARN}   content publishing not confirmed ({limit.status_code}): {limit.text[:200]}")
        print("         → reads work but publishing may not; check instagram_content_publish.")
        return False
    print(f"{OK}   content publishing authorised")
    return True


def _diagnose_unreachable_ig(name: str, ig_id: str, token: str):
    """Say WHICH of the two prerequisites is missing, not just "no access".

    🔴 THERE ARE TWO, AND ONLY ONE OF THEM IS OBVIOUS. Assigning the Instagram
    account to the System User in Business Manager — the thing everyone does
    first, and which the Business settings UI presents as the whole job — is
    NOT sufficient. graph.facebook.com can only resolve an `{ig-user-id}` node
    that is CONNECTED TO A FACEBOOK PAGE the token can act on; an Instagram
    account sitting in a Business portfolio with "Full access" and no linked
    Page is invisible to this API no matter how the token is scoped.
    (Confirmed the hard way on 2026-09-02: @tchessapp was assigned with Full
    access, the token was regenerated, and it still resolved to nothing — the
    Page link was the missing half.)

    So this walks the token's own Pages and reports exactly what it sees,
    because "not assigned" and "assigned but unlinked" need completely
    different fixes and look identical from the error message alone.
    """
    print("         Checking the two prerequisites separately...")
    resp = _graph("me/accounts", {
        "fields": "id,name,instagram_business_account{id,username}",
        "access_token": token, "limit": 100,
    })
    if resp.status_code != 200:
        print(f"         (could not list this token's Pages: {resp.text[:150]})")
        return

    pages = resp.json().get("data", [])
    linked = {
        (pg.get("instagram_business_account") or {}).get("id"): pg.get("name")
        for pg in pages if pg.get("instagram_business_account")
    }
    unlinked = [pg["name"] for pg in pages if not pg.get("instagram_business_account")]

    if ig_id in linked:
        print(f"         → the Page link exists ({linked[ig_id]}), so this is a permissions")
        print("           problem: check instagram_content_publish on the token.")
        return

    print(f"         → this token can act on {len(pages)} Page(s): "
          f"{', '.join(pg['name'] for pg in pages) or 'none'}")
    if unlinked:
        print(f"         → and {len(unlinked)} of them have NO Instagram account connected: "
              f"{', '.join(unlinked)}")
    print()
    print("         DIAGNOSIS: the Instagram account is not connected to a Facebook Page.")
    print("         Business Manager assignment alone is not enough — graph.facebook.com")
    print("         can only see an Instagram account through a Page it is linked to.")
    print()
    print("         FIX (from the Instagram app, signed in as this brand):")
    print("           Settings and privacy -> Account type and tools ->")
    print("           Sharing to other apps / Connect a Facebook Page -> pick the Page.")
    print("         Then re-run this script. No token change is needed.")


def check_youtube(name: str) -> bool:
    var = accounts.env_var(name, "yt_token_path")
    try:
        token_path = accounts.credential(name, "yt_token_path")
    except accounts.MissingCredential as exc:
        print(f"{BAD} YouTube: {exc}")
        return False
    if not token_path:
        print(f"{BAD} YouTube: {var} is empty")
        return False

    resolved = Path(token_path) if Path(token_path).is_absolute() else (ROOT / token_path)
    if not resolved.exists():
        print(f"{BAD} YouTube: no token at {resolved}")
        print(f"         → run: python scripts/yt_auth_account.py {name}")
        return False

    try:
        creds = publisher._youtube_credentials(name, allow_interactive=False)
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} YouTube: token unusable — {exc}")
        return False
    if not creds or not creds.valid:
        print(f"{BAD} YouTube: token did not refresh into a valid credential")
        return False

    try:
        channel = publisher.youtube_channel(name, creds=creds)
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} YouTube: could not read the bound channel — {exc}")
        return False

    print(f"{OK} YouTube: bound to {channel['title']!r} ({channel['id']})")

    pinned = accounts.credential(name, "yt_channel_id", default="")
    channel_var = accounts.env_var(name, "yt_channel_id")
    if pinned:
        if pinned != channel["id"]:
            print(f"{BAD}   → {channel_var} pins {pinned}; publishing will refuse to run")
            return False
        print(f"{OK}   matches {channel_var}")
    else:
        print(f"{WARN}   {channel_var} is not set — nothing would catch a re-consent")
        print(f"         binding this brand to the wrong channel. Add:")
        print(f"           {channel_var}={channel['id']}")

    expected = accounts.handle(name, "yt")
    if expected and expected.lower() not in (channel["title"] or "").lower():
        print(f"{WARN}   expected a channel named like {expected!r}")

    # Cross-check: two brands must never share one channel.
    return True


def check_facebook(name: str) -> bool:
    page_id = accounts.credential(name, "fb_page_id")
    if not page_id:
        print(f"{BAD} Facebook: FB_PAGE_ID is empty")
        return False
    try:
        token = publisher._fb_token(name)
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} Facebook: no usable token — {exc}")
        return False
    resp = _graph(page_id, {"fields": "id,name", "access_token": token})
    if resp.status_code != 200:
        print(f"{BAD} Facebook: page {page_id} not reachable ({resp.status_code}): {resp.text[:200]}")
        return False
    print(f"{OK} Facebook: {resp.json().get('name')}")
    if "fb" not in ledger_active(name):
        print(f"{WARN}   posting is switched off (FACEBOOK_ENABLED=0) — insights still update")
    return True


def ledger_active(name):
    from src import queue as ledger
    return ledger.active_platforms(name)


def verify(name: str) -> bool:
    ceiling = accounts.platform_ceiling(name)
    enabled = accounts.is_enabled(name)
    print()
    print("=" * 70)
    print(f"  {name}  ({accounts.label(name)})   "
          f"{'ENABLED' if enabled else 'not enabled yet'}")
    print(f"  slots: {', '.join(accounts.slots(name))} PKT   "
          f"platforms: {', '.join(ceiling)}")
    print("=" * 70)

    results = []
    if "fb" in ceiling:
        results.append(check_facebook(name))
    if "ig" in ceiling:
        results.append(check_instagram(name))
    if "yt" in ceiling:
        results.append(check_youtube(name))
    return all(results)


def cross_check() -> bool:
    """No two brands may resolve to the same Instagram id or YouTube channel.

    Everything above verifies one brand in isolation, and every single check
    would still pass if both brands were pointed at the same destination —
    which is the exact configuration that makes "never the same reel twice"
    meaningless, because both accounts would be one account.
    """
    print()
    print("=" * 70)
    print("  Cross-checks")
    print("=" * 70)
    ok = True

    seen_ig = {}
    for name in accounts.all_names():
        if "ig" not in accounts.platform_ceiling(name):
            continue
        try:
            ig_id = accounts.credential(name, "ig_user_id")
        except accounts.MissingCredential:
            continue
        if ig_id and ig_id in seen_ig:
            print(f"{BAD} {name} and {seen_ig[ig_id]} share Instagram id {ig_id}")
            ok = False
        elif ig_id:
            seen_ig[ig_id] = name
    if len(seen_ig) > 1:
        print(f"{OK} Instagram: {len(seen_ig)} distinct accounts")

    seen_yt = {}
    for name in accounts.all_names():
        if "yt" not in accounts.platform_ceiling(name):
            continue
        try:
            creds = publisher._youtube_credentials(name, allow_interactive=False)
            channel = publisher.youtube_channel(name, creds=creds)
        except Exception:  # noqa: BLE001 — already reported per-brand above
            continue
        cid = channel["id"]
        if cid in seen_yt:
            print(f"{BAD} {name} and {seen_yt[cid]} are bound to the SAME YouTube channel "
                  f"({channel['title']}) — re-run scripts/yt_auth_account.py and pick the other one")
            ok = False
        else:
            seen_yt[cid] = name
    if len(seen_yt) > 1:
        print(f"{OK} YouTube: {len(seen_yt)} distinct channels")

    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("account", nargs="?", choices=list(config.ACCOUNTS),
                    help="verify just this brand (default: all)")
    args = ap.parse_args(argv)

    names = [args.account] if args.account else list(config.ACCOUNTS)
    results = {name: verify(name) for name in names}
    if len(names) > 1:
        results["cross-checks"] = cross_check()

    print()
    print("=" * 70)
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("=" * 70)

    failed = [n for n, ok in results.items() if not ok]
    if failed:
        print()
        print(f"  Not ready: {', '.join(failed)}")
        print("  Leave TCHESSAPP_ENABLED unset until this passes — publishing")
        print("  with a broken credential fails against a real, public account.")
        return 1

    print()
    print("  All checked brands can publish.")
    if not accounts.is_enabled("tchessapp") and "tchessapp" in names:
        print("  Switch it on with TCHESSAPP_ENABLED=1 in .env, then register the")
        print("  new slots:  powershell -File scripts/setup_tchessapp_schedule.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
