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


def package_name(value):
    """Normalize APT's optional multi-arch suffix for human-facing evidence."""
    return value.split(":", 1)[0]


def listed_packages(list_output):
    return sorted({
        package_name(line.split("/", 1)[0])
        for line in list_output.splitlines()
        if "/" in line and not line.startswith("Listing")
    })


def package_updates(list_output, simulation_output):
    """Separate packages APT will install now from policy-deferred candidates."""
    candidates = set(listed_packages(list_output))
    installable = {
        package_name(fields[1])
        for line in simulation_output.splitlines()
        if line.startswith("Inst ") and len(fields := line.split()) > 1
    }
    return sorted(installable), sorted(candidates - installable)


def maintenance():
    """Return names/counts only; never publish package source credentials."""
    list_ok = True
    try:
        list_output = run("apt", "list", "--upgradable")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        list_output = ""
        list_ok = False
    simulation_ok = True
    try:
        simulation_output = run("apt-get", "-s", "upgrade")
        packages, deferred = package_updates(list_output, simulation_output)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Preserve the prior conservative behavior if APT simulation is unavailable.
        packages = listed_packages(list_output)
        deferred = []
        simulation_ok = False
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
        "deferred_count": len(deferred),
        "deferred_packages": deferred,
        "apt_check_ok": list_ok and simulation_ok,
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
    # This snapshot contains names and aggregate host metrics only. The
    # dashboard runs under an isolated non-root UID and mounts it read-only, so
    # traversal/read permissions must not depend on matching host UIDs.
    DESTINATION.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    current_mode = DESTINATION.parent.stat().st_mode & 0o7777
    os.chmod(DESTINATION.parent, current_mode | 0o055)
    fd, tmp_name = tempfile.mkstemp(prefix=".host-health.", dir=DESTINATION.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, DESTINATION)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
