# ADR 0149: Extract inventory planning as one application boundary

- **Status**: Accepted
- **Date**: 2026-07-28

## Context

Count lifecycle, exact counted quantities, adjustment movements, maker-checker
approval, reorder rules/signals, audit, and outbox effects remained coordinated
by a SQLite-bound Platform service despite a partial row repository.

## Decision

Expose all thirteen use cases through a typed, connection-free Application
port. Keep schema checks, transactions, count invariants, adjustment effects,
reorder calculation, and evidence in a SQLite adapter. Preserve historical
constructors, constants, summaries, repository injection, and imports through
SQL-free compatibility facades.

## Consequences

The measured Platform inventory reaches zero direct-SQLite and zero partial
repositories, with twenty compatibility facades and twenty-six neutral
Application services. This establishes the SQLite contract boundary only;
PostgreSQL parity remains separately gated.

## Rollback

No schema or stored data changed. A contract-compatible adapter can replace
SQLite without data conversion; weakening quantity, SoD, adjustment, or
atomicity invariants is not acceptable.
