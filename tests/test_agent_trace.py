import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
