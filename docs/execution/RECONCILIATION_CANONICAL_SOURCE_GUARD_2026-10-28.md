# Reconciliation canonical-source containment — 2026-10-28

**Status: in progress; release remains blocked.** The change described here is
a fail-closed containment in `LocalDeterministicMatcherAdapter`, not a claim
that historical matching results, all adapter implementations, or complete
reconciliation replay are correct.

## Observed failure and source boundary

The adapter previously used `attributes_json` with `setdefault` for source
identity, amount, date and reference. The engine also searches the currency
aliases `currency`, `currency_code`, and `ccy`, in that order. A synthetic
adapter reproduction uses a source amount of 1, an overriding attribute
amount of 999, and an opposing amount of 999: the adapter produced `Matched`
with difference 0.00; the control without the override was unmatched. The
source-pinned reproduction and log are
`output/erp-vision-20261028/adapter-attribute-override-probe.py` and `.log`
(SHA-256 `ff4a20b3852d532c16ec50f6529ab16f48f0ae56cc47c9640576f4d8546c745c`
for the log). Another probe separately exercised identity, date, reference,
currency and amount overrides in `output/result-collision-probe-20261028/`.

An independent restricted-role synthetic PostgreSQL test on the earlier source
also observed a persisted completed match using an attribute-supplied left ID
that identified a different source record. Its retained log is
`output/result-collision-probe-20261028/native-identity-confirm.log`, SHA-256
`5fb3ec7b9537656e2405b9d217875e84825a4c627c887cb15b12fd822eaf689f`.
This is not evidence of GL posting, a real customer, or a completed ERP cycle.

## Containment and compatibility

Before invoking the deterministic engine, the adapter compares supplied
attribute aliases against the separate canonical source record. It rejects
conflicting identity, mapped amount/date/reference, canonical field aliases,
currency aliases, and original-amount evidence. It treats absent, null and
blank canonical values as unknown: a nonempty attribute cannot supply them.
It rejects overlapping identity/currency/date/amount/reference mappings;
`amount_original` remains a supported amount mapping when consistent. Numeric
comparison is exact, bounded, finite and independent of the caller Decimal
context. The initial version left binary-float acceptance to the historical
persisted input policy; the later containment below supersedes that behavior
for the hosted adapter without reclassifying historical results.

This is deliberately a behavioral restriction. Existing conflicting or
attributes-only submissions, including direct in-process adapter callers, can
now fail rather than matching; the worker may already have claimed a run when
it reports the error. Values that compare equal retain the existing attributes
and engine behavior. No previous results or persisted inputs are rewritten.
Historical checkpoints in streamed partition mode can be skipped before this
guard runs, and earlier partitions may already have committed; neither history
nor partial-run recovery is qualified by this change. Different source values
may legitimately require a separately versioned mapping contract, which is not
implemented here. The safety guard also does not resolve exact arithmetic,
currency-policy versioning, source authenticity, exception persistence, or
the separate grouped matcher.

The pre-existing worker test fixtures that used attributes without canonical
date, reference or currency were updated to explicitly supply matching source
fields; their existing assertions and v1/v2 financial-policy checks remain.
The public ingestion contract itself has not been migrated in this slice.

## Development verification

The initial red run at parent HEAD `43d8d051` reported 14 failures and one
pass for conflicts and unknown source values; log
`output/erp-vision-20261028/canonical-source-red-v2.log`, SHA-256
`c8a83e6121a8e3102b28a53aee104896c5179da1a3cfe661d3fb7eb90e0c83ba`.
Additional red runs captured absent canonical keys and the temporarily
over-restricted `amount_original` mapping at
`canonical-absent-red.log` and `canonical-original-mapping-red.log` in the
same directory. The latter was narrowed so equal source mappings remain valid.

On Windows, Python 3.12.13, with local changes and concurrent work elsewhere,
the command below passed 118 tests, skipped four PostgreSQL prerequisites and
reported two warnings (Starlette TestClient deprecation and the intentional
legacy financial-input warning). Pytest time was 5.10 s and wall time 7.31 s.

```text
output/release-blocker-20261025/venv312/Scripts/python.exe -m pytest -o addopts='' -q -ra tests/test_reconciliation_canonical_source_guard.py tests/test_postgres_reconciliation.py tests/test_postgres_reconciliation_persisted_json.py tests/test_reconciliation_worker_organization_scope.py tests/test_worker_policy_amount_20261028.py tests/test_postgres_grouped_matching_guard_20261027.py tests/test_postgres_grouped_matching_runtime.py tests/test_api_server_reconciliation.py
```

The log `output/erp-vision-20261028/canonical-source-final-integrated-v2.log`
has SHA-256 `76a964f9014ad0a02b963a4349f2107190c5084b0e0fb2d48c2c4055a846c4a5`.
The worker SHA-256 was
`f3b47b1ded1200bbbcda9a4924bde271b6bed7b5f874564e0e09a2fc403045c5`;
new test SHA-256 was
`ae7f7059bfaae9ea78f1497d2f757f8d479c5c1cadca80748491caa237fb99f3`;
updated existing test SHA-256 was
`5ffa7ee7f4b0b896c74d7d5ec5149a1f2a5158fdffec9d49b87bdbeb4c1d2466`.
Ruff, file-level mypy and Bandit returned success. These are file-bound local
results, not a clean-tree, hosted CI, real PostgreSQL recheck of the guard,
performance, restore or production assurance. Those gates remain required.

## Alias and mapping follow-up — 2026-10-29 00:53 Africa/Cairo

An independent review found that default `amount`, `date`, and `reference`
attributes could still affect an `exact_fields` or `partition_fields` rule when
the corresponding matching field had a custom name. The guard now compares
those default aliases against the canonical source even for custom mappings.
If a canonical alias is used by an exact or partition rule but was not the
selected mapping and is absent from the source attributes, it refuses the run:
inserting a replacement silently would change historical rule semantics. It
also rejects using a canonical amount/date/reference name as a mapping for a
different domain and rejects an explicitly selected canonical source alias when
its value is absent or inconsistent with the historical fallback.

For a streamed, not-yet-completed partition, the adapter checks each record
before matching and yielding its result; the SQL cursor may already have
classified that partition. A prior partition may already have been yielded or
committed when a later conflict is found. A completed checkpoint is still
skipped before the guard. Neither whole-run atomicity nor historical checkpoint
integrity follows from the new checks. String exact-fields list elements
containing commas are also checked as separate names, matching the engine's
effective field parsing.

Four retained red logs cover the new cases:
`canonical-alias-mapping-red.log` SHA-256
`0b5bb849891816e520ef1933731d90f1d4e645e5829c86d9bb24dd9b24f15562`,
`canonical-explicit-stream-red-20261029.log` SHA-256
`bd7cc3ea8f711ffc5bc5ddf617dae52ca5ab8c939655c63499bc7f78078d039d`,
`canonical-missing-alias-red-20261029.log` SHA-256
`42487e421e45f65f1946b2c517f948fc6031692a183086f3a32b7ac00008637c`,
and `canonical-comma-exact-red-20261029.log` SHA-256
`a50efcc8a33f2f034ad33ad25b3978700d42ccf878a8e220d7944c17cadf79e5`,
all under `output/erp-vision-20261028/`.

The same focused eight-file command above then passed 157 tests with four
PostgreSQL prerequisite skips and two warnings on Windows/Python 3.12.13;
pytest time was 6.67 s and wall time 9.69 s. Its log is
`output/erp-vision-20261028/canonical-source-final-20261029-v2.log`, SHA-256
`a9b72866b87b49cd7bbcdcfaa967cbc0d6d59a55acdb4b6fe9aa892f2d5f637a`.
The worker file SHA-256 was
`7b8f929564ad7b5429f613c99d0675cf380b2748d46dcfdf12fff243ce3abc3e`,
new test file SHA-256 was
`bdef11d904daee62b345ecf9839e98f607816c1a1cf9b27581f39a3fc2cb95bf`,
and modified existing test SHA-256 was
`5ffa7ee7f4b0b896c74d7d5ec5149a1f2a5158fdffec9d49b87bdbeb4c1d2466`.
Ruff passed after one initially reported SIM102 style issue; mypy and Bandit
passed on the semantically identical source immediately before that edit.
This is local, file-bound development evidence; PostgreSQL and hosted checks
on the final integrated source remain independent requirements.

## Exact-field input shapes — 2026-10-29 01:20 Africa/Cairo

Independent review found that the guard initially inspected list-valued
`exact_fields` but missed text-valued `exact_fields`, even though the adapter
passed text to the engine. The regression reproduced two missing-alias
failures in `canonical-string-exact-red-20261029.log` (SHA-256
`7fce3bc14726feb06a9f51d33701aa711ef2cd42e7b70483a75a161b816754d6`).
The guard and engine now share a single conversion to exact-field text;
strings, comma-separated strings, lists of strings, empty values and `None`
retain their prior meaning. Unsupported scalar values, objects and lists with
non-string members fail closed instead of being coerced; this deliberately
restricts an earlier accidental contract. Its six-case red evidence is
`canonical-invalid-exact-red-20261029.log` SHA-256
`6d2a1dd510beca0a7769b5ca7611ebb0e369bf18864db2a9f1aa610805d5e1ff`.

The eight-file command above then passed 173 cases with four PostgreSQL
prerequisite skips and two warnings in 5.72 s pytest time, 7.91 s wall time;
`canonical-source-final-20261029-v3.log` SHA-256 is
`3e9f702f7b3411f34687f8fffa9bbb94e59eb61130cbbeee644e87fc23cd7719`.
These logs are under `output/erp-vision-20261028/`. Final worker SHA-256 was
`ee3d39446648e3ec01f49d23d04897f70992bea6f66e720197062280d510e8e3`;
the new test SHA-256 was
`9c25b0460e0bcbd286f104524a07460e4fa86231a8282755524541d72caef56f`.
Ruff, file-level mypy and Bandit passed on this source. PostgreSQL and hosted
validation remain separate, and the earlier source-bound results remain
historical rather than being attributed to this version.

## Required identity, currency and exact fields — 2026-10-29 04:42 Africa/Cairo

An independent adapter-level review found that legacy matching could generate
an identity when `source_id` was missing, match records without currency, and
consider two missing exact fields equal. The adapter now refuses missing,
non-text, blank or noncanonical source IDs before matching. It also refuses IDs
with newlines or more than 160 characters because the underlying engine would
replace or truncate those IDs. It requires an uppercase, nonblank currency
present in the currently installed currency registry. Currency registry version
and digest are not bound to the decision by this slice.

The submission API and repository still accept source IDs up to 255 characters;
therefore a 161–255 character ID can be accepted and later fail worker
processing. This deliberate fail-closed containment avoids silently truncated
lineage but is a compatibility gap, not aligned ingress validation. Resolving
it requires a versioned identity contract and a migration/retry plan for
already submitted records.

Each explicitly configured exact field must be present and nonblank after
the existing canonical-field defaults have been applied. Structured values
and binary floats are rejected because the financial decision would otherwise
depend on an unversioned string conversion or floating-point value; present
zero and `False` remain valid scalar values. Currency aliases `currency` and
`ccy` are not invented from `currency_code` when used as exact fields. The
previously accepted legacy direct callers and inputs with missing identity,
unknown currency, missing exact fields or unsupported exact-field types may now
fail and require review. A worker currently reports this as `Failed`; this is
not a persisted data-quality exception, and the separate matcher-exception
contract is still open. Completed checkpoints bypass these checks and are not
qualified by the new containment.

The initial RED run for identity/currency/exact-field gaps reported 22 failures
and 7 cases already rejected; its log
`output/erp-vision-20261028/canonical-missing-required-red-20261029.log`
has SHA-256 `9785a9f3f70c90dc951304c90c6078f4b926ffc673644aa4ee7f00e98e986139`.
A second RED for structured and float exact fields reported five failures;
`canonical-exact-unsafe-values-red-20261029.log` SHA-256 is
`038073a6cc0ba19825611d1b27d947d0140577195bb6fea6bb9b0dba4bcefc66`.
The first integrated run after the fix reported two fixture failures because
the synthetic direct-adapter records lacked currency; that negative is
`canonical-required-integrated-first-20261029.log`, SHA-256
`7a333822c1773f5514f528ea11969aa251d1a20c330158520570b8f60b237069`.
The fixtures now carry the intended USD currency and retain their assertions;
separate tests explicitly refuse missing currency.

After this fixture correction, the same eight-file command above passed 239
tests, with four PostgreSQL prerequisites skipped and two warnings, in
18.34 s pytest time and 26.44 s wall time. The log
`canonical-required-integrated-20261029.log` SHA-256 is
`61937be70cdf75df0e24e4231001ff572ac7115246f1c51084696220fb675660`.
The worker file SHA-256 was
`6b243394194e5cf2e771e5841956e923431f1c97935b6c03b03678c893a0ccf9`;
the new test SHA-256 was
`6aa66144e7f1305b64d87e1ccfd4915e64a8209af81f0aceb3418d72a81c3e61`,
and the existing test SHA-256 was
`5b731fa8f4bc4a89457af514fef4bca4df96ece1a6ad926db70738335a216dff`.
Ruff, file-level mypy and Bandit passed. These results are on a mutable local
checkout and do not establish a final-source PostgreSQL rerun, hosted CI, full
replay, rollback, or production qualification.

## Validity and financial-input containment — 2026-10-29 06:34 Africa/Cairo

Independent adapter probes found that non-boolean `valid` values such as
`"false"` were converted to true and that `"12,3"` could be parsed as 123
even under strict v2. The adapter now requires an explicit real boolean `valid`
field; a missing or non-boolean value is rejected. An explicit `False` remains
invalid, including when attributes say `True`. Source IDs containing C0 or DEL
controls are also rejected, as are IDs beyond 160 characters that the engine
would truncate. The repository accepts IDs through 255 characters; this is a
deliberate availability/compatibility restriction pending a versioned identity
contract, not a change to the ingestion schema or to historical identities.

For this adapter boundary, financial amounts are checked before matching even
when there is no corresponding attribute. Only actual built-in `str`, `int`,
and `Decimal` values are accepted: binary floats, NumPy floats, zero-dimensional
arrays, custom subclasses and their potentially deceptive conversions are
rejected. String grouping is validated using `parse_guarded_amount_v3` as a
fail-closed check; the original value and the recorded financial-input policy
remain unchanged, and no past v1 or v2 decision is reclassified. The Decimal
coefficient and exponent are bounded in a trapping context before conversion
to fixed-point text; independent unit tests ensure a 10,000-digit Decimal is
rejected before formatting. This is not a general memory or throughput claim.

The earlier test that deliberately expected binary-float matching under v1 now
checks rejection under both v1 and v2, then uses exact text to retain its
checks for the two identity-policy versions. This is an intentional contract
change, not evidence that historical float decisions were repaired. A missing
amount remains available for the existing data-quality path; invalid direct
input raises a worker error, which currently becomes `Failed`, not a persisted
data-quality exception. The separate engine-exception persistence gap and
historical checkpoint restrictions remain open.

The initial reproduction recorded 33 failures and 6 passes in
`output/erp-vision-20261028/canonical-valid-amount-red-20261029.log`, SHA-256
`6b8b7d347385592e14640466941d6a1d9415f81759d7bec2ec6f587497720cc6`.
Additional custom-type spoofing yielded four failures in
`canonical-custom-type-red-20261029.log`, SHA-256
`b8f73ed6fb9cff8f501b9cad9b275b894e31a0767b2671fe0ece60ceb51fcb3a`.
The eight-file regression command above subsequently passed 285 tests with four
PostgreSQL prerequisites skipped and one Starlette warning, in 9.48 s pytest
time and 11.98 s wall time. Log
`canonical-valid-amount-integrated-final-v2-20261029.log` SHA-256:
`5823a1b886ed044cdf0c11f8cec55437fc25ac0a24f01e9d0c76ef31798aebe6`.
The worker SHA-256 was
`1cab6371824e6d5c9b6efa013ae7543fa1bc77e935fb5b40d3de23d07519657b`,
the new test SHA-256 was
`1d204f07fe20fcfc0297b91a8dbfee0c1ec056e3478953692b3f205ea2349f23`,
and the existing test SHA-256 was
`ac30f65eeeef4e3243a27a287f9c23d69bf4cf68e71fc628c0e37790a2a3408c`.
Ruff, file-level mypy and Bandit passed on the same source. PostgreSQL
restricted-role and hosted CI reruns on the final source remain required.

A subsequent restricted-role PostgreSQL 16.15 synthetic run passed all 18
native cases with no skips, against worker SHA-256
`1cab6371824e6d5c9b6efa013ae7543fa1bc77e935fb5b40d3de23d07519657b` and
repository SHA-256
`7f8191b1` (prefix as reported by the runner). Tracked contents remained
stable during that run, although the tree contained changes. The log
`output/erp-vision-20261028/streamed-partition-postgres-first-20261029.log`
has SHA-256 `d8f77385d9a5189c9cc0ac63fdd7dc78402417d584868d9206808d586df50fa6`.
The cases include a previously committed partition retained when a later
partition fails. This was the first live run after the repair, not a live RED;
it does not prove whole-run rollback, historical checkpoint integrity, hosted
CI or a release artifact.
