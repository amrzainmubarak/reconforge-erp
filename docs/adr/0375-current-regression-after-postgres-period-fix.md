# ADR 0375: Record the current regression after the PostgreSQL period fix

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Record a fresh full local regression after the PostgreSQL
  consolidation close business-period binding correction. This is a quality
  checkpoint, not a release approval.
- **Verification**: `uv run --no-sync pytest -q --tb=short -ra` exits 0 in
  356.4 seconds on the current Windows/Python 3.12 tree. No collected or
  executed test failed; declared live-service/platform skips and existing
  framework/legacy-input warnings remain visible. The focused PostgreSQL
  17.10 financial, IAM, and database-reference live contracts were already
  executed separately and remain recorded in E-475 through E-477.
- **Boundary**: Local compatibility evidence only. Hosted matrices, native
  backup-tool availability, hosted security/provenance attestation, live
  ERP/bank providers and write-back, statutory accounting, independent HA/DR,
  and production approval remain open.
- **Rollback**: Remove the evidence entry and ADR; no runtime or data rollback
  is required.
