import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import status_bridge as bridge


def entry(views, stamp="2026-10-02T10:00:00Z"):
    return {"fetched_at": stamp, "posted_at": "2026-09-01T10:00:00Z",
            "metrics": {"youtube": {"views": views}}}


class RetentionTests(unittest.TestCase):
    def test_unavailable_read_never_writes_or_fetches(self):
        with patch.object(bridge, "_enabled", return_value=True), patch.object(bridge, "_get_file", return_value=(None, None)), patch.object(bridge, "_save_analytics") as save, patch.object(bridge.ledger, "load") as load:
            bridge.sync_analytics()
            save.assert_not_called()
            load.assert_not_called()

    def test_failure_keeps_counts_and_success_timestamp_without_secrets(self):
        result = bridge._merge_analytics_entry(entry(4200), {
            "fetched_at": "2026-10-02T11:00:00Z", "metrics": {
                "youtube": {"error": "URL contains access_token=secret"}}})
        self.assertEqual(result["metrics"]["youtube"]["views"], 4200)
        self.assertEqual(result["metrics"]["youtube"]["last_success_at"], "2026-10-02T10:00:00Z")
        self.assertIn("refresh_error", result["metrics"]["youtube"])
        self.assertNotIn("secret", json.dumps(result))

    def test_successful_correction_is_accepted_and_clears_failure(self):
        old = entry(4200)
        old["metrics"]["youtube"]["refresh_error"] = "failed"
        result = bridge._merge_analytics_entry(old, entry(4100, "2026-10-02T11:00:00Z"))
        self.assertEqual(result["metrics"]["youtube"]["views"], 4100)
        self.assertNotIn("refresh_error", result["metrics"]["youtube"])

    def test_older_batch_does_not_overwrite_newer_platform(self):
        result = bridge._merge_analytics_entry(entry(4500, "2026-10-02T12:00:00Z"), entry(4200))
        self.assertEqual(result["metrics"]["youtube"]["views"], 4500)

    def test_conflict_refetches_and_preserves_other_writer_rows(self):
        first = {"old": entry(100)}
        second = {**first, "concurrent": entry(200)}
        responses = [Mock(status_code=409), Mock(status_code=200)]
        with tempfile.TemporaryDirectory() as directory, patch.object(bridge.config, "DATA_DIR", Path(directory)), patch.object(bridge, "_get_file", side_effect=[(first, "sha1"), (second, "sha2")]), patch.object(bridge.requests, "put", side_effect=responses) as put, patch.object(bridge.time, "sleep"):
            self.assertTrue(bridge._save_analytics({"new": entry(300)}, "test"))
            body = put.call_args.kwargs["json"]
            self.assertEqual(body["sha"], "sha2")
            self.assertEqual(set(json.loads(base64.b64decode(body["content"]))), {"old", "concurrent", "new"})

    def test_final_read_failure_aborts_save(self):
        with patch.object(bridge, "_get_file", return_value=(None, None)), patch.object(bridge.requests, "put") as put:
            self.assertFalse(bridge._save_analytics({"new": entry(10)}, "test"))
            put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
