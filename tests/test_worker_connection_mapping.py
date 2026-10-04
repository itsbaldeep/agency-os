import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import worker


class WorkerConnectionMappingTests(unittest.TestCase):
    def test_dashboard_v2_maps_path_and_environment_name(self):
        result = worker._activation_connection_config({
            "activation_config": '{"base_url":"http://127.0.0.1:3100","endpoint":"/journey","credential_ref":"/brand/.env","credential_name":"MARKETING_READ_TOKEN"}'
        }, {})
        self.assertEqual(result, {"base_url": "http://127.0.0.1:3100", "credential_path": "/brand/.env", "credential_name": "MARKETING_READ_TOKEN", "endpoint": "/journey"})

    def test_legacy_config_keeps_path_and_credential_ref_name(self):
        result = worker._activation_connection_config({
            "trueapply_marketing": {"base_url": "http://127.0.0.1:3100", "credential_path": "/brand/.env", "credential_ref": "LEGACY_TOKEN"}
        }, {})
        self.assertEqual(result["credential_path"], "/brand/.env")
        self.assertEqual(result["credential_name"], "LEGACY_TOKEN")

    def test_explicit_task_overrides_are_project_agnostic(self):
        result = worker._activation_connection_config({
            "activation_config": {"base_url": "http://127.0.0.1:3100", "credential_ref": "/brand/.env", "credential_name": "CONFIG_TOKEN"}
        }, {"activation_credential_path": "/task/.env", "activation_credential_name": "TASK_TOKEN", "activation_endpoint": "/task"})
        self.assertEqual(result["credential_path"], "/task/.env")
        self.assertEqual(result["credential_name"], "TASK_TOKEN")
        self.assertEqual(result["endpoint"], "/task")


if __name__ == "__main__":
    unittest.main()
