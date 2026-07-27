# ADR 0018: Alembic for PostgreSQL Server Migrations

- Status: Accepted as an initial server foundation
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

ReconForge's local edition uses explicit SQLite migrations and must keep that
workflow stable. A PostgreSQL deployment needs a standard migration tool with
versioned revisions, offline SQL generation, upgrade tracking, and deployment
credentials supplied outside the repository.

## Decision

Add an optional server dependency on Alembic and SQLAlchemy. `alembic.ini`
contains an empty URL and `alembic/env.py` requires
`RECONFORGE_POSTGRES_DSN`, converting ordinary PostgreSQL URLs to the
`postgresql+psycopg` SQLAlchemy dialect. The first revision installs the
PostgreSQL tenant/RLS foundation already defined by the infrastructure adapter.

The server-boundary CI job installs the server extra and runs
`alembic upgrade head` against a disposable PostgreSQL service before running
non-privileged RLS tests. Local SQLite migrations remain authoritative for the
local edition and are not silently routed through Alembic.

## Consequences

- Database credentials remain outside committed configuration.
- Online and offline Alembic migration paths can be validated independently.
- The current revision chain does not yet represent every SQLite domain table;
  server persistence cannot be called complete until those migrations and
  repository contracts are added.
- Destructive downgrade of the initial schema drops the `reconforge` schema and
  therefore requires explicit operator intent and backup policy.

## Rejected alternatives

- Putting a production DSN in `alembic.ini`: it would risk credential leakage.
- Replacing local SQLite migrations immediately: it would break local mode and
  existing upgrade/backup compatibility.
- Treating the PostgreSQL RLS SQL string alone as a migration system: it would
  lack revision tracking and deployment execution semantics.
