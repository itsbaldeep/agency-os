import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import growth_planner
import seo_cleanup


class SeoCleanupTests(unittest.TestCase):
    def setUp(self):
        self.findings = [
            {"evidence_id": "d1", "rule": "missing_description", "url": "https://trueapply.in/blog/a", "observed": "missing", "expected": "non-empty", "ghost_post_id": "p1"},
            {"evidence_id": "c1", "rule": "canonical_mismatch", "url": "https://trueapply.in/blog/b", "observed": "https://trueapply.in/blog/old", "expected": "https://trueapply.in/blog/b"},
        ]

    def test_plan_groups_owned_repairs_and_is_stable(self):
        first = seo_cleanup.build_cleanup_plan(self.findings, audit_id=7, revision="run-1", owned_origin="https://trueapply.in")
        second = seo_cleanup.build_cleanup_plan(self.findings, audit_id=7, revision="run-1", owned_origin="https://trueapply.in")
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertEqual([g["source_kind"] for g in first["groups"]], ["ghost_metadata", "repo_redirect"])
        self.assertEqual(first["groups"][1]["items"][0]["destination"], "https://trueapply.in/blog/b")

    def test_missing_description_without_editorial_excerpt_stays_unresolved(self):
        plan = seo_cleanup.build_cleanup_plan([dict(self.findings[0], ghost_post_id=None)], audit_id=7)
        self.assertNotIn("proposal", plan["groups"][0]["items"][0])
        with_excerpt = dict(self.findings[0], excerpt="Truthful resume tailoring for experienced professionals.")
        plan = seo_cleanup.build_cleanup_plan([with_excerpt], audit_id=7)
        self.assertEqual(plan["groups"][0]["items"][0]["proposal"]["meta_description"], with_excerpt["excerpt"].rstrip("."))

    def test_receipt_requires_precondition_destination_and_revision(self):
        plan = seo_cleanup.build_cleanup_plan(self.findings, audit_id=7, revision="run-1")
        item = plan["groups"][0]["items"][0]
        good = {"precondition_hash": item["precondition_hash"], "destination": item["destination"], "status": "applied"}
        self.assertTrue(seo_cleanup.verify_receipt(item, good, revision="run-1")["ok"])
        self.assertEqual(seo_cleanup.verify_receipt(item, dict(good, destination="https://evil.test"), revision="run-1")["reason"], "destination_mismatch")
        self.assertEqual(seo_cleanup.verify_receipt(item, good, revision="run-2")["reason"], "revision_mismatch")

    def test_unowned_urls_are_skipped(self):
        plan = seo_cleanup.build_cleanup_plan(self.findings + [{"rule": "missing_title", "url": "https://other.test/x"}], owned_origin="https://trueapply.in")
        self.assertEqual(sum(g["count"] for g in plan["groups"]), 2)

    def test_ghost_executor_updates_only_description_and_verifies_readback(self):
        class Client:
            def __init__(self): self.calls = []; self.post = {"id": "p1", "meta_description": "", "updated_at": "r1"}
            def request(self, method, path, payload=None):
                self.calls.append((method, path, payload))
                if method == "GET": return {"posts": [dict(self.post)]}
                self.post["meta_description"] = payload["posts"][0]["meta_description"]
                return {"posts": [dict(self.post)]}
        item = {"source_kind": "ghost_metadata", "ghost_post_id": "p1", "destination": "https://trueapply.in/blog/x",
                "proposal": {"meta_description": "Evidence based resume tailoring guidance."},
                "precondition": {"content_revision": "r1"}, "precondition_hash": "h"}
        receipt = seo_cleanup.apply_ghost_metadata(item, {}, client=Client())
        self.assertEqual(receipt["status"], "verified")

    def test_rollback_preserves_an_empty_original_description(self):
        class Client:
            def __init__(self): self.post = {"id": "p1", "meta_description": "new", "updated_at": "r1"}
            def request(self, method, path, payload=None):
                if method == "GET": return {"posts": [dict(self.post)]}
                self.post["meta_description"] = payload["posts"][0]["meta_description"]
                return {"posts": [dict(self.post)]}
        item = {"source_kind": "ghost_metadata", "ghost_post_id": "p1", "destination": "https://trueapply.in/blog/x", "precondition": {"content_revision": "r1"}, "precondition_hash": "h"}
        receipt = seo_cleanup.rollback_ghost_metadata(item, {"before": {"meta_description": ""}}, {}, client=Client())
        self.assertEqual(receipt["after"]["meta_description"], "")

    def test_ghost_enrichment_rejects_out_of_scope_credential_path(self):
        with self.assertRaises(ValueError):
            seo_cleanup.enrich_ghost_findings([], {"credential_path": "/tmp/secret", "credential_ref": "GHOST_API"})

    def test_generic_publication_root_is_required_and_project_scoped(self):
        with tempfile.TemporaryDirectory(dir="/home/agency/engagements") as project:
            env = Path(project) / "marketing.env"
            env.write_text("GENERIC_GHOST_KEY=fixture\n", encoding="utf-8")
            destination = {"project_root": project, "credential_root": project, "credential_path": str(env), "credential_ref": "GENERIC_GHOST_KEY"}
            self.assertEqual(seo_cleanup._credential_context(destination), env.resolve())
            with self.assertRaises(ValueError):
                seo_cleanup._credential_context({"project_path": project, "credential_path": str(env), "credential_ref": "GENERIC_GHOST_KEY"})


class GrowthPlannerTests(unittest.TestCase):
    def test_existing_human_queue_is_preserved_and_capped(self):
        existing = [{"kind": "article", "title": "Human choice", "planned_date": "2030-01-01", "status": "accepted"}]
        result = growth_planner.recommend({"findings": [{"rule": "missing_description", "url": "https://trueapply.in/blog/a"}]}, existing, max_articles=1)
        self.assertEqual(result["articles"][0]["title"], "Human choice")
        self.assertEqual(result["articles"][0]["planned_date"], "2030-01-01")

    def test_no_findings_means_no_fabricated_topics(self):
        result = growth_planner.recommend({"findings": []}, [])
        self.assertEqual(result["articles"], [])
        self.assertFalse(result["evidence_available"])

    def test_query_is_ranked_before_generic_finding(self):
        audit = {"brand_context": {"query_terms": ["resume"]}, "sources": {"gsc": {"query": {"row_summaries": [
            {"keys": ["truepal"], "impressions": 99},
            {"keys": ["truthful resume tailoring"], "impressions": 4},
        ]}}}, "findings": [{"rule": "canonical_mismatch", "url": "https://trueapply.in/a"}]}
        result = growth_planner.recommend(audit, [])
        self.assertEqual(result["articles"][0]["target_keyword"], "truthful resume tailoring")
        self.assertEqual(result["repairs"][0]["rule"], "canonical_mismatch")

    def test_owner_feedback_creates_help_lane_without_demand_claim(self):
        result = growth_planner.recommend({"brand_context": {"help_topics": ["How to configure a workspace", "How to review a report", "How to export results"]}}, [], owner_feedback=True)
        self.assertEqual(len(result["articles"]), 0)
        self.assertEqual(len(result["help"]), 3)
        self.assertEqual(result["help"][0]["evidence_status"], "owner_feedback")

    def test_stale_machine_suggestions_are_replaced_but_accepted_entries_remain(self):
        existing = [
            {"kind": "article", "title": "Old machine idea", "status": "suggested"},
            {"kind": "article", "title": "Owner approved", "status": "accepted"},
        ]
        result = growth_planner.recommend({"sources": {"gsc": {"query": {"row_summaries": [{"keys": ["resume tailoring"], "impressions": 2}]}}}}, existing)
        titles = [item["title"] for item in result["articles"]]
        self.assertNotIn("Old machine idea", titles)
        self.assertIn("Owner approved", titles)

    def test_same_query_refresh_can_represent_a_new_machine_candidate(self):
        result = growth_planner.recommend({"audit_id": 2, "sources": {"gsc": {"query": {"row_summaries": [{"keys": ["resume tailoring"], "impressions": 5}]}}}}, [{"kind": "article", "title": "Resume tailoring", "status": "suggested", "audit_id": 1}])
        self.assertEqual(result["articles"][0]["target_keyword"], "resume tailoring")
        self.assertEqual(result["articles"][0]["evidence"]["audit_id"], 2)

    def test_zero_gsc_owner_goal_fills_open_article_slot_with_honest_evidence(self):
        result = growth_planner.recommend({"audit_id": 9, "brand_context": {"goals": [{"title": "How to configure a workspace", "keyword": "workspace setup", "hypothesis": "Owners need a clear setup path."}]}, "sources": {"crawl": {"pages": [{"url": "https://example.test/", "fields": {"title": "Example"}}]}}, "competitor_urls": ["https://competitor.test"]}, [{"kind": "article", "title": "Existing outline", "status": "outline"}], owner_feedback=True, max_articles=2)
        self.assertEqual(len(result["articles"]), 2)
        self.assertEqual(result["articles"][1]["evidence_status"], "owner_goal_hypothesis")
        self.assertIn("unverified", result["articles"][1]["rationale"])

    def test_generic_brand_context_drives_topics_and_journey_gaps(self):
        audit = {
            "brand_context": {
                "query_terms": ["warehouse", "inventory"],
                "goals": [{"title": "Warehouse inventory setup", "keyword": "warehouse inventory", "hypothesis": "Setup friction is owner-reported."}],
                "journey_stages": [{"from": "visitors", "to": "trial_started", "hypothesis": "Trial conversion needs review."}],
            },
            "sources": {"gsc": {"query": {"row_summaries": [{"keys": ["warehouse inventory"], "impressions": 4}, {"keys": ["resume tailoring"], "impressions": 99}]}}, "crawl": {"pages": [{"url": "https://example.test/", "fields": {"title": "Example"}}]}},
            "activation": {"signup_cohort_totals": {"visitors": 10, "trial_started": 2}},
        }
        result = growth_planner.recommend(audit, [], owner_feedback=True)
        self.assertEqual(result["articles"][0]["target_keyword"], "warehouse inventory")
        self.assertTrue(any(g.get("from_stage") == "visitors" for g in result["gaps"]))
        self.assertFalse(any("resume" in str(item).lower() for item in result["articles"]))


if __name__ == "__main__":
    unittest.main()
