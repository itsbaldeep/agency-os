#!/usr/bin/env python3
"""Small, deterministic maintenance controller.

This module deliberately keeps credentials in memory only long enough to perform
the requested rotation.  Command output, exceptions, and state files never
contain credential material.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

AGENCY_HOME = Path(os.environ.get("AGENCY_HOME", "/home/agency"))
CREDENTIAL_DIR = Path(os.environ.get("AGENCY_CREDENTIAL_DIR", AGENCY_HOME / ".config/agency"))
STATE_DIR = Path(os.environ.get("AGENCY_STATE_DIR", AGENCY_HOME / ".local/state/agency-os"))
STATE_FILE = STATE_DIR / "maintenance.json"
ROOT_HELPER = "/usr/local/sbin/codex-system-audit"
UNITS = ("agency-worker", "agency-bot", "caddy-ask", "cron", "opencode", "caddy", "headscale")
CONTAINERS = ("agency-postgres", "agency-clickhouse", "agency-minio", "agency-dashboard", "deployden-site")
ROUTES = {
    "dashboard": ("http://100.64.0.1:5001/", "200"),
    "alerts": ("http://100.64.0.1:5001/alerts", "200"),
    "health": ("http://100.64.0.1:5001/health", "200"),
    "deployden": ("https://deployden.tech/", "200"),
    "opencode": ("http://100.64.0.1:4096/", "401"),
}
CORE_COMPOSE = AGENCY_HOME / "agency-os/docker-compose.yml"
DASHBOARD_COMPOSE = AGENCY_HOME / "core/agency-dashboard/docker-compose.yml"
OPS_STATE = STATE_DIR / "operations.json"


class MaintenanceError(RuntimeError):
    pass


def _run(command: list[str], *, input_text: str | None = None, timeout: int = 180) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(command, input=input_text.encode() if input_text is not None else None,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError) as exc:
        # Never relay stderr: it can contain command arguments or credentials.
        raise MaintenanceError(f"command failed: {command[0]}") from exc


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_state(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".maintenance.", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(name, 0o600)
        os.replace(name, STATE_FILE)
    finally:
        Path(name).unlink(missing_ok=True)


def _active_tasks() -> list[str]:
    sql = "SELECT id FROM tasks WHERE status IN ('queued','running') ORDER BY id"
    try:
        result = _run(["docker", "exec", "agency-postgres", "psql", "-U", "agency", "-d", "agencyos", "-At", "-c", sql])
        return [line.strip() for line in result.stdout.decode(errors="replace").splitlines() if line.strip()]
    except MaintenanceError:
        return ["unavailable"]


def _state() -> dict[str, Any]:
    return _json(STATE_FILE, {}) or {}


def status() -> dict[str, Any]:
    units: dict[str, str] = {}
    for unit in UNITS:
        try:
            _run(["systemctl", "is-active", "--quiet", unit], timeout=15)
            units[unit] = "active"
        except MaintenanceError:
            units[unit] = "inactive"
    containers: dict[str, str] = {}
    for container in CONTAINERS:
        try:
            result = _run(["docker", "inspect", "--format", "{{.State.Status}}", container], timeout=15)
            containers[container] = result.stdout.decode(errors="replace").strip() or "unknown"
        except MaintenanceError:
            containers[container] = "unavailable"
    routes: dict[str, str] = {}
    for name, (url, expected) in ROUTES.items():
        try:
            result = _run([
                "curl", "-sS", "--max-time", "10", "-o", "/dev/null",
                "-w", "%{http_code}", url,
            ], timeout=15)
            code = result.stdout.decode(errors="replace").strip()
            routes[name] = "ok" if code == expected else f"http_{code or 'unknown'}"
        except MaintenanceError:
            routes[name] = "failed"
    return {"active_tasks": _active_tasks(), "units": units, "containers": containers,
            "routes": routes, "maintenance": _state().get("phase", "idle")}


def _verified_backup() -> bool:
    state = _json(OPS_STATE, {}) or {}
    backup = state.get("last_backup") or {}
    verification = state.get("last_verification") or {}
    return bool(
        backup.get("sha256")
        and verification.get("ok")
        and verification.get("bundle_sha256") == backup.get("sha256")
    )


def begin() -> dict[str, Any]:
    active = _active_tasks()
    if active:
        raise MaintenanceError("active tasks prevent maintenance")
    if not _verified_backup():
        raise MaintenanceError("a verified core backup is required before maintenance")
    _run(["sudo", "-n", ROOT_HELPER, "maintenance-begin"], timeout=60)
    data = {"phase": "active", "started": True}
    _write_state(data)
    return data


def _verify() -> dict[str, Any]:
    result = status()
    failed_units = [name for name, state in result["units"].items() if state != "active"]
    failed_containers = [name for name, state in result["containers"].items() if state != "running"]
    failed_routes = [name for name, state in result["routes"].items() if state != "ok"]
    if failed_units or failed_containers or failed_routes:
        raise MaintenanceError("post-maintenance verification failed")
    return result


def resume() -> dict[str, Any]:
    _run(["sudo", "-n", ROOT_HELPER, "maintenance-resume"], timeout=60)
    for collector in ("collect-host-health.py", "collect-alert-state.py"):
        _run(["python3", str(AGENCY_HOME / "agency-os/scripts" / collector)], timeout=60)
    for attempt in range(15):
        try:
            result = _verify()
            break
        except MaintenanceError:
            if attempt == 14:
                _write_state({"phase": "active", "error": "post-maintenance verification failed"})
                raise
            time.sleep(2)
    data = {"phase": "complete", "verified": True}
    _write_state(data)
    result["maintenance"] = data
    return result


def _strong_secret() -> str:
    # URL-safe values avoid shell, Compose interpolation, quoting, and comment syntax.
    alphabet = string.ascii_letters + string.digits + "-_"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(48))
        if (any(c.islower() for c in value) and any(c.isupper() for c in value)
                and any(c.isdigit() for c in value)
                and not any(marker in value.lower() for marker in ("password", "changeme", "placeholder", "agency", "clickhouse", "admin"))):
            return value


def _env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    except OSError as exc:
        raise MaintenanceError("credential file unavailable") from exc
    return values


def _atomic_env(path: Path, updates: dict[str, str]) -> None:
    try:
        original = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        original = ""
    except OSError as exc:
        raise MaintenanceError("credential file unavailable") from exc
    lines = original.splitlines(keepends=True)
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        raw = line.rstrip("\r\n")
        key = raw.split("=", 1)[0].strip() if "=" in raw and not raw.lstrip().startswith("#") else ""
        if key in updates:
            output.append(f"{key}={updates[key]}\n")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}\n")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o400)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(output)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(name, path)
        os.chmod(path, 0o400)
    finally:
        Path(name).unlink(missing_ok=True)


def _restore_env(path: Path, original: str | None) -> None:
    if original is None:
        path.unlink(missing_ok=True)
        return
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.restore.", dir=path.parent)
    try:
        os.fchmod(fd, 0o400)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(original)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
        os.chmod(path, 0o400)
    finally:
        Path(name).unlink(missing_ok=True)


def _set_postgres_password(user: str, database: str, password: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", user):
        raise MaintenanceError("invalid PostgreSQL role name")
    quoted_user = '"' + user.replace('"', '""') + '"'
    quoted_password = "'" + password.replace("'", "''") + "'"
    statement = f"ALTER ROLE {quoted_user} WITH PASSWORD {quoted_password};\n"
    _run([
        "docker", "exec", "-i", "agency-postgres", "psql", "-v", "ON_ERROR_STOP=1",
        "-U", user, "-d", database,
    ], input_text=statement)


def sync_service_env() -> dict[str, Any]:
    """Generate least-privilege service mappings from the canonical core value."""
    core = _env(CREDENTIAL_DIR / "core.env")
    password = core.get("POSTGRES_PASSWORD")
    if not password:
        raise MaintenanceError("required PostgreSQL configuration is missing")
    _atomic_env(CREDENTIAL_DIR / "bot.env", {"PGPASSWORD": password})
    _atomic_env(CREDENTIAL_DIR / "caddy-ask.env", {"POSTGRES_PASSWORD": password})
    return {
        "updated": ["bot.env:PGPASSWORD", "caddy-ask.env:POSTGRES_PASSWORD"],
        "values_printed": False,
    }


def rotate_internal(compromised: bool) -> dict[str, Any]:
    if not compromised:
        raise MaintenanceError("rotate-internal requires --compromised")
    begin()
    paths = {
        CREDENTIAL_DIR / "core.env": None,
        CREDENTIAL_DIR / "bot.env": None,
        CREDENTIAL_DIR / "caddy-ask.env": None,
    }
    credentials_committed = False
    postgres_changed = False
    files_write_started = False
    dashboard_stopped = False
    old: dict[str, str] = {}
    try:
        for path in paths:
            try:
                paths[path] = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                paths[path] = None
            except OSError as exc:
                raise MaintenanceError("credential file unavailable") from exc
        old = _env(CREDENTIAL_DIR / "core.env")
        for required in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD"):
            if not old.get(required):
                raise MaintenanceError("required PostgreSQL configuration is missing")
        updates = {name: _strong_secret() for name in ("POSTGRES_PASSWORD", "CLICKHOUSE_PASSWORD", "MINIO_ROOT_PASSWORD")}
        _run(["docker", "stop", "agency-dashboard"])
        dashboard_stopped = True
        _set_postgres_password(
            old.get("POSTGRES_USER", "agency"),
            old.get("POSTGRES_DB", "agencyos"),
            updates["POSTGRES_PASSWORD"],
        )
        postgres_changed = True
        files_write_started = True
        _atomic_env(CREDENTIAL_DIR / "core.env", updates)
        _atomic_env(CREDENTIAL_DIR / "bot.env", {"PGPASSWORD": updates["POSTGRES_PASSWORD"]})
        _atomic_env(CREDENTIAL_DIR / "caddy-ask.env", {"POSTGRES_PASSWORD": updates["POSTGRES_PASSWORD"]})
        credentials_committed = True
        legacy_cleanup = True
        try:
            _run(["sudo", "-n", ROOT_HELPER, "remove-legacy-opencode-db-secret"], timeout=60)
        except MaintenanceError:
            legacy_cleanup = False
        _run([
            "docker", "compose", "--env-file", str(CREDENTIAL_DIR / "core.env"),
            "-f", str(CORE_COMPOSE), "up", "-d", "--force-recreate", "--no-deps",
            "postgres", "clickhouse", "minio",
        ])
        _run([
            "docker", "compose", "--env-file", str(CREDENTIAL_DIR / "core.env"),
            "-f", str(DASHBOARD_COMPOSE), "up", "-d", "--force-recreate", "--no-deps",
            "dashboard",
        ])
        result = resume()
        result["legacy_cleanup"] = "complete" if legacy_cleanup else "pending"
        if not legacy_cleanup:
            state = _state()
            state["legacy_cleanup"] = "pending"
            _write_state(state)
        return result
    except Exception as exc:
        recovered = False
        if not credentials_committed:
            rollback_ok = True
            if postgres_changed:
                try:
                    _set_postgres_password(
                        old.get("POSTGRES_USER", "agency"),
                        old.get("POSTGRES_DB", "agencyos"),
                        old.get("POSTGRES_PASSWORD", ""),
                    )
                except MaintenanceError:
                    rollback_ok = False
            if files_write_started:
                for path, original in paths.items():
                    try:
                        _restore_env(path, original)
                    except OSError:
                        rollback_ok = False
            if dashboard_stopped:
                try:
                    _run(["docker", "start", "agency-dashboard"])
                except MaintenanceError:
                    rollback_ok = False
            try:
                _run(["sudo", "-n", ROOT_HELPER, "maintenance-resume"], timeout=60)
            except MaintenanceError:
                rollback_ok = False
            recovered = rollback_ok
        _write_state({
            "phase": "failed_recovered" if recovered else "active",
            "error": "internal rotation failed",
            "services_resumed": recovered,
        })
        if isinstance(exc, MaintenanceError):
            raise
        raise MaintenanceError("internal rotation failed") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status"); sub.add_parser("begin"); sub.add_parser("resume")
    sub.add_parser("sync-service-env")
    rotate = sub.add_parser("rotate-internal"); rotate.add_argument("--compromised", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = {
            "status": status,
            "begin": begin,
            "resume": resume,
            "sync-service-env": sync_service_env,
        }.get(args.command, lambda: rotate_internal(args.compromised))()
        print(json.dumps(result, sort_keys=True))
        return 0
    except MaintenanceError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
