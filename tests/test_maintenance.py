import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock


MODULE = Path(__file__).parents[1] / "scripts/maintenance.py"


def load(home):
    env = {"AGENCY_HOME": str(home), "AGENCY_CREDENTIAL_DIR": str(home / "creds"),
           "AGENCY_STATE_DIR": str(home / "state")}
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location("maintenance_test_module", MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.creds = self.home / "creds"
        self.creds.mkdir()
        self.m = load(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def test_begin_refuses_active_tasks_without_sudo(self):
        with mock.patch.object(self.m, "_active_tasks", return_value=["17"]), mock.patch.object(self.m, "_run") as run:
            with self.assertRaises(self.m.MaintenanceError): self.m.begin()
            run.assert_not_called()

    def test_begin_uses_exact_helper_command_and_secret_free_state(self):
        with mock.patch.object(self.m, "_active_tasks", return_value=[]), \
             mock.patch.object(self.m, "_verified_backup", return_value=True), \
             mock.patch.object(self.m, "_run") as run:
            result = self.m.begin()
        self.assertEqual(run.call_args.args[0], ["sudo", "-n", self.m.ROOT_HELPER, "maintenance-begin"])
        self.assertNotIn("secret", json.dumps(result).lower())
        self.assertEqual(json.loads(self.m.STATE_FILE.read_text())["phase"], "active")

    def test_begin_refuses_without_a_verified_backup(self):
        with mock.patch.object(self.m, "_active_tasks", return_value=[]), \
             mock.patch.object(self.m, "_verified_backup", return_value=False), \
             mock.patch.object(self.m, "_run") as run:
            with self.assertRaises(self.m.MaintenanceError):
                self.m.begin()
        run.assert_not_called()

    def test_resume_uses_exact_helper_and_collectors(self):
        with mock.patch.object(self.m, "_run", return_value=CompletedProcess([], 0, b"", b"")) as run, mock.patch.object(self.m, "_verify", return_value={}):
            self.m.resume()
        self.assertEqual(run.call_args_list[0].args[0], ["sudo", "-n", self.m.ROOT_HELPER, "maintenance-resume"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any("collect-host-health.py" in c[-1] for c in commands))
        self.assertTrue(any("collect-alert-state.py" in c[-1] for c in commands))

    def test_resume_verification_failure_keeps_maintenance_active(self):
        with mock.patch.object(self.m, "_run", return_value=CompletedProcess([], 0, b"", b"")), \
             mock.patch.object(self.m, "_verify", side_effect=self.m.MaintenanceError("failed")), \
             mock.patch.object(self.m.time, "sleep"):
            with self.assertRaises(self.m.MaintenanceError):
                self.m.resume()
        state = json.loads(self.m.STATE_FILE.read_text())
        self.assertEqual(state["phase"], "active")
        self.assertEqual(state["error"], "post-maintenance verification failed")

    def test_rotation_gate_and_atomic_mappings_without_secret_output(self):
        with self.assertRaises(self.m.MaintenanceError): self.m.rotate_internal(False)
        for name, content in {"core.env": "POSTGRES_USER=agency\nPOSTGRES_DB=agencyos\nPOSTGRES_PASSWORD=old\nCLICKHOUSE_PASSWORD=old2\nMINIO_ROOT_PASSWORD=old3\n", "bot.env": "PGPASSWORD=old\n", "caddy-ask.env": "POSTGRES_PASSWORD=old\n"}.items():
            (self.creds / name).write_text(content)
        with mock.patch.object(self.m, "begin"), mock.patch.object(self.m, "resume", return_value={}), mock.patch.object(self.m, "_run", return_value=CompletedProcess([], 0, b"", b"")):
            result = self.m.rotate_internal(True)
        self.assertNotIn("old", json.dumps(result))
        core = self.m._env(self.creds / "core.env")
        self.assertEqual(self.m._env(self.creds / "bot.env")["PGPASSWORD"], core["POSTGRES_PASSWORD"])
        self.assertEqual(self.m._env(self.creds / "caddy-ask.env")["POSTGRES_PASSWORD"], core["POSTGRES_PASSWORD"])
        self.assertEqual((self.creds / "core.env").stat().st_mode & 0o777, 0o400)

    def test_sync_service_env_maps_one_canonical_password_without_disclosure(self):
        canonical = "LocalOnlyStrongValue_1234567890"
        (self.creds / "core.env").write_text(f"POSTGRES_PASSWORD={canonical}\n")
        (self.creds / "bot.env").write_text("PGPASSWORD=stale\n")

        result = self.m.sync_service_env()

        self.assertEqual(self.m._env(self.creds / "bot.env")["PGPASSWORD"], canonical)
        self.assertEqual(self.m._env(self.creds / "caddy-ask.env")["POSTGRES_PASSWORD"], canonical)
        self.assertNotIn(canonical, json.dumps(result))
        self.assertEqual((self.creds / "caddy-ask.env").stat().st_mode & 0o777, 0o400)

    def test_successful_rotation_resolves_only_fixed_internal_incidents(self):
        self.m._write_json(self.m.CREDENTIAL_INCIDENTS, {
            "core.env:POSTGRES_PASSWORD": {"status": "active", "at": "x"},
            "core.env:EXTERNAL_API_KEY": {"status": "active", "at": "y"},
        })

        self.m._resolve_internal_incidents()

        incidents = self.m._json(self.m.CREDENTIAL_INCIDENTS, {})
        self.assertEqual(incidents["core.env:POSTGRES_PASSWORD"]["status"], "resolved")
        self.assertEqual(incidents["core.env:EXTERNAL_API_KEY"]["status"], "active")

    def test_rotation_command_does_not_put_password_in_argv_or_state(self):
        for name, content in {"core.env": "POSTGRES_USER=agency\nPOSTGRES_DB=agencyos\nPOSTGRES_PASSWORD=old\nCLICKHOUSE_PASSWORD=old2\nMINIO_ROOT_PASSWORD=old3\n", "bot.env": "PGPASSWORD=old\n", "caddy-ask.env": "POSTGRES_PASSWORD=old\n"}.items():
            (self.creds / name).write_text(content)
        calls = []
        def fake(command, **kwargs):
            calls.append((command, kwargs)); return CompletedProcess([], 0, b"", b"")
        with mock.patch.object(self.m, "begin"), mock.patch.object(self.m, "resume", return_value={}), mock.patch.object(self.m, "_run", side_effect=fake):
            self.m.rotate_internal(True)
        postgres = next(call for call in calls if call[0][:3] == ["docker", "exec", "-i"])
        self.assertNotIn("old", json.dumps(postgres[0]))
        self.assertIn("ALTER ROLE", postgres[1].get("input_text", ""))
        self.assertNotIn("old", json.dumps(self.m._state()))

    def test_precommit_rotation_failure_rolls_back_and_resumes_services(self):
        for name, content in {
            "core.env": "POSTGRES_USER=agency\nPOSTGRES_DB=agencyos\nPOSTGRES_PASSWORD=old\nCLICKHOUSE_PASSWORD=old2\nMINIO_ROOT_PASSWORD=old3\n",
            "bot.env": "PGPASSWORD=old\n",
        }.items():
            (self.creds / name).write_text(content)
        commands = []

        def fake_run(command, **kwargs):
            commands.append(command)
            return CompletedProcess([], 0, b"", b"")

        with mock.patch.object(self.m, "begin"), \
             mock.patch.object(self.m, "_run", side_effect=fake_run), \
             mock.patch.object(self.m, "_set_postgres_password") as set_password, \
             mock.patch.object(self.m, "_atomic_env", side_effect=self.m.MaintenanceError("write failed")):
            with self.assertRaises(self.m.MaintenanceError):
                self.m.rotate_internal(True)

        self.assertEqual(set_password.call_count, 2)
        self.assertIn(["docker", "start", "agency-dashboard"], commands)
        self.assertIn(["sudo", "-n", self.m.ROOT_HELPER, "maintenance-resume"], commands)
        self.assertEqual(self.m._state()["phase"], "failed_recovered")
        self.assertTrue(self.m._state()["services_resumed"])

    def test_postcommit_rotation_failure_stays_quiesced_for_safe_rerun(self):
        for name, content in {
            "core.env": "POSTGRES_USER=agency\nPOSTGRES_DB=agencyos\nPOSTGRES_PASSWORD=old\nCLICKHOUSE_PASSWORD=old2\nMINIO_ROOT_PASSWORD=old3\n",
            "bot.env": "PGPASSWORD=old\n",
        }.items():
            (self.creds / name).write_text(content)
        self.m._write_json(self.m.CREDENTIAL_INCIDENTS, {
            "core.env:POSTGRES_PASSWORD": {"status": "active", "at": "x"},
        })
        commands = []

        def fake_run(command, **kwargs):
            commands.append(command)
            if command[:2] == ["docker", "compose"] and str(self.m.CORE_COMPOSE) in command:
                raise self.m.MaintenanceError("compose failed")
            return CompletedProcess([], 0, b"", b"")

        with mock.patch.object(self.m, "begin"), \
             mock.patch.object(self.m, "_run", side_effect=fake_run), \
             mock.patch.object(self.m, "_set_postgres_password"):
            with self.assertRaises(self.m.MaintenanceError):
                self.m.rotate_internal(True)

        self.assertNotIn(["sudo", "-n", self.m.ROOT_HELPER, "maintenance-resume"], commands)
        self.assertEqual(self.m._state()["phase"], "active")
        self.assertFalse(self.m._state()["services_resumed"])
        incidents = self.m._json(self.m.CREDENTIAL_INCIDENTS, {})
        self.assertEqual(incidents["core.env:POSTGRES_PASSWORD"]["status"], "active")

    def test_final_alert_refresh_failure_restores_active_incidents(self):
        for name, content in {
            "core.env": "POSTGRES_USER=agency\nPOSTGRES_DB=agencyos\nPOSTGRES_PASSWORD=old\nCLICKHOUSE_PASSWORD=old2\nMINIO_ROOT_PASSWORD=old3\n",
            "bot.env": "PGPASSWORD=old\n",
        }.items():
            (self.creds / name).write_text(content)
        self.m._write_json(self.m.CREDENTIAL_INCIDENTS, {
            "core.env:POSTGRES_PASSWORD": {"status": "active", "at": "x"},
        })

        def fake_run(command, **kwargs):
            if command[-1].endswith("collect-alert-state.py"):
                raise self.m.MaintenanceError("refresh failed")
            return CompletedProcess([], 0, b"", b"")

        with mock.patch.object(self.m, "begin"), \
             mock.patch.object(self.m, "resume", return_value={}), \
             mock.patch.object(self.m, "_run", side_effect=fake_run), \
             mock.patch.object(self.m, "_set_postgres_password"):
            with self.assertRaises(self.m.MaintenanceError):
                self.m.rotate_internal(True)

        incidents = self.m._json(self.m.CREDENTIAL_INCIDENTS, {})
        self.assertEqual(incidents["core.env:POSTGRES_PASSWORD"]["status"], "active")


if __name__ == "__main__": unittest.main()
