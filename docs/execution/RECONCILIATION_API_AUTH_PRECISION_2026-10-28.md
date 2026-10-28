# Reconciliation submission authorization precision — 2026-10-28

**Status: in progress; focused development evidence only.** This is an API
submission boundary change. It is not a worker, full replay, monetary-limit,
currency-conversion, or release qualification.

## Problem and scope

The submission route previously passed `_policy_amount` to authorization.
Under a caller Decimal context with precision 3 and rounding down, even a
single `-1234.56` contributes `1230` to that amount. Accounting parentheses
can also be rounded during parsing. The RED test
`test_api_uses_exact_gross_before_any_repository_write` supplied an artificial
policy ceiling of `1232`: the old code did not deny the request. Its retained
log is `output/exposure-authority-20261028/pre-fix-api-red.log`; it is a
synthetic-policy reproduction, not evidence that this ceiling was deployed.

The route now passes a separate calculation to its authorization boundary.
It parses and adds under an isolated, bounded Decimal context with `Inexact`
trapped. Its request schema limits a submission to 5,000 amount strings of at
most 64 characters. The isolated 160-digit precision covers the largest integer
and smallest fractional string values together, plus the possible carry from
the bounded count; the trap fails closed if those assumptions cease to hold.
This does not relax PostgreSQL's independent numeric bounds. Oversized parsed
requests are rejected before these amount calculations. The request body has
already been parsed and serialized at this point; this is not a streaming
upload-size or memory-allocation guarantee.

The authorization amount is unknown (`None`) when any amount is missing, or
when currencies are missing, mixed, or absent from the active currency
registry. Currency normalization for this check trims and uppercases the code.
For the finite, known single-currency case the value is an exact numeric gross,
not proof that a policy limit uses the same currency. An artificially injected
bounded policy denies an unknown amount. An unbounded policy may allow one:
the current route's `enforce_server_scoped_permissions` builds its context
without loading an amount ceiling, and its policy limit has no currency field.
No deployed bound, FX conversion, registry-version binding, or complete currency
authorization is asserted.

For compatibility, the pre-existing `_policy_amount` calculation still supplies
the stored `rule.policy_amount` and therefore the existing run fingerprint. It
may round in the ambient context and may numerically add unlike currencies;
that historical field is **not** a verified financial exposure. It must not be
interpreted as authorization evidence, and this slice does not change existing
worker behavior. Same-request retry under a different historical Decimal
context can still produce a different rule fingerprint. Previously authorized
retries may now be denied by a bounded policy because the checked amount is
exact or unknown; the route's current standard context does not itself install
such a bound. The old API fixture that expects a known authorization amount now
supplies explicit USD; its assertions remain unchanged.

## Synthetic development checks

At observed HEAD `781e93dc31a32d8b7ccbc33608e78367c07a5e13`, with local
changes and concurrent work elsewhere in the checkout, the route file SHA-256
was `ea6e5ced2e222b72a5185aa142884bb82018230a0f31dfbbdfb0b2474c01e7b6`.
This is file-bound development evidence, not a clean-tree or final-commit run.

- Windows Python 3.12.13: the new route tests, existing reconciliation API
  tests and financial-input tests ran 39 cases, exit 0, 9.45 s. The log is
  `output/exposure-authority-20261028/focused-final.log`, SHA-256
  `182d2cbc6a70dd3fb3e81658433ddc7f22700172ffeabb601dd6b3df41fe3f53`.
  One Starlette TestClient deprecation warning was emitted. Tests include a
  synthetic HTTP policy boundary, same-context retry using a fake SQL
  connection with the actual repository, missing/invalid amounts, mixed and
  unknown currencies, a pre-calculation body-size check, and the bounded 5,000
  input/64-character extremes. Ruff, file-level mypy and Bandit returned 0.
  After adding an unbounded-policy compatibility case without currency, the
  same focused command passed 40 tests with one warning in 7.75 s (10.13 s
  wall time). The final focused log is
  `output/erp-vision-20261028/api-precision-integrated-20261028.log` SHA-256
  `2644080e227e5dbd349ed47ac8930b4929f93829653343b08703c12e6e19ed20`;
  the new test file SHA-256 was
  `2301282ecbd49ce17b5739c24f8dd70e76694a82196aeefa7bf0fb7a705b3963`.
- `output/exposure-authority-20261028/oracle_current.py` checks the exact source
  path and route SHA, and compared 2,424 synthetic cases against Python
  `Fraction` with seed 3048, precisions 3/7/28 and both rounding directions.
  Its log `oracle-current.log` has SHA-256
  `21b2a275922a48e6dba1ad08a32394c4b4fa08e71043147b79e1aaf186aeffd6`.
  A prior `probe-v2-unpinned.log` imported an installed package without
  verifying its origin and is retained as diagnostic only, not HEAD evidence.
- A separate task-owned PostgreSQL 16.14 container used a new database migrated
  to Alembic head, a role without superuser/BYPASSRLS and forced RLS on the run
  and input tables. With HTTP TestClient, synthetic authentication and an
  injected bounded policy, inputs `-1234.56` and `1` produced statuses
  `202, 202, 403, 403` for create, same-context retry, a lower synthetic ceiling,
  and mixed currency. The observed authorization amounts were `1235.56`,
  `1235.56`, `1235.56`, and unknown. Run, input, audit and outbox snapshots
  did not change across the retry or denials. `native-probe-result.json`
  SHA-256 is `121353977a4215d2ce27671ca87176fe1403f08106f2173df2ca8c7218189042`;
  `native-probe-one.log`, migration log and PostgreSQL log are in the same
  output directory. The owned, labelled container was removed after capture.
  This test does not exercise real authentication, a configured ceiling, full
  rollback, process failure, all backends or final-source CI.

## Retained negative: zero-valued native retry

On the same route-file SHA and a separate migrated PostgreSQL 16.14 container,
the initial HTTP submission of `-1234.56` and `0` succeeded, but its retry
failed in `PostgresReconciliationRepository.register_input` while calling
`_decimal` on the persisted NUMERIC. PostgreSQL/psycopg returned the zero as
`Decimal('0E-18')`, whose textual representation the current `_decimal` input
regex rejects. The stored representations, role and RLS checks, failure and
container cleanup are in `native-probe-zero-diagnostic.json`, SHA-256
`cecd88ee24dab32bf0b59d8376d76bcef9f9e25cf99ea54ad5a892289544fc98`, and
`native-probe-diagnostic.log`. The earlier native setup failure due to a
relative SQLite path is separately retained as `native-probe-first-failure.*`.
The subsequent nonzero retry is a bounded positive case, not a repair or
reclassification of this zero-valued failure.

The worker still accepts a caller-supplied or historically persisted exposure
and does not bind a currency-aware limit to the locked complete input set.
Partial/missing input retries, concurrent edits, checkpoints, policy revocation,
PostgreSQL upgrade/restore and final-source CI remain separate open gates.
