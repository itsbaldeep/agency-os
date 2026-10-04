# Brand-owned campaign adapter contract

Agency OS keeps campaign drafts, validated policy, human approval, schedule
metadata, and digests. The brand's source system keeps recipients, consent,
suppression, frequency limits, provider credentials, and its durable outbox.

The source adapter exposes three localhost endpoints:

- `POST /marketing/campaigns/preview`
- `POST /marketing/campaigns/dispatch`
- `GET /marketing/campaigns/receipt?idempotency_key=<64 hex characters>`

The core preview request contains the brand ID, work-item ID and revision,
reviewable message and policy, and their digests. A valid preview returns aggregate counts,
source revision, audience digest, generation time, expiry (at most seven days),
and `provider_ready: true`. It must contain no addresses or recipient IDs.

Approval freezes the exact message, policy, audience digest, source revision,
configuration digest, preview expiry, planned send time, approval digest, and
idempotency key. Planned dates do not authorize delivery. Dispatch is accepted
only with this frozen approval contract.

The contract also binds the preview's eligible and suppressed counts. Receipt
eligibility and delivered counts cannot exceed the approved eligible audience.
Receipt suppression counts describe new exclusions since preview, rather than
the people already excluded from that preview. A completed delivery receipt
accounts for the entire approved audience as delivered or newly suppressed.

Digests detect changes; they do not grant human authorization. The core executor
must require a durable exact approval record before using the dispatch transport.
The prepared executor stores that approval in `marketing_campaign_runs` (migration
023). Only due approved rows become tracked dispatch tasks. The worker checks the
current draft revision and ownership, commits a dispatch claim before calling the
source, and never retries an uncertain run through POST. The dashboard provides
preview, exact review, approval, cancellation before dispatch, and receipt checks.
These additions were deliberately deployed on 2026-10-04. Both brand sources remain
unconfigured. Live desktop/mobile checks confirmed disabled delivery controls and
zero campaign runs; no campaign was approved or sent.

Verification uses a rollback-only PostgreSQL fixture for source configuration,
preview, exact approval digest rejection, duplicate approval, scheduling, dispatch,
receipt reconciliation, cancellation persistence, stale draft blocking, cross-brand
isolation, classification boundaries and cross-origin rejection. Worker unit tests
also cover commit-before-POST and post-claim persistence failure. The fixture does
not prove external transaction visibility or concurrent source outbox execution.

Before dispatch, the source must freshly recheck consent, suppression, service
trigger, cooldown, and frequency caps. The eligible audience may shrink after
preview, never grow. The source outbox must lease rows, enforce the
idempotency key, and treat ambiguous provider responses as `uncertain` without
automatic resend. `accepted` means durably queued in the source outbox, not
delivered.

The transport accepts only a localhost origin with an explicit port, uses a
fixed timeout and response limit, rejects redirects and proxies, and obtains
the source credential through the owned-reference reader. TrueApply does not
yet implement these endpoints.
