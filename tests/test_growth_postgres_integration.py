"""Optional isolated PostgreSQL integration for the growth feedback loop.

Run with GROWTH_FIXTURE_DSN pointing at a disposable database created from
018_growth_feedback_loop.sql and 019_growth_delivery_state.sql. It never
defaults to the Agency OS production database.
"""
import json
import os
import sys
import unittest

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover
    psycopg2 = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import worker


@unittest.skipUnless(os.environ.get("GROWTH_FIXTURE_DSN") and psycopg2, "isolated growth PostgreSQL fixture not configured")
class GrowthPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_get_conn = worker.get_conn
        worker.get_conn = lambda: psycopg2.connect(os.environ["GROWTH_FIXTURE_DSN"])

    @classmethod
    def tearDownClass(cls):
        worker.get_conn = cls.original_get_conn

    def task(self, task_id, task_type, params):
        return {"id": task_id, "type": task_type, "params": params}

    def test_refresh_demotes_machine_suggestion_and_preserves_human_choice(self):
        conn = worker.get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO growth_recommendations (brand_id,audit_id,kind,title,target_keyword,rank,rationale,evidence,status) VALUES (31,1,'article','Old machine topic','old',1,'old','{}','suggested'),(31,1,'article','Human choice','approved',1,'human','{}','accepted')")
        conn.commit(); conn.close()
        result = worker.handle_growth_plan(self.task(901, "growth_plan", {"brand_id": 31, "audit_id": 1, "owner_feedback": True}))
        self.assertTrue(result["ok"], result)
        conn = worker.get_conn(); cur = conn.cursor()
        cur.execute("SELECT title,status FROM growth_recommendations WHERE brand_id=31")
        rows = dict(cur.fetchall()); conn.close()
        self.assertEqual(rows["Old machine topic"], "dismissed")
        self.assertEqual(rows["Human choice"], "accepted")

    def test_cleanup_approval_stale_gate_idempotence_and_notification_retry(self):
        result = worker.handle_seo_cleanup(self.task(902, "seo_cleanup", {"brand_id": 31, "audit_id": 1, "owned_origin": "https://trueapply.in"}))
        self.assertTrue(result["ok"], result)
        info = json.loads(result["content"]); batch_id = info["batch_id"]; plan_hash = info["plan_hash"]
        destination = {"credential_path": "/home/agency/engagements/trueapply/.env", "credential_ref": "fixture"}
        blocked = worker.handle_seo_cleanup(self.task(903, "seo_cleanup", {"brand_id": 31, "audit_id": 1, "phase": "apply", "batch_id": batch_id, "approved_plan_hash": plan_hash, "approved": True, "destination": destination}))
        self.assertFalse(blocked["ok"])
        conn = worker.get_conn(); cur = conn.cursor(); cur.execute("UPDATE seo_cleanup_batches SET status='approved' WHERE id=%s", (batch_id,)); conn.commit(); conn.close()
        worker.seo_cleanup.apply_ghost_metadata = lambda item, destination: {"status": "verified", "destination": item.get("destination"), "precondition_hash": item.get("precondition_hash")}
        worker.seo_cleanup.verify_public_metadata = lambda url, expected: {"status": "verified", "meta_description": expected}
        worker.post_discord = lambda text: False
        applied = worker.handle_seo_cleanup(self.task(904, "seo_cleanup", {"brand_id": 31, "audit_id": 1, "phase": "apply", "batch_id": batch_id, "approved_plan_hash": plan_hash, "approved": True, "destination": destination}))
        self.assertTrue(applied["ok"], applied)
        again = worker.handle_seo_cleanup(self.task(905, "seo_cleanup", {"brand_id": 31, "audit_id": 1, "phase": "apply", "batch_id": batch_id, "approved_plan_hash": plan_hash, "approved": True, "destination": destination}))
        self.assertIn("already_verified", again["content"])
        pending = worker.handle_seo_cleanup(self.task(906, "seo_cleanup_notify", {"brand_id": 31, "batch_id": batch_id}))
        self.assertFalse(pending["ok"])
        worker.post_discord = lambda text: True
        sent = worker.handle_seo_cleanup(self.task(907, "seo_cleanup_notify", {"brand_id": 31, "batch_id": batch_id}))
        self.assertTrue(sent["ok"])
