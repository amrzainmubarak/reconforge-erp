# ADR 0102: Extract operational diagnostics behind application ports

- Status: Accepted
- Date: 2026-07-27
- Scope: P1-PLAT-001

## Context

The CLI operational health, job, and error views were implemented directly in
a connection-owning Platform service. SQL, audit verification, migration
inspection, and output composition were inseparable even though the public
result contains only sanitized operational metadata.

## Decision

Move result composition to `OperationsApplicationService`. It consumes an
`OperationsRepositoryProtocol` and a `MigrationStatusProvider`; it imports no
database or infrastructure module. Put SQLite schema validation, bounded audit
verification, migration adaptation, counts, and ordered record reads in
`SQLiteOperationsRepository`. Retain `platform.OperationsService` as a thin
connection-based compatibility adapter for existing CLI callers.

## Consequences

The compatibility API and output keys remain unchanged. The Platform class no
longer executes SQL or makes health decisions. A fake-port test proves the
application use case without a database; a migrated SQLite database proves the
legacy entry point and record shapes. This adds no PostgreSQL adapter and does
not complete P1-PLAT-001 or P1-PLAT-002.

## Reversal

The compatibility class can temporarily inline the previous reads without a
schema or CLI migration. Such reversal must also restore the inventory status
and tests and would increase the measured coupling count.
