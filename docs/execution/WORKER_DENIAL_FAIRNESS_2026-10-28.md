# Worker policy denial and fair discovery — 2026-10-28

Status: **partial isolation under verification; fairness blocked**. On the entry
source the unknown-amount guard rejected bounded authorization before claim,
but one denial stopped the polling cycle. The successor isolates typed per-run
denials within the current page, reports a separate `denied` count and emits a
redacted warning. This does not address starvation across pages or restart.
Discovery-level denials and operational failures remain surfaced.

## Evidence

On runtime source `0611dc16dfab0652fdb134f9fc4c6b98875d6cb2`, a synthetic
test uses the real central policy and worker control flow with a substituted
repository listing and a test connection. In two cycles a tenant's first page
returns a run with unknown exposure and a bounded policy. Both cycles raise
`amount_missing_for_bounded_policy`; observed page reads are
`[(tenant_a, 0), (tenant_a, 0)]`. Neither tenant A's next page nor tenant B
is reached. The test deliberately asserts progress and fails, and is retained
outside the normal suite at
`output/worker-policy-denial-20261028/test_denial_starvation.py`; its log is
`output/worker-policy-denial-20261028/pytest.log` (1.43 s, one failure).
Test SHA-256 `ff838339c8c58d25e9167e35a4e0c527caa0f7329827b83c8cec4580a71a93bf`;
log SHA-256 `9c66ed8cbfc942b242a96ac32e9beef4bce9e891f6a487503ed7531f57027d9c`.
This does not establish a live PostgreSQL reproduction or a production policy
configuration.

At the end of the investigation, `HEAD` remained `0611dc16dfab0652fdb134f9fc4c6b98875d6cb2`;
the Git object hashes of the worker, shared policy and reconciliation repository
in the working directory matched that HEAD. Other CI files were being edited
concurrently and were not part of this reproduction.

`PostgresReconciliationRepository.list_runs` currently sorts by
`created_at DESC, id DESC` and uses LIMIT/OFFSET. Denied runs remain active.
Simply catching the exception and continuing a single page still leaves older
pages behind a full page of denied jobs. Persisting a numeric offset is not a
fairness proof: insertions and completion by this or another worker shift
offsets. `audit_policy_decision` without a sink emits a structured log, not a
durable ledger event. Counting a denial as `skipped` would conflate it with a
busy lease. The existing durable-job scheduler cursor tracks round-robin lane
indices and does not by itself provide a reconciliation keyset cursor.

A repository keyset draft was separately tested on a newly created synthetic
database migrated to head, using PostgreSQL 16.14 and an application role with
neither superuser nor BYPASSRLS. The combined focused suite reported 46 passed,
one skipped and one warning; this is not a worker fairness test. The draft is
not being integrated now: it is not wired to the worker, its cursor binds only
the tenant and can omit records if reused across workspace or entity scopes,
and it establishes neither progress persistence nor fairness across pages. The
retained [patch](../../output/erp-vision-20261028/draft-keyset-discovery.patch),
[tests](../../output/erp-vision-20261028/draft-test-postgres-reconciliation-keyset.py)
and [verification log](../../output/erp-vision-20261028/keyset-owned-migrated-verification-final.log)
are historical evidence for that experiment, not an enabled feature.

## Candidate contract

1. Distinguish a genuine central-policy denial from supplier, manifest,
   storage and programming errors with a typed denial carrying a safe reason
   and decision evidence. Continue other runs and tenants only for that typed
   per-run denial. Discovery-level failures and unexpected exceptions still
   fail the cycle. Never claim, complete, rewrite or silently cancel a denied
   run. Re-evaluate policy before any later claim.
2. Expose an additive, documented denial count and sanitized evidence reference
   rather than counting it as a lease skip. Propagate that field through worker
   and scheduler summaries and telemetry; maintain compatibility for existing
   constructors/readers. Persist an auditable event without raw amounts or
   financial rows using an authorized tenant-bound transaction; failures to
   record required evidence must fail closed.
3. Add a repository-owned keyset page contract using immutable
   `(created_at, id)` ordering, including a bounded scan watermark and a
   per-tenant, per-worker progress record that survives restart. Lock or
   version progress updates for concurrent uses of the same worker identity.
   Every pass eventually wraps to re-evaluate denied runs and newer arrivals.
   A fixed eligible record is eventually examined only assuming recurring
   successful worker cycles, finite work within each bounded pass, and an
   available database; no unconditional fairness guarantee is made under
   unbounded arrivals, persistent outages or arbitrary administrative changes.
4. Preserve the old list API and introduce a versioned migration, narrowly
   scoped grants and RLS for the progress/evidence owner. Specify rollback and
   populated upgrade/restore before enabling the new discovery contract.

An in-memory cursor or offset-based experiment can demonstrate bounded local
progress, but it loses progress on restart and cannot prove fairness under
concurrent inserts/completions; it is not suitable as the default fix. A
single-page denial catch without durable evidence and fairness is likewise not
eligible as a complete fix. The partial successor deliberately keeps this
release blocker open.

The additive `denied` field has a default, preserving existing constructor
calls; it changes dataclass-to-dictionary representations. Compatibility with
external consumers that enforce closed schemas has not been established. The
warning and current policy logger are not a durable denial ledger. Matcher
exceptions raised after a committed claim are treated as execution failures,
including a `BusyError`; a pre-claim busy lease remains a skip. Focused tests
cover the distinction with test doubles; final native and hosted results must
be recorded separately.

## Required verification

First retain RED tests showing one denied item plus an allowed item within a
page, a full denied page followed by an allowed page, and a denied tenant before
an allowed tenant. On real migrated PostgreSQL with restricted roles, test
duplicate timestamps, insertion and completion between pages, policy changes,
retries, concurrent workers, crash before and after progress/evidence commit,
restart, wraparound, rollback/restore and deny-without-claim. Check that a
revoked grant never authorizes a claim and that unexpected infrastructure or
configuration failures remain surfaced. Validate bounded resource use and
compatibility of summaries and existing CLI/API readers before acceptance.
