import base64
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from ghost_publisher import (GhostAdminClient, GhostPublishError, content_digest,
                             publish, render_pipeline_html, _ghost_metadata)


class VoidHTMLTests(unittest.TestCase):
    def test_void_image_serializations_match_but_changed_source_does_not(self):
        from ghost_publisher import _normal_html
        self.assertEqual(_normal_html('<img src="https://example.com/a.png"/>'),
                         _normal_html('<img src="https://example.com/a.png">'))
        self.assertNotEqual(_normal_html('<img src="https://example.com/a.png"/>'),
                            _normal_html('<img src="https://example.com/b.png">'))


class FakeClient:
    def __init__(self, existing=None):
        self.calls = []
        self.existing = existing
        self.post = None

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET" and "/slug/" in path:
            if self.existing:
                return {"posts": [self.existing]}
            raise GhostPublishError("Ghost API returned HTTP 404")
        if method == "POST":
            self.post = {**payload["posts"][0], "id": "ghost-1",
                         "updated_at": "2026-09-24T00:00:00.000Z", "status": "draft"}
            return {"posts": [self.post]}
        if method == "GET" and "/ghost/api/admin/posts/ghost-1/" in path:
            return {"posts": [self.post]}
        if method == "PUT":
            self.post["status"] = "published"
            return {"posts": [{"id": "ghost-1", "status": "published"}]}
        raise AssertionError((method, path))


def item():
    return {"id": 23, "title": "A useful article", "body": "A useful article",
            "content_blocks": [{"type": "prose", "markdown": "Keep the evidence visible."}],
            "structured": {"facts": []}}


class GhostPublisherTests(unittest.TestCase):
    def test_digest_is_deterministic_and_exact(self):
        first = content_digest(item())
        self.assertEqual(first, content_digest(dict(item())))
        changed = dict(item(), meta_description="A reviewed description.")
        self.assertNotEqual(first, content_digest(changed))
        with self.assertRaisesRegex(GhostPublishError, "digest"):
            publish(item(), {"endpoint": "http://localhost:2370"}, "bad", client=FakeClient())

    def test_creates_draft_reads_back_then_publishes(self):
        fake = FakeClient()
        result = publish(item(), {"endpoint": "http://localhost:2370", "base_url": "https://trueapply.in/blog"}, content_digest(item()), client=fake)
        self.assertEqual(result["status"], "published")
        self.assertEqual([call[0] for call in fake.calls], ["GET", "POST", "GET", "PUT", "GET"])
        self.assertEqual(fake.calls[1][2]["posts"][0]["status"], "draft")
        self.assertEqual(fake.calls[1][2]["posts"][0]["slug"], "a-useful-article")
        self.assertEqual(result["url"], "https://trueapply.in/blog/a-useful-article/")
        html = fake.calls[1][2]["posts"][0]["html"]
        self.assertIn("agency-content-card", html)
        self.assertIn("pipeline-article", html)
        self.assertIn("Keep the evidence visible", html)

    def test_metadata_defaults_and_reviewed_values_are_sent_and_read_back(self):
        value = dict(item(), meta_title="Reviewed title", meta_description="Reviewed description",
                     custom_excerpt="Reviewed excerpt")
        fake = FakeClient()
        publish(value, {"endpoint": "http://localhost:2370", "base_url": "https://example.com/blog"}, content_digest(value), client=fake)
        post = fake.calls[1][2]["posts"][0]
        self.assertEqual(post["meta_title"], "Reviewed title")
        self.assertEqual(post["meta_description"], "Reviewed description")
        self.assertEqual(post["custom_excerpt"], "Reviewed excerpt")

    def test_explicit_metadata_preserves_punctuation_and_length_is_validated(self):
        value = dict(item(), meta_title="ATS-ready resume: C++ / Python",
                     meta_description="Use a job-specific, evidence-based summary -- without inventing claims.",
                     custom_excerpt="A short, editorial excerpt -- with punctuation.")
        fake = FakeClient()
        publish(value, {"endpoint": "http://localhost:2370", "base_url": "https://example.com/blog"}, content_digest(value), client=fake)
        post = fake.calls[1][2]["posts"][0]
        self.assertEqual(post["meta_title"], value["meta_title"])
        self.assertEqual(post["meta_description"], value["meta_description"])
        self.assertEqual(post["custom_excerpt"], value["custom_excerpt"])
        invalid = dict(item(), meta_description="x" * 2001)
        with self.assertRaisesRegex(GhostPublishError, "meta_description"):
            content_digest(invalid)

    def test_feature_image_uses_reviewed_managed_article_image(self):
        value = dict(item(), content_blocks=[{"type": "prose", "markdown": "A useful article."}, {"type": "image_slot", "brief": "cover",
            "alt": "A resume cover", "caption": "A reviewed cover", "url": "https://assets.example/old.png",
            "image_url": "https://assets.example/old.png", "reviewed": True,
            "asset": {"sha256": "a" * 64, "object_key": "editorial/" + "a" * 64 + ".png",
                      "provenance": {"kind": "owned"}}}])
        fake = FakeClient()
        with mock.patch("content_assets.read_core_asset", return_value=b"png"), \
             mock.patch("content_assets.copy_to_engagement", return_value={"url": "https://media.example/cover.png", "object_key": "editorial/" + "a" * 64 + ".png"}):
            approved = content_digest(value)
            result = publish(value, {"endpoint": "http://localhost:2370", "base_url": "https://example.com/blog", "asset_storage": {"endpoint": "http://storage", "access_key": "a", "secret_key": "b", "bucket": "public", "public_base": "https://media.example"}}, approved, client=fake)
        self.assertEqual(result["digest"], approved)
        post = fake.calls[1][2]["posts"][0]
        self.assertEqual(post["feature_image"], "https://media.example/cover.png")
        self.assertEqual(post["feature_image_alt"], "A resume cover")
        self.assertEqual(post["feature_image_caption"], "A reviewed cover")

    def test_empty_first_image_does_not_hide_later_image(self):
        value = dict(item(), content_blocks=[
            {"type": "image_slot", "brief": "empty", "alt": "Empty", "reviewed": True,
             "asset": {"sha256": "b" * 64, "object_key": "editorial/" + "b" * 64 + ".png",
                       "provenance": {"kind": "owned"}}},
            {"type": "prose", "markdown": "A useful article."},
            {"type": "image_slot", "brief": "cover", "alt": "Cover", "url": "https://assets.example/cover.png",
             "image_url": "https://assets.example/cover.png", "reviewed": True,
             "asset": {"sha256": "c" * 64, "object_key": "editorial/" + "c" * 64 + ".png",
                       "provenance": {"kind": "owned"}}}])
        fake = FakeClient()
        def copied(metadata, data, storage):
            return {"url": "https://media.example/" + metadata["sha256"][:1] + ".png", "object_key": metadata["object_key"]}
        with mock.patch("content_assets.read_core_asset", return_value=b"png"), mock.patch("content_assets.copy_to_engagement", side_effect=copied):
            publish(value, {"endpoint": "http://localhost:2370", "base_url": "https://example.com/blog", "asset_storage": {"endpoint": "http://storage", "access_key": "a", "secret_key": "b", "bucket": "public", "public_base": "https://media.example"}}, content_digest(value), client=fake)
        self.assertEqual(fake.calls[1][2]["posts"][0]["feature_image"], "https://media.example/c.png")

    def test_long_title_slug_ends_at_word_boundary(self):
        value = item()
        value["title"] = "Resume bullet points without metrics: show scope without inventing numbers"
        fake = FakeClient()
        publish(value, {"endpoint": "http://localhost:2370", "base_url": "https://trueapply.in/blog"},
                content_digest(value), client=fake)
        self.assertEqual(fake.calls[1][2]["posts"][0]["slug"],
                         "resume-bullet-points-without-metrics-show-scope-without-inventing")

    def test_prepare_mode_never_puts(self):
        fake = FakeClient()
        result = publish(item(), {"endpoint": "http://localhost:2370", "base_url": "https://trueapply.in/blog"}, content_digest(item()),
                         publish=False, client=fake)
        self.assertEqual(result["status"], "draft")
        self.assertNotIn("PUT", [call[0] for call in fake.calls])

    def test_search_discovery_is_opt_in_and_receipt_contains_published_url(self):
        fake = FakeClient()
        destination = {"endpoint": "http://localhost:2370", "base_url": "https://example.com/blog",
                       "search_discovery": {"enabled": True, "property": "https://example.com/",
                                             "sitemaps": ["https://example.com/sitemap.xml"], "urls": []}}
        with mock.patch("search_discovery.discover", return_value={"status": "available", "mode": "submit", "property": "https://example.com/", "sitemaps": {"submitted": []}, "inspections": []}) as discover:
            result = publish(item(), destination, content_digest(item()), client=fake)
        self.assertEqual(result["search_discovery"]["status"], "available")
        config = discover.call_args.args[0]
        self.assertTrue(discover.call_args.kwargs["submit"])
        self.assertIn(result["url"], config["urls"])
        self.assertTrue(destination["search_discovery"]["enabled"])

    def test_search_discovery_failure_does_not_fail_publication_or_prepare(self):
        fake = FakeClient()
        destination = {"endpoint": "http://localhost:2370", "base_url": "https://example.com/blog",
                       "search_discovery": {"enabled": True, "property": "https://example.com/"}}
        with mock.patch("search_discovery.discover", side_effect=RuntimeError("unavailable")):
            result = publish(item(), destination, content_digest(item()), client=fake)
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["search_discovery"]["status"], "source_unavailable")

        private = FakeClient()
        with mock.patch("search_discovery.discover") as discover:
            draft = publish(item(), destination, content_digest(item()), publish=False, client=private)
        self.assertEqual(draft["status"], "draft")
        discover.assert_not_called()

    def test_unrelated_existing_slug_is_not_overwritten(self):
        existing = {"id": "other", "tags": [{"name": "someone-else"}]}
        with self.assertRaisesRegex(GhostPublishError, "not owned"):
            publish(item(), {"endpoint": "http://localhost:2370"}, content_digest(item()),
                    client=FakeClient(existing))

    def test_matching_existing_marker_is_idempotent(self):
        marker = "#agency-content-23-" + content_digest(item())[:16]
        fake = FakeClient({"id": "ghost-1", "tags": [{"name": marker}], **_ghost_metadata(item()),
                           "updated_at": "2026-09-24T00:00:00.000Z", "status": "draft"})
        fake.post = {"id": "ghost-1", "html": render_pipeline_html(item()), "status": "draft", **_ghost_metadata(item())}
        result = publish(item(), {"endpoint": "http://localhost:2370"}, content_digest(item()),
                         publish=False, client=fake)
        self.assertEqual(result["post_id"], "ghost-1")
        self.assertNotIn("POST", [call[0] for call in fake.calls])

    def test_endpoint_and_error_do_not_leak_secret(self):
        with self.assertRaisesRegex(GhostPublishError, "HTTPS"):
            publish(item(), {"endpoint": "http://100.64.0.1:2370"}, content_digest(item()), client=FakeClient())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("BLOG_AGENCY_ADMIN_KEY=abc:def\n")
            with self.assertRaisesRegex(GhostPublishError, "id:hex-secret"):
                publish(item(), {"endpoint": "http://localhost:2370", "env_file": ".env",
                                 "project_path": directory, "credential_ref": "BLOG_AGENCY_ADMIN_KEY"}, content_digest(item()))

    def test_jwt_has_ghost_admin_shape(self):
        client = GhostAdminClient("http://localhost:2370", "kid:" + "ab" * 32)
        header, payload, signature = client.token.split(".")
        decode = lambda value: json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        self.assertEqual(decode(header)["kid"], "kid")
        self.assertEqual(decode(payload)["aud"], "/admin/")
        self.assertTrue(signature)

    def test_published_retry_performs_no_second_write(self):
        marker = '#agency-content-23-' + content_digest(item())[:16]
        fake = FakeClient({'id': 'ghost-1', 'tags': [{'name': marker}], **_ghost_metadata(item())})
        fake.post = {'id': 'ghost-1', 'html': render_pipeline_html(item()), 'status': 'published', **_ghost_metadata(item())}
        result = publish(item(), {'base_url': 'https://example.com/blog'}, content_digest(item()), client=fake)
        self.assertEqual(result['status'], 'published')
        self.assertTrue(all(method == 'GET' for method, _, _ in fake.calls))

    def test_modified_ghost_html_is_never_published(self):
        marker = '#agency-content-23-' + content_digest(item())[:16]
        fake = FakeClient({'id': 'ghost-1', 'tags': [{'name': marker}]})
        fake.post = {'id': 'ghost-1', 'html': render_pipeline_html(item()).replace('Keep the evidence visible.', 'Changed claim.'), 'status': 'draft'}
        with self.assertRaisesRegex(GhostPublishError, 'read-back'):
            publish(item(), {'base_url': 'https://example.com/blog'}, content_digest(item()), client=fake)
        self.assertTrue(all(method == 'GET' for method, _, _ in fake.calls))

    def test_active_markup_is_rejected_before_network(self):
        value = item()
        value['content_blocks'] = [{'type': 'prose', 'markdown': '<script>alert(1)</script>'}]
        fake = FakeClient()
        with self.assertRaisesRegex(GhostPublishError, 'blocked HTML'):
            publish(value, {'base_url': 'https://example.com/blog'}, content_digest(value), client=fake)
        self.assertEqual(fake.calls, [])

    def test_markdown_intro_uses_block_container_not_nested_paragraph(self):
        value = item()
        value['content_blocks'] = [{'type': 'intro', 'markdown': 'First **paragraph**.\n\nSecond paragraph.'}]
        html = render_pipeline_html(value)
        self.assertIn("<div class='lead'><p>", html)
        self.assertNotIn("<p class='lead'>", html)
        self.assertIn('<strong>paragraph</strong>', html)
        self.assertIn('<p>Second paragraph.</p></div>', html)

    def test_managed_asset_is_copied_without_mutating_approved_item(self):
        value = item()
        value["content_blocks"] = [{"type": "image_slot", "brief": "diagram", "alt": "Resume diagram", "prompt": "A diagram", "url": "https://assets.apps.deployden.tech/agency-content/editorial/a/a.png", "image_url": "https://assets.apps.deployden.tech/agency-content/editorial/a/a.png", "reviewed": True, "asset": {"sha256": "a" * 64, "object_key": "editorial/aa/" + "a" * 64 + ".png"}}]
        approved = content_digest(value)
        fake = FakeClient()
        copied = {"url": "https://media.example/editorial/a.png", "object_key": "editorial/aa/" + "a" * 64 + ".png"}
        value['content_blocks'][0]['asset']['provenance'] = {'kind': 'owned', 'creator': 'Test fixture'}
        approved = content_digest(value)
        with mock.patch("content_assets.read_core_asset", return_value=b"png"), mock.patch("content_assets.copy_to_engagement", return_value=copied) as copy_asset:
            result = publish(value, {"endpoint": "http://localhost:2370", "base_url": "https://trueapply.in/blog", "asset_storage": {"endpoint": "http://storage", "access_key": "a", "secret_key": "b", "bucket": "public", "public_base": "https://media.example"}}, approved, client=fake)
        self.assertEqual(result["digest"], approved)
        self.assertEqual(value["content_blocks"][0]["url"], "https://assets.apps.deployden.tech/agency-content/editorial/a/a.png")
        copy_asset.assert_called_once()

    def test_unmanaged_image_is_rejected_before_ghost_write(self):
        value = item()
        value["content_blocks"] = [{"type": "image_slot", "brief": "diagram", "alt": "Resume diagram", "prompt": "A diagram", "url": "https://example.com/image.png", "image_url": "https://example.com/image.png", "reviewed": True}]
        fake = FakeClient()
        with self.assertRaisesRegex(GhostPublishError, "managed editorial asset"):
            publish(value, {"endpoint": "http://localhost:2370", "base_url": "https://trueapply.in/blog"}, content_digest(value), client=fake)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
