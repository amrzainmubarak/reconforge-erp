# ADR 0801: Scoped receivables drafts and independent browser approval

Date: 2026-10-03

Status: Accepted

## Context

React needs a real financial write journey using the existing PostgreSQL API,
authenticated scope, exact amounts and independent review. Customer creation is
an unversioned upsert, and AR-only users cannot read an authoritative currency
precision registry. These contracts constrain the initial browser workflow.

## Decision

Expose `/receivables` for selecting an existing customer, creating a single-line
invoice draft, submitting its expected version and approving with a separate
human reviewer. Share the browser session and obtain permissions and workspace
grants from `/api/v1/auth/me`. Use same-origin HttpOnly cookies and CSRF headers.
Discard private state and stale responses on session revision, expiry or scope
changes. Server checks remain authoritative.

Keep quantities as decimal text and calculate previews with BigInt. Display
explicit integer minor units without guessing currency scale. JSON integers must
be exactly representable (at most 9007199254740991); quantities have at most12
total digits and intermediate products stay below10^28 to respect the existing
backend contract. Reject unsafe or inconsistent monetary responses. Oversized
input is rejected, never truncated into a different valid amount.

Freeze the draft payload and its idempotency key when the outcome is unknown so
the human can retry the same request. Do not automatically repeat transitions.
After an uncertain transition, reload the server record for review. Use expected
versions, explicit confirmation and creator/approver separation.

Provide Arabic/English text, RTL, responsive layouts, focusable error feedback
and a named keyboard-accessible scrolling invoice table. On narrow viewports,
arrow keys scroll the region and Tab/Enter reach and activate review.

## Verification and boundaries

Repository Playwright exercised actual HTTPS and a separate synthetic PostgreSQL
database at migration0094. Quantity1.25 at1001 minor units rounds to1251; tax125
produces1376 total. Persistence is Draft v1, Submitted v2, Approved v3, with
different creator/approver identities, three audit events and three outbox events.
The sibling tenant has no invoices. Self-approval, absent CSRF, missing workspace,
foreign tenant and stale-version attempts are denied. Retained source hashes and
commands are in [browser evidence](../execution/RECEIVABLES_UI_2026-10-03.json)
and [persistence evidence](../execution/RECEIVABLES_UI_PERSISTENCE_2026-10-03.json).

The in-app browser was unavailable; no inspection through it is claimed.
Receipts, customer creation, grouped aging, inventory and GL posting remain
separate journeys. This path does not complete the trade cycle or establish
production readiness. Rollback removes the React route; financial records remain
accessible through the existing API and audit trail.
