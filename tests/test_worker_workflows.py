import sys
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
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
    def test_retired_deepseek_aliases_route_to_current_models(self):
        self.assertEqual(worker._normalise_api_model("deepseek-chat"), "deepseek-v4-flash")
        self.assertEqual(worker._normalise_api_model("deepseek-reasoner"), "deepseek-v4-pro")

    def test_deepseek_json_request_is_explicit_and_priced(self):
        response = SimpleNamespace(read=lambda: json.dumps({
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                      "prompt_cache_hit_tokens": 40, "prompt_cache_miss_tokens": 60},
        }).encode())
        with mock.patch.object(worker.urllib.request, "urlopen", return_value=response) as opened:
            result = worker.call_zen("Return JSON", model="deepseek-chat", json_mode=True)
        request = opened.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(body["model"], "deepseek-v4-flash")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertTrue(result["ok"])
        self.assertGreater(result["cost"], 0)

    def test_raw_opencode_command_disables_tools(self):
        proc = SimpleNamespace(returncode=0, stdout='{"part":{"type":"text","text":"ok"}}\n', stderr="")
        with mock.patch("subprocess.run", return_value=proc) as run, \
             mock.patch.dict(worker.os.environ, {
                 "OPENAI_API_KEY": "raw-key", "OPENAI_BASE_URL": "https://api.deepseek.com",
                 "DEEPSEEK_API_KEY": "deepseek-key",
             }, clear=False):
            worker.run_opencode("answer", "/tmp", model="opencode/deepseek-v4-flash", allow_tools=False)
        cmd = run.call_args.args[0]
        env = run.call_args.kwargs["env"]
        self.assertIn("--pure", cmd)
        self.assertNotIn("--auto", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("OPENAI_BASE_URL", env)
        self.assertNotIn("DEEPSEEK_API_KEY", env)
        self.assertEqual(env["HOME"], "/home/agency")

    def test_raw_fallback_skips_provider_error_then_uses_subscription(self):
        provider_error = json.dumps({
            "type": "error", "error": {"data": {"message": "Invalid API key."}}
        })
        success = json.dumps({"type": "text", "part": {"type": "text", "text": "{\"ok\":true}"}})
        with mock.patch.object(worker, "run_opencode", side_effect=[
                (0, provider_error, 0, 0), (0, success, 10, 3)]), \
             mock.patch.object(worker, "post_discord") as notify:
            result = worker._raw_opencode_fallback("Return JSON", True, 30, "deepseek-v4-pro", "probe")
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "openai/gpt-5.4-mini-fast")
        self.assertEqual(notify.call_count, 2)

    def test_research_facts_require_exact_fetched_evidence(self):
        fetched = [{
            "url": "https://example.test/a", "extract_ok": True, "word_count": 20,
            "plain_text": "This exact source sentence contains enough words to verify a useful claim today.",
        }]
        payload = {
            "elements": [{"url": "https://example.test/a", "headings": [], "elements_used": [],
                          "word_count": 20, "freshness": "unknown"}],
            "strongest": [], "weaknesses": [], "gaps": [], "element_strategy": "use prose",
            "facts": [{"claim": "A useful claim", "source_url": "https://example.test/a",
                       "evidence_snippet": "This exact source sentence contains enough words to verify a useful claim"}],
        }
        safe, failures = worker._validate_research_payload(payload, fetched)
        self.assertEqual(failures, [])
        self.assertEqual(safe["facts"][0]["id"], "fact-1")
        payload["facts"][0]["evidence_snippet"] = "These invented words are nowhere within the fetched page source at all"
        safe, failures = worker._validate_research_payload(payload, fetched)
        self.assertEqual(safe["facts"], [])
        self.assertTrue(any("not present" in failure for failure in failures))

    def test_data_blocks_require_known_fact_ids(self):
        blocks = [
            {"type": "intro", "brief": "Open directly"},
            {"type": "prose", "brief": "Explain", "keyword_target": True},
            {"type": "chart", "brief": "Show data", "chart_type": "bar", "fact_ids": ["fact-9"]},
        ]
        failures = worker._content_outline_validate(blocks, [{"id": "fact-1"}])
        self.assertTrue(any("unknown fact_ids" in failure for failure in failures))

    def test_compose_block_keyword_contract_is_local(self):
        block = {"type": "prose", "brief": "Explain", "markdown": "Useful qualitative advice.",
                 "keyword_target": True, "fact_ids": [], "sources": []}
        self.assertIn("target_keyword missing from keyword_target block",
                      worker._content_block_validate(block, "job search automation"))

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
