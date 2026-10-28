"""Tests for Facebook publishing through the browser composer.

Run: python -m unittest tests.test_fb_browser -v

Facebook is the one platform here that is not an API call — the Graph API's
Video Reels flow never worked for these Pages. That makes its failure modes
different from every other platform's, and worse: a browser run that is
reported wrongly can publish the same public reel twice. These tests pin the
decisions that prevent that.

Nothing here launches a browser or touches a real Page — the Node bridge is
stubbed at the subprocess boundary.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src import publisher


def _completed(stdout, returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestBrowserPublish(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict("os.environ", {
            "FB_PAGE_ID": "111", "FB_PAGE_TOKEN": "tok",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

        self.profile = mock.patch.object(config, "BROWSER_PROFILE_DIR", str(Path(__file__).parent))
        self.profile.start()
        self.addCleanup(self.profile.stop)

        self.live = mock.patch.object(config, "BROWSER_DRY_RUN", False)
        self.live.start()
        self.addCleanup(self.live.stop)

        # No test here may touch the network. Several of these exercise error
        # paths that still take the "what is the newest reel" snapshot first —
        # unmocked, that fired real Graph API calls with a dummy token on every
        # run: slow, noisy, and dependent on Meta being reachable for a test
        # that is really about parsing subprocess output. Individual cases
        # patch over this with their own before/after pair; the inner patch
        # wins and restores to this one.
        self.newest = mock.patch.object(publisher, "_newest_reel_id", return_value=None)
        self.newest.start()
        self.addCleanup(self.newest.stop)

    def _publish(self, stdout, before="old_reel", after="new_reel", **kw):
        with mock.patch.object(subprocess, "run", return_value=_completed(stdout)), \
             mock.patch.object(publisher, "_newest_reel_id", side_effect=[before, after]), \
             mock.patch("time.sleep"):
            return publisher.post_facebook("v.mp4", "caption", account="tahachesstv", **kw)

    def test_returns_the_recovered_reel_id(self):
        got = self._publish(json.dumps({"ok": True, "published": True, "step": "done"}))
        self.assertEqual(got, "new_reel")

    def test_a_failed_run_raises_with_the_step(self):
        out = json.dumps({"ok": False, "published": False, "step": "deselect-instagram",
                          "error": "still includes @tahachesstv"})
        with mock.patch.object(subprocess, "run", return_value=_completed(out, returncode=1)):
            with self.assertRaises(publisher.PublishError) as ctx:
                publisher.post_facebook("v.mp4", "caption", account="tahachesstv")
        self.assertIn("deselect-instagram", str(ctx.exception))

    def test_a_dry_run_is_never_reported_as_published(self):
        """dryRun walks the entire flow and stops. Returning a post id here
        would record a reel in the ledger that does not exist."""
        out = json.dumps({"ok": True, "published": False, "step": "dry-run-stop"})
        with mock.patch.object(subprocess, "run", return_value=_completed(out)):
            with self.assertRaises(publisher.PublishError) as ctx:
                publisher.post_facebook("v.mp4", "caption", account="tahachesstv")
        self.assertIn("DRY RUN", str(ctx.exception))

    def test_unparseable_output_raises_rather_than_guessing(self):
        with mock.patch.object(subprocess, "run", return_value=_completed("not json at all")):
            with self.assertRaises(publisher.PublishError):
                publisher.post_facebook("v.mp4", "caption", account="tahachesstv")

    def test_only_the_last_stdout_line_is_parsed(self):
        """Anything the bridge prints before its result must not break parsing —
        a parse failure on a SUCCESSFUL post would be retried and publish the
        reel twice."""
        out = "some stray line\n" + json.dumps({"ok": True, "published": True, "step": "done"})
        got = self._publish(out)
        self.assertEqual(got, "new_reel")

    def test_an_unrecoverable_id_becomes_a_sentinel_not_an_error(self):
        """🔴 The reel is live. Raising would leave the entry pending and the
        next run would post it to the same Page again."""
        out = json.dumps({"ok": True, "published": True, "step": "done"})
        with mock.patch.object(subprocess, "run", return_value=_completed(out)), \
             mock.patch.object(publisher, "_newest_reel_id", return_value="same_id"), \
             mock.patch("time.sleep"):
            got = publisher.post_facebook("v.mp4", "caption", account="tahachesstv")
        self.assertTrue(got.startswith(config.FB_UNRESOLVED_PREFIX))

    def test_a_timeout_says_the_reel_may_be_live(self):
        """Playwright may have clicked Share before this process gave up. The
        error has to stop somebody blindly retrying."""
        with mock.patch.object(subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(cmd="node", timeout=1)):
            with self.assertRaises(publisher.PublishError) as ctx:
                publisher.post_facebook("v.mp4", "caption", account="tahachesstv")
        self.assertIn("may already be live", str(ctx.exception))

    def test_an_account_without_a_page_is_refused(self):
        no_fb = dict(config.ACCOUNTS["tahachesstv"], platforms=("ig", "yt"))
        with mock.patch.dict(config.ACCOUNTS, {"nofb": no_fb}, clear=False):
            with self.assertRaises(publisher.PublishError) as ctx:
                publisher.post_facebook("v.mp4", "caption", account="nofb")
        self.assertIn("no Facebook Page", str(ctx.exception))

    def test_a_missing_chrome_profile_is_refused_before_launching(self):
        with mock.patch.object(config, "BROWSER_PROFILE_DIR", ""):
            with self.assertRaises(publisher.PublishError) as ctx:
                publisher.post_facebook("v.mp4", "caption", account="tahachesstv")
        self.assertIn("CHROME_PROFILE_DIR", str(ctx.exception))

    def test_crossposting_is_never_requested(self):
        """Instagram is published by the Graph API, which returns the media id
        that insights and the pinned comment need. A crosspost from the
        composer would add a second, id-less copy to a live account."""
        captured = {}

        def fake_run(cmd, **kw):
            captured["request"] = json.loads(cmd[2])
            return _completed(json.dumps({"ok": True, "published": True, "step": "done"}))

        with mock.patch.object(subprocess, "run", side_effect=fake_run), \
             mock.patch.object(publisher, "_newest_reel_id", side_effect=["a", "b"]), \
             mock.patch("time.sleep"):
            publisher.post_facebook("v.mp4", "caption", account="tahachesstv", title="T")

        self.assertEqual(captured["request"]["account"], "tahachesstv")
        self.assertFalse(captured["request"]["dryRun"])
        self.assertEqual(captured["request"]["title"], "T")


class TestSentinelHandling(unittest.TestCase):
    """A sentinel id must be inert everywhere it flows, not just at creation."""

    def test_analytics_skips_a_sentinel_instead_of_erroring_forever(self):
        from src import analytics

        entry = {
            "puzzle_id": "x", "account": "tahachesstv", "created_at": "2026-09-01T00:00:00Z",
            "platforms": {"fb": config.FB_UNRESOLVED_PREFIX + "2026-09-02T12:00:00Z"},
        }
        with mock.patch.object(analytics, "fetch_facebook") as fetch:
            out = analytics.fetch_for_entry(entry)
        fetch.assert_not_called()
        self.assertIn("not recovered", out["facebook"]["error"])

    def test_a_real_id_is_still_fetched(self):
        from src import analytics

        entry = {
            "puzzle_id": "x", "account": "tahachesstv", "created_at": "2026-09-01T00:00:00Z",
            "platforms": {"fb": "1798207428203527"},
        }
        with mock.patch.object(analytics, "fetch_facebook", return_value={"ok": 1}) as fetch:
            out = analytics.fetch_for_entry(entry)
        fetch.assert_called_once()
        self.assertEqual(out["facebook"], {"ok": 1})


if __name__ == "__main__":
    unittest.main()
