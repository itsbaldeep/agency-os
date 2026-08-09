#!/usr/bin/env python3
"""
agency_bot.py — Discord steering bot for Agency OS.

Two-way bridge: connects OUTBOUND to Discord's gateway (works from behind
the tailnet, zero exposed ports) and reads/writes the same Postgres tables
the worker and approval-executor already poll.

Commands (in the configured channel only):
  !task <spec>              queue a task with the default type
  !task <type>: <spec>      queue a task with an explicit type
  !queue                    show queued/running tasks
  !status                   24h summary: tasks by status, spend
  !approvals                list pending approvals
  !approve <id>             mark an approval approved (executor applies it)
  !reject <id> [reason]     mark an approval rejected
  !fail <task_id>           show the error text of a failed task

Push notifications (no polling by you):
  - posts when a task finishes (with cost) or fails (with error)
  - posts when a new approval appears, with its id ready for !approve

Env (see /etc/agency/bot.env):
  DISCORD_TOKEN, DISCORD_CHANNEL_ID, OWNER_ID
  PGHOST, PGUSER, PGPASSWORD, PGDATABASE
  DEFAULT_TASK_TYPE      (must be a type worker.py dispatches on)
  APPROVAL_APPROVED_STATUS / APPROVAL_REJECTED_STATUS
                         (must match what approval-executor.sh looks for;
                          defaults: approved / rejected)
"""
import os
import re
import subprocess

import asyncio
import datetime as dt

import discord
from discord.ext import commands
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
ASSISTANT_CHANNEL_ID = int(os.environ.get("ASSISTANT_CHANNEL_ID", "0"))
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
DEFAULT_TYPE = os.environ.get("DEFAULT_TASK_TYPE", "generate_draft")
ST_APPROVED = os.environ.get("APPROVAL_APPROVED_STATUS", "approved")
ST_REJECTED = os.environ.get("APPROVAL_REJECTED_STATUS", "rejected")
DONE_STATES = ("completed", "done", "success")
FAIL_STATES = ("failed", "error")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://100.64.0.1:5001")


def q(sql, args=(), fetch=True):
    """One short-lived connection per query: simple and stale-proof."""
    with psycopg2.connect(
        host=os.environ.get("PGHOST", "100.64.0.1"),
        user=os.environ.get("PGUSER", "agency"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "agencyos"),
        connect_timeout=10,
    ) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, args)
            return cur.fetchall() if fetch else cur.rowcount


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# high-water marks for the push loop
_known_approvals: set = set()
_primed = False


def guard(ctx) -> bool:
    if ctx.channel.id != CHANNEL_ID:
        return False
    if OWNER_ID and ctx.author.id != OWNER_ID:
        return False
    return True


def run_gh(args):
    """Execute a gh REST command; return None on success, else stderr."""
    try:
        p = subprocess.run(["gh", "api", *args],
                           capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return "timed out after 15s"
    if p.returncode == 0:
        return None
    return p.stderr.strip()


@bot.command(name="hold")
async def hold_cmd(ctx, pr_number: int, repo: str = "agency-os"):
    if not guard(ctx):
        return
    err = run_gh(["-X", "POST",
                  f"repos/itsbaldeep/{repo}/issues/{pr_number}/labels",
                  "-f", "labels[]=hold"])
    await ctx.reply(f"⏸️ hold on {repo}#{pr_number}" if not err else f"❌ {err}")


@bot.command(name="unhold")
async def unhold_cmd(ctx, pr_number: int, repo: str = "agency-os"):
    if not guard(ctx):
        return
    err = run_gh(["-X", "DELETE",
                  f"repos/itsbaldeep/{repo}/issues/{pr_number}/labels/hold"])
    await ctx.reply(f"▶️ released {repo}#{pr_number}" if not err else f"❌ {err}")


@bot.command(name="task")
async def task_cmd(ctx, *, spec: str):
    if not guard(ctx):
        return
    ttype = DEFAULT_TYPE
    first, _, rest = spec.partition(" ")
    if first.endswith(":") and len(first) > 1:
        ttype, spec = first[:-1], rest.strip()
    rows = q(
        """INSERT INTO tasks (type, status, params, triggered_by)
           VALUES (%s, 'queued', %s, 'discord') RETURNING id""",
        (ttype, Json({"spec": spec, "source": "discord",
                      "requested_by": str(ctx.author)})),
    )
    await ctx.reply(f"🧾 queued **task {rows[0]['id']}** (`{ttype}`)\n> {spec[:180]}"
                    f"\n🔎 {DASHBOARD_URL}/tasks/{rows[0]['id']}")


@bot.command(name="queue")
async def queue_cmd(ctx):
    if not guard(ctx):
        return
    rows = q("""SELECT id, type, status,
                       COALESCE(params->>'spec','') AS spec, created_at
                FROM tasks WHERE status IN ('queued','running')
                ORDER BY id LIMIT 15""")
    if not rows:
        await ctx.reply("📭 queue is empty — feed me with `!task <spec>`")
        return
    lines = [f"`{r['id']}` **{r['status']}** {r['type']} — {r['spec'][:70]}"
             for r in rows]
    await ctx.reply("**Queue**\n" + "\n".join(lines))


@bot.command(name="status")
async def status_cmd(ctx):
    if not guard(ctx):
        return
    rows = q("""SELECT status, count(*) AS n, COALESCE(sum(cost),0) AS cost
                FROM tasks WHERE created_at > now() - interval '24 hours'
                GROUP BY status ORDER BY n DESC""")
    pend = q("SELECT count(*) AS n FROM approvals WHERE status = 'pending'")
    total_cost = sum(float(r["cost"]) for r in rows)
    lines = [f"**{r['status']}**: {r['n']}" for r in rows] or ["no tasks in 24h"]
    lines.append(f"💸 24h spend: ${total_cost:.4f}")
    lines.append(f"📋 approvals pending: {pend[0]['n']}")
    await ctx.reply("**Status (24h)**\n" + "\n".join(lines))


@bot.command(name="approvals")
async def approvals_cmd(ctx):
    if not guard(ctx):
        return
    rows = q("""SELECT * FROM approvals WHERE status = 'pending'
                ORDER BY id DESC LIMIT 10""")
    if not rows:
        await ctx.reply("✅ nothing pending")
        return
    import json as _json
    lines = []
    for r in rows:
        payload = r.get("payload") or {}
        gist = (payload.get("title") or payload.get("summary")
                or payload.get("subdomain") or _json.dumps(payload)[:80])
        age = (dt.datetime.now(dt.timezone.utc) - r["requested_at"]).days
        lines.append(f"`{r['id']}` **{r['type']}** — {str(gist)[:80]} ({age}d old)")
    await ctx.reply("**Pending approvals** — `!approve <id>` / `!reject <id>`\n"
                    + "\n".join(lines))


@bot.command(name="approve")
async def approve_cmd(ctx, approval_id: int):
    if not guard(ctx):
        return
    n = q("""UPDATE approvals SET status=%s, decided_at=now()
             WHERE id=%s AND status='pending'""",
          (ST_APPROVED, approval_id), fetch=False)
    await ctx.reply(f"✅ approval {approval_id} → {ST_APPROVED} "
                    f"(executor applies within 60s)" if n else
                    f"⚠️ approval {approval_id} not found or not pending")


@bot.command(name="reject")
async def reject_cmd(ctx, approval_id: int, *, reason: str = ""):
    if not guard(ctx):
        return
    n = q("""UPDATE approvals SET status=%s, decided_at=now(), note=%s
             WHERE id=%s AND status='pending'""",
          (ST_REJECTED, reason or None, approval_id), fetch=False)
    msg = f"🛑 approval {approval_id} → {ST_REJECTED}"
    if reason:
        msg += f" — {reason}"
    await ctx.reply(msg if n else f"⚠️ approval {approval_id} not found or not pending")


@bot.command(name="fail")
async def fail_cmd(ctx, task_id: int):
    if not guard(ctx):
        return
    rows = q("SELECT id, type, status, error FROM tasks WHERE id=%s", (task_id,))
    if not rows:
        await ctx.reply("not found")
        return
    r = rows[0]
    await ctx.reply(f"task `{r['id']}` ({r['type']}, {r['status']})\n"
                    f"```{(r['error'] or 'no error recorded')[:1500]}```")



@bot.command(name="fix")
async def fix_cmd(ctx, repo: str, *, description: str):
    """!fix <repo>[@base_branch] <description> — dev task via propose_fix.
    Worker will: branch, run OpenCode, commit, push, open a PR."""
    if not guard(ctx):
        return
    base = None
    if "@" in repo:
        repo, base = repo.split("@", 1)
    model = timeout = None
    words = description.split(" ")
    for front in ("model=", "timeout="):
        if words and words[0].startswith(front):
            val, words = words[0][len(front):], words[1:]
            if front == "model=":
                model = val
            else:
                timeout = int(val)
    description = " ".join(words)
    params = {"repo": repo, "description": description,
              "source": "discord", "requested_by": str(ctx.author)}
    if base:
        params["base"] = base
    if model:
        params["model"] = model
    if timeout:
        params["timeout"] = timeout
    rows = q(
        """INSERT INTO tasks (type, status, params, triggered_by)
           VALUES ('propose_fix', 'queued', %s, 'discord') RETURNING id""",
        (Json(params),),
    )
    base_txt = f" (base `{base}`)" if base else ""
    await ctx.reply(f"🔧 queued **fix task {rows[0]['id']}** on `{repo}`"
                    f"{base_txt}\n> {description[:180]}\n"
                    f"PR link arrives here when it's done."
                    f"\n🔎 {DASHBOARD_URL}/tasks/{rows[0]['id']}")


@bot.command(name="fixpr")
async def fixpr_cmd(ctx, *, arg: str):
    """!fixpr <github-pr-url> <description> — fix task on an existing PR
    (prefixes: model= timeout=)."""
    if not guard(ctx):
        return
    words = arg.split(" ")
    model = timeout = None
    for front in ("model=", "timeout="):
        if words and words[0].startswith(front):
            val, words = words[0][len(front):], words[1:]
            if front == "model=":
                model = val
            else:
                timeout = int(val)
    m = re.match(r"https://github\.com/[^/]+/([^/]+)/pull/([0-9]+)", words[0])
    if not m:
        await ctx.reply("usage: `!fixpr <github-pr-url> <description>` "
                        "(prefixes: model= timeout=)")
        return
    repo, pr_number = m.group(1), int(m.group(2))
    description = " ".join(words[1:])
    if not description:
        await ctx.reply("usage: `!fixpr <github-pr-url> <description>`")
        return
    params = {"repo": repo, "pr_number": pr_number, "description": description,
              "source": "discord", "requested_by": str(ctx.author)}
    if model:
        params["model"] = model
    if timeout:
        params["timeout"] = timeout
    rows = q(
        """INSERT INTO tasks (type, status, params, triggered_by)
           VALUES ('propose_fix', 'queued', %s, 'discord') RETURNING id""",
        (Json(params),),
    )
    await ctx.reply(f"🔧 queued fix task {rows[0]['id']} onto PR #{pr_number} "
                    f"of `{repo}`\n> {description[:180]}\n"
                    f"\n🔎 {DASHBOARD_URL}/tasks/{rows[0]['id']}")


@bot.command(name="run")
async def run_cmd(ctx, repo: str, *, prompt: str):
    """!run <repo> <prompt> — ask opencode to do something in a checked-out repo.
    No git ops: worker runs opencode headlessly and returns the raw output."""
    if not guard(ctx):
        return
    words = prompt.split(" ")
    model = timeout = None
    for front in ("model=", "timeout="):
        if words and words[0].startswith(front):
            val, words = words[0][len(front):], words[1:]
            if front == "model=":
                model = val
            else:
                timeout = int(val)
    prompt = " ".join(words)
    params = {"repo": repo, "prompt": prompt, "source": "discord",
              "requested_by": str(ctx.author)}
    if model:
        params["model"] = model
    if timeout:
        params["timeout"] = timeout
    rows = q(
        """INSERT INTO tasks (type, status, params, triggered_by)
           VALUES ('agent_task', 'queued', %s, 'discord') RETURNING id""",
        (Json(params),),
    )
    await ctx.reply(f"🤖 queued **agent task {rows[0]['id']}** on `{repo}`\n> {prompt[:180]}"
                    f"\n🔎 {DASHBOARD_URL}/tasks/{rows[0]['id']}")


@bot.command(name="ask")
async def ask_cmd(ctx, *, question: str):
    """!ask <question> — answer a question with opencode (prefixes: model= timeout=)."""
    if not guard(ctx):
        return
    words = question.split(" ")
    model = timeout = None
    for front in ("model=", "timeout="):
        if words and words[0].startswith(front):
            val, words = words[0][len(front):], words[1:]
            if front == "model=":
                model = val
            else:
                timeout = int(val)
    question = " ".join(words)
    params = {"question": question, "source": "discord",
              "requested_by": str(ctx.author)}
    if model:
        params["model"] = model
    if timeout:
        params["timeout"] = timeout
    rows = q(
        """INSERT INTO tasks (type, status, params, triggered_by)
           VALUES ('ask', 'queued', %s, 'discord') RETURNING id""",
        (Json(params),),
    )
    await ctx.reply(f"🧠 thinking about it — task {rows[0]['id']}"
                    f"\n🔎 {DASHBOARD_URL}/tasks/{rows[0]['id']}")


@bot.command(name="draft")
async def draft_cmd(ctx, *, spec: str):
    """!draft <project name> keyword=<kw> [words=<min>-<max>] <brief> — queue a blog draft."""
    if not guard(ctx):
        return
    import re as _re
    model = None
    mdl = _re.search(r"\s+model=(\S+)", spec)
    if mdl:
        model = mdl.group(1)
        spec = spec[:mdl.start()] + spec[mdl.end():]
    m = _re.search(r"\s+keyword=", spec)
    if not m:
        await ctx.reply("Usage: `!draft <project name> keyword=<kw> "
                        "[words=<min>-<max>] <brief>`")
        return
    project = spec[:m.start()].strip()
    rest = spec[m.end():]
    wm = _re.search(r"\s+words=", rest)
    kw = rest[:wm.start()].strip() if wm else rest.strip()
    wmin = wmax = None
    brief = ""
    if wm:
        tail = rest[wm.end():].strip()
        tok, _, brief = tail.partition(" ")
        lo, _, hi = tok.partition("-")
        if lo.isdigit() and hi.isdigit():
            wmin, wmax = int(lo), int(hi)
    rows = q("""SELECT id, name FROM projects
                WHERE name ILIKE %s OR repo_name ILIKE %s""", (project, project))
    if not rows:
        names = [r["name"] for r in q("SELECT name FROM projects ORDER BY name")]
        await ctx.reply(f"❌ project **{project}** not found.\n"
                        f"Available: {', '.join(names)}")
        return
    project_id, name = rows[0]["id"], rows[0]["name"]
    brand = q("SELECT id FROM brands WHERE project_id = %s", (project_id,))
    if not brand:
        brand = q("""INSERT INTO brands (name, project_id) VALUES (%s, %s) RETURNING id""",
                  (name, project_id))
    brand_id = brand[0]["id"]
    params = {"content_type": "blog_post", "brand_id": brand_id,
              "suggestion": brief, "suggestion_title": brief[:80],
              "target_keyword": kw or "", "word_count_min": wmin or 700,
              "word_count_max": wmax or 1600, "source": "discord"}
    if model:
        params["model"] = model
    rows = q(
        """INSERT INTO tasks (type, status, params, triggered_by)
           VALUES ('generate_draft', 'queued', %s, 'discord') RETURNING id""",
        (Json(params),),
    )
    await ctx.reply(f"✍️ drafting — task {rows[0]['id']}"
                    f"\n🔎 {DASHBOARD_URL}/tasks/{rows[0]['id']}")


@bot.command(name="audit")
async def audit_cmd(ctx, project: str, url: str = None):
    """!audit <project name or repo_name> [url] — queue a defend_audit task."""
    if not guard(ctx):
        return
    rows = q("SELECT id, name, repo_url FROM projects "
             "WHERE name ILIKE %s OR repo_name ILIKE %s", (project, project))
    if not rows:
        names = [r["name"] for r in q("SELECT name FROM projects ORDER BY name")]
        await ctx.reply(f"❌ project **{project}** not found.\n"
                        f"Available: {', '.join(names)}")
        return
    row = rows[0]
    if url and url.startswith("http"):
        target = url
    elif row["repo_url"] and row["repo_url"].startswith("http"):
        target = row["repo_url"]
    else:
        await ctx.reply(f"⚠️ no url on project **{row['name']}** — "
                        f"pass one: `!audit {project} <https://...>`")
        return
    params = {"project_id": row["id"], "url": target,
              "source": "discord", "requested_by": str(ctx.author)}
    inserted = q(
        """INSERT INTO tasks (type, status, params, triggered_by)
           VALUES ('defend_audit', 'queued', %s, 'discord') RETURNING id""",
        (Json(params),),
    )
    await ctx.reply(f"🛡️ auditing **{row['name']}** — task {inserted[0]['id']}"
                    f"\n🔎 {DASHBOARD_URL}/tasks/{inserted[0]['id']}")


@bot.command(name="help")
async def help_cmd(ctx):
    if not guard(ctx):
        return
    await ctx.reply(
        "`!fix <repo>[@base] <description>` — dev task → PR (prefixes: model= timeout=)\n"
        "`!fixpr <pr-url> <description>` — fix an existing PR (prefixes: model= timeout=)\n"
        "`!run <repo> <prompt>` — run opencode in a repo (no git ops; prefixes: model= timeout=)\n"
        "`!ask <question>` — answer a question (prefixes: model= timeout=)\n"
        "`!task <spec>` · `!task <type>: <spec>` · `!queue` · `!status`\n"
        "`!approvals` · `!approve <id>` · `!reject <id> [reason]` · `!fail <id>` · "
        "`!draft <project name> keyword=<kw> [words=<min>-<max>] [model=<m>] <brief>`\n"
        "`!audit <project name or repo_name> [url]` — queue a defend_audit\n"
        "`!hold <pr> [repo]` · `!unhold <pr> [repo]` — toggle auto-merge block (default repo: agency-os)"
    )


@bot.event
async def on_message(message):
    print(f"on_message fired: chan={message.channel.id} len={len(message.content)}", flush=True)
    if (not message.author.bot
            and ASSISTANT_CHANNEL_ID
            and message.channel.id == ASSISTANT_CHANNEL_ID
            and message.author.id == OWNER_ID
            and not message.content.startswith("!")):
        content = message.content.strip()
        if content:
            q("INSERT INTO assistant_messages (role, content) "
              "VALUES ('user', %s)", (content,))
            q("""INSERT INTO tasks (type, status, params, triggered_by)
                 VALUES ('assistant_turn', 'queued', %s, 'assistant')""",
              (Json({"message": content}),))
            await message.add_reaction("\U0001F914")
    await bot.process_commands(message)


async def push_loop():
    """Real-time events: finished/failed tasks and new approvals."""
    global _primed
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    assistant = bot.get_channel(ASSISTANT_CHANNEL_ID) if ASSISTANT_CHANNEL_ID else None
    while not bot.is_closed():
        try:
            if not _primed:  # don't replay history on startup
                for r in q("SELECT id FROM approvals WHERE status='pending'"):
                    _known_approvals.add(r["id"])
                _primed = True

            rows = q("""SELECT id, type, status, cost, error, result_ref,
                                COALESCE(params->>'question', params->>'prompt', params->>'spec', params->>'description', '') AS spec
                        FROM tasks
                        WHERE finished_at IS NOT NULL AND announced_at IS NULL
                          AND finished_at > now() - interval '24 hours'
                        ORDER BY finished_at""")
            for r in rows:
                if r["status"] not in DONE_STATES + FAIL_STATES:
                    continue
                if assistant and r["type"] == "assistant_turn":
                    if r["status"] in DONE_STATES:
                        answer = r["result_ref"] or ""
                        for i in range(0, len(answer), 1900):
                            await assistant.send(answer[i:i + 1900])
                    else:
                        await assistant.send(
                            f"❌ **task {r['id']}** FAILED — "
                            f"{r['spec'][:100]}\n"
                            f"```{(r['error'] or '')[:400]}```"
                            f"\n🔎 {DASHBOARD_URL}/tasks/{r['id']}")
                elif r["status"] in DONE_STATES and r["type"] == "ask":
                    answer = r["result_ref"] or "no answer"
                    if len(answer) > 9500:
                        import io as _io
                        await channel.send(
                            file=discord.File(_io.BytesIO(answer.encode()),
                                             filename=f"ask-{r['id']}.md"))
                    else:
                        for i in range(0, min(len(answer), 9500), 1900):
                            await channel.send(answer[i:i + 1900])
                elif r["status"] in DONE_STATES:
                    import re as _re
                    m = _re.search(r"https://github\.com/\S+/pull/\d+", r.get("result_ref") or "")
                    pr = f"\n🔗 {m.group(0)}" if m else ""
                    ref = f"\n```{r['result_ref'][:900]}```" if r['type'] == 'agent_task' and r['result_ref'] else ""
                    await channel.send(
                        f"✅ **task {r['id']}** done (${float(r['cost'] or 0):.4f}) "
                        f"— {r['spec'][:120]}{pr}{ref}"
                        f"\n🔎 {DASHBOARD_URL}/tasks/{r['id']}")
                elif r["status"] in FAIL_STATES:
                    await channel.send(
                        f"❌ **task {r['id']}** FAILED — {r['spec'][:100]}\n"
                        f"```{(r['error'] or '')[:400]}```"
                        f"\n🔎 {DASHBOARD_URL}/tasks/{r['id']}")
                q("UPDATE tasks SET announced_at=now() WHERE id=%s",
                  (r["id"],), fetch=False)

            for r in q("SELECT id FROM approvals WHERE status='pending'"):
                if r["id"] not in _known_approvals:
                    _known_approvals.add(r["id"])
                    await channel.send(
                        f"📋 new approval `{r['id']}` waiting — "
                        f"`!approvals` to view, `!approve {r['id']}` to ship")
        except Exception as e:
            print(f"[push_loop] {e}", flush=True)
        await asyncio.sleep(45)


@bot.event
async def on_ready():
    print(f"logged in as {bot.user}", flush=True)


async def main():
    async with bot:
        bot.loop.create_task(push_loop())
        await bot.start(os.environ["DISCORD_TOKEN"])


if __name__ == "__main__":
    asyncio.run(main())
