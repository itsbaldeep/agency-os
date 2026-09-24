import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from editorial_visuals import render_visual, validate_visual, visual_markdown


FACTS = [{"id": "f1", "claim": "The result was -4 units", "evidence_snippet": "The result was -4 units", "source_url": "https://news.example.test/report"}]


def base(kind, **extra):
    value = {"kind": kind, "title": "A title", "caption": "A caption"}
    value.update(extra)
    return value


class EditorialVisualTests(unittest.TestCase):
 def test_valid_editorial_example_and_escaping(self):
    visual = validate_visual(base("annotated_example", before="Old", after="New", notes=["Try this < safely"]), [])
    rendered = render_visual(visual)
    self.assertEqual(visual["type"], "editorial_visual")
    self.assertIn("&lt;", rendered)
    self.assertIn("Hypothetical example", visual_markdown(visual))


 def test_xss_is_escaped(self):
    visual = validate_visual(base("checklist", title="<script>alert(1)</script>", items=["<img src=x onerror=1>"]), [])
    rendered = render_visual(visual)
    self.assertNotIn("<script>", rendered)
    self.assertIn("&lt;script&gt;", rendered)


 def test_unsafe_image_url_rejected(self):
    with self.assertRaises(ValueError):
        validate_visual(base("image", url="http://127.0.0.1/a", alt="A descriptive image", credit="Source"), [])


 def test_chart_requires_facts_and_literal_numeric_grounding(self):
    payload = base("bar_chart", units="units", points=[{"label": "x", "value": -4, "fact_id": "f1"}, {"label": "y", "value": -4, "fact_id": "f1"}])
    visual = validate_visual(payload, FACTS)
    self.assertEqual(visual["sources"], [FACTS[0]["source_url"]])
    with self.assertRaises(ValueError):
        validate_visual({**payload, "points": [{"label": "x", "value": 5, "fact_id": "f1"}]}, FACTS)
    with self.assertRaises(ValueError):
        validate_visual(payload, [])


 def test_dimensions_and_nonfinite_values_rejected(self):
    payload = base("line_chart", units="units", points=[{"label": "x", "value": -4, "fact_id": "f1"}, {"label": "y", "value": -4, "fact_id": "f1"}])
    with self.assertRaises(ValueError):
        validate_visual({**payload, "width": 1}, FACTS)
    with self.assertRaises(ValueError):
        validate_visual({**payload, "points": [{"label": "x", "value": float("nan"), "fact_id": "f1"}, payload["points"][1]]}, FACTS)


 def test_comparison_constraints(self):
    visual = validate_visual(base("comparison", columns=["A", "B"], rows=[["one", "two"]]), [])
    self.assertIn("Editorial guidance", visual["editorial_label"])
    self.assertIn("| A | B |", visual_markdown(visual))
