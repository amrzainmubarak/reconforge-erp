# Reconciliation result value validation — 2026-10-29

**Status: development implementation and synthetic native tests; final-source,
hosted and full-cycle gates remain open.** This record concerns direct
PostgreSQL reconciliation result persistence. It does not establish that an
invalid value is reachable through a public API or occurred in production.

## Problem and contract

Before this change, `append_result` and `append_results_batch` used
`_decimal(...) or "0"`; an explicitly supplied `None` for
`amount_difference` therefore became a stored zero. Both also called `int()`
on `date_difference_days`, silently accepting booleans, binary floats and
fractional Decimal values by truncating them. Some malformed strings such as
`"1_0"` were accepted; an infinite Decimal produced an unclassified
`OverflowError`. These behaviors could misstate a persisted result without
representing a valid difference.

The repository now rejects an explicitly null or otherwise invalid amount
difference in both single and batch paths. Existing exact amount bounds and
binary-float rejection are retained. A missing **key** in a batch keeps the
declared historical single-result default `"0"`; omitting the argument to
`append_result` also keeps that default. This is a compatibility concession,
not proof that a zero is a measured difference. The result schema has
`NUMERIC NOT NULL DEFAULT 0`, and historical unmatched or invalid results can
store zero where a difference may be inapplicable. Distinguishing unknown,
not applicable and genuine zero requires a versioned schema/contract and
migration strategy; this slice does not meet that broader requirement or infer
the meaning of historical zeros.

`date_difference_days=None` remains valid and persists as SQL NULL. For a
specified difference, exact `int`, ASCII integer text with optional sign and
surrounding whitespace, and finite integral `Decimal` values are accepted
within `0..10,000,000`. Boolean, binary float (including mathematically
integral float), fractional/nonfinite Decimal, malformed text and out-of-range
values are rejected. Decimal checks do not depend on the ambient rounding
context. Previously accepted float/bool/truncated values and underscore
strings now fail: this is an intentional validation compatibility change.
No existing row, identity or checkpoint is reinterpreted or migrated.

The shared decimal validator also accepts text, Decimal and exact integral
scalars (including NumPy integer scalars) without relying on an arbitrary
object's string representation. Floating scalars and wrapped arrays, including
zero-dimensional NumPy/MaskedArray values, are refused. Subclasses of text and
Decimal use their built-in underlying value without executing overridden
`__str__` or `strip`. This type tightening affects the shared source-amount,
confidence, amount-difference and exception-risk inputs; callers previously
passing numeric-looking arbitrary objects must use exact supported values.
Scientific notation supplied as input remains rejected. This does not change
the separate, bounded conversion of typed NUMERIC values read from PostgreSQL.

The result collision change initially entered a savepoint before validating
the single result, regressing the existing bounded-lineage preflight contract.
The public single-result path now validates all inputs before database access,
then calls a savepoint-protected internal writer. Nonempty batch validation
continues inside a savepoint, before INSERT; it is not claimed to avoid all
database access. Autocommit remains refused before any write.

## Development evidence

All data and roles below were synthetic. Windows Python 3.12.13 used a
dedicated PostgreSQL 16.14 container and a newly migrated, disposable database.
The app role was not superuser, BYPASSRLS, CREATEDB or CREATEROLE; the fixture
grants named tables for testing and does not prove production least privilege.
The observed HEAD was `3ae65551dfa51b1ef6bdb9b28cbde83deb4e32d5`; other files
in the shared checkout were modified during development. Each source/test
hash below was measured before and after its own run; this is not a clean-tree
or final-commit result.

- Before the change, the native regression reported 20 failures and 56 passes
  with no skipped tests. It reproduced explicit-null-to-zero, accepted
  bool/float/fractional values, malformed underscore text, and unclassified
  infinite Decimal errors in both single and batch paths. The test that catches
  an invalid second batch item showed the request was accepted instead of
  rejected. Log `output/result-values-20261029/native-red.log` SHA-256:
  `096a7daf0e4d49e0362d31601f835c4d81cffd3a5e64dc2a2a8fec0003898fc2`.
  The former source SHA-256 was
  `3b2ca27fd788b9cd4bb50f257f784d77b8794d89025a08874200ac8feae42b99`.
- After the change and a style-only correction, the focused native suite
  reported **92 passed, 0 skipped/xfail/xpass** with
  `tests.mandatory_native_gate`, in 23.51 s pytest time and 25.01 s wall time.
  It covers both APIs, default omission, explicit null, exact monetary bounds,
  float/bool/nonfinite/fractional/huge day values, nullable days, integer text,
  low-precision Decimal context and rollback after a caught invalid item. Log
  `output/result-values-20261029/native-styled.log` SHA-256:
  `9118f79b2fdf9f38cc0021704fa61f8974518659954c9e0cfe82f0a0118a2432`.
  The source and test SHA-256 hashes before/after were respectively
  `3d038f96d30ee6a87d6f346dd0d04ce3d0623bb48fb3741d00a9af13c4ae94c3`
  and `1564e7ca90c0c84c18582f40014cd96208f851fefca962cb9ef902fd0383541c`.
  The receipt is `native-styled-hashes.txt` in the same
  output directory.
- A wider cohort covering repository, prior result/exception collision and
  numeric retry tests reported **234 passed, 1 skipped, 2 warnings** in
  65.11 s. The skip was `test_postgres_reconciliation.py:1702`, which needs a
  separate configured live PostgreSQL service; it is not counted as a pass.
  The warnings were Starlette TestClient deprecation and legacy binary-input
  fixture policy. Log `compatibility.log` SHA-256:
  `5609f466b8799efdba1d1e1a85f39da7e76a1c256e413ad96f033a51cbe1351c`.
  Ruff, file-level mypy and Bandit passed after the style correction.

- A later independent review found that NumPy `float16`, `float32` and
  `longdouble` values could pass the decimal validator, and zero-dimensional
  arrays or numeric-looking arbitrary objects could do so through `str`.
  RED logs `numpy-red.log` and `numpy-wrapper-red.log` record 12 and 19
  failures respectively. A separate conservative whitelist iteration rejected
  exact text/Decimal subclasses too; its eight failing tests remain recorded
  in `exact-subclass-red.log`. The subsequent revision accepts their underlying
  exact values without calling the custom conversion methods. The pre-existing
  bounded-lineage test also failed due to early SAVEPOINT (`preflight-red.log`)
  and passed after the validation/write split (`preflight-green.log`).
- The final integrated native cohort of result-value, result-collision and
  bounded-JSON tests reported **249 passed, 0 skipped/xfail/xpass**, in
  51.23 s pytest time and 52.75 s wall time. It ran with NumPy 2.5.1 and the
  mandatory native gate. `whitelist-final.log` SHA-256:
  `0d65036bf79e30d2221c3b0bd43dde81076623ab1480f31cac1b638da9f98b35`.
  The repository source and result-value test SHA-256 hashes, unchanged
  before/after that run, were respectively
  `84bc15d251098a9a5bdc167093039abb8a22f55d525ad6d93a26efd5555a5a8a`
  and `38c894d5dddf431c996935b663aa8586c9ff7f598390c63d23d6a68714dcacfe`.
  The receipt `whitelist-final-hashes.txt` also binds the collision test.
  This run includes NumPy wrapper rejection, NumPy integer acceptance,
  float/text/Decimal subclasses, original regex restrictions, no-database
  preflight, result collision and caught-error rollback; it is still a
  shared working-tree run, not final hosted CI.
- A wider post-whitelist compatibility cohort reported **346 passed, 1
  skipped, 2 warnings** in 77.75 s. The skipped legacy test at
  `test_postgres_reconciliation.py:1706` needed a separate configured live
  service; no pass is claimed for it. `compatibility-whitelist-final.log`
  SHA-256:
  `bb6c5f028afffdada2e957f209999f7eb5169c1f6a043fa9290e6963bbf3ec6f`.
  The post-refactor native sealed-input regression separately passed once
  with one Alembic deprecation warning; `legacy-seal-native.log` SHA-256:
  `26f3588a06a0b17a7a073aa339a4f2a5647c78cfe3a8d5c8e10b7fb917f73e90`.
  Ruff, file-level mypy and Bandit passed on the changed source/tests.

The task-owned container is removed after testing. The exact source still
requires independent review and CI on the integrated commit. Historical
default-zero semantics, checkpoint provenance and the route-level input
contract remain separate issues; no migration, production readiness or
financial reporting qualification is asserted.

### Subclass and bounded-text review follow-up (2026-10-29)

An independent agent identified an additional repository-boundary bypass: an
`int` or NumPy integer subclass representing 100 could override `__int__`
to return 1. Separately, a `Decimal` subclass could override `__int__` and a
text subclass could override `strip` when supplying the day difference. The
new regression tests reproduced all four cases. A guarded parser also proved
that a one-million-character numeric text reached `Decimal` before rejection.
The RED cohort was **8 failed, 1 passed**; `subclass-red.log` SHA-256:
`02d3686596cdbcc3a69a8c6566992275b9485e96a416a43b8a6220d04d12663f`.
The passing test shows the previous day parser rejected that particular long
text; it does not mean it had an early length bound.

The repository now reads Python `int` subclasses with the base conversion,
accepts only exact NumPy integer scalar types, copies Decimal subclasses to
the base type before date operations and invokes the base string strip.
Overridden subclass methods therefore cannot substitute another value. The
repository imports NumPy directly; the current project declares pandas, which
installs NumPy transitively, so explicitly declaring the direct dependency is
an integration follow-up for the maintainer. These statements concern this
repository boundary; API reachability is not established.

Numeric text and day-difference text now have a **256 character** maximum,
counting leading zeros and whitespace, before trimming, regular expression or
numeric parsing. This intentionally rejects long text, including strings of
zeros previously accepted as zero, and is a compatibility narrowing, not a
versioned migration. Up to 256 zeros is tested; 257 is rejected. Single
result validation still precedes any database access; a batch validates
inside its savepoint before INSERT. Historical stored values and the omitted
amount default are unchanged, and financial-policy qualification remains open.

On an owned PostgreSQL 16.14 Alpine container with a freshly migrated random
synthetic database and restricted non-superuser/non-BYPASSRLS application
role, the integrated result-values, result-collision and bounded-JSON cohorts
passed **270 tests, 0 skipped/xfail/xpass**, pytest exit 0, 54.83 s pytest
and 56.62 s wall. The test included actual stored values for Python integer,
Decimal and text subclasses and rejection without stored result for a NumPy
integer subclass, both single and batch. The run also exercised existing
caught-error rollback and preflight tests. Log `subclass-native-confirm.log`
SHA-256 `3584eb80c27c57921986449229b3926a61f2d5db23cb8d691a3da2836c04e6b8`;
source SHA-256 `7f8191b1205ff11ec7b749d156de91eb84f2a150f677884dcc5b98a396fc3e43`;
result-value test SHA-256
`5448a36041510e666372e8fecead2a9d1d2babdb6f095ac7060f313de0814ae8`.
Hashes before and after the preceding same-source native run are recorded in
`subclass-native-hashes.txt`; the confirmation receipt with complete paths is
`subclass-native-confirm-hashes.txt`. Ruff, file-level mypy and Bandit passed.
The task-owned container was removed after the run. This is an uncommitted,
shared working-tree test; hosted CI, independent post-fix review, route-level
behavior and historical evidence qualification remain separate gates.

### Decimal coefficient resource limit and dependency follow-up (2026-10-29)

The direct NumPy import is now declared without a new minimum in
`pyproject.toml`. `uv lock --offline` and `uv lock --offline --check`, using
uv 0.11.32, succeeded. A comparison of `(name, version, resolution markers)`
found the same 131 locked package selections before and after. The lock diff
adds only the direct requirement and references to the existing NumPy
2.4.6 (Python < 3.12) and 2.5.1 (Python >= 3.12) resolutions. This
supersedes the previous paragraph's dependency follow-up; it does not
establish that either hosted CI matrix installation has run.

A separate artificial `Decimal` with one million coefficient digits was
constructed before tracing. In the previous source `_decimal` rejected it
for precision but allocated a measured 18,843,181 bytes of traced peak
memory while formatting it; the test for this allocation failed, while the
same fractional input's day-difference check passed its allocation threshold.
The RED log is `decimal-memory-red.log`, SHA-256
`fd89071fd4ea9943526357d41bc91cf6d2d5c97bbcc10927f45b675823ea3896`.
This proves a repository-level resource concern, not API reachability.

An experimental CPython-specific `Decimal.__sizeof__` guard did reduce the
measured allocation, but was removed after review: its memory representation
is not a portable contract, and the guard would reject some previously
accepted whole-day values containing very long runs of trailing zeros. A
spot check showed the same size figures on CPython 3.11.15, 3.12.13 and
3.14.6 for two sample values, which is not proof of portability or semantic
compatibility. The PostgreSQL run of the experimental guard was interrupted
and is not evidence of a pass. The restored source and result-values test
hashes match the earlier 270-pass native run exactly; no general coefficient
resource bound is claimed. A safe resource limit and compatibility policy
remain open. The task-owned experimental PostgreSQL container was removed.
