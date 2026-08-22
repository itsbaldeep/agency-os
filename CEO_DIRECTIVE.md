# Agency OS — CEO Directive (state verified 2026-08-22)

Authority: human co-CEO + AI co-CEO (Codex CLI). This file is the persistent
strategic context — read it on every session start. It supersedes informal
chat decisions. Update it when strategy changes.

---

## 0. What this VPS is (one sentence)

A self-hosted AI digital-marketing agency platform that does **real client
work** for black-box brands — marketing, SEO, AEO, content — with the human
co-CEO steering from the dashboard at :5001 and AI co-CEO executing behind
approval gates.

## 1. The three project types

| Type | Repo access | What we do | Likelihood |
|---|---|---|---|
| **Black-box** | None — public web only | Marketing, SEO, AEO, content, audits, strategy | **Majority of clients. Focus.** |
| **Code-onboarded** | Existing repo + brand | Pending dev, CMS management, push articles/code + all marketing | Less likely early (trust gap) |
| **Fully-scaffolded** | We create everything | Repo, dev, design, marketing, SEO, audit — mostly our own products | Some clients + own products |

All three get the **marketing layer**. Black-box is the wedge and the focus.

## 2. Marketing = defend + attack (the operating model)

**Defend (recon):** audit the brand's current state — sitemap, blog presence,
CMS capabilities, schema, meta, Core Web Vitals, content freshness, technical
SEO issues. Discover what's broken or missing before acting. **Defend audit
lives in `capabilities` table + `defend_audit` task type.**

**Attack (offensive):** competitor gap analysis — what are direct/indirect
competitors doing that the brand isn't? Content gaps, keyword gaps, SERP
feature gaps, AI-visibility gaps. Turn gaps into prioritized suggestions →
content briefs → drafts → publish. **Attack lives in `run_brand_audit` +
`competitor_scan` + `suggestions` + content pipeline.**

The loop: **defend → attack → prioritize → approve → execute → verify →
report → repeat.** Every step visible on the dashboard.

## 3. Honest assessment — where we actually are (2026-08-22)

### What works (verified live)

- The core control plane is Postgres, bounded ClickHouse, core MinIO, dashboard,
  worker, Discord alerts/bot, Caddy, Headscale, OpenCode web, and Deployden.
  The dashboard runs non-root without the Docker socket.
- Core source is under `/home/agency/core`; `/home/agency/agency-os` is a
  runtime-only deployment tree. Jobs 8–11 are retired and job 12 must never be
  enabled. Core changes now use one deliberate, tested deployment path.
- Approval and suggestion actions create linked tasks, can request additional
  input, record test/outcome state, and link failures back to the initiating row.
  Publication requires an explicit destination and credential reference.
- The black-box report/cockpit is live. Jobright audit task 287 completed 15/15
  bounded visibility samples, stored audit 32, selected reachable direct
  substitutes (Simplify, Teal, LazyApply), created suggestions, and linked exact
  model/tokens/cost to the task. Repeated audits now upsert one current value per
  brand property instead of accumulating duplicate/stale metadata.
- The content draft path is evidence-gated and resumable. Jobright research 288,
  outline 291, and compose 297 created dashboard draft 20 with 18 validated blocks,
  four reverified public evidence snippets/sources, no publish task, and durable
  per-block checkpoints. Preview and task/spend links return HTTP 200.
- Model routing is explicit: Codex uses the ChatGPT subscription for coding;
  DeepSeek V4 Flash handles cheap/classification work and V4 Pro handles evidence
  synthesis/content. Configured free raw providers precede OpenCode fallbacks.
  OpenCode OpenAI OAuth works; the OpenCode Zen API credential currently returns
  401 and remains a visible rotation/availability issue.
- ClickHouse retains only actionable `events` and `ai_visibility_checks`, capped at
  0.25 CPU / 512 MiB. Routine success heartbeats are filtered; failures, changes,
  resolutions, and visibility evidence remain visible.
- Daily checksummed recovery covers Postgres, both retained ClickHouse tables,
  core MinIO, central credentials, configuration, and readable OpenCode state.
  Saturday off-site acknowledgement keeps alerting until the human marks it done.
- The secret-free host snapshot is readable by the non-root dashboard and exposes
  RAM, disk, container use, pending packages, and reboot state. The daily Discord
  digest surfaces task/content failure rates, recovery/credential debt, package
  debt, and required reboot state rather than repeating routine success noise.
- Core and engagement resources are separate. Hearth and Streamwise are soft
  parked; Aetheria and the old jobs/resume stack are hard parked; Deployden is
  non-parkable core; Weft is reserved and not created.

### What's broken or missing (the real gap)

1. **No first-party SEO outcome loop yet.** No Deployden GSC/GA4 property is
   connected, and there is no production multi-page crawl/PageSpeed collector.
2. **AI visibility is still a proxy.** It is DeepSeek training-knowledge sampling,
   not live-web ChatGPT/Perplexity/Gemini/Copilot or first-party search visibility.
3. **The content tournament is incomplete.** One evidence-gated outline and draft
   work; multiple outline/draft variants with human selection are still planned.
4. **Publication breadth is narrow.** WordPress has a tracked adapter but needs a
   live credential/destination proof. Git/PHP/Java/Next.js adapters do not exist.
5. **Recovery has two honest gaps.** The sudo helper lacks fixed-target
   `backup-core` support for root-only state, and the first laptop copy/ack is due.
6. **Fallback is degraded.** OpenCode OpenAI OAuth succeeds, but the desired free
   OpenCode Zen credential is invalid; configured free API providers depend on
   their own present credentials/rate limits.
7. **Soft parks retain rollback weight.** Hearth's stopped containers/layers and a
   root-owned `.next` build remain intentionally preserved until a later cleanup.
8. **Host maintenance is due.** Twenty-three packages are upgradable and the host
   requires a reboot for the installed kernel; Codex lacks passwordless authority
   for package upgrades/reboot, so this remains visible rather than silently run.

### The honest bottom line

Agency OS now has a proven black-box audit and evidence-gated draft baseline, not a
complete marketing agency. The next leap is measured first-party SEO on Deployden:
deterministic crawl + PageSpeed + GSC/GA4, then linked suggestions and verified
execution. Do not expand into Weft or campaign automation before that loop repeats.

## 4. Competitive position (vs SearchAtlas, Synscribe, Alli AI)

| Competitor | Their strength | Their weakness | Our opening |
|---|---|---|---|
| **SearchAtlas** ($99-399) | Full stack: OTTO autonomous SEO/ads/social, white-label, aggressive price, big social proof | Black-box autonomy (trust their AI), no evidence/confidence/risk shown, pricing ladder traps at $399 | Show the reasoning + gates + verification. That's the trust story they lack. |
| **Synscribe** (agency) | Sharp B2B positioning, real case-study numbers, programmatic SEO, published playbooks, agentic discovery (MCP/llms.txt) | People-heavy service, slow (1-wk research), expensive, no self-serve product, no owned dashboard | Give the black-box audit free as a lead magnet, then automate the sprints. |
| **Alli AI** | Crisp "AI sees blank page" framing, live crawler monitor, Fortune-100 report = great content marketing, WP plugin, bulk on-page deploy | Narrow wedge (on-page/technical), rules-based not reasoning, no content/link/PR/ads strategy | Extend to content + AEO + competitors + execution + memory. |

**Our one-line positioning:** *"The AI marketing OS that shows its work —
every recommendation comes with evidence, confidence, risk, and a human
approval gate. You own the data, you own the decision."*

**Defensible wedge for regulated industries (healthcare/finance):** our
compliance checks (superlatives, health claims, review incentives,
marketplace restrictions) are a feature none of them show.

## 5. Grounded roadmap — measured SEO before surface expansion

The detailed, current sequence lives in `ROADMAP.md`; do not duplicate its state
here. The strategic order is fixed:

1. Stabilize and prove the black-box audit/content loop. **Done 2026-08-22** for
   Jobright as an external baseline; no external publication occurred.
2. Use Deployden as the first owned measurement loop: deterministic crawl,
   PageSpeed/Core Web Vitals, then GSC/GA4 after property access is granted.
3. Convert verified evidence into task-linked suggestions, selected content
   variants, reviewed assets, approved publication, and outcome measurement.
4. Add real, separately labeled AEO engines and multi-CMS adapters only after the
   first-party loop repeats reliably.
5. Create Weft only after its PRD. Jobright is the competitor baseline, not an
   instruction to scaffold the product.

Campaign automation, multi-tenant SaaS, billing/RBAC, Grafana, and autonomous
self-fixing remain parked until the core client workflow is dependable.

## 6. What I need from the human co-CEO (checklist)

### Immediate (unblocks Phase 1)
- [ ] Copy the latest verified core backup to the laptop, then run the explicit
      Saturday acknowledgement command. The VPS must continue nagging until done.
- [ ] Human-rotate/acknowledge every unrotated central credential. Replace the
      invalid OpenCode Zen auth only if its free fallback remains desired.
- [ ] Grant Deployden GSC and GA4 property access to the existing service account.
      No connector may pretend a property exists before that grant.
- [ ] Extend the fixed-target sudo audit helper with `backup-core` if root-only
      Headscale/system state should enter the recovery bundle.
- [ ] Schedule the pending package upgrade and host reboot with an operator who has
      the required sudo authority; verify every core service after the reboot.

### When we have a real client engagement
- [ ] **WordPress Application Password** from the client (Phase 3 publisher).
      URL + username + app password. Technoflavour is WP-ready.
- [ ] **3 real competitor names** per client (seed/validate LLM-proposed ones).
- [ ] **Ahrefs API key** (optional, $99+/mo) — real backlinks, KD, content gap.
- [ ] **OpenAI API key** (optional — real ChatGPT visibility, Phase 4).

### Strategic decisions only the human can make
- [ ] **Pricing model** — retainer vs per-project vs free-audit → paid execution?
- [ ] **First real client proof** after Deployden — Technoflavour or a prospect?
- [ ] **Weft PRD** when ready. Until supplied, Weft remains a ledger concept only.

## 7. Operating rules for the AI co-CEO

1. **Challenge everything.** Don't assume code exists = works. Test it.
2. **Push durable state to the map** — CEO_DIRECTIVE.md, ROADMAP.md, the latest
   audit execution log, and AGENTS.md. Do not create one-off Markdown handoffs.
3. **Deploy deliberately** — jobs 8–11 are retired and job 12 stays disabled.
   A worker restart can interrupt work: capture active tasks, batch source changes,
   restart once, verify, and safely resume/requeue only after inspecting side effects.
   Author under `/home/agency/core`; never author in runtime-only
   `/home/agency/agency-os`.
4. **Everything visible on the dashboard** — if it's not on :5001, it doesn't
   exist for the human co-CEO.
5. **Never assume a data source is available** — establish keys, ownership,
   permissions, scope, and a live probe before claiming a capability.
6. **Be honest about gaps** — the user respects honesty over false confidence.
7. **Determinism first, LLM second** — models generate bounded proposals/artifacts;
   code verifies evidence, validates shape, records cost, and executes.
8. **Black-box first** — every marketing feature must work without repo/CMS access.
   Deeper access unlocks more, but the default path is public-web-only.
9. **Keep providers separate** — Codex uses subscription auth; DeepSeek credentials
   are raw-completion credentials and must not leak into Codex/OpenCode OAuth.
   Every fallback transition is attributed and alerts Discord/dashboard.
10. **Respect core/engagement boundaries** — engagements own their data, secrets,
    routes, storage, and containers. A parkable engagement can never become a core
    runtime dependency.

## 8. Retired and parked estate (verified 2026-08-22)

| What | Action | Reversible via |
|---|---|---|
| Aetheria | Recovery bundles verified; live source, routes, containers, volumes, UI, handler, and job 12 removed/retired | Restore only from the recorded recovery bundle as a new isolated engagement |
| Old jobs/resume SaaS | `/jobs` surfaces/handlers removed; isolated tables dumped then dropped | Restore the dump only into future Weft's separate app/database after its PRD |
| Autonomous jobs 8–11 | Cron and DB scheduling retired; no deploy/review/merge loop | Reintroduction is a strategic decision, not routine rollback |
| Hearth | Source/data/context preserved; containers and public routes stopped | Use its recovery refs/manifests for an explicit unpark |
| Streamwise | Source/data/context preserved; no live containers or DNS route | Use its recovery refs/manifests for an explicit unpark |
| Other legacy projects/docs | Recovery snapshot retained; live ledger/source clutter removed | Review the archived bundle, never silently re-import it |
