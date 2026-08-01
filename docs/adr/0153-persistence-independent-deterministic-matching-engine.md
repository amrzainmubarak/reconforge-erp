# ADR 0153: Execute deterministic matching without a local database

- Status: Accepted
- Date: 2026-07-28

## Context

The matching Application port separated callers from SQLite, but the complete
algorithm still lived inside `SQLiteMatchingRepository`. Hosted PostgreSQL
reconciliation therefore created and migrated an in-memory SQLite database
solely to obtain the algorithm and its currency lookup. This was hidden
cross-backend coupling and made hosted execution depend on an unrelated local
schema.

## Decision

Move candidate generation, exact financial parsing, normalization, budgets,
minimum-cost assignment, ambiguity, and explanation construction into
`DeterministicMatchingEngine` under the reconciliation layer. Define separate
typed ports for currency precision and pure matching. The engine imports no
database or Infrastructure module.

SQLite retains job, rule, result, audit, and outbox persistence and delegates
calculation to the engine. The PostgreSQL reconciliation worker invokes the
same engine directly and resolves precision through the versioned offline
`CurrencyRegistry`; all hosted input, checkpoint, result, exception, audit, and
outbox persistence remains PostgreSQL-owned.

Candidate limits are explicit engine constructor policy. SQLite passes its
historical module-level values to preserve the supported fault-injection seam.

## Consequences

- Hosted matching no longer imports `sqlite3`, creates an in-memory database,
  or runs local migrations.
- SQLite delegation, direct-engine execution, and input permutation produce
  identical immutable output values in focused parity tests.
- Unknown currencies remain explicit data-quality exceptions and currency
  precision is never inferred as two decimal places.
- The complete six-method PostgreSQL `MatchingRepositoryProtocol` remains
  absent. This ADR proves the hosted worker execution boundary, not all
  file-oriented Application repository methods or a current live PostgreSQL
  run.

## Rollback

SQLite can temporarily host the engine again without a data migration, but
restoring the PostgreSQL worker's in-memory SQLite dependency is not an
acceptable long-term rollback. No stored schema changes are introduced.
