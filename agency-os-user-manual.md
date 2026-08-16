# Agency OS — User Manual
*deployden.tech · Baldeep Singh*

> **SUPERSEDED (2026-08-16).** This manual describes the legacy software-agency
> flow (scaffold client POCs → preview → public deploy). That flow still works
> but is parked. The **current mission** is an AI digital-marketing agency for
> black-box brands. Read `CEO_DIRECTIVE.md` (strategy) and `ROADMAP.md`
> (state + open items) first. The rest of this file is kept for infra
> reference (access, ports, DNS, deploy mechanics).

---

## What you built (plain English)

You have a self-hosted AI software agency running on a single server in the cloud. Here's what that means in practice:

- **From your phone or laptop**, you open a browser, connect to your private VPN, and talk to an AI engineer (OpenCode) that lives on your server.
- You describe what you want to build. The AI plans it, writes the code, scaffolds the GitHub repo, runs the app, and gives you a private preview link — all without touching the public internet.
- When you're happy with the preview, you click **Approve** in a dashboard on the same VPN. Within 60 seconds the app is live at `https://<appname>.apps.deployden.tech` with a real SSL certificate.
- A second browser tab shows you a dashboard: every project, its health, pending approvals, and how much you've spent on AI tokens.
- Nothing ever goes public without your explicit approval. The AI cannot publish, post, or deploy without you.

**The two tools you use every day:**
- `http://100.64.0.1:4096` — OpenCode (your AI engineer, chat interface)
- `http://100.64.0.1:5001` — Dashboard (approvals, project status, spend, health)

Both are only reachable when Tailscale is connected on your device.

---

## The golden rules (memorise these)

| Rule | What it means |
|---|---|
| **PRD first** | Never ask the agent to "just build X." Always agree on what you're building first. |
| **Preview before public** | Every app runs privately on the VPN before it ever touches the internet. |
| **You approve, it executes** | DNS, deploy, AI content — nothing public happens without your click. |
| **One project per window** | Each OpenCode session should be scoped to one project (see Window Management below). |
| **"What's next?"** | Ask this when you return to a session — the agent reads the ledger and tells you where things stand. |

---

## How to access OpenCode

1. On your device, ensure **Tailscale is connected** (toggle on in the app).
2. Open a browser and go to `http://100.64.0.1:4096`.
3. Login: username `agency`, password (the one you set in the service file).
4. You're now talking directly to the AI engineer running on your server.

---

## Window (session) management

This is important. OpenCode sessions are like browser tabs — each one has its own context window. Here's the pattern that works:

### The root window (always keep one open)
- Open a session rooted at `~/projects` (the default).
- Use this for: cross-project questions, infrastructure checks, "what's the status of everything?", adding new projects to the ledger, general orchestration prompts.
- Start every root session with: `Read AGENTS.md and SETUP-CONTEXT.md, then tell me the current state of all projects.`

### Per-project windows (one per active project)
- Open a **new session** for each project you're actively working on.
- Navigate the session to that project's folder (tell the agent: `cd ~/projects/<name>` or just say "we're working on project X").
- The agent reads that project's own `AGENTS.md` and `PRD.md` for scoped context.
- Keep this session open while you're building that project. Return to it to check progress, give feedback, or approve things.
- When the project is handed off (client accepts the POC), close that session.

### Rule of thumb
```
Root window      → infrastructure, ledger, "what's next across all projects"
Project window   → building, debugging, deploying a specific project
New project      → always start in the root window (register it), then open a project window
```

### Don't do this
- Don't ask about project A in a session that's been building project B — the context gets muddled.
- Don't start building without a PRD in the session — the agent will drift.
- Don't keep a session open for weeks — start fresh sessions and let the agent reload from the ledger and files.

---

## Use Case 1: Taking over an existing GitHub project

You have a repo already on GitHub and want the agent to import it, run it, and deploy it.

**In a root window, start with:**
```
I want to import an existing GitHub project.
Repo: https://github.com/itsbaldeep/<reponame>
Project name: <name>
Here is a brief description: <2-3 sentences about what it does>

Read the repo, understand its structure, create a PRD based on what exists,
register it in the ledger, and tell me what you find before doing anything else.
```

**What the agent will do:**
1. Clone the repo into `~/projects/<name>/`
2. Read the code and write a `PRD.md` based on what it finds
3. Register the project in Postgres via `orch project new`
4. Report back: stack, services needed, dependencies, anything missing

**You then:**
- Review the PRD — correct anything wrong
- Say: `PRD looks good, proceed to containerise and run a VPN preview`

**The agent will:**
1. Write/fix `Dockerfile(s)` if missing
2. Build the image and run the container on a VPN-only port
3. Give you a preview URL: `http://100.64.0.1:<port>`
4. Stage a deploy + DNS approval when you're ready to go public

**When you're happy with the preview:**
- Go to `http://100.64.0.1:5001` → Approvals → Approve both the DNS and Deploy items
- Within 60 seconds: `https://<name>.apps.deployden.tech` is live with a real cert

---

## Use Case 2: PRD ready, no GitHub repo yet

You have a product spec and want the agent to build it from scratch.

**In a root window:**
```
I want to start a new project from a PRD I have written.
Project name: <name>
Here is the PRD:

<paste your full PRD here>

Read it carefully. Ask me any clarifying questions before you start.
Do not begin building until I confirm the PRD is finalised.
```

**The agent will:**
1. Read your PRD and ask clarifying questions (tech stack preference, auth method, DB schema, etc.)
2. Propose any gaps it spots
3. Wait for your confirmation

**Once you confirm:**
```
PRD is finalised. Proceed:
1. Create the GitHub repo under itsbaldeep/<name>
2. Scaffold the project structure
3. Register in the ledger
4. Begin building — report back when you have a VPN preview ready
```

**The agent will then:**
1. Create the repo on GitHub (using your stored token)
2. Scaffold all services (frontend, API, DB, etc.)
3. Build and containerise
4. Give you a VPN preview URL
5. Iterate with you until you're happy
6. Stage approvals for public release when you say go

**Review cycle:**
- Open the preview URL, test it
- Give feedback in chat: `The login page works but the dashboard throws a 500 on /api/users — fix it`
- The agent fixes, rebuilds, updates the preview
- Repeat until the POC is client-ready

---

## Use Case 3: Monitoring both projects on the dashboard

Once both projects are running, open `http://100.64.0.1:5001`.

**Overview tab:**
- Shows every registered project as a card
- Green dot = service running, red = stopped/unhealthy
- Port, memory usage, last seen timestamp
- Click into a project to see all its services

**Approvals tab:**
- Any pending DNS/deploy/content approvals appear here
- Full payload shown (exact subdomain, port, or content text)
- Approve/Reject buttons update the ledger immediately
- The executor picks up approved items within 60 seconds and makes them live

**Health tab:**
- Recent health check results per service
- Event timeline from ClickHouse — every agent action, deploy, and command
- If a container crashes and the agent self-heals, you'll see the incident here

**Spend tab:**
- Total token spend across all projects
- Broken down by project and by model
- Use this to watch your OpenRouter credit usage against your cap

**To check on a specific project from OpenCode:**
```
What is the current status of project <name>?
Show me recent activity and any issues.
```

---

## Day-to-day workflow

```
Morning / when you sit down:
1. Connect Tailscale
2. Open dashboard (5001) — scan for any pending approvals or health alerts
3. Open root OpenCode window (4096) — type "what's next?"
4. Agent summarises pending approvals, project states, anything that needs attention
5. Approve anything waiting, or open a project window and continue building

Starting a new task:
1. Open a project-specific OpenCode window
2. Say: "Read PRD.md and the current ledger state, then tell me where we left off"
3. Give it the next instruction

Approving a public release:
1. Agent tells you it has staged DNS + deploy approvals
2. Open dashboard → Approvals tab → review the payload → Approve
3. Wait 60 seconds → open https://<app>.apps.deployden.tech → verify it's live
4. Tell the agent: "Confirmed live, update state to live"
```

---

## Useful prompts to keep handy

**Load context at the start of any session:**
```
Read AGENTS.md and SETUP-CONTEXT.md. 
Then read ~/projects/<name>/PRD.md and ~/projects/<name>/AGENTS.md.
Tell me the current state before we continue.
```

**Check everything across all projects:**
```
What is the current state of all projects?
Any pending approvals, unhealthy services, or outstanding tasks?
```

**Fix a broken service:**
```
Service <name> in project <project> is showing unhealthy on the dashboard.
Investigate and fix. Follow the self-heal protocol.
Report back before making any Yellow-gate changes.
```

**Hand off a completed POC:**
```
Project <name> has been accepted by the client.
Run the repo-handoff skill: clean the repo, write deploy-handoff.md,
ensure no POC secrets or test data are in the codebase, 
and give me the GitHub repo link to hand to the client.
```

**Stage a public release:**
```
The preview of <name> at http://100.64.0.1:<port> looks good.
Stage it for public release at <appname>.apps.deployden.tech.
Create the DNS and deploy approval requests and wait.
```

**Check spend:**
```
How much have I spent on AI tokens today / this week / on project <name>?
```

---

## What's possible from here (the road ahead)

### Near-term (Phase 2 — more autonomy)
- **Scheduled agent runs:** the agent wakes up, checks health, runs routine maintenance, and reports — without you prompting it. Built on top of the existing cron layer.
- **Auto-retry deploys:** currently the agent self-heals within a session; Phase 2 makes this durable across sessions via the job queue.
- **More skills:** database migration skill, performance-testing skill, SEO audit skill for marketing sites, blog-post drafting and content-review flow.

### Medium-term (Phase 3 — scale out)
- **Multiple VPS / per-client isolation:** each client's POC runs on its own server. The control plane (Postgres, ClickHouse, dashboard) stays on the current box; workloads move out.
- **Cloudflare DNS:** move `deployden.tech` to Cloudflare, get a real DNS API, enable per-subdomain records and DNSSEC. Removes the wildcard limitation.
- **Real secrets manager (Infisical):** currently secrets live in `.env`. Infisical gives you a proper vault with per-project scopes, rotation, and audit logs.
- **Secondary Headscale node:** current Headscale is a single point of failure. A standby node fixes that.

### Longer-term (Phase 4 — agency OS as a product)
- **Multi-human access:** controlled VPN access for a small team. Each person gets their own Headscale node; RBAC at the dashboard level.
- **Client portal:** a separate, simplified view (public or auth-gated) where clients can see their POC's status, request changes, and approve it for production — without VPN access.
- **Autonomous project manager:** the agent drafts sprint plans, tracks its own tasks in the ledger, and works through a backlog between your sessions. You review outcomes, not steps.

---

## Quick reference

| What | Where |
|---|---|
| OpenCode (AI engineer) | http://100.64.0.1:4096 |
| Dashboard | http://100.64.0.1:5001 |
| Public apps | https://<app>.apps.deployden.tech |
| VPS SSH | ssh agency@187.127.182.199 |
| Project files | ~/projects/<name>/ on the VPS |
| Root Bible | ~/projects/AGENTS.md |
| Setup context | ~/projects/SETUP-CONTEXT.md |
| Ledger CLI | orch (anywhere on the VPS) |
| Logs | ~/agency-os/logs/ |
| Backups | ~/agency-os/backups/ (nightly) |
| Env/secrets | ~/agency-os/.env (never share) |

Roadmap-driven autonomous development enabled 2026-08.
