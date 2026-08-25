# ADR 0637: Fail closed for local-only Exceptions and Workflow routes

- Status: Accepted
- Date: 2026-08-26
- Scope: `reconforge.api.routes.exceptions`, `reconforge.api.routes.workflow`

## Context

ReconForge has a local SQLite Exceptions queue and Workflow state machine, but
these route families do not yet have PostgreSQL adapters with authenticated
hierarchy binding, central policy re-evaluation, RLS, audit/outbox parity, and
live server evidence. The generic `get_db` dependency could therefore open a
tenant-local SQLite database while the rest of the request used PostgreSQL
server identity. That would create an ambiguous financial workflow boundary.

## Decision

Keep both route families explicitly local-only until their PostgreSQL adapters
are complete. They now use `get_local_db` and reject Server Profile requests
with route-specific HTTP 501 errors before invoking any SQLite service:

- `exceptions_server_backend_unavailable` for Exceptions;
- `workflow_server_backend_unavailable` for Workflow.

Local Profile behavior remains unchanged. The rejection is intentionally
fail-closed and reversible; the next implementation gate is a dedicated
PostgreSQL adapter plus scope, policy, RLS, audit/outbox, migration, and live
HTTP evidence.

## Evidence and limits

`tests/test_api_server_local_boundaries.py` runs a real FastAPI app with an
unreachable PostgreSQL DSN and verifies three Exceptions endpoints and four
Workflow endpoints return 501 without opening local SQLite. Existing local
workflow/audit tests continue to pass. This proves only the safety boundary;
it does not prove PostgreSQL Exceptions or Workflow support, external IAM,
HA/DR, provider behavior, capacity, backup/restore, compliance, or production
readiness.

## Rollback

Do not restore generic `get_db` in Server Profile. Replace the 501 guards only
when the dedicated PostgreSQL adapters and their evidence gates are merged.
