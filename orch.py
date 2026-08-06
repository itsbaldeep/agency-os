#!/usr/bin/env python3
"""
orch — Agency OS CLI for reading/writing the Postgres state ledger.
Usage: orch <command> [options]
"""
import base64, click, psycopg2, psycopg2.extras, json, os, sys, time, urllib.request
from datetime import datetime

def get_ch_creds():
    env_path = "/home/agency/agency-os/.env"
    env_text = open(env_path).read()
    user, pw = "agency", ""
    for line in env_text.splitlines():
        if line.startswith("CLICKHOUSE_PASSWORD="):
            pw = line.split("=", 1)[1].strip()
    return user, pw or "changeme_strong_password"

def ch_trace(event):
    user, pw = get_ch_creds()
    all_cols = {"project","session_id","actor","action","detail","exit_code","duration_ms",
                "model","tokens_in","tokens_out","cost_usd","gate","decision","ok"}
    cols = [c for c in all_cols if c in event and event[c] != ""]
    if not cols:
        return
    vals = [str(event[c]) for c in cols]
    sql = f"INSERT INTO default.events ({','.join(cols)}) FORMAT TabSeparated\n"
    sql += "\t".join(vals)
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req = urllib.request.Request(
        "http://100.64.0.1:8123/", data=sql.encode(),
        headers={"Authorization": f"Basic {auth}"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def get_conn():
    pw = os.environ.get("PGPASSWORD") or open("/home/agency/agency-os/.env").read()
    if "POSTGRES_PASSWORD=" in pw:
        pw = [l.split("=",1)[1].strip() for l in pw.splitlines() if l.startswith("POSTGRES_PASSWORD=")][0]
    return psycopg2.connect(host="100.64.0.1", port=5432, dbname="agencyos",
                            user="agency", password=pw,
                            cursor_factory=psycopg2.extras.RealDictCursor)

@click.group()
def cli():
    """Agency OS state ledger CLI."""
    pass

# ── projects ──────────────────────────────────────────────────────────────────

@cli.group()
def project():
    """Manage projects."""
    pass

@project.command("list")
def project_list():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT name, state, repo_url, created_at FROM projects ORDER BY created_at DESC")
    rows = cur.fetchall()
    if not rows:
        click.echo("No projects yet.")
        return
    click.echo(f"{'NAME':<20} {'STATE':<15} {'REPO'}")
    for r in rows:
        click.echo(f"{r['name']:<20} {r['state']:<15} {r['repo_url'] or '-'}")
    conn.close()

@project.command("new")
@click.argument("name")
@click.option("--prd", default=None)
@click.option("--repo", default=None)
def project_new(name, prd, repo):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO projects (name, prd_path, repo_url) VALUES (%s,%s,%s) RETURNING id",
        (name, prd, repo))
    pid = cur.fetchone()["id"]
    conn.commit(); conn.close()
    _auto_trace(name, "project_new", f"Project '{name}' created, prd={prd}, repo={repo}")
    click.echo(f"Created project '{name}' id={pid}")

@project.command("show")
@click.argument("name")
def project_show(name):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM projects WHERE name=%s", (name,))
    p = cur.fetchone()
    if not p:
        click.echo(f"Project '{name}' not found."); return
    click.echo(json.dumps(dict(p), default=str, indent=2))
    cur.execute("SELECT * FROM services WHERE project_id=%s", (p["id"],))
    svcs = cur.fetchall()
    if svcs:
        click.echo("\nServices:")
        for s in svcs:
            click.echo(f"  {s['name']:<20} {s['kind']:<12} {s['status']:<10} port={s['port']} mem={s['mem_limit_mb']}MB")
    conn.close()

@project.command("status")
@click.argument("name")
@click.argument("state")
def project_status(name, state):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE projects SET state=%s::project_state, updated_at=now() WHERE name=%s", (state, name))
    conn.commit(); conn.close()
    click.echo(f"Project '{name}' → {state}")

# ── ports ─────────────────────────────────────────────────────────────────────

@cli.command("port")
@click.argument("action")
@click.argument("project_name")
@click.argument("service_name")
@click.option("--range-start", default=3000)
@click.option("--range-end", default=3999)
def port_alloc(action, project_name, service_name, range_start, range_end):
    """Allocate a free port: orch port alloc <project> <service>"""
    if action != "alloc":
        click.echo("Usage: orch port alloc <project> <service>"); return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT port FROM ports ORDER BY port")
    used = {r["port"] for r in cur.fetchall()}
    free = next((p for p in range(range_start, range_end+1) if p not in used), None)
    if not free:
        click.echo("ERROR: no free ports in range"); sys.exit(1)
    cur.execute("SELECT id FROM projects WHERE name=%s", (project_name,))
    proj = cur.fetchone()
    if not proj:
        click.echo(f"ERROR: project '{project_name}' not found"); sys.exit(1)
    cur.execute("INSERT INTO ports (port, project_id, service) VALUES (%s,%s,%s)",
                (free, proj["id"], service_name))
    conn.commit(); conn.close()
    click.echo(str(free))

# ── approvals ─────────────────────────────────────────────────────────────────

@cli.group()
def approval():
    """Manage approvals."""
    pass

@approval.command("request")
@click.option("--type", "atype", required=True)
@click.option("--project", required=True)
@click.option("--payload", required=True)
def approval_request(atype, project, payload):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM projects WHERE name=%s", (project,))
    proj = cur.fetchone()
    pid = proj["id"] if proj else None
    cur.execute(
        "INSERT INTO approvals (project_id, type, payload) VALUES (%s,%s,%s) RETURNING id",
        (pid, atype, json.dumps(json.loads(payload))))
    aid = cur.fetchone()["id"]
    conn.commit(); conn.close()
    click.echo(f"Approval requested id={aid} type={atype} status=pending")

@approval.command("list")
@click.option("--pending", is_flag=True)
def approval_list(pending):
    conn = get_conn(); cur = conn.cursor()
    q = "SELECT id, type, status, payload, requested_at FROM approvals"
    if pending:
        q += " WHERE status='pending'"
    q += " ORDER BY requested_at DESC LIMIT 20"
    cur.execute(q)
    rows = cur.fetchall()
    if not rows:
        click.echo("No approvals."); return
    for r in rows:
        click.echo(f"[{r['id']}] {r['type']:<10} {r['status']:<10} {str(r['requested_at'])[:19]}  {json.dumps(r['payload'])}")
    conn.close()

@approval.command("decide")
@click.argument("approval_id", type=int)
@click.argument("decision")
@click.option("--note", default=None)
def approval_decide(approval_id, decision, note):
    if decision not in ("approved", "rejected"):
        click.echo("decision must be 'approved' or 'rejected'"); return
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "UPDATE approvals SET status=%s, decided_at=now(), note=%s WHERE id=%s",
        (decision, note, approval_id))
    conn.commit(); conn.close()
    _auto_trace("system", f"approval_{decision}", f"Approval {approval_id} → {decision}")
    click.echo(f"Approval {approval_id} → {decision}")

# ── dns ───────────────────────────────────────────────────────────────────────

@cli.command("dns")
@click.argument("action")
@click.argument("project_name")
@click.argument("subdomain")
@click.option("--target", default=None)
def dns_stage(action, project_name, subdomain, target):
    """Stage a DNS record for approval: orch dns stage <project> <subdomain> --target <service>"""
    if action != "stage":
        click.echo("Usage: orch dns stage <project> <subdomain> --target <service>"); return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM projects WHERE name=%s", (project_name,))
    proj = cur.fetchone()
    if not proj:
        click.echo(f"ERROR: project '{project_name}' not found"); sys.exit(1)
    cur.execute(
        "INSERT INTO dns_records (project_id, subdomain, target_service) VALUES (%s,%s,%s) "
        "ON CONFLICT (subdomain) DO UPDATE SET state='under_approval', target_service=%s",
        (proj["id"], subdomain, target, target))
    conn.commit(); conn.close()
    click.echo(f"DNS staged: {subdomain} → under_approval")

# ── deploy preview ────────────────────────────────────────────────────────────

@cli.command("deploy")
@click.argument("action")
@click.argument("project_name")
@click.argument("service_name")
@click.option("--port", type=int, required=True)
def deploy_preview(action, project_name, service_name, port):
    """Record a VPN-only preview deployment."""
    if action != "preview":
        click.echo("Usage: orch deploy preview <project> <service> --port <p>"); return
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM projects WHERE name=%s", (project_name,))
    proj = cur.fetchone()
    if not proj:
        click.echo(f"ERROR: project '{project_name}' not found"); sys.exit(1)
    cur.execute("""
        INSERT INTO services (project_id, name, kind, port, status)
        VALUES (%s,%s,'frontend',%s,'running')
        ON CONFLICT (project_id, name) DO UPDATE SET port=%s, status='running', last_seen=now()
    """, (proj["id"], service_name, port, port))
    cur.execute("UPDATE projects SET state='preview', updated_at=now() WHERE name=%s", (project_name,))
    conn.commit(); conn.close()
    _auto_trace(project_name, "deploy_preview", f"{service_name} deployed on port {port}")
    click.echo(f"Preview recorded: {project_name}/{service_name} → VPN::{port}")

# ── trace ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("event_json")
def trace(event_json):
    """Record an event to ClickHouse: orch trace '{\"project\":\"x\",\"action\":\"y\"}'"""
    try:
        event = json.loads(event_json)
    except json.JSONDecodeError:
        click.echo("ERROR: invalid JSON"); sys.exit(1)
    ch_trace(event)
    click.echo(f"Traced: {event.get('action','?')}")


# ── auto-trace helper ─────────────────────────────────────────────────────────

def _auto_trace(project, action, detail, ok=True, **kw):
    ch_trace({
        "project": project, "actor": "agent", "action": action,
        "detail": detail, "ok": 1 if ok else 0, **kw,
    })


if __name__ == "__main__":
    cli()
