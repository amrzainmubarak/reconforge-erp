# ADR 0386: Server identity close fixture installs intercompany evidence schemas

- **Status**: Accepted
- **Date**: 2026-08-06
- **Decision owners**: ReconForge maintainers

## Context

The PostgreSQL server-identity integration fixture exercises consolidation
close, PPA, ownership, write-back, emergency-access, and scope workflows. The
close repository replay-verifies intercompany evidence on every run transition,
including runs that contain no intercompany eliminations. The fixture installed
only part of the migration dependency graph, so a fresh database lacked the
domain workspace, application master-data, approval, emergency-access,
service-account, scope-authority, audit-ledger, and intercompany evidence
relations required by the route. The first missing-relation error was translated
by the API boundary into a misleading 503 `consolidation_close_unavailable`.

## Decision

Install the shared dependency schemas in migration order: domain foundation,
master-data application, identity, approvals, emergency access, service
accounts, scope authority, intercompany artifacts, and close links. Grant the
application role the tables used by the exercised routes, including the domain
audit ledger. This keeps the fixture aligned with migrations 0029, 0039, 0037,
0046, 0063, and 0064 and with the repository's replay-verification contract.
No production route or stored data is changed by this test-only correction.

## Verification

The live PostgreSQL server-identity test passes from a newly created disposable
PostgreSQL 16.14 database with a non-superuser, non-BYPASSRLS application role.
The existing PostgreSQL metrics parity and Alembic upgrade command tests also
pass against the configured PostgreSQL 16.14 service.

## Boundary and rollback

This closes a test-fixture schema drift defect only. It does not prove
statutory consolidation, live providers/write-back, distributed scale,
independent HA/DR, or production readiness. Rollback removes the fixture
schema calls, grants, this ADR, and its evidence; no migration rollback or
runtime data change is required.
