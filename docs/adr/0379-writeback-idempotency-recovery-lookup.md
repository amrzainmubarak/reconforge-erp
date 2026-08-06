# ADR 0379: Add an explicit write-back idempotency recovery lookup

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Keep provider mutation dispatch and uncertain-outcome recovery as
  separate injected transport contracts. When a POST may have been accepted but
  its acknowledgement was lost, recovery may query a provider-specific status
  endpoint using the original idempotency key; it must not resolve the payload or
  issue another mutation.
- **Verification**: `tests/test_connector_writeback_network.py` covers a
  successful recovery with zero POST calls and fail-closed 404/misbound
  acknowledgements. The focused network suite reports 18 passed; Ruff and Mypy
  pass for the changed transport surface.
- **Boundary**: This is a provider-neutral recovery primitive with an injected
  lookup adapter. It does not prove that any ERP, bank, or payment provider
  exposes a compatible status API, and it does not establish accounting posting,
  production write-back, distributed idempotency, HA/DR, or release readiness.
- **Rollback**: Remove the recovery protocol, executor method, tests, ADR, and
  evidence entry. Existing POST dispatch behavior and persisted intent schemas
  remain unchanged; no migration is required.
