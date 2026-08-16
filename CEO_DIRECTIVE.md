# Agency OS — CEO Directive (2026-08-16, state locked for fresh-context handoff)

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

## 3. Honest assessment — where we actually are (2026-08-16)

Progress since 2026-08-15: the report surface, capability rendering, ClickHouse
stability, and the engagement cockpit are all live. What follows is the
current truth, not the previous state.

### What works (verified live)
- Control plane: Postgres ledger, ClickHouse traces, approval gates, cron,
  Discord bot, dashboard, OpenCode brain. Solid.
- `defend_audit`: thin but functional — checks robots/sitemap/blog/feed/
  WP REST/meta/OG/JSON-LD presence/image alt. Writes `capabilities` rows.
  Accepts brand_id (auto-resolves domain, auto-creates project for black-box).
  Ran for both active brands (10 capabilities each).
- `run_brand_audit`: crawls homepage, LLM infers category/competitors/prompts,
  queries LLM with brand-neutral prompts, substring-matches brand name for
  "AI visibility." Writes `audits` + `competitors` + ClickHouse rows +
  `suggestions`. cur2 bug fixed 2026-08-15; confidence gate + suggestion
  engine now reachable. Fresh audit ran on localfermentco.in (audit 29,
  7 suggestions).
- **Report page** `/engagements/brand/<id>/report` — the pitchable surface:
  executive summary (visibility %, confidence, gate alerts), capabilities
  checklist with severity colors + per-capability metrics (URL counts,
  lastmod dates, alt-text stats), gated capabilities (GSC/WP/Code locked
  badges), per-prompt AI visibility table from ClickHouse, competitor
  analysis (page counts, freshness), suggestions with capability gates +
  implementation instructions + linked content/tasks, content & drafts,
  audit history, recent activity, methodology + raw JSON. All surfaces
  interlinked (report ↔ content ↔ tasks ↔ competitors ↔ engagements).
- **Engagement cockpit** `/engagements`: unified clients/projects/brands,
  hot-first sort by last activity, Black-box/Code/Scaffolded badges, pending
  action counts, audit/content/capability badges, View Report buttons,
  onboarding wizard (name+URL minimum, optional: industry, target market,
  audience, competitors, stage, channel, notes). Deduped (Localfermentco x4 →
  x1); junk removed (brand 22 "system", project 22, 8 junk clients, archived
  infra projects excluded from list).
- **Content pipeline**: research → outline → compose with typed GEO blocks;
  content list rows clickable → preview page with sticky action bar
  (Download/Approve/Regenerate/Compose Full Draft); outline rows get
  "Continue to Draft"; content_blocks rendered as formatted HTML.
- **Suggestion semantics**: black-box brands — no approve/reject buttons,
  "Requires Code Access" locked badges, step-by-step how-to instructions,
  "Generate Content" → /content/new?brand_id=&suggestion_id=, linked content
  + task badges. Code-access brands — "Implement Now" creates a dev task.
- `competitor_scan`: fetches competitor sitemaps, diffs against last snapshot.
  paperboat.com (brand 4) baseline done (9 pages, 2022-10-31 lastmod).
  Competitors page now links back to engagement+report, shows "why" text,
  explains baseline-vs-delta status, flags unverified auto-proposed domains.
- **Free-model fallback (2026-08-16):** credits exhausted on the opencode
  workspace (HTTP 401 CreditsError killed every AI task). Added fallback
  chain to all three LLM call sites (worker.py call_zen, self-tuning-brand-
  audit.py zen, suggestion-engine.py zen): hy3-free → laguna-s-2.1-free →
  nemotron-3-ultra-free → deepseek-v4-flash-free → mimo-v2.5-free, all $0.
  Triggers on CreditsError / Insufficient balance / FreeUsageLimitError /
  429. Verified: content_compose task 270 (17 blocks) ran entirely on
  hy3-free at $0.0; content item 19 (Technoflavour, "physical therapy
  benefits") is now draft. Free models report cost=0 and echo model name.
- **ClickHouse fixed**: memory 307MB→1.5GB (max_memory_usage 1500000000),
  stuck DELETE mutations killed, pre-DELETE removed from audit script
  (insert-only). ai_visibility_checks rows: brand 1=60, 2=60, 4=15.

### What's broken or missing (the real gap)
1. **No real SEO data sources.** No GSC property connected (key exists at
   `gcs-api-key.json` but no property shared for any brand), no GA4, no
   Ahrefs, no PageSpeed, no real SERP, no backlinks, no site crawl, no
   schema validation. The "audit" is still homepage curl + LLM + sitemap
   presence. A senior SEO specialist would call it a triage sketch.
2. **Suggestion Approve is still a no-op status flip** for black-box brands
   (buttons hidden on report; API endpoint exists but creates no task).
3. **Activity timeline query** traces events with project="brands" not brand
   name — brand activity may be sparse on brand pages.
4. **No ads/campaigns/email/WhatsApp/social** — zero. SearchAtlas's tagline
   ("runs your SEO, AEO, Google Ads, Meta Ads, content, and site health")
   beats us ~10-fold in scope.
5. **Credits exhausted** — paid model down; free fallback works but free
   models are rate-limited and lower quality. Top-up restores quality.
6. **AI-visibility is a training-knowledge proxy** — single LLM (DeepSeek),
   substring match, no real ChatGPT/Perplexity/Gemini/Copilot citation data.
   Citation matching has no word boundaries ("Apple" matches any fruit).
7. **Competitors mostly inert stubs** — only paperboat.com scanned;
   run_brand_audit competitors not yet wired to competitor_scan
   (scan_enabled=false, no sitemap_url for the rest).

### The honest bottom line
We went from 5-10% to maybe 20-25% of what competitors do, on the surfaces
that matter most for pitching (report + cockpit + content). The product
surface is real now. The next leap requires real data (GSC/PageSpeed/crawl)
and one real client to iterate against.

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

### Phase 0 — Fix what's broken (DONE except 2 items)
- [x] Fix `cur2` bug in `handle_run_brand_audit` (DONE 2026-08-15)
- [x] Kill parasites: Aetheria loop, job-application stack, dead projects (DONE)
- [x] Dashboard: brand audit report page (DONE 2026-08-15 — the pitchable surface)
- [x] Render `defend_audit` results on brand report page (capability chips) (DONE)
- [x] Stop wiping visibility history — pre-DELETE removed, insert-only (DONE)
- [x] ClickHouse memory fix + mutation cleanup (DONE 2026-08-15)
- [x] Competitor domain validation + dedupe (DONE)
- [x] Suggestion semantics: black-box instructions vs code implement vs content
      links, capability-gated (DONE 2026-08-15)
- [x] Content list/preview UI + engagements cockpit + onboarding wizard (DONE)
- [x] Free-model fallback for exhausted credits (DONE 2026-08-16)
- [ ] Wire suggestion Approve → creates a task (still a no-op status flip;
      buttons hidden for black-box)
- [ ] Fix activity timeline query (project="brands" vs brand name)

### Phase 1 — Real SEO data (1-2 weeks, needs user-provided keys)
- [ ] **Google Search Console connector** — service-account OAuth per brand.
      Nightly collector: queries, impressions, clicks, CTR, position → `signals`
      table. **STATUS: key file exists (gcs-api-key.json, gitignored) but NO
      GSC property shared for any brand. technoflavour is not addable by us;
      localfermentco property unknown. Connector code not started — report
      shows "Requires DNS TXT verification" gate until a property exists.**
- [ ] **PageSpeed Insights API** — free, no auth. Add to `defend_audit`:
      LCP/CLS/INP, mobile score, lab data. Best unblocked next step.
- [ ] **Rich Results / Schema validation** — Google's Rich Results Test API.
- [ ] **Real site crawl** — not just homepage; broken links, redirect chains,
      orphans, title/meta length, canonical issues.
- [ ] **Keyword table + tracking** — from GSC queries, positions over time.

### Phase 2 — Dashboard as the cockpit (partially DONE)
- [x] Unified brand report page (audit + capabilities + competitors + suggestions
      + content + history + activity) (DONE)
- [x] Engagement list cockpit + onboarding wizard (DONE)
- [x] Content pipeline visible on brand page + preview page (DONE)
- [x] Competitor page linkage + scan-status explanation (DONE)
- [ ] Charts: visibility trend, ranking movement, spend per brand (Chart.js)
- [ ] Per-brand spend breakdown from `token_usage`
- [ ] Pipeline config UI — `brand_pipelines` table (enabled_stages,
      schedule_cron, Run Now). Already in DB, not rendered.

### Phase 3 — Execution loop (2-4 weeks, needs client CMS access)
- [ ] **WordPress publisher** — `publish_content` step in approval-executor.
      Technoflavour has WP REST API available; missing only the Application
      Password from the client.
- [ ] **Content decay detection** — pages older than N months → refresh briefs.
- [ ] **Findings → suggestions bridge** — defend_audit defects auto-filed.
- [ ] **Competitor content scan** — wire run_brand_audit competitors to
      competitor_scan (scan_enabled=true, populate sitemap_url). Only
      paperboat.com scanned so far.
- [ ] **Draft variants** — N {title, angle, outline} concepts → pick → draft.

### Phase 4 — AEO + multi-engine (4-8 weeks)
- [ ] **Real AI-visibility** — ChatGPT/Perplexity/Gemini/Copilot APIs, real
      citations with word-boundary matching.
- [ ] **AEO-structured content** — front-loaded answers, FAQ schema, llms.txt.
- [ ] **Seasonal/event calendar** — Google Trends integration.
- [ ] **Weekly marketing decision job** — signals + capabilities + gaps +
      content inventory → prioritized plan into suggestions.

### Parked (deliberate — not until 3+ paying clients)
- Google/Meta ads automation, social media posting, email campaigns,
  WhatsApp/RCS, PR marketplace, local SEO/GBP, ecommerce SEO, image generation,
  multi-tenant SaaS, billing, RBAC, knowledge graph, learning engine.
- Hearth/Streamwise/old scaffolded apps: archived, excluded from engagement
  list. Do not revive.

## 6. What I need from the human co-CEO (checklist)

### Immediate (unblocks Phase 1)
- [ ] **GSC property access** — key file exists (gcs-api-key.json). Now need:
      (a) a GSC property that can be shared with the service account for ANY
      brand (technoflavour can't be added by us — it's not your Google account;
      localfermentco needs the client's verification), or (b) permission to
      create/verify a property for a domain we control. Until then the GSC
      connector stays gated. The service-account email must be given the
      property; DNS TXT verification is the standard path.
- [ ] **Confirm technoflavour.com status** — real client/prospect? Do they
      have a GSC property we can access?
- [ ] **Top up opencode workspace credits** (optional but recommended) —
      paid deepseek-v4-flash is the primary model; free fallback works but
      free models are rate-limited and lower quality.

### When we have a real client engagement
- [ ] **WordPress Application Password** from the client (Phase 3 publisher).
      URL + username + app password. Technoflavour is WP-ready.
- [ ] **3 real competitor names** per client (seed/validate LLM-proposed ones).
- [ ] **Ahrefs API key** (optional, $99+/mo) — real backlinks, KD, content gap.
- [ ] **OpenAI API key** (optional — real ChatGPT visibility, Phase 4).

### Strategic decisions only the human can make
- [ ] **Public domain for the marketing site** — deployden.tech is infra.
      Separate agency brand domain for public site + free audit lead magnet?
- [ ] **Pricing model** — retainer vs per-project vs free-audit → paid execution?
- [ ] **First real client** — technoflavour (your product) as case study, or a
      real prospect?

## 7. Operating rules for the AI co-CEO

1. **Challenge everything.** Don't assume code exists = works. Test it.
2. **Use subagents for exploration** — keep the main context window for
   decisions, not file reading.
3. **Push context to files** — CEO_DIRECTIVE.md, ROADMAP.md. Never hold
   critical state only in chat. On session start: read CEO_DIRECTIVE.md
   then ROADMAP.md (ROADMAP has the system state block).
4. **Deploy from time to time** — don't let work sit uncommitted. The
   auto-deploy jobs (8, 9) will pick up merges. **WARNING: pushing to
   agency-os restarts the worker and orphans running tasks — re-queue
   orphaned tasks after each push, or temporarily disable job 8 during
   long audits.** Deploy scripts SKIP when /home/agency/agency-os has
   uncommitted changes — commit config drift there first.
5. **Everything visible on the dashboard** — if it's not on :5001, it doesn't
   exist for the human co-CEO.
6. **Never assume a data source is available** — ask for keys/permissions early.
7. **Be honest about gaps** — the user respects honesty over false confidence.
8. **Determinism first, LLM second** — LLMs generate proposals; code validates
   and executes. Every LLM output passes a deterministic validator.
9. **Black-box first** — every feature must work without repo/CMS access.
   Deeper access unlocks more, but the default path is public-web-only.
10. **Credits may be zero** — the free fallback chain keeps the pipeline alive
    (hy3-free etc.). Free models are slower/rate-limited; don't treat their
    output as equal quality. Check for "model" key in call results.

## 8. Parasites killed (2026-08-15)

| What | Action | Reversible via |
|---|---|---|
| Aetheria autonomous dev loop | Cron commented, job 12 disabled, DISPATCH entry removed, nav link removed | Uncomment + re-enable |
| Job-application automation (7 handlers) | DISPATCH entries commented, /jobs nav removed. Code/tables preserved. | Uncomment DISPATCH block |
| 7 dead projects | state → 'archived' | UPDATE state back |