# ADR 0377: Record the current regression after the API authorization fix

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Record a fresh full local regression after the FinanceRead
  authorization-consistency correction and its updated contract test.
- **Verification**: `uv run --no-sync pytest -q --tb=short -ra` exits 0 in
  354.3 seconds on the current Windows/Python 3.12 tree. No collected or
  executed test failed; declared live-service/platform skips and existing
  framework/legacy-input warnings remain visible. The selected live API suite
  had already passed 24/24 on disposable PostgreSQL 17.10.
- **Boundary**: Local compatibility evidence only. Hosted matrices, hosted
  security/provenance, live ERP/bank providers and write-back, statutory
  accounting, independent HA/DR, and production approval remain open.
- **Rollback**: Remove the evidence entry and ADR; no runtime or data rollback
  is required.
