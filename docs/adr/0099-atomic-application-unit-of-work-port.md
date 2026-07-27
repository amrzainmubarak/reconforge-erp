# ADR 0099: Atomic application unit-of-work port

- Status: Accepted
- Date: 2026-07-27
- Owners: Platform Architecture, Financial Correctness, Security
- Decision scope: First P1-PLAT-001 vertical slice

## Context

Phase 0 introduced repository protocols for workspaces, periods, and audit
events, but no runtime application service consumed them. Concrete
repositories committed independently and active platform services commonly
accepted `sqlite3.Connection`. A structural protocol test could therefore pass
while an application use case remained backend-coupled or partially committed.

Workspace bootstrap is financially relevant because every later entity,
period, reconciliation, and evidence object inherits its scope. Creating a
workspace without its intended first period or without append-only audit
evidence leaves an incomplete control boundary.

## Decision

Introduce `DomainUnitOfWorkProtocol` as the transaction-owning application
port. Its first use case creates one workspace, one initial period, and two
audit events through repository protocols, followed by one explicit commit.

The SQLite adapter:

- owns `BEGIN IMMEDIATE` and refuses ambiguous pre-existing transactions;
- supplies workspace and period repositories with per-call autocommit disabled;
- uses the existing append-only audit implementation inside the same active
  transaction;
- rolls back when the context exits without commit or any operation fails;
- never exposes its connection to application code.

Existing direct repository construction retains autocommit by default to avoid
an implicit compatibility break. Application validation rejects blank,
non-printable, overlong, or non-canonical date input before transaction start.

## Consequences

The first application boundary is backend-neutral at the type/import level and
has an atomic SQLite implementation. An injected failure on the second audit
append proves that the workspace, period, first event, and audit-chain head all
roll back.

This does not make the existing platform backend-neutral. P1-PLAT-001 remains
in progress until the declared application-service inventory is migrated and
contract-tested. PostgreSQL behavior belongs to P1-PLAT-002; no distributed
transaction or exactly-once transport claim is introduced.

## Compatibility and migration

There is no CLI, API, schema, or serialized-artifact change. Existing
`WorkspaceRepository(connection)` and `PeriodRepository(connection)` callers
continue to commit each successful create. New application code should receive
a unit-of-work factory instead of a connection.

## Rollback

Remove the application and SQLite unit-of-work modules, remove the new protocol
exports, and restore the repository constructors. No database migration or
persisted data rollback is required. Do not preserve an application service
that performs the four writes without one transaction.
