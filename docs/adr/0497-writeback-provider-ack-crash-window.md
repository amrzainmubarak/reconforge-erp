# ADR 0497: Verify write-back recovery after provider acceptance

- **Status**: Accepted
- **Date**: 2026-08-10
- **Context**: The write-back route persists `DISPATCHED` before provider I/O,
  and providers may accept an idempotent mutation immediately before the
  ReconForge process exits. A retrying POST in that window could duplicate the
  provider effect unless status recovery is exercised explicitly.
- **Decision**: Add a real spawned-process contract that stages a dispatched
  synthetic intent, records one provider acceptance, and exits through
  `os._exit` before acknowledgement persistence. The recovery path must query
  provider status using the original idempotency key, must not resolve the
  mutation payload, and must persist the bound acknowledgement without a second
  POST.
- **Verification**: E-660 passes locally on the migrated SQLite repository.
  Version 3 remains `DISPATCHED` after the child exit; one status lookup writes
  version 4 `ACKNOWLEDGED`; the injected POST marker remains at one call.
- **Boundary**: Synthetic injected provider and one-host SQLite process
  evidence only. It does not prove vendor status-API interoperability,
  distributed receiver idempotency, ERP/bank semantics, accounting posting,
  HA/DR, or production write-back.
- **Rollback**: Remove the additive process test, ADR, and evidence records;
  no product schema or user data is changed.
