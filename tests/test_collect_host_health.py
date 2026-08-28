import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


COLLECTOR_PATH = Path(__file__).parents[1] / "scripts" / "collect-host-health.py"


def load_collector():
    spec = importlib.util.spec_from_file_location("collect_host_health", COLLECTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class HostHealthTests(unittest.TestCase):
    def setUp(self):
        self.collector = load_collector()

    def test_package_updates_separates_installable_and_deferred(self):
        listed = """Listing...\nalpha/release 2 amd64 [upgradable from: 1]\nbeta/release 2 all [upgradable from: 1]\n"""
        simulated = """Inst alpha [1] (2 release [amd64])\nConf alpha (2 release [amd64])\n1 upgraded, 0 newly installed, 0 to remove and 1 not upgraded.\n"""

        installable, deferred = self.collector.package_updates(listed, simulated)

        self.assertEqual(installable, ["alpha"])
        self.assertEqual(deferred, ["beta"])

    def test_package_updates_normalizes_multiarch_names(self):
        listed = "libalpha/release 2 amd64 [upgradable from: 1]\n"
        simulated = "Inst libalpha:amd64 [1] (2 release [amd64])\n"

        installable, deferred = self.collector.package_updates(listed, simulated)

        self.assertEqual(installable, ["libalpha"])
        self.assertEqual(deferred, [])

    def test_maintenance_falls_back_to_list_when_simulation_fails(self):
        listed = "alpha/release 2 amd64 [upgradable from: 1]\n"
        failure = subprocess.CalledProcessError(1, ["apt-get", "-s", "upgrade"])

        with mock.patch.object(self.collector, "run", side_effect=[listed, failure]):
            result = self.collector.maintenance()

        self.assertEqual(result["upgradable_packages"], ["alpha"])
        self.assertEqual(result["deferred_packages"], [])
        self.assertFalse(result["apt_check_ok"])

    def test_maintenance_marks_both_command_failures_unavailable(self):
        failure = subprocess.CalledProcessError(1, ["apt"])

        with mock.patch.object(self.collector, "run", side_effect=[failure, failure]):
            result = self.collector.maintenance()

        self.assertEqual(result["upgradable_packages"], [])
        self.assertFalse(result["apt_check_ok"])


if __name__ == "__main__":
    unittest.main()
