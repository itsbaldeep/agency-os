import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import seo_measurement as seo


class SeoMeasurementTests(unittest.TestCase):
    def test_url_parser_and_fields(self):
        self.assertEqual(seo.normalize_url("/x/", "https://Example.test"), "https://example.test/x/")
        self.assertEqual(seo.normalize_url("https://Example.test:8443/x#f"), "https://example.test:8443/x")
        self.assertEqual(seo.normalize_url("https://[::1]:8443/x"), "https://[::1]:8443/x")
        self.assertEqual(seo.normalize_url("https://example.test:notaport/x"), None)
        self.assertFalse(seo.same_origin("https://example.test:notaport/x", "https://example.test"))
        self.assertIsNone(seo.normalize_url("javascript:alert(1)"))
        fields = seo.extract_html(b'<title> Home </title><meta name="description" content="d"><a href="/x">x</a><img> ', "https://example.test/")
        self.assertEqual(fields["title"], "Home")
        self.assertEqual(fields["missing_alt"], 1)
        self.assertEqual(fields["links"], ["https://example.test/x"])

    def test_headings_schema_canonical_and_noindex_are_extracted(self):
        fields = seo.extract_html(b'<title>T</title><meta name="robots" content="noindex"><link rel="canonical" href="/x#fragment"><h1>One</h1><h2>Two</h2><script type="application/ld+json">{}</script>', "https://example.test/")
        self.assertEqual(fields["h1_count"], 1)
        self.assertTrue(fields["jsonld"])
        self.assertTrue(fields["noindex"])
        self.assertEqual(fields["canonical"], "https://example.test/x")

    def test_sitemap_robots_and_bounded_same_origin_crawl(self):
        pages = {
            "https://example.test/robots.txt": (200, b"User-agent: *\nAllow: /\nSitemap: /sitemap.xml"),
            "https://example.test/sitemap.xml": (200, b"<urlset><url><loc>https://example.test/</loc></url><url><loc>/x</loc></url></urlset>"),
            "https://example.test/": (200, b'<title>Home</title><a href="/missing">bad</a><a href="https://other.test/no">out</a>'),
            "https://example.test/x": (200, b'<title>X</title>'),
            "https://example.test/missing": (404, b"not found"),
        }
        def fetch(url):
            if url not in pages: raise AssertionError("unexpected fetch " + url)
            return pages[url]
        result = seo.crawl("https://example.test", max_pages=2, fetcher=fetch, sleep=lambda _: None)
        self.assertEqual([p["url"] for p in result["pages"]], ["https://example.test/", "https://example.test/x"])
        self.assertEqual(result["broken_links"], [])  # page cap prevents the third fetch
        result = seo.crawl("https://example.test", max_pages=3, fetcher=fetch, sleep=lambda _: None)
        self.assertEqual(result["broken_links"][0]["url"], "https://example.test/missing")
        self.assertEqual(result["broken_links"][0]["source_url"], "https://example.test/")

    def test_nested_sitemap_and_path_robots(self):
        pages = {
            "https://example.test/robots.txt": (200, b"User-agent: *\nDisallow: /private\nSitemap: /index.xml"),
            "https://example.test/index.xml": (200, b"<sitemapindex><sitemap><loc>/child.xml</loc></sitemap></sitemapindex>"),
            "https://example.test/child.xml": (200, b"<urlset><url><loc>/ok</loc></url><url><loc>/private/no</loc></url></urlset>"),
            "https://example.test/": (200, b"<title>Home</title><a href='/private/no'>no</a>"),
            "https://example.test/ok": (200, b"<title>OK</title>"),
        }
        result = seo.crawl("https://example.test/", fetcher=lambda u: pages[u], sleep=lambda _: None)
        self.assertEqual([p["url"] for p in result["pages"]], ["https://example.test/", "https://example.test/ok"])
        self.assertNotIn("https://example.test/private/no", [p["url"] for p in result["pages"]])
        self.assertTrue(result["sitemap"]["status"] == "available")

    def test_redirect_is_recorded_and_canonical_finding_is_stable(self):
        pages = {
            "https://example.test/robots.txt": (200, b"User-agent: *\nAllow: /"),
            "https://example.test/sitemap.xml": (404, b""),
            "https://example.test/": (200, b"<title>Home</title><link rel='canonical' href='/wrong'>", "https://example.test/new"),
        }
        result = seo.crawl("https://example.test/", max_pages=1, fetcher=lambda u: pages[u], sleep=lambda _: None)
        page = result["pages"][0]
        self.assertEqual(page["requested_url"], "https://example.test/")
        self.assertEqual(page["final_url"], "https://example.test/new")
        findings = seo.make_findings(result)
        canonical = [f for f in findings if f["rule"] == "canonical_mismatch"]
        self.assertEqual(canonical[0]["evidence_id"], seo.evidence_id("canonical_mismatch", "https://example.test/new"))

    def test_deterministic_ids_and_comparison(self):
        self.assertEqual(seo.evidence_id("rule", "u", True), seo.evidence_id("rule", "u", True))
        self.assertEqual(seo.compare_runs({"counts": {"pages": 1}}, {"counts": {"pages": 2}})["delta"], {"pages": 1})

    def test_api_normalizers_reject_bad_shapes(self):
        self.assertEqual(seo.normalize_pagespeed({})["status"], "source_unavailable")
        self.assertEqual(seo.normalize_gsc({"rows": []})["status"], "available")
        self.assertEqual(seo.normalize_ga4({"metricHeaders": [], "rows": []})["status"], "available")
        self.assertEqual(seo.normalize_gsc({"responseAggregationType": "byPage"})["rows"], 0)
        self.assertEqual(seo.normalize_ga4({"metricHeaders": [{"name": "sessions"}]})["totals"], {"sessions": 0})
        self.assertEqual(seo.google_metric("https://evil.test", "x", {})["status"], "source_unavailable")

    def test_pagespeed_requires_key_and_ga_metrics_normalize(self):
        with mock.patch.dict(seo.os.environ, {}, clear=True):
            self.assertEqual(seo.query_pagespeed("https://example.test")["status"], "source_unavailable")
        gsc = seo.normalize_gsc({"rows": [{"clicks": 2, "impressions": 4, "position": 3}]})
        self.assertEqual((gsc["clicks"], gsc["impressions"], gsc["ctr"], gsc["weighted_average_position"]), (2, 4, .5, 3))
        ga = seo.normalize_ga4({"metricHeaders": [{"name":"sessions"},{"name":"totalUsers"},{"name":"keyEvents"}], "rows": [{"metricValues":[{"value":"2"},{"value":"1"},{"value":"0"}]}]})
        self.assertEqual(ga["totals"], {"sessions": 2, "totalUsers": 1, "keyEvents": 0})
        self.assertEqual(len(ga["row_summaries"]), 1)
        self.assertEqual(gsc["row_summaries"][0]["position"], 3)

    def test_non_html_is_excluded_and_invalid_schema_is_a_finding(self):
        pages = {
            "https://example.test/robots.txt": (200, b"User-agent: *\nAllow: /"),
            "https://example.test/sitemap.xml": (200, b"<urlset><url><loc>/</loc></url><url><loc>/file.pdf</loc></url></urlset>"),
            "https://example.test/": (200, b"<title>Home</title><meta name='description' content='D'><link rel='canonical' href='/'><h1>Home</h1><script type='application/ld+json'>{bad}</script>", "https://example.test/", "text/html"),
            "https://example.test/file.pdf": (200, b"pdf", "https://example.test/file.pdf", "application/pdf"),
        }
        result = seo.crawl("https://example.test/", fetcher=lambda url: pages[url], sleep=lambda _: None)
        self.assertTrue(any(item["reason"] == "non_html" for item in result["excluded"]))
        self.assertTrue(any(item["rule"] == "invalid_jsonld" for item in seo.make_findings(result)))

    def test_google_missing_access_and_signing_does_not_print_key(self):
        self.assertEqual(seo.google_access("/does/not/exist")["status"], "source_unavailable")
        proc = mock.Mock(returncode=0, stdout=b"signature", stderr=b"")
        with mock.patch.object(seo.subprocess, "run", return_value=proc) as run:
            token = seo.sign_jwt({"alg": "RS256"}, {"x": 1}, "PRIVATE-SECRET")
        self.assertNotIn("PRIVATE-SECRET", token)
        self.assertNotIn("PRIVATE-SECRET", repr(run.call_args.kwargs))

    def test_signing_closes_both_fds_on_failure(self):
        closed = []
        with mock.patch.object(seo.os, "close", side_effect=lambda fd: closed.append(fd)), mock.patch.object(seo.os, "write", side_effect=OSError("pipe")):
            with self.assertRaises(OSError): seo.sign_jwt({}, {}, "key")
        self.assertEqual(len(closed), 2)

    def test_secret_free_result_shape(self):
        result = {"audit_id": 1, "run_id": "r", "source_statuses": {"gsc": "source_unavailable"}, "counts": {}, "comparison": {}}
        self.assertNotIn("private_key", json.dumps(result))

    def test_worker_dispatch_is_registered(self):
        import worker
        self.assertIs(worker.DISPATCH["seo_measurement"], worker.handle_seo_measurement)


if __name__ == "__main__":
    unittest.main()
