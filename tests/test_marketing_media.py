import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import marketing_media as media


class MarketingMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "brands"
        self.patch = mock.patch.object(media, "ARTIFACT_ROOT", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_generates_brand_scoped_pngs_and_zip(self):
        result = media.create_media_artifacts({"name": "Alpha"}, {"positioning": "Clear workflows"}, {"id": 4, "brand_id": 7, "revision": 2, "kind": "social_post", "title": "Launch", "brief": {"approved_facts": ["Review work"]}})
        output_paths = [Path(row["path"]) for row in result["outputs"] if "path" in row and row["path"].endswith(".png")]
        self.assertEqual({path.name for path in output_paths}, {"avatar.png", "banner.png", "social-card.png", "carousel-01.png"})
        from PIL import Image
        with Image.open(output_paths[0]) as image:
            self.assertEqual(image.format, "PNG")
        archive = next(Path(row["path"]) for row in result["outputs"] if row.get("mime") == "application/zip")
        with zipfile.ZipFile(archive) as zipped:
            self.assertEqual(set(zipped.namelist()), {"avatar.png", "banner.png", "social-card.png", "carousel-01.png", "metadata.json"})

    def test_brand_and_item_paths_are_isolated_and_safe(self):
        result_a = media.create_media_artifacts("Alpha", {}, {"id": "a/../../escape", "brand_id": 1, "revision": 1, "kind": "social_post", "title": "A", "brief": {}})
        result_b = media.create_media_artifacts("Beta", {}, {"id": 2, "brand_id": 2, "revision": 1, "kind": "social_post", "title": "B", "brief": {}})
        self.assertIn("/brands/1/work/", result_a["outputs"][0]["path"])
        self.assertIn("/revision-1/", result_a["outputs"][0]["path"])
        self.assertIn("/brands/2/work/2/revision-1/", result_b["outputs"][0]["path"])
        self.assertNotEqual(result_a["outputs"][0]["path"], result_b["outputs"][0]["path"])

    def test_video_requires_owned_ui_asset_and_escapes_html(self):
        result = media.create_media_artifacts({"name": "<Alpha>"}, {}, {"id": 3, "brand_id": 8, "revision": 1, "kind": "video_brief", "title": '"Launch"', "brief": {}})
        self.assertIn("project_ui_asset", result["needs_input"])
        self.assertIn("approved_facts", result["needs_input"])
        composition = Path(next(row["path"] for row in result["outputs"] if row.get("mime") == "text/html"))
        source = composition.read_text()
        self.assertIn("&lt;Alpha&gt;", source)
        self.assertNotIn("<Alpha>", source)
        self.assertEqual(result["state"], "draft")
        self.assertFalse(result["reviewed"])

    def test_video_composition_uses_supplied_story(self):
        brand_root = self.root / "9"
        brand_root.mkdir(parents=True)
        ui = brand_root / "ui.png"
        from PIL import Image
        Image.new("RGB", (40, 40), "blue").save(ui)
        result = media.create_media_artifacts("Example", {}, {"id": 4, "brand_id": 9, "kind": "video_brief", "title": "Product reveal", "brief": {"approved_facts": ["Evidence-backed insight", "Reviewable draft"], "cta_text": "Open the report", "project_ui_asset": str(ui)}})
        index = Path(next(row["path"] for row in result["outputs"] if row.get("mime") == "text/html"))
        source = index.read_text()
        self.assertTrue(index.name == "index.html")
        self.assertIn("Evidence-backed insight", source)
        self.assertIn("Open the report", source)
        self.assertEqual(source.count('class="clip"'), 4)

    def test_rejects_ui_asset_outside_approved_roots(self):
        with self.assertRaises(ValueError):
                media.create_media_artifacts("Alpha", {}, {"brand_id": 1, "kind": "video_brief", "title": "X", "brief": {"project_ui_asset": "/tmp/owned.png"}})

    def test_long_text_wraps_within_safe_width(self):
        from PIL import Image, ImageDraw
        font = media._font(40)
        lines = media._wrap("This is a deliberately long approved brand statement for a compact card", font, 400)
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        self.assertTrue(all(draw.textbbox((0, 0), line, font=font)[2] <= 400 for line in lines))

    def test_rejects_symlinked_brand_before_creating_artifacts(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.root).mkdir(parents=True)
        (self.root / "7").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            media.create_media_artifacts("Alpha", {}, {"brand_id": 7, "kind": "social_post", "title": "X", "brief": {}})

    def test_runtime_check_failure_is_explicit(self):
        brand_root = self.root / "7"
        brand_root.mkdir(parents=True)
        ui = brand_root / "ui.png"
        from PIL import Image
        Image.new("RGB", (20, 20), "blue").save(ui)
        with mock.patch.object(media, "_runtime", return_value=("/bin/false", [], "test")):
            with self.assertRaisesRegex(RuntimeError, "check failed"):
                media.create_media_artifacts("Alpha", {}, {"brand_id": 7, "kind": "video_brief", "title": "X", "brief": {"approved_facts": ["Fact"], "project_ui_asset": str(ui)}})


if __name__ == "__main__":
    unittest.main()
