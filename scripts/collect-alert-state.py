#!/usr/bin/env python3
"""Build the dashboard's secret-free, deterministic human-chores snapshot."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import ops


DESTINATION = Path(os.environ.get(
    "AGENCY_ALERT_STATE_FILE",
    "/home/agency/.local/state/agency-os/alerts.json",
))
HOST_HEALTH = Path(os.environ.get(
    "AGENCY_HOST_HEALTH_FILE",
    "/home/agency/.local/state/agency-os/host-health.json",
))
BACKUP_SSH_HOST = os.environ.get("AGENCY_BACKUP_SSH_HOST", "100.64.0.1")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def failed_units() -> list[str]:
    try:
        result = subprocess.run(
            ["systemctl", "--failed", "--no-legend", "--plain"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    units = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields:
            units.append(fields[0].lstrip("●"))
    return sorted(set(units))


def credential_action(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    weak = bool(item.get("placeholder_like"))
    rotated = bool(item.get("human_rotated_at"))
    health = item.get("health_status") or "not_probed"
    item["status"] = "clear" if rotated and not weak else "action_required"
    item["source_path"] = (
        f"/home/agency/.config/agency/{item['source']}"
        if item.get("source") != "tool-auth-status.json"
        else "/home/agency/.config/agency/tool-auth-status.json"
    )
    if weak and health in ("invalid", "missing", "stale"):
        item["next_action"] = "Re-authenticate this provider, recheck, then mark it human-rotated."
        item["command"] = "opencode auth login"
    elif weak:
        item["next_action"] = "Replace the value with a strong human-generated credential, restart its owner, then recheck."
        item["command"] = f"nano {item['source_path']}"
    elif not rotated:
        item["next_action"] = "If you personally replaced this credential, acknowledge that rotation."
        item["command"] = ""
    else:
        item["next_action"] = "No action required."
        item["command"] = ""
    return item


def build_alert_state(today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    operations = ops.operations_status(today)
    backup = dict(operations.get("last_backup") or {})
    verification = operations.get("last_verification") or {}
    offsite = dict(operations.get("offsite") or {})
    bundle = Path(backup.get("path") or "") if backup.get("path") else None
    filename = bundle.name if bundle else "core-backup-UNKNOWN.tar.gz"
    verified = bool(
        backup.get("sha256")
        and verification.get("ok")
        and verification.get("bundle_sha256") == backup.get("sha256")
    )
    offsite["next_due"] = (
        date.fromisoformat(offsite["required_since"]) + timedelta(days=7)
    ).isoformat() if offsite.get("required_since") else None
    backup.update({
        "filename": filename,
        "server_verified": verified,
        "verified_at": verification.get("at") if verified else None,
        "offsite": offsite,
        "scp_command": f"scp agency@{BACKUP_SSH_HOST}:{backup.get('path') or '/home/agency/backups/core/'} .",
        "verify_command": f"sha256sum {filename}",
        "status": "clear" if verified and not offsite.get("overdue") else "action_required",
    })

    credentials = [credential_action(item) for item in ops.credential_inventory()]
    credential_open = sum(item["status"] != "clear" for item in credentials)

    host = read_json(HOST_HEALTH)
    maintenance = dict(host.get("maintenance") or {})
    update_count = int(maintenance.get("upgradable_count") or 0)
    reboot_required = bool(maintenance.get("reboot_required"))
    apt_check_ok = maintenance.get("apt_check_ok") is not False
    maintenance.update({
        "status": (
            "clear"
            if apt_check_ok and update_count == 0 and not reboot_required
            else "action_required"
        ),
        "current_kernel": os.uname().release,
        "commands": [
            "sudo apt update",
            "apt list --upgradable",
            "sudo apt upgrade",
            "sudo reboot",
        ],
    })

    units = failed_units()
    root_included = bool(backup.get("root_state_included"))
    groups = {
        "backup": backup.get("status") != "clear",
        "credentials": credential_open > 0,
        "maintenance": maintenance.get("status") != "clear",
        "root_recovery": not root_included,
        "failed_units": bool(units),
    }
    open_count = sum(groups.values())
    critical_count = sum((
        bool(offsite.get("overdue")),
        any(item.get("placeholder_like") for item in credentials),
        reboot_required,
    ))
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "summary": {
            "open_count": open_count,
            "critical_count": critical_count,
            "clear_count": len(groups) - open_count,
        },
        "backup": backup,
        "credentials": credentials,
        "credential_summary": {
            "total": len(credentials),
            "open": credential_open,
            "weak_or_unhealthy": sum(bool(item.get("placeholder_like")) for item in credentials),
            "acknowledged": sum(bool(item.get("human_rotated_at")) for item in credentials),
        },
        "maintenance": maintenance,
        "root_recovery": {
            "status": "clear" if root_included else "blocked",
            "included": root_included,
            "detail": (
                "Root-only system state is included in the latest recovery bundle."
                if root_included else
                "The fixed-target sudo helper still lacks backup-core; application recovery is verified but root-only units/firewall/sudo/Headscale state is absent."
            ),
        },
        "failed_units": {
            "status": "clear" if not units else "action_required",
            "units": units,
        },
    }


def write_snapshot(payload: dict[str, Any]) -> None:
    DESTINATION.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    current_mode = DESTINATION.parent.stat().st_mode & 0o7777
    os.chmod(DESTINATION.parent, current_mode | 0o055)
    fd, raw = tempfile.mkstemp(prefix=".alerts.", dir=DESTINATION.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
        os.chmod(raw, 0o644)
        os.replace(raw, DESTINATION)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def main() -> None:
    write_snapshot(build_alert_state())


if __name__ == "__main__":
    main()
