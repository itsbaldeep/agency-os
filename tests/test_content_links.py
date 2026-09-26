import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import content_links


class ContentLinksTests(unittest.TestCase):
    def setUp(self):
        self.pages = {
            "https://site.example/robots.txt": (200, b"User-agent: *\nAllow: /\nSitemap: /sitemap.xml"),
            "https://site.example/sitemap.xml": (200, b"<urlset><url><loc>/</loc></url><url><loc>/blog/post</loc></url><url><loc>/help/start</loc></url></urlset>"),
            "https://site.example/": (200, b'<html><title>Home</title><a href="/blog/post">Blog</a><a href="/missing">Missing</a><a href="https://external.example/ok">OK</a><a href="https://external.example/not-found">Bad</a></html>', "https://site.example/", "text/html"),
            "https://site.example/blog/post": (200, b'<html><title>Post</title><a href="https://external.example/ok">OK again</a><a href="https://external.example/blocked">Blocked</a></html>', "https://site.example/blog/post", "text/html"),
            "https://site.example/help/start": (200, b'<html><title>Help</title></html>', "https://site.example/help/start", "text/html"),
            "https://site.example/missing": (404, b"not found"),
        }

    def fetch(self, url):
        return self.pages[url]

    def external(self, url):
        return {
            "https://external.example/ok": (200, b"ok"),
            "https://external.example/not-found": (404, b"gone"),
            "https://external.example/blocked": (403, b"no"),
        }[url]

    def test_inventory_covers_landing_blog_help_and_internal_404(self):
        result = content_links.audit_links("https://site.example/", fetcher=self.fetch, external_fetcher=self.external, sleep=lambda _: None)
        by_url = {item["url"]: item for item in result["page_inventory"]}
        self.assertEqual(by_url["https://site.example/"]["category"], "landing")
        self.assertEqual(by_url["https://site.example/blog/post"]["category"], "blog")
        self.assertEqual(by_url["https://site.example/help/start"]["category"], "help")
        self.assertEqual(by_url["https://site.example/missing"]["state"], "broken")
        self.assertEqual(result["internal_links"][0]["source_url"], "https://site.example/")

    def test_external_states_distinguish_broken_blocked_and_ok(self):
        result = content_links.audit_links("https://site.example/", fetcher=self.fetch, external_fetcher=self.external, sleep=lambda _: None)
        states = {item["url"]: item["state"] for item in result["external_links"]}
        self.assertEqual(states["https://external.example/ok"], "ok")
        self.assertEqual(states["https://external.example/not-found"], "broken")
        self.assertEqual(states["https://external.example/blocked"], "blocked")

    def test_external_checks_are_deduplicated_and_cached_per_source(self):
        calls = []

        def external(url):
            calls.append(url)
            return (200, b"ok")

        result = content_links.audit_links("https://site.example/", fetcher=self.fetch, external_fetcher=external, sleep=lambda _: None)
        self.assertEqual(calls.count("https://external.example/ok"), 1)
        ok_records = [item for item in result["external_links"] if item["url"].endswith("/ok")]
        self.assertEqual(len(ok_records), 2)
        self.assertEqual(ok_records[1]["reason"], "cache")

    def test_external_budget_reports_unchecked_coverage(self):
        result = content_links.audit_links("https://site.example/", fetcher=self.fetch, external_fetcher=self.external, external_budget=1, sleep=lambda _: None)
        self.assertEqual(result["coverage"]["external_checked"], 1)
        self.assertTrue(result["coverage"]["external_budget_exhausted"])
        self.assertGreater(result["coverage"]["external_unchecked"], 0)
        self.assertTrue(any(item.get("reason") == "external_budget_exhausted" for item in result["external_links"]))

    def test_timeout_or_safe_fetch_failure_is_unknown(self):
        def external(url):
            raise TimeoutError("network timeout")

        result = content_links.audit_links("https://site.example/", fetcher=self.fetch, external_fetcher=external, sleep=lambda _: None)
        self.assertTrue(all(item["state"] == "unknown" for item in result["external_links"]))

    def test_safe_fetch_http_error_strings_keep_404_and_403_distinct(self):
        def external(url):
            if url.endswith("/not-found"):
                return {"ok": False, "error": "http_status_404"}
            if url.endswith("/blocked"):
                return {"ok": False, "error": "http_status_403"}
            return (200, b"ok")

        result = content_links.audit_links("https://site.example/", fetcher=self.fetch, external_fetcher=external, sleep=lambda _: None)
        states = {item["url"]: item["state"] for item in result["external_links"]}
        self.assertEqual(states["https://external.example/not-found"], "broken")
        self.assertEqual(states["https://external.example/blocked"], "blocked")

    def test_page_cap_is_explicit(self):
        result = content_links.audit_links("https://site.example/", max_pages=1, fetcher=self.fetch, external_fetcher=self.external, sleep=lambda _: None)
        self.assertEqual(result["coverage"]["pages_fetched"], 1)
        self.assertGreater(result["coverage"]["pages_unfetched"], 0)
        self.assertTrue(all(item["reason"] == "page_budget_exhausted" for item in result["page_inventory"][1:]))

    def test_invalid_start_rejected(self):
        with self.assertRaises(ValueError):
            content_links.audit_links("javascript:alert(1)")

    def test_document_links_checks_markdown_sources_and_editorial_sources(self):
        blocks = [
            {"type": "prose", "markdown": "Read [the guide](https://external.example/ok)."},
            {"type": "editorial_visual", "kind": "bar_chart", "points": [{"source_url": "https://external.example/not-found"}]},
            {"type": "image_slot", "image_url": "https://external.example/blocked", "alt": "Image"},
        ]
        result = content_links.check_document_links(blocks, "https://site.example/blog/post", fetcher=self.external)
        states = {item["url"]: item["state"] for item in result["links"]}
        self.assertEqual(states["https://external.example/ok"], "ok")
        self.assertEqual(states["https://external.example/not-found"], "broken")
        self.assertNotIn("https://external.example/blocked", states)
        self.assertEqual(len(result["blocking"]), 1)
        self.assertEqual(result["findings"][0]["rule"], "content_link_broken")

    def test_document_link_failures_are_unverified_not_blocking(self):
        blocks = [{"type": "prose", "markdown": "See [source](https://external.example/ok)."}]
        result = content_links.check_document_links(blocks, "https://site.example/", fetcher=lambda _: {"ok": False, "error": "timeout"})
        self.assertEqual(result["blocking"], [])
        self.assertEqual(result["unverified"][0]["state"], "unknown")
        self.assertEqual(result["findings"][0]["rule"], "content_link_unverified")


if __name__ == "__main__":
    unittest.main()
