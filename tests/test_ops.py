import importlib.util
import json
import os
import tarfile
import tempfile
import unittest
from subprocess import CompletedProcess
from datetime import date
from pathlib import Path
from unittest import mock


OPS_PATH = Path(__file__).parents[1] / "scripts" / "ops.py"
SEED_PATH = Path(__file__).parents[1] / "infra" / "seed.sql"


def load_ops(home: Path):
    env = {
        "AGENCY_HOME": str(home),
        "AGENCY_CREDENTIAL_DIR": str(home / ".config/agency"),
        "AGENCY_STATE_DIR": str(home / ".local/state/agency-os"),
        "AGENCY_BACKUP_DIR": str(home / "backups/core"),
    }
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location("agency_ops", OPS_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        return module


class OpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.credentials = self.home / ".config/agency"
        self.credentials.mkdir(parents=True)
        self.ops = load_ops(self.home)

    def tearDown(self):
        self.temp.cleanup()

    def test_credential_inventory_never_returns_values(self):
        secret_value = "never-print-this-value"
        (self.credentials / "core.env").write_text(
            f"API_TOKEN={secret_value}\nPUBLIC_URL=https://example.com\n",
            encoding="utf-8",
        )
        records = self.ops.credential_inventory()
        encoded = json.dumps(records)
        self.assertEqual([record["name"] for record in records], ["API_TOKEN"])
        self.assertNotIn(secret_value, encoded)

    def test_background_job_seed_uses_sql_boolean_literals(self):
        seed = SEED_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(seed, r",\s*[tf],\s*[tf]\)")
        self.assertIn("TRUE, FALSE", seed)

    def test_placeholder_is_flagged_without_disclosure(self):
        (self.credentials / "core.env").write_text(
            "CLICKHOUSE_PASSWORD=changeme\n", encoding="utf-8"
        )
        record = self.ops.credential_inventory()[0]
        self.assertTrue(record["placeholder_like"])
        self.assertNotIn("value", record)

    def test_weak_credential_cannot_be_acknowledged(self):
        (self.credentials / "core.env").write_text(
            "CLICKHOUSE_PASSWORD=changeme\n", encoding="utf-8"
        )
        with self.assertRaises(self.ops.OpsError):
            self.ops.mark_credential("core.env:CLICKHOUSE_PASSWORD")

    def test_strong_credential_can_be_acknowledged(self):
        (self.credentials / "core.env").write_text(
            "API_TOKEN=q9M!2xL#7vP@4sD$8nK\n", encoding="utf-8"
        )
        records = self.ops.mark_credential("core.env:API_TOKEN")
        self.assertTrue(records[0]["human_rotated_at"])

    def test_project_named_password_is_treated_as_weak(self):
        self.assertTrue(self.ops.credential_looks_weak("agency_clickhouse_2026"))
        self.assertFalse(self.ops.credential_looks_weak("q9M!2xL#7vP@4sD$8nK"))

    def test_weekly_offsite_acknowledgement(self):
        before = self.ops.operations_status(date(2026, 8, 22))
        self.assertTrue(before["offsite"]["overdue"])
        self.ops.STATE_DIR.mkdir(parents=True)
        self.ops.write_json(
            self.ops.OPS_STATE,
            {"offsite": {"confirmed_on": "2026-08-22", "confirmed_at": "x"}},
        )
        after = self.ops.operations_status(date(2026, 8, 22))
        self.assertFalse(after["offsite"]["overdue"])

    def test_verify_backup_checks_component_hashes(self):
        component = self.home / "postgres.dump"
        component.write_bytes(b"backup")
        manifest = {
            "created_at": "2026-08-22T00:00:00+00:00",
            "components": {"postgres": True},
            "files": {
                "postgres.dump": {
                    "bytes": component.stat().st_size,
                    "sha256": self.ops.sha256(component),
                }
            },
        }
        manifest_path = self.home / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        bundle = self.home / "bundle.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            archive.add(component, arcname="postgres.dump")
            archive.add(manifest_path, arcname="manifest.json")
        result = self.ops.verify_backup(bundle)
        self.assertTrue(result["ok"])

        recorded = self.ops.verify_and_record_backup(bundle)
        self.assertTrue(recorded["ok"])
        status = self.ops.operations_status(date(2026, 8, 22))
        self.assertEqual(status["last_verification"]["bundle_sha256"], result["bundle_sha256"])

    def test_export_configs_includes_global_agent_rules_and_trace_state(self):
        (self.home / "core/agency-os").mkdir(parents=True)
        (self.home / "core/agency-os/CEO_DIRECTIVE.md").write_text("directive\n")
        (self.home / "core/agency-os/ROADMAP.md").write_text("roadmap\n")
        (self.home / "AGENTS.md").write_text("global rules\n")
        trace_dir = self.ops.STATE_DIR / "agent-traces"
        trace_dir.mkdir(parents=True)
        (trace_dir / "2026-08-24.jsonl").write_text("{}\n")
        destination = self.home / "configs.tar.gz"

        result = self.ops.export_configs(destination)

        self.assertTrue(result["root-agents"])
        self.assertTrue(result["agent-traces"])
        with tarfile.open(destination, "r:gz") as archive:
            member = archive.extractfile("root-agents")
            self.assertIsNotNone(member)
            self.assertEqual(member.read().decode(), "global rules\n")

    def test_root_backup_copies_only_the_helper_reported_fixed_path(self):
        root_dir = self.home / "root-backups"
        root_dir.mkdir()
        archive = root_dir / "core-system-20260828T180000Z.tar.gz"
        archive.write_bytes(b"root state")
        stage = self.home / "stage"
        stage.mkdir()
        self.ops.ROOT_BACKUP_DIR = root_dir

        with mock.patch.object(
            self.ops,
            "run",
            return_value=CompletedProcess([], 0, f"{archive}\n".encode(), b""),
        ):
            self.assertTrue(self.ops.request_root_backup(stage))

        self.assertEqual((stage / archive.name).read_bytes(), b"root state")

    def test_root_backup_rejects_an_unexpected_helper_path(self):
        stage = self.home / "stage"
        stage.mkdir()
        unexpected = self.home / "core-system-20260828T180000Z.tar.gz"
        unexpected.write_bytes(b"unexpected")

        with mock.patch.object(
            self.ops,
            "run",
            return_value=CompletedProcess([], 0, f"{unexpected}\n".encode(), b""),
        ):
            self.assertFalse(self.ops.request_root_backup(stage))


if __name__ == "__main__":
    unittest.main()
