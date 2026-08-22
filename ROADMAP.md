# Agency OS — Current Roadmap

Mission: operate a truthful, service-based development, design, marketing,
SEO/AEO, and content agency from one VPS. Deterministic code owns evidence and
execution; models propose bounded artifacts; humans approve material actions.

State verified: 2026-08-22. Read `CEO_DIRECTIVE.md` first and the latest audit
execution log second.

## Current reality

- Canonical core source is `/home/agency/core/{agency-os,agency-dashboard,deployden}`.
  `/home/agency/agency-os` is runtime-only.
- Core runtime: Postgres, bounded ClickHouse, core MinIO, dashboard `:5001`,
  worker, Discord bot/alerts, Caddy, Headscale, OpenCode web `:4096`, and Deployden.
- ClickHouse retains only actionable `events` and `ai_visibility_checks`; it is
  capped at 0.25 CPU / 512 MiB and is not an analytics product.
- Jobs 8–11 are retired. Job 12 is permanently retired and must not be enabled.
  Core development is manual edit → test → review → commit → deliberate deploy.
- Core credentials live under `/home/agency/.config/agency`; engagement credentials
  stay with their owner. Credential values never enter logs, chat, Git, or traces.
- Deployden is core and active. Technoflavour is a live no-code/no-access engagement.
  Hearth and Streamwise are recoverable soft parks. Aetheria and the old jobs SaaS
  are hard parked. `Weft` is a reserved future product; do not scaffold it without
  the PRD.
- OpenCode web remains core for mobile/web agent access. Codex is the normal coding
  harness; DeepSeek V4 Flash/Pro handle raw completions; OpenCode/OpenAI OAuth is the
  last subscription fallback. The OpenCode Zen credential is currently invalid.
- A checksummed daily core recovery bundle exists. Root-only system state is absent
  until the fixed-target sudo helper grows `backup-core`; the first laptop/off-site
  copy and Saturday acknowledgement are still human actions.
- Dashboard Resources and the daily Discord digest now expose host maintenance.
  Twenty-three package updates and a required kernel reboot remain operator work.

## Stabilization completed on 2026-08-22

- [x] Removed autonomous deploy/review/merge loops and restart-driven task orphaning.
- [x] Centralized core credentials and added name-only rotation auditing.
- [x] Added verified Postgres/ClickHouse/MinIO/config/OpenCode recovery bundles.
- [x] Isolated core object storage; soft parked Hearth/Streamwise; hard parked
      Aetheria and the ambiguous jobs/resume stack.
- [x] Removed Adminer, ClickHouse Play, `/jobs`, and Aetheria dashboard surfaces.
- [x] Made approvals task-linked, resumable, input-aware, and outcome-linked.
- [x] Added explicit WordPress publishing with credential references and no implicit
      publication; other CMS adapters remain planned.
- [x] Replaced ClickHouse/no-op noise with incident, recovery, and failure alerts.
- [x] Removed the dashboard Docker socket and run the dashboard as a non-root user.
- [x] Centralized task usage, actual model labels, cost, and task/job attribution.
- [x] Enforced one current brand-property identity and removed 27 repeat-audit
      duplicates while retaining audit history.
- [x] Restored non-root dashboard access to the secret-free host snapshot and made
      package/reboot debt visible in Resources and Discord.
- [x] Enforced verified source snippets, typed evidence blocks, bounded outlines,
      a 24k compose ceiling, local retries, and durable per-block checkpoints.
- [x] Proved a black-box Jobright baseline: audit task 287 completed 15/15 bounded
      samples; research 288, outline 291, and compose 297 produced draft 20 with
      18 validated blocks and four reverified public sources. Nothing was published.

## Next focus — real first-party SEO on Deployden

1. Add a polite deterministic multi-page crawl: status, redirects, canonicals,
   titles/meta, headings, schema, broken links, indexability, and sitemap coverage.
2. Add PageSpeed/Core Web Vitals and render evidence on the brand report.
3. Connect Deployden GSC and GA4 once the human grants property access; collect
   queries, impressions, clicks, CTR, position, landing pages, and conversions.
4. Turn verified defects and content gaps into linked suggestions and measured tasks.
5. Exercise research → outline choice → draft choice → images → approval on Deployden,
   then prove publish plus rollback on a real destination.

## Content and execution work after that

- [ ] Add multiple outline and draft variants with explicit human selection; the
      current proven path produces one evidence-gated outline and one draft.
- [ ] Prove core-MinIO image sourcing/review on a real draft; never generate assets
      merely by opening a preview page.
- [ ] Prove WordPress publication and rollback with engagement credentials.
- [ ] Add explicit Git/PHP/Java/Next.js publication adapters with preview, tests,
      approval, and rollback evidence.
- [ ] Wire source-specific competitor sitemap/feed adapters and change-only alerts.
- [ ] Add per-engagement soft-park/start controls only after manifests and health
      checks are tested; hard park remains a recovery-first operator action.

## Honest AEO boundary

- Current AI visibility is a DeepSeek training-knowledge proxy, never labeled as
  ChatGPT, Google, Perplexity, Gemini, Copilot, live-web, or first-party analytics.
- Jobright audit 32 baseline: Jobright 1/15, Teal 9/15, LazyApply 5/15, Simplify
  4/15. This is a directional proxy, not market share.
- [ ] Add separately labeled real-engine adapters and word-boundary/entity matching.
- [ ] Add FAQ/schema/`llms.txt` checks and citeable answer extraction.
- [ ] Measure offense against GSC/GA4 outcomes, not model confidence.

## Capability library backlog

- Marketing: GSC, GA4, PageSpeed, crawl, schema, keyword tracking, content decay,
  backlink provider, local SEO, consent-safe email/WhatsApp, and paid ads.
- Delivery: multi-CMS adapters, preview/rollback, visual regression, accessibility,
  security checks, uptime/SLOs, and client-ready reports.
- Every capability needs a registered executor, deterministic acceptance test,
  dashboard evidence, alert path, credential scope, and rollback before “available.”

## Human gates still open

- [ ] Copy the latest core backup to the laptop and mark the Saturday acknowledgement.
- [ ] Human-rotate every unacknowledged core credential; replace invalid OpenCode Zen
      auth if free fallback is still desired.
- [ ] Add fixed-target `backup-core` support to `/usr/local/sbin/codex-system-audit`.
- [ ] Apply the 23 pending host package updates and perform the required controlled
      reboot, then re-verify all core services, routes, firewall, and task state.
- [ ] Grant Deployden GSC/GA4 property access and later a real CMS destination.
- [ ] Provide the Weft PRD when ready; Jobright is the baseline, not a build request.

## Non-goals until the core path is repeatable

No Weft scaffold, multi-tenant SaaS, billing/RBAC, Grafana, autonomous self-fixing,
mass campaign execution, or project revival merely to expand the surface area.
