# ADR 0545: Prove write-back recovery and compensation parity on PostgreSQL

- Status: Accepted
- Date: 2026-08-22
- Scope: E-831 provider-neutral recovery and compensation checkpoints

## Context

E-660 proves a crash window between synthetic provider acceptance and
acknowledgement persistence using SQLite plus an injected status lookup.
E-825--E-830 establish immutable proposal identity, PostgreSQL lifecycle
guards, receiver idempotency, and bounded receiver failover. The remaining
server-backed gap is the full recovery and compensation lifecycle: the
application must be able to persist the original acknowledgement after a
process exits, then request and complete a separately keyed compensation after
another response-loss window without producing a second mutation or changing
the proposal identity.

## Decision

Add one disposable, provider-neutral matrix over exact PostgreSQL 16.14 and
17.10 images and a same-input SQLite reference. The runner stages
`proposed -> approved -> dispatched`, records a synthetic provider acceptance
and exits before acknowledgement persistence, recovers with the original
idempotency key, requests compensation under a distinct actor, records a
synthetic compensation acceptance and exits before completion persistence, and
recovers with `<original-key>:compensation`. Both replay paths must be
idempotent, the six-version append-only history must match SQLite, tenant scope
must not leak, direct UPDATE/DELETE must fail, and the application role must
have no superuser, create-database, create-role, replication, or BYPASSRLS
privilege.

The matrix report is schema-closed, digest-bound to the lifecycle sources,
migration, policy, runner, and base commit, and is run in CI before the live
server-boundary tests. Its synthetic acceptance markers are explicitly not
provider status API evidence.

## Rationale

The provider mutation and its durable acknowledgement are separate failure
domains. Recovery must ask the provider about the original identity rather
than POST again. Compensation is a new, separately allowlisted mutation with
its own idempotency key; conflating it with the original key could silently
turn a reversal into a duplicate original operation. Comparing canonical
SQLite/PostgreSQL histories makes the repository contract backend-neutral
without claiming vendor interoperability.

## Consequences and limits

- The lifecycle evidence becomes server-backed on both declared PostgreSQL
  versions and includes real child-process crash windows for acknowledgement
  and compensation.
- No payload bytes, credentials, provider response bodies, accounting amounts,
  or external network calls are retained by the matrix.
- This remains one disposable PostgreSQL node per version on one Docker
  Desktop host. It does not prove live provider behavior, status endpoint
  authenticity, accounting posting, settlement, cross-host quorum, automatic
  failover, production exactly-once, or production RPO/RTO.
- Rollback is removal of the runner, report, schema, test, ADR, CI step, and
  manifest entries; no product migration is introduced.
