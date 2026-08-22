# ADR 0539: Bind write-back versions to one immutable proposal identity

- Status: Accepted
- Date: 2026-08-22
- Scope: E-825 governed connector write-back lifecycle

## Context

Write-back intents are persisted as append-only lifecycle versions. The prior
SQLite and PostgreSQL repositories enforced optimistic versioning and allowed
status adjacency, while the PostgreSQL database rejected UPDATE and DELETE.
However, a direct repository caller could construct an otherwise valid next
status whose connector, operation, payload digest, idempotency key, requester,
request time, or feature-policy decision differed from the persisted proposal.
The repository accepted that retargeted version because it compared only the
state transition. Direct INSERTs could also bypass lifecycle adjacency at the
database boundary.

That behavior was incompatible with the intended contract: approval and later
provider evidence must describe the exact mutation originally proposed. An
append-only row history is insufficient when consecutive rows are not bound to
one immutable business identity.

## Decision

Define the proposal identity as the canonical JSON values of:

- schema version, intent, tenant, and workspace identifiers;
- connector and operation;
- payload SHA-256 and idempotency key;
- requester and request timestamp; and
- the captured feature-policy decision.

Expose a deterministic `proposal_digest` over that identity. Every authorized
lifecycle version retains this digest even though its full evidence digest
changes as approval, acknowledgement, and compensation evidence is added.

Use one application-level transition validator in both repositories. It first
requires equal proposal digests and then requires an explicitly allowed
adjacent state. Add migration 42 for SQLite and Alembic 0089 for PostgreSQL.
Each migration audits all existing rows before installing an INSERT guard that
requires:

- JSON identity to match indexed columns;
- version 1 to start at `proposed`;
- every later version to have the exact predecessor;
- all proposal fields to equal the predecessor; and
- the predecessor/status pair to be an allowed transition.

The SQLite migration audit uses connection-local temporary state so it cannot
drop or overwrite a same-named table in the operator's main database.

The PostgreSQL UPDATE/DELETE refusal remains in the replacement trigger.
Historical migration definitions remain behaviorally stable: new safeguards
are installed only by migration 42/0089. The API adds `proposal_digest` as an
additive response field so reviewers can correlate every version without
discarding the full version digest.

## Security and financial integrity

This prevents approval substitution, cross-operation retargeting, payload hash
replacement, idempotency-domain changes, requester rewriting, and invalid
direct INSERT state jumps. Migration audits fail closed instead of silently
normalizing or accepting pre-existing drift.

No financial payload is persisted by this contract, no provider is contacted,
and no autonomous approval is introduced. It does not establish provider
authenticity, live accounting posting, distributed receiver idempotency, or
production write-back assurance.

## Compatibility

Valid existing lifecycle histories and repository/API callers remain valid.
`proposal_digest` is additive. SQLite advances from schema 41 to 42 and
PostgreSQL advances from Alembic `0088_pg_currency_snapshot` to
`0089_pg_writeback_identity`. A database containing a retargeted or invalid
history is deliberately refused and requires evidence-preserving human
investigation before migration.

## Rollback

The PostgreSQL downgrade restores the preceding UPDATE/DELETE-only trigger and
does not mutate history. SQLite migrations are forward-only under the existing
local migration contract. Do not bypass a failed audit by deleting or editing
history. Corrective recovery must preserve the original database, document the
invalid versions, and create an independently reviewed migration or restore
path before retrying.
