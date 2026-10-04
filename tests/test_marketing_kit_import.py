import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import marketing_kit_import as importer


class Cursor:
    def __init__(self, brand, existing=None):
        self.brand = brand
        self.existing = existing
        self.next_id = 91
        self.last = None
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if "FROM brands b" in sql:
            self.last = self.brand
        elif "FROM marketing_work_items" in sql:
            self.last = self.existing
        elif "RETURNING id" in sql:
            self.last = {"id": self.next_id}
            self.next_id += 1
        else:
            self.last = None

    def fetchone(self):
        value, self.last = self.last, None
        return value

    def fetchall(self):
        value = [] if self.last is None else ([self.last] if isinstance(self.last, dict) else self.last)
        self.last = None
        return value


class Connection:
    def __init__(self, brand, existing=None):
        self.cursor_value = Cursor(brand, existing)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **kwargs): return self.cursor_value
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): pass


class MarketingKitImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        self.package = self.root / "operator-kit"
        self.package.mkdir(parents=True)
        (self.package / "caption.txt").write_text("historical caption", encoding="utf-8")
        (self.package / "image.png").write_bytes(b"png")
        (self.package / "manifest.json").write_text(json.dumps({
            "session_id": "session-42",
            "items": [{"kind": "social_post", "channel": "instagram", "title": "Historical launch",
                       "body": "Review this draft", "brief": {"source": "old notes", "approved": True},
                       "files": ["caption.txt", "image.png"]}],
        }), encoding="utf-8")
        self.brand = {"id": 4, "project_id": 9, "local_path": str(self.root), "lifecycle": "active"}
        self.artifacts = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.artifacts.cleanup()
        self.tmp.cleanup()

    def task(self):
        return {"id": 55, "params": {"brand_id": 4, "source_dir": "operator-kit", "manifest_path": "manifest.json"}}

    def test_import_creates_reviewable_draft_and_owned_media(self):
        conn = Connection(self.brand)
        with mock.patch.object(importer, "ARTIFACT_ROOT", Path(self.artifacts.name)):
            result = importer.handle(self.task(), lambda: conn)
        self.assertTrue(result["ok"])
        self.assertEqual(result["item_ids"], [91])
        self.assertFalse(result["published"])
        self.assertFalse(result["sent"])
        self.assertIn('"item_ids":[91]', result["content"])
        self.assertEqual(conn.commits, 1)
        brief = json.loads([params for sql, params in conn.cursor_value.calls if "UPDATE marketing_work_items SET brief" in sql][0][0])
        self.assertTrue(brief["needs_review"])
        self.assertFalse(brief["current_offer"])
        self.assertFalse(brief["approved"])
        self.assertEqual(len(brief["media"]["outputs"]), 2)
        self.assertEqual(len(brief["media"]["outputs"][0]["sha256"]), 64)
        self.assertTrue((Path(self.artifacts.name) / "4/work/91/imported/image.png").is_file())

    def test_same_manifest_is_idempotent(self):
        conn = Connection(self.brand, [{"id": 91}, {"id": 92}])
        with mock.patch.object(importer, "ARTIFACT_ROOT", Path(self.artifacts.name)):
            result = importer.handle(self.task(), lambda: conn)
        self.assertTrue(result["ok"])
        self.assertTrue(result["idempotent"])
        self.assertEqual(result["item_ids"], [91, 92])
        self.assertIn('"idempotent":true', result["content"])
        self.assertEqual(conn.commits, 0)

    def test_rejects_hidden_secret_html_and_escape_inputs(self):
        cases = [
            {"files": [".env"]},
            {"files": ["../image.png"]},
            {"body": "<script>alert(1)</script>"},
            {"brief": {"api_key": "secret-value"}},
        ]
        for override in cases:
            manifest = {"items": [{"kind": "social_post", "channel": "instagram", "title": "Draft", "body": "Text", "files": ["image.png"], **override}]}
            (self.package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            conn = Connection(self.brand)
            with mock.patch.object(importer, "ARTIFACT_ROOT", Path(self.artifacts.name)):
                result = importer.handle(self.task(), lambda: conn)
            self.assertFalse(result["ok"])
            self.assertEqual(conn.commits, 0)

    def test_inactive_brand_and_source_outside_linked_root_are_rejected(self):
        conn = Connection({**self.brand, "lifecycle": "soft_parked"})
        self.assertFalse(importer.handle(self.task(), lambda: conn)["ok"])
        conn = Connection(self.brand)
        task = {"params": {"brand_id": 4, "source_dir": str(Path(self.tmp.name) / "outside"), "manifest_path": "manifest.json"}}
        self.assertFalse(importer.handle(task, lambda: conn)["ok"])


if __name__ == "__main__":
    unittest.main()
