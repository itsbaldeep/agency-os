#!/usr/bin/env python3
"""Daily Discord digest — system summary for the last 24h."""

import json, os, re, subprocess, sys, urllib.request
from datetime import datetime, timezone

ENV_PATH = "/home/agency/agency-os/.env"
LOG = "/home/agency/agency-os/logs/digest.log"

def env_val(key):
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return ""

PGHOST = "100.64.0.1"
PGUSER = "agency"
PGPASS = env_val("POSTGRES_PASSWORD")
WEBHOOK = env_val("DISCORD_WEBHOOK_URL")
DB = "agencyos"

def pg(query):
    cmd = [
        "psql", "-h", PGHOST, "-U", PGUSER, "-d", DB,
        "-t", "-A", "-F|", "-c", query,
    ]
    env = os.environ.copy()
    env["PGPASSWORD"] = PGPASS
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
    return r.stdout.strip()

def ch(query):
    cmd = [
        "docker", "exec", "agency-clickhouse",
        "clickhouse-client", "-q", query,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return r.stdout.strip()

# ── 1. Spend ──────────────────────────────────────────────────────
def get_spend():
    rows_24h = pg("""
        SELECT
          COALESCE(ROUND(SUM(j.cost_usd)::numeric,4),0) AS j_usd,
          COALESCE(ROUND(SUM(j.cost_inr)::numeric,2),0) AS j_inr,
          COALESCE(ROUND(SUM(t.cost)::numeric,4),0)      AS t_usd
        FROM job_runs j FULL JOIN tasks t ON false
        WHERE j.started_at > now() - interval '24 hours'
           OR t.created_at > now() - interval '24 hours'
    """)
    rows_mtd = pg("""
        SELECT
          COALESCE(ROUND(SUM(j.cost_usd)::numeric,4),0) AS j_usd,
          COALESCE(ROUND(SUM(j.cost_inr)::numeric,2),0) AS j_inr,
          COALESCE(ROUND(SUM(t.cost)::numeric,4),0)      AS t_usd
        FROM job_runs j FULL JOIN tasks t ON false
        WHERE j.started_at >= date_trunc('month', now())
           OR t.created_at >= date_trunc('month', now())
    """)
    def parse(row):
        parts = row.split("|")
        return float(parts[0]), float(parts[1]), float(parts[2])
    j24, ji24, t24 = parse(rows_24h)
    jm, jim, tm = parse(rows_mtd)
    usd_24 = round(j24 + t24, 4)
    inr_24 = round(ji24, 2)
    usd_mtd = round(jm + tm, 4)
    inr_mtd = round(jim, 2)
    return (f"24h: ${usd_24} / ₹{inr_24}  |  MTD: ${usd_mtd} / ₹{inr_mtd}", usd_24)

# ── 2. Jobs ───────────────────────────────────────────────────────
def get_jobs():
    rows = pg("""
        SELECT status, count(*) FROM job_runs
        WHERE started_at > now() - interval '24 hours'
        GROUP BY status ORDER BY status
    """)
    counts = {}
    for line in rows.split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        s, c = line.split("|", 1)
        counts[s.strip()] = int(c.strip())
    total = sum(counts.values())
    failed = counts.get("failed", 0) or counts.get("Failed", 0)
    parts = [f"**{total}** total"]
    for s in sorted(counts):
        c = counts[s]
        if s == "failed":
            parts.append(f"⚠️ {c} failed")
        else:
            parts.append(f"{c} {s}")
    alert = ""
    if failed:
        alert = f"\n⚠️ **{failed} job(s) failed** — check logs"
    return "; ".join(parts) + alert

# ── 3. Async tasks ────────────────────────────────────────────────
def get_tasks():
    rows = pg("""
        SELECT status, count(*) FROM tasks
        WHERE created_at > now() - interval '24 hours'
        GROUP BY status ORDER BY status
    """)
    counts = {}
    for line in rows.split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        s, c = line.split("|", 1)
        counts[s.strip()] = int(c.strip())
    total = sum(counts.values())
    if total == 0:
        return "0 (idle)"
    parts = [f"**{total}** total"]
    for s in sorted(counts):
        parts.append(f"{counts[s]} {s}")
    return "; ".join(parts)

# ── 4. Approvals ──────────────────────────────────────────────────
def get_approvals():
    rows = pg("""
        SELECT type, count(*) FROM approvals
        WHERE status='pending' GROUP BY type ORDER BY type
    """)
    counts = {}
    for line in rows.split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        t, c = line.split("|", 1)
        counts[t.strip()] = int(c.strip())
    total = sum(counts.values())
    if total == 0:
        return "✅ None pending"
    parts = [f"**{total}** pending"]
    for t in sorted(counts):
        parts.append(f"{t}: {counts[t]}")
    return "; ".join(parts)

# ── 5. Projects + alerts ──────────────────────────────────────────
def get_projects():
    rows = pg("""
        SELECT name, state FROM projects ORDER BY name
    """)
    lines = []
    for line in rows.split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        n, s = line.split("|", 1)
        icon = {"live": "🟢", "preview": "🔵", "building": "🟡", "failed": "🔴"}.get(s.strip(), "⚪")
        lines.append(f"{icon} **{n.strip()}** ({s.strip()})")
    projects_text = "\n".join(lines) if lines else "None registered"

    # security scan findings in last 24h from ClickHouse
    ch_count = ch("""
        SELECT count() FROM events
        WHERE action = 'security_scan'
          AND ts > now() - INTERVAL 24 HOUR
    """)
    try:
        scan_count = int(ch_count.strip())
    except (ValueError, AttributeError):
        scan_count = 0
    alert_line = ""
    if scan_count > 0:
        alert_line = f"\n🔍 Security scans ran **{scan_count}x** in 24h"
    return projects_text + alert_line

# ── Discord send ──────────────────────────────────────────────────
def send_discord(title, fields, color):
    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "footer": {"text": f"Agency OS · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"},
    }
    body = json.dumps({"embeds": [embed]}).encode()
    req = urllib.request.Request(WEBHOOK, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "AgencyOS-Digest/1.0")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return -1

# ── Main ──────────────────────────────────────────────────────────
def main():
    with open(LOG, "a") as log:
        log.write(f"{datetime.now(timezone.utc).isoformat()} digest starting\n")

        spend_text, usd = get_spend()
        jobs_text = get_jobs()
        tasks_text = get_tasks()
        approvals_text = get_approvals()
        projects_text = get_projects()

        fields = [
            {"name": "💰 Spend", "value": spend_text, "inline": False},
            {"name": "⚙️  Scheduled Jobs (24h)", "value": jobs_text, "inline": True},
            {"name": "🧠 Async Tasks (24h)", "value": tasks_text, "inline": True},
            {"name": "📋 Approvals", "value": approvals_text, "inline": False},
            {"name": "📦 Projects", "value": projects_text, "inline": False},
        ]

        color = 0x00FF00 if usd < 0.1 else 0xFFA500
        status = send_discord("🌅 Agency OS Daily Digest", fields, color)
        log.write(f"{datetime.now(timezone.utc).isoformat()} digest sent — HTTP {status}\n")

        # Print for job_runs detail capture
        print(f"Spend: {spend_text}")
        print(f"Jobs: {jobs_text}")
        print(f"Tasks: {tasks_text}")
        print(f"Approvals: {approvals_text}")
        print(f"Projects: {projects_text}")
        print(f"Discord HTTP {status}")

        sys.exit(0 if str(status).startswith("2") else 1)

if __name__ == "__main__":
    main()
