# ADR 0655: Fail closed for the local-only individual cashflow API in Server Profile

- Date: 2026-08-26
- Status: accepted
- Scope: `POST /api/v1/individual/cashflow-controls/run`

## Context

The individual cashflow endpoint is an authenticated, stateless local
control. It calculates a replay-verifiable non-posting result from records in
the request and does not persist a tenant-scoped aggregate. It therefore has
no PostgreSQL server adapter, server-side evidence repository, or enterprise
scope binding. A permission dependency by itself was insufficient to classify
the endpoint safely in the PostgreSQL Server Profile.

## Decision

Keep the endpoint available in Local Profile. When the explicit server identity
profile is active, return HTTP 501 with
`individual_cashflow_server_backend_unavailable` before running the control.
Do not open the local SQLite path, introduce an implicit server fallback, or
represent this refusal as server-side cashflow support.

## Consequences

- Enterprise/server callers receive an explicit and stable unsupported-surface
  response instead of ambiguous local execution.
- Local users, CLI behavior, control packs, report schemas, and non-posting
  semantics remain unchanged.
- A future server implementation must add tenant/workspace persistence,
  policy scope, audit/evidence, migration/restore, and its own runtime gate
  before this refusal can be removed.

## Verification and boundary

E-961 passes the authenticated local compatibility and Server Profile refusal
contracts, plus authorization inventory, Ruff, and Mypy. This does not prove
server cashflow support, bank connectivity, tax/legal treatment, posting,
external IAM, HA/DR, or production readiness.

## Rollback

Revert the route guard, regression test, and E-961 evidence. No migration or
external-state rollback is required.
