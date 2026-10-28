"""Build a reel on demand, at publish time, instead of drawing from a backlog.

WHY THIS EXISTS. The pipeline used to run in two disconnected halves: somebody
ran run_batch.py to build a pile of reels, and publish.py posted one per slot
until the pile was gone. On 2026-09-07 the pile ran out and the autopilot did
exactly what it was told to do — it stopped — and then posted nothing for a day
and a half. A backlog is a buffer that has to be refilled by hand, and nobody
refills a buffer they cannot see emptying.

So the queue is now the fallback, not the source: publish.py asks for content,
and if none is waiting it builds one and posts that.

WHAT STOPS IT REPEATING ITSELF. Nothing here tracks "what did I post last" —
uniqueness is structural and lives one layer down. puzzles.select() is handed
`exclude=ledger.posted_ids()`, so a puzzle that has ever been used cannot come
back, whatever this module asks for. The rotation below is about VARIETY (not
three sacrifice reels in a row), not about correctness.

WHAT IT WILL AND WILL NOT BUILD. AUTO_VARIANTS is deliberately short. These are
the three formats that have been built, watched end to end and signed off. The
motion/meme compositions, the carousel and gm_games are all still scheduled by
content_plan.py for a human to build — an autopilot that posts to two live
accounts should only ever reach for formats somebody has actually looked at.
"""

import subprocess
import sys
from pathlib import Path

import config
from src import queue as ledger

ROOT = Path(__file__).resolve().parent.parent

# 🔴 REVIEWED FORMATS ONLY. Adding a name here puts it in front of real
# followers unattended, so build one by hand and watch it first.
AUTO_VARIANTS = ["promo_guess", "promo_sac", "promo_mate"]

# Same two axes content_plan.py rotates, for the same reason: a month of one
# motif reads as a bot, and a month of one rating band reads as either showing
# off or beginner content. Kept as its own copy rather than imported, because
# content_plan's list is a 30-day human schedule and this is a per-post picker —
# they can drift apart without either being wrong.
THEME_CYCLE = [
    "fork", "pin", "backRankMate", "skewer", "discoveredAttack",
    "deflection", "smotheredMate", "attraction",
    "doubleCheck", "clearance", "mateIn3", "sacrifice", "endgame",
]
BANDS = [
    ("club", 1400, 1900),
    ("sharp", 1900, 2600),
    ("beginner", 800, 1400),
]


def _counter() -> int:
    """A number that goes up by one per reel ever made.

    Using the ledger's own size rather than a date or a slot index means the
    rotation advances per POST, not per day — two reels built in the same hour
    (a catch-up, a manual top-up) still differ from each other, and a day with
    no posts does not silently skip a motif.
    """
    return len(ledger.load().get("posted", []))


def _variant_history() -> dict:
    """Newest timestamp per AUTO_VARIANT, read back out of the ledger.

    The variant is recovered from the video's own path (output/promo/<subdir>/)
    rather than from meta.json, because the path is already in the ledger entry
    and meta.json would mean a file read per entry.
    """
    sub2var = {config.variant(v)["output_subdir"]: v for v in AUTO_VARIANTS}
    newest = {}
    for entry in ledger.load().get("pending", []):
        path = Path(entry.get("video_path", "")).as_posix()
        when = entry.get("posted_at") or entry.get("created_at") or ""
        for sub, var in sub2var.items():
            if f"/output/{sub}/" in path:
                if when > newest.get(var, ""):
                    newest[var] = when
                break
    return newest


def least_recent_variant() -> str:
    """The format that has gone the longest without being made.

    🔴 THIS REPLACES A BLIND COUNTER, AND THE LEDGER SAYS WHY. The first
    version indexed AUTO_VARIANTS by len(posted), which looks like a rotation
    and is not one: that number counts every build the project has ever made,
    including carousels, tours, gm_games and test renders, so which variant it
    lands on is unrelated to what actually went out. Measured on 2026-09-08 the
    last eight board reels were mate, guess, mate, mate, guess, mate, guess,
    mate — no promo_sac at all, for days.

    Asking the ledger instead makes "one of each, spread out" true by
    construction: whatever was posted least recently is what gets built next,
    so no format can go missing however the slots fall.
    """
    newest = _variant_history()
    # A variant that has never been built sorts first — "" is below any stamp.
    return min(AUTO_VARIANTS, key=lambda v: (newest.get(v, ""), v))


def next_spec(n: int = None, variant: str = None) -> dict:
    """What to build next: variant, motif and rating band."""
    n = _counter() if n is None else n
    variant = variant or least_recent_variant()

    # 🔴 THE BAND IS OFFSET, AND WITHOUT THE OFFSET THIS IS BROKEN. There are
    # three variants and three bands, so indexing both on n straight makes the
    # pairing constant: promo_mate would be a beginner reel forever, promo_sac a
    # 1900+ reel forever. Adding n // len(AUTO_VARIANTS) advances the band once
    # per full pass through the variants, so each format walks all three.
    # THEME_CYCLE needs no such fix — 13 is coprime with 3.
    band, lo, hi = BANDS[(n + n // len(AUTO_VARIANTS)) % len(BANDS)]
    theme = THEME_CYCLE[n % len(THEME_CYCLE)]

    # promo_mate carries its own theme filter (mateIn2). Overriding it with
    # "fork" produces a mate reel that is not a mate — content_plan.py has the
    # same carve-out and for the same reason.
    if variant == "promo_mate":
        theme = None

    return {"variant": variant, "theme": theme, "band": band,
            "rating": [lo, hi], "n": n}


def command(spec: dict) -> list:
    """The run_batch.py argv for a spec."""
    argv = [sys.executable, str(ROOT / "run_batch.py"),
            "--variant", spec["variant"], "--count", "1"]
    if spec["theme"]:
        argv += ["--theme", spec["theme"]]
    if spec["rating"]:
        argv += ["--rating-min", str(spec["rating"][0]),
                 "--rating-max", str(spec["rating"][1])]
    return argv


def generate_one(log, spec: dict = None, timeout: float = None) -> dict | None:
    """Build one reel and return its new pending ledger entry, or None.

    Never raises. A generator that throws inside the publish run would take the
    whole slot down with it, and a slot that posts nothing is strictly better
    than a slot that crashes before it can report why.

    The new entry is identified by DIFFING the ledger rather than by parsing
    run_batch's stdout: the build writes the entry itself (queue.record_success)
    and its own log format is not an interface.
    """
    spec = spec or next_spec()
    timeout = timeout or config.AUTOGEN_TIMEOUT

    before = {e["puzzle_id"] for e in ledger.pending()}
    argv = command(spec)
    log.info("autogen: building %s (%s, %s) — %s",
             spec["variant"], spec["theme"] or "any motif", spec["band"],
             " ".join(argv[1:]))

    try:
        proc = subprocess.run(argv, cwd=str(ROOT), capture_output=True,
                              text=True, timeout=timeout,
                              creationflags=config.SUBPROCESS_NO_WINDOW)
    except subprocess.TimeoutExpired:
        log.error("autogen: build timed out after %.0fs", timeout)
        return None
    except OSError as exc:
        log.error("autogen: could not start the build: %s", exc)
        return None

    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-6:]
        log.error("autogen: build failed (exit %d): %s",
                  proc.returncode, " / ".join(tail))
        return None

    fresh = [e for e in ledger.pending() if e["puzzle_id"] not in before]
    if not fresh:
        # run_batch exits 0 when it selects nothing — an over-narrow theme plus
        # rating band, or a corpus exhausted for that combination.
        log.warning("autogen: build reported success but queued nothing "
                    "(no puzzle matched %s / %s?)",
                    spec["theme"] or "any motif", spec["band"])
        return None

    entry = fresh[0]
    log.info("autogen: built %s -> %s", entry["puzzle_id"], entry["video_path"])
    return entry


def generate_until_eligible(log, is_eligible, cutoff, attempts: int = None):
    """Build until something publishable exists, or the attempts run out.

    A single failure is usually a too-narrow motif/band pair rather than a
    broken pipeline, and the next spec in the rotation asks for a different
    pair — so retrying is worth doing, and worth capping.
    """
    attempts = attempts or config.AUTOGEN_MAX_ATTEMPTS
    n = _counter()
    # Pick the format ONCE. Re-deriving it per attempt would let a build that
    # succeeded but was rejected shift the slot onto a different format, which
    # is how one variant quietly stops appearing.
    variant = least_recent_variant()
    for i in range(attempts):
        entry = generate_one(log, spec=next_spec(n + i, variant=variant))
        if entry and is_eligible(entry, cutoff):
            return entry
        if entry:
            log.warning("autogen: %s built but is not publishable, retrying",
                        entry["puzzle_id"])
    log.error("autogen: gave up after %d attempt(s)", attempts)
    return None
