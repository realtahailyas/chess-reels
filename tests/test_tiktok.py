"""TikTok (browser-published, tchessapp only): the rules that protect the shorts.

No browser is launched and nothing is posted. subprocess and the ledger are
mocked.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from src import accounts, queue as ledger, tiktok_browser  # noqa: E402


class Scope(unittest.TestCase):
    def test_only_tchessapp_can_post_to_tiktok(self):
        self.assertIn("tt", accounts.platform_ceiling("tchessapp"))
        self.assertNotIn("tt", accounts.platform_ceiling("tahachesstv"))
        self.assertEqual(accounts.handle("tchessapp", "tt"), "@wwwtchessapp")

    def test_flag_gates_tiktok(self):
        with mock.patch.object(config, "TIKTOK_ENABLED", False):
            self.assertNotIn("tt", ledger.active_platforms("tchessapp"))
        with mock.patch.object(config, "TIKTOK_ENABLED", True):
            self.assertIn("tt", ledger.active_platforms("tchessapp"))
            self.assertNotIn("tt", ledger.active_platforms("tahachesstv"))

    def test_dry_run_defaults_on(self):
        # A missing .env line must never become a live post.
        import importlib, os
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TIKTOK_DRY_RUN", None)
            fresh = importlib.reload(config)
            self.assertTrue(fresh.TIKTOK_DRY_RUN)
        importlib.reload(config)


class Profiles(unittest.TestCase):
    def test_refuses_the_facebook_and_jarvis_profiles(self):
        for other in (config.BROWSER_PROFILE_DIR or r"D:\x\profile_38", config.JARVIS_PROFILE_DIR):
            with mock.patch.object(config, "TIKTOK_PROFILE_DIR", other), \
                 mock.patch.object(config, "BROWSER_PROFILE_DIR", other if "38" in other else config.BROWSER_PROFILE_DIR), \
                 mock.patch("os.path.isdir", return_value=True), \
                 mock.patch("subprocess.run") as run:
                with self.assertRaises(tiktok_browser.TikTokBrowserError):
                    tiktok_browser.post_tiktok("v.mp4", "c", "tchessapp")
                run.assert_not_called()


class Results(unittest.TestCase):
    def _run(self, payload):
        proc = mock.Mock(stdout=json.dumps(payload) + "\n", stderr="", returncode=0)
        with mock.patch("subprocess.run", return_value=proc), \
             mock.patch("os.path.isdir", return_value=True), \
             mock.patch.object(config, "TIKTOK_PROFILE_DIR", r"C:\profiles\tiktok"):
            return tiktok_browser.post_tiktok("v.mp4", "caption", "tchessapp")

    def test_url_is_returned(self):
        self.assertEqual(self._run({"ok": True, "published": True, "postUrl": "https://www.tiktok.com/@x/video/1"}),
                         "https://www.tiktok.com/@x/video/1")

    def test_posted_without_url_is_a_sentinel_not_an_error(self):
        # An error here would leave "tt" due and the reel would be posted again.
        out = self._run({"ok": True, "published": True, "unconfirmed": True})
        self.assertTrue(out.startswith(config.TT_UNRESOLVED_PREFIX))

    def test_dry_run_is_an_error(self):
        with self.assertRaises(tiktok_browser.TikTokBrowserError):
            self._run({"ok": True, "published": False, "step": "dry-run-stop"})

    def test_timeout_is_a_sentinel_never_a_retry(self):
        import subprocess
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("node", 1)), \
             mock.patch("os.path.isdir", return_value=True), \
             mock.patch.object(config, "TIKTOK_PROFILE_DIR", r"C:\profiles\tiktok"):
            out = tiktok_browser.post_tiktok("v.mp4", "caption", "tchessapp")
        self.assertTrue(out.startswith(config.TT_UNRESOLVED_PREFIX + "timeout:"))


class FailureNeverBlocksTheShorts(unittest.TestCase):
    def test_a_tiktok_failure_completes_the_entry(self):
        """publish.py must mark "tt" on failure, so the entry is not the oldest
        pending reel at the next slot (which would then post nothing new on
        FB/IG/YT)."""
        import publish, tempfile
        video = Path(tempfile.mkdtemp()) / "video.mp4"
        video.write_bytes(b"\0")              # publish_one checks the file exists
        entry = {"puzzle_id": "P1", "account": "tchessapp", "status": "pending",
                 "video_path": str(video),
                 "platforms": {"fb": "1", "ig": "2", "yt": "3", "tt": None}}
        with mock.patch.object(publish, "load_meta", return_value={"caption": {}}), \
             mock.patch.object(publish, "compose_caption", return_value="c"), \
             mock.patch.object(publish.ledger, "due_platforms", return_value=["tt"]), \
             mock.patch.object(publish.tiktok_browser, "post_tiktok", side_effect=RuntimeError("boom")), \
             mock.patch.object(publish.tiktok_browser, "record_failure", return_value="tt-failed:x") as rec, \
             mock.patch.object(publish, "notify"), \
             mock.patch.object(publish.status_bridge, "record_event"), \
             mock.patch.object(publish, "is_structurally_publishable", return_value=True, create=True):
            publish.publish_one(entry, dry_run=False, account="tchessapp")
        rec.assert_called_once()
        self.assertEqual(rec.call_args[0][0], "P1")


if __name__ == "__main__":
    unittest.main()
