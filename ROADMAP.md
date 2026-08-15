# Agency OS — Roadmap & Open Items

Mission: a self-hosted AI digital-marketing agency that does real client work
for black-box brands. Deterministic core, LLMs as tools, humans at the gates
that matter. Everything visible on the dashboard at :5001.

See CEO_DIRECTIVE.md for full strategic context, competitive analysis, and
the human co-CEO checklist.

## Doctrine
- LLMs generate artifacts and decisions-as-proposals; code executes and verifies.
- Every LLM output passes a deterministic validator before entering the ledger.
- Black-box first: every feature must work without repo/CMS access.
- Everything visible on the dashboard — if it's not on :5001, it doesn't exist.
- Challenge everything: don't assume code exists = works. Test it.
- Determinism first, LLM second. Use the cheapest reliable model.

## Phase 0 — Fix what's broken (NOW)
- [x] Fix cur2 bug in handle_run_brand_audit (confidence gate + suggestions unreachable)
- [x] Kill parasites: Aetheria loop, job-application stack, dead projects
- [x] Build brand audit report page on dashboard (/engagements/brand/<id>/report)
- [x] Fix crawl_homepage for WordPress sites (strip <head>, CSS leakage)
- [x] Add LLM fallback for business understanding (heuristic if model returns empty)
- [ ] Wire suggestion Approve → creates a task (currently a no-op status flip)
- [ ] Stop wiping visibility history (remove DELETE in self-tuning-brand-audit.py)
- [ ] Render defend_audit capabilities on the brand page (not just project page)
- [ ] Fix activity timeline query (events traced with project="brands", not brand name)

## Phase 1 — Real SEO data (needs human-provided keys)
- [ ] [HUMAN] GSC connector: service-account OAuth per brand. Nightly collector
      into signals table. Replaces Ahrefs estimates with real queries/impressions/CTR.
      REQUIRES: GCP project + service account + GSC property shared.
- [ ] PageSpeed Insights API (free, no auth): LCP/CLS/INP, mobile score → capabilities
- [ ] Rich Results / Schema validation via Google API (not just presence check)
- [ ] Real site crawl (up to N pages, polite): broken links, redirect chains,
      orphan pages, title/meta length, canonical issues
- [ ] Keyword table populated from GSC queries, positions tracked over time

## Phase 2 — Dashboard as the cockpit
- [ ] Unified brand page: merge AI-visibility + tech audit into one view
- [ ] Competitor comparison: side-by-side visibility, keyword overlap, content gap
- [ ] Content pipeline on brand page (not just project page)
- [ ] Charts: visibility trend, ranking movement, spend per brand (Chart.js)
- [ ] Per-brand spend breakdown from token_usage
- [ ] Pipeline config UI: brand_pipelines (enabled_stages, cron, Run Now) — table
      exists, not rendered
- [ ] Black-box onboard form: just name + website URL (no repo needed)

## Phase 3 — Execution loop (needs client CMS access)
- [ ] [HUMAN] WordPress publisher: publish_content step in approval-executor.
      REQUIRES: WP Application Password from client.
- [ ] Content decay detection: pages older than N months → refresh briefs
- [ ] Findings→suggestions bridge: defend_audit defects auto-filed as suggestions
- [ ] Wire run_brand_audit competitors to competitor_scan (scan_enabled=true,
      populate sitemap_url)
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
