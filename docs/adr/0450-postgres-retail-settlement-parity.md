# ADR 0450: Add a PostgreSQL retail settlement evidence adapter

## Context

E-604 exposed replay-verifiable retail settlement evidence through the local
SQLite API and CLI, while the server profile intentionally refused to fall
back to SQLite. A server deployment needs a real tenant/workspace persistence
adapter before the API can be used without weakening isolation or making a
local-only claim.

## Decision

Add PostgreSQL migration `0080_pg_retail_settlement` and
`PostgresRetailSettlementRepository`. The adapter stores the bounded report as
JSONB with scalar digest and status projections, enables and forces tenant and
workspace row-level security, and guards rows against update/delete. Writes
use a transaction-scoped advisory lock and `ON CONFLICT DO NOTHING` so replay
of the same decision/artifact is idempotent while a different artifact with
the same decision digest is refused. Reads re-run the same artifact and nested
decision verification before returning evidence.

The server API now selects this adapter through the existing PostgreSQL tenant
boundary. The request workspace header is authoritative; a body/query
workspace may only echo that scope. Local mode remains SQLite and keeps its
existing behavior. No processor, ERP, bank, posting, write-back, or external
network call is introduced.

## Evidence and limits

`tests/test_postgres_retail_settlement.py` covers schema/migration contracts
and an opt-in live non-privileged PostgreSQL RLS/idempotency/immutability drill.
`tests/test_api_server_retail_settlement.py` proves the server boundary and
explicit no-fallback route composition. The live test is skipped when the
configured PostgreSQL service and non-privileged application role are absent;
local green tests therefore do not claim hosted parity, HA/DR, provider
authenticity, production SLOs, or retail posting.

## Rollback

The Alembic downgrade refuses to drop non-empty evidence, then removes only
the trigger, function, index, and empty table. API server selection must be
disabled before downgrading a deployed database.
