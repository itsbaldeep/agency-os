import subprocess
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / "infra" / "codex-system-audit"
SUDOERS = Path(__file__).parents[1] / "infra" / "sudoers-agency-executor"
CADDY_ASK_UNIT = Path(__file__).parents[1] / "infra" / "systemd" / "caddy-ask.service"


class SystemAuditHelperTests(unittest.TestCase):
    def test_shell_syntax(self):
        subprocess.run(["bash", "-n", str(HELPER)], check=True)

    def test_backup_core_uses_fixed_recovery_sources(self):
        source = HELPER.read_text()
        expected = (
            "etc/systemd/system",
            "usr/lib/systemd/system/headscale.service",
            "usr/lib/systemd/system/caddy.service",
            "etc/ufw",
            "etc/default/ufw",
            "etc/sudoers",
            "etc/sudoers.d",
            "etc/headscale",
            "var/lib/headscale",
            "etc/caddy",
            "var/lib/caddy",
        )
        for path in expected:
            self.assertIn(path, source)
        self.assertNotIn("${2", source)
        self.assertIn('ROOT_BACKUP_DIR="/var/backups/agency-os"', source)
        self.assertIn('install -d -o root -g agency -m 0750 "$ROOT_BACKUP_DIR"', source)
        self.assertIn('chmod 0600 "$temporary_backup"', source)

    def test_maintenance_commands_are_fixed_and_allowlisted(self):
        source = HELPER.read_text()
        sudoers = SUDOERS.read_text()
        for action in (
            "maintenance-begin",
            "maintenance-resume",
            "remove-legacy-opencode-db-secret",
        ):
            self.assertIn(f"codex-system-audit {action}", sudoers)
        self.assertIn(
            "systemctl stop cron.service agency-worker.service agency-bot.service caddy-ask.service",
            source,
        )
        self.assertIn(
            "systemctl start caddy-ask.service agency-bot.service agency-worker.service cron.service",
            source,
        )

    def test_caddy_ask_uses_its_service_specific_environment(self):
        unit = CADDY_ASK_UNIT.read_text()
        self.assertIn(
            "EnvironmentFile=/home/agency/.config/agency/caddy-ask.env",
            unit,
        )
        self.assertNotIn("opencode.env", unit)


if __name__ == "__main__":
    unittest.main()
