# ADR 0452: Professional invoice/payment dual-mode persistence and API boundary

- Status: accepted
- Date: 2026-08-08
- Scope: local-first, immutable evidence persistence for the professional control

## Decision

Add SQLite migration 36 and migration-backed PostgreSQL persistence (revision
0081) for `professional.invoice-payment` as a bounded dual-mode persistence
boundary. The report is opt-in from the CLI and exposed through authenticated
API routes in two explicit modes:

- Local mode (no server profile): SQLite-backed run/list/read with workspace
  scope.
- Server mode (server profile): PostgreSQL-backed run/list/read with server
  tenant/workspace/organization/legal-entity scope and enforced authorization.

`POST /api/v1/professional/invoice-payments` requires `finance_core.manage` in
local mode and scope-bound `finance_core.manage` in server mode.
`GET` list/read routes use the equivalent finance read/manage/validate any-of
policy with the same explicit scope checks.

Both modes enforce idempotent writes for the same workspace/decision digest,
reject conflicting artifact digests, malformed JSON, nested replay changes, and
metadata drift, and include immutable trigger + backup/restore table coverage.

Server mode is bounded, not provider-integrated: it requires server-scope
selection, does not call providers, and keeps `network_dispatch: disabled`.

## Non-goals and rollback

This slice does not add provider authentication, payment initiation, revenue
recognition, receivables allocation, write-back, distributed job execution,
HA/DR, or production availability claims. Rollback is a versioned migration
rollback plus removal of the persistence slice routing, tests, and adapters;
no external service or credential behavior is changed.

## Evidence boundary

Evidence includes local-mode SQLite/API/CLI execution and server-mode
PostgreSQL repository contract tests over synthetic fixtures. Focused tests cover
idempotency, scope isolation, replay/tamper refusal, migration gating,
backup/restore, and API contract parity where implemented. Live PostgreSQL/Redis
and hosted native backup tools remain environment-dependent and are not claimed as
production assurance by this ADR.
