# Deployden Marketing OS v2 release ledger

Owner direction, 2026-10-04 UTC: Deployden is a human-led design, development and digital marketing services agency. The dashboard is its internal operating console. Tested core, dashboard and website deployment is authorized. Client publications, social posts, campaigns and spending require separate exact approvals.

## Delivered source under acceptance

Compact portfolio and seven brand workspace tabs: overview, strategy, measurement, editorial, social and video, lifecycle, setup. Shared workers consume ledger-scoped configuration. Development tasks are retired; technical recommendations produce a developer handoff. Existing editorial approval and immutable audit history remain intact.

Brand briefs, channel identity/checklists, marketing drafts, planning dates and revision-bound draft/media jobs are durable. Local media creates graphics, carousels and 20-second portrait launch videos from owned screenshots and approved facts. No narration or generative photography provider is configured. Exact publication approval is separate from marking a draft ready.

GA4 collection adds page views, event and acquisition samples. First-party journey connection setup stores references, never credentials or recipients. Schema 2 supports generic stage totals; schema 1 remains a legacy adapter. Daily measurement is opt-in; the previously authorized TrueApply pilot remains enabled. Dates on content and campaigns are planning, not automatic dispatch.

Deployden website is redesigned around services and human review, with consent-first analytics, existing contact storage and a journal destination. Static publication uses approval digests, private ownership receipts, atomic files and exact retry recovery. A whole publication generation is not a multi-file filesystem transaction.

## External capability gates

Social APIs, backlink providers and campaign delivery are not connected by saving a profile. Account owners must create or select accounts, grant access and verify provider scopes. This release supports setup, production, review and export; direct social publishing and email sending require verified provider adapters and recipient consent/suppression workflows. These remain required work for the full enterprise goal and must not be advertised as live.

Imported historical TrueApply launch copy must be reviewed against current product and offer details. The original video approval does not authorize new channel publication.

## Recovery and acceptance

Pre-release core backup: `/home/agency/backups/core/core-backup-20261004T093105Z.tar.gz`, SHA256 `7bf8b16adfab52db3b4424fadfe0d3267aa898cb1346a23a6d04d819459628c5`, root state included.
Prior dashboard image: `sha256:5b3ccc4be62dd416b8171299762fe9cf74e3f66884940557dc7c602126df20d2`.
Prior Deployden image: `sha256:e33e626502cabf11f1710a69b36feee8a8a833d66c12322b22c4d39b6fd483f8`.

Additive migrations 020, 021 and 022 are awaiting deliberate deployment. Source verification and live deployment evidence will be appended after acceptance. Preserve the unrelated working ROADMAP changes outside this release commit.

Reference schemas verified 2026-10-04: [GA4 dimensions and metrics](https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema), [Search Console Search Analytics](https://developers.google.com/webmaster-tools/v1/searchanalytics/query). GSC query results are bounded samples, not a backlink inventory.

## Live release checkpoint, 2026-10-04 UTC

Committed and deployed: core `12351017883781af7839e501830f699b0b0495e9`, dashboard `6d0ecdc73bb676fb93674e0991a9d7b6ea5df1b5`, Deployden `b39dfc1af1811bc37d26f60e17f27f7e442bbf75`. Migrations 020 through 022 applied transactionally. Queue had zero running tasks before the one deliberate worker stop/start, so no restart orphans existed. Runtime recovery copies and committed source archives are in `/home/agency/backups/releases/dashboard-v2-20261004`.

New dashboard image `sha256:fca7dcb692d0abe2e36bfb8888ed8363e8b8268c6084ca2c3be389d6a79050c7`, Deployden image `sha256:ba050c7bd0e18f1f68b3d907a7f234e67b2fdd5ddb42493181e4064815528f69`. Existing lead storage mount remains `/home/agency/core/deployden/data:/data`.

Verification: 284 core tests (2 skipped), 112 dashboard tests (1 skipped), 5 Deployden tests passed. Live health, all fourteen brand tabs, portfolio, calendar, reports, alerts and operations return 200. Public site and six destination routes return 200. Browser verification on fourteen live dashboard routes at 1440 and 390 pixels passed overflow checks with no page errors; mobile menu settled at left 0, width 192. Public desktop/mobile screenshots inspected. Browser fixture font configuration is `/tmp/agency-browser-fonts.conf`, harness `/tmp/dashboard_v2_live.cjs`; this host requires a font configuration for Chromium.

Tracked tasks 432/433 completed fresh measurement snapshots 63/64. Both brands have available GA4, GSC, crawl and PageSpeed evidence. TrueApply GA4 journey reporting is available. First-party activation is unavailable: the running TrueApply API has no marketing read token set, and the configured aggregate endpoint returns 404. A credential reference alone does not activate an engagement runtime. That runtime change remains outside the core-only deployment completed here.

Task 436 imported the owner-referenced TrueApply launch session as eight draft work items 4 through 11. Original artifacts are served only through brand-scoped download routes. Tasks 437 through 439 prepared Deployden social, account-setup and enquiry follow-up drafts. No post, campaign or new article has been published or sent.

The full goal remains active: verified provider adapters and exact social/email campaign execution, actual account onboarding, retention runtime connection, static rollback UI, richer campaign eligibility/preview and scheduled approved execution still require delivery or owner access. Do not mark the enterprise objective complete based on this initial live v2 release.

## Portfolio consolidation and static recovery, 2026-10-04 UTC

Core `1c31c97` and dashboard `8316a2d` are committed, pushed and deliberately deployed. Portfolio is the single cross-brand overview; `/brands` redirects to `/dashboard`. Individual brand workspace routes remain available. Live redirect, portfolio navigation and both owned brand workspaces were verified. Dashboard image is `sha256:ba55836c042f03c9b054bfa905234d28f62081f29dee8068eb495fb910b88583`.

Owned static articles now have an exact-receipt withdrawal review and tracked recovery worker. Recovery preserves a checksummed private archive and repairs indexes on retry. The dashboard binds withdrawal to the original completed publication receipt and current destination. Isolated tests prove the route-to-worker workflow against real PostgreSQL and temporary files; no live client article was withdrawn. Acceptance included 117 dashboard tests (one skipped), seven recovery-worker tests, thirteen static publisher tests and four PostgreSQL workflow tests.

The queue was empty before the worker stop/start. Recovery copies and the captured task list are in `/home/agency/backups/releases/dashboard-v2-recovery-20261004`. Worker service is active after deployment. Unrelated working changes remain excluded from the runtime copy.

## Structured campaign rules, 2026-10-04 UTC

Core `b851e98` and dashboard `d8542d4` plus `0d1fef3` add campaign policy editing and honest delivery readiness. Rules include message category, confirmed service trigger, inactivity thresholds, cooldown, seven-day frequency cap and IANA timezone quiet hours. Shared eligibility is fail-closed and requires source facts no older than five minutes, active verified address, consent where applicable, explicit suppression/risk flags and deduplication. Repeated and skipped daylight-saving hours are tested. Recipient facts are not transferred or persisted by the dashboard policy editor.

Changing policy resets the item to draft and increments its revision. Invalid or cross-brand updates are rejected. Existing free-text brief edits also validate structured policy and category consistency. The Deployden enquiry draft now records transactional `enquiry.requested` rules; this is a draft configuration, not proof of a verified event or delivery authorization.

Acceptance: 126 dashboard tests (one skipped), twelve campaign contract tests and five rollback-only PostgreSQL workflow tests passed. Live readiness and cross-brand isolation passed. Browser checks at 1440 and 390 pixels prove loaded rules, guided transactional/category dependencies and no overflow or page errors. Screenshots are `/tmp/campaign-policy-1440.png` and `/tmp/campaign-policy-390.png`.

Campaign deployment captured an empty queue and backed up prior runtime files under `/home/agency/backups/releases/dashboard-v2-campaigns-20261004`. Only committed campaign modules were copied to runtime; other working changes were excluded. Dashboard image is `sha256:d210c283426cfd732312231c3b2e337249c89c1e0bc0e6cf8e4c28d0970638d4`. Direct delivery remains unavailable until a brand-owned adapter, fresh audience preview and exact approval are proven. No campaign was sent or scheduled.
