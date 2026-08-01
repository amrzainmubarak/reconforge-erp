# ADR 0142: Extract the governed finance core as one application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Chart, account, dimension, journal, entry lifecycle, and trial-balance behavior
was implemented directly in a SQLite-bound Platform service. Splitting only
the reads or ledger rows would permit future adapters to diverge on balance,
currency precision, period, SoD, immutability, audit, and transaction rules.

## Decision

Define one typed, connection-free Application protocol covering all 18 public
use cases. Move the existing implementation unchanged to
`SQLiteFinanceCoreRepository`, and retain `FinanceCoreService(connection)` as a
SQL-free compatibility facade. Keep the historical private integrity-validation
test seam temporarily so the database-lock and rollback proof remains valid.

Exact line values cross the Application boundary as text/mappings without
float conversion. Validation, voiding, and entry creation continue to execute
their policy checks and evidence effects inside the SQLite adapter's existing
transaction boundaries.

## Consequences

- A future PostgreSQL adapter can implement one complete financial contract.
- Existing API, CLI, inventory, and direct Python callers keep their constructor,
  method names, defaults, result type, and exception behavior.
- The Application layer imports neither SQLite nor Infrastructure.
- PostgreSQL parity is not established by this extraction.

## Rollback

The facade can point back to the prior implementation without a schema or data
migration. Restoring implicit float conversion, partial financial commits, or
weaker validation is not an acceptable rollback.
