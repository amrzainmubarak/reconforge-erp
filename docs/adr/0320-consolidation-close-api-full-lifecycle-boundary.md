# ADR 0320: Expose the governed consolidation-close lifecycle through one API boundary

- Status: accepted
- Date: 2026-08-04

## Decision

Expose the existing backend-neutral close lifecycle through strict authenticated
routes for:

- replay-verified run preparation;
- independent run approval and control-journal posting;
- reversal request and independent reversal approval; and
- period lock and independent reopen.

Every mutation uses an optimistic `expected_version` and bounded reason. The
route chooses SQLite in local mode or the request-scoped PostgreSQL repository
in server mode, binds the actor to the authenticated principal, and verifies
returned workspace scope before response. Worksheet ingress is reconstructed
through `verify_consolidation_worksheet_payload`; arbitrary recalculation or
raw journal payloads are not accepted.

## Rationale

The period-write slice left a gap between entering a close period and the
already-tested repository lifecycle. Exposing the existing application port
closes that gap without adding a second posting engine, bypassing SoD, or
pretending the control journal is a statutory general ledger.

## Evidence and boundary

The local API contract executes prepare → approve → post → reversal request →
reversal approve and lock → reopen with distinct users and version checks. The
live PostgreSQL server-identity fixture executes authenticated prepare,
approval, posting, lock, and reopen with scoped users and step-up. The result is
synthetic single-node control-journal evidence. It does not claim statutory
consolidation, legal-book posting, live ERP/bank mutation, independent HA/DR,
or production readiness. PostgreSQL currently represents a reopened period as
`Open`, while SQLite exposes `Reopened`; that compatibility difference remains
explicit and is not silently relabeled.

## Rollback

Remove the lifecycle routes, request models, tests, inventory update, docs, and
manifest entry. No schema migration rollback is required because the existing
repositories and tables are reused.
