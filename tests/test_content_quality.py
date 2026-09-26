import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from content_quality import validate_content


class ContentQualityTests(unittest.TestCase):
    def test_draft22_shape_reports_empty_faq_and_unresolved_image_as_warnings(self):
        blocks = [
            {"type": "intro", "markdown": "ATS resume formatting helps parsing."},
            {"type": "heading", "heading": "Visual examples: Good vs. bad ATS formatting"},
            {"type": "image_slot", "alt": "Comparison of resume formatting", "prompt": "Annotated comparison"},
            {"type": "heading", "heading": "Frequently asked questions about ATS resume formatting"},
        ]
        report = validate_content(blocks, "draft")
        self.assertFalse(report["ok"])
        self.assertFalse(report["blocking"])
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("unresolved_image", codes)
        self.assertIn("empty_faq", codes)

    def test_publish_promotes_unresolved_items_to_blockers(self):
        report = validate_content([
            {"type": "heading", "heading": "FAQ"},
            {"type": "image_slot", "alt": "Diagram", "prompt": "A diagram"},
        ], "publish")
        self.assertTrue(report["blocking"])
        self.assertTrue(all(item["severity"] == "blocker" for item in report["findings"]))

    def test_complete_visual_and_faq_pass(self):
        report = validate_content([
            {"type": "intro", "markdown": "A useful introduction."},
            {"type": "image_slot", "alt": "A clear process diagram", "prompt": "Process diagram",
             "url": "https://assets.example.test/process.svg"},
            {"type": "heading", "heading": "Frequently asked questions"},
            {"type": "faq", "brief": "Can I use a PDF?", "answer": "Check the employer's instructions."},
        ], "publish")
        self.assertTrue(report["ok"])

    def test_missing_payload_and_evidence_are_reported(self):
        report = validate_content([
            {"type": "prose", "markdown": ""},
            {"type": "table", "columns": ["A", "B"], "rows": [["x", "y"]]},
            {"type": "callout", "stat": "2.5MB", "label": "Limit"},
        ], "publish")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("empty_payload", codes)
        self.assertIn("missing_evidence", codes)
        self.assertIn("missing_sources", codes)

    def test_placeholder_markers_are_not_accepted(self):
        report = validate_content([
            {"type": "prose", "markdown": "[PLACEHOLDER: add conclusion]"},
            {"type": "image_slot", "alt": "Placeholder image", "prompt": "placeholder",
             "url": "https://assets.example.test/placeholder.svg"},
        ], "publish")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("placeholder_text", codes)
        self.assertIn("placeholder_asset", codes)

    def test_asset_prompt_metadata_does_not_trigger_visible_placeholder_check(self):
        report = validate_content([
            {"type": "image_slot", "alt": "A resume comparison", "prompt": "Placeholder brief for the asset team",
             "url": "https://assets.example.test/comparison.svg"},
        ], "publish")
        self.assertTrue(report["ok"])

    def test_consecutive_headings_are_reported_and_malformed_chart_is_safe(self):
        report = validate_content([
            {"type": "heading", "heading": "First section"},
            {"type": "heading", "heading": "Second section"},
            {"type": "chart", "data_series": []},
        ], "draft")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("orphan_heading", codes)
        self.assertIn("empty_payload", codes)


if __name__ == "__main__":
    unittest.main()
