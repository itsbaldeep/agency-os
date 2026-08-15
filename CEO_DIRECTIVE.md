# Agency OS — CEO Directive (2026-08-15)

Authority: human co-CEO + AI co-CEO (OpenCode). This file is the persistent
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

## 3. Honest assessment — where we actually are (2026-08-15)

The user challenged the AI co-CEO's confidence. The challenge was correct.
After running a real audit and reading the code end-to-end:

### What works
- Control plane: Postgres ledger, ClickHouse traces, approval gates, cron,
  Discord bot, dashboard, OpenCode brain. Solid.
- `defend_audit`: thin but functional — checks robots/sitemap/blog/feed/
  WP REST/meta/OG/JSON-LD presence/image alt. Writes `capabilities` rows.
- `run_brand_audit`: crawls homepage, LLM infers category/competitors/prompts,
  queries LLM with brand-neutral prompts, substring-matches brand name for
  "AI visibility." Writes `audits` + `competitors` + ClickHouse rows + (now
  fixed) `suggestions`.
- Content pipeline: research → outline → compose with typed GEO blocks.
  Works but not visible on the brand page.
- `competitor_scan`: fetches competitor sitemaps, diffs against last snapshot.
  Works but competitors from `run_brand_audit` are inert stubs (scan_enabled
  = false, no sitemap_url).

### What's broken or missing (the real gap)
1. **`run_brand_audit` had a fatal bug** (`cur2` used before definition at
   worker.py:1095) — confidence gate + suggestion engine never ran. **Fixed
   2026-08-15.** Prior DB suggestions came from older code or manual inserts.
2. **No real SEO data sources.** No GSC, no GA4, no Ahrefs, no PageSpeed, no
   real SERP, no backlinks, no site crawl, no schema validation. The "audit"
   is a homepage curl + LLM imagination. A senior SEO specialist would call
   it a rough triage sketch, not an audit.
3. **Dashboard shows almost nothing.** One visibility %, inert competitor
   badges, suggestions with a no-op approve button (no task created), no
   audit report page, no charts, no trend, no competitor comparison, no
   client-facing report. `audits.summary` has rich data (prompts, competitor
   reasoning, market tier, methodology) that is **never rendered.**
4. **No ads/campaigns/email/WhatsApp/social** — zero. SearchAtlas's tagline
   ("runs your SEO, AEO, Google Ads, Meta Ads, content, and site health")
   beats us 10-fold in scope.
5. **No pitchable report.** No webpage/PDF/doc a human could show a client.
6. **Two audit types on unlinked pages** — brand AI-visibility on
   `/engagements/brand/<id>`, tech audit on `/projects/<id>`. No unified view.
7. **AI-visibility is a training-knowledge proxy** — single LLM (DeepSeek),
  substring match, no real ChatGPT/Perplexity/Gemini/Copilot citation data.
8. **Visibility history is wiped on re-run** (DELETE per brand_id in
   ClickHouse before insert).
9. **Citation detection has no word boundaries** — "Apple" matches any fruit.
10. **Competitors are inert stubs** — scan_enabled=false, no sitemap_url.

### The honest bottom line
We are doing **maybe 5-10%** of what competitors do. The infrastructure is
good. The product surface is not there yet. The user is right to demand we
build more before shipping a real client.

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

## 5. Grounded roadmap — black-box SEO first, then expand

### Phase 0 — Fix what's broken (NOW, 1-2 days)
- [x] Fix `cur2` bug in `handle_run_brand_audit` (DONE 2026-08-15)
- [x] Kill parasites: Aetheria loop, job-application stack, dead projects (DONE)
- [ ] **Dashboard: brand audit report page** — render `audits.summary` fully:
      visibility %, per-prompt table (from ClickHouse), competitor reasoning,
      market tier, methodology, crawl text excerpt, confidence/gate status.
      This is the "pitchable report" surface. Route: `/engagements/brand/<id>/report`
      or a report tab on the engagement page.
- [ ] **Dashboard: wire suggestion Approve → creates a task** (not a no-op)
- [ ] **Dashboard: render `defend_audit` results on the brand page** (not just
      project page) — capabilities as a checklist with status badges
- [ ] **Stop wiping visibility history** — remove the DELETE in
      `self-tuning-brand-audit.py:179`, use INSERT-only with audit_id

### Phase 1 — Real SEO data (1-2 weeks, needs user-provided keys)
- [ ] **Google Search Console connector** — service-account OAuth per brand.
      Nightly collector: queries, impressions, clicks, CTR, position → `signals`
      table. This replaces Ahrefs estimates with real data. **REQUIRES: user
      to create a GCP project + service account + share GSC property.**
- [ ] **PageSpeed Insights API** — free, no auth. Add to `defend_audit`:
      LCP/CLS/INP, mobile score, lab data. Write to `capabilities` or `signals`.
- [ ] **Rich Results / Schema validation** — use Google's Rich Results Test
      API (free) to validate JSON-LD, not just check presence.
- [ ] **Real site crawl** — not just homepage. Crawl up to N pages (polite,
      respect robots). Detect broken links, redirect chains, orphan pages,
      title/meta length issues, canonical issues.
- [ ] **Keyword table + tracking** — populate `keywords` table from GSC
      queries, track positions over time.

### Phase 2 — Dashboard as the cockpit (1-2 weeks)
- [ ] **Unified brand page** — merge brand AI-visibility + project tech audit
      into one view. Defend checklist + attack findings + suggestions queue +
      content drafts in tabs.
- [ ] **Competitor comparison view** — side-by-side: AI-visibility, keyword
      overlap, content gap, sitemap page count, blog freshness.
- [ ] **Content pipeline on brand page** — not just project page. For
      black-box brands with no project, draft → review → approve → download
      (or publish if CMS connected).
- [ ] **Charts** — visibility trend over time, ranking movement, spend per
      brand. Chart.js or similar.
- [ ] **Per-brand spend breakdown** from `token_usage`.
- [ ] **Pipeline config UI** — `brand_pipelines` table (enabled_stages,
      schedule_cron, Run Now). Already in DB, not rendered.

### Phase 3 — Execution loop (2-4 weeks, needs client CMS access)
- [ ] **WordPress publisher** — `publish_content` step in approval-executor
      for brands with WP REST config. Status=draft first, trace to events.
      **REQUIRES: user to get a WP Application Password from the client.**
- [ ] **Content decay detection** — list pages older than N months as refresh
      briefs into suggestions.
- [ ] **Findings → suggestions bridge** — defend_audit defects auto-filed as
      pending suggestions with plain-language rationale.
- [ ] **Competitor content scan** — wire `run_brand_audit` competitors to
      `competitor_scan` (set scan_enabled=true, populate sitemap_url).
- [ ] **Draft variants** — generate N {title, angle, outline} concepts, pick
      one, then full draft.

### Phase 4 — AEO + multi-engine (4-8 weeks)
- [ ] **Real AI-visibility** — query ChatGPT/Perplexity/Gemini/Copilot APIs
      (not just DeepSeek), measure real citations with word-boundary matching.
- [ ] **AEO-structured content** — front-loaded answers, FAQ schema, Q&A
      format, llms.txt, entity optimization.
- [ ] **Seasonal/event calendar** — Google Trends integration for demand
      timing.
- [ ] **Weekly marketing decision job** — reads signals + capabilities + gaps
      + content inventory, files a prioritized plan into suggestions.

### Parked (deliberate — not until 3+ paying clients)
- Google/Meta ads automation, social media posting, email campaigns,
  WhatsApp/RCS, PR marketplace, local SEO/GBP, ecommerce SEO, image generation,
  multi-tenant SaaS, billing, RBAC, knowledge graph, learning engine.

## 6. What I need from the human co-CEO (checklist)

These are the things only the human can do. Everything else is on me.

### Immediate (unblocks Phase 1)
- [ ] **Google Cloud project + service account** for Search Console API.
      Create a GCP project, enable Search Console API, create a service
      account, download the JSON key, share the GSC property with the service
      account email. Give me the JSON key path or contents. This is the
      single highest-leverage integration — it replaces all estimates with
      real data.
- [ ] **Confirm technoflavour.com is a real client/prospect** — do we have
      permission to audit it? Do they have a GSC property we can access?

### When we have a real client engagement
- [ ] **WordPress Application Password** from the client (for Phase 3
      publisher). URL + username + app password.
- [ ] **3 real competitor names** for the client (to seed/validate the
      LLM-proposed competitors).
- [ ] **Ahrefs API key** (optional but high-value — $99+/mo). Enables real
      backlink data, keyword difficulty, competitor content gap. Without this
      we rely on GSC + public crawl + LLM.
- [ ] **OpenAI API key** (optional — for real ChatGPT visibility measurement
      in Phase 4). We currently use Zen/OpenRouter which is fine for now.

### Strategic decisions only the human can make
- [ ] **Public domain for the marketing site** — deployden.tech is the infra
      domain. Do we want a separate agency brand domain for the public site +
      free audit lead magnet?
- [ ] **Pricing model** — per-client monthly retainer? Per-project? Free audit
      → paid execution? Decide before we build the public site.
- [ ] **First real client** — technoflavour (your own product) as a case
      study, or do you have a real prospect lined up?

## 7. Operating rules for the AI co-CEO

1. **Challenge everything.** Don't assume code exists = works. Test it.
2. **Use subagents for exploration** — keep the main context window for
   decisions, not file reading.
3. **Push context to files** — AGENTS.md, CEO_DIRECTIVE.md, ROADMAP.md.
   Never hold critical state only in chat.
4. **Deploy from time to time** — don't let work sit uncommitted. The
   auto-deploy jobs (8, 9) will pick up merges.
5. **Everything visible on the dashboard** — if it's not on :5001, it doesn't
   exist for the human co-CEO.
6. **Never assume a data source is available** — ask for keys/permissions
   early.
7. **Be honest about gaps** — the user respects honesty over false confidence.
8. **Determinism first, LLM second** — LLMs generate proposals; code validates
   and executes. Every LLM output passes a deterministic validator.
9. **Black-box first** — every feature must work without repo/CMS access.
   Deeper access unlocks more, but the default path is public-web-only.

## 8. Parasites killed (2026-08-15)

| What | Action | Reversible via |
|---|---|---|
| Aetheria autonomous dev loop | Cron commented, job 12 disabled, DISPATCH entry removed, nav link removed | Uncomment + re-enable |
| Job-application automation (7 handlers) | DISPATCH entries commented, /jobs nav removed. Code/tables preserved. | Uncomment DISPATCH block |
| 7 dead projects | state → 'archived' | UPDATE state back |
