import base64
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import content_assets as assets


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class AssetTests(unittest.TestCase):
    def test_metadata_is_immutable_and_alt_is_editable_suggestion(self):
        with mock.patch.object(assets, "_dimensions", return_value=(10, 20)):
            meta = assets._metadata(PNG, "Annotated resume parsing flow", {"provider": "owned"})
        self.assertEqual(meta["id"], meta["sha256"])
        self.assertEqual(meta["mime"], "image/png")
        self.assertEqual(meta["alt"], "Annotated resume parsing flow")
        self.assertEqual(meta["provenance"]["provider"], "owned")

    def test_rejects_svg_and_unknown_bytes(self):
        for value in (b"<svg><script>alert(1)</script></svg>", b"not-an-image"):
            with self.assertRaises(ValueError):
                assets._metadata(value, "graphic", {"provider": "owned"})

    def test_sanitize_reencodes_and_strips_exif(self):
        from PIL import Image
        source = io.BytesIO()
        image = Image.new("RGB", (2, 2), "green")
        image.save(source, format="JPEG", exif=b"Exif\x00\x00GPS-PRIVATE")
        clean = assets._sanitize(source.getvalue())
        with Image.open(io.BytesIO(clean)) as decoded:
            self.assertEqual(decoded.format, "JPEG")
            self.assertEqual(len(decoded.getexif()), 0)

    def test_pixel_cap_is_enforced(self):
        with mock.patch.object(assets, "_mime", return_value="image/png"), mock.patch("PIL.Image.open") as opened:
            opened.return_value.__enter__.return_value.width = 5000
            opened.return_value.__enter__.return_value.height = 5000
            with self.assertRaisesRegex(ValueError, "pixel"):
                assets._sanitize(b"x")

    def test_public_readback_is_exact_hash(self):
        digest = __import__("hashlib").sha256(PNG).hexdigest()
        self.assertTrue(assets.public_readback(PNG, digest))
        self.assertFalse(assets.public_readback(PNG + b"x", digest))

    def test_provider_search_rejects_non_provider_thumbnail(self):
        payload = json.dumps({"photos": [{"id": 7, "url": "https://www.pexels.com/photo/7/", "src": {"medium": "https://evil.example/x.jpg"}}]}).encode()
        with mock.patch.dict(os.environ, {"PEXELS_API_KEY": "test"}), mock.patch.object(assets, "_request", return_value=(200, payload, "", "application/json")):
            with self.assertRaises(ValueError):
                assets.search_assets("resume")

    def test_import_resolves_id_and_never_accepts_arbitrary_url(self):
        api = json.dumps({"id": 7, "url": "https://www.pexels.com/photo/7/", "photographer": "A", "alt": "Resume illustration", "src": {"original": "https://images.pexels.com/photo.jpg"}}).encode()
        with mock.patch.dict(os.environ, {"PEXELS_API_KEY": "test"}), mock.patch.object(assets, "_request", side_effect=[(200, api, "", "application/json"), (200, PNG, "https://images.pexels.com/photo.jpg", "image/png")]), mock.patch.object(assets, "store_asset", return_value={"sha256": "x"}) as store:
            result = assets.import_stock("7", "Resume parsing diagram")
        self.assertEqual(result["sha256"], "x")
        self.assertEqual(store.call_args.args[0][0:8], PNG[0:8])

    def test_import_prefers_bounded_editorial_size(self):
        resized = 'https://images.pexels.com/sized.jpg'
        photo = {'id': 7, 'url': 'https://www.pexels.com/photo/7/',
                 'src': {'original': 'https://images.pexels.com/original.jpg', 'large2x': resized}}
        with mock.patch.dict(os.environ, {'PEXELS_API_KEY': 'test'}), \
             mock.patch.object(assets, '_request', side_effect=[
                 (200, json.dumps(photo).encode(), '', 'application/json'),
                 (200, PNG, resized, 'image/png')]) as fetch, \
             mock.patch.object(assets, 'store_asset', return_value={'sha256': 'x'}):
            assets.import_stock('7')
        self.assertEqual(fetch.call_args_list[1].args[0], resized)


if __name__ == "__main__":
    unittest.main()
