# ADR 0485: PostgreSQL bank-statement server boundary

- **Status:** Accepted
- **Date:** 2026-08-10
- **Scope:** `bank.cash-reconciliation` evidence persistence

## Context

E-646 closed the local SQLite retention, replay, backup, and authenticated API
boundary for the CAMT.053-to-ledger control. The API deliberately returned a
501 response when a PostgreSQL server profile was configured because parity had
not yet been demonstrated. Leaving that branch untested would make the server
surface materially different from local mode.

## Decision

Additive Alembic revision `0084_pg_bank_statement` and
`PostgresBankStatementRepository` persist the same replay-verified report as a
bounded JSONB record. The table is tenant/workspace-scoped under forced RLS,
protects rows with an immutable trigger, and uses workspace-scoped digest
idempotency. The authenticated server routes select this repository only when
the server identity factory is enabled; local mode continues to use SQLite.
Both modes return `network_dispatch=disabled`. No bank credential, provider
call, payment initiation, posting, or ERP write-back is enabled by this ADR.

## Evidence

`tests/test_postgres_bank_statement.py` proves migration/schema contracts,
replay verification, idempotency, tenant isolation, and immutable-update
refusal. `tests/test_api_server_bank_statement.py` proves real TestClient
list/read behavior through PostgreSQL identity and RLS, workspace denial, and
sibling-tenant denial. The opt-in run uses a disposable PostgreSQL 16 database
and a non-superuser application role.

## Consequences

- The server profile now has a bounded persistence/API parity path.
- Evidence remains non-posting and source-provider neutral.
- Hosted CI, live bank authenticity, workers, payment execution, posting,
  write-back, HA/DR, and production operation remain unverified.
- SQLite rows and existing migrations are unchanged; the rollback is to disable
  the server factory and remove revision 0084/its adapter in a controlled
  migration window.
