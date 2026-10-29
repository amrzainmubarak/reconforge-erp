# Reconciliation result identity collision — 2026-10-29

**Status: implementation and synthetic native verification; hosted and final
source qualification pending.** This slice concerns result persistence. It
does not verify the original matcher decision, financial posting, historical
checkpoints, or a complete business cycle.

## Problem and bounded change

Result row identity is derived from tenant, run, source IDs, match type and
status. Confidence, explanation, amount difference, date difference, reason
and lineage are not part of that identity. The previously observed live
PostgreSQL counterexample is documented in
[source and result evidence](RECONCILIATION_SOURCE_AND_RESULT_EVIDENCE_2026-10-28.md):
a second partition with a different result payload completed a checkpoint with
the requested payload's hash while the persisted result remained from the
first partition. That is evidence of direct repository calls with synthetic
outputs, not evidence the matcher generated the conflicting pair.

The updated repository preserves historical row identities. It checks existing
single results and every row in a nonempty batch against the requested content,
using PostgreSQL's NUMERIC and JSONB equality and explicit NULL-safe comparison.
It rejects missing or changed rows. A nonempty batch rejects repeated IDs even
when the repeated payloads are identical: previously a checkpoint could count
the same stored row twice. Identical retry in a **separate** call remains
accepted. Empty batch behavior remains unchanged and does not touch the DB.

Batch writes use a savepoint inside the caller's transaction; an error rolls
back inserts made earlier by that operation even if the caller catches the
Python exception and commits. The existing partition savepoint protects the
whole new partition's writes, including when a later result conflicts. The
caller remains responsible for its outer transaction; a successful operation
does not commit it. The single-result operation now uses the same nested
savepoint and refuses an autocommit connection before writing. The existing
test-only savepoint name is unchanged.

This deliberately tightens compatibility: a previously accepted request with
the same row identity and changed fields or duplicated batch identities now
raises an integrity error. Exact numeric equivalence and JSONB equivalence
remain accepted, while JSON boolean `true` and number `1` differ. No schema or
identity migration is performed. Existing checkpoints remain readable under
their historical semantics, but their hashes and counts alone do not prove
which persisted rows belonged to them; a versioned migration or separate
verification policy is needed before qualifying historical replay. Identical
results in distinct partitions may still share a row; no unique cross-partition
cardinality or result-to-partition lineage is claimed.

An independent source review identified two pre-existing input-validation
gaps outside this change: the result path converts an explicitly missing
`amount_difference` to `"0"`, and `int(date_difference_days)` may truncate
a fractional value. Neither issue is repaired by comparing persisted content;
their reachability through the public API and production impact have not been
established. They require separate failure-first tests and a compatible
ingress policy before any broader correctness claim.

For nonempty result and exception batches, `chunk_size` must now be an integer
from 1 to 5,000; zero, negative, booleans, nonintegers and larger values fail
before any SQL. This closes a previous silent loss in which a negative value
produced an empty iteration. Empty batches preserve the historical immediate
`[]` behavior, including when the supplied size is invalid. Each insert uses
13 bind parameters per row: the maximum generates 65,000, below PostgreSQL's
65,535 parameter ceiling. This is a compatibility tightening for callers that
used invalid, boolean, noninteger or oversized chunk values.

## Development verification

On Windows/Python 3.12.13, an owned PostgreSQL 16.14 container and new migrated
database used a role without superuser, BYPASSRLS, CREATEDB or CREATEROLE.
The fixture's named-table test grants are not a production least-privilege
profile. The environment had other concurrent work in the checkout, so the
following is file-bound, **not** final source-frozen or hosted CI evidence.

- Before the change, the focused live regression suite exited 1 with 14 failed
  and 2 passed in 13.41 s. It exposed changed-content acceptance, repeated
  identity acceptance, a second misleading checkpoint, partial batch writes
  when the caller caught an error, and two successful concurrent attempts.
  `output/result-collision-20261029/native-red.log` SHA-256:
  `389cc2d2232d678c6d6a1dab149133b14aabe696c66c6499d461fb64abb14b8b`.
- After the change, `tests/test_reconciliation_result_collision.py` ran with
  `tests.mandatory_native_gate`: 18 passed, 0 skipped/xfail/xpass in 16.41 s
  pytest time, 18.76 s wall time. It covers changed fields, boolean versus
  number, numeric/JSONB-equivalent retries, duplicates within/across chunks,
  caught-error commit, partition rollback, concurrent different payloads,
  caller rollback, and nested savepoint preservation. The log
  `output/result-collision-20261029/native-final.log` SHA-256 is
  `4e5fb34c23a3b64a4538366e9658105a4c80401c725c7d17a97bbcc2ad8cbdb2`.
- The source SHA-256 was
  `6a068c0226500d7ba4b0cc1fd4e7a866ed73dffb9ad2d56786f87ddb5aef45e7`
  before and after that run; the test SHA-256 was
  `8282e9589001859f4086c8f0a3f38d9805c0dd6b7af65427cde0893ffd224fee`.
  The observed HEAD was `f4686c4a209337c60e1f6ed4be35da2efeb4180a`; the
  checkout was modified. The hash receipt is `native-final-hashes.txt` in the
  same output directory.
- A wider compatibility run before the final two savepoint tests were added
  reported 113 passed, one skipped for an unrelated native service
  prerequisite, and two warnings in 48.06 s. Its log SHA-256 is
  `39c70985d3bbe5260943584976000077f5f9919c79bec366bd6bde8e30f040a3`.
  An earlier run had three failures: an old mock did not handle the new
  comparison query and the binding fixture repeated a now-forbidden identity.
  That negative log is `compatibility.log`, SHA-256
  `178d5822ffb442ebd1e82bc0e38bb0aac9d39b41041dc5ddbc46ce2535590622`.
  The updated fixtures retain hostile SQL values and assertions and add
  verification-query binding assertions. Ruff, file-level mypy and Bandit
  passed on the changed source/tests.

- Further focused tests exposed two additional pre-existing failures. The
  nonempty invalid-size tests produced 16 failures before the change because
  they reached SQL; `chunk-boundary-red.log` SHA-256
  `b19be2c29dd31218dae4b1c1b97348b05ca22b7204dfbcb6f4694e0686b21abc`.
  The restricted PostgreSQL autocommit probe showed that the old single-result
  path wrote successfully instead of rejecting; `autocommit-red.log` SHA-256
  `5fe6b1ef65b1e401ad2d000c317ce785299389227a5a296d41997be3fa8112a9`.
  These negatives are retained alongside the original collision RED.
- After adding the bound and single-result savepoint, the expanded mandatory
  native suite reported 45 passed, zero skips/xfails/xpasses in 16.82 s pytest
  time (18.27 s wall). It includes nonempty size boundaries, `NULL` versus zero,
  autocommit rejection and a real 5,000-row exception batch. The latter passed
  65,000 bound insert parameters and 60,001 verification parameters. The
  `native-bounds-green.log` SHA-256 is
  `aa92a142d4ebb29268e5aab5ae17fc8fbc9671827e81c66ce998359c9946786c`.
  Its source SHA-256 was
  `3b2ca27fd788b9cd4bb50f257f784d77b8794d89025a08874200ac8feae42b99`
  and its test SHA-256 was
  `42d6774b0f017dfc64adf39dff66d74d40aba9fd563c8da2896cefa8c1cf8dcd`,
  both unchanged before/after. This remains a concurrently modified tree.
- The updated compatibility cohort reported 142 passed, one existing skipped
  for an unavailable separate PostgreSQL prerequisite, and two warnings in
  42.95 s. `compatibility-bounds.log` SHA-256:
  `8dbc640cc96121e478ee34d90ecdf383181071f3f807f3ec377d901554282bcd`.
  Ruff, file-level mypy and Bandit passed after the additions.

The synthetic service is isolated from user data and removed after testing.
Further work must run the integrated source and required CI against the final
commit, assess prior checkpoints and variant persistence paths, and measure
any performance impact of the additional comparison query. A test of this
result contract does not establish safety of exception provenance or authorization.
