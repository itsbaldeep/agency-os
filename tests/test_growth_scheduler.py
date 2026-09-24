import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

SPEC = importlib.util.spec_from_file_location('growth_scheduler', Path(__file__).resolve().parents[1] / 'scripts/queue-growth-measurement.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SchedulerTests(unittest.TestCase):
    def test_daily_deduplication_and_next_day(self):
        calls = []
        def opener(request, timeout):
            self.assertEqual(request.method, 'POST')
            self.assertEqual(request.full_url, 'http://100.64.0.1:5001/api/brands/31/seo-measurement')
            calls.append(request)
            return io.BytesIO(json.dumps({'ok': True, 'task_id': 500 + len(calls)}).encode())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(module.queue(31, root, '2026-09-23', opener)['task_id'], 501)
            self.assertTrue(module.queue(31, root, '2026-09-23', opener)['deduplicated_day'])
            self.assertEqual(module.queue(31, root, '2026-09-24', opener)['task_id'], 502)
        self.assertEqual(len(calls), 2)

    def test_bad_result_does_not_mark_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                module.queue(31, Path(directory), opener=lambda *a, **k: io.BytesIO(b'{"ok":true,"task_id":"oops"}'))
            self.assertFalse((Path(directory) / '31.json').exists())

    def test_parked_brand_is_skipped(self):
        def opener(*args, **kwargs):
            raise HTTPError('local', 409, 'Conflict', {}, None)
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn('skipped', module.queue(31, Path(directory), opener=opener))
            self.assertFalse((Path(directory) / '31.json').exists())

    def test_invalid_identifiers_rejected(self):
        for value in [0, -1, True, '31', None]:
            with self.assertRaises(ValueError):
                module.queue(value)


if __name__ == '__main__':
    unittest.main()
