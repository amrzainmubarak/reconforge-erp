# ADR 0362: Derive CI synthetic object-storage credentials at runtime

- **Status:** Accepted
- **Date:** 2026-08-05
- **Decision:** Keep the object-storage CI job authenticated to its disposable
  digest-pinned MinIO process, but derive the same temporary password inside
  each shell step from the non-secret seed `reconforge-ci-object-store`.
  Repository workflow environment mappings must not contain a reusable
  password literal.
- **Verification:** The workflow contract still starts MinIO, runs the real
  boto3-backed verifier, uploads the schema-closed report, and cleans up. The
  focused test rejects the prior literals; supply-chain policy, Ruff, and
  diff-check pass.
- **Boundary:** The derived value is synthetic CI material, not a vault,
  customer credential, or production secret. Hosted Gitleaks history/tree
  execution remains a required release gate.
- **Rollback:** Revert this workflow/test/documentation slice only if the
  disposable provider authentication contract fails; retain scanner defaults
  and do not add a broad allowlist.
