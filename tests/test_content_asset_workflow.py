import copy
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import content_asset_workflow as workflow


class FakeCursor:
    def __init__(self, rows=None, library=None, registered=None):
        self.rows = list(rows or [])
        self.library = list(library or [])
        self.registered = registered
        self.statements = []
        self.last_sql = ""

    def execute(self, sql, args=()):
        self.last_sql = sql
        self.statements.append((sql, args))

    def fetchone(self):
        if "INSERT INTO content_assets" in self.last_sql:
            return copy.deepcopy(self.registered)
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return copy.deepcopy(self.library)


class FakeConnection:
    def __init__(self, rows=None, library=None, registered=None):
        self.cursor_obj = FakeCursor(rows, library, registered)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **kwargs):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class ConnectionFactory:
    def __init__(self, *connections):
        self.connections = list(connections)
        self.used = []

    def __call__(self):
        connection = self.connections.pop(0)
        self.used.append(connection)
        return connection


class WorkflowTests(unittest.TestCase):
    def stock_slot(self, alt="Professional reviewing a resume"):
        return {"type": "image_slot", "alt": alt,
                "brief": "Office portrait of a professional reviewing a resume",
                "prompt": "Office portrait of a professional reviewing a resume"}

    def diagram_slot(self):
        return {"type": "image_slot", "alt": "Resume parsing workflow diagram",
                "brief": "Annotated resume parsing workflow diagram",
                "prompt": "Annotated resume parsing workflow diagram"}

    def item(self, blocks=None, body=None, structured=None):
        blocks = blocks if blocks is not None else [self.stock_slot()]
        return {"id": 22, "brand_id": 4, "project_id": 8, "lifecycle": "active",
                "status": "draft", "title": "Resume review guide",
                "body": body if body is not None else "_[Image planned: Professional reviewing a resume]_",
                "content_blocks": blocks, "structured": structured if structured is not None else {"facts": []}}

    def metadata(self):
        return {"sha256": "a" * 64, "object_key": "editorial/aa/" + "a" * 64 + ".png",
                "url": "https://assets.example/resume.png", "alt": "Professional reviewing a resume",
                "caption": "A candidate reviews a resume.",
                "provenance": {"provider": "pexels", "source_url": "https://www.pexels.com/photo/7/"}}

    def candidate(self):
        return {"provider": "pexels", "provider_id": "7",
                "thumbnail_url": "https://images.pexels.com/resume.jpg",
                "source_url": "https://www.pexels.com/photo/7/",
                "alt": "Professional reviewing a resume"}

    def factory(self, initial, final=None, library=None, registered=None):
        return ConnectionFactory(FakeConnection([initial], library=library),
                                 FakeConnection([final or copy.deepcopy(initial)], registered=registered))

    def execute(self, initial, final=None, library=None, registered=None, key=True):
        factory = self.factory(initial, final, library, registered)
        env = {"PEXELS_API_KEY": "test-key"} if key else {}
        with mock.patch.dict(os.environ, env, clear=not key):
            with mock.patch.object(workflow.content_assets, "search_assets", return_value=[self.candidate()]) as search:
                with mock.patch.object(workflow.content_assets, "import_stock", return_value=self.metadata()) as import_stock:
                    result = workflow.handle({"params": {"content_item_id": 22}}, factory)
        return result, factory, search, import_stock

    def update_args(self, factory):
        args = next(args for sql, args in factory.used[-1].cursor_obj.statements if "UPDATE content_items" in sql)
        return json.loads(args[0]), args[1], json.loads(args[2]), args[3]

    def test_fingerprint_excludes_only_mutable_suggestion_report(self):
        first = workflow.fingerprint(self.item())
        changed = self.item(structured={"facts": [], "asset_suggestions": {"checked_at": "later"}})
        self.assertEqual(first, workflow.fingerprint(changed))
        changed["title"] = "Changed"
        self.assertNotEqual(first, workflow.fingerprint(changed))

    def test_automatic_stock_selection_registers_unreviewed_asset_and_quality_blocks(self):
        initial = self.item()
        result, factory, search, import_stock = self.execute(initial, registered={"id": 91, "metadata": self.metadata()})
        self.assertTrue(result["ok"])
        self.assertEqual(search.call_count, 2)
        import_stock.assert_called_once_with("7")
        blocks, body, structured, _ = self.update_args(factory)
        self.assertFalse(blocks[0]["reviewed"])
        self.assertEqual(blocks[0]["selection_source"], "automatic")
        self.assertIn("![Professional reviewing a resume](https://assets.example/resume.png)", body)
        self.assertTrue(any(f.get("code") == "unreviewed_asset" for f in structured["quality_report"]["findings"]))
        expected = workflow.fingerprint({**initial, "content_blocks": blocks, "body": body, "structured": structured})
        self.assertEqual(structured["asset_suggestions"]["fingerprint"], expected)

    def test_stale_final_row_makes_no_database_mutation(self):
        initial = self.item()
        final = self.item()
        final["title"] = "Changed elsewhere"
        result, factory, search, import_stock = self.execute(initial, final=final)
        self.assertFalse(result["ok"])
        self.assertIn("changed", result["error"].lower())
        write = factory.used[-1]
        self.assertFalse(any("UPDATE content_items" in sql or "INSERT INTO content_assets" in sql for sql, _ in write.cursor_obj.statements))
        self.assertEqual(write.commits, 0)

    def test_existing_resolved_image_is_preserved_without_import(self):
        block = self.stock_slot()
        block.update({"url": "https://assets.example/existing.png", "reviewed": True,
                      "asset": {"id": 12, "url": "https://assets.example/existing.png"},
                      "caption": "Existing caption"})
        initial = self.item([block], body="![Professional reviewing a resume](https://assets.example/existing.png)\n\nExisting caption")
        result, factory, search, import_stock = self.execute(initial)
        self.assertTrue(result["ok"])
        import_stock.assert_not_called()
        self.assertEqual(self.update_args(factory)[0], [block])

    def test_diagram_never_imports_stock_and_reports_custom_asset(self):
        result, factory, search, import_stock = self.execute(self.item([self.diagram_slot()]))
        self.assertTrue(result["ok"])
        search.assert_not_called()
        import_stock.assert_not_called()
        self.assertEqual(self.update_args(factory)[2]["asset_suggestions"]["slots"][0]["status"], "needs_custom_asset")

    def test_missing_provider_key_is_visible_without_provider_call(self):
        result, factory, search, _ = self.execute(self.item(), key=False)
        self.assertTrue(result["ok"])
        search.assert_not_called()
        entry = self.update_args(factory)[2]["asset_suggestions"]["slots"][0]
        self.assertEqual(entry["provider_state"], "unavailable")
        self.assertIn("unavailable", entry["reason"].lower())

    def test_visual_base_body_is_replaced_with_same_asset_body(self):
        structured = {"facts": [], "visual_base_body": "_[Image planned: Professional reviewing a resume]_"}
        result, factory, _, _ = self.execute(self.item(structured=structured), registered={"id": 91, "metadata": self.metadata()})
        self.assertTrue(result["ok"])
        self.assertIn("![Professional reviewing a resume](https://assets.example/resume.png)", self.update_args(factory)[2]["visual_base_body"])

    def test_body_replacement_is_caption_aware_and_idempotent(self):
        old = {"alt": "Old resume photo", "url": "https://assets.example/old.png", "caption": "Old caption"}
        new = {"alt": "New resume photo", "url": "https://assets.example/new.png", "caption": "New caption"}
        body = "![Old resume photo](https://assets.example/old.png)\n\nOld caption"
        replaced = workflow.replace_image_body(body, old, new)
        self.assertEqual(replaced, "![New resume photo](https://assets.example/new.png)\n\nNew caption")
        self.assertEqual(workflow.replace_image_body(replaced, old, new), replaced)

    def test_slots_queries_are_bounded_and_deduplicated(self):
        blocks = [self.stock_slot() for _ in range(5)]
        body = "\n\n".join("_[Image planned: Professional reviewing a resume]_" for _ in blocks)
        result, factory, search, import_stock = self.execute(self.item(blocks, body=body), registered={"id": 91, "metadata": self.metadata()})
        self.assertTrue(result["ok"])
        self.assertLessEqual(search.call_count, 2)
        self.assertLessEqual(import_stock.call_count, 4)
        self.assertEqual(self.update_args(factory)[2]["asset_suggestions"]["skipped_slots"], [4])


if __name__ == "__main__":
    unittest.main()
