import io
import gzip
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest import mock


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import agent_trace


class AgentTraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.trace_dir = Path(self.tmp.name) / "traces"
        self.patches = [
            mock.patch.object(agent_trace, "TRACE_DIR", self.trace_dir),
            mock.patch.object(agent_trace, "CURRENT_DIR", self.trace_dir / "current"),
            mock.patch.object(agent_trace, "ARCHIVE_DIR", self.trace_dir / "archive"),
            mock.patch.object(agent_trace, "ATTENTION_PATH", self.trace_dir / "attention.json"),
            mock.patch.object(agent_trace, "DISCORD_RECEIPTS_PATH", self.trace_dir / "discord-receipts.json"),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def _records(self):
        path = next(self.trace_dir.glob("????-??-??.jsonl"))
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_prompt_hook_stores_hash_not_prompt_and_returns_trace_context(self):
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "cwd": "/home/agency",
            "model": "gpt-5.6-sol",
            "prompt": "This text must not enter the trace file",
        }
        with mock.patch("sys.stdin", io.StringIO(json.dumps(payload))), \
             mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(agent_trace.handle_hook(), 0)
        output = json.loads(stdout.getvalue())
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("atr_", context)
        self.assertIn("must not spawn a subagent", context)
        self.assertIn("For substantive", context)
        raw = next(self.trace_dir.glob("????-??-??.jsonl")).read_text()
        self.assertNotIn(payload["prompt"], raw)
        self.assertEqual(self._records()[0]["prompt_chars"], len(payload["prompt"]))

    def test_record_refuses_credential_like_summary(self):
        args = mock.Mock(
            trace_id=None,
            session_id="",
            kind="result",
            status="recorded",
            severity="info",
            summary="api_key=do-not-store",
            ref=[],
            fresh_until=None,
        )
        with self.assertRaises(ValueError):
            agent_trace.record(args)

    def test_search_returns_bounded_summary_not_lifecycle_noise(self):
        agent_trace._append({
            "trace_id": "atr_test",
            "kind": "research",
            "status": "verified",
            "summary": "Lavish uses a Tailscale-only listener",
            "refs": ["https://github.com/kunchenguid/lavish-axi"],
            "redacted": True,
        })
        agent_trace._append({"trace_id": "atr_test", "kind": "PostToolUse", "status": "observed"})
        args = mock.Mock(terms=["lavish"], days=7, limit=5)
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(agent_trace.search(args), 0)
        rows = stdout.getvalue().splitlines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])["trace_id"], "atr_test")

    def test_active_alert_is_resolved_only_by_terminal_record(self):
        tid = "atr_test_attention"
        agent_trace._append({
            "trace_id": tid,
            "kind": "alert",
            "status": "needs_human",
            "severity": "urgent",
            "summary": "Choose the release window",
            "refs": ["dashboard:/alerts"],
        })
        agent_trace._append({
            "trace_id": tid,
            "kind": "checkpoint",
            "status": "working",
            "summary": "Safe work continued",
            "refs": [],
        })
        self.assertEqual([item["trace_id"] for item in agent_trace.active_alerts()], [tid])
        agent_trace._append({
            "trace_id": tid,
            "kind": "decision",
            "status": "resolved",
            "summary": "Release window chosen",
            "refs": [],
        })
        self.assertEqual(agent_trace.active_alerts(), [])

    def test_unresolved_alert_index_does_not_expire_by_age(self):
        self.trace_dir.mkdir(parents=True)
        old = self.trace_dir / "2020-01-01.jsonl"
        old.write_text(json.dumps({
            "v": 1,
            "ts": "2020-01-01T00:00:00.000Z",
            "trace_id": "atr_old",
            "kind": "alert",
            "status": "needs_human",
            "severity": "warning",
            "summary": "Old decision still needs a human",
            "refs": [],
        }) + "\n")
        self.assertEqual([item["trace_id"] for item in agent_trace.active_alerts(days=1)], ["atr_old"])
        self.assertTrue(agent_trace.ATTENTION_PATH.exists())

    def test_urgent_discord_notification_is_deduplicated(self):
        item = {
            "ts": "2026-08-24T00:00:00.000Z",
            "trace_id": "atr_urgent",
            "kind": "alert",
            "status": "needs_human",
            "severity": "urgent",
            "summary": "Choose the release window",
            "refs": ["ignored:arbitrary-reference"],
        }

        class Response:
            status = 204

            def getcode(self):
                return self.status

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch.object(agent_trace, "_core_env", return_value={"DISCORD_WEBHOOK_URL": "https://example.test/hook"}), \
             mock.patch.object(agent_trace.urllib.request, "urlopen", return_value=Response()) as send:
            first = agent_trace.notify_active_urgent([item])
            second = agent_trace.notify_active_urgent([item])
            reopened = agent_trace.notify_active_urgent([{**item, "ts": "2026-08-24T01:00:00.000Z"}])
        self.assertEqual(first["sent"], 1)
        self.assertEqual(second["suppressed"], 1)
        self.assertEqual(reopened["sent"], 1)
        self.assertEqual(send.call_count, 2)
        body = json.loads(send.call_args.args[0].data)
        self.assertIn("http://100.64.0.1:5001/alerts", body["content"])
        self.assertNotIn("arbitrary-reference", body["content"])

    def test_failed_discord_notification_is_retried(self):
        item = {
            "trace_id": "atr_retry", "status": "needs_human", "severity": "urgent",
            "summary": "Human input needed", "ts": "2026-08-24T00:00:00.000Z",
        }
        with mock.patch.object(agent_trace, "_core_env", return_value={"DISCORD_WEBHOOK_URL": "https://example.test/hook"}), \
             mock.patch.object(agent_trace.urllib.request, "urlopen", side_effect=OSError("offline")) as send:
            self.assertEqual(agent_trace.notify_active_urgent([item])["failed"], 1)
            self.assertEqual(agent_trace.notify_active_urgent([item])["failed"], 1)
        self.assertEqual(send.call_count, 2)
        self.assertFalse(agent_trace.DISCORD_RECEIPTS_PATH.exists())

    def test_attention_rebuild_serializes_with_concurrent_append(self):
        agent_trace._append({
            "trace_id": "atr_existing", "kind": "alert", "status": "needs_human",
            "severity": "warning", "summary": "Existing choice", "refs": [],
        })
        original_build = agent_trace._build_attention_payload
        started = threading.Event()
        release = threading.Event()

        def slow_build():
            payload = original_build()
            started.set()
            release.wait(timeout=2)
            return payload

        with mock.patch.object(agent_trace, "_build_attention_payload", side_effect=slow_build):
            rebuild = threading.Thread(target=agent_trace.rebuild_attention)
            rebuild.start()
            self.assertTrue(started.wait(timeout=1))
            append = threading.Thread(target=agent_trace._append, args=({
                "trace_id": "atr_new", "kind": "alert", "status": "needs_human",
                "severity": "urgent", "summary": "New choice", "refs": [],
            },))
            append.start()
            self.assertTrue(append.is_alive())
            release.set()
            rebuild.join(timeout=2)
            append.join(timeout=2)
        self.assertEqual(
            {item["trace_id"] for item in agent_trace.active_alerts()},
            {"atr_existing", "atr_new"},
        )

    def test_compaction_retains_high_value_and_summarizes_routine_noise(self):
        self.trace_dir.mkdir(parents=True)
        source = self.trace_dir / "2026-01-01.jsonl"
        rows = [
            {"v": 1, "ts": "2026-01-01T00:00:00.000Z", "trace_id": "atr_one",
             "kind": "prompt", "status": "received", "prompt_sha256": "a" * 64, "redacted": True},
            {"v": 1, "ts": "2026-01-01T00:01:00.000Z", "trace_id": "atr_one",
             "kind": "PostToolUse", "status": "observed", "response_sha256": "b" * 64, "redacted": True},
            {"v": 1, "ts": "2026-01-01T00:02:00.000Z", "trace_id": "atr_one",
             "kind": "decision", "status": "verified", "severity": "info",
             "summary": "Keep the bounded design", "refs": [], "redacted": True},
        ]
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        now = datetime(2026, 8, 24, tzinfo=timezone.utc)
        with mock.patch.object(agent_trace, "utc_now", return_value=now):
            report = agent_trace.compact_old_traces(90)
        self.assertEqual(report["files"], 1)
        self.assertFalse(source.exists())
        archive = self.trace_dir / report["archives"][0]
        with gzip.open(archive, "rt", encoding="utf-8") as handle:
            archived = [json.loads(line) for line in handle]
        decision = next(row for row in archived if row["kind"] == "decision")
        summary = next(row for row in archived if row["kind"] == "trace_compaction")
        self.assertEqual(decision, rows[2])
        self.assertEqual(summary["record_count"], 2)
        self.assertEqual(summary["event_counts"], {"PostToolUse": 1, "prompt": 1})
        self.assertTrue((self.trace_dir / "archive" / "manifest.json").exists())

    def test_malformed_trace_is_never_deleted_by_compaction(self):
        self.trace_dir.mkdir(parents=True)
        source = self.trace_dir / "2026-01-01.jsonl"
        source.write_text("not-json\n")
        now = datetime(2026, 8, 24, tzinfo=timezone.utc)
        with mock.patch.object(agent_trace, "utc_now", return_value=now), self.assertRaises(ValueError):
            agent_trace.compact_old_traces(90)
        self.assertEqual(source.read_text(), "not-json\n")


if __name__ == "__main__":
    unittest.main()
