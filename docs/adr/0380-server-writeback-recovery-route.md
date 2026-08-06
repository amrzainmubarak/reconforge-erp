# ADR 0380: Expose idempotency recovery through the governed server route

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Add `POST /api/v1/connectors/writeback/intents/{intent_id}/recover`
  behind `connectors.writeback.reconcile`. The route is server-profile-only,
  scope-bound, optimistic-versioned, and accepts only a `DISPATCHED` intent. It
  invokes the provider-specific recovery lookup and persists an acknowledgement
  only after the original idempotency key and response digest are verified.
- **Verification**: The API connector suite and closed authorization-inventory
  suite pass 8/8. The inventory is 239 routes with digest
  `17c4bfc40da554070b4cf1589e49845f7a77a798654ac3dbb80eced0b567b388`.
  Ruff and Mypy pass for the changed route surface.
- **Boundary**: Local SQLite and unconfigured server profiles remain fail-closed.
  This route does not establish provider status-API interoperability, live
  ERP/bank write-back, accounting posting, distributed idempotency, HA/DR, or
  production readiness.
- **Rollback**: Remove the route, request model, inventory expectation, tests,
  ADR, and evidence entry; no migration or persisted-data rollback is required.
