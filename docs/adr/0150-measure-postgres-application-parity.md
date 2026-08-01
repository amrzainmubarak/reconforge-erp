# ADR 0150: Measure PostgreSQL parity per Application boundary

- **Status**: Accepted
- **Date**: 2026-07-28

## Decision

Maintain `POSTGRES_PARITY_INVENTORY.yaml` as an exact, tested inventory of all
Application services. Distinguish current live verification, available but not
currently executed live tests, contract-only adapters, absent adapters, and
database-independent services. Never infer parity from a similarly named file.

## Consequences

The initial inventory covers all 26 services: zero currently live-verified in
this environment, nine with live tests available, two contract-only, fourteen
absent, and one database-independent. P1-PLAT-002 remains open. Finance Core is
the first critical absent boundary; existing PostgreSQL ledger/master-data APIs
are not signature-compatible with its eighteen-use-case Application port.
