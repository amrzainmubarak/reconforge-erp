# ADR 0631: Persist server policy provenance through a tenant-scoped audit sink

- Status: Accepted
- Date: 2026-08-25
- Scope: PostgreSQL server authorization dependencies

## Context

`audit_policy_decision` already creates a closed, redacted, digest-bound
`PolicyDecisionEvidence` object. The local SQLite path persisted that evidence
in the immutable local ledger, but server-mode authorization dependencies had
only a structured-log boundary. A request dependency cannot safely retain a
PostgreSQL connection for the later business transaction, so direct connection
passing would either leak infrastructure into the policy engine or couple the
authorization decision to the wrong transaction.

The server profile already has the tenant-scoped `domain_audit_events` chain,
RLS, immutable trigger, and `PostgresAuditEventRepository`. The missing piece
is a narrow adapter that acquires a short independent tenant transaction after
the policy engine has produced its evidence.

## Decision

Add two explicit persistence options to `audit_policy_decision`:

1. The existing SQLite connection for local mode.
2. A backend-neutral append-only repository for direct adapter use, or a
   `PolicyAuditSink` for request-scoped adapters that must open their own
   transaction.

The options are mutually exclusive and the default remains structured logging.
Server API dependencies use a sink that calls
`execute_postgres_policy_audit`. That boundary obtains the configured identity
factory, applies the request tenant scope through `PostgresTenantBoundary`, and
appends one `authorization.policy_decision` event to
`domain_audit_events`. The event binds `object_id` and `after_hash` to the
decision digest and stores only the closed evidence plus the evidence request
digest. It never stores the raw tenant, workspace, amount, permission, or
request ID in metadata.

Authorization provenance is committed independently of the subsequent business
mutation. If the server audit backend is unavailable, the adapter returns a
safe `503 authorization_audit_unavailable`; it does not silently downgrade the
server path to logging once the server audit profile is configured.

## Consequences

Server API authorization attempts become durable and tenant-isolated in the
existing domain audit chain, and the audit-administration browser can verify
that chain. Local SQLite behavior remains unchanged. The policy engine remains
backend-neutral and does not import PostgreSQL transaction code.

The focused proof currently uses a synthetic repository/sink and static caller
contracts; live PostgreSQL execution, non-privileged role grants, RLS runtime,
external IAM authenticity, distributed cache invalidation, and production
effectiveness remain open and are not claimed by this ADR.

## Rollback

Remove the server sink wiring and retain the existing closed evidence/logging
contract. Do not reintroduce raw-context logging or silently suppress a failed
configured audit write.
