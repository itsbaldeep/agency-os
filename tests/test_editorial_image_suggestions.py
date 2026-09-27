import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from editorial_image_suggestions import build_suggestion, derive_intent, derive_query, rank_candidates, suggest_slots


class EditorialImageSuggestionTests(unittest.TestCase):
    def test_diagram_slot_is_not_stock_photo_eligible(self):
        slot = {"alt": "ATS resume formatting comparison", "brief": "Annotated side-by-side diagram"}
        intent = derive_intent(slot, "ATS resume formatting")
        self.assertEqual(intent["kind"], "explanatory_visual")
        self.assertFalse(intent["stock_appropriate"])
        request = derive_query(slot, "ATS resume formatting")
        self.assertIn("comparison", request["query"])

    def test_illustration_signal_classifies_without_stock_fallback(self):
        intent = derive_intent({"alt": "Illustration of resume parsing", "brief": "Editorial illustration"})
        self.assertEqual(intent["kind"], "explanatory_visual")
        self.assertFalse(intent["stock_appropriate"])

    def test_diagram_requirement_wins_over_photographic_context(self):
        intent = derive_intent({'alt': 'Office workspace diagram for a professional at a desk'})
        self.assertEqual(intent['kind'], 'explanatory_visual')
        self.assertFalse(intent['stock_appropriate'])

    def test_photo_slot_can_use_stock_candidate(self):
        slot = {"alt": "Professional reviewing a resume", "brief": "Office portrait"}
        result = build_suggestion(slot, [{"id": "p1", "provider": "pexels", "url": "https://images.example/p.jpg", "alt": "Professional resume review", "source_url": "https://pexels.com/photo/1"}], "Resume review")
        self.assertEqual(result["kind"], "stock_photo")
        self.assertIsNotNone(result["default"])
        self.assertTrue(result["default"]["requires_review"])
        self.assertFalse(result["default"]["reviewed"])

    def test_diagram_does_not_select_irrelevant_pexels_default(self):
        slot = {"alt": "Resume workflow diagram", "brief": "Clean annotated workflow"}
        result = build_suggestion(slot, [{"id": "p1", "provider": "pexels", "url": "https://images.example/p.jpg", "alt": "Person working in an office"}], "Resume parsing")
        self.assertIsNone(result["default"])
        self.assertTrue(result["needs_custom_visual"])

    def test_imported_stock_is_not_misclassified_as_owned_diagram(self):
        result = build_suggestion({'alt': 'Resume workflow diagram'}, [{
            'id': 9, 'asset_id': 9, 'source': 'project', 'url': 'https://assets.example/photo.jpg',
            'alt': 'Person looking at a resume workflow diagram',
            'provenance': {'provider': 'pexels', 'photographer': 'Photographer'}}])
        self.assertIsNone(result['default'])

    def test_stock_candidate_can_be_pending_import_default_with_provenance(self):
        slot = {"alt": "Professional reviewing a resume", "brief": "Office portrait"}
        result = build_suggestion(slot, [{"provider": "pexels", "provider_id": "p1",
                                          "thumbnail_url": "https://images.example/resume.jpg",
                                          "source_url": "https://pexels.com/photo/1",
                                          "alt": "Professional reviewing a resume"}], "Resume review")
        self.assertIsNotNone(result["default"])
        self.assertTrue(result["default"]["requires_review"])

    def test_unrelated_chart_is_not_default_for_resume_diagram(self):
        slot = {"alt": "Resume parsing workflow diagram", "brief": "Workflow diagram"}
        result = build_suggestion(slot, [{"id": "chart", "source": "project", "asset_id": 4,
                                          "url": "https://assets.example/revenue.png", "kind": "chart",
                                          "alt": "Revenue chart", "provenance": {"kind": "owned"}}], "ATS resume formatting")
        self.assertIsNone(result["default"])

    def test_project_visual_candidate_ranks_before_provider_and_prefills_metadata(self):
        slot = {"alt": "ATS parsing workflow", "brief": "Workflow diagram"}
        candidates = [
            {"id": "stock", "provider": "pexels", "thumbnail_url": "https://images.example/p.jpg", "alt": "Office desk"},
            {"id": "owned", "source": "project", "asset_id": 44, "url": "https://assets.example/diagram.png", "kind": "diagram", "alt": "Resume parsing workflow", "provenance": {"kind": "owned"}},
        ]
        result = build_suggestion(slot, candidates, "ATS resume formatting")
        self.assertEqual(result["default"]["id"], "owned")
        self.assertEqual(result["default"]["suggested_alt"], "Resume parsing workflow")
        self.assertTrue(result["default"]["requires_review"])

    def test_candidates_are_bounded_and_bad_urls_are_dropped(self):
        request = derive_query({"alt": "Resume photo", "brief": "Professional portrait"})
        candidates = [{"id": str(i), "url": "https://assets.example/%s.jpg" % i, "alt": "Resume professional photo", "provenance": {"kind": "owned"}} for i in range(9)]
        candidates.append({"id": "bad", "url": "http://unsafe.example/x.jpg"})
        result = rank_candidates(candidates, request, limit=99)
        self.assertEqual(len(result), 5)
        self.assertNotIn("bad", {item["id"] for item in result})

    def test_slot_contract_keeps_current_asset_first_and_unreviewed(self):
        blocks = [{"type": "image_slot", "alt": "Resume workflow diagram", "url": "https://assets.example/current.png",
                   "asset": {"id": 8, "provenance": {"kind": "owned"}}}]
        report = suggest_slots(blocks, stock_candidates=[{"provider_id": "p1", "provider": "pexels",
                                                          "thumbnail_url": "https://images.example/p.jpg", "alt": "Office desk"}],
                               title="ATS resume formatting")
        slot = report["slots"][0]
        self.assertEqual(slot["index"], 0)
        self.assertEqual(slot["candidates"][0]["id"], 8)
        self.assertEqual(slot["candidates"][0]["kind"], "library")
        self.assertEqual(slot["candidates"][0]["caption"], "")
        self.assertFalse(slot["candidates"][0]["reviewed"])
        self.assertTrue(slot["requires_review"])


if __name__ == "__main__":
    unittest.main()
