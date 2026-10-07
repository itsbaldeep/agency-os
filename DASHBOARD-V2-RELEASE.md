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

## Read-only email provider connection, 2026-10-04 UTC

Core `fd8c885` and dashboard `a5c5f03` are tested and deliberately deployed. Email onboarding now stores brand-owned credential references and sender identity, then queues read-only Brevo account/sender verification. Worker paths reject traversal, symlinks including ancestors, unsafe ownership/permissions, non-regular files and oversized input. Provider requests use fixed HTTPS endpoints, GET only, no proxy or redirects, bounded responses and redacted receipts. Account access does not prove domain authentication, recipient eligibility or sending authority.

TrueApply setup task 449 stores a private engagement-owned reference to its existing live provider credential. Verification task 450 completed and recorded `source_unavailable`, `http_403`, with authentication and sender verification both false at `2026-10-04T16:34:00.476471+00:00`. The provider is not connected successfully. The owner has been asked to check provider access and IP-security settings; no exact cause is inferred from HTTP 403. No recipient data was copied and no email was sent.

Acceptance: ten provider tests, six rollback-only PostgreSQL workflow tests and 134 dashboard tests (one skipped) passed. Dashboard tests passed without script-directory overrides after committed runtime dependencies were synchronized. Live email setup loads the saved reference and unavailable state. Browser checks at 1440/390 pixels passed with no overflow or script errors. Screenshots: `/tmp/email-provider-1440.png`, `/tmp/email-provider-390.png`.

Deployment captured an empty queue, saved runtime recovery files in `/home/agency/backups/releases/dashboard-v2-email-provider-20261004`, copied only committed files and byte-verified them before starting the worker. Dashboard image: `sha256:152dbacec0978edc24b9c4a9cb4c5581a861d0e15f3b673f655d2c9e2b6cdc82`. Worker is active. Unrelated Ghost/search/publication-config working changes remain excluded.

API references checked 2026-10-04: [Brevo account read](https://developers.brevo.com/reference/get-account), [sender inventory](https://developers.brevo.com/reference/get-senders), [API-key access](https://developers.brevo.com/docs/api-key-authentication). These checks do not call the email sending endpoint.


## Exact campaign approval and scheduling, 2026-10-04 17:14 UTC

Core `8451ea0` and dashboard `3715c30` are deployed. Migration 023 stores exact
message, policy, audience, revision and send-time approvals, without recipient
records. Due approved runs queue tracked dispatch tasks. The worker checks current
ownership and draft revision, commits its claim before contacting the source, and
requires receipt reconciliation after an uncertain outcome. Cancellation before
dispatch persists through duplicate approval.

Validation: 134 dashboard tests passed (one skip), 37 campaign tests passed,
seven rollback-only PostgreSQL tests passed, and fixture-backed desktop/mobile
exact-review checks passed without approval requests. Live GET-only checks passed
at 1440 and 390 pixels for both email setup pages and Deployden's campaign detail,
with disabled delivery controls, no overflow and no script errors. The PostgreSQL
fixture uses savepoints to simulate commit/rollback boundaries while preserving
its outer rollback; it does not prove concurrent source outbox behavior.

The worker was stopped with an empty queue. Migration 023 was applied, four
committed runtime modules were copied and byte-verified, and the worker restarted.
Recovery files and the previous dashboard image are recorded in
`/home/agency/backups/releases/dashboard-v2-exact-campaigns-20261004`.
Live dashboard image:
`sha256:4c1206d19410c266b7d51b4c48335982ff35201e04d5fc57e519ad0ee61cbaed`.
Worker is active. No restart orphans were found. Unrelated dirty Ghost/search
and publication configuration changes were excluded.

Both brand campaign sources remain unconfigured, and the database contains zero
campaign runs. No delivery was approved or sent. Brand-owned source endpoints,
idempotent outbox execution and current provider access remain required before
live campaign delivery is usable. TrueApply's existing Brevo verification still
reports HTTP 403. Public marketing actions need separate exact approval.


### TrueApply integration source provenance

Verified 2026-10-04 17:17 UTC: the canonical engagement checkout is
`/home/agency/engagements/trueapply`, HEAD `d2f116d`, and lacks the retention
modules found in `/home/agency/worktrees/trueapply-v1.0.0`, HEAD `e30e70e`.
The running `trueapply-api-1` Compose labels name the latter worktree and
`/tmp/trueapply-prod-override.yaml` as its deployment origin. Its running image is
`sha256:7486b80b1eb1496634b99d8608c13256e72333025484c30d2a0cd5be78e7bb74`.
Canonical source and runtime origin therefore differ. Reconcile the retained
release lineage before authoring or deploying a campaign adapter. Canonical
compose files alone are insufficient evidence of the live application version.
No TrueApply source or runtime was changed during this verification.


## Unified planning and delivery calendar, 2026-10-04

Dashboard `cf1bc65` separates planning metadata from exact campaign delivery runs
at `/calendar`. An optional brand filter applies to both lanes. Approved runs show
revision, UTC delivery time, state and a work-item link; cancellation remains
visible. Queries never select contracts, recipients or credentials. Bounds reject
invalid, Unicode-only and oversized brand identifiers.

Validation: 137 dashboard tests passed (one skip) and seven rollback-only
PostgreSQL tests passed, including actual calendar SQL and approved-run rendering.
Desktop/mobile checks passed locally for all brands and brand filters. The
previous dashboard image is preserved in
`/home/agency/backups/releases/dashboard-v2-calendar-20261004`.
No worker restart or TrueApply deployment was performed. The isolated adapter
checkout `/home/agency/worktrees/trueapply-marketing-adapter` starts at current
remote release lineage `29f0cdb`, preserving the dirty canonical and running
checkouts. Existing retention code is present in that lineage; its staged module
comment is stale because the worker now wires consented product notifications.
This does not enable candidate application or outreach sending.

Mobile screenshot review found excessive row wrapping. Dashboard `6061d75` fixes
calendar table widths and compact UTC timestamps, retaining horizontal scrolling
inside the table. Repeated live desktop/mobile checks passed after deployment.
Final image: `sha256:3322be328850d19ddb614ba6ca70c1ce13561ad55775bbff45849e62f99d3b8a`.

## Private owned-brand enquiry review, 2026-10-06 UTC

Dashboard `32ea33b` and Deployden `ac6d782` are committed, pushed and deployed.
Deployden's Lifecycle workspace links to `/brands/27/enquiries`. The private
view reads the source-owned SQLite store through an explicit read-only mount;
it does not copy contact data into core Postgres or model prompts. Runtime
configuration maps brand 27 to its active core owner, project 10. The reader
rejects ownership drift, engagements, unsafe paths, malformed source rows and
invalid cursors. It displays fifty enquiries per page with escaped messages,
UTC dates, bounded queries and no-store headers. Other brands are unavailable
until an appropriate source is explicitly connected.

The website rejects malformed JSON, field types, request framing, cross-origin
browser submissions and incomplete bodies before persistence. Body reads have
an absolute ten-second deadline, server concurrency is capped at eight, and
internal notifications have a five-second timeout. Failed worker startup and
overload responses release resources. Internal notifications contain only a
lead ID; addresses and enquiry text remain in the source. A stored enquiry
does not imply marketing consent or authorize an email. The public form and
privacy copy state this boundary without promising a response within 24 hours.

Website credentials now load from the private central core environment.
Verification proved the existing notification credential identity and scope
were preserved without printing it. Both build contexts exclude local
environment files, data and Git metadata.

Acceptance: 145 dashboard tests passed (one additional PostgreSQL test skipped)
and sixteen website tests passed, including tests in both built images with
network access disabled. Independent review accepted the final source after
correcting truncated-body handling and bounded notification occupancy.
Synthetic desktop/mobile review at 1440/390 pixels passed overflow and script
checks; no real contact data was used for screenshots. Live GET-only checks
prove the owned inbox is available with no-store headers, the TrueApply inbox
is unavailable, and the public website/privacy/health routes return 200.
Nine deployed source files were byte-verified against canonical source.

Recovery images, previous committed source archives, a private consistent
SQLite backup, captured tasks and runtime verification are saved under
`/home/agency/backups/releases/dashboard-v2-enquiries-20261006T023522Z`.
The captured queue was empty. Agency worker was not restarted and remains
active, so this release created no worker restart orphans.

Dashboard image:
`sha256:3160d6a583e9d4c1467f433fbddecb687a7a1655137255b7396810aa0206456a`.
Deployden image:
`sha256:3b49d865c2b73d03d05499a3be1536a7b0be0e0bec53468454c3dc581082cf7b`.

Tracked read-only email verification task 456 refreshed TrueApply's provider
state at `2026-10-06T02:41:13.328993+00:00`: HTTP 403, authentication and sender
verification both false. No cause is inferred and no campaign was sent.

TrueApply campaign source preparation is at `ea485b7` in the isolated
`feat/dashboard-marketing-adapter` branch and [draft PR 42](https://github.com/itsbaldeep/trueapply/pull/42).
Shared approved contact limits now apply before native/campaign quota claims,
with transactional priority, exact retained snapshot identity and uncertainty
preserved. Acceptance passed 293 focused tests and 41 isolated PostgreSQL
checks. Migrations 034 through 037, API/worker recreation and source settings
remain undeployed. Source runtime approval and provider access remain pending;
marketing sending still requires its own exact approval. The full enterprise
goal remains active.

## Owned enquiry measurement, verified 2026-10-06 UTC

Deployden `3137b04`, Dashboard `5124dbe` and the core measurement module from
`85d59f0` are committed, pushed and deliberately deployed. Core runtime keeps
its existing release plus this byte-verified module; unrelated dirty source
was excluded. The worker restarted once after capturing an empty queue and
zero active campaign runs. The post-restart queue was empty, with no orphans.

Deployden now serves authenticated, read-only `/marketing/summary?days=28`.
Its dedicated core credential stays in the private central environment, mode
0600. Missing or invalid configuration disables the endpoint; unauthenticated
requests return 401 when configured. All summary responses are no-store.
The source reads only timestamps and internal notification flags, with a
one-second SQLite deadline. It returns enquiry and confirmed internal alert
counts, never contact data, marketing consent, signup or retention claims.

Connection setup task 457 records the brand-owned nonsecret references.
Measurement task 458 completed audit 67, captured at
`2026-10-06T03:02:49.084955+00:00`. Its 28-day window has zero enquiries and
zero confirmed internal alerts. Empty coverage stays empty and retention
remains unavailable. GA4, GSC, crawl, PageSpeed and first-party measurement
are available. The separate journey reports remain unavailable with
`journey rows unavailable` in all three lanes; this is a parsing/evidence gap
under investigation, not evidence of an access failure.

Shared schema 2 now accepts validated project stages or aggregate-only counts,
preserves generic coverage and legitimate zeros, and rejects malformed counts,
metadata and control characters. Dashboard reports and Lifecycle show source
labels and additional counts without rendering the legacy resume/signup funnel.
Optional retention counts are sanitized before exposure. Schema 1 remains
compatible. Source health and event timestamps are visible in the full report.

Acceptance: 149 dashboard tests passed, one PostgreSQL test skipped, including
the built image with networking disabled; 22 website tests passed in the host
and built image; 26 core measurement and seven isolated PostgreSQL workflow
tests passed. The broad core run initially lacked Flask in its test environment;
after installing the existing dashboard requirements, its affected PostgreSQL
module passed. Independent review accepted the final validation corrections.
Synthetic source-to-collector-to-dashboard and 1440/390-pixel report/Lifecycle
checks passed, with no overflow or script errors. Five container source files
and the deployed core module were byte-verified. Live report, Lifecycle, public
home and privacy routes returned 200; authenticated summary returned 200 and
unauthenticated summary returned 401.

Recovery: `/home/agency/backups/releases/dashboard-v2-measurement-20261006T025453Z`.
It holds private source/data/environment recovery, the previous core module,
task checkpoints and verification. The old website image reference was no
longer taggable, so its recovery image was rebuilt from the exact previous
committed source. New images:
Dashboard `sha256:72ab0d33d58cd35a706022e5ec6732bb89ea14a2738cb3873ce12845561c0ddb`;
Deployden `sha256:0aeda1cb1a3a1a8ad11c1e78e123cc0c4cad60fb837ef6a939c18e0a86c80b39`.
No new collection schedule, marketing publication, client runtime deployment
or campaign send was enabled.

## GA4 journey empty-response correction, verified 2026-10-06 UTC

The audit 67 follow-up established the source shape through three bounded,
read-only requests for the same owned property and window. Each provider
response had the expected dimension and metric headers, fixed GA4 report kind
and metadata, with empty rows and zero row count omitted from JSON. The parser
had incorrectly classified that valid empty shape as unavailable.
Google's [RunReportResponse reference](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/RunReportResponse)
and [ProtoJSON defaults](https://protobuf.dev/programming-guides/json/)
support the correction. Only sanitized header/presence flags were retained.

Core `62f4e11` is committed, pushed and deployed as one byte-verified
`growth_measurement.py` update after the enquiry batch. Exact headers and
fixed empty-response kind are required; wrong kinds, missing headers, null
rows and malformed or inconsistent row counts remain unavailable. Dimension
values must be bounded strings, with control characters, DEL and query/hash
values dropped. A valid empty report means no rows were reported, not proof
that every tracking event or tag is configured correctly.

Acceptance: 360 core tests passed, two skipped. Independent review accepted
the final parser after adding wrong-kind regressions. The worker restart
captured an empty queue and zero active campaigns; its post-restart checkpoint
was empty, with no orphans. The previous module and sanitized source evidence
are retained in the same private measurement recovery directory.

Tracked Deployden task 461 completed audit 68 at
`2026-10-06T03:11:12.615027+00:00`: all six sources are available, including
valid empty GA4 page/event/channel reports. TrueApply task 462 completed audit
69 at `2026-10-06T03:11:31.235806+00:00`: GA4, GSC, crawl, PageSpeed and journey
are available. Journey reports contain 34 page-path rows, eight event rows and
five channel rows, without truncation or dropped rows. Its first-party source
remains unavailable pending the separately requested source deployment.
Both measurement pages returned 200 and rendered the fresh journey evidence.
No client runtime, collection schedule, publication or campaign send changed.

## Channel identity and launch-kit bridge, verified 2026-10-07 UTC

Dashboard `abebc55` is deployed. Core `ca954bd` contributes additive migration
024 and one byte-verified runtime module, `marketing_channel_identity.py`.
The remaining core runtime stays at its previously documented scoped release.
There was no worker restart. Empty task/campaign queues were checked again
immediately before deployment and after verification.

Channel onboarding now applies suggested identity text to the local form only
after an explicit operator action. Avatar and banner selections retain exact
brand-owned work references and image hashes. Copy-only source revisions preserve
unchanged saved selections; new selections require the current source revision.
Reads reject symlinks, non-regular files, cross-brand references, oversized images,
invalid MIME types and changed bytes. Owner setup remains separate from provider
verification and publication approval.

The private launch ZIP includes saved identity, selected images, setup guidance
and complete bounded draft copy with work IDs, revisions and planned dates.
CSV formula escaping covers leading whitespace. Stale selected images and invalid
draft bodies fail closed instead of producing a misleading partial kit.

Acceptance: core suite 369 passed, two skipped; dashboard suite 156 passed, one
skipped, including the built image using the actual runtime script dependency.
Eight rollback-only PostgreSQL fixtures passed, proving selection, reload,
copy-only revision reuse, long copy export and changed-byte rejection. Independent
review accepted the final changes. Browser checks at 1440 and 390 pixels verified
explicit draft application and submitted asset references without overflow or
script errors. Live read-only checks returned 200 for all eight channel setup
pages and private Instagram launch kits for both brands 27 and 31. No actual
brand identity selections, account creation, publication or sends were performed.

Live dashboard image:
`sha256:7a33f066e7a4ab54c669a0fed29c80baba25bea430c8bb5b86f2cd686508952d`.
Runtime helper SHA256:
`ed8d7950181739b9fdb2799d18557d6bbddec284f99257dacdae45d3a326e189`.
Recovery checkpoints:
`/home/agency/backups/releases/channel-onboarding-20261006T033549Z`.
The prior running image was no longer taggable; rollback image
`agency-dashboard:before-channel-onboarding-20261006` was rebuilt from committed
dashboard source `5124dbe`, with current base/dependencies, rather than claimed
as an identical historical image. The additive schema and unused helper can
remain in place if reverting the dashboard.

Core recovery bundles were verified on October 6 and again before the October 7
container replacement. The latter bundle is
`/home/agency/backups/core/core-backup-20261007T062254Z.tar.gz`, SHA256
`f873c3d693c9c5c04d301a29641c950bff39e905edeff3a457ffb6236c8d5a4a`.
Its database, credentials, object storage and configuration components verified;
privileged host-state export was absent. The October 6 bundle includes verified
privileged host state. This release changed no host configuration.

The overall v2 goal remains active. External social/provider access and the
separately requested TrueApply retention source deployment remain unproven;
setup progress and successful kit export do not close those requirements.
