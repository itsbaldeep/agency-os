import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import search_discovery as discovery


class SearchDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "property": "https://example.test/",
            "sitemaps": ["https://example.test/sitemap.xml"],
            "urls": ["https://example.test/blog/post"],
        }
        self.calls = []

    def api(self, request, timeout=15):
        self.calls.append((request.method, request.full_url, request.data))
        if request.full_url.endswith("/sitemaps"):
            return {"sitemap": [{"path": "https://example.test/already.xml"}]}
        if request.method == "POST":
            return {"inspectionResult": {"indexStatusResult": {
                "verdict": "PASS", "coverageState": "Submitted and indexed",
                "robotsTxtState": "ALLOWED", "indexingState": "INDEXING_ALLOWED",
            }}}
        return {}

    @mock.patch.object(discovery.public_fetch, "_validate_target", return_value=object())
    def test_inspect_is_read_only_and_uses_read_scope(self, _public):
        result = discovery.discover(self.config, token="token", request=self.api)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["mode"], "inspect")
        self.assertEqual([method for method, _, _ in self.calls], ["GET", "POST"])
        self.assertNotIn("PUT", [method for method, _, _ in self.calls])

    @mock.patch.object(discovery.public_fetch, "_validate_target", return_value=object())
    def test_submit_is_idempotent_and_only_submits_new_sitemap(self, _public):
        config = {**self.config, "sitemaps": ["https://example.test/already.xml", "https://example.test/new.xml"], "urls": []}
        reads = [0]
        def api(request, timeout=15):
            if request.method == "GET":
                reads[0] += 1
                return {"sitemap": [{"path": "https://example.test/already.xml"}]} if reads[0] == 1 else {
                    "sitemap": [{"path": "https://example.test/already.xml"}, {"path": "https://example.test/new.xml", "isPending": False}]}
            return {}
        result = discovery.discover(config, submit=True, token="token", request=api)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["sitemaps"]["submitted"], ["https://example.test/new.xml"])
        self.assertEqual(result["sitemaps"]["skipped"][0]["reason"], "already_submitted")
        self.assertEqual(reads[0], 2)

    @mock.patch.object(discovery.public_fetch, "_validate_target", return_value=object())
    def test_unrelated_inventory_entry_does_not_verify_requested_sitemap(self, _public):
        config = {**self.config, "urls": [], "sitemaps": ["https://example.test/requested.xml"]}
        def api(request, timeout=15):
            return {"sitemap": [{"path": "https://example.test/unrelated.xml"}]} if request.method == "GET" else {}
        result = discovery.discover(config, submit=True, token="token", request=api)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["inventory"]["status"], "partial")
        self.assertEqual(result["inventory"]["entries"][0]["path"], "https://example.test/unrelated.xml")

    @mock.patch.object(discovery.public_fetch, "_validate_target", return_value=object())
    def test_empty_successful_put_is_accepted(self, _public):
        reads = [0]
        def api(request, timeout=15):
            if request.method == "GET":
                reads[0] += 1
                return {"sitemap": []} if reads[0] == 1 else {"sitemap": [{"path": "https://example.test/sitemap.xml"}]}
            if request.method == "PUT":
                return io.BytesIO(b"")
            return {"inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}}
        result = discovery.discover({**self.config, "urls": []}, submit=True, token="token", request=api)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["sitemaps"]["submitted"], ["https://example.test/sitemap.xml"])

    @mock.patch.object(discovery.public_fetch, "_validate_target", return_value=object())
    def test_partial_submission_receipt_survives_later_failure(self, _public):
        calls = []
        def api(request, timeout=15):
            calls.append(request.method)
            if request.method == "GET":
                return {"sitemap": []}
            if len([item for item in calls if item == "PUT"]) == 2:
                raise RuntimeError("simulated failure")
            return {}
        config = {**self.config, "sitemaps": ["https://example.test/one.xml", "https://example.test/two.xml"], "urls": []}
        result = discovery.discover(config, submit=True, token="token", request=api)
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["sitemaps"]["submitted"], ["https://example.test/one.xml"])

    @mock.patch.object(discovery.public_fetch, "_validate_target", return_value=object())
    def test_missing_inspection_verdict_is_unavailable(self, _public):
        def api(request, timeout=15):
            return {"sitemap": []} if request.method == "GET" else {}
        result = discovery.discover(self.config, token="token", request=api)
        self.assertEqual(result["status"], "source_unavailable")
        self.assertIsNone(result["inspections"][0]["verdict"])

    def test_rejects_mismatched_origin_credentials_queries_and_caps(self):
        for key, value in (("sitemaps", ["https://other.test/sitemap.xml"]),
                           ("sitemaps", ["https://example.test/sitemap.xml?token=secret"]),
                           ("urls", ["https://user:pass@example.test/post"]),
                           ("urls", ["https://example.test/post?x=1"])):
            result = discovery.discover({**self.config, key: value}, token="token", request=self.api)
            self.assertEqual(result["status"], "source_unavailable")
        result = discovery.discover({**self.config, "urls": ["https://example.test/" for _ in range(51)]}, token="token", request=self.api)
        self.assertEqual(result["status"], "source_unavailable")

    @mock.patch.object(discovery.public_fetch, "_validate_target", return_value=object())
    def test_domain_property_matches_target_and_does_not_claim_indexing_api(self, _public):
        result = discovery.discover({**self.config, "property": "sc-domain:example.test"}, token="token", request=self.api)
        self.assertEqual(result["status"], "available")
        self.assertNotIn("request_indexing", json.dumps(result))

    def test_scope_selection_is_explicit(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as handle:
            json.dump({"client_email": "svc@example.test", "private_key": "private"}, handle)
            handle.flush()
            with mock.patch.object(discovery, "sign_jwt", return_value="assertion") as sign:
                discovery.access_token(handle.name, submit=False, token_request=lambda _: {"access_token": "token"})
                readonly = sign.call_args.args[1]["scope"]
                discovery.access_token(handle.name, submit=True, token_request=lambda _: {"access_token": "token"})
                writable = sign.call_args.args[1]["scope"]
        self.assertEqual(readonly, discovery.READ_SCOPE)
        self.assertEqual(writable, discovery.WRITE_SCOPE)


if __name__ == "__main__":
    unittest.main()
