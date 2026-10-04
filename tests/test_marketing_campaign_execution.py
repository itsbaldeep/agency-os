import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

sys.path.insert(0, "/home/agency/core/agency-os/scripts")
import marketing_campaign_execution as execution


class Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows); self.calls = []; self.rowcount = 1
    def execute(self, sql, args=()): self.calls.append((sql, args))
    def fetchone(self): return self.rows.pop(0) if self.rows else None
    def fetchall(self): return self.rows


class Conn:
    def __init__(self, cursor, fail_commit=False): self.c = cursor; self.commits = 0; self.fail_commit = fail_commit
    def cursor(self, *args, **kwargs): return self.c
    def commit(self):
        if self.fail_commit: raise RuntimeError("db unavailable")
        self.commits += 1
    def rollback(self): pass
    def close(self): pass


class ExecutionTests(unittest.TestCase):
    def queued_rows(self, state="queued", revision=1):
        now = datetime.now(UTC)
        item = {"id": 2, "brand_id": 4, "revision": revision, "state": "ready", "item_brand_id": 4, "brand_lifecycle": "active", "classification": "engagement", "local_path": "/tmp/x", "adapter_config": {}}
        run = {"id": 9, "brand_id": 4, "item_id": 2, "revision": revision, "state": state, "approval_digest": "a" * 64, "idempotency_key": "b" * 64, "contract": {"brand_id": 4, "item_id": 2, "revision": revision, "approval_digest": "a" * 64, "idempotency_key": "b" * 64, "send_at": now.isoformat()}, "send_at": now, "task_id": 44}
        return [item, run]

    def test_exact_parameter_shapes_and_safe_ids(self):
        with self.assertRaises(ValueError): execution._ids({"brand_id": 1, "item_id": 2, "revision": 3, "recipients": []}, ("brand_id", "item_id", "revision"))
        with self.assertRaises(ValueError): execution._ids({"run_id": True, "brand_id": 2}, ("run_id", "brand_id"))

    def test_terminal_run_never_posts(self):
        cur = Cursor([{"id": 2, "brand_id": 4, "revision": 1, "state": "ready", "item_brand_id": 4, "brand_lifecycle": "active", "classification": "engagement", "local_path": "/tmp/x", "adapter_config": None}, {"id": 9, "brand_id": 4, "item_id": 2, "revision": 1, "state": "delivered", "receipt": {"status": "delivered"}}])
        conn = Conn(cur); client = Mock()
        result = execution.handle_dispatch({"params": {"run_id": 9, "brand_id": 4}}, lambda: conn, client)
        self.assertEqual(result["status"], "delivered"); client.request_dispatch.assert_not_called()

    def test_uncertain_run_requires_reconciliation(self):
        cur = Cursor([{"id": 2, "brand_id": 4, "revision": 1, "state": "ready", "item_brand_id": 4, "brand_lifecycle": "active", "classification": "engagement", "local_path": "/tmp/x", "adapter_config": None}, {"id": 9, "brand_id": 4, "item_id": 2, "revision": 1, "state": "uncertain"}])
        client = Mock(); result = execution.handle_dispatch({"params": {"run_id": 9, "brand_id": 4}}, lambda: Conn(cur), client)
        self.assertEqual(result["status"], "uncertain"); client.request_dispatch.assert_not_called()

    def test_cancel_only_approved_or_queued(self):
        cur = Cursor(); conn = Conn(cur)
        result = execution.cancel(3, 4, lambda: conn)
        self.assertTrue(result["ok"]); self.assertIn("state IN ('approved','queued')", cur.calls[0][0])

    def test_scheduler_has_no_work_without_approved_rows(self):
        cur = Cursor([]); conn = Conn(cur)
        result = execution.enqueue_due(lambda: conn)
        self.assertEqual(result, {"ok": True, "queued": 0}); self.assertEqual(conn.commits, 1)

    def test_claim_commits_before_post_and_repeated_dispatch_posts_once(self):
        first = Conn(Cursor(self.queued_rows()))
        second = Conn(Cursor(self.queued_rows(state="dispatching")))
        client = Mock(); events = []
        client.request_dispatch.side_effect = lambda *args: (events.append(first.commits), {"status": "uncertain"})[1]
        with patch.object(execution, "_config", return_value={}), patch.object(execution.adapter, "validate_contract"):
            result = execution.handle_dispatch({"id": 44, "params": {"run_id": 9, "brand_id": 4}}, lambda: first, client)
            duplicate = execution.handle_dispatch({"id": 44, "params": {"run_id": 9, "brand_id": 4}}, lambda: second, client)
        self.assertEqual(events, [1]); self.assertEqual(result["status"], "uncertain"); self.assertEqual(duplicate["status"], "uncertain"); client.request_dispatch.assert_called_once()

    def test_postclaim_database_failure_leaves_uncertain_without_retry(self):
        initial = Conn(Cursor(self.queued_rows()))
        persist = Conn(Cursor(), fail_commit=True)
        client = Mock(); client.request_dispatch.return_value = {"status": "accepted"}
        connections = iter((initial, persist))
        with patch.object(execution, "_config", return_value={}), patch.object(execution.adapter, "validate_contract"), patch.object(execution.adapter, "validate_receipt", return_value={"status": "accepted"}):
            result = execution.handle_dispatch({"id": 44, "params": {"run_id": 9, "brand_id": 4}}, lambda: next(connections), client)
        self.assertEqual(result["status"], "uncertain"); self.assertEqual(initial.commits, 1); client.request_dispatch.assert_called_once()

    def test_stale_revision_is_blocked_durably_without_post(self):
        cur = Cursor(self.queued_rows(revision=2)); client = Mock()
        with patch.object(execution, "_config", return_value={}):
            result = execution.handle_dispatch({"params": {"run_id": 9, "brand_id": 4}}, lambda: Conn(cur), client)
        self.assertEqual(result["status"], "blocked"); self.assertTrue(any("SET state='blocked'" in sql for sql, _ in cur.calls)); client.request_dispatch.assert_not_called()

    def test_cancelled_run_cannot_reconcile(self):
        cur = Cursor([{**self.queued_rows()[0]}, {**self.queued_rows(state="cancelled")[1]}]); client = Mock()
        result = execution.handle_receipt({"params": {"run_id": 9, "brand_id": 4}}, lambda: Conn(cur), client)
        self.assertEqual(result["status"], "blocked"); client.request_receipt.assert_not_called()

    def test_wrong_receipt_identity_is_rejected_and_not_persisted(self):
        initial = Conn(Cursor(self.queued_rows()))
        client = Mock(); client.request_dispatch.return_value = {"status": "accepted"}
        with patch.object(execution, "_config", return_value={}), patch.object(execution.adapter, "validate_contract"), patch.object(execution.adapter, "validate_receipt", side_effect=ValueError("receipt_identity_mismatch")):
            result = execution.handle_dispatch({"params": {"run_id": 9, "brand_id": 4}}, lambda: initial, client)
        self.assertEqual(result["status"], "uncertain"); client.request_dispatch.assert_called_once()


if __name__ == "__main__": unittest.main()
