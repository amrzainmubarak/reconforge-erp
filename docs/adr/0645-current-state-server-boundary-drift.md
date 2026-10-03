# ADR-0645: Synchronize current-state server-boundary wording

- Status: Accepted
- Date: 2026-08-26
- Scope: E-952

## Context

`docs/architecture/current-state.md` still described reconciliation and most
domain routes as SQLite-only or not PostgreSQL-backed after the repository had
added bounded PostgreSQL server adapters through the current Alembic head.
That wording obscured the actual boundary and conflicted with the execution
evidence for the authenticated server API.

## Decision

Describe the PostgreSQL Server Profile as a bounded set of explicit adapters,
name the current revision head `0090_pg_writeback_observations`, and state the
remaining limits: unsupported routes either retain explicitly supported local
compatibility or fail closed, and the repository is not a complete ERP,
statutory posting system, external-provider lifecycle, or production platform.
Keep the Local Profile and tenant-local compatibility statements intact.

## Consequences

- Architecture readers see the current implemented server boundary without
  turning bounded evidence into a completeness claim.
- Future adapter work must update the same current-state paragraph and the
  Claims Evidence Matrix together.
- This is documentation-only; no runtime, migration, or persisted-data change
  is introduced. ADR 0644 remains the health endpoint decision.

## Rollback

Revert the current-state wording and this ADR. No data or schema rollback is
required.
