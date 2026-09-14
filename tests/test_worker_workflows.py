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

    def test_completed_collector_state_is_available_in_marketing_report(self):
        self.assertEqual(worker._marketing_source_state("done"), "available")

    def test_seo_run_id_is_stable_per_task(self):
        self.assertEqual(worker._seo_run_id(7, 2, "https://example.test"), worker._seo_run_id(7, 2, "https://example.test"))
        self.assertNotEqual(worker._seo_run_id(7, 2, "https://example.test"), worker._seo_run_id(8, 2, "https://example.test"))

    def test_seo_dedupe_uses_jsonb_and_executing_status(self):
        # Keep this acceptance check close to the fake-DB workflow contract.
        source = Path(worker.__file__).read_text()
        self.assertIn("sources @> %s::jsonb", source)
        self.assertIn("'executing'", source)

    def test_marketing_audit_creates_one_collecting_assessment_and_three_stages(self):
        class Cursor(FakeCursor):
            def fetchone(self):
                sql = self.calls[-1][0]
                if "FROM brands" in sql:
                    return {"id": 7, "project_id": 30}
                return None

            def fetchall(self):
                return [{"property_type": "gsc_property", "value": "sc-domain:example.test"},
                        {"property_type": "ga4_property_id", "value": "123456"}]

        class Conn:
            def __init__(self):
                self.c = Cursor()
            def cursor(self, **_): return self.c
            def commit(self): pass
            def close(self): pass

        conn = Conn()
        assessment = {"id": 55, "trigger_task_id": 99, "status": "queued"}
        with mock.patch.object(worker, "get_conn", return_value=conn), \
             mock.patch.object(worker.marketing_assessments, "get_or_create_assessment",
                               return_value=(assessment, True, False)) as create, \
             mock.patch.object(worker.marketing_assessments, "ensure_stage_tasks",
                               return_value=[101, 102, 103]) as ensure:
            result = worker.handle_marketing_audit({
                "id": 99,
                "params": {"brand_id": 7, "project_id": 30, "url": "https://example.test"},
            })
        self.assertTrue(result["ok"])
        payload = json.loads(result["content"])
        self.assertEqual(payload["stages"], ["defend_audit", "run_brand_audit", "seo_measurement"])
        self.assertEqual(payload["assessment_id"], 55)
        self.assertEqual(payload["status"], "collecting")
        self.assertEqual(result["task_status"], "collecting")
        create.assert_called_once()
        stages = ensure.call_args.kwargs["stages"]
        self.assertEqual([stage[0] for stage in stages], payload["stages"])
        self.assertEqual(stages[0][1]["url"], "https://example.test")
        self.assertEqual(stages[1][1], {
            "brand_id": 7, "domain": "example.test", "source": "marketing_audit",
        })
        self.assertEqual(stages[-1][1]["gsc_property"], "sc-domain:example.test")
        self.assertEqual(stages[-1][1]["ga4_property_id"], "123456")

    def test_marketing_assessment_collection_state_is_not_report_ready(self):
        rows = [
            {"stage_key": "defend_audit", "task_id": 1, "required": True, "task_status": "done"},
            {"stage_key": "run_brand_audit", "task_id": 2, "required": True, "task_status": "done"},
            {"stage_key": "seo_measurement", "task_id": 3, "required": True, "task_status": "done"},
        ]
        status, manifest, text = worker.marketing_assessments.collection_outcome(rows)
        self.assertEqual(status, "collecting")
        self.assertTrue(manifest["children_settled"])
        self.assertTrue(manifest["synthesis_eligible"])
        self.assertEqual(manifest["report_state"], "not_generated")
        self.assertIn("synthesis pending", text)

    def test_marketing_assessment_failed_collection_has_no_green_partial_report(self):
        rows = [
            {"stage_key": "defend_audit", "task_id": 1, "required": True, "task_status": "done"},
            {"stage_key": "run_brand_audit", "task_id": 2, "required": True, "task_status": "failed", "task_error": "provider unavailable"},
            {"stage_key": "seo_measurement", "task_id": 3, "required": True, "task_status": "done"},
        ]
        status, manifest, text = worker.marketing_assessments.collection_outcome(rows)
        self.assertEqual(status, "failed")
        self.assertFalse(manifest["synthesis_eligible"])
        self.assertEqual(manifest["missing_evidence"], ["run_brand_audit"])
        self.assertEqual(manifest["report_state"], "not_generated")
        self.assertIn("failed", text)

    def test_marketing_assessment_run_key_is_stable_and_accepts_ui_idempotency_key(self):
        self.assertEqual(worker.marketing_assessments.assessment_run_key(99, {}), "task:99")
        self.assertEqual(
            worker.marketing_assessments.assessment_run_key(99, {"idempotency_key": " dashboard-click-1 "}),
            "dashboard-click-1",
        )

    def test_assessment_stage_creation_is_idempotent_after_restart(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.stage_rows = {}
                self.next_task_id = 100
                self.last_row = None

            def execute(self, sql, params=()):
                normalized = " ".join(sql.split())
                self.calls.append((normalized, params))
                self.last_row = None
                if normalized.startswith("SELECT stage_key, task_id"):
                    return
                if normalized.startswith("INSERT INTO tasks"):
                    self.last_row = {"id": self.next_task_id}
                    self.next_task_id += 1
                if normalized.startswith("INSERT INTO marketing_assessment_stages"):
                    self.stage_rows[params[1]] = params[2]

            def fetchone(self):
                return self.last_row

            def fetchall(self):
                return [{"stage_key": key, "task_id": value}
                        for key, value in self.stage_rows.items()]

        cur = Cursor()
        stages = [("defend_audit", {"brand_id": 7}), ("seo_measurement", {"brand_id": 7})]
        assessment = {"id": 55}
        first = worker.marketing_assessments.ensure_stage_tasks(
            cur, assessment=assessment, parent_task_id=99, stages=stages,
        )
        second = worker.marketing_assessments.ensure_stage_tasks(
            cur, assessment=assessment, parent_task_id=99, stages=stages,
        )
        self.assertEqual(first, [100, 101])
        self.assertEqual(second, first)
        self.assertEqual(len([call for call in cur.calls if call[0].startswith("INSERT INTO tasks")]), 2)

    def test_concurrent_logical_run_conflict_reuses_existing_assessment(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.last_query = ""

            def execute(self, sql, params=()):
                self.last_query = " ".join(sql.split())
                self.calls.append((self.last_query, params))

            def fetchone(self):
                if "OR (brand_id=%s" in self.last_query:
                    return {"id": 55, "trigger_task_id": 98, "status": "collecting"}
                return None

        cur = Cursor()
        assessment, created, deduplicated = worker.marketing_assessments.get_or_create_assessment(
            cur, task_id=99, brand_id=7, project_id=30,
            params={"assessment_run_key": "same-dashboard-click"},
        )
        self.assertEqual(assessment["id"], 55)
        self.assertFalse(created)
        self.assertTrue(deduplicated)
        insert = next(call for call in cur.calls if call[0].startswith("INSERT INTO marketing_assessments"))
        self.assertIn("ON CONFLICT DO NOTHING", insert[0])

    def test_assessment_reconciliation_is_idempotent_and_keeps_parent_collecting(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.last_query = ""
                self.assessment = {"id": 55, "trigger_task_id": 99, "status": "collecting"}
                self.rows = [
                    {"stage_key": "defend_audit", "task_id": 1, "required": True,
                     "status": "queued", "task_status": "done", "task_error": None},
                    {"stage_key": "run_brand_audit", "task_id": 2, "required": True,
                     "status": "queued", "task_status": "done", "task_error": None},
                    {"stage_key": "seo_measurement", "task_id": 3, "required": True,
                     "status": "queued", "task_status": "done", "task_error": None},
                ]

            def execute(self, sql, params=()):
                self.last_query = " ".join(sql.split())
                self.calls.append((self.last_query, params))

            def fetchone(self):
                if self.last_query.startswith("SELECT * FROM marketing_assessments"):
                    return self.assessment
                return None

            def fetchall(self):
                if self.last_query.startswith("SELECT s.stage_key"):
                    return self.rows
                return []

        cur = Cursor()
        first = worker.marketing_assessments.reconcile_assessment(cur, 55)
        second = worker.marketing_assessments.reconcile_assessment(cur, 55)
        self.assertEqual(first["status"], "collecting")
        self.assertEqual(second["manifest"], first["manifest"])
        parent_updates = [call for call in cur.calls if call[0].startswith("UPDATE tasks SET status")]
        self.assertEqual(len(parent_updates), 2)
        self.assertTrue(all(call[1][0] == "collecting" for call in parent_updates))

    def test_only_one_synthesizer_can_claim_a_settled_assessment(self):
        class Cursor:
            def __init__(self, rowcount):
                self.calls = []
                self.rowcount = rowcount

            def execute(self, sql, params=()):
                self.calls.append((" ".join(sql.split()), params))

        settled = {"manifest": {"synthesis_eligible": True}}
        with mock.patch.object(worker.marketing_assessments, "reconcile_assessment", return_value=settled):
            winner, winner_reason = worker.marketing_assessments.claim_synthesis(Cursor(1), 55)
            loser, loser_reason = worker.marketing_assessments.claim_synthesis(Cursor(0), 55)
        self.assertTrue(winner)
        self.assertEqual(winner_reason, "claimed")
        self.assertFalse(loser)
        self.assertEqual(loser_reason, "already claimed")

    def test_settled_collection_queues_one_synthesis_task(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.last_query = ""
                self.rowcount = 1

            def execute(self, sql, params=()):
                self.last_query = " ".join(sql.split())
                self.calls.append((self.last_query, params))

            def fetchone(self):
                if self.last_query.startswith("SELECT id, brand_id"):
                    return {"id": 55, "brand_id": 7, "project_id": 30, "trigger_task_id": 99,
                            "status": "collecting", "source_manifest": {"synthesis_eligible": True}}
                if "stage_key=%s" in self.last_query:
                    return None
                if self.last_query.startswith("INSERT INTO tasks"):
                    return {"id": 104}
                return None

        cur = Cursor()
        task_id = worker.marketing_assessments.queue_synthesis_if_eligible(cur, 55)
        self.assertEqual(task_id, 104)
        task_insert = next(call for call in cur.calls if call[0].startswith("INSERT INTO tasks"))
        self.assertEqual(task_insert[1][0], "marketing_assessment_synthesis")
        stage_insert = next(call for call in cur.calls if call[0].startswith("INSERT INTO marketing_assessment_stages"))
        self.assertIn("false,'queued'", stage_insert[0])

    def test_deterministic_report_marks_unavailable_sources_partial_and_preserves_zero(self):
        report = worker.build_deterministic_marketing_report(
            {"id": 55},
            {"subject": {"name": "Example", "url": "https://example.test"}, "sources": [
                {"key": "technical_crawl", "label": "Technical crawl", "status": "available",
                 "checked_at": "2026-09-14T10:00:00Z",
                 "metrics": [{"key": "pages", "state": "observed", "value": 0, "unit": "count"}]},
                {"key": "gsc", "label": "Google Search Console", "status": "not_configured",
                 "checked_at": "2026-09-14T10:00:00Z", "metrics": []},
            ], "suggestions": [{"id": 9, "title": "Add structured data", "rationale": "Crawl evidence needs review.",
                                  "impact": "high", "action_type": "propose_fix"}]},
            generated_at="2026-09-14T10:01:00Z",
        )
        self.assertEqual(report["status"], "partial")
        crawl = next(source for source in report["sources"] if source["key"] == "technical_crawl")
        self.assertEqual(crawl["metrics"][0]["value"], 0)
        self.assertEqual(report["actions"][0]["mode"], "review_required")
        self.assertTrue(report["actions"][0]["human_decision_required"])

    def test_synthesis_failure_marks_parent_failed_instead_of_leaving_collecting(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.last_query = ""
            def execute(self, sql, params=()):
                self.last_query = " ".join(sql.split())
                self.calls.append((self.last_query, params))
            def fetchone(self):
                if self.last_query.startswith("SELECT s.assessment_id"):
                    return {"assessment_id": 55, "stage_key": "marketing_assessment_synthesis",
                            "task_status": "failed", "task_error": "invalid report"}
                return None

        outcome = worker.marketing_assessments.reconcile_for_child_task(Cursor(), 104)
        self.assertEqual(outcome["status"], "failed")
        self.assertIn("invalid report", outcome["progress_text"])

    def test_synthesis_loads_only_audits_referenced_by_its_own_child_tasks(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.last_query = ""

            def execute(self, sql, params=()):
                self.last_query = " ".join(sql.split())
                self.calls.append((self.last_query, params))

            def fetchone(self):
                if self.last_query.startswith("SELECT name FROM brands"):
                    return {"name": "Example"}
                if self.last_query.startswith("SELECT value FROM brand_properties"):
                    return {"value": "example.test"}
                if "audit_type='seo_measurement'" in self.last_query:
                    return {"created_at": "2026-09-14T10:00:00Z", "summary": {"counts": {"pages": 0}},
                            "raw_data": {"sources": {"crawl": {"status": "available"}, "gsc": {"status": "not_configured"}}}}
                if "audit_type <> 'seo_measurement'" in self.last_query:
                    return {"created_at": "2026-09-14T10:00:00Z", "summary": {"prompts_queried": 5}}
                return None

            def fetchall(self):
                if self.last_query.startswith("SELECT s.stage_key"):
                    return [
                        {"stage_key": "defend_audit", "task_status": "done", "result_ref": "{}", "error": None, "finished_at": "2026-09-14T10:00:00Z"},
                        {"stage_key": "run_brand_audit", "task_status": "done", "result_ref": '{"audit_id":22}', "error": None, "finished_at": "2026-09-14T10:00:00Z"},
                        {"stage_key": "seo_measurement", "task_status": "done", "result_ref": '{"audit_id":11}', "error": None, "finished_at": "2026-09-14T10:00:00Z"},
                    ]
                if self.last_query.startswith("SELECT id, title"):
                    return [{"id": 2, "title": "Review crawl findings", "rationale": "Use evidence.", "impact": "high", "action_type": "propose_fix"}]
                return []

        cur = Cursor()
        evidence = worker._load_marketing_evidence(cur, {"id": 55, "brand_id": 7, "project_id": 30})
        self.assertEqual(evidence["subject"]["url"], "https://example.test")
        self.assertEqual(next(item for item in evidence["sources"] if item["key"] == "technical_crawl")["status"], "available")
        audit_queries = [call for call in cur.calls if "FROM audits" in call[0]]
        self.assertEqual([call[1][0] for call in audit_queries], [11, 22])
        self.assertTrue(all("ORDER BY created_at" not in call[0] for call in audit_queries))

    def test_restart_recovery_queues_eligible_synthesis(self):
        class Cursor:
            def __init__(self):
                self.calls = []
            def execute(self, sql, params=()):
                self.calls.append((" ".join(sql.split()), params))
            def fetchall(self):
                return [{"id": 55}]

        recovered = {"assessment_id": 55, "manifest": {"synthesis_eligible": True}}
        with mock.patch.object(worker.marketing_assessments, "reconcile_assessment", return_value=recovered), \
             mock.patch.object(worker.marketing_assessments, "queue_synthesis_if_eligible", return_value=104) as queued:
            result = worker.marketing_assessments.reconcile_open_assessments(Cursor())
        self.assertEqual(result[0]["synthesis_task_id"], 104)
        queued.assert_called_once_with(mock.ANY, 55)

    def test_synthesis_retry_after_persisted_report_is_idempotent_success(self):
        class Cursor:
            def __init__(self): self.calls = []
            def execute(self, sql, params=()): self.calls.append((" ".join(sql.split()), params))
            def fetchone(self):
                return {"id": 55, "status": "ready", "report": {"report_id": "assessment-55"},
                        "validation": {"valid": True}}
        class Conn:
            def __init__(self): self.c = Cursor(); self.commits = 0
            def cursor(self, **_): return self.c
            def commit(self): self.commits += 1
            def close(self): pass
        conn = Conn()
        with mock.patch.object(worker, "get_conn", return_value=conn):
            result = worker.handle_marketing_assessment_synthesis({"params": {"assessment_id": 55}})
        self.assertTrue(result["ok"])
        self.assertTrue(json.loads(result["content"])["recovered"])
        self.assertEqual(conn.commits, 1)

    def test_synthesis_refuses_unclaimed_collecting_assessment(self):
        class Cursor:
            def execute(self, *_args, **_kwargs): pass
            def fetchone(self): return {"id": 55, "status": "collecting"}
        class Conn:
            def cursor(self, **_): return Cursor()
            def close(self): pass
        with mock.patch.object(worker, "get_conn", return_value=Conn()):
            result = worker.handle_marketing_assessment_synthesis({"params": {"assessment_id": 55}})
        self.assertFalse(result["ok"])
        self.assertIn("collecting", result["error"])

    def test_poll_keeps_parent_task_collecting_after_child_queueing(self):
        class Cursor:
            def __init__(self):
                self.calls = []
                self.claimed = False

            def execute(self, sql, params=()):
                self.calls.append((" ".join(sql.split()), params))

            def fetchone(self):
                if not self.claimed:
                    self.claimed = True
                    return {"id": 99, "type": "marketing_audit", "params": {}}
                return None

        class Conn:
            def __init__(self):
                self.cursor_value = Cursor()
            def cursor(self, **_): return self.cursor_value
            def commit(self): pass
            def close(self): pass

        conn = Conn()
        result = {"ok": True, "content": "{}", "task_status": "collecting"}
        with mock.patch.object(worker, "get_conn", return_value=conn), \
             mock.patch.dict(worker.DISPATCH, {"marketing_audit": lambda _task: result}), \
             mock.patch.object(worker.marketing_assessments, "reconcile_for_child_task"):
            self.assertTrue(worker.poll())
        update = next(call for call in conn.cursor_value.calls if call[0].startswith("UPDATE tasks SET status=%s"))
        self.assertEqual(update[1][0], "collecting")

    def test_seo_handler_fake_db_keeps_sources_explicit_and_result_bounded(self):
        class Cursor(FakeCursor):
            def fetchone(self):
                sql = self.calls[-1][0]
                if "FROM brands" in sql: return {"id": 2, "project_id": 9, "name": "Test"}
                if "RETURNING id" in sql: return {"id": 44}
                return None
            def fetchall(self): return []
        class Conn:
            def __init__(self): self.c = Cursor()
            def cursor(self, **_): return self.c
            def commit(self): pass
            def close(self): pass
        crawl = {"status": "available", "pages": [], "broken_links": [], "sitemap": {"status": "available", "members": [], "unavailable": []}, "excluded": [], "bounded": {}}
        with mock.patch.object(worker, "get_conn", return_value=Conn()), \
             mock.patch.object(worker.seo_measurement, "crawl", return_value=crawl), \
             mock.patch.object(worker.seo_measurement, "make_findings", return_value=[]), \
             mock.patch.object(worker.seo_measurement, "query_pagespeed", return_value={"status": "source_unavailable"}), \
             mock.patch.object(worker.seo_measurement, "google_access", return_value={"status": "source_unavailable"}):
            result = worker.handle_seo_measurement({"id": 77, "params": {"brand_id": 2, "url": "https://example.test"}})
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(result["content"])["source_statuses"]["gsc"], "source_unavailable")
        self.assertLess(len(result["content"]), 20000)

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

    def test_truncated_primary_usage_survives_failed_fallback(self):
        response = SimpleNamespace(read=lambda: json.dumps({
            "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 25, "completion_tokens": 400,
                      "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 25},
        }).encode())
        with mock.patch.object(worker.urllib.request, "urlopen", return_value=response), \
             mock.patch.object(worker, "_raw_opencode_fallback", return_value={
                 "ok": False, "error": "fallback failed", "prompt_tokens": 7,
                 "completion_tokens": 3, "cost": 0.0, "model": "fallback",
             }):
            result = worker.call_zen("A verbose prompt", model="deepseek-v4-flash")
        self.assertFalse(result["ok"])
        self.assertEqual(result["prompt_tokens"], 32)
        self.assertEqual(result["completion_tokens"], 403)
        self.assertGreater(result["cost"], 0)
        self.assertEqual(result["incomplete_primary_model"], "deepseek-v4-flash")

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

    def test_outline_count_is_capped_before_substantive_validation(self):
        blocks = [{"type": "prose", "brief": f"Section {i}"} for i in range(20)]
        capped, original = worker._cap_outline_blocks(blocks)
        self.assertEqual(len(capped), worker.CONTENT_MAX_OUTLINE_BLOCKS)
        self.assertEqual(original, 20)
        self.assertEqual(capped[-1]["brief"], "Section 17")

    def test_compose_block_keyword_contract_is_local(self):
        block = {"type": "prose", "brief": "Explain", "markdown": "Useful qualitative advice.",
                 "keyword_target": True, "fact_ids": [], "sources": []}
        self.assertIn("target_keyword missing from keyword_target block",
                      worker._content_block_validate(block, "job search automation"))

    def test_hidden_brief_does_not_trigger_keyword_stuffing(self):
        block = {"type": "prose", "brief": "Explain the AI job search assistant category",
                 "markdown": "Compare the tools by workflow and evidence.",
                 "keyword_target": False, "fact_ids": [], "sources": []}
        self.assertNotIn(
            "target_keyword appears in an unflagged block",
            worker._content_block_validate(block, "AI job search assistant"),
        )

    def test_compose_parser_accepts_wrapped_and_direct_block_json(self):
        wrapped = worker._parse_composed_block('{"content":{"markdown":"Useful"}}', "prose")
        direct = worker._parse_composed_block('{"markdown":"Useful"}', "prose")
        string_wrapped = worker._parse_composed_block('{"content":"Useful"}', "prose")
        null_wrapper = worker._parse_composed_block('{"content":null,"markdown":"Useful"}', "prose")
        scalar = worker._parse_composed_block('"Useful"', "prose")
        plain = worker._parse_composed_block('Useful plain markdown.', "prose")
        paragraphs = worker._parse_composed_block('["First paragraph.","Second paragraph."]', "prose")
        self.assertEqual(wrapped, {"markdown": "Useful"})
        self.assertEqual(direct, wrapped)
        self.assertEqual(string_wrapped, wrapped)
        self.assertEqual(null_wrapper, wrapped)
        self.assertEqual(scalar, wrapped)
        self.assertEqual(plain, {"markdown": "Useful plain markdown."})
        self.assertEqual(paragraphs, {"markdown": "First paragraph.\n\nSecond paragraph."})
        self.assertEqual(worker._composed_output_shape('[1,2]'), "json_list")

    def test_compose_checkpoint_must_match_outline_prefix(self):
        outline = [{"type": "intro"}, {"type": "prose"}]
        checkpoint = [{"type": "heading", "heading": "Wrong block"}]
        failures = worker._compose_checkpoint_validate(outline, checkpoint, "keyword")
        self.assertTrue(any("does not match outline" in failure for failure in failures))

    def test_failure_first_aid_is_deterministic(self):
        category, action = worker.classify_failure("draft failed validation: invalid JSON")
        self.assertEqual(category, "deterministic validation")
        self.assertIn("validator", action)

    def test_needs_input_is_not_a_failure(self):
        result = worker._needs_input("CMS access needed", ["credential_ref"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["required_inputs"], ["credential_ref"])

    def test_operator_chore_is_whitelisted_and_silent(self):
        with mock.patch.object(worker, "_refresh_alert_snapshot") as refresh:
            result = worker.handle_operator_chore({
                "id": 99,
                "type": "operator_chore",
                "params": {"action": "recheck_credentials", "silent": True},
            })
        self.assertTrue(result["ok"])
        refresh.assert_called_once_with(refresh_host=False)
        rejected = worker.handle_operator_chore({"params": {"action": "run_any_shell"}})
        self.assertFalse(rejected["ok"])

    def test_task_usage_has_one_central_insert(self):
        cursor = FakeCursor()
        worker.record_task_usage(
            cursor,
            {"id": 4, "type": "content_outline", "params": {}},
            {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
        )
        inserts = [call for call in cursor.calls if "INSERT INTO token_usage" in call[0]]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0][1][1], 4)
        self.assertEqual(inserts[0][1][3:5], (10, 5))

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
