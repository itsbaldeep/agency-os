#!/usr/bin/env python3
"""Action-oriented daily Discord digest for Agency OS."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import ops  # noqa: E402


LOG = Path("/home/agency/agency-os/logs/digest.log")


def env_value(key: str) -> str:
    return ops.core_env().get(key, "")


PGHOST = "100.64.0.1"
PGUSER = env_value("POSTGRES_USER") or "agency"
PGPASS = env_value("POSTGRES_PASSWORD")
DB = env_value("POSTGRES_DB") or "agencyos"
WEBHOOK = env_value("DISCORD_WEBHOOK_URL")


def pg(query: str) -> str:
    command = [
        "psql", "-h", PGHOST, "-U", PGUSER, "-d", DB,
        "-t", "-A", "-F|", "-v", "ON_ERROR_STOP=1", "-c", query,
    ]
    environment = os.environ.copy()
    environment["PGPASSWORD"] = PGPASS
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=20, env=environment
    )
    if result.returncode:
        raise RuntimeError((result.stderr or "Postgres query failed").strip()[-300:])
    return result.stdout.strip()


def rows(query: str) -> list[list[str]]:
    output = pg(query)
    return [line.split("|") for line in output.splitlines() if line.strip()]


def tracked_spend() -> str:
    result = rows("""
        SELECT
          COALESCE(ROUND(SUM(cost)::numeric,4),0),
          COALESCE(SUM(prompt_tokens),0),
          COALESCE(SUM(completion_tokens),0)
        FROM tasks
        WHERE created_at > now() - interval '24 hours'
    """)
    usd, prompt, completion = result[0] if result else ("0", "0", "0")
    return (
        f"Tracked application work: **${usd}** · {int(prompt):,} input / "
        f"{int(completion):,} output tokens\n"
        "_Codex subscription sessions are not API-billed and are intentionally "
        "outside this application total._"
    )


def failure_summary() -> tuple[str, list[str]]:
    task_rows = rows("""
        SELECT type, count(*) FILTER (WHERE status='failed'), count(*)
        FROM tasks
        WHERE created_at > now() - interval '24 hours'
        GROUP BY type
        HAVING count(*) FILTER (WHERE status='failed') > 0
        ORDER BY count(*) FILTER (WHERE status='failed') DESC, type
    """)
    job_rows = rows("""
        SELECT b.name, count(*) FILTER (WHERE r.status='failed'), count(*)
        FROM job_runs r JOIN background_jobs b ON b.id=r.job_id
        WHERE r.started_at > now() - interval '24 hours'
        GROUP BY b.name
        HAVING count(*) FILTER (WHERE r.status='failed') > 0
        ORDER BY count(*) FILTER (WHERE r.status='failed') DESC, b.name
    """)
    alerts: list[str] = []
    lines: list[str] = []
    for kind, failed, total in task_rows:
        rate = int(failed) / max(int(total), 1)
        icon = "🚨" if int(failed) >= 2 or rate >= 0.25 else "⚠️"
        line = f"{icon} task `{kind}`: {failed}/{total} failed ({rate:.0%})"
        lines.append(line)
        if icon == "🚨":
            alerts.append(line)
    for name, failed, total in job_rows:
        rate = int(failed) / max(int(total), 1)
        icon = "🚨" if int(failed) >= 2 or rate >= 0.25 else "⚠️"
        line = f"{icon} job `{name}`: {failed}/{total} failed ({rate:.0%})"
        lines.append(line)
        if icon == "🚨":
            alerts.append(line)
    return ("\n".join(lines) if lines else "✅ No task/job failures in 24h", alerts)


def work_queue() -> tuple[str, list[str]]:
    queue = rows("""
        SELECT status, count(*) FROM tasks
        WHERE status IN ('queued','running') GROUP BY status ORDER BY status
    """)
    stale = rows("""
        SELECT count(*) FROM tasks
        WHERE (status='running' AND started_at < now() - interval '20 minutes')
           OR (status='queued' AND created_at < now() - interval '30 minutes')
    """)
    pending = rows("SELECT type,count(*) FROM approvals WHERE status='pending' GROUP BY type ORDER BY type")
    stale_count = int(stale[0][0]) if stale else 0
    queue_text = "; ".join(f"{count} {status}" for status, count in queue) or "idle"
    approval_text = "; ".join(f"{count} {kind}" for kind, count in pending) or "none"
    text = f"Tasks: **{queue_text}** · approvals: **{approval_text}**"
    alerts = []
    if stale_count:
        alert = f"🚨 {stale_count} stale queued/running task(s)"
        text += f"\n{alert}"
        alerts.append(alert)
    return text, alerts


def content_pipeline() -> tuple[str, list[str]]:
    result = rows("""
        SELECT
          count(*) FILTER (WHERE status='done'),
          count(*) FILTER (WHERE status='failed'),
          count(*)
        FROM tasks
        WHERE type IN ('content_research','content_outline','content_compose','generate_draft')
          AND created_at > now() - interval '30 days'
    """)
    done, failed, total = (map(int, result[0]) if result else (0, 0, 0))
    rate = failed / total if total else 0
    text = f"30d content tasks: **{done} done · {failed} failed · {total} total**"
    alerts = []
    if total and rate >= 0.20:
        alert = f"🚨 Content failure rate is {rate:.0%}; expansion remains gated"
        text += f"\n{alert}"
        alerts.append(alert)
    elif total:
        text += f" · failure rate {rate:.0%}"
    else:
        text += " · no recent sample"
    return text, alerts


def recovery_and_credentials() -> tuple[str, list[str]]:
    state = ops.operations_status()
    backup = state.get("last_backup") or {}
    offsite = state["offsite"]
    inventory = ops.credential_inventory()
    unrotated = [item for item in inventory if not item["human_rotated_at"]]
    weak = [item for item in inventory if item["placeholder_like"]]
    alerts: list[str] = []
    if backup:
        backup_line = f"Last core backup: `{backup.get('at','unknown')}`"
        if not backup.get("root_state_included"):
            root_alert = "⚠️ Root-only Headscale/OpenCode state is not yet bundled"
            backup_line += f"\n{root_alert}"
            alerts.append(root_alert)
    else:
        backup_line = "🚨 No successful core backup recorded"
        alerts.append(backup_line)
    if offsite["overdue"]:
        offsite_line = (
            f"🚨 Laptop/off-site copy is due for Saturday {offsite['required_since']}. "
            "After SCP, mark it done in Operations."
        )
        alerts.append(offsite_line)
    else:
        offsite_line = f"✅ Off-site copy acknowledged {offsite['confirmed_on']}"
    credential_line = f"Credential audit: **{len(unrotated)} not human-rotated**"
    if weak:
        names = ", ".join(sorted({item["name"] for item in weak}))
        weak_line = f"🚨 Weak/placeholder-like credentials: {names}"
        credential_line += f"\n{weak_line}"
        alerts.append(weak_line)
    return "\n".join((backup_line, offsite_line, credential_line)), alerts


def estate_summary() -> str:
    result = rows("SELECT state,count(*) FROM projects GROUP BY state ORDER BY state")
    return "; ".join(f"**{count}** {state}" for state, count in result) or "No projects registered"


def send_discord(fields: list[dict[str, object]], critical: bool) -> int:
    if not WEBHOOK:
        return -1
    embed = {
        "title": "Agency OS — action digest",
        "description": "Stabilization first: exceptions and required decisions only.",
        "color": 0xFF4757 if critical else 0x2ED573,
        "fields": fields,
        "footer": {"text": f"Agency OS · {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"},
    }
    request = urllib.request.Request(
        WEBHOOK,
        data=json.dumps({"embeds": [embed]}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "AgencyOS-Digest/2.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return -1


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        failures, failure_alerts = failure_summary()
        queue, queue_alerts = work_queue()
        content, content_alerts = content_pipeline()
        recovery, recovery_alerts = recovery_and_credentials()
        alerts = failure_alerts + queue_alerts + content_alerts + recovery_alerts
        action_text = "\n".join(alerts[:8]) if alerts else "✅ No immediate action required"
        fields = [
            {"name": "🚨 Action required", "value": action_text[:1024], "inline": False},
            {"name": "📝 Content reliability", "value": content[:1024], "inline": False},
            {"name": "❌ Failures", "value": failures[:1024], "inline": False},
            {"name": "📥 Work queue", "value": queue[:1024], "inline": False},
            {"name": "💾 Recovery + credentials", "value": recovery[:1024], "inline": False},
            {"name": "💰 Accounted usage", "value": tracked_spend()[:1024], "inline": False},
            {"name": "📦 Estate", "value": estate_summary()[:1024], "inline": False},
        ]
        status = send_discord(fields, bool(alerts))
        with LOG.open("a", encoding="utf-8") as log:
            log.write(f"{ops.iso_now()} digest sent status={status} alerts={len(alerts)}\n")
        print(f"digest status={status} alerts={len(alerts)}")
        return 0 if 200 <= status < 300 else 1
    except Exception as exc:
        with LOG.open("a", encoding="utf-8") as log:
            log.write(f"{ops.iso_now()} digest failed: {str(exc)[:300]}\n")
        print(f"digest failed: {str(exc)[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
