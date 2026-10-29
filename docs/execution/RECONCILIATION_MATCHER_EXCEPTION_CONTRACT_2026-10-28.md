# Reconciliation matcher exception contract — 2026-10-28

**Status: reproduced; repair and native validation pending.** This record is
an investigation, not a claim that exception persistence or replay is safe.
The analysis used parent HEAD `96c9f853dfba5d0fc6fbf27a12e9ef0c31fdd843` with
the worker source hash below; other local changes may be present.

## Observed failure

The PostgreSQL synthetic organization test, with its previously saved failing
log `output/erp-vision-20261028/worker-org-native-exception-id-failure-20261028.log`
(SHA-256 `ee2a20f46e83b488b6aa93fde2ed23c3acf252e8494540659b9616c674d13046`),
created inputs without dates. An authorized call to the real worker returned
`Failed`; its persisted error was `matcher exception contains unsupported
fields: exception_id`. This log is a failed native fixture, not a successful
financial reconciliation or proof of partial-output rollback. The succeeding
organization test used a different fixture and does not close this failure.

In [the deterministic engine](../../reconforge/reconciliation/deterministic_engine.py),
data-quality and candidate-budget ambiguity exceptions carry `exception_id`.
[LocalDeterministicMatcherAdapter](../../reconforge/workers/postgres_reconciliation.py)
returns those exceptions unchanged from `_match_records`. In non-partitioned
execution, `_persist_and_complete` rejects any key outside `_EXCEPTION_FIELDS`
before `append_exception`; in partitioned execution the repository independently
rejects the same key in `append_partition` before persistence. The failure is
not restricted to missing dates: any engine outcome that emits the identifier,
including invalid amount/currency or candidate-budget ambiguity where reachable,
requires examination. Financial impact beyond the failed reconciliation and
unpersisted exception is not established by these observations.

## Independent synthetic probe

On Windows, Python 3.12.13, the following read-only probe used synthetic USD
records and an in-memory simulated collision; it did not access PostgreSQL:

```text
output/release-blocker-20261025/venv312/Scripts/python.exe output/erp-vision-20261028/matcher-exception-contract-probe.py
```

The original and reversed input order both produced a `data_quality` /
`MISSING_DATE` exception with `EXC-A4E0695572461108B3FC`, and the worker
validator rejected `exception_id` both times. A real adapter partition was
also rejected by repository validation before any SQL. This one permutation
example does not prove identifier stability across all duplicate, identity,
rule or historical replay cases. The engine derives the identifier from
exception type, side, source ID, reason, title, explanation, severity, score
and evidence except top-level source location; record lineage includes duplicate
ordinals. [Repository identity](../../reconforge/infrastructure/postgres_reconciliation.py)
instead hashes tenant, run, type, side, source ID and reason code. They are
different identities with different scope and collision semantics.

Probe file SHA-256
`69b4416254aa5ad789c7b471446659c425de001a7cf47fcdffc1b02ad4b1cf6d`;
log `output/erp-vision-20261028/matcher-exception-contract-probe.log` SHA-256
`e8b93e81b29be32c2e4b56d4dfcf7786cf6e02a36e8801bbe4a821470aa5a0f5`.
Source file SHA-256 at reproduction: worker
`4eeec1a59c044b373bf5fdb5a2ca6592139017b8a0ce43a4b214cea284c18ce0`,
repository `a49033d36cfaac4995c1118bfcfdd3f2bb760680df5ad3b048413f258d183d19`,
engine `da30b51f0b95d3659a7e4fb1ad2e7e0a684d961e1c519963ff2cfac39d924de2`.

## Collision and replay concern

`append_exception` uses `ON CONFLICT DO NOTHING` and requires a returned row;
an existing ID can therefore produce an integrity error. The batch method
selects an existing ID after a conflict without comparing the requested fields
or evidence, and `append_partition` can then write a checkpoint whose digest
describes the requested output. A synthetic fake-connection probe returned
stored evidence `{"v":"stored"}` when the requested colliding payload had
`{"v":"changed"}`. It exercises the batch branch, but does not establish
that a supported real-engine dataset creates that collision or that a live
PostgreSQL checkpoint was committed. Do not infer stable replay or evidence
preservation from this result.

Further synthetic RED reproduction uses the real adapter with the current
`canonical-multiset-occurrence-v1` identity policy, two partition values and
both input sides. Two different left `source_id` values provide the same
`attributes.id`; the adapter respects that attribute as the matcher `id`.
Missing dates yield two exceptions with different engine identifiers and the
same `(type, side, source_id, reason)` storage identity fields. Because the
tenant and run are also identical, the repository's current identity formula
would select the same exception row. The test's uniqueness assertion fails as
intended with exit 1. This proves an adapter output collision, not yet an
actual database conflict or committed checkpoint. `attributes` is accepted by
the current canonical request and serialized by input registration; API/SQL
reachability and a native PostgreSQL collision must still be demonstrated.

The reproduction is `output/erp-vision-20261028/matcher-exception-collision-red.py`,
SHA-256 `c069384b5d70ffd50c53eaf7fdc848e3e3892c089daa2ccb0bb02d033be5168e`;
its log is `matcher-exception-collision-red.log` in the same directory,
SHA-256 `3dfe00de66cec9ea7b1e6d228e42ac8e67932274619d4f745587d5981c07aeed`.
This reachable output collision is why the proposed adapter bridge remains
unimplemented until the storage conflict and checkpoint semantics are handled.

## Candidate fail-closed collision containment

This is a design proposal, not an implemented fix. Keep the existing row-ID
formula and historical records unchanged. For a new exception batch, validate
and normalize every requested item, run the existing insert-with-conflict
operation, and resolve the actual row for **every** prepared item. Compare
each item with its returned or pre-existing row before a checkpoint can be
written. Checking only IDs missing from `RETURNING` is insufficient: two
different items within one SQL chunk can share an ID, so the first appears in
`RETURNING` while the second is discarded. Any missing or unequal row must
raise a safe integrity error in the same transaction; no requested evidence may
be silently substituted. Exact repeated requests can return the existing row
without modifying it. Consider duplicate identical items within *one* batch
separately from replay of the same batch: physical row counts and checkpoint
counts must not imply multiple persisted rows when only one exists.

The equality contract must include tenant, run, type, side, source and reason,
plus title, explanation, severity, risk score, requested owner and evidence. Use
the repository's actual input validation, PostgreSQL `NUMERIC` equality and
JSONB value equality, rather than comparing raw JSON strings or imposing a new
decimal rounding rule. Explicitly define how `None` and empty evidence are
normalized. The current repository has no application update route for these
rows, but owner/workflow fields have mutable-looking semantics; if another
authorized writer can change them before completion, a strict check may reject
a formerly valid replay. Fail closed rather than overwrite; document and test
that behavior before presenting it as compatible. Do not expose protected row
content in conflict errors.

The standalone `append_exception` currently errors on any conflict because its
insert returns no row; returning an identical existing row would be a deliberate
contract change that requires tests. Conflicting content must remain rejected.
No test or new behavior should delete or rewrite an existing evidence row.

For concurrency, `append_partition` and the batch repository take the parent
run row lock; the current
[child-write trigger](../../reconforge/infrastructure/postgres_reconciliation_input_seal.py)
also locks the parent row and requires READ COMMITTED for child writes. This
can serialize concurrent writers only when the supported migrated trigger is
present and cannot be disabled by the application role. Verify the actual
catalog, grants, trigger state, transaction isolation and behavior with two
connections. Do not infer protection against privileged SQL or configurations
that bypass the trigger.

The real PostgreSQL regression must start with a fresh, explicitly owned
database and non-superuser/non-BYPASSRLS role. Cover same identity with changed
evidence within a batch, across chunks and across committed partitions; equal
replay, numeric/JSONB semantic equivalence, changed owner/content, and missing
row behavior; two concurrent attempts; failure after earlier writes in the
same transaction; restore and re-read. Assert that a conflicting transaction
rolls back its attempted result/exception writes and creates no checkpoint for
that partition. An earlier, independently committed partition and its evidence
must remain intact; this is not an all-or-nothing transaction for the whole
run. The test must prove this on actual PostgreSQL rather than only a fake.

Existing checkpoints currently return early on matching input/output counts and
hash without re-reading their persisted rows. A new conflict guard does not
retroactively verify those historical checkpoints. Do not rewrite or silently
reinterpret them; investigate versioned verification and compatibility as a
separate gate. The distinct `append_results_batch` conflict path also needs an
independent audit before any whole-partition integrity claim. The adapter
bridge remains blocked until these contracts, tests and their interaction with
the owning repository change are reviewed.

## Candidate repair and verification

One bounded candidate is to adapt the engine's output once at the hosted
adapter boundary: preserve the engine identifier under a reserved, explicitly
versioned evidence key and remove only the unsupported transport field, while
keeping the repository-generated row ID unchanged. A conflicting preexisting
reserved key must be handled explicitly rather than overwritten. This candidate
would reach both ordinary and partition paths; it is not yet implemented or
reviewed. Changing the repository row identity to the engine ID risks changing
historical contracts and needs a migration and compatibility policy. Silently
dropping the engine identifier loses provenance. Adding `exception_id` only to
the worker allowlist is insufficient because repository methods reject it.

Required evidence includes red-first tests for invalid input and ambiguity,
ordinary and partitioned paths, reserved-key collisions, permutations and
duplicate lineage, unchanged valid outputs, and exact engine-ID retention;
real restricted-role PostgreSQL integration must show a complete run, the
stored evidence, transactional failure without partial output, and checkpoint
retry/crash/restore. Independently exercise conflicting batch content and
require either verified equality or a fail-closed result before claiming the
checkpoint represents persisted rows. Review any change to partition output
hash against prior checkpoints; historical policies and successful checkpoints
must not be silently reinterpreted. Entity isolation, financial-exposure
authority, and legal or operational qualification remain separate gates.

## Exception collision containment — local development evidence

An in-progress repository change checks exception batch identities before any
insert and refuses duplicates within one call, including identical duplicates.
After each insert chunk, a parameterized SQL comparison checks every expected
row using PostgreSQL JSONB and NUMERIC equality. Missing or different content
raises an integrity error; a separate, exactly matching replay may return the
existing row. `workflow_status` and timestamps are not source content, while a
changed `owner_id` is conservatively treated as a conflict because the schema
does not preserve an immutable original owner. Therefore a replay after a
legitimate reassignment may now fail; this deliberate compatibility limit
requires a future versioned origin/assignment contract. Existing row IDs and
evidence are neither rewritten nor silently reinterpreted.

The initial containment failed a further test: after catching its Python
integrity error *inside* a transaction, the caller could commit result and
exception writes that preceded the conflict. The red PostgreSQL log
`output/erp-vision-20261028/exception-collision-caught-commit-red-20261028.log`
has SHA-256 `c9945aceb9104932af0e1ac6530e13b107dcd9b9cb7c9b40e09cab54c83b2453`.
The subsequent candidate places savepoints around the full validated partition
write and standalone exception batch, rolling them back before re-raising. It
does not commit the caller's transaction. The partition still validates its
payload before accessing the database; an autocommit call without a surrounding
transaction fails before writing. Explicit duplicate rejection changes the
previous behavior for duplicate IDs within the same batch.

On parent HEAD `43d8d051ea14046e78f86c2723f4c5aaec0afa02`, with uncommitted
source hashes recorded below, a task-owned PostgreSQL 16.15 database using a
non-superuser/non-BYPASSRLS app role ran `tests/test_reconciliation_exception_collision.py`
under `PYTEST_ADDOPTS=-p tests.mandatory_native_gate`: **17 collected, 17
passed, zero skips/xfail**, in 14.969 s. One test exercises the pure engine;
the other 16 use PostgreSQL. Coverage includes mismatched evidence in a chunk
and across calls, same-batch duplicates, exact single/batch replay, JSONB
boolean versus number, JSON key order and numeric scale, conservative owner
conflicts, unchanged workflow state, two concurrent conflicting writers,
rollback of earlier result and exception writes even when the caller catches
the error, caller rollback, nested same-named savepoints, and autocommit
refusal. All 4,728 tracked file contents matched before/after the run;
the untracked test file also matched its before/after hash. This is not a
committed-source result or proof of production grants, restore, all replay, or
the adapter bridge.

The full native command, environment record, role flags and source snapshot
are retained in `output/erp-vision-20261028/exception-collision-savepoint-green-20261028.json`;
its log has SHA-256 `9d3547a4115618aed69aea07d46239df29bbc6c7c46c1d1d3b0686ab03a371f9`.
The repository source SHA-256 was
`81d4795db6ac9e3077c05152e9024298c93bae8e0f96c6d93e1e9322e327b6bd` and test
SHA-256 `bbf9edb2b783532fdaf1c77e4a6f54ed74dae4d7c7ccc6fdc7d7f6a7ef248417`.
The broader local Python suite ran 124 passed and 17 skips (the 16 owned-database
cases above and one separate live-PostgreSQL prerequisite), with two warnings;
Ruff, file-level mypy, Bandit and bound-SQL assertions passed. A previous Bandit
B608 finding on string concatenation was resolved by joining only fixed SQL
placeholders; hostile input remains parameter-bound.

The adapter's engine exception identifier remains incompatible and has **not**
been bridged by this change. Existing checkpoints return without inspecting
their stored child rows, and `append_results_batch` has a separately identified
conflict-content gap. Neither historical checkpoint integrity nor general
partition integrity follows from this exception-only containment. Hosted CI,
frozen-commit native verification, upgrade/restore, rollout and performance
remain open.

### Compatibility and canonical-source follow-up

Independent review found the savepoint wrapper initially touched the database
for `append_exceptions_batch(items=[])`, whereas the historical contract
returned `[]` immediately, even without a usable connection. The focused
no-database test reproduced that regression before correction. The public
method now returns for an empty batch before entering the savepoint; a separate
autocommit test covers the same compatibility boundary. Non-empty calls retain
the tested savepoint and collision handling. On 2026-10-28 the final combined
development tree at parent HEAD `43d8d051ea14046e78f86c2723f4c5aaec0afa02`
passed **20/20 tests with zero skips or xfails** under the mandatory native
gate on task-owned PostgreSQL 16.15, in 16.625 seconds. The app role had neither
superuser nor BYPASSRLS; the tracked source fingerprint was unchanged before
and after (`437f655bb74e7dd6af699f54b88d0853eafa52f2b768b0c95146667e8bf57ba1`),
as was the untracked test file. The repository source SHA-256 was
`50fc754b4825ee26cb52488030dee96b8abadb554348c06233e35b02ae488735` and the
test SHA-256 was
`1baf19be68d15b82d1097360a417d78694c58a06e45538f017a3c969b0ab34ce`.
The log at `output/erp-vision-20261028/exception-collision-empty-contract-green-20261028.log`
has SHA-256 `bede608dc9900d90eb90dd055c5b1a1c4e8a5efff731fc159b14665e1c594fff`;
its companion JSON records the image and snapshot. This is a local uncommitted
source result, not a hosted or release verification.

The earlier engine collision reproduction above was accurate on its stated
source, but a later in-progress canonical-source guard now rejects its
contradictory `attributes.id` and `source_id` before the engine. A current
regression checks that rejection. Repository collision, replay, SQL binding,
transaction, and concurrency tests now use explicitly synthetic, distinct
payloads with the same storage identity; they do not claim those payloads
still arise from the guarded adapter. The original probe and negative logs
remain historical evidence. The repository contract must still fail closed
for conflicting direct inputs, independently of the adapter's guard.
