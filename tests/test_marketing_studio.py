import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import marketing_studio as studio


class MarketingStudioTests(unittest.TestCase):
    def test_profile_is_allowlisted_and_rejects_credentials(self):
        profile = studio.validate_profile({"positioning": "Practical workflow software", "audience": "Teams", "primary_goal": "Activation"})
        self.assertEqual(profile["positioning"], "Practical workflow software")
        with self.assertRaises(ValueError):
            studio.validate_profile({"positioning": "x", "api_key": "secret"})
        with self.assertRaises(ValueError):
            studio.validate_profile({"positioning": "token=abc"})
        with self.assertRaises(ValueError):
            studio.validate_profile({"positioning": "x", "logo_url": "https://user:pass@example.com/logo"})

    def test_work_item_is_brand_scoped_and_rejects_invalid_values(self):
        item = studio.validate_work_item({"brand_id": 7, "kind": "social_post", "channel": "linkedin", "title": "A useful update", "brief": {"source": "approved release note"}})
        self.assertEqual(item["brand_id"], 7)
        self.assertEqual(item["state"], "draft")
        with self.assertRaises(ValueError):
            studio.validate_work_item({"brand_id": 7, "kind": "social_post", "channel": "linkedin", "title": "x", "brief": {"nested": {"private_key": "abc"}}})
        with self.assertRaises(ValueError):
            studio.validate_work_item({"brand_id": 7, "kind": "social_post", "channel": "linkedin", "title": "x", "brief": {"source_url": "https://user:pass@example.com"}})
        for bad in (
            {"brand_id": 0, "kind": "social_post", "channel": "linkedin", "title": "x"},
            {"brand_id": 7, "kind": "social_post", "channel": "sms", "title": "x"},
            {"brand_id": 7, "kind": "social_post", "channel": "linkedin", "title": "x", "state": "sent"},
        ):
            with self.assertRaises(ValueError):
                studio.validate_work_item(bad)

    def test_render_is_draft_only_and_deterministic(self):
        profile = {"positioning": "Clear tools", "primary_goal": "Activation"}
        item = {"brand_id": 3, "kind": "email_campaign", "channel": "email", "title": "Welcome", "brief": {"approved_facts": ["Teams can review work in one place"], "source_url": "https://example.com/onboarding", "cta_text": "Read the guide"}}
        first = studio.render_work_item({"name": "Example"}, profile, item)
        second = studio.render_work_item({"name": "Example"}, profile, item)
        self.assertEqual(first, second)
        self.assertFalse(first["send"])
        self.assertFalse(first["publish"])
        self.assertIn("Teams can review work in one place", first["body"])
        self.assertIn("approved_facts", first["brief"])

    def test_missing_facts_needs_input_without_inventing_claims(self):
        result = studio.render_work_item("Customers Example", {}, {"brand_id": 1, "kind": "social_post", "channel": "linkedin", "title": "Draft", "brief": {}})
        self.assertEqual(result["brief"]["needs_input"], ["approved_facts"])
        self.assertIn("approved facts needed", result["body"])

    def test_video_brief_has_three_formats_and_bounded_timing(self):
        result = studio.render_work_item("Example", {}, {"brand_id": 1, "kind": "video_brief", "channel": "youtube", "title": "Launch", "brief": {"approved_facts": ["Approved fact"], "project_ui_asset": "asset-1"}})
        self.assertEqual(result["brief"]["formats"], ["9:16", "1:1", "16:9"])
        self.assertEqual(result["brief"]["duration_seconds"], 20)
        self.assertEqual(result["brief"]["voiceover"], "opt_in_only")
        self.assertEqual(sum(scene["duration"] for scene in result["brief"]["scenes"]), 20)

    def test_channel_setup_does_not_claim_account_creation(self):
        result = studio.render_work_item("Example", {}, {"brand_id": 1, "kind": "channel_setup", "channel": "instagram", "title": "Setup", "brief": {}})
        self.assertIn("exact title", result["brief"]["checklist"])
        self.assertEqual(result["brief"]["account_creation"], "not performed")

    def test_catalog_has_required_lifecycle_guardrails(self):
        self.assertGreaterEqual(len(studio.GTM_PLAYBOOKS), 12)
        ids = {play["id"] for play in studio.GTM_PLAYBOOKS}
        self.assertTrue({"welcome", "inactivity", "product_updates", "referral"} <= ids)
        inactivity = next(play for play in studio.GTM_PLAYBOOKS if play["id"] == "inactivity")
        self.assertIn("7 days", inactivity["trigger"])
        self.assertIn("suppressed", inactivity["guardrails"])


if __name__ == "__main__":
    unittest.main()
