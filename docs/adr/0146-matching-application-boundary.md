# ADR 0146: Extract deterministic matching as one application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

File execution, benchmark jobs, job/results reads, and pure record matching
were exposed by one SQLite-bound Platform service. The same implementation owns
candidate indexes and budgets, exact Decimal parsing, reference normalization,
record identity, deterministic selection, ambiguity, lineage, rule JSON,
audit, outbox, and persisted results.

## Decision

Define one typed, connection-free Application protocol for all six public use
cases. Move the engine and persistence implementation to
`SQLiteMatchingRepository`; retain `MatchingService(connection)` as a SQL-free
compatibility facade. Move the public immutable normalization and result types,
plus the legacy identity-policy constant, to Application and re-export them.

Exact tolerances remain Decimal/object inputs and record mappings cross the
port without conversion. Candidate budgets and range-index helpers stay with
the engine. Fault injection, security inventories, and budget tests reference
the adapter that owns the relevant behavior. Retain the historical connection
read seam and private range-index imports for deterministic regression tests.

## Consequences

- No Platform service remains classified direct-SQLite.
- Three inventory services remain partial repositories and keep
  P1-PLAT-001 open.
- Application imports neither SQLite nor Infrastructure.
- Existing CLI, demo, workers, Reconciliation-as-Code, strategy adapter, and
  Python callers retain the public contract.
- PostgreSQL matching execution parity is not established by this extraction.

## Rollback

No schema or stored data changed. The facade can be redirected without data
migration. Restoring float financial parsing, unbounded candidates,
non-deterministic selection, partial evidence, or weaker ambiguity behavior is
not an acceptable rollback.
