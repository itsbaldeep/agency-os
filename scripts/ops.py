#!/usr/bin/env python3
"""Minimal recovery, off-site acknowledgement, and credential audit CLI.

Secret values are consumed only as subprocess environment or backup payload. They
are never printed, placed in manifests, or written to Postgres/ClickHouse.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


AGENCY_HOME = Path(os.environ.get("AGENCY_HOME", "/home/agency"))
CREDENTIAL_DIR = Path(
    os.environ.get("AGENCY_CREDENTIAL_DIR", AGENCY_HOME / ".config/agency")
)
STATE_DIR = Path(
    os.environ.get("AGENCY_STATE_DIR", AGENCY_HOME / ".local/state/agency-os")
)
BACKUP_DIR = Path(
    os.environ.get("AGENCY_BACKUP_DIR", AGENCY_HOME / "backups/core")
)
OPS_STATE = STATE_DIR / "operations.json"
ROTATION_STATE = STATE_DIR / "credential-rotations.json"
ROOT_BACKUP_DIR = AGENCY_HOME / "backups/system"
ROOT_HELPER = "/usr/local/sbin/codex-system-audit"
SENSITIVE_NAME = re.compile(r"(TOKEN|KEY|SECRET|PASSWORD|PASS|ACCESS|WEBHOOK|AUTH)")
PLACEHOLDER = re.compile(r"^(|change-?me!?|placeholder|example|default|test|secret)$", re.I)
WEAK_MARKERS = ("password", "changeme", "placeholder", "agency", "clickhouse", "hearth", "admin")


class OpsError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value.strip().strip('"').strip("'")
    return values


def core_env() -> dict[str, str]:
    return parse_env(CREDENTIAL_DIR / "core.env")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    stdout: Any = subprocess.PIPE,
    timeout: int = 180,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            check=True,
            stdout=stdout,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise OpsError(f"required command is missing: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise OpsError(f"command timed out: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise OpsError(f"command failed: {command[0]}{suffix}") from exc


def add_tar_path(archive: tarfile.TarFile, source: Path, arcname: str) -> bool:
    if not source.exists():
        return False
    try:
        archive.add(source, arcname=arcname, recursive=True)
        return True
    except (OSError, PermissionError):
        return False


def export_postgres(destination: Path, env_values: dict[str, str]) -> None:
    required = ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD")
    missing = [name for name in required if not env_values.get(name)]
    if missing:
        raise OpsError("Postgres environment is incomplete: " + ", ".join(missing))
    process_env = os.environ.copy()
    process_env["PGPASSWORD"] = env_values["POSTGRES_PASSWORD"]
    run(
        [
            "pg_dump",
            "-h",
            "100.64.0.1",
            "-U",
            env_values["POSTGRES_USER"],
            "-d",
            env_values["POSTGRES_DB"],
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            f"--file={destination}",
        ],
        env=process_env,
    )


def export_clickhouse(stage: Path) -> dict[str, bool]:
    datasets = ("events", "ai_visibility_checks")
    exported: dict[str, bool] = {}
    for table in datasets:
        schema_path = stage / f"clickhouse-{table}.sql"
        data_path = stage / f"clickhouse-{table}.native"
        auth = 'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD"'
        try:
            with schema_path.open("wb") as output:
                run(
                    ["docker", "exec", "agency-clickhouse", "sh", "-lc",
                     f"exec {auth} --query {shlex.quote(f'SHOW CREATE TABLE default.{table}') }"],
                    stdout=output,
                )
            with data_path.open("wb") as output:
                run(
                    ["docker", "exec", "agency-clickhouse", "sh", "-lc",
                     f"exec {auth} --query {shlex.quote(f'SELECT * FROM default.{table} FORMAT Native') }"],
                    stdout=output,
                )
            exported[table] = True
        except OpsError:
            schema_path.unlink(missing_ok=True)
            data_path.unlink(missing_ok=True)
            exported[table] = False
    return exported


def export_credentials(destination: Path) -> bool:
    files = [path for path in CREDENTIAL_DIR.iterdir() if path.is_file()]
    if not files:
        return False
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(files):
            archive.add(path, arcname=path.name, recursive=False)
    os.chmod(destination, 0o600)
    return True


def export_configs(destination: Path) -> dict[str, bool]:
    sources = {
        "root-agents": AGENCY_HOME / "AGENTS.md",
        "agency-os-infra": AGENCY_HOME / "projects/agency-os/infra",
        "agency-os-directive": AGENCY_HOME / "projects/agency-os/CEO_DIRECTIVE.md",
        "agency-os-roadmap": AGENCY_HOME / "projects/agency-os/ROADMAP.md",
        "caddy": Path("/etc/caddy"),
        "headscale-config": Path("/etc/headscale/config.yaml"),
    }
    included: dict[str, bool] = {}
    with tarfile.open(destination, "w:gz") as archive:
        for name, path in sources.items():
            included[name] = add_tar_path(archive, path, name)
    return included


def request_root_backup(stage: Path) -> bool:
    before = set(ROOT_BACKUP_DIR.glob("core-system-*.tar*")) if ROOT_BACKUP_DIR.exists() else set()
    try:
        run(["sudo", "-n", ROOT_HELPER, "backup-core"], timeout=60)
    except OpsError:
        return False
    after = set(ROOT_BACKUP_DIR.glob("core-system-*.tar*")) if ROOT_BACKUP_DIR.exists() else set()
    created = sorted(after - before, key=lambda path: path.stat().st_mtime)
    if not created:
        return False
    shutil.copy2(created[-1], stage / created[-1].name)
    return True


def repo_state(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return result
    try:
        head = run(["git", "-C", str(path), "rev-parse", "HEAD"], timeout=15)
        status = run(["git", "-C", str(path), "status", "--porcelain"], timeout=15)
        result.update(
            head=head.stdout.decode().strip(),
            dirty=bool(status.stdout.decode().strip()),
        )
    except OpsError:
        result["git"] = False
    return result


def prune_backups(now: datetime, keep_days: int = 14) -> int:
    removed = 0
    cutoff = now.timestamp() - keep_days * 86400
    for path in BACKUP_DIR.glob("core-backup-*.tar.gz"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed


def create_backup() -> dict[str, Any]:
    now = utc_now()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=BACKUP_DIR))
    os.chmod(stage, 0o700)
    final = BACKUP_DIR / f"core-backup-{now.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
    try:
        env_values = core_env()
        export_postgres(stage / "postgres.dump", env_values)
        clickhouse = export_clickhouse(stage)
        credentials = export_credentials(stage / "credentials.tar.gz")
        configs = export_configs(stage / "configs.tar.gz")
        root_state = request_root_backup(stage)

        minio_data = AGENCY_HOME / "agency-os/data/minio"
        minio_included = False
        if minio_data.exists():
            with tarfile.open(stage / "agency-minio.tar.gz", "w:gz") as archive:
                minio_included = add_tar_path(archive, minio_data, "minio")

        manifest = {
            "created_at": now.replace(microsecond=0).isoformat(),
            "format": 1,
            "components": {
                "postgres": True,
                "clickhouse": clickhouse,
                "credentials": credentials,
                "configs": configs,
                "agency_minio": minio_included,
                "root_state": root_state,
            },
            "repositories": [
                repo_state(AGENCY_HOME / "projects/agency-os"),
                repo_state(AGENCY_HOME / "projects/agency-dashboard"),
            ],
        }
        component_files = sorted(path for path in stage.iterdir() if path.is_file())
        manifest["files"] = {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in component_files
        }
        write_json(stage / "manifest.json", manifest)

        tmp_bundle = final.with_suffix(final.suffix + ".tmp")
        with tarfile.open(tmp_bundle, "w:gz") as archive:
            for path in sorted(stage.iterdir()):
                archive.add(path, arcname=path.name, recursive=True)
        os.chmod(tmp_bundle, 0o600)
        os.replace(tmp_bundle, final)

        state = read_json(OPS_STATE, {})
        state["last_backup"] = {
            "at": manifest["created_at"],
            "path": str(final),
            "bytes": final.stat().st_size,
            "sha256": sha256(final),
            "root_state_included": root_state,
        }
        write_json(OPS_STATE, state)
        removed = prune_backups(now)
        return {**state["last_backup"], "retention_removed": removed}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def latest_saturday(today: date) -> date:
    return today - timedelta(days=(today.weekday() - 5) % 7)


def operations_status(today: date | None = None) -> dict[str, Any]:
    today = today or utc_now().date()
    state = read_json(OPS_STATE, {})
    last_backup = state.get("last_backup") or {}
    offsite = state.get("offsite") or {}
    required_since = latest_saturday(today)
    try:
        confirmed = date.fromisoformat(offsite.get("confirmed_on", ""))
    except ValueError:
        confirmed = None
    return {
        "last_backup": last_backup,
        "offsite": {
            "required_since": required_since.isoformat(),
            "confirmed_on": confirmed.isoformat() if confirmed else None,
            "overdue": confirmed is None or confirmed < required_since,
        },
    }


def mark_offsite(note: str = "") -> dict[str, Any]:
    state = read_json(OPS_STATE, {})
    state["offsite"] = {
        "confirmed_on": utc_now().date().isoformat(),
        "confirmed_at": iso_now(),
        "note": note[:200],
    }
    write_json(OPS_STATE, state)
    return operations_status()


def credential_inventory() -> list[dict[str, Any]]:
    rotations = read_json(ROTATION_STATE, {})
    records: list[dict[str, Any]] = []
    for env_path in sorted(CREDENTIAL_DIR.glob("*.env")):
        for name, value in sorted(parse_env(env_path).items()):
            if not SENSITIVE_NAME.search(name):
                continue
            key = f"{env_path.name}:{name}"
            records.append(
                {
                    "id": key,
                    "name": name,
                    "source": env_path.name,
                    "placeholder_like": credential_looks_weak(value),
                    "human_rotated_at": (rotations.get(key) or {}).get("at"),
                }
            )
    gsc = CREDENTIAL_DIR / "gsc-service-account.json"
    if gsc.exists():
        key = "gsc-service-account.json:GSC_SERVICE_ACCOUNT"
        records.append(
            {
                "id": key,
                "name": "GSC_SERVICE_ACCOUNT",
                "source": gsc.name,
                "placeholder_like": False,
                "human_rotated_at": (rotations.get(key) or {}).get("at"),
            }
        )
    return records


def credential_looks_weak(value: str) -> bool:
    normalized = value.strip().lower()
    if PLACEHOLDER.fullmatch(normalized):
        return True
    if len(normalized) < 16:
        return True
    return any(marker in normalized for marker in WEAK_MARKERS)


def mark_credential(identifier: str) -> list[dict[str, Any]]:
    valid = {item["id"] for item in credential_inventory()}
    if identifier not in valid:
        raise OpsError("unknown credential identifier; run credentials first")
    rotations = read_json(ROTATION_STATE, {})
    rotations[identifier] = {"at": iso_now(), "acknowledged_by": "human"}
    write_json(ROTATION_STATE, rotations)
    return credential_inventory()


def verify_backup(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise OpsError(f"backup not found: {path}")
    with tarfile.open(path, "r:gz") as archive:
        names = set(archive.getnames())
        if "manifest.json" not in names:
            raise OpsError("manifest.json is missing")
        member = archive.extractfile("manifest.json")
        if member is None:
            raise OpsError("manifest.json is unreadable")
        manifest = json.load(member)
        for name, expected in manifest.get("files", {}).items():
            extracted = archive.extractfile(name)
            if extracted is None:
                raise OpsError(f"backup component is missing: {name}")
            digest = hashlib.sha256()
            for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                digest.update(chunk)
            if digest.hexdigest() != expected.get("sha256"):
                raise OpsError(f"checksum mismatch: {name}")
    return {
        "ok": True,
        "created_at": manifest.get("created_at"),
        "components": manifest.get("components", {}),
        "bundle_sha256": sha256(path),
    }


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="create the daily core recovery bundle")
    commands.add_parser("status", help="show backup/off-site acknowledgement state")
    offsite = commands.add_parser("mark-offsite", help="acknowledge laptop/off-site copy")
    offsite.add_argument("--note", default="")
    commands.add_parser("credentials", help="list credential names and rotation state")
    rotated = commands.add_parser("mark-credential", help="acknowledge one human rotation")
    rotated.add_argument("identifier")
    verify = commands.add_parser("verify", help="verify a recovery bundle without restoring")
    verify.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            result = create_backup()
        elif args.command == "status":
            result = operations_status()
        elif args.command == "mark-offsite":
            result = mark_offsite(args.note)
        elif args.command == "credentials":
            result = credential_inventory()
        elif args.command == "mark-credential":
            result = mark_credential(args.identifier)
        elif args.command == "verify":
            result = verify_backup(args.bundle)
        else:
            raise OpsError("unsupported command")
        print_json(result)
        return 0
    except OpsError as exc:
        print(f"operations error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
