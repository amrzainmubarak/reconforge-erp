# Reconciliation claim authority: investigation and test design

Investigation entry: `c44a71110dd63f3ef2372c0bc8d451f91d3424d7`, with
an uncommitted worker-policy draft under review. This record describes the
source and a proposed design; it does not claim a live PostgreSQL reproduction
of the supplied-amount case or a completed fix. See
`RECONCILIATION_EXPOSURE_REPLAY_2026-10-28.md` for the independently observed
Decimal-context and legacy replay issues.

## Data flow and locking

* `reconforge/workers/postgres_reconciliation.py::process_once` reads a page of
  active runs, extracts `rule_json.policy_amount`, then passes that value to
  `process_run`. `process_run` is also callable directly with an amount chosen
  by its caller. Its preliminary and transaction-scoped authorization checks
  currently evaluate that argument rather than the locked persisted run.
  An independent fake-repository test has shown a lower supplied amount may
  pass a synthetic bounded policy while the stored value exceeds the bound;
  production callers and a live exploit have not been established.
* In the claim transaction, authorization currently occurs **before**
  `PostgresReconciliationRepository.claim_run` takes `_run_row(..., lock=True)`.
  The latter acquires `FOR UPDATE`, then changes the lease and appends audit and
  outbox effects in that transaction. A policy denial must roll all of these
  effects back and must not be handled as a matcher failure that marks the run
  failed.
* `register_input` and migration `0097_postgres_reconciliation_input_seal.py`
  take the same parent row lock for input writes. Inputs may still be inserted
  while the run is queued and its attempt is zero. Once the parent is locked in
  a READ COMMITTED transaction, those compliant writes serialize with claim;
  after a successful claim the seal rejects new inputs. This depends on the
  installed trigger, permissions and matching tenant/workspace/entity RLS;
  test the actual migrated schema rather than assuming this for arbitrary SQL
  privileges or old installations.
* `rule_json.policy_amount` is derived at API submission time and persisted;
  it is not proof of an exact current input set. The discovery read and claim
  transaction do not share a snapshot, the inputs can change before claim, and
  the user-supplied `input_hash` is not by itself proof of the full set. The
  amount can also reflect legacy context rounding. Do not silently relabel or
  rewrite historical values, results or checkpoint evidence.

## Safe incremental boundary

First test a deliberately narrow hardening: inside the scoped READ COMMITTED
claim transaction, lock the actual run, obtain its persisted metadata from
that locked row, then evaluate the execution policy using a trusted value
chosen by the application rather than the `process_run` argument, before
`claim_run` and before commit. An optional caller amount may be treated only as
an expected value: a mismatch fails closed with no lease or writes. This closes
the caller-versus-persisted-value gap only. It is **not** sufficient to claim
the amount reflects the entire current input set or that a financial ceiling
is safe. Missing or malformed values must remain unknown or fail closed, never
become zero. The design must also preserve tenant discovery behavior and
authorized legacy direct calls, or record a versioned compatibility transition.

For actual bounded financial authorization, derive or verify an exact,
versioned exposure against all canonical inputs under the same parent lock,
including missing/invalid values, every side, currency, policy and input
fingerprint. An exact PostgreSQL numeric aggregate can avoid ambient Python
Decimal rounding, but must reject or explicitly classify nonfinite and missing
amounts and must not lose lineage; unbounded `list_inputs` materialization is
not an adequate scale claim. `PolicyEvaluationContext` currently represents
amount and bound as bare Decimal without currency. A sum across currencies or
a same-currency sum compared with a limit of unknown currency is not a sound
financial authorization. Bind currency and policy/registry version to both
amount and limit, or reject unsupported bounded decisions. Reconcile recorded
legacy retries, jobs and checkpoints through an explicit policy, compatibility
reader and audit trail; do not retroactively attest old outcomes.

## Pooling and authorization freshness

`PostgresTenantBoundary.transaction` leases a connection from its factory;
`PostgresConnectionPool` permits `max_size=1`. The supplied authorization
callback may itself require a connection. Calling it while a transaction owns
the sole pooled connection can wait until the acquisition timeout; the existing
transaction-scoped `_authorize_scope` already permits this configuration.
Do not fix the new race by adding another independent acquisition under a row
lock. Resolve a bounded policy snapshot before acquiring the transaction and
evaluate it locally on the locked amount, **or** define a transaction-aware
supplier that uses the same connection. A snapshot alone does not prove that
permissions were not revoked before commit: a bound revision or authoritative
grant rows must be checked/locked in that same transaction for that guarantee.
Document the existing revocation semantics until this is demonstrated. Keep
lock duration bounded and avoid remote calls under locks.

## Required synthetic tests

Use a disposable migrated PostgreSQL database with RLS enabled and forced,
and an ordinary runtime role without superuser or BYPASSRLS; no customer data.
Existing entry points include `tests/test_postgres_reconciliation.py`,
`tests/test_postgres_reconciliation_input_seal.py`,
`tests/test_postgres_reconciliation_seal_restore.py`, and
`tests/test_api_server_reconciliation_live.py`.

1. Store exposure `20`, configure ceiling `10`, call `process_run` with `1`;
   assert denial and unchanged lease, attempt, run, inputs, results,
   checkpoints, audit and outbox. Repeat via `process_once` and with a direct
   caller passing no amount. A permitted exact same-value path must still work.
2. Pause a writer after a queued input insert starts; race the claim with a
   separate restricted connection. In both lock orders, assert that either
   the committed input is included in authorization or it is rejected by the
   seal after claim. Verify no partial effects, deadlock or stale approval.
3. Challenge missing, malformed, negative and huge amounts, scientific text,
   nonfinite database numerics, negative/positive and mixed currencies, and
   different Decimal precision/rounding contexts using an independent exact
   oracle. Bound behavior for real backends and input sizes separately.
4. Exercise policy revocation between snapshot and claim, pool size one and
   saturation with concurrent workers, tenant/workspace/entity denial and
   restricted-role SQL attempts. State what a fake policy cannot prove.
5. Preserve populated legacy rules, inputs, decisions and checkpoints through
   upgrade/restore/rollback. Test retry with exactly the full old request and
   with missing, extra, duplicate or changed records; do not trust client hash
   alone or mutate old evidence. Record whether jobs remain queued or require
   human intervention; no false `skipped` success.

No code or migration is implemented by this design. Complete CI and final-source
native recovery checks remain required.
