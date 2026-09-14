# Marketing delivery plan for Agency OS, Dashboard, TrueApply and Deployden

Status: initial implementation slice verified locally, pending controlled database integration and core deployment. Prepared 2026-09-14 UTC.

## Implementation checkpoint, 2026-09-14 UTC

The initial reusable foundation is implemented in canonical source: versioned
assessment persistence, idempotent collection and synthesis, deterministic report
validation, dashboard evidence/action rendering, and behavioral CI gates. TrueApply
now has a public help surface, valid entity/FAQ JSON-LD, sitemap coverage, and a
static SEO contract. Local verification passed for Agency OS (101 tests), Dashboard
(28 tests), and TrueApply web (22 tests plus type checks).

This does not prove a migrated live database, worker/dashboard deployment, live
GSC/GA4 access, ranking, traffic, or commercial outcomes. The next controlled gate
is the migration and dashboard-to-worker integration run. Publication, spend, and
new external channel activity remain separately approved workflows.

## 1. Outcome and authority

Deliver a reusable dashboard workflow that assesses a business, gathers available evidence, discovers and evaluates growth opportunities, explains priorities, produces reviewed content, tracks execution, and measures subsequent results. TrueApply and Deployden are the two launch cases. The human must be able to initiate Deployden's assessment entirely through the dashboard without reconstructing a marketing prompt in an agent session.

This document authorizes no execution by itself. The current user request is planning only. A subsequent instruction to implement this plan authorizes its scoped implementation and verification; publication, spend, external messages and production deployment must follow the existing applicable authority and gates. Prepare concrete previews, changes and test evidence before requesting any missing final authorization. Do not repeatedly ask for routine implementation choices.

The user explicitly wants GPT-5.6 Terra to own subsequent execution and to delegate bounded implementation and verification to GPT-5.6 Luna. This task-specific model choice supersedes the ordinary Sol ownership preference for this handoff. Terra owns architecture, contracts, integration, safety, acceptance and final reporting. Luna workers never deploy, merge, publish, spend, contact people, rotate credentials or delete production data.

Read the VPS AGENTS.md, canonical CEO_DIRECTIVE.md, ROADMAP.md, latest audit log, and project AGENTS.md before execution. Keep jobs 8–12 retired. Author core changes only under `/home/agency/core`; `/home/agency/agency-os` is runtime-only. TrueApply owns its data, credentials, content and deployment. Deployden remains core and non-parkable.

## 2. Starting evidence and corrections

Verified in source during this conversation:

- `scripts/worker.py:2709`, `handle_marketing_audit`, queues defend, brand and SEO tasks and returns. It has no final synthesis or aggregate completion contract.
- `scripts/suggestion-engine.py:151`, `generate_suggestions`, prompts with 300 characters of homepage context and a 1,800-token response cap. The recommendation prompt omits collected crawl, analytics and competitor-page evidence. It requests disconnected suggestion fields rather than an integrated strategy.
- Dashboard `app.py:286` independently selects latest non-SEO and SEO audits. Defend summary is a task result, not part of a durable unified assessment. `templates/brand_report.html` contains suggestion cards and some fixed guidance.
- Core and dashboard CI currently compile Python but do not run their existing behavioral test suites. Closing this gap is launch scope.
- `seo_measurement.py` treats missing JSON-LD on every page as a finding, does not semantically validate schema, and labels Lighthouse lab metrics as Core Web Vitals. Its bounded GSC/GA4 row sums must not be presented as complete property totals.
- TrueApply public site is static under `infra/public-site`; the application is Next.js under `apps/web`. Public sitemap listed homepage and privacy page. Both origins configure GA4 but explicit business-funnel instrumentation was not found.
- TrueApply brand 31 has registered GSC `sc-domain:trueapply.in` and GA4 property `553391253`. Registration is not fresh API access proof. Re-resolve IDs from the ledger; do not hardcode brand 31 in reusable code.
- Existing records classified TrueApply's sales channel as `DTC ecommerce`, showing that inherited categorization is not reliable product context.
- TrueApply has substantial existing uncommitted admin/workspace refactoring. Preserve it. Its older launch audit metrics are dated baseline evidence, not current production performance guarantees.
- Deployden has an existing five-page static site, `server.py`, `/api/lead`, SQLite lead storage, and a Discord notification path. Reuse these; do not replace the service to add marketing pages.
- Previous assessment claims need verification: two sitemap URLs do not prove two indexed URLs; a differently named source social image does not prove the deployed asset is broken; shared GA4 configuration across subdomains does not itself prove attribution fragmentation or require a linker. Verify each before changing it.

Reference artifacts: `.lavish/trueapply-marketing-os-assessment.html`; source diagnosis trace `atr_20260914T054306Z_1a36e5493515`. Keep the accepted Lavish artifact intact. Its information hierarchy is the design reference for the native dashboard, not a correctness oracle.

## 3. Launch scope and completion rules

Deliver in this release:

1. Stored business brief and reusable assessment instructions.
2. Durable orchestration, evidence collection, live research, final synthesis and versioned reports.
3. Native dashboard report with defensive findings, growth opportunities, sequencing, decisions, execution and outcomes.
4. Competitor discovery with evidence, preserved human seeds and explicit coverage limits.
5. Reliable analytics access/status and project-specific conversion definitions.
6. Reviewed static publishing with previews, approval, deployment linkage and rollback for both owned sites.
7. TrueApply public SEO/help/guides and private-app indexing/analytics boundaries.
8. Deployden service-page improvements, editorial content and tested lead measurement.
9. Automated functional, integration, security, browser and failure-recovery tests, plus live acceptance evidence after authorized deployment.

Do not equate a generated report, accepted JSON or HTTP 200 with marketing success. Engineering acceptance is measurable immediately. Indexing, non-branded search traffic, qualified activation and leads require later observation. Ship their collectors, review schedule and dashboard outcome states now; do not promise rankings or fabricate lift.

Include next-channel strategy and execution-readiness assessment in the report now. Actual newsletter sending, paid campaigns, social publishing and a public forum need account/budget/consent or moderation decisions not supplied in this conversation. Do not scaffold empty adapters. Surface a precise missing-input card and executable next task when those inputs are provided. These external dependencies must not block SEO launch.

## 4. Ownership and batching

Use at most three independent Luna assignments at once. Every brief must state objective, owned files, forbidden actions, evidence and acceptance tests. Workers are not alone in the codebase: never revert another worker's or the user's changes. Freeze shared contracts before parallel implementation. Terra exclusively integrates shared dispatcher, migrations and cross-repository changes when ownership overlaps.

| Batch | Deliverable | Owner and parallel work | Depends on |
|---|---|---|---|
| 0 | Current baseline, worktree reconciliation, contract and test harness | Terra; Luna scout verifies deployment/test entrypoints | Nothing |
| 1 | Assessment storage and orchestration | Luna backend worker; Terra owns migration and dispatcher integration | 0 |
| 2 | Collectors, context and competitor research | Separate Luna evidence worker and research worker, with non-overlapping new modules | Contract from 0; integrate with 1 |
| 3 | Synthesis and native dashboard report | Luna synthesis worker and dashboard worker; Terra freezes report payload first | 1–2 contracts |
| 4 | Static content delivery and attribution | Luna publisher worker; Terra integration review | Report/action contract |
| 5 | TrueApply and Deployden launch content and instrumentation | One Luna worker per site; independent verifier on completed changes | 2–4 contracts |
| 6 | Full regression, adversarial cases, release and production evidence | Terra owns release; Luna verifier owns independent acceptance review | 1–5 |
| 7 | Human Deployden dashboard acceptance and outcome monitoring | Human uses dashboard; Terra handles diagnosis and fixes | Authorized production deployment |

Do not deploy once per worker or task. Target one coordinated core/dashboard release after integrated verification and deliberate site deployments against their verified commits. A genuine migration compatibility dependency may require a documented two-step rollout.

## 5. Batch 0: baseline and contract

Resolve branch/commit, dirty files, runtime version and canonical deployment instructions for all four repositories. Inspect TrueApply's current dirty changes with the human's existing work in mind. Create an isolated worktree from an agreed commit if necessary; do not automatically include unrelated refactoring or silently omit dependencies needed by this plan. Record the exact baseline in the execution ledger.

Read the current TrueApply PRD, architecture, product design, latest release notes and launch issue ledger. Reconcile open launch blockers against present source and deployed behavior. Close marketing-critical failures found in the scoped journey; preserve broader product requests in their existing tracked ledger. If current parser/export/tenant tests fail, diagnose them and identify actual launch impact instead of treating older percentages as current results.

Inventory access without printing secrets: GSC, GA4, PageSpeed, public web search/SERP provider, model route, publisher destinations. Distinguish installed/configured, permission-granted, successful probe, and production proof. Interactive harness web search is not automatically available to the scheduled worker. Identify a usable worker-side research adapter or require a named provider input; do not silently substitute model recall.

Freeze these contracts before implementation:

- Assessment identity and source-run linkage.
- Evidence shape and source availability states.
- Report schema, recommendation schema and action lifecycle.
- Project-specific conversion configuration.
- Publication artifact and approval fingerprint.

Prefer additive Postgres changes and plain Python modules with existing dependencies. Reuse `tasks`, `audits`, `suggestions`, `content_items`, `brand_properties` and approval/input flows. Add only missing relationships; do not build a second scheduler, agent platform or generic workflow framework.

## 6. Batch 1: storage and orchestration

Primary paths: `agency-os/infra/migrations`, `scripts/worker.py`, new bounded assessment module(s), `tests/test_worker_workflows.py`. Update schema snapshot after migration is accepted.

Proposed minimum storage, adjusted to existing columns during Batch 0:

- `marketing_assessments`: id, brand/project, trigger task, schema version, status, brief snapshot/version, start/completion times, source manifest, report JSON, validation result, prior assessment reference, synthesis model/usage links.
- Reuse audit rows for immutable collector snapshots; associate each with assessment and source task. Snapshot defend evidence so later capability upserts cannot rewrite the past.
- Recommendation rows reference assessment, stable opportunity key and evidence IDs. Store owner, dependencies, validation method, metric and review horizon. Retain previous recommendations and decisions rather than deleting them on refresh.
- Brief data includes audience, geography/language, business model, offer, stage, primary outcome, constraints, source access and human competitor seeds. Every inferred field carries confidence/provenance and can be corrected.

Separate task execution success from overall assessment state. A coordinator can finish queueing, but the assessment stays `collecting` until required stages settle. Use existing task completion hooks plus a persisted idempotent reconciliation mechanism. Never keep the single worker blocked waiting for children it must execute.

Lifecycle: queued → collecting → synthesizing → ready or partial; failed/cancelled as appropriate. `partial` requires a usable validated report with named missing evidence. No validated report means failure, not a green partial success. Store stage timeouts, retry limits and recoverable checkpoints. Duplicate clicks and restart recovery must not duplicate child tasks, synthesis or recommendations. Exactly one finalizer wins concurrent completion races.

Preserve historical reports. New runs link to the exact snapshots from that run, not “latest available” rows from different runs. Mark explicitly reused evidence with age. Resume failed stages without repeating successful paid queries unnecessarily. Record cost and elapsed time per stage, including retries.

Acceptance: migration up/down or documented forward rollback tested on a disposable restored schema; concurrent finalizer test; restart mid-stage recovery; child failure and timeout tests; duplicate-request idempotency; brand/project mismatch rejected; old reports still viewable.

## 7. Batch 2: evidence, business context and competitors

Primary paths: `scripts/seo_measurement.py`, `scripts/self-tuning-brand-audit.py`, narrowly scoped new evidence/research modules, associated tests and dashboard setup endpoints.

Common evidence record: stable ID, assessment ID, source kind, exact URL or private record reference, observation timestamp, date window, country/device where relevant, observation, availability, completeness/truncation, limitation and optional content hash. Keep secrets, resumes, lead messages and personal data outside report evidence.

Technical audit improvements:

- Respect robots, redirects, header and HTML index directives, canonical relationships, sitemap bounds, content types and crawl caps. Separate crawl eligibility from confirmed search indexing.
- Handle graph-based JSON-LD; validate supported types/properties and visible-content consistency. Missing schema is a context-dependent opportunity, not a universal defect on privacy or unrelated pages. A JSON object alone must not pass semantic validation.
- Distinguish lab Lighthouse metrics from field CrUX data. Total Blocking Time is not INP. Show no field data honestly for young sites.
- Test declared social assets by response and content type before reporting a broken image. Do not infer deployment defects from source filenames.
- Do not identify a CMS solely from a `/blog/` response or treat absent WordPress REST as a defect on a static site.
- Bound public retrieval and prevent SSRF across URLs, DNS results and every redirect, including internal IPs, metadata endpoints, credentials, ports and malicious sitemap children. Reuse existing safe-fetch code where sound.

Analytics:

- Probe each site's actual GSC and GA4 access read-only and retain status. Distinguish permission failure, rate limit, empty valid report and malformed response.
- Collect GSC property totals separately from bounded query/page lists; retain anonymization and pagination limitations. Separate branded/non-branded estimates with documented matching rules.
- Collect GA4 hostname, channel/source/medium, landing page and configured outcome events with appropriate aggregate semantics. Do not sum non-additive unique users across rows into property totals.
- Use complete date windows and source-specific delay; show date ranges and freshness. Verify indexing/sitemap processing only via available first-party interfaces, otherwise label unverified.
- Define outcomes per project rather than hardcoding `generate_lead` for all businesses.

Competitor discovery:

- Preserve NextRaise (`nextraise.ai`) and Jobright (`jobright.ai`) as TrueApply human-provided seeds. Human corrections survive future audits and never disappear because a model proposes replacements.
- Discover additional candidates from several live intent queries using audience, geography and workflow; distinguish commercial substitutes, search competitors, publishers and adjacent tools.
- Validate identity and relevant product pages, not just reachable domains. Store inclusion/exclusion reasons and evidence. Do not require the human to discover every competitor.
- Capture bounded homepage, feature, pricing and relevant content evidence. Dates, claims and prices stay attributed; no unverified competitor success numbers become factual market estimates.
- Store observed search results with provider, query, locale, timestamp and rank. General search results do not establish keyword volume, difficulty, market share or a complete competitive landscape.
- Provider unavailable: keep confirmed seeds and direct-page evidence, mark discovery coverage partial and request the specific missing access in the dashboard. Do not label a model's remembered list a completed live discovery run.

Acceptance: fixture sites with and without schemas/CMS/blogs; robots/header/canonical cases; graph schema; stale/missing analytics; truncated datasets; SSRF and redirect tests; persisted seeds; competitor classification challenge set across SaaS, agency and a black-box fixture business.

## 8. Batch 3: synthesis and dashboard

Synthesis paths: new assessment synthesis/validation module, `scripts/suggestion-engine.py` compatibility wrapper, `scripts/worker.py` dispatch. Dashboard paths: `app.py`, `models.py`, `templates/brand_report.html`, reusable report fragments, `static/app.css`, route/template tests.

Turn the user's repeated questions into a versioned default assessment brief: What is the business trying to achieve? What works? What obstructs acquisition and conversion? Which competitors matter and why? What opportunities have evidence? What can execute now? What needs product integration, access or judgment? What happens next and how will we measure it?

Build a selected evidence packet from the persisted brief, current collector snapshots, verified competitor pages, prior accepted decisions, action outcomes and available executors. Use explicit budgets and relevance selection; never silently reduce the business to a 300-character homepage extract. Separate instructions from untrusted page text. Models cannot execute arbitrary page instructions.

Report schema v1:

- Executive diagnosis and primary business outcome.
- Verified strengths, defensive findings and growth opportunities.
- Market/competitor position with limitations and alternatives considered.
- Prioritized now/next/later plan with explicit dependencies and readiness gates.
- Recommendations: stable key, title, business rationale, facts versus hypothesis, evidence IDs, expected mechanism, priority rationale, estimated effort range, owner (agency/site/joint/human), required access, action type, prerequisites, acceptance checks, metric, baseline availability and review horizon.
- Human decisions and missing inputs; tool availability scoped to this project.
- Changes since the prior report, completed/rejected/pending actions and observed outcomes.

Validate evidence IDs and ownership, dependency acyclicity, valid action types, required fields, bounded lengths, source status and numerical claims. Reject invented volumes, guaranteed traffic lift, unsupported product capabilities and invalid citations. Model validation failure triggers bounded targeted repair; repeated failure is visible. Keep opportunity hypotheses useful when no numerical forecast exists.

Do not overwrite accepted decisions on every rerun. Reconcile recommendations by stable key, retain audit history, and explicitly mark superseded or no-longer-supported actions. A supported recommendation is not automatically executable: distinguish ready, needs input, manual and unsupported executor.

Native report should use the accepted artifact's hierarchy: clear assessment, capability truth table, growth opportunities, phase gates, shared responsibilities and sources. Adapt to dashboard styling and accessibility. Use deterministic templates and escaped structured data; never inject arbitrary generated HTML/scripts.

Add brief editing, competitor confirmation/correction, source drill-down, current/prior report selection, stage progress, retry failed source, approve/reject with reason, request input, content preview and outcome review. Keep every action tied to the displayed report version. Preserve existing URLs and old report views with an explicit legacy label.

Acceptance: report usable at mobile/desktop widths and keyboard-only; every important factual claim drillable to evidence; stale/partial states visible; XSS and cross-brand action tests; correcting business model changes subsequent context; blocked action cannot execute; no misleading “full audit complete” while sources are still running. Agent-generated task must include sufficient evidence and acceptance detail that another worker does not need the original chat.

## 9. Batch 4: reviewed publishing and attribution contract

Reuse research → outline → compose → content preview/approval. Add the smallest static-site publication adapter usable by both destinations, with an explicit destination manifest per site. Site owns rendering and files; Agency OS owns workflow and references. Avoid a core dependency on a TrueApply service or database.

Manifest: engagement/project identity, canonical repo/root, permitted content paths, URL base, supported page types, build/preview/test commands chosen from a trusted allowlist, deployment mechanism and rollback method. Model-supplied arbitrary shell commands or filesystem paths are forbidden.

Persist a content artifact containing typed text blocks, title, slug, description, author/reviewer, source citations, update date, schema inputs, CTA and intent. Render to static HTML with a shared site layout and escaped content. Use existing dependencies; add a Markdown parser only if existing typed blocks cannot meet a demonstrated requirement. No CMS/database is required for initial articles.

Before publication: source verification, claims review, link/image/license checks, deterministic render, accessibility/metadata/schema checks, internal links, sitemap, canonical and preview screenshot. Approval binds to content hash, destination and preview/build version. Any edit invalidates approval. Repeated publish requests cannot duplicate pages or releases.

Use tracked execution tasks to prepare source changes and connect their commit/release/deployment evidence. Deployment remains deliberate. Preserve previous artifact/commit and sitemap state for rollback. A failed remote/deploy response must reconcile actual state before retry. Never mark published from task acceptance alone: verify public URL, content fingerprint and expected indexing directives after deployment.

Attribution configuration is owned by each site. Define permitted event names/parameters, page/URL sanitization, consent behavior, internal/test traffic exclusion and event deduplication. No email, resume filenames/content, job descriptions, private resource IDs or token/query-string leakage. Test browser automatic collection as well as custom events.

Acceptance: draft → preview → approval → staged publish → HTTP/content verification → rollback → verified prior content. Include stale approval, forbidden destination, path traversal, concurrent publish, broken build, timeout after successful publication and retry recovery. All publication tests use isolated destinations before production authorization.

## 10. Batch 5A: TrueApply launch work

Ownership: `engagements/trueapply/infra/public-site`, site build/render scripts and tests; app event integration in `apps/web`; safe aggregate event derivation in engine only if required. Coordinate changes with existing admin/workspace refactoring.

- Improve homepage category clarity and benefit explanation while retaining beta and draft-only truth. Add a clearly labeled synthetic product example or demo and useful paths into help and guides. No invented testimonials, ratings or interview claims.
- Publish a compact first content set: two substantive commercial feature pages (resume tailoring; job matching), four guides answering validated search intent, and four practical help pages (supported uploads/troubleshooting; profile corrections; understanding matches and gaps; draft review/download/privacy). Select final titles from research; avoid duplicate intent and unrelated high-volume topics.
- Create navigable `/guides/` and `/help/` hubs under the public apex, with reviewer/source metadata, Article/Breadcrumb markup where appropriate, honest product/entity markup, sitemap updates and relevant product CTAs. Do not require a separate `apps/blog` runtime merely because the name was reserved.
- Verify actual SoftwareApplication rich-result requirements at implementation time. Do not fabricate reviews, ratings or prices to pass a validator. Entity markup can be valid without qualifying for a rich result.
- Make authenticated application/sign-in indexing policy explicit using appropriate response/meta directives. Preserve authentication and authorization as actual privacy protection. Do not block crawler access in a way that prevents Google from seeing a needed noindex directive.
- Instrument sign-in success, profile confirmation, first relevant job view, draft request/completion/failure and successful download, plus public CTA events. Use actual lifecycle transitions, not component renders, as business-event triggers.
- Preserve the existing activation definition: confirmed profile plus first relevant job viewed within 24 hours. Report successful draft/download separately as deeper value, not silently redefine activation.
- Verify same-site subdomain session continuity before adding linker settings. Validate OAuth referrals, consent and refresh/navigation behavior with synthetic accounts. Keep GA4 diagnostic counts separate from server-confirmed aggregate outcomes.
- Run current parser, review, draft/export and tenant tests. A failed core value journey blocks promotion and must produce a concrete fix task. Do not claim that a marketing launch resolves every historical product-quality issue.

Acceptance: entire synthetic visitor → sign-in → upload → confirm → relevant job → draft → download journey completes with expected events, no private content in analytics, readable public pages and truthful CTAs. Failed parse/draft paths produce correct failure events, useful help and no false conversion.

## 11. Batch 5B: Deployden launch work

Ownership: `core/deployden/public`, `server.py` only for scoped conversion correctness, `tests/test_site.py`, content build scripts. Inspect and retain existing technical SEO work; do not add redundant schema or redesign for its own sake.

- Validate the homepage and technical SEO, AI visibility and web development service pages against actual offered services and available Agency OS capabilities. Clarify buyer, deliverable and contact CTA. Claims of autonomous execution or real-engine visibility must match proven capability.
- Add a useful three-article first cluster supporting those service pages: measurement/readiness, practical technical SEO, and evidence-based search/AI visibility limitations. Final briefs use live search evidence. Use owned experience without presenting internal synthetic tests as client case studies.
- Add internal links, author/reviewer context and the same reviewed publishing contract with Deployden's own design and deployment.
- Verify `/api/lead` behavior, successful submission measurement and duplicate protection as relevant. A click or invalid/spam/rejected form must not emit `generate_lead`. External notification failure must not lose a stored lead or encourage duplicate submission.
- Use isolated SQLite and stub notifications in tests. Do not send test lead PII to Discord. Verify a production notification only with explicit authorization for that message.
- Register/validate the site's brief, service-business outcome, actual GSC/GA4 access and destination in the dashboard. Resolve its ledger IDs dynamically.

Acceptance: public article → service page → valid form in staging yields one stored synthetic lead and one appropriate conversion; error paths yield none. Dashboard assessment prioritizes qualified leads and service demand rather than TrueApply activation or ecommerce tactics.

## 12. End-to-end test plan

Create a reproducible isolated acceptance suite with disposable Postgres, temporary site content roots, stub external services, isolated Deployden SQLite, and TrueApply's existing synthetic fixtures. Never point destructive fixtures at runtime databases/volumes. Reuse existing CI container-smoke patterns. Use Playwright if installed; otherwise pin it as the smallest necessary browser-test dependency. No screenshots of personal data.

| ID | Scenario | Required result |
|---|---|---|
| E01 | Dashboard starts Deployden full assessment | One assessment and bounded child tasks; correct project; progress visible; no direct agent prompt |
| E02 | All collectors complete in any order | One synthesis after required stages settle; report references only its own source manifest |
| E03 | Google permission failure, provider outage or zero rows | Distinct source states; usable partial report when justified; no invented traffic or missing-as-zero |
| E04 | Crash after collection, during synthesis, after save | Resume without duplicate costs/actions; completed evidence retained; recoverable state |
| E05 | Two clicks or concurrent finalizers | Exactly one logical run/finalization according to idempotency policy |
| E06 | Report synthesis malformation or fabricated evidence | Validator rejects; bounded repair; visible failure after exhaustion |
| E07 | Prompt injection in competitor page or unsafe URL | No tool execution/instruction override, private fetch or secret exposure |
| E08 | Refresh after human rejects action or corrects competitor | Correction retained; rejected action not silently resurrected; versioned explanation |
| E09 | TrueApply, Deployden and black-box fixture assessed | Context and outcomes differ correctly; no cross-brand data; black-box limitations honest |
| E10 | Approve actionable content recommendation | Complete brief/evidence in linked task; preview and approval visible; no separate prompt needed |
| E11 | Publish approved article to staging, retry, then rollback | One URL with expected hash; correct sitemap/internal links; prior state restored |
| E12 | Change draft after approval or switch destination | Publication blocked until matching approval; no arbitrary filesystem writes |
| E13 | Re-audit after real fix in staging | Finding resolved by evidence; unchanged issues remain; history retained; no fabricated uplift |
| E14 | Browser TrueApply happy and failure journeys | Correct activation/value/failure counts; no duplicate events or private payloads |
| E15 | Browser Deployden valid/invalid/spam form paths | Stored lead and event only on valid success; no external test messages |
| E16 | Google reporting lag or absent field performance | Pending/unknown states and dates; no false failed deployment or claimed field CWV |
| E17 | Keyboard, mobile, long content, escaped hostile text | Report and previews usable; no horizontal page overflow or XSS; actions accessible |
| E18 | Unavailable executor/account/budget | Precise needs-input/manual state; analysis still available; no unauthorized side effect |
| E19 | Additive migration and rollback compatibility | Existing reports, approvals and content work; old application rollback does not destroy new evidence |
| E20 | Deployden independent of TrueApply availability | Core assessment/report/publishing remains usable when TrueApply endpoint is simulated unavailable |

Add focused unit/property tests for semantic schema validation, evidence references, aggregation arithmetic, recommendation reconciliation, URL safety, event sanitization, dependency cycles and approval fingerprints. Avoid tests that merely assert prompt wording. Test behavior and meaningful negative cases.

Run existing suites in suitable isolated environments, starting with:

- Agency OS: `python3 -m unittest discover -s tests` and Python compile checks, with required dependencies installed in a task environment.
- Dashboard: `python3 -m unittest discover -s tests` plus route/template tests and new browser acceptance.
- Deployden: `python3 -m unittest discover -s tests -p 'test_*.py'`; review `test-isolation.sh` before use because network checks may be environment-specific. Existing tests already cover metadata, sitemap, consent and lead behavior; extend rather than replace them.
- TrueApply: `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`; engine `uv run pytest`, `uv run ruff check .`, `uv run mypy trueapply_engine --ignore-missing-imports` from `services/engine`; applicable existing isolated container and tenant/export checks.

Inspect scripts before running any bootstrap, backup, integration or demo command. Some entrypoints may default to live data or create outbound actions. Adapt test environment explicitly. Core/dashboard CI must execute meaningful behavioral suites, not only compile. Require all integration acceptance cases to produce machine-readable pass/fail/blocked results and artifact references.

For TrueApply's release quality gate, repeat the supplied synthetic corpus evaluation using `scripts/evaluate_journey.py` and applicable current verification scripts after checking their arguments and storage boundaries. Report parser readiness, field recovery, relevant-job supply, first-attempt and bounded-retry draft completion, PDF/DOCX round-trip fidelity, latency and cost by case. Preserve failures visibly. Real supplied resumes remain private and require their existing authorized evaluation path; never copy them into public test artifacts or CI. Do not accept a single happy-path browser journey as proof of corpus-level product quality.

## 13. Quality assessment beyond schema validity

Maintain a small fixed evaluation pack for TrueApply, Deployden and an unrelated black-box fixture. Use deterministic expected observations and an independent review rubric:

- Business model, audience and conversion goal are correct or clearly unresolved.
- Known important competitor seeds are considered, with reasons and live evidence where available.
- At least one supported growth opportunity is distinct from technical repair when evidence warrants it; no arbitrary quota forces invented opportunities.
- Top priorities follow evidence, feasibility and prerequisites. Missing analytics cannot justify a confident paid-ROI forecast.
- Each proposed task is executable from its brief or explicitly names missing inputs.
- Recommendations distinguish platform work, site work, joint work and human decisions.
- The report explains what changed after an action and what remains unmeasured.

Release requires zero fabricated factual claims/evidence references in the evaluation pack and no critical privacy/authorization failures. A second agent reviews substantive usefulness; its judgment does not replace deterministic checks. Fix generic or misleading reports by tracing missing context/collection, not merely adding decorative prose.

## 14. Release and production verification

Terra produces a human-readable diff, green CI, acceptance ledger and exact deployment plan. Commit only owned verified changes. Resolve unrelated dirty changes using worktrees or explicit integration decisions. Capture running task IDs before any agency-worker restart; inspect side effects before resuming or requeueing interrupted tasks.

Apply additive migrations, deploy compatible core/dashboard once, verify health/old routes and new report actions, then deploy each owned site's reviewed release. Validate Caddy changes before reload where needed. Record commit/image identifiers, migration versions, backup references, deployment timestamps and rollback commands. Do not assume push deploys anything.

After authorized deployment, run real tracked assessments for both sites through the same dashboard API used by the UI. Verify actual read-only Google queries, public crawls, report completeness, source dates, seed competitors, recommendations and tasks. Do not create artificial SEO defects in production. Use genuine fixes or content additions for the before/after trail; otherwise explicitly retain an unproven production comparison state while staging tests provide functional evidence.

TrueApply production smoke uses an approved synthetic account and scoped data. A missing OAuth test session may require one human sign-in; automate the remaining journey once it exists. Do not bypass login. Production lead tests must avoid unsolicited notifications. Separate operational smoke evidence from real customer acquisition evidence.

## 15. Human acceptance: audit Deployden from the dashboard

The human performs this exact test after Terra's automated acceptance passes:

1. Open Deployden's brand report from Engagements. Confirm brief, conversion goal and source access are visible.
2. Click Run full audit once. No marketing prompt, copied URL list, shell command or separate AI session should be required.
3. Observe collecting/synthesizing progress. Parent status must not imply completion while child work is pending.
4. Read the finished native report: business diagnosis, defensive issues, growth opportunities, evidence, priorities, owners and next steps. Its clarity should match the accepted Lavish artifact.
5. Open a recommendation's sources and see actual observations and dates. Correct one brief/competitor assumption if appropriate; refresh and confirm persistence.
6. Select a real proposed content or technical action. The dashboard produces the linked brief/preview or precise missing input. Terra handles implementation; the human supplies only genuine product/publication decisions.
7. After an approved real change, rerun the assessment and inspect before/after findings and outcome tracking. Traffic improvement may remain pending, clearly labeled.

Human acceptance fails if a separate agent conversation is needed to obtain ordinary strategy, understand an unsupported recommendation, reconstruct task context or find the result. A real missing credential/business decision is acceptable only if the dashboard identifies it specifically and preserves the completed work.

## 16. Outcome monitoring included in this delivery

Ship a dashboard review queue using existing scheduling primitives: weekly source refresh and action-outcome review, with configurable bounded collection. Record publication/fix dates and consistent comparison windows. Assess indexing/first impressions early; review non-branded clicks, qualified activation and leads over subsequent weeks. Preserve seasonal, low-sample and attribution limitations. Before/after correlations are not proof of causality.

Show action status separately from marketing outcome: implemented/verified, measurement pending, observed improvement, inconclusive, or regression. Alerts are for actionable failures or decisions, not successful routine polling. Report cost per assessment and source freshness so the automation's operating cost is reviewable.

## 17. Execution handoff checklist

Terra should maintain one execution ledger with batch/task, owner, dependency, files, test result, artifact, commit, runtime verification and unresolved input. Update canonical roadmaps and the audit execution log after accepted implementation; do not mark planned capabilities available in advance.

Completion means: integrated code and tests pass, reviewed deployment is verified when authorized, both sites have their scoped public content and measurement improvements, native reports produce evidence-backed strategy, the human Deployden test passes, and ongoing outcome collection is installed. If publication/deployment authority or external access remains unavailable, finish reviewable code/previews/tests and report the exact remaining gate without claiming production completion.

Suggested next-session instruction:

> Use GPT-5.6 Terra as lead and bounded GPT-5.6 Luna workers. Implement `/home/agency/core/agency-os/MARKETING-DELIVERY-PLAN.md` in dependency order. Read current authoritative state, reconcile existing work, and maintain the acceptance ledger. Complete code, tests, previews and integration before presenting any missing deployment/publication authorization. Preserve the accepted Lavish artifact and deliver the native dashboard experience, TrueApply improvements and Deployden human acceptance path described in the plan.
