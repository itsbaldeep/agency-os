import sys
import json
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import worker
from worker import _content_planning_context


class PlanningContextTests(unittest.TestCase):
    def test_missing_or_malformed_is_empty(self):
        for raw in (None, [], "bad", 1):
            self.assertEqual(_content_planning_context({"planning_context": raw}), {})

    def test_only_bounded_intent_fields_survive(self):
        result = _content_planning_context({"planning_context": {
            "audience": "a" * 1200, "hypothesis": "Test focused guidance",
            "facts": ["unverified"], "success_metric": "gsc_clicks",
            "evidence_note": {"invalid": True}, "secret": "not copied",
        }})
        self.assertEqual(len(result["audience"]), 1000)
        self.assertEqual(result["success_metric"], "gsc_clicks")
        self.assertNotIn("facts", result)
        self.assertNotIn("secret", result)
        self.assertNotIn("evidence_note", result)

    def test_research_chain_propagates_calendar_title_and_planning_context(self):
        class Cursor:
            def __init__(self, row):
                self.row = row
                self.calls = []

            def execute(self, sql, params=()):
                self.calls.append((sql, params))

            def fetchone(self):
                return self.row

        class Conn:
            def __init__(self, row):
                self.cursor_value = Cursor(row)

            def cursor(self, **_kwargs):
                return self.cursor_value

            def commit(self):
                pass

            def close(self):
                pass

        research_conn = Conn((41,))
        chain_conn = Conn((77,))
        planning = {"audience": "career changers", "hypothesis": "A checklist earns qualified search traffic", "success_metric": "gsc_clicks"}
        candidate = {"elements": [{"url": "https://competitor.test", "headings": [], "elements_used": [], "word_count": 10, "freshness": "unknown"}], "strongest": [], "weaknesses": [], "gaps": [], "element_strategy": "use steps", "facts": []}
        with mock.patch.object(worker, "set_task_progress"), \
             mock.patch.object(worker, "_fetch_clean", return_value=(True, "clean text", 10, "clean text")), \
             mock.patch.object(worker, "call_zen", return_value={"ok": True, "content": json.dumps(candidate), "model": "test"}), \
             mock.patch.object(worker, "get_conn", side_effect=[research_conn, chain_conn]), \
             mock.patch.object(worker, "_validate_research_payload", return_value=(candidate, [])):
            result = worker.handle_content_research({"id": 9, "params": {
                "target_keyword": "job search checklist", "competitor_urls": ["https://competitor.test"],
                "calendar_id": 12, "title": "Job Search Checklist for Career Changers",
                "planning_context": planning,
            }})

        self.assertTrue(result["ok"])
        chain_params = chain_conn.cursor_value.calls[0][1]
        outline_params = json.loads(chain_params[0])
        self.assertEqual(outline_params["calendar_id"], 12)
        self.assertEqual(outline_params["title"], "Job Search Checklist for Career Changers")
        self.assertEqual(outline_params["planning_context"], planning)

    def test_outline_persists_calendar_title_and_planning_context_in_structured_data(self):
        class Cursor:
            def __init__(self, rows):
                self.rows = list(rows)
                self.calls = []

            def execute(self, sql, params=()):
                self.calls.append((sql, params))

            def fetchone(self):
                return self.rows.pop(0)

        class Conn:
            def __init__(self, rows):
                self.cursor_value = Cursor(rows)

            def cursor(self, **_kwargs):
                return self.cursor_value

            def commit(self):
                pass

            def close(self):
                pass

        research = {"id": 41, "keyword_id": None, "target_keyword": "job search checklist", "elements": [], "strongest": [], "weaknesses": [], "gaps": [], "element_strategy": "use steps", "facts": []}
        outline_conn = Conn([research])
        persist_conn = Conn([{"id": 88}])
        planning = {"audience": "career changers", "hypothesis": "A checklist earns qualified search traffic", "success_metric": "gsc_clicks"}
        parsed = {"title": "Job Search Checklist", "blocks": [{"type": "intro", "brief": "Answer directly", "keyword_target": True}]}
        with mock.patch.object(worker, "set_task_progress"), \
             mock.patch.object(worker, "get_conn", side_effect=[outline_conn, persist_conn]), \
             mock.patch.object(worker, "call_zen", return_value={"ok": True, "content": json.dumps(parsed), "model": "test"}), \
             mock.patch.object(worker, "_draft_parse_json", return_value=parsed), \
             mock.patch.object(worker, "_content_outline_validate", return_value=[]):
            result = worker.handle_content_outline({"id": 10, "params": {
                "research_id": 41, "brand_id": 7, "calendar_id": 12,
                "title": "Job Search Checklist for Career Changers", "planning_context": planning,
            }})

        self.assertTrue(result["ok"])
        structured = json.loads(persist_conn.cursor_value.calls[0][1][3])
        self.assertEqual(structured["calendar_id"], 12)
        self.assertEqual(structured["planned_title"], "Job Search Checklist for Career Changers")
        self.assertEqual(structured["planning_context"], planning)
