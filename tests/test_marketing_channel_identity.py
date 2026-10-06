import hashlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import marketing_channel_identity as identity


class MarketingChannelIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "brands"
        self.brand = self.root / "1"
        self.brand.mkdir(parents=True)
        self.png = self.brand / "avatar.png"
        image = Image.new("RGBA", (16, 12), (10, 20, 30, 255))
        image.save(self.png, format="PNG")
        self.item = {
            "id": 7,
            "brand_id": 1,
            "revision": 3,
            "title": "A safe title",
            "brief": {"media": {"outputs": [{"path": str(self.png), "mime": "image/png", "provenance": "generated"}]}},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_candidates_and_resolve_return_bounded_identity_and_bytes(self):
        found = identity.candidates([self.item], 1, self.root)
        self.assertEqual(len(found), 1)
        candidate = found[0]
        self.assertEqual(candidate["work_id"], 7)
        self.assertEqual(candidate["source_revision"], 3)
        self.assertEqual(candidate["mime"], "image/png")
        self.assertEqual(candidate["width"], 16)
        self.assertEqual(candidate["height"], 12)
        self.assertNotIn("path", candidate)
        resolved = identity.resolve_reference(self.item, 1, {key: candidate[key] for key in ("work_id", "source_revision", "filename", "sha256")}, self.root)
        self.assertEqual(resolved["metadata"]["sha256"], candidate["sha256"])
        self.assertEqual(hashlib.sha256(resolved["image_bytes"]).hexdigest(), candidate["sha256"])
        self.assertNotIn("path", resolved["metadata"])

    def test_cross_brand_ids_and_zero_or_bool_ids_fail_closed(self):
        self.assertEqual(identity.candidates([self.item], 2, self.root), [])
        for bad in (0, False, True, "1"):
            self.assertEqual(identity.candidates([self.item], bad, self.root), [])
        for bad_item in ({**self.item, "brand_id": 2}, {**self.item, "id": 0}, {**self.item, "revision": True}):
            self.assertEqual(identity.candidates([bad_item], 1, self.root), [])

    def test_changed_hash_and_malformed_refs_are_rejected(self):
        candidate = identity.candidates([self.item], 1, self.root)[0]
        ref = {key: candidate[key] for key in ("work_id", "source_revision", "filename", "sha256")}
        self.png.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            identity.resolve_reference(self.item, 1, ref, self.root)
        for malformed in (
            {},
            {**ref, "extra": 1},
            {**ref, "work_id": True},
            {**ref, "source_revision": 0},
            {**ref, "filename": "../avatar.png"},
            {**ref, "sha256": "A" * 64},
        ):
            with self.assertRaises(ValueError):
                identity.resolve_reference(self.item, 1, malformed, self.root)

    def test_symlinks_outside_paths_and_ambiguous_outputs_are_skipped(self):
        outside = Path(self.tmp.name) / "outside.png"
        outside.write_bytes(self.png.read_bytes())
        outside_item = {**self.item, "brief": {"media": {"outputs": [{"path": str(outside), "mime": "image/png"}]}}}
        self.assertEqual(identity.candidates([outside_item], 1, self.root), [])
        link = self.brand / "link.png"
        link.symlink_to(outside)
        symlink_item = {**self.item, "brief": {"media": {"outputs": [{"path": str(link), "mime": "image/png"}]}}}
        self.assertEqual(identity.candidates([symlink_item], 1, self.root), [])
        real_parent = self.brand / "real-parent"
        real_parent.mkdir()
        nested = real_parent / "nested.png"
        nested.write_bytes(self.png.read_bytes())
        parent_alias = self.brand / "parent-alias"
        parent_alias.symlink_to(real_parent, target_is_directory=True)
        parent_item = {**self.item, "brief": {"media": {"outputs": [{"path": str(parent_alias / "nested.png"), "mime": "image/png"}]}}}
        self.assertEqual(identity.candidates([parent_item], 1, self.root), [])
        fifo = self.brand / "pipe.png"
        os.mkfifo(fifo)
        fifo_item = {**self.item, "brief": {"media": {"outputs": [{"path": str(fifo), "mime": "image/png"}]}}}
        self.assertEqual(identity.candidates([fifo_item], 1, self.root), [])
        ambiguous = {**self.item, "brief": {"media": {"outputs": [
            {"path": str(self.brand / "a" / "same.png"), "mime": "image/png"},
            {"path": str(self.brand / "b" / "same.png"), "mime": "image/png"},
        ]}}}
        self.assertEqual(identity.candidates([ambiguous], 1, self.root), [])

    def test_mime_image_bounds_and_read_cap_fail_closed(self):
        jpeg = self.brand / "photo.jpg"
        Image.new("RGB", (8, 8), "red").save(jpeg, format="JPEG")
        wrong_mime = {**self.item, "brief": {"media": {"outputs": [{"path": str(jpeg), "mime": "image/png"}]}}}
        self.assertEqual(identity.candidates([wrong_mime], 1, self.root), [])
        huge_pixels = self.brand / "huge.png"
        Image.new("RGB", (4500, 4500), "blue").save(huge_pixels, format="PNG")
        huge_item = {**self.item, "brief": {"media": {"outputs": [{"path": str(huge_pixels), "mime": "image/png"}]}}}
        self.assertEqual(identity.candidates([huge_item], 1, self.root), [])
        oversized = self.brand / "oversized.png"
        oversized.write_bytes(b"x" * (identity.MAX_FILE_BYTES + 1))
        oversized_item = {**self.item, "brief": {"media": {"outputs": [{"path": str(oversized), "mime": "image/png"}]}}}
        self.assertEqual(identity.candidates([oversized_item], 1, self.root), [])
        malformed_mime = {**self.item, "brief": {"media": {"outputs": [{"path": str(self.png), "mime": {}}]}}}
        self.assertEqual(identity.candidates([malformed_mime], 1, self.root), [])

    def test_pixel_limit_is_checked_before_image_load(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.width = identity.MAX_PIXELS + 1
        fake.height = 1
        fake.format = "PNG"
        with mock.patch.object(identity.Image, "open", return_value=fake):
            with self.assertRaises(ValueError):
                identity._validate_image({"mime": "image/png"}, self.png, self.brand)
        fake.verify.assert_not_called()
        fake.load.assert_not_called()

    def test_boolean_reference_work_id_is_rejected(self):
        candidate = identity.candidates([self.item], 1, self.root)[0]
        ref = {key: candidate[key] for key in ("work_id", "source_revision", "filename", "sha256")}
        ref["work_id"] = True
        with self.assertRaises(ValueError):
            identity.resolve_reference(self.item, 1, ref, self.root)

    def test_candidates_are_bounded_to_items_and_results(self):
        items = []
        for index in range(40):
            item = {**self.item, "id": index + 1, "title": "x" * 400}
            item["brief"] = {"media": {"outputs": [{"path": str(self.png), "mime": "image/png"}]}}
            items.append(item)
        result = identity.candidates(items, 1, self.root)
        self.assertLessEqual(len(result), identity.MAX_CANDIDATES)
        self.assertTrue(all(len(candidate["title"]) <= 240 for candidate in result))


if __name__ == "__main__":
    unittest.main()
