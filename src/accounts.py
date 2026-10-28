"""Which brand a reel is published as, and where that brand's credentials live.

Two accounts share this one pipeline (see config.ACCOUNTS): the original
`tahachesstv` and the app's own `tchessapp`. They share everything about the
*content* — caption engine, hashtags, YouTube title shape, pinned first
comment, the burnt-in watermark — and differ only in destination credentials
and posting hours.

This module is the single place that turns an account name into real
credentials, so no caller ever reads FB_PAGE_TOKEN / IG_USER_ID /
YT_TOKEN_PATH directly and quietly posts to the wrong brand.

🔴 THE DEFAULT ACCOUNT MUST STAY A NO-OP. Every function here resolves
`tahachesstv` to exactly the unprefixed environment variables that were in
use before a second account existed, and every account-taking parameter in
this codebase defaults to config.DEFAULT_ACCOUNT. Adding the second brand had
to be invisible to the first one, which has been publishing since day one.
"""

from datetime import datetime

import config


class UnknownAccount(KeyError):
    pass


def get(name: str = None) -> dict:
    name = name or config.DEFAULT_ACCOUNT
    try:
        return config.ACCOUNTS[name]
    except KeyError:
        raise UnknownAccount(f"no such account: {name!r} (known: {', '.join(config.ACCOUNTS)})") from None


def exists(name: str) -> bool:
    return name in config.ACCOUNTS


def label(name: str = None) -> str:
    return get(name).get("label", name or config.DEFAULT_ACCOUNT)


def handle(name: str, platform: str) -> str:
    return get(name).get("handles", {}).get(platform, "")


def all_names() -> tuple:
    """Every configured account, enabled or not — for status/reporting."""
    return tuple(config.ACCOUNTS)


def enabled_names() -> tuple:
    """The accounts a run is allowed to publish to, in config order.

    A disabled account is still a real account everywhere else: its already
    posted entries keep their stamp, keep their analytics, and keep showing on
    the dashboard. Disabling only stops new posts.
    """
    return tuple(n for n in config.ACCOUNTS if config.ACCOUNT_ENABLED.get(n))


def is_enabled(name: str) -> bool:
    return bool(config.ACCOUNT_ENABLED.get(name))


def platform_ceiling(name: str = None) -> tuple:
    """Platforms this brand could ever post to — before FACEBOOK_ENABLED /
    TIKTOK_ENABLED are applied. src/queue.py:active_platforms() is what
    callers should ask; this is the input to it."""
    return tuple(get(name).get("platforms", ()))


def slots(name: str = None) -> list:
    """This account's daily publish times, "HH:MM" in PKT, chronologically."""
    return sorted(get(name).get("publish_times_pkt", []))


def env_var(name: str, key: str) -> str:
    """The environment variable NAME holding one credential for one account."""
    return get(name).get("env", {}).get(key, "")


def credential(name: str, key: str, default: str = "") -> str:
    """Resolve one credential for one account, from the real environment.

    Falls back to the default account's variable when the account declares a
    variable that is not set. That fallback is what lets @tchessapp reuse the
    one System User token covering both brands in the Taha Pages portfolio
    (FB_PAGE_TOKEN_TCHESSAPP unset → FB_PAGE_TOKEN) without a code change if a
    separate token is ever issued.

    ⚠️ NOT every credential may fall back. Two groups are excluded, for two
    different reasons — see _NEVER_FALL_BACK and _NO_FALLBACK below.
    """
    import os

    var = env_var(name, key)
    value = os.environ.get(var, "").strip() if var else ""
    if value:
        return value

    if key in _NEVER_FALL_BACK:
        raise MissingCredential(
            f"{var or key} is not set for account {name!r} — refusing to fall back to "
            f"{config.DEFAULT_ACCOUNT}'s {key}, which would publish to the wrong brand. "
            f"Run: python scripts/verify_accounts.py"
        )

    if key in _NO_FALLBACK:
        return default

    fallback_var = env_var(config.DEFAULT_ACCOUNT, key)
    if fallback_var:
        value = os.environ.get(fallback_var, "").strip()
    return value or default


# Credentials that identify a DESTINATION rather than authorise one. A wrong
# token fails loudly with a permissions error; a wrong destination succeeds
# and posts to the other brand's audience, which nothing downstream can undo.
# Unset means stop, not "use the other brand's".
_NEVER_FALL_BACK = frozenset({"ig_user_id", "yt_token_path"})

# Credentials that are an ASSERTION about one account, meaningless for any
# other, and optional. Unset means "this account pins nothing", so these
# return the caller's default rather than raising — inheriting the default
# brand's expected YouTube channel id would make every one of the other
# brand's uploads fail the guard that variable exists to power.
_NO_FALLBACK = frozenset({"yt_channel_id"})


class MissingCredential(RuntimeError):
    pass


def infer_from_clock(now: datetime = None, tolerance_min: int = None) -> str:
    """Which account's slot is closest to `now`, or None if none is close.

    A fallback only — the scheduled tasks pass `--account` explicitly and that
    always wins. This exists so a manual `python publish.py` at 17:05, or a
    "Run Next Now" from the dashboard, does the obviously-intended thing
    instead of always falling to the default brand.

    Returns None rather than guessing when nothing is within tolerance, so the
    caller can decide (publish.py falls back to the default account and says
    so in the log).
    """
    now = now or datetime.now()
    tolerance = config.ACCOUNT_SLOT_TOLERANCE_MIN if tolerance_min is None else tolerance_min
    minutes_now = now.hour * 60 + now.minute

    best, best_delta = None, None
    for name in enabled_names():
        for slot in slots(name):
            hh, mm = slot.split(":")
            minutes_slot = int(hh) * 60 + int(mm)
            # Circular distance — 00:30 is 60 minutes from 23:30, not 1380.
            delta = abs(minutes_now - minutes_slot)
            delta = min(delta, 1440 - delta)
            if best_delta is None or delta < best_delta:
                best, best_delta = name, delta

    if best_delta is not None and best_delta <= tolerance:
        return best
    return None


def entry_account(entry: dict) -> str:
    """The account a ledger entry belongs to.

    An entry with no `account` key predates the second brand and is, by
    definition, tahachesstv's — every reel ever posted before this existed
    went there. Never guess any other way: this is what keeps 300+ historical
    entries correctly attributed without a migration.
    """
    return entry.get("account") or config.DEFAULT_ACCOUNT
