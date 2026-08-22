import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import worker


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), params))


class ResultCursor(FakeCursor):
    def __init__(self, row):
        super().__init__()
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.cursor_value = ResultCursor(row)

    def cursor(self, **_kwargs):
        return self.cursor_value

    def close(self):
        pass


class WorkerWorkflowTests(unittest.TestCase):
    def test_failure_first_aid_is_deterministic(self):
        category, action = worker.classify_failure("draft failed validation: invalid JSON")
        self.assertEqual(category, "deterministic validation")
        self.assertIn("validator", action)

    def test_needs_input_is_not_a_failure(self):
        result = worker._needs_input("CMS access needed", ["credential_ref"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["required_inputs"], ["credential_ref"])

    def test_task_usage_has_one_central_insert(self):
        cursor = FakeCursor()
        worker.record_task_usage(
            cursor,
            {"id": 4, "type": "content_outline", "params": {}},
            {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
        )
        inserts = [call for call in cursor.calls if "INSERT INTO token_usage" in call[0]]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0][1][2:4], (10, 5))

    def test_side_effect_tasks_require_review_after_interruption(self):
        self.assertIn("publish_content", worker.SIDE_EFFECT_TASKS)
        self.assertIn("execute_suggestion", worker.SIDE_EFFECT_TASKS)
        self.assertNotIn("content_outline", worker.SIDE_EFFECT_TASKS)

    def test_content_approval_resume_inputs_reach_publisher(self):
        conn = FakeConnection({
            "id": 9,
            "type": "content",
            "payload": {"content_item_id": 22, "destination": {"type": "wordpress"}},
        })
        seen = {}

        def fake_publish(task):
            seen.update(task["params"])
            return worker._needs_input("credential needed", ["credential_ref"])

        with mock.patch.object(worker, "get_conn", return_value=conn), \
             mock.patch.object(worker, "handle_publish_content", side_effect=fake_publish):
            result = worker.handle_execute_approval({
                "id": 30,
                "params": {"approval_id": 9, "destination": {"credential_ref": "WP_APP_PASSWORD"}},
            })
        self.assertEqual(seen["content_item_id"], 22)
        self.assertEqual(seen["destination"]["credential_ref"], "WP_APP_PASSWORD")
        self.assertEqual(result["linked_content_item_id"], 22)

    def test_dns_approval_never_claims_live_without_provider(self):
        conn = FakeConnection({
            "id": 10,
            "type": "dns",
            "payload": {"subdomain": "example.test"},
        })
        with mock.patch.object(worker, "get_conn", return_value=conn):
            result = worker.handle_execute_approval({"id": 31, "params": {"approval_id": 10}})
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("dns_provider", result["required_inputs"])

    def test_codex_failure_uses_visible_opencode_fallback(self):
        with mock.patch.object(worker, "run_codex", return_value=(1, "codex error", 2, 0)), \
             mock.patch.object(worker, "run_opencode", return_value=(0, "fallback ok", 3, 4)) as run_fb, \
             mock.patch.object(worker, "post_discord") as notify, \
             mock.patch.dict(worker.os.environ, {}, clear=False):
            worker.os.environ.pop("OPENCODE_FALLBACK", None)
            result = worker.run_agent_harness("do work", "/tmp", timeout=30)
        self.assertEqual(result[0], 0)
        self.assertEqual(result[2:4], (5, 4))
        self.assertEqual(result[4], "opencode/deepseek-v4-flash")
        run_fb.assert_called_once()
        notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
