import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import configure_trueapply_ga4 as ga


class ConfigureTests(unittest.TestCase):
    def test_apply_snapshots_first_and_reads_back_exact_settings(self):
        calls, snapshots = [], []
        state = {"streamEnabled": True}
        events = []
        def request(token, path, method="GET", payload=None):
            calls.append((path, method, payload))
            if "enhancedMeasurementSettings" in path:
                if method == "PATCH":
                    self.assertTrue(snapshots)
                    self.assertIn("updateMask=stream_enabled", path)
                    state.update(payload)
                return dict(state)
            if method == "POST":
                events.append(dict(payload))
            return {"keyEvents": list(events)}
        result = ga.configure("private", apply=True, request=request, snapshot=snapshots.append)
        self.assertTrue(result["configuration_verified"])
        self.assertFalse(result["collection_verified"])
        self.assertEqual(snapshots[0]["settings"]["streamEnabled"], True)
        mutations = len([item for item in calls if item[1] != "GET"])
        ga.configure("private", apply=True, request=request, snapshot=snapshots.append)
        self.assertEqual(len([item for item in calls if item[1] != "GET"]), mutations)

    def test_inspection_does_not_write(self):
        def request(token, path, method="GET", payload=None):
            self.assertEqual(method, "GET")
            return {"streamEnabled": True} if "Settings" in path else {"keyEvents": []}
        self.assertEqual(ga.configure("private", request=request)["mode"], "inspect")

    def test_apply_requires_snapshot(self):
        with self.assertRaises(ValueError):
            ga.configure("private", apply=True, request=lambda *args: {})

    def test_other_property_rejected_before_network(self):
        with self.assertRaises(ValueError):
            ga.api("private", "v1beta/properties/999/keyEvents")
