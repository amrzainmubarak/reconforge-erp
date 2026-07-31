# ADR 0143: Extract governed inventory state as one application boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Units of measure, items, warehouses, locations, lots/serials, movements,
on-hand balances, and control exceptions were implemented in a SQLite-bound
Platform service. Partial extraction would let future adapters diverge on
quantity scale, stock direction, period, tracking, negative-stock, posting,
voiding, and evidence behavior.

## Decision

Define one typed, connection-free Application protocol covering all 19 public
use cases. Move the existing implementation to
`SQLiteInventoryCoreRepository`, and retain `InventoryCoreService(connection)`
as a SQL-free compatibility facade.

Quantity strings and movement lines cross the port without float conversion.
Scaled-integer conversion, movement integrity, lot/serial constraints,
period/location policy, transaction ownership, audit, and outbox behavior stay
inside the SQLite adapter. Retain the historical connection, balance-read, and
movement-integrity fault-injection seams so transaction and redaction tests
continue to exercise the same boundaries.

## Consequences

- Application imports neither SQLite nor Infrastructure.
- Existing API, CLI, planning, valuation, reversal, and direct Python callers
  retain constructor, methods, defaults, result type, and output shapes.
- The repository inventory now records three direct-SQLite services and three
  partial repositories.
- PostgreSQL inventory parity is not established by this extraction.

## Rollback

No schema or stored data changed. The compatibility facade can be redirected
without data migration. Restoring float conversion, partial movement effects,
or weaker inventory invariants is not an acceptable rollback.
