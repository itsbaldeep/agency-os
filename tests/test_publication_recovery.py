import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import publication_recovery


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class Conn:
    def __init__(self, rows, fail_commit=False):
        self.cur = Cursor(rows)
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **kwargs): return self.cur
    def commit(self):
        self.commits += 1
        if self.fail_commit: raise RuntimeError("fixture commit failure")
    def rollback(self): self.rollbacks += 1
    def close(self): pass


class PublicationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.destination = {"type": "static", "enabled": True,
                            "output_root": "/tmp/publications/4",
                            "base_url": "https://brand.example/blog"}
        self.params = {"brand_id": 4, "content_item_id": 23,
                       "publish_task_id": 88, "manifest_hash": "a" * 64,
                       "approved_destination": publication_recovery.destination_digest(self.destination)}
        self.item = {"id": 23, "brand_id": 4, "status": "published",
                     "publish_task_id": 88, "structured": {}, "project_id": 10,
                     "lifecycle": "active"}
        self.origin = {"id": 88, "type": "publish_content", "status": "done",
                       "params": {"brand_id": 4, "content_item_id": 23,
                                  "approved_destination": self.params["approved_destination"]},
                       "result_ref": {"manifest_hash": "a" * 64, "brand_id": 4, "content_id": 23}}

    def invoke(self, conn, rollback_result=None):
        task = {"id": 99, "params": self.params}
        with mock.patch.object(publication_recovery, "project_destination", return_value=self.destination), \
             mock.patch.object(publication_recovery, "rollback", return_value=rollback_result or {"unpublished": True}):
            return publication_recovery.handle(task, lambda: conn)

    def test_brand_mismatch_is_rejected(self):
        conn = Conn([{**self.item, "brand_id": 5}, self.origin])
        result = self.invoke(conn)
        self.assertFalse(result["ok"])
        self.assertEqual(conn.commits, 0)

    def test_receipt_brand_and_content_must_match(self):
        conn = Conn([self.item, {**self.origin, "result_ref": {"manifest_hash": "a" * 64, "brand_id": 5, "content_id": 23}}])
        result = self.invoke(conn)
        self.assertFalse(result["ok"])

    def test_missing_receipt_manifest_is_rejected(self):
        conn = Conn([self.item, {**self.origin, "result_ref": {"brand_id": 4, "content_id": 23}}])
        result = self.invoke(conn)
        self.assertFalse(result["ok"])

    def test_lock_targets_content_row_only(self):
        conn = Conn([self.item, self.origin])
        self.invoke(conn)
        select = conn.cur.calls[0][0]
        self.assertIn("FOR UPDATE OF ci", select)

    def test_stale_destination_is_rejected_before_filesystem_rollback(self):
        conn = Conn([self.item, self.origin])
        with mock.patch.object(publication_recovery, "destination_digest", return_value="b" * 64), \
             mock.patch.object(publication_recovery, "rollback", return_value={}) as rollback, \
             mock.patch.object(publication_recovery, "project_destination", return_value=self.destination):
            result = publication_recovery.handle({"id": 99, "params": self.params}, lambda: conn)
        self.assertFalse(result["ok"])
        rollback.assert_not_called()

    def test_success_preserves_origin_task_and_updates_content(self):
        conn = Conn([self.item, self.origin])
        result = self.invoke(conn)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["workflow_status"], "rolled_back")
        self.assertEqual(conn.commits, 1)
        update = next(params for sql, params in conn.cur.calls if sql.startswith("UPDATE content_items"))
        self.assertEqual(update[-1], 88)
        self.assertIn("publication_rollback", json.loads(update[0]))

    def test_db_commit_failure_is_retryable_and_fs_rollback_is_idempotent(self):
        conn = Conn([self.item, self.origin], fail_commit=True)
        result = self.invoke(conn)
        self.assertFalse(result["ok"])
        self.assertEqual(conn.rollbacks, 1)
        self.assertIn("retry", result["error"])


if __name__ == "__main__":
    unittest.main()
