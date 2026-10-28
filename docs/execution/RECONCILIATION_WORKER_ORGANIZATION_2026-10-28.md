# Reconciliation worker organization authority — 2026-10-28

**Status: locally tested, not yet qualified on PostgreSQL or hosted CI.** This
bounded change verifies the organization at two pre-claim policy checks; it
does not qualify tenant discovery, post-claim revocation, the entire worker, or
the ERP release.

## Reproduction and cause

On parent HEAD `32e6cffb2911987c1b788ce73fe5057f32e8c116`, a synthetic service
account context authorized for `org_a`, a tenant, a workspace and an entity
was accepted by `PostgresReconciliationWorker._authorize_scope` because its
policy context and invocation omitted the selected organization. Evaluating
the same synthetic context with `organization_id="org_b"` using
`CentralPolicyEngine` returned `organization_scope_denied`. This is a policy
boundary reproduction, not an observed PostgreSQL cross-organization claim.

The worker previously passed `organization_id` to the database transaction
and `claim_run`, but not its central policy guard. The shared guard already
supports a hierarchy-aware supplier and checks exact context identity. RLS
compares persisted organization against the selected database setting; that
comparison alone does not establish that the worker identity is authorized to
select the setting.

## Change and compatibility

The worker's settings now optionally accept the existing four-argument
`policy_context_hierarchy_supplier(tenant, workspace, organization, entity)`.
When policy is configured, organization-scoped processing requires that
supplier; a tenant-only or three-argument supplier remains valid for lanes
without an organization. The selected organization is included in the scoped
preflight and rechecked in the claim transaction before `claim_run`. The shared
guard requires a matching context and checks organization grants. A revoked
grant observed by the second check prevents the claim.

This is a deliberate compatibility change: a previously configured
three-argument supplier processing organization-scoped runs must be upgraded
to the hierarchy supplier, returning the exact selected organization and its
actual authorization grants. Missing hierarchy configuration raises an error;
`process_once` stops at that run rather than counting it as a policy denial.
Tenant-wide discovery occurs first. A hierarchy supplier must also support
discovery and tenant preflight calls with the narrower scopes set to `None`.
The existing `allow_unbound_hosted_policy=True` opt-out remains unchanged: it
does not evaluate organization authorization and must not be described as
secure policy enforcement. No schema or persisted financial record is changed.
Reverting the worker change reopens the documented missing-organization guard.

## Local verification and limits

Before implementation, the new tests returned three failures and one success:
the legacy scoped supplier reached a connection instead of failing preflight,
and the hierarchy setting did not exist. After implementation, the command

```text
output/release-blocker-20261025/venv312/Scripts/python.exe -m pytest -o addopts='' -q -ra tests/test_reconciliation_worker_organization_scope.py tests/test_postgres_reconciliation.py tests/test_postgres_reconciliation_persisted_json.py tests/test_governed_worker_policy.py tests/test_worker_policy_amount_20261028.py
```

ran on Windows/Python 3.12 against changed files with **92 passed, 1 skipped,
1 legacy financial-input warning in 3.90 s**. The skip was the existing
live-PostgreSQL test without its service. Nine new synthetic tests cover scoped
grant denial, context mismatch, missing hierarchy/manifest, pre-claim grant
revocation, discovery behavior, legacy unscoped compatibility and the explicit
unbound opt-out. They use an in-memory boundary and repository; they are not
evidence of real SQL, RLS, rollback, identity authentication or deployed grant
configuration. The existing organization-scope test now provides an explicit
organization grant and keeps its original assertions. Ruff on all three changed
Python files and mypy on the worker passed.

At this run, SHA-256 values were worker
`4eeec1a59c044b373bf5fdb5a2ca6592139017b8a0ce43a4b214cea284c18ce0`, new test
`9ba68fe2e0b3d6a781bfc2737a5f62afc7448acbdfce1a6988bd9679dd221b5f`, existing
test `b1a798a6a4520784ad8b6da109cd9691215a56cd0cdd0f24b7ddcabf0148e840`,
and `output/erp-vision-20261028/worker-organization-focused.log`
`a93be3572bac57c654b53f77edd501906fb6f7fc44e18d568424ced1cae3c2a0`.

Open gates: test final source on an owned PostgreSQL database with a restricted
role and real policy contexts, denied organization and no partial claim,
revocation and concurrent transactions; verify hosted CI and migration/restore
independently. Tenant-level discovery may expose run metadata/rules before a
per-run organization check, and permission withdrawal after a committed claim
is not rechecked before partitions, heartbeat or completion. Supplier trust,
durable decision audit, financial exposure authority, organization-free legacy
records and arbitrary SQL privileges need separate assessment. This work does
not prove those properties or close the broader security blocker.

Subsequently, a synthetic PostgreSQL 16.15 run with changed, uncommitted
source passed the native case in 13.469 s with no skip. The application role
was not superuser, BYPASSRLS, CREATEDB or CREATEROLE, and `reconciliation_runs`
had FORCE RLS. Denied organization, mismatched or absent scope, and revocation
before claim left run rows and child-table counts unchanged; an allowed run
completed with one match. Fixture grants covered seven named tables and do not
prove production least privilege; child-table contents were not compared in
full. Tracked-file hashes matched before and after this run, but the checkout
was not committed. Receipt: `output/erp-vision-20261028/worker-org-native-20261028.json`;
log SHA-256 `b17966c068c50a564c909ed7395d27cd6c003d8c90ca160db514b1dad682128b`.
An earlier attempt with missing source dates reached the worker but failed
because the matcher emitted an `exception_id` field rejected by the worker;
the negative log is `output/erp-vision-20261028/worker-org-native-exception-id-failure-20261028.log`.
This is an independent open data-quality path and is not repaired by the
complete-input success. Final-source, hosted CI and full recovery gates remain.
