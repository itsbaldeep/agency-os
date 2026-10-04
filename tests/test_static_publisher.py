import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ghost_publisher import GhostPublishError, content_digest
import static_publisher
from static_publisher import StaticPublishError, publish, rollback


def item(content_id=23, title="Useful article"):
    return {
        "id": content_id,
        "brand_id": 4,
        "project_status": "active",
        "publication_status": "publishing",
        "title": title,
        "body": "Useful article",
        "content_blocks": [{"type": "prose", "markdown": "Keep the evidence visible."}],
        "structured": {"facts": [], "meta_description": "A useful description."},
    }


class StaticPublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.publications = Path(self.tmp.name) / "publications"
        self.root = self.publications / "4"
        self.patch_root = mock.patch.object(static_publisher, "PUBLICATION_ROOT", Path(self.tmp.name) / "publications")
        self.patch_root.start()

    def tearDown(self):
        self.patch_root.stop()
        self.tmp.cleanup()

    def destination(self, root=None):
        return {
            "type": "static", "enabled": True, "base_url": "https://deployden.tech/blog",
            "output_root": str(root or self.root), "project_status": "active",
            "publication_status": "publishing", "brand_name": "Deployden",
        }

    def test_publishes_document_with_canonical_and_owned_indexes(self):
        value = item(title="Guide & <strong>Basics</strong>")
        result = publish(value, self.destination(), content_digest(value))
        article = self.root / "article" / "23" / "index.html"
        self.assertTrue(article.is_file())
        html = article.read_text()
        self.assertIn('rel="canonical" href="https://deployden.tech/blog/article/23/"', html)
        self.assertIn("Guide &amp; &lt;strong&gt;Basics&lt;/strong&gt;", html)
        self.assertEqual(result["url"], "https://deployden.tech/blog/article/23/")
        index = (self.root / "index.html").read_text()
        sitemap = (self.root / "sitemap.xml").read_text()
        self.assertIn("Guide &amp; &lt;strong&gt;Basics&lt;/strong&gt;", index)
        self.assertIn("https://deployden.tech/blog/article/23/", sitemap)
        self.assertNotIn("<strong>Basics</strong>", index)

    def test_revised_digest_is_rejected_before_filesystem_write(self):
        value = item()
        with self.assertRaisesRegex(StaticPublishError, "digest"):
            publish(value, self.destination(), "0" * 64)
        self.assertFalse(self.root.exists())

    def test_missing_statuses_and_wrong_brand_folder_are_rejected(self):
        value = item()
        missing = self.destination()
        del missing["project_status"]
        value_missing = dict(value)
        value_missing.pop("project_status")
        with self.assertRaisesRegex(StaticPublishError, "active project"):
            publish(value_missing, missing, content_digest(value_missing))
        missing = self.destination()
        del missing["publication_status"]
        value_missing = dict(value)
        value_missing.pop("publication_status")
        with self.assertRaisesRegex(StaticPublishError, "publishing state"):
            publish(value_missing, missing, content_digest(value_missing))
        wrong = self.destination(self.publications / "5")
        with self.assertRaisesRegex(StaticPublishError, "match the content brand"):
            publish(value, wrong, content_digest(value))

    def test_output_traversal_and_symlink_roots_are_rejected(self):
        value = item()
        with self.assertRaisesRegex(StaticPublishError, "outside"):
            publish(value, self.destination(Path(self.tmp.name) / ".." / "outside"), content_digest(value))
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        link = Path(self.tmp.name) / "publications" / "4"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(StaticPublishError, "outside"):
            publish(value, self.destination(link), content_digest(value))

    def test_exact_retry_is_idempotent_and_conflicting_item_cannot_overwrite(self):
        value = item()
        first = publish(value, self.destination(), content_digest(value))
        second = publish(value, self.destination(), content_digest(value))
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        changed = item(title="Different article")
        with self.assertRaisesRegex(StaticPublishError, "conflicts"):
            publish(changed, self.destination(), content_digest(changed))

    def test_index_lists_multiple_owned_articles_only(self):
        first = item(content_id=23, title="First")
        second = item(content_id=24, title="Second")
        publish(first, self.destination(), content_digest(first))
        publish(second, self.destination(), content_digest(second))
        index = (self.root / "index.html").read_text()
        self.assertIn("article/23/", index)
        self.assertIn("article/24/", index)
        self.assertIn("<link rel=\"canonical\" href=\"https://deployden.tech/blog/\">", index)
        self.assertIn("<title>Articles | Deployden</title>", index)

    def test_receipt_target_identity_conflict_refuses_retry(self):
        value = item()
        result = publish(value, self.destination(), content_digest(value))
        receipt = static_publisher._receipt_root() / "4" / "23.json"
        data = json.loads(receipt.read_text())
        data["canonical"] = "https://other.example/article/23/"
        receipt.write_text(json.dumps(data))
        with self.assertRaisesRegex(StaticPublishError, "conflicts"):
            publish(value, self.destination(), content_digest(value))

    def test_unsafe_markup_is_rejected_before_article_creation(self):
        value = item()
        value["content_blocks"] = [{"type": "prose", "markdown": "<script>alert(1)</script>"}]
        with self.assertRaises((StaticPublishError, GhostPublishError)):
            publish(value, self.destination(), content_digest(value))
        self.assertFalse(self.root.exists())

    def test_rollback_requires_exact_owned_hash_and_preserves_archived_bytes(self):
        value = item()
        result = publish(value, self.destination(), content_digest(value))
        article = self.root / "article" / "23" / "index.html"
        original = article.read_bytes()
        rolled = rollback(self.destination(), result["manifest_hash"])
        archive = Path(rolled["archived_path"])
        self.assertFalse(article.exists())
        self.assertEqual(archive.read_bytes(), original)
        self.assertFalse(any((static_publisher._receipt_root()).glob("4/23.json")))
        self.assertNotIn("article/23/", (self.root / "index.html").read_text())
        retry = rollback(self.destination(), result["manifest_hash"])
        self.assertTrue(retry["unpublished"])
        self.assertEqual(Path(retry["archived_path"]).read_bytes(), original)
        with self.assertRaisesRegex(StaticPublishError, "not owned"):
            rollback(self.destination(), "0" * 64)

    def test_brand_name_has_no_implicit_deployden_default(self):
        value = item()
        destination = self.destination()
        destination.pop("brand_name")
        publish(value, destination, content_digest(value))
        article = (self.root / "article" / "23" / "index.html").read_text()
        index = (self.root / "index.html").read_text()
        self.assertIn("Brand", article)
        self.assertIn("Articles | Brand", index)
        self.assertNotIn("Deployden", article + index)

    def test_receipt_write_failure_leaves_private_stage_and_exact_retry_repairs(self):
        value = item()
        original = static_publisher._write_atomic
        calls = {"count": 0}

        def fail_receipt(path, content):
            calls["count"] += 1
            if calls["count"] == 3:
                raise OSError("injected receipt failure")
            return original(path, content)

        with mock.patch.object(static_publisher, "_write_atomic", side_effect=fail_receipt):
            with self.assertRaises(OSError):
                publish(value, self.destination(), content_digest(value))
        self.assertTrue((self.root / "article" / "23" / "index.html").is_file())
        self.assertTrue((static_publisher._pending_path("4", "23")).is_file())
        self.assertFalse((static_publisher._receipt_path("4", "23")).exists())
        repaired = publish(value, self.destination(), content_digest(value))
        self.assertTrue(repaired["idempotent"])
        self.assertTrue((static_publisher._receipt_path("4", "23")).is_file())
        self.assertFalse((static_publisher._pending_path("4", "23")).exists())
        self.assertIn("article/23/", (self.root / "index.html").read_text())

    def test_index_write_failure_is_repaired_on_exact_retry(self):
        value = item()
        original = static_publisher._write_atomic
        calls = {"count": 0}

        def fail_sitemap(path, content):
            calls["count"] += 1
            if calls["count"] == 5:
                raise OSError("injected sitemap failure")
            return original(path, content)

        with mock.patch.object(static_publisher, "_write_atomic", side_effect=fail_sitemap):
            with self.assertRaises(OSError):
                publish(value, self.destination(), content_digest(value))
        repaired = publish(value, self.destination(), content_digest(value))
        self.assertTrue(repaired["idempotent"])
        self.assertIn("article/23/", (self.root / "index.html").read_text())
        self.assertIn("article/23/", (self.root / "sitemap.xml").read_text())

    def test_rollback_retry_repairs_indexes_after_injected_failure(self):
        value=item()
        result=publish(value,self.destination(),content_digest(value))
        write=static_publisher._write_atomic
        def fail_sitemap(path,content):
            if path.name=='sitemap.xml':raise OSError('fixture interruption')
            return write(path,content)
        with mock.patch.object(static_publisher,'_write_atomic',side_effect=fail_sitemap):
            with self.assertRaises(OSError):rollback(self.destination(),result['manifest_hash'])
        retry=rollback(self.destination(),result['manifest_hash'])
        self.assertTrue(retry['unpublished'])
        self.assertNotIn('article/23/',(self.root/'sitemap.xml').read_text())


if __name__ == "__main__":
    unittest.main()
