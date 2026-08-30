# Agency OS — Current Roadmap

Mission: operate a truthful, service-based development, design, marketing,
SEO/AEO, and content agency from one VPS. Deterministic code owns evidence and
execution; models propose bounded artifacts; humans approve material actions.

State verified: 2026-08-30. Read `CEO_DIRECTIVE.md` first and the latest audit
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
  Local environment files are authoritative and Agency OS has no password-manager
  dependency. Routine rotation is retired; alert only on weak, placeholder-like,
  unhealthy, or known-compromised credentials.
- Operator routing is impact-based. Sol/xhigh handles routine status, navigation,
  non-impactful reconnaissance, and bounded low-risk work directly. Bounded Luna
  subagents support consequential engagement, production, core, security, and
  material decision work. Automatic tracing is limited to compaction, actual
  subagent lifecycle, and session errors; curated traces retain material
  decisions/results/alerts without recording every prompt or tool call. Job 15
  compacts retained lifecycle noise and job 16 retries deduplicated urgent Discord
  delivery; Dashboard Alerts remains the single human source of truth.
- Deployden is core and active. Technoflavour is a live no-code/no-access engagement.
  Hearth and Streamwise are recoverable soft parks. Aetheria and the old jobs SaaS
  are hard parked. The human supplied the Weft PRD on 2026-08-29, selected the name
  TrueApply, and authorized it as an isolated, fully scaffolded in-house engagement.
  The retired jobs stack is not revived or imported by that authorization.
- OpenCode web remains core for mobile/web agent access. Codex is the normal coding
  harness; DeepSeek V4 Flash/Pro handle raw completions; OpenCode/OpenAI OAuth is the
  last subscription fallback. The human confirmed on 2026-08-26 that OpenCode Zen
  remains required as free-capacity fallback; a new Zen key passed an explicit
  free-model probe on 2026-08-28.
- A checksummed daily core recovery bundle exists. The weekly laptop acknowledgement
  is current through 2026-08-29. The fixed-target `backup-core` helper is installed,
  the old wildcard sudo permission is removed, and the latest bundle verifies
  root-only system state.
- Dashboard Resources and the daily Discord digest now expose host maintenance.
  Nine packages were upgraded on 2026-08-28. APT now reports zero actionable
  updates, two policy-deferred candidates, and no reboot requirement.
- The reviewed `scripts/maintenance.py` controller consolidates status, queue and
  backup gates, quiesce/resume, least-privilege environment synchronization, and
  compromised-only internal credential replacement. The controller has completed
  a live credential replacement and post-rotation verification.
- Dashboard Alerts at `:5001/alerts` is the human chore inbox: it shows the latest
  backup/SCP/SHA evidence, weekly laptop acknowledgement, name-only credential
  weakness/provider-health evidence, exact package commands, and silent
  deterministic rechecks.
  Discord digests deep-link there. Operations approvals are core/system-only;
  engagement/content decisions stay in their own workflow.

## Stabilization completed on 2026-08-22

- [x] Removed autonomous deploy/review/merge loops and restart-driven task orphaning.
- [x] Centralized core credentials and added name-only weakness/provider-health
      auditing.
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
- [x] Added the Alerts control plane and Tools registry; production recheck task 298
      and backup verification task 299 completed with zero model tokens.

## Next focus — real first-party SEO on Deployden

Deployden task 316 and audit 33 completed the first production measurement on
2026-08-26: five canonical pages, zero broken links, zero deterministic findings,
mobile PageSpeed 100 with 1.01 s LCP, and available zero-traffic GSC/GA4 evidence.
The source-backed pre-change baseline had one page, no canonical/schema/sitemap,
mobile PageSpeed 80, and 4.07 s LCP. The sitemap was submitted to the verified GSC
domain property at 2026-08-26 18:06 UTC and is pending Google's processing.

1. **Done for the first Deployden run.** Add a polite deterministic multi-page crawl: status, redirects, canonicals,
   titles/meta, headings, schema, broken links, indexability, and sitemap coverage.
2. **Done for the first Deployden run.** Add PageSpeed/Core Web Vitals and render evidence on the brand report.
3. **Done for the first Deployden run.** Connect Deployden GSC and GA4 once the human grants property access; collect
   queries, impressions, clicks, CTR, position, landing pages, and conversions.
4. Turn the next real verified defect or content gap into a linked suggestion and
   measured task. Deterministic linkage is tested, but the post-deploy run was clean,
   so no synthetic defect was introduced merely to manufacture production evidence.
5. Exercise research → outline choice → draft choice → images → approval on Deployden,
   then prove publish plus rollback on a real destination.

## Authorized product engagement: TrueApply

TrueApply is the former Weft concept with a supplied PRD and explicit human build
authority as of 2026-08-29. Its first proof is engine-first: sanctioned public job
feed ingestion and search, durable background work, canonical PDF/DOCX resume
parsing, deterministic sibling rendering with round-trip validation, grounded
draft-only resume and cover-letter tailoring, and visible provenance. Application
submission, email/connection sending, logged-in scraping, server-side portal
credentials, and silent outbound automation are prohibited.

TrueApply owns its repository, Postgres database, object storage, credentials,
containers, and lifecycle under `/home/agency/engagements/trueapply`. It must remain
parkable and may not become a dependency of core Agency OS. Its detailed phase gates
live in the engagement roadmap, while this core roadmap records only authorization,
ledger visibility, and isolation.

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

- [x] The latest core backup was server-verified on 2026-08-26, and the laptop
      acknowledgement is current through 2026-08-29.
- [x] OpenCode Zen was re-authenticated and passed an explicit free-model probe on
      2026-08-28; it remains the approved free-capacity fallback.
- [x] Install the reviewed fixed-target helper and sudo allowlist, remove the old
      wildcard permission, and prove a fresh recovery bundle with `root_state=true`.
- [x] Apply all actionable host package updates. Two candidates remain deferred by
      APT policy, and the host does not currently require a reboot.
- [x] Run the compromised-only internal credential replacement once for the
      PostgreSQL/ClickHouse/MinIO variables exposed to diagnostic tool context.
- [ ] Repair and verify the stale `systemd-networkd-wait-online.service` failure
      without weakening live DNS or boot ordering.
- [x] Grant and verify Deployden GSC/GA4 property access.
- [ ] Provide a real CMS destination when publication testing is authorized.
- [x] Provide the TrueApply/Weft PRD. Received and authorized on 2026-08-29;
      Jobright remains competitor evidence rather than implementation authority.

## Non-goals until the core path is repeatable

No untracked revival of the retired jobs stack, Agency-core billing/RBAC expansion,
Grafana, autonomous self-fixing, mass campaign execution, or project revival merely
to expand the surface area. TrueApply follows its separately authorized PRD and
engine-first gates.
