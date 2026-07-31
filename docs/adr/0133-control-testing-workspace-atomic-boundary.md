# ADR 0133: Workspace-safe atomic control-testing boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Control testing combined library ingestion, test planning, results,
remediation, exception creation, audit, and SQLite operations in one Platform
service. Ineffective results used the literal `default` workspace for their
unified exception even when the persisted test plan belonged elsewhere.

## Decision

Define one complete application protocol for all public control-testing use
cases. Move SQLite behavior into `SQLiteControlTestingRepository` and preserve
`ControlTestingService(connection)` as a SQL-free compatibility facade. When a
result is ineffective, resolve the plan's stored workspace ID to its canonical
workspace name and call the SQLite exception adapter with autocommit disabled.
Result insertion, plan status, exception, and audit therefore share one
transaction and explicitly roll back on handled failure.

## Consequences

- Non-default workspace results no longer leak exceptions into `default`.
- Existing CLI, demo, and Python call shapes remain compatible.
- The application layer no longer imports SQLite or infrastructure.
- PostgreSQL parity, RLS runtime evidence, and supported scale remain open.
- No data migration is required; existing incorrectly scoped historical rows
  require an explicit separately authorized reconciliation if encountered.
