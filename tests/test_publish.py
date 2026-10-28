"""Tests for the publishing layer (publish.py, src/queue.py's platform tracking).

Run: python -m unittest tests.test_publish -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from src import queue as ledger

import publish


class TestPlatformTracking(unittest.TestCase):
    """A partial failure must not re-post to platforms that already succeeded."""

    def test_mark_platform_flips_status_only_once_all_three_are_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "posted.json"
            puzzle = {"id": "p1", "rating": 1500, "theme_label": "Sacrifice"}
            ledger.record_success(puzzle, "v.mp4", "c.txt", 15.0, path=path)

            ledger.mark_platform("p1", "fb", "fb_123", path=path)
            entry = ledger.load(path)["pending"][0]
            self.assertEqual(entry["platforms"]["fb"], "fb_123")
            self.assertIsNone(entry["platforms"]["ig"])
            self.assertEqual(entry["status"], "pending")

            ledger.mark_platform("p1", "ig", "ig_456", path=path)
            ledger.mark_platform("p1", "yt", "yt_789", path=path)
            entry = ledger.load(path)["pending"][0]
            self.assertEqual(entry["status"], "posted")

    def test_a_platform_that_keeps_failing_is_skipped_after_the_limit(self):
        """One stuck platform must not hold the queue (Facebook, 2026-10-16..20)."""
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(config, "PLATFORM_MAX_FAILURES", 3), \
                mock.patch.object(config, "FACEBOOK_ENABLED", True):
            path = Path(tmp) / "posted.json"
            ledger.record_success({"id": "p1"}, "v.mp4", "c.txt", 15.0, path=path)
            ledger.assign_account("p1", "tahachesstv", path=path)
            ledger.mark_platform("p1", "ig", "ig_1", path=path)
            ledger.mark_platform("p1", "yt", "yt_1", path=path)

            self.assertIsNone(ledger.record_platform_failure("p1", "fb", path=path))
            self.assertIsNone(ledger.record_platform_failure("p1", "fb", path=path))
            entry = ledger.load(path)["pending"][0]
            self.assertEqual(entry["status"], "pending")
            self.assertEqual(ledger.due_platforms(entry), ["fb"])

            mark = ledger.record_platform_failure("p1", "fb", path=path)
            self.assertTrue(mark.startswith(config.PUBLISH_SKIPPED_PREFIX))
            entry = ledger.load(path)["pending"][0]
            self.assertEqual(entry["status"], "posted")
            self.assertEqual(ledger.due_platforms(entry), [])

            from src import status_bridge
            self.assertEqual(status_bridge.platforms_of(entry), {"ig", "yt"})

    def test_due_platforms(self):
        entry = {"platforms": {"fb": "x", "ig": None, "yt": None}}
        self.assertEqual(ledger.due_platforms(entry), ["ig", "yt"])

    def test_due_platforms_defaults_when_missing(self):
        self.assertEqual(ledger.due_platforms({}), ["fb", "ig", "yt"])


class TestEligibility(unittest.TestCase):
    """The ledger's `pending` list is every build ever recorded, not a clean
    publish queue — is_eligible() is what keeps autopilot off the historical
    backlog and off the in-app-feed content."""

    def _entry(self, video_path, created_at):
        return {"puzzle_id": "x", "video_path": str(video_path), "created_at": created_at}

    def test_app_feed_is_never_eligible(self):
        video_path = config.ROOT / "output" / "app" / "0001_x" / "video.mp4"
        entry = self._entry(video_path, "2099-01-01T00:00:00Z")
        self.assertFalse(publish.is_eligible(entry, cutoff="2000-01-01T00:00:00Z"))

    def test_outside_project_is_never_eligible(self):
        entry = self._entry(Path(tempfile.gettempdir()) / "video.mp4", "2099-01-01T00:00:00Z")
        self.assertFalse(publish.is_eligible(entry, cutoff="2000-01-01T00:00:00Z"))

    def test_before_cutoff_is_not_eligible(self):
        video_path = config.ROOT / "output" / "gm_games" / "0001_x" / "video.mp4"
        entry = self._entry(video_path, "2020-01-01T00:00:00Z")
        self.assertFalse(publish.is_eligible(entry, cutoff="2099-01-01T00:00:00Z"))

    def test_after_cutoff_is_eligible(self):
        video_path = config.ROOT / "output" / "gm_games" / "0001_x" / "video.mp4"
        entry = self._entry(video_path, "2099-01-01T00:00:00Z")
        self.assertTrue(publish.is_eligible(entry, cutoff="2000-01-01T00:00:00Z"))

    def test_posted_marker_folder_is_never_eligible(self):
        # The user's own manual convention: moving an item into a _posted/
        # subfolder means "already shared, don't touch again."
        video_path = config.ROOT / "output" / "promo" / "sac" / "_posted" / "0001_x" / "video.mp4"
        entry = self._entry(video_path, "2099-01-01T00:00:00Z")
        self.assertFalse(publish.is_eligible(entry, cutoff="2000-01-01T00:00:00Z"))

    def test_promo_is_eligible_even_before_cutoff(self):
        # output/promo/ is the user's own curated backlog, not dev/test
        # debris — exempt from the cutoff so autopilot works through it.
        video_path = config.ROOT / "output" / "promo" / "sac" / "0001_x" / "video.mp4"
        entry = self._entry(video_path, "2000-01-01T00:00:00Z")
        self.assertTrue(publish.is_eligible(entry, cutoff="2099-01-01T00:00:00Z"))


class TestCaption(unittest.TestCase):
    def test_compose_caption_joins_body_hashtags(self):
        # 2026-08-26: the on-screen `hook` is no longer prepended — the
        # caption body already opens with its own hook line, and doubling
        # it up was part of why FB/IG posts read as bloated.
        meta = {"caption": {"hook": "Hook.", "caption": "Body.", "hashtags": ["#a", "#b"]}}
        text = publish.compose_caption(meta)
        self.assertEqual(text, "Body.\n\n#a #b")

    def test_compose_caption_tolerates_missing_fields(self):
        self.assertEqual(publish.compose_caption({}), "")

    def test_compose_youtube_description_uses_dedicated_field(self):
        meta = {"caption": {"caption": "FB body.", "youtube_description": "YT body.",
                             "hashtags": ["#a", "#b"]}}
        text = publish.compose_youtube_description(meta)
        self.assertEqual(text, "YT body.\n\n#a #b")

    def test_compose_youtube_description_falls_back_to_caption(self):
        # Content built before 2026-08-26 has no youtube_description.
        meta = {"caption": {"caption": "FB body.", "hashtags": ["#a", "#b"]}}
        text = publish.compose_youtube_description(meta)
        self.assertEqual(text, "FB body.\n\n#a #b")


if __name__ == "__main__":
    unittest.main()
