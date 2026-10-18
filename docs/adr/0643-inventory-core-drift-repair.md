# ADR 0643: Remove the superseded Inventory Core guard and synchronize evidence

- Status: Accepted
- Date: 2026-08-26
- Scope: Inventory Core route dependency, tests, and execution evidence

## Context

E-939/ADR 0632 introduced `get_inventory_local_db` as a safe 501 boundary
while Inventory Core had no server adapter. E-941/ADR 0634 later wired all 19
routes to the scoped PostgreSQL adapter, but the old helper, its tests, and
current-looking claims remained in the tree even though no route depended on
the helper. That created documentation and audit drift.

## Decision

Remove the unused helper and obsolete 501/local-helper tests. Keep
`get_local_db` as the dependency used by all routes: it yields SQLite only in
Local Profile, while Server Profile reaches the explicit PostgreSQL adapter
branch. Mark E-939/ADR 0632/D-987 as historical and keep E-941/ADR 0634 as the
authoritative current boundary.

## Consequences

- Source, test inventory, claims, and runtime behavior now describe the same
  Inventory Core boundary.
- No implicit SQLite fallback is restored; no schema or persisted data changes.
- Historical evidence remains traceable without being mistaken for the current
  Server Profile behavior.
- Existing bounded live PostgreSQL, RLS, exact-quantity, and step-up claims are
  unchanged; this ADR does not add hosted, HA/DR, IAM, capacity, provider,
  compliance, or production-readiness evidence.

## Verification and rollback

- `tests/test_api_inventory_core.py`, authorization, and domain tests pass;
  Ruff, Mypy, and diff-check pass.
- Roll back by restoring the helper and historical tests only if the current
  PostgreSQL server adapter is removed at the same time; never reintroduce an
  unguarded SQLite fallback.
