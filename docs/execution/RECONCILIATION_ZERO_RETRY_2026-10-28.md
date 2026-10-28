# PostgreSQL reconciliation input retry and NUMERIC scale — 2026-10-28

**Status: implemented and locally tested on a modified checkout; hosted and
final-source qualification remain open.** This slice concerns retrying an
already registered input, not complete reconciliation replay or worker
idempotency in general.

## Reproduction and change

PostgreSQL `NUMERIC(38,18)` returns the exact zero as typed
`Decimal('0E-18')` through psycopg. Before this change, `register_input`
converted that stored Decimal to scientific text and passed it through the
external-input grammar, which rejects exponent notation. Consequently an
identical zero retry raised `PostgresReconciliationValidationError` instead
of returning the existing record. The same issue affects sufficiently small
positive and negative stored Decimal values. The defect was reproduced with a
real migrated PostgreSQL 16.15 database, not only a mock.

The stored-row path now handles a typed, finite Decimal by checking its scale
and integer-digit bounds *before* rendering fixed-point text and applying the
existing strict parser. It never formats unbounded exponents. External request
handling remains unchanged: scientific text and `Decimal` instances whose
string form uses exponent notation, binary floats, booleans, malformed,
non-finite and out-of-range inputs remain rejected. Existing comparison of
all source fields remains in place; a changed amount, currency, hash or
attributes does not become an idempotent retry. No schema, migration, rule
version or recorded input is rewritten. Reverting the source file restores the
previous behavior and the same retry failure.

## Evidence

- Baseline parent `781e93dc31a32d8b7ccbc33608e78367c07a5e13`; the original
  repository file blob SHA-256 was
  `a49033d36cfaac4995c1118bfcfdd3f2bb760680df5ad3b048413f258d183d19`.
  Targeted unit tests failed 8 cases and passed 10 before repair. The distinct
  real PostgreSQL reproduction added a failing native test; its retained log
  is `output/erp-vision-20261028/zero-retry-postgres-red-20261028.log`, SHA-256
  `37d67366c5400cdd4d5ff2f9a11fd3199dcbf503b6d665690aa592a63f9c9e97`.
- On Windows 11 / Python 3.12.13, the repaired paired native run used an owned
  ephemeral PostgreSQL 16.15 container, image digest
  `sha256:1a66d744c1b459e13b05a8fca341da84cb63383e99ce262210efee5a319d4551`.
  The application role was neither superuser nor BYPASSRLS; the fixtures
  create and destroy their own random databases. Both organization-authority
  and zero-retry test files ran together: **27 collected, 27 passed, zero
  skipped/xfail/xpass**, mandatory native gate, 23.015 seconds. Retained log
  `output/erp-vision-20261028/worker-safety-paired-20261028.log`, SHA-256
  `107d33ef30305916b2d50c14ea8db8b6da81c8abe6426cb5167086c676f8c4b6`;
  corresponding JSON records environment, test hashes and source snapshot.
  The owned container was removed. Grants are synthetic fixture grants, not a
  production privilege profile.
- The native test exercises exact zero and ±10⁻¹⁸ before claim, after claim and
  after completion, then rejects a changed amount and external scientific
  notation. Unit cases also cover signed zero, alternate stored scales,
  malformed values, non-finite and oversized values, and changed metadata.
  A targeted broader Python run reported 84 passed, two native cases
  deselected and one existing legacy-float warning; the paired native run above
  is separate evidence. Ruff and file-level mypy passed; CI partition contract
  tests passed 12/12 after including both complete test files in the required
  shard with the mandatory no-skip plugin.
- At the paired run the changed repository file SHA-256 was
  `fa16db3523c32077d332ca62deb5b422053083979ab16e86e73db7d82733c324`, and
  `tests/test_reconciliation_zero_retry.py` was
  `e38b0e06a777286e98fd8a180fd0b50c841bfb6115cc9a85528dc41c5bd090f5`.
  The 4,724 tracked-file contents had identical hashes before and after the
  run, but the working tree included uncommitted changes. This is not evidence
  for the eventual committed source or hosted CI.

Further restore/upgrade, supported-driver parity, concurrent retries and the
full reconciliation business cycle remain separate gates. The unrelated
matcher exception contract and entity/amount authorization gaps are not
addressed here.
