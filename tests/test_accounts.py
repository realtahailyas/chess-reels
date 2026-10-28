"""Tests for the two-brand publishing split (src/accounts.py, the ledger's
account stamping, and publish.py's content runway).

Run: python -m unittest tests.test_accounts -v

The property most of these defend is a single sentence: THE SAME REEL IS
NEVER PUBLISHED BY BOTH BRANDS. Everything else here is in service of that or
of not breaking @tahachesstv, which was publishing long before a second
account existed.
"""

import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import publish
from src import accounts
from src import queue as ledger


def _puzzle(pid):
    return {"id": pid, "rating": 1500, "theme_label": "Sacrifice"}


# A brand with no Facebook Page, pinned here rather than borrowed from a real
# account. These tests defend "platforms are resolved per account"; they used
# to assert that on @tchessapp, which had no Page — for exactly one day, until
# it got one (2026-09-02) and five tests failed over a fact about the world
# rather than about the code.
IG_YT_ONLY = {
    "label": "IG/YT Only Brand",
    "handles": {"ig": "@igytonly", "yt": "IG YT Only"},
    "platforms": ("ig", "yt"),
    "publish_times_pkt": ["09:00", "13:00"],
    "env": {
        "fb_token": "FB_PAGE_TOKEN",
        "ig_user_id": "IG_USER_ID_IGYTONLY",
        "yt_token_path": "YT_TOKEN_PATH_IGYTONLY",
        "yt_channel_id": "YT_CHANNEL_ID_IGYTONLY",
    },
}


def with_ig_yt_brand():
    """Context manager adding the no-Facebook brand to the account registry."""
    return mock.patch.dict(config.ACCOUNTS, {"igytonly": IG_YT_ONLY}, clear=False)


class TestAccountResolution(unittest.TestCase):
    def test_unknown_account_raises(self):
        with self.assertRaises(accounts.UnknownAccount):
            accounts.get("not-a-brand")

    def test_default_account_is_tahachesstv(self):
        """The brand that was publishing before this feature existed must stay
        the default, or every un-migrated call site changes destination."""
        self.assertEqual(config.DEFAULT_ACCOUNT, "tahachesstv")
        self.assertIs(accounts.get(None), config.ACCOUNTS["tahachesstv"])

    def test_entry_without_account_is_the_default_brand(self):
        """300+ historical entries have no `account` key. They are all
        tahachesstv's, and guessing any other way would misattribute every
        reel ever posted."""
        self.assertEqual(accounts.entry_account({}), "tahachesstv")
        self.assertEqual(accounts.entry_account({"account": None}), "tahachesstv")
        self.assertEqual(accounts.entry_account({"account": "tchessapp"}), "tchessapp")

    def test_the_two_brands_have_different_slots(self):
        tv = set(accounts.slots("tahachesstv"))
        app = set(accounts.slots("tchessapp"))
        self.assertEqual(tv & app, set(), "the brands must never post at the same time")

    def test_platform_ceiling_is_per_account(self):
        """An account can only have the platforms its own config lists."""
        with with_ig_yt_brand():
            self.assertNotIn("fb", accounts.platform_ceiling("igytonly"))
            self.assertEqual(accounts.platform_ceiling("igytonly"), ("ig", "yt"))
        self.assertIn("fb", accounts.platform_ceiling("tahachesstv"))


class TestCredentialIsolation(unittest.TestCase):
    """A credential that identifies a DESTINATION must never fall back to the
    other brand's — that failure publishes successfully to the wrong audience,
    which nothing downstream can undo."""

    def test_ig_user_id_never_falls_back(self):
        with mock.patch.dict("os.environ", {"IG_USER_ID": "tv-ig", "IG_USER_ID_TCHESSAPP": ""}, clear=False):
            with self.assertRaises(accounts.MissingCredential):
                accounts.credential("tchessapp", "ig_user_id")

    def test_yt_token_path_never_falls_back(self):
        with mock.patch.dict("os.environ", {"YT_TOKEN_PATH": "tv.json", "YT_TOKEN_PATH_TCHESSAPP": ""}, clear=False):
            with self.assertRaises(accounts.MissingCredential):
                accounts.credential("tchessapp", "yt_token_path")

    def test_yt_channel_id_is_absent_rather_than_inherited(self):
        """Pinning is an assertion about one channel. Inheriting the default
        brand's pin would make every one of the other brand's uploads fail the
        very guard the pin exists to power."""
        with mock.patch.dict("os.environ", {"YT_CHANNEL_ID": "UC-tv", "YT_CHANNEL_ID_TCHESSAPP": ""}, clear=False):
            self.assertEqual(accounts.credential("tchessapp", "yt_channel_id", default=""), "")

    def test_shared_meta_token_does_fall_back(self):
        """One System User token legitimately covers both brands, so this one
        is allowed to fall back — that is what makes the override optional."""
        with mock.patch.dict("os.environ", {"FB_PAGE_TOKEN": "shared", "FB_PAGE_TOKEN_TCHESSAPP": ""}, clear=False):
            self.assertEqual(accounts.credential("tchessapp", "fb_token"), "shared")


class TestClockInference(unittest.TestCase):
    def setUp(self):
        self._patch = mock.patch.dict(
            config.ACCOUNT_ENABLED, {"tahachesstv": True, "tchessapp": True}, clear=False)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_each_slot_infers_its_own_brand(self):
        for hour, expected in [(15, "tahachesstv"), (23, "tahachesstv"), (5, "tahachesstv"),
                               (17, "tchessapp"), (1, "tchessapp"), (7, "tchessapp")]:
            with self.subTest(hour=hour):
                got = accounts.infer_from_clock(datetime(2026, 9, 2, hour, 2))
                self.assertEqual(got, expected)

    def test_midnight_wrap_is_circular(self):
        """00:30 is 30 minutes from the 01:00 slot, not 23.5 hours from it."""
        self.assertEqual(accounts.infer_from_clock(datetime(2026, 9, 2, 0, 30)), "tchessapp")

    def test_far_from_any_slot_returns_none(self):
        self.assertIsNone(accounts.infer_from_clock(datetime(2026, 9, 2, 11, 0)))

    def test_disabled_brand_is_never_inferred(self):
        with mock.patch.dict(config.ACCOUNT_ENABLED, {"tchessapp": False}, clear=False):
            self.assertIsNone(accounts.infer_from_clock(datetime(2026, 9, 2, 17, 2)))


class TestLedgerStamping(unittest.TestCase):
    """The stamp IS the uniqueness guarantee."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "posted.json"
        for pid in ("p1", "p2", "p3"):
            ledger.record_success(_puzzle(pid), f"{pid}.mp4", "c.txt", 15.0, path=self.path)

    def test_assign_stamps_the_entry(self):
        self.assertTrue(ledger.assign_account("p1", "tchessapp", path=self.path))
        entry = next(e for e in ledger.load(self.path)["pending"] if e["puzzle_id"] == "p1")
        self.assertEqual(entry["account"], "tchessapp")
        self.assertIn("assigned_at", entry)

    def test_reassigning_to_the_other_brand_is_refused(self):
        """Re-stamping is the single operation that could hand one reel to
        both brands, so it fails rather than overwriting."""
        ledger.assign_account("p1", "tchessapp", path=self.path)
        self.assertFalse(ledger.assign_account("p1", "tahachesstv", path=self.path))
        entry = next(e for e in ledger.load(self.path)["pending"] if e["puzzle_id"] == "p1")
        self.assertEqual(entry["account"], "tchessapp")

    def test_reassigning_to_the_same_brand_is_idempotent(self):
        ledger.assign_account("p1", "tchessapp", path=self.path)
        self.assertTrue(ledger.assign_account("p1", "tchessapp", path=self.path))

    def test_pending_excludes_the_other_brands_entries(self):
        ledger.assign_account("p1", "tchessapp", path=self.path)
        tv_ids = [e["puzzle_id"] for e in ledger.pending(path=self.path, account="tahachesstv")]
        app_ids = [e["puzzle_id"] for e in ledger.pending(path=self.path, account="tchessapp")]
        self.assertNotIn("p1", tv_ids)
        self.assertIn("p1", app_ids)
        # The unstamped pool is visible to both until one of them claims it.
        self.assertIn("p2", tv_ids)
        self.assertIn("p2", app_ids)

    def test_pending_without_account_is_unchanged(self):
        """The historical no-argument meaning still returns everything — the
        dashboard's backlog count and watcher's retry sweep rely on it."""
        self.assertEqual(len(ledger.pending(path=self.path)), 3)

    def test_two_brands_claiming_in_turn_never_collide(self):
        """The property, end to end: alternate claims, no reel twice."""
        claimed = {}
        for brand in ("tahachesstv", "tchessapp", "tahachesstv", "tchessapp"):
            available = ledger.pending(path=self.path, account=brand)
            unclaimed = [e for e in available if not e.get("account")]
            if not unclaimed:
                break
            pid = unclaimed[0]["puzzle_id"]
            self.assertNotIn(pid, claimed, f"{pid} was handed out twice")
            ledger.assign_account(pid, brand, path=self.path)
            claimed[pid] = brand
        self.assertEqual(len(claimed), 3)
        self.assertEqual(len(set(claimed)), 3)


class TestPerAccountCompletion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "posted.json"

    def test_entry_completes_on_its_own_accounts_platforms(self):
        """The bug this guards: completion measured against a global platform
        list leaves a two-platform brand's entries permanently one 'fb' short
        of done, so they never get posted_at and never get analytics."""
        with with_ig_yt_brand():
            ledger.record_success(_puzzle("a1"), "a1.mp4", "c.txt", 15.0, path=self.path)
            ledger.assign_account("a1", "igytonly", path=self.path)

            ledger.mark_platform("a1", "ig", "ig_1", path=self.path)
            entry = ledger.load(self.path)["pending"][0]
            self.assertEqual(entry["status"], "pending")

            ledger.mark_platform("a1", "yt", "yt_1", path=self.path)
            entry = ledger.load(self.path)["pending"][0]
            self.assertEqual(entry["status"], "posted")
            self.assertIn("posted_at", entry)

    def test_a_three_platform_brand_still_needs_all_three(self):
        """The mirror case, so the fix above cannot regress into 'two is
        always enough'."""
        ledger.record_success(_puzzle("b1"), "b1.mp4", "c.txt", 15.0, path=self.path)
        ledger.assign_account("b1", "tahachesstv", path=self.path)
        with mock.patch.object(config, "FACEBOOK_ENABLED", True):
            ledger.mark_platform("b1", "ig", "ig_1", path=self.path)
            ledger.mark_platform("b1", "yt", "yt_1", path=self.path)
            self.assertEqual(ledger.load(self.path)["pending"][0]["status"], "pending")
            ledger.mark_platform("b1", "fb", "fb_1", path=self.path)
            self.assertEqual(ledger.load(self.path)["pending"][0]["status"], "posted")

    def test_due_platforms_follows_the_entrys_own_brand(self):
        with with_ig_yt_brand():
            self.assertEqual(
                ledger.due_platforms({"account": "igytonly", "platforms": {"ig": None, "yt": None}}),
                ["ig", "yt"])
            self.assertNotIn(
                "fb", ledger.due_platforms({"account": "igytonly", "platforms": {}}))

    def test_a_global_flag_cannot_invent_a_platform_an_account_lacks(self):
        """FACEBOOK_ENABLED can only ever REMOVE fb from an account that has a
        Page; it must never add one to an account that does not."""
        with with_ig_yt_brand(), mock.patch.object(config, "FACEBOOK_ENABLED", True):
            self.assertNotIn("fb", ledger.active_platforms("igytonly"))
            self.assertIn("fb", ledger.active_platforms("tahachesstv"))
        with mock.patch.object(config, "FACEBOOK_ENABLED", False):
            self.assertNotIn("fb", ledger.active_platforms("tahachesstv"))


class TestContentRunway(unittest.TestCase):
    def _runway_with(self, total, unassigned=None, enabled=("tahachesstv", "tchessapp")):
        entries = []
        for i in range(total):
            entries.append({"puzzle_id": f"x{i}", "video_path": "v.mp4", "status": "pending"})
        if unassigned is not None:
            for entry in entries[unassigned:]:
                entry["account"] = "tahachesstv"
        enabled_map = {n: (n in enabled) for n in config.ACCOUNTS}
        with mock.patch.object(ledger, "pending", return_value=entries), \
             mock.patch.object(publish, "is_eligible", return_value=True), \
             mock.patch.dict(config.ACCOUNT_ENABLED, enabled_map, clear=False):
            return publish.content_runway(cutoff="2000-01-01T00:00:00Z")

    def test_levels(self):
        self.assertEqual(self._runway_with(0)["level"], "exhausted")
        self.assertEqual(self._runway_with(config.CONTENT_CRITICAL_WATERMARK)["level"], "critical")
        self.assertEqual(self._runway_with(config.CONTENT_LOW_WATERMARK)["level"], "low")
        self.assertEqual(self._runway_with(config.CONTENT_LOW_WATERMARK + 1)["level"], "ok")

    def test_burn_rate_is_derived_from_the_enabled_schedule(self):
        """Not a hardcoded 6: pausing a brand has to move the estimate, or the
        dashboard quotes a cadence nobody runs."""
        both = self._runway_with(30)
        self.assertEqual(both["daily_burn"], 6)
        self.assertEqual(both["days_left"], 5.0)

        one = self._runway_with(30, enabled=("tahachesstv",))
        self.assertEqual(one["daily_burn"], 3)
        self.assertEqual(one["days_left"], 10.0)

    def test_counts_split_assigned_and_unassigned(self):
        runway = self._runway_with(10, unassigned=4)
        self.assertEqual(runway["total"], 10)
        self.assertEqual(runway["unassigned"], 4)
        self.assertEqual(runway["by_account"]["tahachesstv"], 6)
        self.assertEqual(runway["by_account"]["tchessapp"], 0)


class TestRunOutBehaviour(unittest.TestCase):
    """When the built backlog empties, the pipeline STOPS and says why. It
    must never start generating — the owner rewires the generator first."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.marker = Path(self.tmp.name) / "content_level.txt"
        patch = mock.patch.object(config, "CONTENT_LEVEL_MARKER", self.marker)
        patch.start()
        self.addCleanup(patch.stop)

    def _runway(self, level, total=0):
        return {"total": total, "unassigned": 0, "by_account": {"tahachesstv": 0, "tchessapp": 0},
                "daily_burn": 6, "days_left": 0.0, "level": level}

    def test_a_level_is_announced_once_not_every_run(self):
        """Six runs a day against a shrinking backlog would otherwise fire six
        identical warnings a day — which is how a warning gets ignored right
        before it matters."""
        with mock.patch.object(publish, "notify") as notify,              mock.patch.object(publish.status_bridge, "record_event"):
            publish._announce_runway(self._runway("low", total=12))
            publish._announce_runway(self._runway("low", total=11))
            publish._announce_runway(self._runway("low", total=10))
            self.assertEqual(notify.call_count, 1)

    def test_crossing_into_a_new_level_announces_again(self):
        with mock.patch.object(publish, "notify") as notify,              mock.patch.object(publish.status_bridge, "record_event"):
            publish._announce_runway(self._runway("low", total=12))
            publish._announce_runway(self._runway("critical", total=6))
            publish._announce_runway(self._runway("exhausted", total=0))
            self.assertEqual(notify.call_count, 3)

    def test_healthy_level_is_never_announced(self):
        with mock.patch.object(publish, "notify") as notify,              mock.patch.object(publish.status_bridge, "record_event"):
            publish._announce_runway(self._runway("ok", total=100))
            notify.assert_not_called()

    def test_exhaustion_pauses_the_autopilot(self):
        with mock.patch.object(publish.status_bridge, "is_paused", return_value=False),              mock.patch.object(publish.status_bridge, "pause_for_content_exhaustion",
                               return_value=True) as pause:
            publish._stop_if_exhausted(self._runway("exhausted"))
            pause.assert_called_once()

    def test_a_healthy_backlog_never_pauses(self):
        with mock.patch.object(publish.status_bridge, "is_paused", return_value=False),              mock.patch.object(publish.status_bridge, "pause_for_content_exhaustion") as pause:
            publish._stop_if_exhausted(self._runway("low", total=10))
            publish._stop_if_exhausted(self._runway("critical", total=3))
            pause.assert_not_called()

    def test_an_already_paused_autopilot_is_not_re_paused(self):
        """Re-pausing would overwrite a human's pause reason with ours."""
        with mock.patch.object(publish.status_bridge, "is_paused", return_value=True),              mock.patch.object(publish.status_bridge, "pause_for_content_exhaustion") as pause:
            publish._stop_if_exhausted(self._runway("exhausted"))
            pause.assert_not_called()

    def test_autopause_can_be_switched_off(self):
        with mock.patch.object(config, "CONTENT_EXHAUSTED_AUTOPAUSE", False),              mock.patch.object(publish.status_bridge, "is_paused", return_value=False),              mock.patch.object(publish.status_bridge, "pause_for_content_exhaustion") as pause:
            publish._stop_if_exhausted(self._runway("exhausted"))
            pause.assert_not_called()


class TestDrainingTheQueueDoesNotPause(unittest.TestCase):
    """A run that posts its LAST reel must not stop the autopilot.

    🔴 THIS IS A REGRESSION TEST FOR A LIVE OUTAGE. On 2026-09-08 the 23:00 run
    posted davJ8 to Facebook, Instagram and YouTube, comments and all — and then
    reached the end of _run(), saw the queue it had just emptied, and paused
    itself. Every slot after it skipped on "paused" until a human noticed.

    The bug was not in _stop_if_exhausted, which is why the six tests above it
    all passed: that function did exactly what it says. The bug was WHERE it was
    called from. So this test drives _run() end to end rather than the helper,
    because the helper was never the thing that was broken.

    Draining to zero is the normal steady state now — publish.py builds a reel
    when its queue is empty (src/autogen.py), so an empty queue means the buffer
    did its job, not that content ran out.
    """

    def _args(self):
        return types.SimpleNamespace(account="tahachesstv", once=None,
                                     dry_run=False, verbose=False)

    def test_posting_the_last_eligible_reel_leaves_the_autopilot_running(self):
        entry = {"puzzle_id": "davJ8", "status": "pending",
                 "video_path": str(config.ROOT / "output" / "promo" / "mate"
                                   / "0022_davJ8" / "video.mp4"),
                 "created_at": "2999-01-01T00:00:00Z",
                 "account": "tahachesstv"}
        exhausted = {"level": "exhausted", "total": 0, "unassigned": 0,
                     "by_account": {}, "days_left": 0.0, "daily_burn": 6}

        with mock.patch.object(publish, "resolve_account", return_value="tahachesstv"),              mock.patch.object(publish.ledger, "pending", return_value=[entry]),              mock.patch.object(publish, "get_or_init_cutoff", return_value="2000-01-01T00:00:00Z"),              mock.patch.object(publish, "is_eligible", return_value=True),              mock.patch.object(publish, "publish_one", return_value=True) as posted,              mock.patch.object(publish, "content_runway", return_value=exhausted),              mock.patch.object(publish, "_announce_runway"),              mock.patch.object(publish.status_bridge, "is_paused", return_value=False),              mock.patch.object(publish.status_bridge, "record_event"),              mock.patch.object(publish.status_bridge, "pause_for_content_exhaustion") as pause:
            rc = publish._run(self._args())

        self.assertEqual(rc, 0)
        posted.assert_called_once()
        pause.assert_not_called()

    def test_a_run_that_cannot_generate_anything_still_pauses(self):
        """The autopause is not gone — it just means a real fault now."""
        exhausted = {"level": "exhausted", "total": 0, "unassigned": 0,
                     "by_account": {}, "days_left": 0.0, "daily_burn": 6}

        with mock.patch.object(publish, "resolve_account", return_value="tahachesstv"),              mock.patch.object(publish.ledger, "pending", return_value=[]),              mock.patch.object(publish, "get_or_init_cutoff", return_value="2000-01-01T00:00:00Z"),              mock.patch.object(config, "AUTOGEN_ENABLED", True),              mock.patch.object(publish.autogen, "generate_until_eligible", return_value=None),              mock.patch.object(publish, "content_runway", return_value=exhausted),              mock.patch.object(publish, "_announce_runway"),              mock.patch.object(publish.status_bridge, "is_paused", return_value=False),              mock.patch.object(publish.status_bridge, "record_event"),              mock.patch.object(publish, "_stop_if_exhausted") as stop:
            rc = publish._run(self._args())

        self.assertEqual(rc, 1)
        stop.assert_called_once()

    def test_an_empty_queue_generates_instead_of_stopping(self):
        built = {"puzzle_id": "NEW01", "status": "pending",
                 "video_path": str(config.ROOT / "output" / "promo" / "sac"
                                   / "0019_NEW01" / "video.mp4"),
                 "created_at": "2999-01-01T00:00:00Z",
                 "account": "tahachesstv"}
        calls = {"n": 0}

        def pending(*a, **kw):
            # empty on the first look, then holding what autogen just built
            calls["n"] += 1
            return [] if calls["n"] <= 2 else [built]

        with mock.patch.object(publish, "resolve_account", return_value="tahachesstv"),              mock.patch.object(publish.ledger, "pending", side_effect=pending),              mock.patch.object(publish, "get_or_init_cutoff", return_value="2000-01-01T00:00:00Z"),              mock.patch.object(publish, "is_eligible", return_value=True),              mock.patch.object(config, "AUTOGEN_ENABLED", True),              mock.patch.object(publish.autogen, "generate_until_eligible",
                               return_value=built) as gen,              mock.patch.object(publish, "publish_one", return_value=True) as posted,              mock.patch.object(publish, "content_runway",
                               return_value={"level": "exhausted", "total": 0,
                                             "unassigned": 0, "by_account": {},
                                             "days_left": 0.0, "daily_burn": 6}),              mock.patch.object(publish, "_announce_runway"),              mock.patch.object(publish.status_bridge, "is_paused", return_value=False),              mock.patch.object(publish.status_bridge, "record_event"),              mock.patch.object(publish.status_bridge, "pause_for_content_exhaustion") as pause:
            rc = publish._run(self._args())

        self.assertEqual(rc, 0)
        gen.assert_called_once()
        posted.assert_called_once()
        pause.assert_not_called()

    def test_a_queue_of_only_retries_still_publishes_a_fresh_reel(self):
        """2026-10-16..20: the oldest reel owed only Facebook, which kept
        failing, and every slot retried just that — nothing new went out on
        IG / YouTube / TikTok for four days."""
        stuck = {"puzzle_id": "OLD01", "status": "pending", "account": "tahachesstv",
                 "video_path": "x.mp4", "created_at": "2999-01-01T00:00:00Z",
                 "platforms": {"fb": None, "ig": "ig_1", "yt": "yt_1"}}
        built = {"puzzle_id": "NEW01", "status": "pending", "account": None,
                 "video_path": "y.mp4", "created_at": "2999-01-01T00:00:00Z"}
        calls = {"n": 0}

        def pending(*a, **kw):
            calls["n"] += 1
            return [stuck] if calls["n"] <= 2 else [stuck, built]

        with mock.patch.object(publish, "resolve_account", return_value="tahachesstv"), \
             mock.patch.object(config, "FACEBOOK_ENABLED", True), \
             mock.patch.object(publish.ledger, "pending", side_effect=pending), \
             mock.patch.object(publish.ledger, "assign_account", return_value=True), \
             mock.patch.object(publish, "is_structurally_publishable", return_value=True), \
             mock.patch.object(publish, "get_or_init_cutoff", return_value="2000-01-01T00:00:00Z"), \
             mock.patch.object(publish, "is_eligible", return_value=True), \
             mock.patch.object(config, "AUTOGEN_ENABLED", True), \
             mock.patch.object(publish.autogen, "generate_until_eligible",
                               return_value=built) as gen, \
             mock.patch.object(publish, "publish_one", return_value=True) as posted, \
             mock.patch.object(publish, "content_runway", return_value={
                 "level": "ok", "total": 1, "unassigned": 0, "by_account": {},
                 "days_left": 1.0, "daily_burn": 6}), \
             mock.patch.object(publish, "_announce_runway"), \
             mock.patch.object(publish.status_bridge, "is_paused", return_value=False), \
             mock.patch.object(publish.status_bridge, "record_event"):
            rc = publish._run(self._args())

        self.assertEqual(rc, 0)
        gen.assert_called_once()
        self.assertEqual([c.args[0]["puzzle_id"] for c in posted.call_args_list],
                         ["OLD01", "NEW01"])


class TestManualOnceStamps(unittest.TestCase):
    """`--once` has to claim an unstamped reel too, or the manual door
    reintroduces the duplicate the scheduled path prevents."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "posted.json"
        ledger.record_success(_puzzle("legacy"), "legacy.mp4", "c.txt", 15.0, path=self.path)

    def _run_once(self, account, dry_run=False):
        args = mock.Mock(once="legacy", dry_run=dry_run, account=account)
        # Bind the real implementations first — a side_effect that called the
        # patched name would recurse into itself.
        real_assign = ledger.assign_account
        real_load = ledger.load
        with mock.patch.object(ledger, "pending",
                               side_effect=lambda *a, **k: real_load(self.path)["pending"]),              mock.patch.object(ledger, "assign_account",
                               side_effect=lambda pid, acct, path=None:
                                   real_assign(pid, acct, path=self.path)),              mock.patch.object(publish, "publish_one", return_value=True),              mock.patch.object(publish, "resolve_account", return_value=account):
            publish._run(args)
        return real_load(self.path)["pending"][0]

    def test_once_claims_an_unstamped_entry(self):
        entry = self._run_once("tchessapp")
        self.assertEqual(entry["account"], "tchessapp")

    def test_dry_run_once_claims_nothing(self):
        entry = self._run_once("tchessapp", dry_run=True)
        self.assertIsNone(entry.get("account"))


class TestAFullDayOfRuns(unittest.TestCase):
    """End to end: six runs alternating brands must consume six DIFFERENT
    reels. This is the behaviour the whole feature is for, exercised through
    publish._run rather than through the ledger helpers directly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "posted.json"
        self.videos = []
        for i in range(8):
            # Real files, so is_structurally_publishable() passes for them.
            folder = Path(self.tmp.name) / f"r{i}"
            folder.mkdir()
            video = folder / "video.mp4"
            video.write_bytes(b"x")
            (folder / "meta.json").write_text('{"caption": {}}', encoding="utf-8")
            self.videos.append(video)
            ledger.record_success(_puzzle(f"r{i}"), video, "c.txt", 15.0, path=self.path)

    def test_six_alternating_runs_never_repeat_a_reel(self):
        real_load, real_assign = ledger.load, ledger.assign_account
        real_mark = ledger.mark_platform
        posted = []

        def fake_publish_one(entry, dry_run, account=None):
            posted.append((account, entry["puzzle_id"]))
            # A real publish marks every due platform, which flips the entry
            # out of `pending`. Without that the next run for the SAME brand
            # correctly picks its own claimed reel up again to finish it — the
            # partial-failure retry path — and the test would be measuring
            # that instead of the day's rotation.
            for p in ledger.active_platforms(account):
                real_mark(entry["puzzle_id"], p, f"{p}_id", path=self.path)
            return True

        order = ["tahachesstv", "tchessapp"] * 3
        with mock.patch.object(ledger, "pending",
                               side_effect=lambda path=None, account=None, include_unassigned=True: [
                                   e for e in real_load(self.path)["pending"]
                                   if e.get("status") == "pending"
                                   and (account is None
                                        or e.get("account") == account
                                        or (e.get("account") is None and include_unassigned))
                               ]),              mock.patch.object(ledger, "assign_account",
                               side_effect=lambda pid, acct, path=None: real_assign(pid, acct, path=self.path)),              mock.patch.object(publish, "is_eligible", return_value=True),              mock.patch.object(publish, "get_or_init_cutoff", return_value="2000-01-01T00:00:00Z"),              mock.patch.object(publish, "publish_one", side_effect=fake_publish_one),              mock.patch.object(publish, "_announce_runway"),              mock.patch.object(publish, "_stop_if_exhausted"):
            for brand in order:
                args = mock.Mock(once=None, dry_run=False, account=brand)
                with mock.patch.object(publish, "resolve_account", return_value=brand):
                    publish._run(args)

        self.assertEqual(len(posted), 6)
        ids = [pid for _, pid in posted]
        self.assertEqual(len(set(ids)), 6, f"a reel was published twice: {ids}")
        self.assertEqual([acct for acct, _ in posted], order)

        # And every consumed reel now carries the stamp of the brand that took it.
        stamps = {e["puzzle_id"]: e.get("account") for e in real_load(self.path)["pending"]}
        for account, pid in posted:
            self.assertEqual(stamps[pid], account)

    def test_a_half_posted_reel_is_retried_only_by_its_own_brand(self):
        """Claimed but not finished: the owning brand picks it back up on its
        next run, and the other brand still cannot see it. A partial failure
        must not leak a reel into the shared pool."""
        real_load, real_assign = ledger.load, ledger.assign_account
        real_mark = ledger.mark_platform

        real_assign("r0", "tchessapp", path=self.path)
        real_mark("r0", "ig", "ig_1", path=self.path)   # IG landed, the rest did not
        entry = next(e for e in real_load(self.path)["pending"] if e["puzzle_id"] == "r0")
        self.assertEqual(entry["status"], "pending")
        # Whatever tchessapp's line-up is today, IG is done and the others are not.
        due = ledger.due_platforms(entry)
        self.assertNotIn("ig", due)
        self.assertIn("yt", due)

        def visible(account):
            return [e["puzzle_id"] for e in real_load(self.path)["pending"]
                    if e.get("status") == "pending"
                    and (e.get("account") == account or e.get("account") is None)]

        self.assertIn("r0", visible("tchessapp"))
        self.assertNotIn("r0", visible("tahachesstv"))


class TestStructuralCheckBeforeStamping(unittest.TestCase):
    """A reel is checked before it is stamped: a broken file must not be
    permanently consumed from the shared pool by whichever brand saw it
    first."""

    def test_missing_file_is_not_publishable(self):
        self.assertFalse(publish.is_structurally_publishable(
            {"video_path": str(Path(tempfile.gettempdir()) / "nope-does-not-exist.mp4")}))

    def test_non_mp4_is_not_publishable(self):
        self.assertFalse(publish.is_structurally_publishable({"video_path": "cover.png"}))


if __name__ == "__main__":
    unittest.main()
