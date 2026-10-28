"""Task Scheduler entrypoint: polls the dashboard's control.json between the
six main publish.py runs (tahachesstv 15:00/23:00/05:00 PKT, tchessapp
17:00/01:00/07:00 PKT) so Emergency Controls (Pause/Resume, Run Next Now,
Retry Failed, Test Connections) take effect within minutes instead of waiting
for the next scheduled slot.

Usage:
    python watcher.py             # one tick: check control.json, act, refresh status.json
    python watcher.py --verbose

Runs on its own short-interval Task Scheduler trigger (e.g. every 5 minutes).
Every tick also refreshes status.json regardless of whether a command was
pending, so the dashboard's "last heartbeat" reflects real liveness.
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import config
from src import accounts
from src import autogen
from src import queue as ledger
from src import status_bridge

log = logging.getLogger("watcher")

RETRY_ALL_MAX = 5  # cap on "Retry Failed" expanding into individual --once runs


def setup_logging(verbose: bool):
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(console)


def _run_publish(*extra_args) -> int:
    cmd = [sys.executable, str(Path(__file__).resolve().parent / "publish.py"), *extra_args]
    log.info("running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                            creationflags=config.SUBPROCESS_NO_WINDOW)
    if result.stdout:
        log.info(result.stdout.strip())
    if result.stderr:
        log.warning(result.stderr.strip())
    return result.returncode


def _test_connections() -> dict:
    """Lightweight read-only reachability check, per brand. Never posts.

    Checked for every ENABLED brand rather than once globally: the two now
    have different Instagram ids and different YouTube tokens, so a single
    green tick would say nothing about whether the second brand can actually
    publish. Results stay flat-keyed ("instagram" for the default brand,
    "tchessapp.instagram" for the other) so the existing dashboard rows keep
    resolving while the new ones simply appear alongside.
    """
    import os
    import requests
    from src import publisher

    results = {}

    for name in accounts.enabled_names():
        prefix = "" if name == config.DEFAULT_ACCOUNT else f"{name}."
        ceiling = accounts.platform_ceiling(name)

        try:
            fb_token = publisher._fb_token(name)
        except Exception:  # noqa: BLE001
            fb_token = ""

        if "fb" in ceiling:
            fb_page_id = accounts.credential(name, "fb_page_id")
            try:
                r = requests.get(f"https://graph.facebook.com/{fb_page_id}",
                                 params={"fields": "id,name", "access_token": fb_token}, timeout=10)
                results[f"{prefix}facebook"] = r.status_code == 200
            except Exception:  # noqa: BLE001
                results[f"{prefix}facebook"] = False

        if "ig" in ceiling:
            try:
                ig_user_id = accounts.credential(name, "ig_user_id")
                r = requests.get(f"https://graph.facebook.com/{ig_user_id}",
                                 params={"fields": "id", "access_token": fb_token}, timeout=10)
                results[f"{prefix}instagram"] = r.status_code == 200
            except Exception:  # noqa: BLE001
                results[f"{prefix}instagram"] = False

        if "yt" in ceiling:
            try:
                # allow_interactive=False: a missing token must report False,
                # not open a browser consent window on an unattended machine.
                creds = publisher._youtube_credentials(name, allow_interactive=False)
                results[f"{prefix}youtube"] = bool(creds and creds.valid)
            except Exception:  # noqa: BLE001
                results[f"{prefix}youtube"] = False

    gh_token = os.environ.get("GITHUB_TOKEN", "")
    try:
        r = requests.get("https://api.github.com/repos/" + config.GITHUB_REPO,
                          headers={"Authorization": f"Bearer {gh_token}"}, timeout=10)
        results["github_cdn"] = r.status_code == 200
    except Exception:  # noqa: BLE001
        results["github_cdn"] = False

    results["github_status_bridge"] = status_bridge._enabled() and status_bridge._get_file("status.json")[0] is not None

    return results


def handle_command(control: dict):
    command = control.get("command")
    if not command:
        return

    ctype = command.get("type") if isinstance(command, dict) else command
    log.info("dashboard command received: %s", command)

    if ctype == "run_next_now":
        # The dashboard may name a brand; when it doesn't, publish.py infers
        # one from the clock, which is the right answer for a button pressed
        # near a slot and a harmless default otherwise.
        target = command.get("account") if isinstance(command, dict) else None
        if target:
            _run_publish("--account", target, "--verbose")
        else:
            _run_publish("--verbose")

    elif ctype == "retry":
        puzzle_id = command.get("puzzle_id") if isinstance(command, dict) else None
        if puzzle_id:
            _run_publish("--once", puzzle_id, "--verbose")
        else:
            log.warning("retry command missing puzzle_id, ignoring")

    elif ctype == "retry_all_failed":
        failed_ids = []
        for entry in ledger.pending():
            due = ledger.due_platforms(entry)
            # "Partially posted" is relative to the entry's OWN brand: a
            # tchessapp reel owes two platforms, a tahachesstv one owes three.
            # The old `len(due) < 3` test hardcoded the latter, which would
            # have quietly treated every untouched tchessapp entry (due = 2 of
            # 2) as a failed post and retried the entire backlog.
            total = len(ledger.active_platforms(accounts.entry_account(entry)))
            if due and len(due) < total:
                failed_ids.append(entry["puzzle_id"])
        for pid in failed_ids[:RETRY_ALL_MAX]:
            _run_publish("--once", pid, "--verbose")
        status_bridge.record_event("retry_all_failed", count=len(failed_ids[:RETRY_ALL_MAX]))

    elif ctype == "generate_now":
        # Build a reel without posting it, so the queue can be topped up ahead
        # of a slot rather than during one. publish.py generates on demand
        # anyway; this is for filling the buffer deliberately — before a busy
        # day, or after checking a format change — and for proving the
        # generator still works without waiting for a slot to prove it.
        spec = autogen.next_spec()
        if isinstance(command, dict) and command.get("variant"):
            spec = dict(spec, variant=command["variant"])
            if spec["variant"] == "promo_mate":
                spec["theme"] = None
        entry = autogen.generate_one(log, spec=spec)
        status_bridge.record_event(
            "generate_now",
            variant=spec["variant"],
            puzzle_id=(entry or {}).get("puzzle_id"),
            ok=bool(entry),
        )

    elif ctype == "test_connections":
        results = _test_connections()
        status_bridge.record_event("test_connections", results=results)
        log.info("test_connections: %s", results)

    else:
        log.warning("unknown command type: %s", ctype)

    status_bridge.clear_command(result=f"executed {ctype}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.verbose)

    if not status_bridge._enabled():
        log.info("status bridge not configured (GITHUB_STATUS_TOKEN/REPO missing) — nothing to poll")
        return 0

    control = status_bridge.get_control()
    try:
        handle_command(control)
    except Exception as exc:  # noqa: BLE001 — a bad command must not crash the heartbeat
        log.error("command handling failed: %s", exc)
        status_bridge.record_event("watcher_error", error=str(exc))

    status_bridge.sync_status(kind="heartbeat")
    status_bridge.sync_analytics()
    status_bridge.sync_account_stats()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
