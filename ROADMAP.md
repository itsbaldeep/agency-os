# Agency OS — Roadmap & Open Items

Mission: a self-hosted AI digital-marketing agency that does real client work
for black-box brands. Deterministic core, LLMs as tools, humans at the gates
that matter. Everything visible on the dashboard at :5001.

See CEO_DIRECTIVE.md for full strategic context, competitive analysis, and
the human co-CEO checklist. Read CEO_DIRECTIVE.md first on every session.

State locked: 2026-08-16 (fresh-context handoff).

## Doctrine
- LLMs generate artifacts and decisions-as-proposals; code executes and verifies.
- Every LLM output passes a deterministic validator before entering the ledger.
- Black-box first: every feature must work without repo/CMS access.
- Everything visible on the dashboard — if it's not on :5001, it doesn't exist.
- Challenge everything: don't assume code exists = works. Test it.
- Determinism first, LLM second. Use the cheapest reliable model. Free fallback
  chain when credits run out (see Phase 0, done).

## Phase 0 — Fix what's broken (mostly DONE)
- [x] Fix cur2 bug in handle_run_brand_audit (confidence gate + suggestions unreachable)
- [x] Kill parasites: Aetheria loop, job-application stack, dead projects
- [x] Build brand audit report page on dashboard (/engagements/brand/<id>/report)
- [x] Fix crawl_homepage for WordPress sites (strip <head>, CSS leakage)
- [x] Add LLM fallback for business understanding (heuristic if model returns empty)
- [x] Stop wiping visibility history (removed pre-DELETE in self-tuning-brand-audit.py; insert-only)
- [x] Render defend_audit capabilities on brand report page (capability chips, severity colors)
- [x] Fix ClickHouse: memory 307MB→1.5GB (max_memory_usage 1500000000), killed stuck
      DELETE mutations that were blocking inserts; verified 120+ rows intact
- [x] Wire audit competitors → validated/deduped (domain regex + per-brand dedupe)
- [x] Suggestion semantics: black-box → instructions only (no approve/reject buttons,
      "Requires Code Access" gates, how-to steps); code brands → "Implement Now"
      creates dev task; content suggestions → "Generate Content" → /content/new
- [x] **Model-stack migration (2026-08-22):** Codex CLI replaces OpenCode for
      worker coding tasks and Discord `!run`/`!ask`; it uses subscription auth,
      not API keys. Raw LLM calls use DeepSeek `deepseek-chat` with
      `DEEPSEEK_API_KEY`, then z.ai GLM-4.5-Flash and a configurable OpenRouter
      `:free` model as cross-host fallbacks. `OPENCODE_FALLBACK=1` is rollback.
- [ ] Wire suggestion Approve → creates a task (still a no-op status flip; buttons
      hidden for black-box brands, but /api/suggestions/<id>/approve endpoint exists)
- [ ] Fix activity timeline query (events traced with project="brands", not brand name)

## Phase 1 — Real SEO data (needs human-provided keys)
- [ ] [HUMAN] GSC connector: service-account OAuth per brand. Nightly collector
      into signals table. Replaces Ahrefs estimates with real queries/impressions/CTR.
      **STATUS: GSC key exists at gcs-api-key.json (gitignored, user-provided) but NO
      GSC property is shared for any brand — technoflavour cannot be added by us;
      localfermentco status unknown. Connector code not started. Surfaced on report
      page as "Requires DNS TXT verification" gated capability.**
- [ ] PageSpeed Insights API (free, no auth): LCP/CLS/INP, mobile score → capabilities
- [ ] Rich Results / Schema validation via Google API (not just presence check)
- [ ] Real site crawl (up to N pages, polite): broken links, redirect chains,
      orphan pages, title/meta length, canonical issues
- [ ] Keyword table populated from GSC queries, positions tracked over time

## Phase 2 — Dashboard as the cockpit (partially DONE)
- [x] Unified brand report page: AI-visibility + defend capabilities + competitors +
      suggestions + content + audit history + recent activity in one view
      (/engagements/brand/<id>/report, 9 sections, severity colors, dense chips)
- [x] Engagement list: hot-first sort (last activity), Black-box/Code/Scaffolded
      badges, pending-action counts, audit/content/capability badges, View Report
      buttons, onboarding wizard (name+URL minimum, optional enrichment fields)
- [x] Content list/preview: clickable rows, sticky action bar (Download/Approve/
      Regenerate/Compose Full Draft), content_blocks rendered as formatted HTML
- [x] Competitors page: linked back to engagement+report, "why" text from audit,
      baseline-vs-delta scan status explanation, unverified-domain warning chips
- [ ] Charts: visibility trend, ranking movement, spend per brand (Chart.js)
- [ ] Per-brand spend breakdown from token_usage
- [ ] Pipeline config UI: brand_pipelines (enabled_stages, cron, Run Now) — table
      exists, not rendered

## Phase 3 — Execution loop (needs client CMS access)
- [ ] [HUMAN] WordPress publisher: publish_content step in approval-executor.
      REQUIRES: WP Application Password from client. Technoflavour has WP REST API
      available (capability check passed) — only auth credential missing.
- [ ] Content decay detection: pages older than N months → refresh briefs
- [ ] Findings→suggestions bridge: defend_audit defects auto-filed as suggestions
- [ ] Wire run_brand_audit competitors to competitor_scan (scan_enabled=true,
      populate sitemap_url) — only paperboat.com (brand 4) scanned so far (9 pages,
      baseline done 2026-08-15); rest are inert stubs
- [ ] Draft variants: N concepts → pick one → full draft

## Phase 4 — AEO + multi-engine
- [ ] Real AI-visibility: query ChatGPT/Perplexity/Gemini/Copilot APIs (not just
      DeepSeek), word-boundary citation matching
- [ ] AEO-structured content: front-loaded answers, FAQ schema, llms.txt
- [ ] Weekly marketing decision job: reads signals + gaps → prioritized plan
- [ ] Seasonal/event calendar via Google Trends

## Parked (deliberate — not until 3+ paying clients)
- Google/Meta ads, social media posting, email campaigns, WhatsApp/RCS
- PR marketplace, local SEO/GBP, ecommerce SEO, image generation
- Multi-tenant SaaS, billing, RBAC, knowledge graph, learning engine
- Nightly builder, auto-merge, assistant channel (meta-loop — not client value)
- **Hearth / Streamwise / old scaffolded apps: archived (state='archived'),
  excluded from engagement list. Do not revive.**

## System state to know on session start (2026-08-16)
- Brands: 4=Localfermentco (project 26, black-box, 5 competitors, audit_id 29:
  0/15 cited, gate blocked, 7 suggestions 93-99), 23=Technoflavour (project 28,
  black-box, 9 deduped competitors, audit_id 28, 8 suggestions 85-92), plus
  Brevo(1), Minimalist(2), Verbatimsolutions(9), Kalamkari(11), Testauditbrand(16),
  Subscription Optimizer(21). Junk removed: brand 22 "system", project 22,
  8 junk clients.
- defend_audit done for both active brands: 10 capabilities each.
  Localfermentco gaps: blog missing, RSS missing, Twitter cards missing,
  91/93 images missing alt text, no WP REST API, 84 sitemap URLs.
  Technoflavour: everything available incl. WP REST API.
- ClickHouse ai_visibility_checks: brand 1=60, 2=60, 4=15 rows.
- Worker: systemd agency-worker, restarts on deploy (orphans running tasks —
  re-queue after each agency-os push). Deploy jobs: 8 (agency-os, 2min),
  9 (dashboard, 3min) — both disabled; do not re-enable them. Deploy scripts SKIP when the deployed repo
  /home/agency/agency-os has uncommitted changes (commit config drift there first).
- Dashboard: 100.64.0.1:5001. Codex CLI is the agent harness; OpenCode is
  retained only behind `OPENCODE_FALLBACK=1`.
- Raw completions: DeepSeek `deepseek-chat`, then z.ai/OpenRouter fallback.
