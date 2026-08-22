#!/usr/bin/env python3
"""Write a secret-free host/container health snapshot for the dashboard."""
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DESTINATION = Path(os.environ.get(
    "AGENCY_HOST_HEALTH_FILE",
    "/home/agency/.local/state/agency-os/host-health.json",
))


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=30, check=True).stdout


def human_bytes(value):
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f}{unit}" if unit != "GiB" else f"{size:.1f}{unit}"
        size /= 1024


def memory():
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, raw, *_ = line.replace(":", "").split()
        if key in ("MemTotal", "MemAvailable"):
            values[key] = int(raw) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = max(0, total - available)
    return {
        "total_gb": round(total / 1024**3, 1), "used_gb": round(used / 1024**3, 1),
        "avail_gb": round(available / 1024**3, 1),
        "used_perc": f"{round(used / total * 100) if total else 0}%",
        "total_mb": round(total / 1024**2), "used_mb": round(used / 1024**2),
        "avail_mb": round(available / 1024**2),
    }


def maintenance():
    """Return names/counts only; never publish package source credentials."""
    try:
        output = run("apt", "list", "--upgradable")
        packages = sorted({
            line.split("/", 1)[0]
            for line in output.splitlines()
            if "/" in line and not line.startswith("Listing")
        })
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        packages = []
    reboot_marker = Path("/var/run/reboot-required")
    reboot_packages = Path("/var/run/reboot-required.pkgs")
    try:
        reboot_names = sorted({
            line.strip() for line in reboot_packages.read_text().splitlines()
            if line.strip()
        })
    except OSError:
        reboot_names = []
    return {
        "upgradable_count": len(packages),
        "upgradable_packages": packages,
        "reboot_required": reboot_marker.exists(),
        "reboot_packages": reboot_names,
    }


def main():
    containers = []
    for line in run("docker", "stats", "--no-stream", "--format", "{{json .}}").splitlines():
        item = json.loads(line)
        item["Container"] = item.get("Name") or item.get("Container")
        containers.append({k: item.get(k, "") for k in (
            "Container", "CPUPerc", "MemUsage", "MemPerc", "PIDs",
        )})
    networks = run("docker", "network", "ls", "--format", "{{.Name}}").splitlines()
    disk = shutil.disk_usage("/")
    load = Path("/proc/loadavg").read_text().split()
    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "containers": containers,
        "networks": sorted(n for n in networks if n.startswith("net-") and n != "net-control"),
        "memory": memory(),
        "maintenance": maintenance(),
        "cpu": {"load_1m": load[0], "load_5m": load[1], "load_15m": load[2]},
        "disk": {
            "size": human_bytes(disk.total), "used": human_bytes(disk.used),
            "avail": human_bytes(disk.free), "use_perc": f"{round(disk.used / disk.total * 100)}%",
        },
    }
    DESTINATION.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=".host-health.", dir=DESTINATION.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, DESTINATION)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
