# ADR 0505: Current local operator and Studio validation refresh

- **Date**: 2026-08-10
- **Decision**: Retain a current-tree local validation record for the operator
  commands and modern Studio web surface without promoting skipped live-browser
  or hosted capabilities.
- **Evidence**: `reconforge doctor`, sample-data validation, and a fresh demo
  output directory all exit successfully. Web typecheck, Vitest, and production
  build pass. Playwright reports 16 passed and 5 declared capability skips.
- **Boundary**: Sample data intentionally contains ten validation warnings. The
  demo command requires a fresh output directory because an existing client-pack
  recovery directory is fail-closed as ambiguous. The skipped browser-session
  and HTTPS-hosting tests require their declared live environment; this record
  does not establish hosted deployment, provider interoperability, or production
  readiness.
- **Rollback**: Remove this evidence-only ADR and the E-668 execution entries;
  no product code, schema, or persisted customer data changes are involved.
