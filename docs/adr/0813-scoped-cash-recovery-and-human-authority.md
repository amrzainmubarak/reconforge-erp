# 0813: Scoped cash recovery and human-governed receipt actions

Status: accepted for scoped AR cash writes and verified recovery, 2026-10-03.

## Observed failure

A real PostgreSQL0097 authenticated receipt creation returned200, but no receipt
GET route existed and cached retries returned503. The database's JSONB driver
returned a mapping; the replay decoder converted it with str(dict), producing
invalid JSON. Exact same-payload retry and a direct decoder error independently
reproduced this failure. No cross-entity leak was established by that run.

## Decision

Add closed authenticated receipt/invoice/customer read-back and bounded receipt
pagination over both adapters. Receipt creation idempotency uses a versioned
canonical request/response envelope. A repeat must bind to the original request
and re-read its authoritative object under the current selected scope before
returning cached data. Historical response-only caches remain readable through
object GET; their missing request identity is not invented for mutation replay.

Derive an omitted receipt hierarchy from the authoritative customer. Reject
explicitly conflicting workspace/organization/entity or currency. Allocation
requires equal receipt/invoice workspace, organization, entity, customer and
currency plus exact available amounts and expected version. Legacy scope is not
silently filled from a label or user-selected code.

Central policy v3 requires an authenticated human and recent reauthentication
only for the internal receivables.receipt post/allocate actions. The existing
receivables.manage capability remains available to service draft/import paths;
the browser cannot choose an alternate internal object/action classification.
Original closed v1/v2 evidence and its digests remain verifiable. Existing server
cash clients receive an explicit403 until they satisfy the human assurance rule.
Community trusted local behavior remains compatible.

The React AR workspace uses these actual APIs. It parses bounded exact minor
units with BigInt before permitted API integer serialization, refreshes customer
and invoice authority without guessing identities from a truncated list, and
supports partial allocation. An uncertain creation response retains the exact
command key/content. An uncertain allocation uses authoritative receipt/invoice
read-back and expected-version state; it does not create a new cash operation
until the outcome is resolved. Scope/session changes clear private financial
state. English/Arabic, RTL, mobile and keyboard paths are acceptance gates.
The parent invoice controls are also locked during pending/unknown cash outcomes:
refresh or draft replacement cannot unmount and discard that exact request.
New invoice and receipt evidence use accessible disclosures to keep the cash
workflow visible. Monetary display remains explicitly in exact minor units;
historical AR precision is not inferred from a current currency code.

## Evidence and limits

Before runtime reports retain the successful initial write, GET404, same-payload
503 and direct decoder error, with owned database removal. Real password/session
and service-token PostgreSQL tests exercise step-up, scoped reads, payload
conflicts, narrowed-entity cache denial, partial allocation recovery and persisted
audit/outbox. The frozen production build passes the final actual HTTPS browser
journey in19.9s on PostgreSQL0097: one1376minor receipt and total1376 allocation,
invoice Paid/version6, receipt/version3, customer exposure0, and exactly one
posted/two allocated event in both audit and outbox. Source hashes remain
unchanged and the owned database is removed. English/Arabic keyboard, automated
accessibility and390px overflow checks pass.159 web tests, typecheck/build,
16 general browser tests,95 broad AR tests and two dedicated cash tests pass.
RECEIVABLES_CASH_2026-10-03.json preserves the original codec failures, first
harness/source-binding failure, aborted coordination run and failed Arabic
selector attempt; none is relabeled as a pass. The final selector repair changes
test localization lookup only. The later full regression has its own source.
These receipts are AR/cash subledger effects; operational GL integration remains
a separate posting/trade contract. No real customer, external bank settlement,
business ROI or independent auditor acceptance is claimed.

Rollback removes additive reads/UI without deleting financial records. Retain
versioned request envelopes and historical policy evidence. Removing cash guards
restores weaker authority; no migration should relabel legacy financial scope.
