import subprocess
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / "infra" / "codex-system-audit"


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


if __name__ == "__main__":
    unittest.main()
