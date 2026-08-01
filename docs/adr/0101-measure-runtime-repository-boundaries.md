# ADR 0101: Measure runtime repository boundaries before migrating services

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-001

## Context

Repository protocols existed before Phase 1 but were not used by active
application code. Three platform services accept partial repositories while
retaining a direct SQLite connection for schema, authorization, audit, outbox,
or other operations. Counting protocols or constructor parameters therefore
overstates backend neutrality.

## Decision

Maintain an exact, AST-tested inventory of every `*Service` under
`reconforge/platform` and `reconforge/application`. Classify a service as:

- `direct_sqlite` when its active boundary imports SQLite directly;
- `partial_repository` when it delegates some persistence but still imports
  SQLite directly; or
- `backend_neutral` only when it imports neither SQLite nor infrastructure.

Adapters remain infrastructure concerns and do not weaken the application
classification. Every migration must atomically update implementation,
behavioral tests, and inventory counts.

## Consequences

The baseline is 17 direct-SQLite platform services, three partial-repository
platform services, and one backend-neutral application service. P1-PLAT-001
cannot close while that measured runtime surface remains coupled. This is a
source-boundary measurement, not PostgreSQL parity or production-readiness
evidence.
