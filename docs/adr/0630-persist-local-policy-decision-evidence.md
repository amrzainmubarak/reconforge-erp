# ADR 0630: Persist local policy-decision evidence in the audit ledger

- Status: Accepted
- Date: 2026-08-25
- Scope: Local SQLite authorization paths

## Context

Central policy decisions already produce a closed, redacted, digest-bound
`PolicyDecisionEvidence` object. Previously `audit_policy_decision` emitted
that object only through structured logging. Logs can be rotated, dropped, or
separated from the database backup that contains the governed action, so this
was insufficient for local replay and recovery evidence.

ReconForge already has an append-only, hash-chained SQLite audit ledger with
tamper verification and backup support. The local policy path can use it
without changing the server-profile PostgreSQL contract.

## Decision

Add an optional SQLite connection to `audit_policy_decision`. When supplied,
append one `authorization.policy_decision` event whose object ID and
`after_hash` are the policy evidence decision digest. Store only the closed
policy evidence plus a request-ID digest; never store the raw policy context,
amount, tenant, workspace, object, or permission contract in event metadata.
Use the existing audit ledger transaction, chain hash, immutable triggers, and
verification/backup mechanisms.

Local API dependencies, platform authorization, workflow transitions, and
Studio authorization pass their existing SQLite connection. Server workers,
PostgreSQL scoped exports, and other callers without a local connection retain
the structured-log boundary and are not represented as durable local events.

## Consequences

Local policy evidence becomes queryable, tamper-evident, and included in the
existing local backup/restore surface. A failure to append through a supplied
connection raises the existing audit-ledger error and therefore fails the
governed local operation closed. This does not prove server-side append-only
storage, external IAM enforcement, distributed invalidation, or production
authorization effectiveness.

## Rollback

Revert the optional persistence argument and caller wiring if the local audit
schema is replaced. Keep the structured evidence and context-digest contract;
rollback must not reintroduce raw-context logging or silent audit loss.
