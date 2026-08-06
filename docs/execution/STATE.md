# Execution State

Updated: 2026-08-06

## Current phase

Phase 4 — Global Capability Expansion (active; Phase 1–3 owner/team scope remains complete)

## E-423 — PostgreSQL migration-head compatibility repair (passed locally)

- Updated `tests/test_alembic_postgres.py` to expect the current Alembic head
  `0065_pg_deferred_tax` after the deferred-tax persistence migration.
- The isolated PostgreSQL 16 migration contract passes through upgrade to head,
  downgrade to `0051_access_policy_lifecycle`, re-upgrade, downgrade to
  `0011_postgres_recon_ckpts`, and final re-upgrade; expected schema presence
  and absence checks remain green.
- This closes a stale test assertion exposed by the server-boundaries log. It
  does not prove native backup tools on every runner, statutory/legal-book
  posting, live providers/write-back, independent HA/DR, distributed IAM,
  scale/soak, or production readiness.

## E-424 — Python 3.11 all-extras collection boundary (passed locally)

- Recreated the dependency profile used by the current CI test matrix with
  `uv sync --locked --all-extras --no-editable --python 3.11`. The lock installs
  the optional observability, backup/connector cryptography, CBOR, and WebAuthn
  packages that were missing in the historical collection log.
- The seven affected modules collect 49 tests and execute 48 passes with one
  declared live-PostgreSQL skip under the refreshed Python 3.11 environment.
- The current `.github/workflows/ci.yml` already uses `--all-extras`; this local
  result confirms the import boundary is covered by that profile. It does not
  establish a hosted rerun, Gitleaks approval, live provider/write-back,
  statutory close, independent HA/DR, scale, or production readiness.

## E-425 — Full Python 3.11 regression after CI dependency verification (passed)

- `uv run pytest -q --tb=short -ra` exits 0 in 366.7 seconds on the refreshed
  locked Python 3.11 all-extras environment.
- Only declared optional-service/platform skips and existing legacy financial
  input/framework warnings remain visible. No collection or test failure
  remains in this local run.
- This confirms local compatibility for the current test profile; hosted
  matrices, statutory close, live provider/write-back, independent HA/DR,
  distributed IAM, scale/soak, and release approval remain open.

## E-426 — Fresh repeated PostgreSQL HA/DR drill (passed locally)

- The repeated Docker drill ran three complete cycles on Docker Engine 29.6.2
  with PostgreSQL 17.10 Alpine, synchronous standby fencing, encrypted native
  backup/isolated restore, promotion, rejoin, failback, and labelled-resource
  cleanup.
- All three runs passed with zero acknowledged transaction loss and cleanup;
  failover RTO ranged from 11.084s to 11.175s and failback RTO from 0.981s to
  1.023s. The schema-valid report is retained at
  `docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION_2026-08-05.json`.
- Boundary: two containers on one host with a manual controller and synthetic
  data/key. Independent failure domains, quorum/witness, automatic failover,
  site-loss recovery, and production SLO remain unverified.

## E-427 — Hosted scheduler/outbox central-policy boundary (passed locally)

- Added the shared `require_service_worker_policy` guard and opt-in settings
  fields to the PostgreSQL scheduler and transactional-outbox workers.
- Configured workers now require a matching service-account actor, exact
  tenant-only scope, and `schedule.run`/`outbox.publish` before opening a
  repository connection. Focused allow/deny contracts pass 4/4.
- Existing unconfigured worker and Community/SQLite behavior remains
  compatible. Universal worker/export/UI adoption, workspace/entity worker
  scope, federation, distributed invalidation, and production IAM remain open.

## E-428 — Full local regression after hosted worker IAM (passed)

- `uv run pytest -q --tb=short -ra` exits 0 in 345.7 seconds after E-427.
- Only declared external-service/platform skips and existing financial/framework
  warnings remain; no collection or executed test failure is present.
- Boundary: local Windows regression only. Hosted matrices, live providers,
  statutory/legal-book close, independent HA/DR, distributed IAM, scale/soak,
  coherent breadth, and release approval remain open.

## E-429 — Static/security/package gates after hosted worker IAM (passed locally)

- Ruff passes; Mypy reports no issues in 453 source files; Bandit passes with
  existing nosec/test-comment warnings; pip-audit 2.10.1 reports no known
  vulnerabilities after excluding the local project distribution.
- Package build and `git diff --check` pass. This is local evidence only; the
  project exclusion, hosted supply-chain/provenance gates, signed artifacts,
  and release approval remain explicit.

## E-430 — Current no-network install, identity recovery, and rollback drill

- Docker Engine 29.6.2 executed the current 0.7.1 bundle on
  `python:3.14.1-slim` (digest-pinned), with 68 entries and 100,386,256 bytes.
  The container used network mode `none`, read-only root/bundle mounts, bounded
  tmpfs, hash-locked no-index installation, and doctor success.
- Identity recovery restored two local users, preserved admin permission and
  the audit chain, rejected a wrong AES-256-GCM key atomically, and restored no
  old sessions. The tagged 0.7.0 to 0.7.1 cutover used zero network inputs and
  rolled back to the exact prior content digest.
- Boundary: connected bundle assembly, one Linux/Python runtime and one run;
  signature trust, physical transfer custody, OCI offline verification,
  hardware-backed keys, cross-platform repetition, HA/DR, and production
  readiness remain unverified.

## E-407 — Acquisition deferred-tax bridge (passed locally)

- Added `acquisition-deferred-tax-bridge-v1`, a deterministic non-posting
  artifact for source-bound temporary differences. It uses exact `Money` and
  Decimal tax rates, explicit asset/liability signing, the installed currency
  registry rounding policy, canonical item ordering, source/policy lineage,
  independent maker-checker actors, and replay/tamper verification.
- Added the closed JSON Schema, CLI command
  `reconforge consolidation acquisition-deferred-tax`, and five focused tests
  covering arithmetic, permutation determinism, maker-checker/rate rejection,
  tamper detection, schema validation, and the read-only CLI contract.
- This is a calculation bridge only. It does not decide tax-law recognition,
  valuation allowances, statutory/legal-book treatment, tax filing, journal
  posting, live rates, or production close readiness.

## E-408 — Full local suite after deferred-tax bridge (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 325.9 seconds; only declared
  skips and existing deprecation/legacy-input warnings remain.
- The package build already succeeded and the changed-file Ruff, Mypy, and
  diff-check gates pass. Mypy reports no issues in 448 source files after the
  new domain and CLI contract.
- This is local compatibility evidence only. The global objective remains open
  for statutory close semantics, live providers/write-back, independent HA/DR,
  distributed IAM adoption, scale/soak, and coherent industry breadth.

## E-409 — HA/DR quorum safety hardening (passed locally)

- The orchestration-neutral HA/DR state machine now requires at least one
  witness failure domain independent from all voter domains.
- Witness acknowledgement remains mandatory but is no longer counted as a
  voter when checking quorum during failover or repromotion; a three-voter
  topology therefore cannot elect with only one healthy voter plus a witness.
- Focused HA/DR simulation tests pass 5/5 with Ruff, Mypy, and diff-check.
  This improves model safety only; it does not provide independent-host,
  network, external-fencing, automatic-failover, wall-clock RPO/RTO, or
  production-SLO evidence.

## E-410 — Final local gates after HA/DR safety hardening (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 326.3 seconds with only declared
  skips and existing deprecation/legacy-input warnings.
- Ruff, Mypy (448 source files), Bandit, pip-audit, package build, and
  `git diff --check` all pass. The local package is internally consistent.
- This remains local evidence only. Hosted Python matrices, live provider
  contracts/write-back, statutory close, independent HA/DR, distributed IAM,
  scale/soak, and coherent breadth are not complete.

## E-411 — Server-scoped evidence read policy (passed locally)

- PostgreSQL evidence list, coverage, record, and non-sensitive drill-down
  reads now re-evaluate `evidence.read` OR `evidence.manage` against the
  authenticated tenant/workspace before the repository adapter.
- Sensitive drill-down retains the separate `evidence.manage` gate. Local
  SQLite behavior is unchanged; the focused server contract captures every
  read/manage/verify policy call.
- This closes a route-family IAM gap only. Worker/export/UI adoption,
  federation, distributed invalidation, live providers, independent HA/DR,
  and production IAM assurance remain open.

## E-412 — Final local gates after evidence-read IAM adoption (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 322.8 seconds with only declared
  skips and existing deprecation/legacy-input warnings.
- Ruff, Mypy (448 source files), Bandit, pip-audit, package build, and
  `git diff --check` all pass after the evidence route changes.
- This is local regression/package evidence only; the global objective and
  GitHub publication remain open pending external/runtime workstreams.

## E-413 — Server-scoped legacy audit policy (passed locally)

- Legacy PostgreSQL ledger audit events and chain verification now re-evaluate
  tenant-wide `audit.read` and `audit.verify` before the tenant-scoped adapter;
  no synthetic workspace is introduced.
- A focused fake-adapter test captures both calls, and server-identity plus
  audit-administration regressions remain green. This is route IAM evidence
  only; complete worker/export/UI adoption, federation, distributed
  invalidation, providers, independent HA/DR, and production IAM remain open.

## E-414 — Final local gates after legacy-audit IAM adoption (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 325.3 seconds; only declared
  skips and existing deprecation/legacy-input warnings remain.
- Ruff, Mypy (448 source files), Bandit, pip-audit, package build, and
  `git diff --check` all pass after the legacy audit route change.
- This is local regression/package evidence only. External providers,
  statutory close, independent HA/DR, distributed IAM, scale/soak, coherent
  breadth, hosted matrices, and production approval remain open.

## E-415 — Server-scoped legacy Finance reads (passed locally)

- Legacy PostgreSQL ledger branches for summary, accounts, trial balance,
  entries, and entry lookup now re-evaluate `finance_core.read` against the
  authenticated tenant before adapter access. Tenant-wide semantics are used
  because this compatibility ledger boundary rejects workspaces.
- Existing account/entry mutations retain their workspace-bound
  `finance_core.manage` checks. A focused test captures five read gates, and
  server identity/Finance Core regressions pass.
- Boundary: route IAM only; statutory posting, worker/export/UI adoption,
  federation, distributed invalidation, live providers, independent HA/DR,
  and production IAM remain open.

## E-416 — Final local gates after legacy Finance-read IAM adoption (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 322.7 seconds with only declared
  skips and existing deprecation/legacy-input warnings.
- Ruff, Mypy (448 source files), Bandit, pip-audit, package build, and
  `git diff --check` all pass after the legacy Finance route changes.
- This is local regression/package evidence only. Hosted matrices, external
  providers/write-back, statutory close, independent HA/DR, distributed IAM,
  scale/soak, coherent breadth, and production approval remain open.

## E-417 — Governed durable-worker claim boundary (passed locally)

- Added the opt-in `GovernedDurableJobWorkerService` facade. Before a durable
  worker claims a lane, it requires a central permission decision, a
  `service_account` principal, worker-id identity equality, and exact
  tenant/workspace/entity agreement. Denials occur before the repository claim;
  allowed decisions emit sanitized policy-audit metadata.
- `uv run pytest -q tests/test_governed_worker_policy.py --tb=short` -> 3
  passed. Ruff and Mypy pass for the changed worker/application test surface.
- Boundary: this is an explicit worker claim boundary, not universal worker,
  export, or UI adoption. Re-evaluation after revocation, distributed cache
  invalidation, federation, provider integration, independent HA/DR, and
  production IAM assurance remain open.
- ADR: `docs/adr/0356-governed-durable-worker-claim-boundary.md`.

## E-418 — Final local gates after governed worker boundary (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 323.9 seconds with declared
  skips and existing deprecation/legacy-input warnings only.
- Ruff, Mypy (448 source files), and the repository boundary/parity inventories
  pass after registering the new policy facade. The full gate remains local
  evidence and does not promote hosted, provider, statutory, independent
  HA/DR, distributed-IAM, scale, breadth, or production claims.

## E-419 — PostgreSQL reconciliation worker policy boundary (passed locally)

- `PostgresReconciliationWorkerSettings` now accepts an optional central policy
  context supplier and permission contract. When configured, the worker
  re-evaluates each tenant before run discovery and before claim, requiring a
  service-account identity equal to the audit actor and exact tenant-only
  scope. Policy denial happens before connection access.
- `uv run pytest -q tests/test_postgres_reconciliation.py -k worker_policy
  --tb=short` -> 2 passed; the full reconciliation contract file passes
  15 tests with one declared skip; Ruff and Mypy pass.
- Boundary: the current reconciliation schema has no workspace/entity scope,
  so this is tenant-only and opt-in. Universal worker/export/UI adoption,
  dynamic revocation, federation, distributed invalidation, providers,
  independent HA/DR, and production IAM assurance remain open.
- ADR: `docs/adr/0357-postgres-reconciliation-worker-policy-boundary.md`.

## E-420 — Final local gates after PostgreSQL worker policy boundary (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 324.6 seconds with declared
  skips and existing deprecation/legacy-input warnings only.
- This full local regression confirms the optional worker policy path does not
  break existing reconciliation, PostgreSQL contracts, or compatibility
  surfaces. Hosted matrices, external providers/write-back, statutory close,
  independent HA/DR, distributed IAM, scale, breadth, and production approval
  remain unverified.

## E-421 — PostgreSQL acquisition deferred-tax evidence boundary (passed locally)

- Added migration `0065_pg_deferred_tax`, a backend-neutral
  `AcquisitionDeferredTaxApplicationService`, and a tenant-forced-RLS,
  append-only `PostgresConsolidationDeferredTaxRepository`. Request/result JSON
  is canonical and digest-bound; deterministic recalculation occurs before
  insert; reads verify both request and result lineage; retries are idempotent;
  and creation emits a sanitized audit event. The database contract and API
  are explicitly non-posting.
- Added authenticated server-profile POST/GET routes with strict canonical
  Money, actor binding, maker-checker separation, tenant policy re-evaluation,
  and no SQLite fallback. The authorization inventory now has 238 routes with
  digest `2fd93f143e0b3294bbc7159bc6a0f7e3e52b6e9351c6a285a2490e3cabe43086`.
- Focused schema/API tests pass. With the disposable local PostgreSQL 16
  service at `127.0.0.1:55433`, Alembic `0065_pg_deferred_tax` was applied and
  the live runtime contract passed 1/1 under the non-superuser role, proving
  RLS, idempotent replay, sibling-tenant exclusion, replay verification, and
  trigger-enforced immutability. The global objective remains open for
  statutory tax recognition/posting, live rates and providers, independent
  restore/HA/DR, scale, distributed IAM, coherent breadth, and production
  assurance.
- ADR: `docs/adr/0358-postgres-deferred-tax-evidence-boundary.md`.

## E-422 — Full local regression after deferred-tax persistence/API (passed)

- `uv run pytest -q --tb=short -ra` exits 0 in 351.9 seconds with only
  declared capability skips and existing framework/SAML/legacy-input warnings.
- Ruff, Mypy (452 source files), Bandit, pip-audit, package build, and
  `git diff --check` pass. The separate live PostgreSQL 16 runtime proof is
  recorded under E-421 because the full suite intentionally runs without live
  service environment variables.
- This remains local regression/package evidence. Hosted matrices, statutory
  close, live providers/write-back, independent restore/HA/DR, distributed
  IAM, scale/soak, coherent breadth, and production approval remain open.

## E-403 — Full local post-E-402 quality gates (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 330.3 seconds; only declared
  skips and existing deprecation/legacy-input warnings remain.
- Ruff, Mypy (447 source files), Bandit, pip-audit, package build and
  `git diff --check` all pass. `pip-audit` reports no known vulnerabilities
  and skips the unpublished local distribution because it is not on PyPI.
- This is local correctness/package evidence only. Hosted matrices, live
  vendor providers, independent failure domains, and production release
  approval remain separate and unverified.

## E-404 — Server-scoped metrics policy (passed locally)

- PostgreSQL metrics dashboard and lineage reads now re-evaluate
  `metrics.read` against the validated request tenant before the metrics
  adapter, using `workspace_id=None` for these tenant-wide projections.
- The focused API contract passes both routes with explicit tenant/null-
  workspace assertions. Local SQLite compatibility is unchanged.
- This is a bounded route IAM control, not a security assurance, SLO,
  compliance, or production-readiness claim; broader distributed IAM and
  worker/export/UI adoption remain open.

## E-405 — PostgreSQL native backup portable dump retry (passed locally)

- The native backup adapter now requires a non-empty dump and retries once with
  the equivalent `--file=<path>` spelling when a successful `pg_dump` command
  produces no usable file. A second absence fails closed; non-zero tool exits
  are not retried.
- Focused backup tests pass normal encryption, one portable retry, and
  fail-closed double absence. This is a bounded client-wrapper resilience fix,
  not independent HA/DR or production backup evidence.

## E-406 — Final full local gate after backup hardening (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 356.6 seconds with only declared
  skips and existing deprecation/legacy-input warnings.
- Ruff, Mypy (447 source files), Bandit, pip-audit, package build and
  `git diff --check` all pass after the metrics/IAM and backup changes.
- This closes the local correctness gate for the current branch only. The
  global objective remains open for external provider contracts, statutory
  close semantics, independent HA/DR, distributed IAM, production scale and
  coherent industry breadth.

## E-401 — Server-scoped consolidation PPA policy (passed locally)

- PostgreSQL consolidation PPA preparation now re-evaluates
  `finance_core.manage` against the validated request tenant before the
  non-posting evidence adapter; reads re-evaluate the existing
  `finance_core.read` OR `finance_core.manage` contract.
- The policy call deliberately passes `workspace_id=None` because the current
  PPA persistence contract is tenant-scoped and has no workspace key. A
  focused API regression proves the call shape and the existing server-identity
  lifecycle remains green.
- This is route-family IAM evidence only. Statutory acquisition accounting,
  provider interoperability, write-back, independent HA/DR, and complete
  worker/export/UI policy adoption remain open.

## E-402 — Server-scoped audit and security views (passed locally)

- PostgreSQL audit browsing, audit-chain verification, and the security-center
  overview now re-evaluate their exact central permissions against the
  validated tenant before opening the tenant-wide repository boundary.
- These projections intentionally pass `workspace_id=None`; they are
  tenant-wide operational views, not workspace business actions.
- Focused audit/security-center/PostgreSQL security-center tests pass. This
  extends route-family IAM coverage only; federation, distributed invalidation,
  worker/export/UI adoption, independent HA/DR, and production IAM assurance
  remain open.

## E-400 — Full local post-IAM quality gates (passed)

- `uv run pytest -q --tb=short` -> exit 0 in 318.9 seconds; declared skips and
  existing deprecation/legacy-input warnings remain visible.
- Ruff, Mypy (447 source files), Bandit, pip-audit, package build and
  `git diff --check` all pass. `pip-audit` reports no known vulnerabilities and
  skips the unpublished local distribution because it is not on PyPI.
- This is a clean local quality gate after E-399, not hosted CI, image,
  external-provider, HA/DR or production-release evidence.

## E-399 — Central server-policy tenant binding (passed)

- `enforce_server_scoped_permissions` now compares every adapter-supplied
  tenant with the validated request tenant before evaluating policy; a
  mismatch returns `tenant_scope_denied` before repository access.
- A focused regression covers both valid workspace scope and a caller-supplied
  sibling tenant. This is additive to E-397/E-398 and leaves local SQLite
  behavior unchanged.
- Worker/export/UI adoption, federation, distributed invalidation, live
  providers, independent HA/DR and production IAM assurance remain open.

## E-398 — Live PostgreSQL tenant-administration policy gate (passed locally)

- A fresh PostgreSQL 16 database with the non-superuser `reconforge_app`
  (`NOBYPASSRLS`) exercised access administration, security governance, and
  identity administration after upgrading through Alembic `0064`.
- The three live contracts passed with tenant isolation, maker/checker and
  lifecycle behavior, guarded downgrade/rollback evidence, and no cross-tenant
  visibility. The first attempted run used the superuser and an already-used
  database; it is not evidence and is retained only as a diagnostic boundary.
- This promotes the tenant-wide route family to current local PostgreSQL
  runtime evidence. It does not prove federation, distributed invalidation,
  worker/export/UI adoption, independent HA/DR, or production IAM assurance.

## E-397 — Tenant-wide central policy re-evaluation (passed)

- Added `enforce_server_tenant_permission`, which binds tenant-wide
  administration to the request tenant and re-evaluates the central policy
  immediately before PostgreSQL repository access without inventing a
  workspace scope.
- Adopted the boundary for access roles/policies, identity/session
  administration, workspace/entity scope grants, and integration/evidence
  retention governance. Local SQLite compatibility is unchanged.
- Focused execution-scope, access-administration, identity-administration and
  security-governance tests pass. This closes only the tenant-wide route
  family; worker/export/UI adoption, federation, distributed invalidation,
  live providers, HA/DR and production IAM assurance remain open.

## E-396 — Python 3.11 all-extras CI ImportError reproduction (passed current head)

- A fresh disposable Python 3.11.15 environment created with
  `uv sync --locked --all-extras --no-editable` installed the previously missing
  `opentelemetry`, `cryptography`, `cbor2`, `webauthn`, server and connector
  dependencies from the locked resolution.
- The focused set matching the old CI collection failures passed 44 tests with
  one declared skip. This is current-head dependency evidence; it does not
  retroactively make the old hosted run green or prove every external workflow.

## E-395 — Disposable local HTTPS REST reader sandbox (complete bounded slice)

- The reference REST reader now runs through a disposable local TLS server and
  the real `PinnedHttpsGetTransport`/`NetworkConnectorExecutor` path. The
  sandbox returns one transient `429` and then a valid bounded JSON page.
- The gate proves stable idempotency key/cursor propagation, public-address
  resolution guard execution, secret-reference header handling, cursor output,
  canonical response digest and deterministic server cleanup.
- Boundary: provider-neutral loopback transport only. No live ERP/bank schema,
  vendor authentication, external network or production capacity is evidenced.

## E-394 — Disposable local HTTPS write-back sandbox (complete bounded slice)

- The provider-neutral write-back test now runs the real TLS/HTTP transport
  against a short-lived local HTTPS server. The sandbox returns two transient
  `503` responses and then a digest-valid acknowledgement.
- The gate proves three attempts carry the same idempotency key and exact
  payload, the public-address resolver guard is exercised, the synthetic
  bearer secret is only sent in the request, and the receipt is secret-free.
- Boundary: no internet, vendor API, vault, accounting posting, provider
  version contract or production write-back is evidenced. The provider and
  compensation gaps remain open; GitHub publication remains deferred.

## E-393 — Official-source competitive matrix supplement (complete bounded slice)

- Added a dated ethical comparison using only first-party Odoo, ERPNext and
  Apache Fineract documentation. The matrix separates documented competitor
  workflows from ReconForge code/evidence and records unresolved live-provider,
  statutory, IAM, HA/DR and breadth gaps.
- Added a regression test for the required official links, local evidence IDs
  and prohibited unqualified wording. The supplement is documentation and
  evidence governance only; it does not change runtime behavior, migrations or
  connector activation.
- Boundary: a source page is not a performance, security-assurance, customer-
  outcome or production-readiness proof. GitHub publication remains deferred
  by the owner, so no hosted evidence exists for this slice.

## E-392 — PostgreSQL grouped-matching 10K tier with bounded connection reuse (complete bounded slice)

- Added `PostgresConnectionPool`, a small dependency-free pool with explicit
  max size/acquisition timeout, rollback-on-release, idempotent proxy close,
  and deterministic idle/active cleanup. Foundation tests prove one bounded
  connection is reused and then closed; existing tenant-local transaction
  scope remains in force.
- The grouped-matching harness now uses the pool and publishes
  `postgres-grouped-matching/10k-partitions-v1`: 16 worker tasks, 1,000 runs,
  ten partitions per run, five synthetic modes, and 24,000 expected result
  rows. A local PostgreSQL 16 run completed 10,000/10,000 partitions and
  24,000/24,000 result rows with zero duplicate identities, zero failed/active
  runs, and 200 completed runs per mode.
- Observed wall time was approximately 303.5 seconds on Windows 11/Python
  3.14.6 with one host. The artifact records effect digest
  `14e33ba117d7be05da5290346736ea6a594c1a0a52689b4939b665c0c674c88b` and
  manifest digest `da43b12e3a034bcb7e6f3dc8492a7a45fdfb9e87f2591718d49e8049c0f00305`.
- Boundary: bounded synthetic correctness/concurrency only. The result is not
  throughput, capacity, soak, SLO, HA/DR, provider, statutory-posting,
  write-back, or production-sizing evidence.

## E-391 — PostgreSQL grouped-matching 10K probe (blocked, not promoted)

- A disposable PostgreSQL 16 probe for 10,000 grouped-matching partitions
  reached 304 completed runs, 3,108 checkpoints, and 7,458 result rows before
  the existing worker's fresh-connection-per-phase behavior exhausted local
  Windows ephemeral ports (`Address already in use`). The test failed closed
  rather than publishing a partial tier; the disposable container was removed.
- No 10K profile, workflow gate, artifact, or public capability claim was
  retained. The existing 500-partition gate remains unchanged and green.
- Required follow-up: connection lifecycle/pooling or bounded connection reuse
  must be designed, tested, and benchmarked before any larger PostgreSQL
  grouped-matching tier can be promoted. This is an engineering blocker, not
  evidence of production capacity.

## E-390 — PostgreSQL durable-job backpressure runtime gate (complete bounded slice)

- Added `postgres-durable-job-load/backpressure-tier-v1`: eight independent
  worker connections, four producer lanes, 64 jobs, four partitions per job,
  and a four-job queued/retrying cap per tenant/workspace/entity lane. The
  profile uses the existing atomic bounded-submit, lease, checkpoint, and
  partition-effect contracts; no new migration or provider activation is
  introduced.
- A local PostgreSQL 16 disposable-service run completed 64/64 jobs and
  256/256 effects, observed maximum queue depth four and 12 rejected retries,
  and ended with zero duplicate effects and zero queued/running residue. Each
  lane completed exactly 16 jobs. Artifact digests are recorded in the
  benchmark JSON and the E-390 evidence entry.
- Focused shape/live tests, Ruff, and Mypy pass. The workflow server-boundaries
  selector now includes the gate, but hosted evidence remains pending because
  GitHub publication is intentionally deferred by the owner.
- Boundary: this is bounded single-host synthetic queue-cap correctness only;
  throughput, capacity, global fairness, soak, queue HA, automatic failover,
  host loss, cross-host fairness, RPO/RTO, and production sizing remain open.

## E-388 — Bounded CAMT.053 offline statement ingestion (complete bounded slice)

- Added a strict local ISO 20022 CAMT.053 parser and `reconforge connectors
  parse-camt053` CLI. The boundary accepts one `BkToCstmrStmt/Stmt`, preserves
  exact finite Decimal amount text and signed direction, requires a stable
  entry/service reference, validates booking/value-date ordering, and emits
  opening/closing balances, references, remittance text, and a deterministic
  source digest.
- Added a deterministic projection into bounded internal payment-statement
  pages. It preserves signed amounts, stable line IDs, account/currency,
  booking/value dates, and source references while using only a local offset
  cursor for pagination.
- XML parsing uses `defusedxml`; payloads are capped at 8 MiB, entries at
  100,000, and bounded text fields at 8 KiB. The closed JSON Schema, synthetic
  golden fixture, packaging assertions, malformed-input tests, XXE rejection,
  duplicate/missing identity tests, and CLI replay test all pass locally.
- Boundary: this is a read-only file/bytes ingestion contract with no network,
  bank credential, provider acknowledgement, payment initiation, ERP mapping,
  or write-back. Named live bank/ERP providers and production deployment remain
  open under P4-CON-001.

## E-389 — Connector boundary module and threat-model parity (complete bounded slice)

- Registered `connectors.boundary` as an evidence-bounded runtime module with
  explicit interfaces, connector import/export contracts, data classifications,
  retention/activation notes, and the existing connector test portfolio.
- Added exact threat-model index coverage, readable threat-model coverage, and
  maturity-policy ceiling. Registry, threat-index schema/parity, and maturity
  tests pass with eleven active modules.
- Boundary: module discoverability and governance metadata only; it does not
  promote provider-neutral adapters to live ERP/bank integrations or establish
  vendor credentials, source authenticity, write-back, HA/DR, or production
  readiness.

## E-387 — PostgreSQL durable-job 100K-effect tier (complete bounded slice)

- Added `postgres-durable-job-load/100k-effects-v1`: 16 independent worker
  connections, 2,500 jobs, forty partitions per job, and four forced-RLS tenant
  lanes (100,000 declared effects). The shared schema now validates both the
  published 10K and 100K profiles.
- A local PostgreSQL 16 container run completed 2,500/2,500 jobs and
  100,000/100,000 unique effects with zero duplicate effects, zero queued or
  running residue, and exactly 625 completions per lane. Observed runtime was
  202.1521 seconds / 12.3669 jobs per second on Windows 11/Python 3.14.6.
- Focused profile/schema/package tests pass. Hosted CI run `30970795278` passed
  the `server-boundaries` job `92194440053`, including both the 10K and 100K
  live PostgreSQL profile gates. Security `30970795282`, Docker `30970795277`,
  CodeQL `30970795309`, `postgres-ha-dr` `92194440057`, and Docker parity
  `92195270355` are green.
- Boundary: synthetic one-host correctness/concurrency only; no throughput,
  soak, backpressure, queue HA, automatic failover, host-loss, cross-host
  fairness, RPO/RTO, or production-sizing claim.

## E-384 — PostgreSQL intercompany elimination evidence (complete bounded slice)

- Added a server-profile API and forced-RLS PostgreSQL adapter for the exact
  intercompany proposal bridge. The server computes the result from typed source
  lines, binds the authenticated preparer and workspace, persists immutable
  request/result JSONB plus digests, and records an audit event.
- Reads replay the result against persisted source lines and fail closed on
  payload/digest tampering. The artifact explicitly reports
  `posting: not_available`; no statutory journal or provider write-back path was
  added.
- Local schema/API contracts pass. Hosted CI run `30961377710`, including
  `server-boundaries` job `92165832615`, passed the live non-superuser
  PostgreSQL migration/RLS/replay/immutability/workspace-isolation test. The
  parity row is now `live_verified_current`.
- Boundary: one digest-pinned PostgreSQL CI service with synthetic data. This
  proves a non-posting evidence artifact only; statutory posting, ERP/bank
  providers, write-back, throughput, HA/DR, and production readiness remain
  unverified.

## E-383 — Exact intercompany elimination proposal bridge (complete bounded slice)

- Added the pure `intercompany-elimination-v1` domain/application boundary and
  the read-only `reconforge consolidation intercompany-eliminations` command.
  The caller must supply signed reporting-currency `Money`, explicit group
  account and account type, reciprocal entity/counterparty, period/reference,
  source reference, and source digest for every line.
- A partition is proposed only when entity/counterparty coverage is reciprocal
  and the signed Decimal total is exactly zero. The generated elimination
  negates each source line while preserving source digest/entity/account
  lineage. One-way, incomplete, and imbalanced partitions remain explicit
  `unresolved` records; no tolerance, implicit FX, account inference, or
  posting is performed.
- Request, source-group, and result digests, replay against the original typed
  lines, a closed JSON Schema, permutation stability, tamper refusal, and CLI
  regressions are covered by `tests/test_intercompany_elimination.py`.
- This closes only the deterministic intercompany-to-worksheet proposal bridge.
  Approval, accounting-standard interpretation, tax/FX/impairment, statutory
  or legal-book posting, live provider semantics, persistence parity, HA/DR,
  and production readiness remain open under P4-FIN-002/P4-CON-001/P4-REL-001.
- Hosted CI for commit `39ee3560` is green: CI `30957905278` (server-boundaries
  `92155112535`, PostgreSQL/HA-DR `92155112665`, Docker parity `92156185805`),
  Security `30957904702`, Docker `30957904676`, and CodeQL `30957905390`.
- ADR: `docs/adr/0333-intercompany-elimination-proposals-are-exact-and-nonposting.md`.

## E-382 — Signed package admission CLI (complete bounded slice)

- Added `reconforge connectors verify-package`, a read-only operator command
  that accepts an explicit package path and public trust key, invokes the
  signed trust-plus-conformance gate, and emits only the digest-bound admission
  record. Invalid input exits non-zero; no package code is loaded or executed.
- CLI regression, package/SDK tests, Ruff, and Mypy pass. This is local
  operator evidence only; marketplace installation, live ERP/bank providers,
  write-back, and production deployment remain open.
- ADR: `docs/adr/0332-signed-package-admission-cli.md`.

## E-381 — Signed connector package trust-plus-conformance admission (complete bounded slice)

- Added `load_verified_package_for_admission` and `admit_verified_package`.
  A signed envelope must pass the operator-owned Ed25519 trust registry and the
  existing read-only connector conformance portfolio before admission.
- `VerifiedConnectorPackage` binds the manifest digest, trust-registry
  version/digest, signature digest, and canonical admission digest. The
  boundary remains data-only and never imports or executes package code.
- Focused package/SDK tests, CLI regression, Ruff, and Mypy pass. Live provider interoperability,
  executable package loading, write-back, and production marketplace evidence
  remain open.
- ADR: `docs/adr/0331-signed-connector-package-admission.md`.

## E-380 — Governed write-back compensation dispatch API (complete bounded slice)

- Added the server-profile-only
  `POST /api/v1/connectors/writeback/intents/{intent_id}/compensate/dispatch`
  route behind the privileged `connectors.writeback.dispatch` permission and
  central server scope re-evaluation.
- The route resolves a short-lived compensation payload only from an explicit
  in-memory application resolver, checks the caller-provided SHA-256 digest,
  delegates bounded retries/egress/secret/acknowledgement checks to the
  provider-neutral executor, and appends `compensated` only after an accepted
  provider acknowledgement. Missing resolver, stale version, wrong state,
  digest mismatch, and provider failure leave the intent retryable.
- Local SQLite network I/O remains disabled. Focused local API, route-inventory,
  Ruff, and Mypy checks pass; hosted PostgreSQL server-identity evidence is
  recorded below.
- ADR: `docs/adr/0330-governed-writeback-compensation-dispatch-api.md`.
- Hosted CI for commit `1f9f222d` is green: CI `30951488861` including
  server-boundaries `92134375855`, PostgreSQL/HA-DR `92134375833`, Python
  3.11/3.12, object-storage, parity, and Docker parity `92135966028`;
  Security `30951488894`, Docker `30951488919`, and CodeQL `30951488904`.

## E-379 — Governed write-back compensation request API (complete bounded slice)

- Added the independent `connectors.writeback.compensate` human permission and
  local SQLite migration 32, seeded for the default `admin` and `controller`
  roles. The PostgreSQL identity boundary remains explicit: tenants provision
  this permission through identity administration under their RLS context.
- Added `POST /api/v1/connectors/writeback/intents/{intent_id}/compensate`.
  It binds the authenticated actor, rejects the original maker, checks the
  tenant/workspace scope in server mode, enforces optimistic versions, records
  bounded reason/actor/UTC time, and never performs provider I/O.
- Same-input retries against the immediately prior version replay the existing
  compensation request without appending a duplicate. Changed reason/actor,
  stale versions, wrong scope, and invalid lifecycle states fail closed.
- Focused API/domain/repository/inventory gates pass locally. This remains a
  bounded synthetic/provider-neutral request boundary; live ERP/bank reversal
  semantics, automatic compensation, signed connector packages, HA/DR, and
  production deployment evidence remain open.
- ADR: `docs/adr/0329-governed-writeback-compensation-request-api.md`.
- Hosted CI for commit `4932442f` is green: CI `30948449550` (server-boundaries
  `92124197210`, PostgreSQL/HA-DR `92124197189`, Python 3.11/3.12,
  object-storage, parity, and Docker parity `92125667608`), Security
  `30948449806`, Docker `30948449939`, and CodeQL `30948449932`.

## E-378 — Governed write-back compensation transport (complete bounded slice)

- The provider-neutral HTTPS write-back executor now exposes an explicit
  `dispatch_compensation` boundary. Registrations must allow compensation for
  the original operation; the transport uses a separate `compensate.*`
  operation marker and `:compensation` idempotency key.
- The caller supplies a short-lived compensation payload and SHA-256 digest in
  memory. The executor refuses a missing allowlist, wrong lifecycle state,
  oversized/tampered payload, or misbound provider acknowledgement, and only a
  valid acknowledgement transitions the intent to `compensated`.
- Focused write-back/network tests pass 24/24, including rejected-provider
  acknowledgement refusal, transient HTTP/transport failure injection, and
  the reusable synthetic conformance check. Existing write-back dispatch tests
  remain green; Ruff and Mypy pass for the changed connector surfaces.
- Boundary: provider-neutral transport contract only. No live ERP/bank
  compensation semantics, provider sandbox, vault, signed executable
  connector, production egress, or deployment assurance is claimed.
- ADR: `docs/adr/0328-governed-writeback-compensation-transport.md`.

## E-353 — Live S3-compatible object-storage provider gate (complete bounded slice)

- Added an independent CI `object-storage` job that starts a digest-pinned
  MinIO process with synthetic credentials, creates normal and object-lock
  buckets, runs the real boto3-backed `S3ObjectStore`, and uploads a
  digest-bound report.
- The contract verifies hierarchical tenant/workspace/entity isolation,
  immutable conditional creation, checksum tamper refusal, object-lock delete
  refusal, and cleanup. The report verifier rejects credentials and requires
  all observed invariants.
- Boundary: one disposable MinIO process on one CI host. Replication, KMS,
  cross-site durability, provider interoperability, object-store HA/DR,
  malware scanning, authorized download, and production SLOs remain open.
- ADR: `docs/adr/0303-live-s3-compatible-object-storage-gate.md`.

## E-354 — Redis-shared policy-cache generation (complete bounded slice)

- Added `RedisPolicyCacheVersionStore` as an explicit optional server-profile
  boundary. API processes include its monotonic generation in local allowed
  decision-cache keys; non-safe requests bump the generation and clear local
  entries. Redis is never used to store policy decisions or credentials.
- If the generation read fails, the cache bypasses itself and evaluates policy
  directly. Unit tests prove independent cache instances stop reusing an
  allowed decision after a bump and do not cache during a synthetic outage.
  Live Redis tests prove two clients observe atomic generation changes and
  remove their synthetic key.
- Hosted head `01ee957b` passed CI `30873354330` (server-boundaries
  `91879657202`), where the Redis 7 live contract ran with PostgreSQL; Security,
  Docker, CodeQL, object-storage, both Python suites, and all engine-parity
  cells also passed.
- Boundary: coarse global invalidation only. Redis HA/failover, outage
  recovery, complete route/job/export/UI migration, federation, and production
  IAM assurance remain open. The feature is opt-in and local-first defaults are
  unchanged.
- ADR: `docs/adr/0304-redis-shared-policy-cache-generation.md`.

## E-358 — Hosted repeated PostgreSQL HA/DR runtime gate (complete bounded slice)

- The existing Docker drill now runs as a dedicated `postgres-ha-dr` CI job
  using locked server/backup dependencies. Three repetitions execute encrypted
  native backup, isolated restore, synchronous replication, partition write
  refusal, old-primary fencing, standby promotion, former-primary read-only
  rejoin, and failback; labelled Docker resources are checked for cleanup and
  the report is uploaded as an artifact.
- Local Windows 11 / Docker Engine 29.6.2 evidence passed all three runs:
  failover RTO 11.098–11.138s, failback RTO 0.980–1.025s, zero acknowledged
  transaction loss, final sequence `[1, 2, 3, 4]`, and cleanup on every run.
  Artifact: `docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION_2026-08-04.json`.
- Boundary remains one host and manual controller: no independent failure
  domains, quorum/witness, automatic promotion, site loss, or production SLO
  is claimed. Hosted CI run `30884962171` passed the full workflow; the
  `postgres-ha-dr` job `91914021265` ran the three repeated Docker drills and
  uploaded the report artifact. The hosted artifact reports 3/3 passes,
  zero acknowledged loss, failover RTO 10.468–11.301s, and failback RTO
  0.424–0.668s. The same run's Python 3.11/3.12, server-
  boundaries, engine-parity, object-storage, Docker, Security, and CodeQL
  jobs also passed.
- ADR: `docs/adr/0308-postgres-ha-dr-runtime-gate.md`.

## E-359 — Hosted PostgreSQL durable-job 10K-effect gate (complete bounded slice)

- The `server-boundaries` CI command now explicitly runs the existing live
  `postgres-durable-job-load/10k-effects-v1` profile with 16 independent
  worker connections, 2,500 jobs, four partitions per job, four forced-RLS
  tenant lanes, and 10,000 declared effects.
- The gate requires every job/effect to complete exactly once, zero duplicate
  effects, zero queued/running residue, and equal per-lane completion counts.
  Hosted CI run `30887647946` passed the full workflow; the
  `server-boundaries` job `91922298719` ran the explicit test successfully
  against the digest-pinned PostgreSQL 16 service. The same run's Python
  3.11/3.12, engine-parity, object-storage, Docker, Security, CodeQL, and
  `postgres-ha-dr` jobs also passed. No capacity, soak, backpressure,
  queue-HA, or production-sizing claim is made.
- ADR: `docs/adr/0309-postgres-durable-job-10k-hosted-gate.md`.

## E-360 — Hosted PostgreSQL grouped-matching 500-partition gate (complete bounded slice)

- The next hosted advanced-matching gate adds
  `test_live_postgres_grouped_matching_500_partition_scale_profile` to
  `server-boundaries`: 16 worker connections, 250 runs, two partitions per
  run, five grouped modes, and a bounded batch size of 16. An initial 2,000-
  partition attempt failed in hosted `server-boundaries` after 2m34s and is
  retained as an unverified scale boundary, not a success.
- The verifier requires 500 completed partitions, exact result-row
  cardinality, zero duplicate result identities, zero failed/active runs, and
  50 completed runs per mode. Hosted CI run `30894602923` passed with
  `server-boundaries` job `91944412213`; Python 3.11/3.12, engine-parity,
  Docker-parity, object-storage, and `postgres-ha-dr` also passed in the same
  workflow.
- The hosted run exposed a real active-page race: a second worker could see a
  run already completed by another worker and treat that terminal state as an
  integrity failure. `PostgresReconciliationRepository.claim_run` now maps
  terminal `Complete`/`Failed`/`Cancelled` observations to the existing busy
  skip path; a focused regression covers the contract.
- Boundary: hosted single-node synthetic PostgreSQL matching
  correctness/concurrency only. This does not claim throughput, soak, queue
  backpressure, cross-host scheduling, provider interoperability, posting,
  write-back, HA/DR, or production sizing.
- ADR: `docs/adr/0310-postgres-grouped-matching-2000-partition-hosted-gate.md`.

## E-361 — Replay-verifiable consolidation close evidence bundle (complete bounded slice)

- Added `consolidation-close-bundle-v1`, a pure digest-bound index over the
  replay-verified worksheet, translation evidence, management statement,
  journal, and committed effects for one close run. SQLite and PostgreSQL
  `get_run` details now expose the same additive bundle after their existing
  integrity checks.
- Focused SQLite bundle/lifecycle tests pass 15/15; the PostgreSQL close
  contract passes 7/7 with one no-DSN skip, and the live local PostgreSQL close
  contract passes 8/8. Cross-run worksheet binding, effect ordering, header
  compatibility, and tamper refusal are covered. No migration or posting path
  changed.
- Boundary: local control-journal and management-only evidence. This is not a
  statutory statement, external ledger posting, provider acknowledgement,
  write-back, HA/DR, or production-assurance claim.
- ADR: `docs/adr/0311-consolidation-close-evidence-bundle.md`.

## E-362 — Hosted PostgreSQL queue-policy and lane-fairness gate (complete bounded slice)

- `server-boundaries` now explicitly runs the existing live PostgreSQL tests
  for atomic queue-cap rejection/idempotent replay/retry cleanup and the
  process-scoped round-robin scheduler's tenant/workspace/entity lane
  isolation.
- Hosted CI run `30898382499` / `server-boundaries` job `91956632669` passed
  the explicit queue-policy and lane-fairness invocation; Python 3.11/3.12,
  engine-parity, Docker-parity, object-storage, and `postgres-ha-dr` also
  passed in the same workflow. This slice does not claim throughput, global
  fairness, soak, queue HA, failover, capacity, or production SLOs.
- ADR: `docs/adr/0312-hosted-postgres-queue-policy-and-fairness-gate.md`.

## E-363 — Scope-bound server write-back authorization (complete bounded slice)

- Added `enforce_server_scoped_permission` to the API policy dependencies. In
  the PostgreSQL server profile it re-evaluates a permission against the
  authenticated tenant/workspace/entity grant snapshot, step-up state, and
  central policy engine before a repository operation; authorization evidence
  remains sanitized and local SQLite compatibility is unchanged.
- The proposal, maker-checker approval, and provider-acknowledgement routes
  now invoke that gate after request-scope equality and before touching the
  PostgreSQL write-back repository. Focused API tests pass 8/8, including
  sibling-workspace refusal and granted-workspace approval with step-up;
  Ruff and Mypy pass for the changed surface.
- Boundary: one server write-back surface is now centrally scope-bound. Full
  route/job/export/UI adoption, federation, distributed IAM assurance, live
  ERP/bank providers, network dispatch, compensation, HA/DR, and production
  write-back remain open.
- ADR: `docs/adr/0313-server-writeback-policy-is-scope-bound.md`.

## E-364 — Scope-bound PostgreSQL consolidation-close API (complete bounded slice)

- Added a request-scoped PostgreSQL adapter for the existing
  consolidation-close periods, runs, replay-verified detail, certification,
  and summary routes. Server requests now pass the authenticated
  tenant/workspace/organization/entity hierarchy through `PostgresTenantBoundary`
  and query the authorized workspace; detail, certification, and every list
  record fail closed on a returned sibling-workspace row.
- The eight routes are now included in the startup authorization inventory.
  Focused API, server-scope, and inventory tests pass 16/16; Ruff and Mypy
  pass, and local SQLite consolidation-close behavior remains green.
- Hosted no-regression verification for commit `21978ccb` is green: CI run
  `30904707354` (including `server-boundaries` and `postgres-ha-dr`), Security
  `30904707336`, Docker `30904707413`, and CodeQL `30904707431`. The hosted
  matrix did not add a live authenticated consolidation-close API fixture, so
  this remains repository/CI compatibility evidence rather than a live API
  route claim.
- Boundary: synthetic/local API policy and repository wiring only. The close
  adapter remains control-journal evidence, not statutory consolidation,
  external posting, live ERP/bank integration, write-back, HA/DR, or complete
  enterprise IAM.
- ADR: `docs/adr/0314-postgres-consolidation-close-api-is-scope-bound.md`.

## E-365 — Scope-bound consolidation ownership API (complete bounded slice)

- Added strict authenticated `/api/v1/consolidation-ownership/interests` and
  `/effective` routes over the existing immutable effective-dated ownership
  service. Local mode uses SQLite; server mode binds the authenticated
  tenant/workspace/organization/entity hierarchy through PostgreSQL RLS.
- Percentages are exact decimal text, the authenticated principal is bound as
  `prepared_by`, and sibling workspace requests fail before repository use.
  Focused API and server-scope tests pass 12/12; authorization inventory is
  219 routes with digest
  `46a0eac80865dbf7219a2b8230c8dc576d41cd503bdae224c9e01e442828e8f8`.
  Ruff and Mypy pass for the changed modules. With the configured local
  PostgreSQL 16 service, `pytest -q tests/test_postgres_consolidation_ownership.py`
  passes 5/5.
- Hosted no-regression verification for commit `b8e30bab` is green: CI
  `30907636302` (including server-boundaries and postgres-ha-dr), Security
  `30907636780`, Docker `30907634915`, and CodeQL `30907635562`. The hosted
  matrix did not add a live authenticated ownership API fixture.
- Boundary: API exposure and hierarchy isolation only. Full approver identity
  proof, statutory statements, live ERP/bank integration, write-back, HA/DR,
  and production assurance remain open.
- ADR: `docs/adr/0315-consolidation-ownership-api-is-scope-bound.md`.

## E-366 — Live authenticated consolidation ownership API gate (complete bounded slice)

- The existing PostgreSQL server-identity fixture now installs the ownership
  schema, grants the non-privileged application role the ownership table, and
  exercises the real FastAPI POST/GET ownership API path.
- The live test proves authenticated preparer binding, exact decimal input,
  PostgreSQL persistence/replay, authorized `workspace-a` resolution, and
  sibling-workspace refusal (`403 workspace_scope_denied`). With the local
  PostgreSQL 16 service, the combined API/identity/ownership gate passes 25/25;
  Ruff and Mypy pass.
- Boundary: synthetic single-node PostgreSQL runtime and one API process. The
  fixture does not prove independent approver authentication, statutory
  consolidation, live ERP/bank providers, write-back, HA/DR, or production
  readiness.
- Hosted verification for commit `0f9a7eb` is green: CI `30909580514`
  (including `server-boundaries` and `postgres-ha-dr`), Security `30909580496`,
  Docker `30909580586`, and CodeQL `30909580604`.
- ADR: `docs/adr/0316-live-consolidation-ownership-api-gate.md`.

## E-367 — Live authenticated consolidation-close API gate (complete bounded slice)

- The live PostgreSQL server-identity fixture now installs the existing
  consolidation-close schema and grants its six RLS tables plus certification
  storage to the non-privileged app role.
- The real authenticated API path returns PostgreSQL-backed empty periods for
  the authorized workspace and rejects the sibling workspace with
  `403 workspace_scope_denied`. The local combined API/identity/ownership/close
  gate passes 29/29; Ruff and Mypy pass.
- Boundary: route selection and hierarchy isolation on one synthetic
  PostgreSQL node. This does not prove posted/statutory close behavior,
  independent HA/DR, ERP/bank providers, write-back, or production readiness.
- Hosted verification for commit `b9fd51d` is green: CI `30910990925`
  (including `server-boundaries` and `postgres-ha-dr`), Security `30910991025`,
  Docker `30910990850`, and CodeQL `30910990719`.
- ADR: `docs/adr/0317-live-consolidation-close-api-gate.md`.

## E-368 — Consolidation ownership approver identity gate (complete bounded slice)

- The ownership save path now resolves `approved_by` to a real enabled local or
  tenant-scoped PostgreSQL identity, requires `finance_core.manage` or
  `finance_core.validate`, and rejects self-approval before persistence.
- Unknown approvers return `consolidation_ownership_approver_invalid`; known
  users without a governed finance permission return
  `consolidation_ownership_approver_unauthorized`. The check runs inside the
  same PostgreSQL request/transaction boundary and preserves SQLite behavior.
- The combined local API/identity/ownership/close gate passes 29/29 after the
  change; focused SQLite ownership tests pass 3/3; Ruff, Mypy, diff-check, and
  package build pass. Hosted head `6eb71f2a` is green: CI `30913043618`
  (`server-boundaries` `92004218583`, `postgres-ha-dr` `92004218707`, and
  `docker-parity` `92005941216`), Security `30913043237`, Docker `30913043606`,
  and CodeQL `30913043202`.
- Boundary: verified identity and permission lookup is not proof of a separate
  approver session, MFA ceremony, statutory consolidation, provider/write-back,
  HA/DR, or production IAM assurance.
- ADR: `docs/adr/0318-consolidation-ownership-approver-identity.md`.

## E-369 — Scoped consolidation-close period write API (complete bounded slice)

- Added strict authenticated `POST /api/v1/consolidation-close/periods` over
  the existing backend-neutral close application service. Local mode persists
  through SQLite; server mode persists through the authenticated PostgreSQL
  hierarchy/RLS boundary and binds the actor to the bearer identity.
- The request rejects unknown fields and malformed currency/date values,
  replays an identical period identity, and rejects sibling workspace input
  before repository use. The live API/identity/ownership/close gate passes
  30/30; authorization inventory is now 220 routes with digest
  `3adace1833893004e67851b0be16791f8cff078bb0a55babe49a7a5c216f05c0`.
- Ruff, Mypy, and diff-check pass. Hosted head `8c2589ef` is green: CI
  `30915384871` (`server-boundaries` `92012074573`, `postgres-ha-dr`
  `92012074773`, and `docker-parity` `92013746295`), Security `30915375062`,
  Docker `30915374854`, and CodeQL `30915379664`.
- Boundary: period creation only. Run preparation, approval/posting, reversal,
  locks/reopens, statutory statements, provider/write-back, independent HA/DR,
  and production assurance remain open.
- ADR: `docs/adr/0319-consolidation-close-period-api-write-boundary.md`.

## E-370 — Full governed consolidation-close API lifecycle (complete bounded slice)

- Added strict authenticated routes for replay-verified run preparation,
  independent approval, control-journal posting, reversal request/approval, and
  period lock/reopen. All transitions use optimistic versions, bounded reasons,
  authenticated actor binding, and the existing SQLite/PostgreSQL application
  ports.
- Worksheet ingress is reconstructed through the closed deterministic verifier;
  unknown fields, float/tampered worksheet payloads, wrong actors, invalid
  states, and stale versions fail closed. The local API lifecycle test executes
  prepare → approve → post → reverse and lock → reopen; the live PostgreSQL
  server-identity fixture executes prepare/approve/post/lock/reopen with scoped
  users and step-up.
- The focused live API/identity/close/inventory gate passes 14/14 in the current
  environment; authorization inventory is now 227 routes with digest
  `9e4e4f568df98a482a0eaf34d9c9c359330caf22df43b89e2cb14f771b183fc5`.
- Hosted verification for exact code head `672b2282` is green: CI run
  `30919182900` (Python 3.11/3.12, server-boundaries job `92025004869`,
  PostgreSQL/HA-DR job `92025004440`, and Docker parity job `92026761956`),
  Security `30919182689`, Docker `30919183050`, and CodeQL `30919183059`.
- Boundary: PostgreSQL reopened periods currently serialize as `Open` while
  SQLite returns `Reopened`; this compatibility difference is recorded rather
  than hidden. The slice remains a control-journal API, not statutory close,
  external posting, live provider write-back, independent HA/DR, or production
  assurance.
- ADR: `docs/adr/0320-consolidation-close-api-full-lifecycle-boundary.md`.

## E-371 — Opt-in governed server write-back dispatch (complete bounded slice)

- Added migration 31 and the human-governed
  `connectors.writeback.dispatch` permission. The dispatch route is now part
  of the startup authorization inventory, which is 231 routes with digest
  `5ab85f381b3ef49f060b27f539b342af01a91d739788da5601db383a5b15ebdd`.
- `POST /api/v1/connectors/writeback/intents/{intent_id}/dispatch` is
  server-profile-only. It persists `approved -> dispatched` before invoking an
  explicitly registered `WritebackNetworkExecutor`, verifies the registration,
  payload digest, canonical provider response, and original idempotency key,
  then persists the acknowledgement. Missing registration or transport errors
  fail closed; a transport failure leaves the intent retryable as dispatched.
- Local API tests prove default network disablement, synthetic provider
  acknowledgement, replay without a duplicate provider call, and route-scope
  authorization. The live PostgreSQL server-identity fixture now also proves
  the real RLS persistence path through proposal, approval, and synthetic
  executor acknowledgement with one provider call. This remains provider-
  neutral synthetic transport evidence: no live ERP/bank vendor, customer
  vault, accounting posting, compensation delivery, distributed quota, HA/DR,
  or production write-back claim.
- Exact code head `392b7907` is green on CI `30926588702` (server-boundaries
  `92050378455`, PostgreSQL/HA-DR `92050378311`, Docker parity `92052163349`),
  Security `30926583902`, Docker `30926589234`, and CodeQL `30926584585`.
- ADR: `docs/adr/0321-governed-server-writeback-dispatch-boundary.md`.

## E-372 — Server-scoped close and ownership mutations (complete bounded slice)

- Every PostgreSQL server-profile mutation in the consolidation-close lifecycle
  now re-evaluates its required `finance_core.manage` or
  `finance_core.validate` permission against the authenticated tenant and
  workspace immediately before repository access. The immutable ownership save
  route uses the same central hierarchy check; local SQLite compatibility is
  unchanged and read routes remain available through their existing read
  permission.
- Focused close/ownership/execution-scope tests pass 15/15, the final full
  pytest suite exits 0, Ruff, Mypy, build, and diff-check pass. Exact code head
  `8521b15d` is green on CI `30929398907` (server-boundaries `92059947838`,
  postgres-ha-dr `92059947810`, Docker parity `92061607466`, both Python test
  jobs and four engine-parity jobs), Security `30929399364`, Docker
  `30929398698`, and CodeQL `30929399241`.
- Boundary: this closes the server-scoped mutation adoption for the close and
  ownership route families only. Federation, complete route/job/export/UI
  adoption, distributed policy invalidation, live provider operation,
  independent HA/DR, and production IAM assurance remain open.
- ADR: `docs/adr/0322-server-scoped-close-and-ownership-mutations.md`.

## E-373 — Server-scoped close-management mutations (complete bounded slice)

- PostgreSQL server-profile close-management period initialization, task status
  changes, period lock, and period reopen now re-evaluate `close.manage`
  against the authenticated tenant/workspace before repository access. Read
  routes and local SQLite compatibility remain unchanged.
- The focused server-profile identity/scope contract passes 7/7 and the final
  full pytest suite exits 0. Ruff, Mypy, and diff-check pass. Exact code head
  `6d2a926a` is green on CI `30931676837` (server-boundaries `92067646971`,
  postgres-ha-dr `92067646818`, Docker parity `92069231895`, both Python test
  jobs and four engine-parity jobs), Security `30931676624`, Docker
  `30931675916`, and CodeQL `30931676434`.
- Boundary: this closes only the close-management mutation family. Complete
  route/job/export/UI policy coverage, federation, distributed invalidation,
  live provider operation, independent HA/DR, and production IAM assurance
  remain open.
- ADR: `docs/adr/0323-server-scoped-close-management-mutations.md`.

## E-374 — Server-scoped finance-ledger mutations (complete bounded slice)

- PostgreSQL server-profile account upsert and atomic ledger-entry creation now
  re-evaluate `finance_core.manage` against the authenticated tenant/workspace
  before repository access. Read routes, unsupported feature boundaries, and
  local SQLite compatibility remain unchanged.
- The focused server identity/scope contract passes 7/7 and the final full
  pytest suite exits 0. Ruff, Mypy, and diff-check pass. Exact code head
  `35c09f63` is green on CI `30932859161` (server-boundaries `92071583948`,
  postgres-ha-dr `92071583884`, Docker parity `92073207856`, both Python test
  jobs and four engine-parity jobs), Security `30932857268`, Docker
  `30932856740`, and CodeQL `30932859207`.
- Boundary: this covers two server finance-ledger mutation endpoints only. It
  is not statutory/legal-book posting, full Finance Core parity, complete
  route/job/export/UI policy coverage, federation, distributed invalidation,
  live providers, independent HA/DR, or production IAM assurance.
- ADR: `docs/adr/0324-server-scoped-finance-ledger-mutations.md`.

## E-375 — Server-scoped master-data mutations (complete bounded slice)

- PostgreSQL server-profile currency, organization, legal-entity, branch,
  fiscal-period, and period-status mutations now re-evaluate
  `master_data.manage` against the authenticated tenant/workspace before
  repository access. Read routes, the explicit server workspace boundary, and
  local SQLite compatibility remain unchanged.
- The focused server identity/scope contract passes 7/7, including six
  master-data mutation assertions; the broader master-data/server-scope
  selection passes 16/16. The final full suite passes with 100% local test
  completion (declared skips only), Ruff, Mypy, build, and diff-check all
  green. Hosted CI is the remaining promotion gate.
- Boundary: route-family policy binding only. Full master-data/Finance Core
  parity, federation, complete route/job/export/UI adoption, distributed
  invalidation, live providers, independent HA/DR, and production IAM
  assurance remain open.
- Exact head `d8bc4dd8` passes hosted CI `30937323538` (server-boundaries
  `92086636635`, postgres-ha-dr `92086636683`, Docker parity `92088189807`,
  both Python suites, four engine-parity jobs, and object-storage), Security
  `30937323640`, Docker `30937323622`, and CodeQL `30937323585`.
- ADR: `docs/adr/0325-server-scoped-master-data-mutations.md`.

## E-376 — Server-scoped reconciliation run mutations (complete bounded slice)

- PostgreSQL server-profile reconciliation submit, cooperative cancel, and
  requeue now re-evaluate the existing compatible permission set
  (`reconciliation.manage` OR `match.run`) against the authenticated
  tenant/workspace before repository access. The reusable central helper keeps
  OR semantics explicit; it does not narrow existing callers to one role.
- Focused reconciliation route and execution-scope tests pass 9/9, including
  six route invocations and a direct `match.run` any-permission proof. The
  full pytest suite passes with declared skips only; Ruff, Mypy, build, and
  diff-check are green locally. Exact head `d8bc4dd8` passes hosted CI
  `30937323538` (server-boundaries `92086636635`, postgres-ha-dr `92086636683`,
  Docker parity `92088189807`, both Python suites, four engine-parity jobs,
  and object-storage), Security `30937323640`, Docker `30937323622`, and
  CodeQL `30937323585`.
- Boundary: reconciliation route-family policy binding only. Distributed
  worker authorization, universal route/job/export/UI adoption, federation,
  live providers, independent HA/DR, and production IAM assurance remain
  open.
- ADR: `docs/adr/0326-server-scoped-reconciliation-run-mutations.md`.

## E-377 — Server-scoped evidence mutations (complete bounded slice)

- PostgreSQL server-profile evidence registration, linking, requirement
  creation, sensitive drill-down authorization, and checksum verification now
  re-evaluate `evidence.manage` or `evidence.verify` against the authenticated
  tenant/workspace before repository access. The former raw permission-set
  check for sensitive drill-down is replaced by the central scope helper.
- Focused evidence, execution-scope, and authorization-inventory tests pass
  12/12; Ruff and Mypy pass for the changed surfaces. Full pytest, build,
  and diff-check pass. Exact head `3778811` passes hosted CI `30940202330`
  (server-boundaries `92096349955`, postgres-ha-dr `92096349776`, Docker
  parity `92097921442`, both Python suites, engine-parity, and object-storage),
  Security `30940202609`, Docker `30940202853`, and CodeQL `30940202230`.
- Boundary: evidence route-family policy binding only. Workspace-level
  evidence persistence, universal route/job/export/UI adoption, federation,
  live providers, independent HA/DR, and production IAM assurance remain
  open.
- ADR: `docs/adr/0327-server-scoped-evidence-mutations.md`.

## E-352 — Deterministic quorum/fencing safety state machine (complete bounded slice)

- Added `reconforge.reliability.ha_dr` with a closed topology requiring three
  voter failure domains plus a witness, a two-vote quorum, monotonic terms,
  fence-before-elect failover, stable election tie-breaks, exact standby
  catch-up, and independent repromotion authorization. Stale leaders cannot
  commit after fencing.
- The generated `HA_DR_QUORUM_SIMULATION_2026-08-04.json` is digest-bound and
  schema-valid. It records two logical failovers, four ordered commits, zero
  acknowledged transaction loss, stale-commit refusal, and no split-brain in
  the model. Five focused tests pass, including input-order stability and
  tamper rejection; CI now runs the same verifier.
- Boundary: `simulation_only`. No PostgreSQL/Docker/network execution,
  external fencing device, wall-clock RPO/RTO, host-loss independence, or
  production SLO is claimed. The existing one-host PostgreSQL drill remains
  `partial`.
- ADR: `docs/adr/0302-ha-dr-quorum-fencing-safety-state-machine.md`.

## E-351 — Concrete PostgreSQL named-query read-only connector (complete bounded slice)

- Added `reference-postgres-readonly` with a dedicated `database_source`
  manifest, exact credential-free endpoint pinning, runtime DSN host/port/path
  matching, fixed `statement_lines_v1` and `trial_balance_v1` queries, bounded
  `READ ONLY` transactions, statement timeout, tenant-local context,
  parameterized cursor/limit values, canonical Decimal output, and safe error
  boundaries. The existing synthetic HTTPS database connector remains
  unchanged and distinct.
- `tests/test_postgres_database_reference.py` passes its structural/failure
  contracts and a live PostgreSQL 16 run with a non-superuser,
  non-`BYPASSRLS` role. The live path proves cursor replay, canonical
  `0E-18` normalization, read-only setup, endpoint/DSN binding, and RLS tenant
  isolation over synthetic rows.
- Boundary: two fixed deployment-provided views only. This is not ERP/bank
  vendor interoperability, provider schema compatibility, secret-vault/TLS
  operations, write-back, throughput/soak, HA/DR, or production readiness.
- Full repository gates then passed: 2,383 collected tests in 316.3s, Ruff,
  Mypy, Bandit, package build, `uv lock --check`, policy validation,
  hash-locked all-extra audit with zero findings, and diff check. A separate
  ambient pip-audit call timed out at PyPI and is recorded as operationally
  blocked rather than green; the hash-locked CI-equivalent audit is the valid
  dependency result.
- Hosted commit `f8e6996b` is green: CI `30865985067` (including
  server-boundaries job `91857821428`), Security `30865984998`, Docker
  `30865985056`, and CodeQL `30865985004` all passed.
- ADR: `docs/adr/0301-postgres-named-query-readonly-connector.md`.

## E-333 — Authenticated PostgreSQL PPA evidence API (complete bounded slice)

- Added strict, additive `POST /api/v1/consolidation-ppa` and
  `GET /api/v1/consolidation-ppa/{artifact_id}` routes. Preparation requires
  `finance_core.manage`; reads require `finance_core.read` or
  `finance_core.manage`; the preparer is bound to the authenticated identity.
- The routes execute only with the PostgreSQL server profile, use the existing
  tenant transaction/RLS boundary and PPA repository, and preserve the
  replay-verified `posted: false` evidence contract. Local mode fails closed
  instead of falling back to SQLite.
- Focused API/authorization tests pass locally. The full local suite collected
  2,336 tests and passed with zero failures/errors; Ruff, Mypy, Bandit, package
  build, pip-audit, and diff checks also pass. CI run `30814401814` passed the
  Python 3.11/3.12, server-boundaries, engine-parity, and Docker-parity jobs;
  Security `30814401794`, Docker `30814404291`, and CodeQL `30814402171` also
  passed.
- The route contract is live-verified only inside the synthetic server
  boundary described by E-334; E-332's `30811914832` remains the separate
  persistence-adapter gate. This is not a hosted API deployment.

## E-334 — Live PostgreSQL PPA API runtime gate (complete bounded slice)

- Extended the existing server-identity runtime contract with the PPA schema,
  a distinct reviewer identity, authenticated step-up, tenant-scoped POST/GET
  calls, and append-only cleanup. Local environments without PostgreSQL skip
  this capability test as declared.
- CI server-boundaries run `30815726556` passed the extended
  `test_live_server_api_uses_postgres_identity_and_tenant_scope` path, along
  with the full Python/parity/security/Docker/CodeQL checks. The PPA API is
  live-verified only within this synthetic single-node server boundary; it is
  not a hosted deployment or production-readiness claim.

## E-335 — Live PostgreSQL true many-to-many worker evidence (complete bounded slice)

- Extended the existing grouped-worker runtime contract with a second explicit
  `many-to-many` run. It retains the prior one-to-many case, requires four
  deterministic Cartesian edges, and compares the persisted decision digest to
  the direct strategy output.
- Local environments without PostgreSQL skip the two live grouped-worker
  cases. CI server-boundaries run `30817197467` passed both the retained
  one-to-many and new true many-to-many assertions; the full Python,
  parity/security, Docker, and CodeQL checks passed on the same head.
- This is one small synthetic single-node worker cycle, not PostgreSQL scale,
  soak, distributed capacity, HA/DR, posting, or write-back evidence.

## E-336 — Live PostgreSQL FX-aware grouped worker evidence (complete bounded slice)

- Added a third grouped-worker run with explicit EUR→USD rate data,
  `target_currency: USD`, and `many-to-one` mode. The test requires two USD
  edges, USD lineage, and direct strategy digest parity alongside the existing
  same-currency runs.
- Local environments without PostgreSQL skip the live cases. CI
  server-boundaries run `30818624136` passed the FX run and the full
  Python/parity/security/Docker/CodeQL matrix. The fixed synthetic rate is not
  live-market or accounting-rate evidence.

## E-337 — Live PostgreSQL portfolio partial-settlement and fee lineage (complete bounded slice)

- Extended the grouped-worker runtime contract with a fourth `portfolio` run
  using explicit `netting_mode: net`, Decimal fee fields, and
  `allow_partial_settlement: true`. The worker persists one partial proposal
  (`120 - 20` net against `80`) with a visible `20` residual and one exact
  `50`/`50` portfolio match.
- The test compares the persisted portfolio result digest with the direct
  strategy output and checks fee totals, net totals, settled amount, residuals,
  reason code, and tenant-scoped result identity. This is synthetic fixed-date
  data; it does not prove settlement posting, provider acknowledgement, scale,
  soak/backpressure, HA/DR, or production accounting treatment.
- CI run `30820862956` passed Python 3.11/3.12, server-boundaries, all engine-
  parity cells, and Docker-parity; Security `30820863921`, Docker
  `30820864225`, and CodeQL `30820865109` also passed.

## E-338 — Live PostgreSQL durable-job same-tenant claim contention (complete bounded slice)

- Extended the existing live durable-job contract with four synthetic jobs for
  one tenant, three partitions per job, and two independent PostgreSQL worker
  connections draining the same queue. `FOR UPDATE SKIP LOCKED` claim
  ownership, checkpointed completion, and unique partition effects are
  asserted for every job.
- This is a small contention gate only; it does not establish PostgreSQL
  throughput, fairness SLOs, soak, distributed supervision, queue HA,
  automatic failover, or production readiness.
- CI run `30822148482` passed Python 3.11/3.12, server-boundaries, all engine-
  parity cells, and Docker-parity; Security `30822149026`, Docker
  `30822148703`, and CodeQL `30822149876` also passed.

## E-339 — HA/DR verified profiles require independent failure domains (complete bounded slice)

- Tightened `ha_dr_operational_profile.schema.json` so a profile marked
  `verified` must report at least two observed failure domains in addition to
  all existing verification booleans.
- Added a regression that sets every boolean true while retaining one domain
  and requires schema rejection. The retained single-host profile remains
  `partial`; no independent-host, quorum, automatic-failover, site-loss, or
  production-SLO evidence is introduced.
- CI run `30823572161` passed Python 3.11/3.12, server-boundaries, all engine-
  parity cells, and Docker-parity; Security `30823574298`, Docker
  `30823572431`, and CodeQL `30823572439` also passed.

## E-340 — Live PostgreSQL carry-forward and reversal worker evidence (complete bounded slice)

- Added `PostgresSequentialMatchingAdapter` for explicit `carry-forward`,
  `sequence-window`, and `reversal-pairing` modes. It preserves strategy
  manifests/digests, allocation residuals, explicit reversal-link basis,
  unmatched records, and ambiguity exceptions through the existing worker
  result contract.
- Local adapter and domain contracts pass. CI server-boundaries run
  `30825258020` passed the carry-forward and explicit reversal runs under the
  non-superuser PostgreSQL boundary, including persisted residual/link lineage
  and direct strategy digest parity. Security `30825257886`, Docker
  `30825258043`, and CodeQL `30825258239` also passed; this remains synthetic
  single-node evidence, not posting, write-back, scale, HA/DR, or production
  readiness.

## E-341 — Atomic durable-job queue backpressure (complete bounded slice)

- Added additive `submit_bounded` application and governed-service methods plus
  SQLite/PostgreSQL repository implementations. The cap is enforced inside one
  transaction for each `(tenant_id, workspace_id, entity_id)` lane and counts
  `queued` and `retrying` work.
- Identical idempotent replay is resolved before capacity rejection. New work
  at the cap raises `DurableJobBackpressureError` with no row or transition;
  PostgreSQL serializes the count/insert section with a transaction-scoped
  advisory lock, while SQLite uses `BEGIN IMMEDIATE`.
- Focused local application, durable-job, PostgreSQL contract, Ruff, and Mypy
  checks pass; the full local suite then passed all 2,341 collected tests in
  306.2 seconds, with Bandit and pip-audit also green. CI run `30828746821`
  passed Python 3.11/3.12, server-boundaries (including the new PostgreSQL
  assertions), engine-parity, and Docker-parity; Security `30828746100`,
  Docker `30828746066`, and CodeQL `30828746780` also passed. No throughput,
  fairness SLO, soak, distributed quota, HA/DR, or production-capacity claim
  is made.
- ADR: `docs/adr/0292-atomic-durable-job-backpressure.md`.

## E-342 — Deterministic fair durable-job lane scheduling (complete bounded slice)

- Added `DurableJobLane` and a process-scoped `RoundRobinDurableJobScheduler`.
  Worker claims now accept optional exact workspace/entity filters while keeping
  the existing tenant/RLS and lease-fencing boundaries intact.
- The scheduler scans each configured lane once from a rotating cursor and
  advances after the selected lane. Focused SQLite evidence alternates two
  non-empty lanes for six claims with no cross-lane job; the live PostgreSQL
  server-boundary test exercises the same assertions under the non-privileged
  role when CI provides the database.
- Local focused tests and static checks pass. The local environment has no
  `RECONFORGE_TEST_POSTGRES_DSN`, so the PostgreSQL runtime is CI-only for this
  slice. CI run `30831774662` passes server-boundaries, Python 3.11/3.12,
  engine-parity, and Docker-parity; Security `30831776530`, Docker `30831774950`,
  and CodeQL `30831774663` also pass. This is process-scoped fairness evidence,
  not distributed fairness, throughput, soak, HA/DR, or production-capacity
  evidence.
- ADR: `docs/adr/0293-deterministic-fair-durable-job-lane-scheduling.md`.

## E-343 — PostgreSQL governed write-back intent persistence (complete bounded slice)

- Added migration `0061_pg_writeback_intents` and
  `PostgresWritebackIntentRepository`. It stores only canonical intent JSON,
  digest, lifecycle version, scope, and timestamp; payloads and secrets are
  excluded. Forced RLS requires the tenant/workspace scope, and append-only
  triggers reject updates and deletes.
- The repository mirrors the existing governed lifecycle: identical replay is
  idempotent, maker/checker approval and dispatch/acknowledgement versions use
  optimistic concurrency, same-intent writers use a PostgreSQL transaction
  advisory lock without UPDATE privilege, reads revalidate the persisted
  digest, and sibling tenants are excluded.
- Local schema/contract checks pass; CI run `30837085198` passed the live
  PostgreSQL server-boundary test under a non-superuser role. This remains
  intent persistence only: no provider payload, credential, network dispatch,
  compensation execution, HA/DR, or production write-back claim.
- ADR: `docs/adr/0294-postgres-writeback-intent-runtime-evidence.md`.

## E-344 — PostgreSQL server-profile write-back intent API boundary (complete bounded slice)

- The proposal, maker-checker approval, and acknowledgement routes now select
  the PostgreSQL intent repository when the explicit server profile is enabled;
  local mode keeps its SQLite adapter. Request tenant/workspace headers must
  match the authenticated execution scope, and proposals must name the
  authenticated actor.
- The route contract proves the PostgreSQL operation seam and an explicit
  `network_dispatch: disabled` response. The underlying live PostgreSQL
  persistence gate remains the runtime evidence for RLS, replay, lifecycle, and
  append-only controls.
- Hosted head `ea0e581` is green in CI `30839751728`, Security `30839744852`,
  Docker `30839746700`, and CodeQL `30839744249`.
- Boundary: this is API/backend selection and scope-binding evidence only. No
  provider I/O, secret-vault integration, compensation delivery, HA/DR, or
  production write-back is claimed.
- ADR: `docs/adr/0295-postgres-writeback-api-server-boundary.md`.

## E-345 — Digest-bound HTTPS write-back transport boundary (complete bounded slice)

- Added `WritebackNetworkRegistration`, `PinnedHttpsPostTransport`, and
  `WritebackNetworkExecutor` as a separate opt-in provider boundary. Exact
  HTTPS egress, credential-reference authentication, allowed operations,
  feature enablement, request/response bounds, rate limiting, and finite
  retries are closed and typed; the existing v1 connector manifests remain
  read-only.
- Dispatch accepts only an already dispatched intent, resolves a short-lived
  payload, verifies its SHA-256 against `payload_digest`, reuses the original
  idempotency key on each retry, and validates a canonical provider response
  digest before returning an acknowledged intent and receipt. Secrets and
  payloads are not persisted or returned.
- Focused tests cover success, retry/failure injection, payload/response
  tamper, secret isolation, egress/size/content-type guards, and pinned POST
  request shape.
- Boundary: synthetic injected transport only. No vendor endpoint, customer
  credential, hosted vault, compensation delivery, accounting posting, HA/DR,
  or production write-back is claimed.
- Hosted head `bf4cc02` is green in CI `30842290819`, Security `30842291391`,
  Docker `30842290618`, and CodeQL `30842290616`.
- ADR: `docs/adr/0296-writeback-network-transport-is-explicit-and-digest-bound.md`.

## E-346 — PostgreSQL bounded multi-worker scale profile (complete bounded slice)

- Added `reconforge/benchmark/postgres_durable_job_scale.py` and a live
  server-boundary contract for eight independent worker connections, four
  tenant lanes, 64 synthetic jobs, four partitions per job, and 256 declared
  partition effects.
- The acceptance result requires completed terminal jobs, exact partition
  cardinality, zero duplicate effects, forced-RLS lane scope, and zero queued
  or running rows after the drain. Runtime and throughput are observations,
  not capacity claims.
- The contention run exposed and then closed a stale-join takeover race:
  `claim_next` now rechecks an active lease after locking the job row, so only
  an explicitly expired lease can be reclaimed.
- Local profile/contract tests pass. Hosted server-boundaries run
  `30845549418` passed the live PostgreSQL 16 Alpine profile, both Python
  versions, all four engine-parity cells, and Docker-parity. Security
  `30845549419`, Docker `30845549425`, and CodeQL `30845549444` also passed.
  No throughput, capacity, soak, distributed fairness, queue HA, HA/DR,
  RPO/RTO, or production-sizing claim is made. ADR:
  `docs/adr/0297-postgres-durable-job-bounded-scale-profile.md`.

## E-347 — PostgreSQL bounded outbox multi-worker delivery (complete bounded slice)

- Added a four-worker, 64-event transactional-outbox profile using the
  existing tenant-bound PostgreSQL worker and an injected idempotent sink.
  The structural acceptance is one observation per event and zero pending,
  claimed, or dead rows after acknowledgement.
- Local live PostgreSQL test passes. Hosted server-boundaries in CI
  `30847668458` pass the 64-event profile; Python 3.11/3.12, all four
  engine-parity cells, and Docker-parity also pass. Security `30847668487`,
  Docker `30847668631`, and CodeQL `30847668940` pass. This is one-node
  synthetic claim/publish/acknowledge evidence only, not broker,
  crash-after-publish, queue-HA, failover, throughput, soak, or production
  delivery evidence. ADR:
  `docs/adr/0298-postgres-outbox-bounded-multi-worker-profile.md`.

## E-348 — PostgreSQL idempotent outbox-consumer receipt (complete bounded slice)

- Added migration `0062_pg_outbox_consumer` and
  `PostgresOutboxConsumer`. A database-local effect and its immutable
  `(tenant, consumer, event)` receipt commit in one transaction; advisory
  locking serializes concurrent replays, the digest is recomputed from the
  persisted outbox JSONB row, same-digest replays return `duplicate`, and
  changed/missing events fail closed.
- The live PostgreSQL contract simulates a crash after the consumer effect
  commits but before outbox acknowledgement. Lease reclaim and redelivery
  leave one effect row and one receipt, then acknowledge the outbox event.
  Local PostgreSQL 16 passed; structural tests, full outbox contracts,
  migration head, Ruff, and Mypy passed.
- This proves a bounded single-node database-local exactly-once business
  effect boundary. It does not prove external broker/provider exactly-once
  delivery, cross-host failover, queue HA, throughput, soak, compensation,
  or production readiness. ADR:
  `docs/adr/0299-postgres-outbox-idempotent-consumer-receipt.md`.
- Hosted verification for code head `c6a73dd9` passed CI `30851329394`
  (server-boundaries, Python 3.11/3.12, engine-parity, docker-parity),
  Security `30851329385`, Docker `30851329398`, and CodeQL `30851329332`.

## E-349 — PostgreSQL grouped matching bounded multi-worker scale

- Added `reconforge/benchmark/postgres_grouped_matching_scale.py` and a live
  contract over four independent worker connections, five grouped modes, and
  a declared 32-run/64-partition profile. The bounded local test uses a
  five-run/ten-partition variant and retains every mode.
- The worker contract asserts complete runs and checkpoints, mode-derived
  result cardinality, unique `(run, partition, left_id, right_id, status)`
  identities, zero failed/active runs, and non-empty effect/manifest digests.
  It also exposed PostgreSQL `Decimal` scale (`0E-18`) as an invalid persisted
  lexeme; the grouped adapter now canonicalizes Decimal JSON/result values
  before repository validation.
- Focused command with PostgreSQL 16 and a non-superuser RLS role:
  `python -m pytest -q tests/test_postgres_grouped_matching_scale.py` ->
  `3 passed`. Ruff passes for the adapter, profile, and tests.
- Boundary: synthetic one-tenant single-node evidence only. The observed
  runtime is not throughput, capacity, soak, SLO, production sizing, provider,
  statutory posting, cross-host scheduling, queue HA, automatic failover, or
  HA/DR evidence. ADR:
  `docs/adr/0300-postgres-grouped-matching-bounded-scale-profile.md`.
- Hosted verification for code head `3ae39b68` passed CI `30854414579`,
  including server-boundaries job `91821932337`, both Python test/build jobs,
  all four engine-parity cells, and Docker-parity. Security `30854414587`,
  Docker `30854414580`, and CodeQL `30854414574` also passed.

## E-350 — Remediate hosted cryptography advisory in the locked supply chain

- Hosted Security reported `CVE-2026-69247` against the previous
  `cryptography==49.0.0` lock on Python 3.11 and 3.12. No exception was added.
- Reviewed remediation updates the optional backup/connectors pin to
  `cryptography==50.0.0`, resolves compatible `pyOpenSSL==26.4.0` for the
  pinned WebAuthn 3.0.0 stack, moves the absolute uv cutoff to
  `2026-08-02T00:00:00Z`, and regenerates the hash-bearing `uv.lock`.
- Local `uv lock --check`, closed supply-chain policy validation, locked
  all-extra Python 3.14 sync, hash-exported `pip-audit` (`pip_findings=0`),
  and cryptographic/WebAuthn/backup/signature compatibility tests pass.
- Hosted verification for head `a4a35f8` is green: CI `30856023045` passed
  Python 3.11/3.12, server-boundaries, four engine-parity cells, and
  Docker-parity; Security `30856022993`, Docker `30856022975`, and CodeQL
  `30856022972` also passed.
- Boundary: this is dependency remediation evidence only. It does not prove
  package safety, reachability, provenance, independent review, or production
  readiness.

## E-293 — Immutable local delegation administration

- Migration 27 adds tenant/workspace-scoped `policy_delegations`; a typed
  SQLite repository creates approved grants, resolves only effective grants at
  an explicit instant, and allows independent-actor revocation only.
- Focused migration/repository/domain tests, Ruff, and Mypy pass. This is a
  Community SQLite slice only; federation, PostgreSQL/RLS parity, API/jobs/
  exports/UI enforcement, cache invalidation, and emergency access remain open.
- Corrected commit `30dfd06` passed CI `30764141422` (Python 3.11/3.12,
  parity, server-boundaries, docker-parity), CodeQL `30764141410`, Security
  `30764141411`, and Docker `30764141415`.

## E-294 — PostgreSQL durable-job runtime gate

- CI server-boundaries run `30764427298` passed the existing live durable-job
  application/worker contract against PostgreSQL 16 Alpine using the
  non-privileged role. Inventory now records both boundaries as
  `live_verified_current`.
- Limits: one node, synthetic workload, no queue HA/failover, no soak,
  distributed capacity, or RPO/RTO evidence.
- Final CI run `30765377133` passed both Python versions, server-boundaries,
  parity, and Docker; CodeQL `30765377149` and Security `30765377138` passed.

## E-295 — PostgreSQL intercompany runtime gate

- The existing live intercompany test passed in CI `30765662833` under the
  non-privileged PostgreSQL role: exact Decimal import, tolerance matching,
  imbalance exception/evidence, settlement/outbox effects, tenant RLS, and
  SQLite parity.
- This is an operational control workflow only; statutory consolidation,
  elimination posting, ERP write-back, HA/DR, and RPO/RTO remain open.

## E-296 — Reference connector manifest portfolio conformance

- Added `verify_manifest_portfolio` and a focused test over REST, payment
  statement, SFTP, object-storage, and database reference manifests. All five
  pass the shared read-only/synthetic/idempotent/schema-threat/secret-egress
  contract.
- This remains provider-neutral synthetic evidence; live vendors, vault
  provisioning, write-back, and interoperability remain open.
- CI `30766363953` passed both Python versions, server-boundaries, parity, and
  Docker; CodeQL `30766363941` and Security `30766363936` passed.

## E-297 — Governed durable-job mutation boundary

- Added `GovernedDurableJobApplicationService`: submit/cancel now have an
  explicit path that requires actor identity match, central permission,
  tenant/workspace scope, and SoD before repository mutation.
- Denied requests are proven no-effect; the legacy lifecycle remains available
  for callers with an independent authorization boundary. Route migration,
  federation, and cache invalidation remain open.
- Final prior CI `30767365683` passed both Python versions, server-boundaries,
  engine-parity, and docker-parity; CodeQL `30767365674` and Security
  `30767365673` passed. PostgreSQL parity classifies the wrapper as
  `live_verified_current` only after the new E-298 live gate passes.

## E-298 — Governed durable-job PostgreSQL runtime boundary

- The live server-boundaries contract exercises the governed wrapper over the
  non-privileged PostgreSQL durable-job repository: denied permission causes no
  row, allowed scoped submit creates one row, and sibling-tenant visibility is
  empty. The wrapper remains opt-in; routes, federation, and cache invalidation
  are not yet fully migrated.
- Final CI `30768307123` passed both Python versions, server-boundaries,
  engine-parity, and Docker; CodeQL `30768307156` and Security `30768307119`
  also passed.

## E-299 — Provider-neutral ERP read-only connector

- `reference-erp-readonly` adds a closed entity-scoped ledger-line page
  contract over the existing governed HTTPS executor. Exact Decimal amounts,
  duplicate/mixed-entity rejection, cursor/idempotency, canonical digests,
  secret references, and egress allowlisting are tested.
- This is synthetic reference evidence only; live ERP onboarding and
  write-back remain open.

## E-300 — HA/DR operational profile and declared targets

- The retained three-run PostgreSQL synchronous-standby drill is now bound to
  a closed operational profile with explicit zero-loss and 60-second
  failover/failback targets, a reproducible runbook, and residual limitations.
- Status is `partial`: all nodes still share one host/failure domain and the
  controller is manual; quorum, automatic failover, site loss, and production
  SLO evidence remain open.

## E-312 — HA/DR verification is fail-closed

- The operational-profile schema now requires explicit verification booleans
  for independent failure domains, quorum/witness fencing, automatic failover,
  backup/restore integrity, repeated integrity, observed RPO/RTO, and
  production SLO evidence.
- JSON Schema conditional validation rejects `status: verified` unless every
  gate is true. The retained Docker profile records the measured backup,
  repeated-integrity, and RPO/RTO gates while keeping the missing independent
  topology, quorum, automatic failover, and production-SLO gates false.
- This closes documentation drift only; it does not claim independent-host HA,
  site-loss recovery, automatic failover, or production readiness.

## E-301 — Scope-aware allowed-only policy decision cache

- The opt-in cache keys every policy context field and policy version, stores
  only allowed non-delegated decisions, and supports explicit
  tenant/workspace/global invalidation.
- Focused tests prove denials and delegated authority bypass storage and that
  invalidating one tenant does not evict a sibling tenant. Existing routes are
  intentionally uncached until each mutation path owns invalidation. Full CI
  run `30770651403` passed on `9582ac2`.

## E-302 — PostgreSQL immutable delegation repository

- Added migration `0056_pg_policy_delegations` and a typed
  `PostgresDelegationRepository`. Grants are tenant/workspace scoped, use an
  explicit evaluation instant, and are protected by forced RLS plus a trigger
  that permits only independent active-to-revoked transitions.
- Focused schema, migration, validation, and repository contracts pass under
  ADR 0253. CI server-boundaries run `30771736208` passed the PostgreSQL
  create/effective-read/revoke/isolation gate under the non-privileged role.
  Federation, route coverage, and cache invalidation wiring remain open.

## E-303 — Explicit API policy cache adoption

- `create_api_app(..., policy_cache_enabled=True)` now installs the bounded
  allowed-only cache; the default remains uncached for compatibility.
- `require_permission` and `require_any_permission` use the cache only when the
  app explicitly enables it. Every non-safe HTTP request invalidates the cache,
  including failed mutations. Focused API/cache tests pass under ADR 0254.
- Distributed invalidation, workspace-specific optimization, and complete
  route/action attribute coverage remain open.
- CI run `30772431595` passed the full compatibility, server-boundaries,
  engine-parity, Docker, Security, and CodeQL gates.

## E-304 — Deterministic management trial-balance projection

- Added `consolidation-management-trial-balance-v1`, a pure projection from a
  verified non-posting worksheet. Exact reporting-currency lines retain
  worksheet source references; the artifact enforces a zero balance and a
  canonical digest for replay/tamper detection.
- Focused tests, Ruff, and Mypy pass. ADR 0255 and the closed schema define the
  boundary: management review artifact only, not a statutory statement, legal
  book, tax report, or assurance conclusion.
- Acquisition/fair-value/goodwill/equity-method policy, PostgreSQL persistence,
  API/CLI/UI exposure, live rates, and ERP/bank write-back remain open.
- Corrected remote gates: CI `30773351786`, Docker `30773351797`, Security
  `30773351818`, and CodeQL `30773351787` passed. The earlier CI `30773107270`
  is retained as a diagnostic failure caused by stale threat-model evidence.

## E-305 — Explicit field-level authorization and masking

- Central policy now accepts `requested_field_names` and
  `authorized_field_names`; any requested field outside the authorized set is
  denied with `field_scope_denied`. `evaluate_principal_access` forwards both
  sets for callers that can supply a versioned field policy.
- `reconforge.auth.field_access.project_fields` provides a separate deterministic
  allowlisted projection: authorized masked fields become `[REDACTED]`, denied
  fields are reported, and the result carries a stable digest.
- Focused policy/field tests pass. This is a reusable primitive, not evidence
  that every route, export, or UI field has migrated; federation, administration,
  and PostgreSQL policy persistence remain open.
- Remote gates: CI `30773746150`, Docker `30773746185`, Security `30773746176`,
  and CodeQL `30773746148` passed for the field-policy slice.

## E-306 — Immutable local write-back intent history

- Migration 28 adds `connector_writeback_intents` with append-only update/delete
  triggers and a tenant/workspace/versioned primary key. The new SQLite
  repository persists only canonical intent contracts and digests; payloads and
  credentials remain outside storage.
- Identical intent digests replay idempotently. New versions require the current
  version and an allowed lifecycle transition; cross-scope reads are empty and
  tamper/delete attempts fail closed.
- Focused repository, connector lifecycle, migration, backup, Ruff, and Mypy
  tests pass. No provider network I/O is performed; live interoperability and
  external acknowledgement reconciliation remain open.
- Corrected remote gates: CI `30774596822`, Docker `30774596807`, Security
  `30774596805`, and CodeQL `30774596803` passed. The earlier CI `30774263443`
  is retained as a diagnostic failure caused by stale compatibility evidence.

## E-307 — Authenticated write-back proposal API boundary

- Added `POST /api/v1/connectors/writeback/intents` with the dedicated
  `connectors.writeback.propose` permission. The route binds `requested_by` to
  the authenticated local user and persists through the append-only repository.
- Repeated identical proposals return the same version/digest; actor mismatch
  is denied. The response explicitly reports `network_dispatch=disabled` and
  no provider call is possible through this route.
- Approval, provider acknowledgement, compensation, and live ERP/bank
  execution remain separate evidence gates.
- Remote gates: CI `30776133163`, Docker `30776133152`, Security `30776133138`,
  and CodeQL `30776133117` passed for the maker-checker approval slice.
- Remote gates: CI `30775343346`, Docker `30775343347`, Security `30775343354`,
  and CodeQL `30775343353` passed.

## E-308 — Maker-checker write-back approval API

- Migration 29 adds `connectors.writeback.approve`, separate from proposal
  permission. The approval route requires tenant/workspace scope, loads the
  latest immutable intent, and appends an approved version only after the
  authenticated checker is distinct from the requester.
- Invalid state/version, self-approval, and missing feature enablement fail
  closed. The response explicitly keeps `network_dispatch=disabled`; provider
  acknowledgement and execution remain open.

## E-309 — Provider acknowledgement reconciliation API

- Migration 30 adds `connectors.writeback.reconcile`, separate from proposal
  and approval permissions. The scoped route loads only the latest local intent
  and requires its lifecycle to be dispatched before acknowledging it.
- Provider reference and response digest are appended as a new immutable
  acknowledged/rejected version and must carry the original idempotency key.
  The route performs no provider call and reports `network_dispatch=disabled`.
- Local focused tests pass; live provider interoperability, credentials,
  settlement semantics, compensation, and production deployment remain open.

## E-310 — Local consolidation-close drill-down API

- Added permissioned read-only endpoints under `/api/v1/consolidation-close`
  for workspace-scoped periods, runs, replay-verified run details, and summary.
- The route passes the authenticated actor to the existing authorization
  boundary and repository replay verifier. Unknown workspaces and tampered
  persisted worksheets fail closed; no new posting or external write-back path
  is exposed.
- This improves local API/evidence drill-down only. PostgreSQL consolidation
  parity, statutory statements, UI workflow, and production close claims remain
  open.

## E-311 — PostgreSQL consolidation-close replay and period SoD hardening

- Conflicting idempotent run identifiers now fail closed when worksheet digest
  or preparer differs. JSONB worksheets and journal digests are replay-verified
  before run reads, lists, or summaries expose them.
- Period lock/reopen transitions persist attributed events with the supplied
  reason and reject reopening by the actor who locked the period.
- The runtime claim remains bounded to one synthetic PostgreSQL CI node;
  restore, HA/DR, ERP write-back, and external assurance remain open.

## E-292 — Explicit expiring delegation in central policy

- The central policy engine now evaluates temporary delegated authority using a
  stable delegation ID, timezone-aware expiry, and caller-supplied evaluation
  instant. Missing evaluation time and expired authority deny by stable codes.
- This closes only the pure policy invariant. Delegation administration storage,
  federation, route/job/export/UI coverage, and PostgreSQL policy parity remain open.
- Commit `8dd94f4` passed CI run `30762890688` (Python 3.11/3.12, parity,
  server-boundaries, docker-parity), CodeQL `30762890703`, Security
  `30762890686`, and Docker `30762890687`.

## E-290 — PostgreSQL consolidation-close control journal boundary

- Added a tenant-scoped PostgreSQL adapter and Alembic migration for verified
  consolidation periods, worksheet runs, maker-checker transitions, immutable
  posting/reversal effects, row-version concurrency guards, and RLS.
- This is recorded as `contract_only`: the JSONB control-journal boundary is
  implemented and structurally tested, but live runtime evidence, ERP/bank
  write-back, statutory consolidation, HA/DR, and restore drills remain open.
- The initial CI server-boundaries failure was a migration-registry compatibility
  defect, not a database migration failure; it was corrected and covered by the
  PostgreSQL operations tests.

## E-291 — Live PostgreSQL consolidation-close gate

- CI run `30762214054` passed the unskipped live lifecycle test under the
  non-privileged application role, including tenant isolation, idempotent replay,
  maker-checker transitions, posting/reversal effects, and period lock/reopen.
- The parity inventory now marks `ConsolidationCloseApplicationService` as
  `live_verified_current`; this does not claim ERP write-back, statutory posting,
  restore, HA, or RPO/RTO.

## E-282 — Published 100K durable-job profile

- The durable-job harness now declares and verifies a hardware-scoped
  `durable-job-load/100k-tier-v1` profile: 16 workers, 10,000 jobs, 10
  partitions per job, four fair tenant lanes, and 100,000 committed effects.
- Two Windows 11/Python 3.14.6 runs completed with zero duplicate effects,
  drained queues/running depth, equal effect/manifest digests, and 2,500
  completions per tenant.
- This remains single-host SQLite evidence. PostgreSQL parity, distributed
  throughput, backpressure, soak, HA/DR, and 1M/10M tiers remain open.

## E-283 — Current PostgreSQL close-management runtime evidence

- The current CI server-boundaries run exercised the existing close-management
  PostgreSQL adapter for tenant isolation, dependency DAG guards, readiness,
  lock/reopen lifecycle, audit/outbox evidence, and locked mutation refusal.
- The parity inventory intentionally remains `live_test_available` until a
  dedicated current-live gate promotes this boundary.
- This is not full consolidation posting or statutory reporting evidence;
  journals, eliminations/NCI, restore, HA/DR, and RPO/RTO remain open.

## E-284 — Reference payment-statement connector

- Added a closed, synthetic `reference-payment-statement-readonly` connector
  with exact Decimal amounts, unique IDs, booking/value-date validation,
  cursor/idempotency reads, canonical digests, and allowlisted egress.
- It is deliberately read-only and does not count as a live bank/ERP
  integration or write-back capability.

## E-285 — Central policy amount and classification bounds

- `central-policy-v1` now supports exact finite Decimal amount floors/ceilings,
  region scope, and data-classification scope with deny-by-default behavior.
- Existing callers remain compatible because the new attributes are optional;
  surface-wide propagation and enterprise IAM administration remain open.

## E-286 — Bounded durable-job producer backpressure

- A separate benchmark now enforces an eight-job queued cap while existing
  workers drain 64 jobs. Two runs held the maximum queue at 8, committed 256
  effects with zero duplicates, and produced matching digests.
- Evidence is local SQLite only; distributed queue backpressure and SLOs
  remain open.

## E-287 — Injected governed write-back transport

- Write-back now has a transport-injected dispatch boundary that requires the
  original idempotency key in the provider acknowledgement and fails closed on
  provider errors or mismatches.
- It remains synthetic and network-free; live providers and posting evidence
  are not claimed.

## E-288 — Grouped matching mutation campaign

- Added a bounded campaign for three critical financial mutants; all 3 were
  killed and no survivor remained.
- This is a targeted request-level regression sentinel, not a platform-wide
  mutation score.

## E-289 — Current-live PostgreSQL Close Management gate

- `CloseManagementApplicationService` is now `live_verified_current` through
  a dedicated PostgreSQL 16 CI gate covering lifecycle, tenant isolation,
  readiness, lock/reopen, and audit/outbox evidence.
- This does not promote the absent Consolidation Close adapter or prove
  consolidation posting, restore, HA/DR, or RPO/RTO.

## Snapshot boundary

- Branch: `codex/consolidation-journal-lifecycle`, current E-332 code head `df5eb094df104483ac76f98222825a6677dc144a`; Draft PR #71 remains deliberately unmerged.
- Phase 1 base: `1c633eea53a2f11c9a90af57edfc80a36faeef82` (merged atomic application-boundary PR #62)
- Phase 0 signed-candidate source remains `d47edd845e6aef3bae16e05698e07878086d690b`; its evidence is immutable historical baseline, not evidence for Phase 1 changes.
- Publication scope: PR #54 merged the evidence-bounded Phase 0 implementation. Signed Release Candidate run `30243819239` is non-publishing: it retained review artifact `8644255664` and pushed only the digest-addressed candidate image required for verification; no GitHub Release, PyPI publication, compliance claim, or production migration occurred.
- PR #66 merged the Phase 1–3 head `dbbeaae9fb765835b9179f338b1443e9f15d52c0` into `main` at `5d401e70c3a0e3cf507c2c7cf635dfc99b01a9af`. Draft PR #67 contains P4-FIN-001 at exact head `836bdc5f75041a2967a51eecfd51dad6c94cb3e6`; all 15 reported checks pass. Stacked Draft PR #68 targets that branch; its initially published P4-FIN-002 worksheet head `c5f23834a2546a29874164d7447f2b258bbe2350` also passed all 15 reported checks. GitHub reported both candidates `CLEAN`/`MERGEABLE`; both remain deliberately unmerged.
- GitHub Actions run `30239994946` closes P0-009; runs `30240642293`, `30240642306`, `30240642321`, and `30240642386` close P0-SEC-008. Exact-main CI `30242293585`, Security `30242293659`, Docker `30242293668`, CodeQL `30242293667`, and OpenSSF Scorecard `30242293599` pass on `d47edd8`. E-087 closes P0-SEC-006/007 through the GitHub-verified signed tag and independently verified retained provenance/SBOM bundles. All 22 evidence-defined Phase 0 tasks are complete.

## Plan status at 2026-08-01

- **Phase 1 (Foundation)**: `docs/execution/PHASE_1_EXIT_AUDIT.yaml` remains `verified`. All required gates and backend-neutrality/operational evidence are closed within the declared scope.
- **Phase 2 (Matching & Evidence 2.0)**: `docs/execution/PHASE_2_EXIT_AUDIT.yaml` remains `verified`. Deterministic matching, evidence graph, reconciliation-as-code, and benchmark evidence are closed within the declared single-process/declared benchmark limits.
- **Phase 3 (Enterprise Product)**: required owner/team scope is `13/13` completed at its documented bounded maturity. `P3-ENT-013` is closed by E-251. `P3-EXT-001` and `P3-EXT-002` are deferred optional assurance items and are not release blockers.
- **Phase 4 (Global Capability Expansion)**: the seven owner-requested workstreams remain active. `P4-FIN-001` is complete at its bounded translation-artifact scope; `P4-FIN-002`, `P4-MAT-001`, and `P4-SCL-001` remain active; live connectors/write-back, independent-domain HA/DR, complex enterprise policy, and complete coherent breadth remain open. E-435 delivers the first experimental retail POS settlement slice, not the breadth exit gate.
- The complete required Phase 1–3 scope is `41/41`; external evidence remains unverified and must not be claimed.
- PR #66's earlier optional-dependency, PostgreSQL harness/registry, and Gitleaks failures were repaired and remotely verified on the Phase 1–3 head. P4-FIN-001 is remotely green on Draft PR #67. The initial P4-FIN-002 worksheet candidate is remotely green on stacked Draft PR #68; every later head still requires its own exact remote verification before merge consideration.
- A historical Docker-API connectivity block was recorded on 2026-07-31 for one run of `verify_postgres_reliability.py`, `verify_postgres_ha_dr.py`, and `verify_otel_collector_distribution.py`; later reruns in the same session completed successfully (`E-227` to `E-228`, `E-224` to `E-226`). Explicit production-readiness and claim limits remain, but optional external assurance does not block the owner/team release path.

## Phase 1–3 Publication Readiness Gate

- New execution checklist is recorded in `docs/execution/PHASE_1_3_PUBLICATION_READINESS.md`.
- Optional pilot template: `docs/execution/P3_EXT_001_CONTROLLED_PILOT_EVIDENCE_TEMPLATE.md`.
- Optional independent-review template: `docs/execution/P3_EXT_002_INDEPENDENT_SECURITY_REVIEW_TEMPLATE.md`.
- Optional assurance index: `docs/execution/P3_EXTERNAL_GATE_EVIDENCE_INDEX.md`.
- Controlled-pilot evidence holders now exist at `docs/execution/P3_EXT_001_PILOT_001.md` through `docs/execution/P3_EXT_001_PILOT_003.md`; `PILOT-001` to `PILOT-003` are now completed as internal bounded runs with synthetic/local scope.
`P3_EXT_002_REVIEW_REPORT.md` remains pending as an optional assurance artifact.
- Required Phase 1–3 completion may be claimed only as owner/team evidence-bounded completion; external-pilot and independent-review claims remain invalid.
- **Publication action requires a fresh exact-candidate local pass, clean worktree, owner/team approval, push, and green required GitHub checks.**
- PR #66 is merged into `main` at `5d401e70c3a0e3cf507c2c7cf635dfc99b01a9af`; no tag or release was created by this Phase 4 slice.
- `codex/consolidation-translation-core` is pushed and Draft PR #67 targets `main`. It remains unmerged; no tag, release, deployment, production mutation, or repository-setting change occurred.
- `codex/consolidation-close-lifecycle` was merged through PR #68; the current branch `codex/consolidation-journal-lifecycle` contains the remotely green grouped-matching benchmark head `0f202b4f2cfce72aafc2281daa24aa8497205c0c` with Draft PR #71 targeting `main`. No merge, tag, release, or deployment occurred.

## Task status

## P4-SCL-001 in progress: high-volume concurrent operations and backpressure

### E-257 complete: reproducible durable-job multi-worker load profile (first slice)

- `reconforge/benchmark/durable_job_load.py` drives the existing durable-job worker loop (claim/commit_partition/complete_partition) under real ThreadPoolExecutor contention on a shared SQLite database over a declared small tier (8 workers, 64 jobs, 4 partitions per job, 4 tenants = 256 declared partition effects). It reuses `SQLiteDurableJobRepository`, `DurableJobApplicationService`, and `DurableJobWorkerService` exactly as callers already use them; no new persistence primitive, domain type, repository method, or migration is introduced.
- Each worker is statically pinned to one tenant so per-tenant contention is fair (workers-per-tenant must be an exact multiple); a worker that has handled its fair share exits. The closed schema-v1 manifest carries only the structural outcome (declared shape, completed jobs, committed partition effects, duplicate count, final queue/running depth, per-tenant completions, deterministic effect-set digest, environment, explicit limitations) and excludes observed runtime/peak-memory/throughput from the manifest digest, so the digest is reproducible across runs and hardware while timing varies honestly.
- `verify_load_manifest` asserts completed jobs equal the declared count, duplicate partition effects are zero, the queue drains to zero, committed effects equal completed * partitions_per_job, per-tenant completions sum to the declared count, and limitations retain honest non-claim wording. ADR 0213 documents scope, consequences, and rollback.
- E-257 records 8/8 focused contracts and a 94-test integration matrix (durable-job domain/application/recovery, sqlite durable jobs, consolidation close, module registry, repository boundary, backup/restore, structured ingress, domain repository, generator benchmark) with zero failures. Ruff and Mypy across 381 source files, Bandit, and exact MANIFEST.in membership pass. An E-256 migration-25 regression in `test_sqlite_durable_jobs.py` (hardcoded `current_version == 24` and `applied_versions == [21,22,23,24]`) was discovered by the focused gate and corrected to the repo's `MIGRATIONS[-1].version` convention as part of the E-256 amend.
- P4-SCL-001 remains open: backpressure, soak, retry/backoff coupling, PostgreSQL load parity, and 10K/100K/1M/10M named-hardware tier publication are not implemented by these slices. SQLite serializes writes under `BEGIN IMMEDIATE`, so measured contention bounds multi-worker coordination, not database partition parallelism.

### E-258 complete: queued and running cancellation profiles

- `reconforge/benchmark/durable_job_cancellation.py` reuses the existing application/worker/repository contracts. The small declared profile cancels a queued subset before claims, proves 48/64 completion with 16 cancellations and 192 exact partition effects, then separately proves running-owner cancellation after a committed prefix with clean lease release. Duplicate effects, queue/running depth, and orphaned leases are checked structurally; timing and peak memory are observations outside the manifest digest.
- E-258 focused tests cover profile validation, queued-cancellation drain and no-duplicate effects, two-run structural digest reproducibility, running cancellation/lease release, closed manifest limitations, and distribution membership. P4-SCL-001 remains open for backpressure, soak, retry/backoff coupling, PostgreSQL load parity, distributed capacity, and named-hardware 10K/100K/1M/10M publication.

### E-313 complete: bounded PostgreSQL concurrent-load parity

- The live PostgreSQL durable-job contract now exercises two tenant lanes,
  three synthetic jobs per lane, and two partitions per job through separate
  worker connections. Every job is claimed, checkpointed, and completed via
  the existing PostgreSQL application/repository/worker boundaries.
- The gate requires six completed jobs, twelve exact partition effects, unique
  partition keys per job, and no duplicate business effect. It is a small
  synthetic runtime gate only; PostgreSQL capacity, soak, backpressure, queue
  HA, distributed scale, and production SLOs remain open.

### E-317 complete: PostgreSQL grouped-matching worker runtime parity

- `PostgresGroupedMatchingAdapter` now maps the bounded grouped strategy's
  multi-record decisions onto the existing PostgreSQL reconciliation result
  contract. Matched groups emit deterministic Cartesian source edges so every
  input is represented; unresolved groups emit explicit `Ambiguous`/`Unmatched`
  rows and review exceptions. Group totals, identities, policy, and strategy
  digests remain in replayable lineage JSON.
- Database-owned identity, amount, date, currency, and partition columns
  override any shadowing JSON attributes. Portfolio mode also materializes
  unmatched source identities rather than letting completion fail with hidden
  omissions.
- The live server-boundaries test executes the real PostgreSQL worker under a
  non-superuser RLS role and verifies one-to-many completion, two exact edges,
  one checkpoint, lineage, direct strategy digest parity, and sibling-tenant
  isolation. Local execution skips only the live section without a configured
  `RECONFORGE_TEST_POSTGRES_DSN`.
- This is one small synthetic runtime proof, not PostgreSQL 10K/100K/1M scale,
  soak, backpressure, distributed capacity, HA/DR, source-system posting, or
  live ERP/bank interoperability. The pure application service remains
  `not_applicable` in `POSTGRES_PARITY_INVENTORY.yaml`.

### E-318 complete: PostgreSQL grouped-matching crash resume

- A live server-boundaries contract now uses two synthetic entity partitions,
  injects an unhandled process-crash exception after the first committed
  checkpoint, rejects a replacement worker while the original lease is valid,
  and resumes only the remaining partition after explicit database lease
  expiry.
- The recovered run completes with two checkpoints, three unique result
  identities, execution attempt two, and no duplicate grouped edges under the
  non-superuser RLS role. This is the first live crash/resume proof for the
  grouped PostgreSQL worker; it does not create process supervision or HA/DR.
- Local execution skips only the live section without a configured
  `RECONFORGE_TEST_POSTGRES_DSN`. Remote CI on exact commit
  `77d9e0c91e70ac4fa90ca6b8bd529fcd0ae98e5f` passed server-boundaries job
  `91593993577` in run `30784006115`; the same run passed both Python jobs,
  engine parity, Docker parity, Security, and CodeQL. ADR 0269 records the
  boundary.

### E-319 complete: PostgreSQL consolidation journal-line parity

- Alembic 0057 and the PostgreSQL adapter now persist immutable,
  tenant-scoped run journal lines and posting/reversal effect lines. Each line
  stores exact minor units plus canonical decimal text; forced RLS and
  append-only database triggers protect the evidence, while reads replay the
  worksheet and compare line/effect digests.
- Pre-0057 rows remain readable through a compatibility path; the first
  governed effect transition materializes the exact verified lines. Focused
  schema, migration, registry, SQLite compatibility, Ruff, Mypy, and adapter
  tests pass locally. Implementation commit `9b9ff98d` passed CI run
  `30786172958`; the final documentation-bound head
  `040196896dd708a4f3120b10e6758a851fafc920` passed CI run `30786555699`;
  the final evidence-bound head `17170ce1bf59abbe9daf1fabafb7f5925f6573cf`
  passed CI run `30786961571`, including live `server-boundaries` job
  `91602257271`, both Python jobs, all four engine-parity jobs, and Docker
  parity `91603048107`. Security `30786961543` and CodeQL `30786961541` also
  passed.
- Boundary: this is synthetic PostgreSQL control-journal parity only. It does
  not prove statutory consolidation, acquisition/goodwill/equity-method
  accounting, live ERP/bank connectors or write-back, HA/DR, distributed
  capacity, or production readiness. ADR 0270 records the decision.

### E-320 complete: explicit consolidation translation evidence projection

- Both close adapters now expose a replay-verified `translation_evidence`
  projection derived from the canonical translation result already embedded in
  the worksheet. It binds `translation_result_digest` plus a line-level FX
  lineage digest, source currencies, selected rate IDs/types, exact pre/post
  balances, the explicit translation adjustment, and unrounded/rounded deltas.
- Local command:
  `python -m pytest tests/test_sqlite_consolidation_close.py
  tests/test_api_consolidation_close.py tests/test_postgres_consolidation_close.py
  -q -ra` -> 19 passed, 1 live PostgreSQL skip. Ruff and Mypy pass for the
  changed application/adapters.
- Boundary: additive read evidence only. No live-rate provider, statutory
  accounting treatment, ERP/bank interoperability, source-system write-back,
  HA/DR, scale, or production-readiness claim is made. ADR 0271 records the
  decision.

### E-321 complete: fail-closed mutating API authorization surface

- Application construction now validates the closed route inventory for every
  `POST`/`PUT`/`PATCH`/`DELETE` operation. Non-handshake mutations must carry an
  explicit permission-bearing (`all`/`any`) or governed `dynamic` contract;
  SCIM remains explicitly classified. Public and identity-only mutations are
  restricted to deliberate auth/WebAuthn/step-up allowlists.
- Local command: `python -m pytest tests/test_api_authorization_inventory.py
  -q -ra` -> 4 passed; Ruff and Mypy pass for the changed API files. Existing
  route inventory count/digest remains unchanged.
- Boundary: route/action coverage only. OIDC/SAML/SCIM provisioning,
  distributed cache invalidation, complete ABAC administration, and jobs/
  exports/UI enforcement remain open.
- ADR: `docs/adr/0272-api-mutating-authorization-surface-gate.md`.

### E-322 complete: PostgreSQL durable-job transient retry recovery

- The live PostgreSQL durable-job contract now injects a transient failure
  after one committed partition, asserts `retrying` with retry count one and
  lease release, then lets a recovery worker claim the job, skip the committed
  partition, finish exactly once, and retain the ordered transition reasons.
- Local command: `python -m pytest tests/test_postgres_durable_jobs.py -q -ra`
  -> 1 schema pass, 1 live skip without a configured DSN. Ruff and Mypy pass.
  The unskipped runtime gate is executed in CI server-boundaries.
- Implementation commit `60cda19e` passed CI run `30789429019`, including
  server-boundaries job `91609680294`, both Python jobs, all four engine-parity
  jobs, and Docker parity. Security `30789428995` and CodeQL `30789428992`
  also passed. The preceding fixture-only failure in run `30789002840` used
  non-hex digest literals and was corrected before this evidence.
- Boundary: small synthetic two-partition retry/recovery proof only; no
  PostgreSQL capacity, soak/SLO, distributed queue, automatic supervision,
  HA/DR, or production retry-tuning claim.
- ADR: `docs/adr/0273-postgres-durable-job-retry-runtime-gate.md`.

### E-323 complete: replayable management statement package

- `ManagementStatementPackage` groups the verified worksheet's exact reporting
  currency lines by account type, calculates section totals with Decimal/Money,
  enforces a zero package balance, and binds the result to the worksheet digest
  and canonical artifact digest. SQLite and PostgreSQL close reads expose the
  same additive `management_statement` drill-down projection.
- Local command: `python -m pytest tests/test_consolidation_statement.py
  tests/test_sqlite_consolidation_close.py tests/test_api_consolidation_close.py
  tests/test_postgres_consolidation_close.py -q -ra` -> 24 passed, 1 live
  PostgreSQL skip. Full Ruff, Mypy, and diff-check pass.
- Implementation commit `4f04c80b` passed CI run `30790446114`, including
  server-boundaries job `91612636473`, both Python jobs, all four engine-parity
  jobs, and Docker parity `91613501563`; Security `30790446103` and CodeQL
  `30790446106` also passed.
- Boundary: management statement evidence only; no statutory statements,
  acquisition/goodwill/equity-method accounting, cash-flow semantics, live
  rates, ERP/bank posting, or external assurance claim.
- ADR: `docs/adr/0274-management-statement-package.md`.

### E-324 complete: consolidation close CLI drill-down

- Added `reconforge consolidation runs`, `reconforge consolidation run`, and
  `reconforge consolidation summary`. These commands reuse the existing
  backend-neutral close service and SQLite repository, preserve workspace and
  actor scope, and expose replay-verified `management_statement` and
  `translation_evidence` in run detail.
- Local command: `python -m pytest tests/test_consolidation_cli.py -q -ra`
  -> 2 passed. The unknown-run case exits through the bounded CLI error path.
- Implementation commit `81bcaa2` passed CI run `30791340686`, including
  server-boundaries job `91615324419`, both Python jobs, all four
  engine-parity jobs, and Docker parity `91616203160`; Security
  `30791340616` and CodeQL `30791340591` also passed.
- Boundary: read-only local operator evidence only. Full lifecycle mutation,
  statutory statements, live rates, source-system write-back, PostgreSQL CLI
  parity, and UI exposure remain open.
- ADR: `docs/adr/0275-consolidation-close-cli-drilldown.md`.

### E-325 complete: acquisition fair-value/goodwill bridge

- `acquisition-fair-value-goodwill-bridge-v1` is a pure-domain Decimal/Money
  artifact for consideration, NCI fair value, identifiable net assets, and
  goodwill. It preserves policy/source digests, maker-checker attribution,
  exact balance, deterministic replay, and an explicit non-posting marker.
- Bargain purchase is fail-closed unless `allow_bargain_purchase` is true;
  goodwill and bargain purchase cannot coexist. The Finance Core registry and
  closed JSON Schema declare the new export contract.
- Local command: `python -m pytest tests/test_consolidation_acquisition.py
  tests/test_module_registry.py -q -ra` -> 16 passed. Ruff and Mypy pass for
  the changed domain/registry files.
- Corrected implementation head `408fa84` passed CI run `30792498056`,
  including server-boundaries job `91618814357`, both Python jobs, all four
  engine-parity jobs, and Docker parity `91619902895`; Security
  `30792497800` and CodeQL `30792497786` also passed.
- Boundary: no purchase-price allocation engine, tax/deferred-tax treatment,
  impairment, step acquisition/disposal, statutory classification, journal
  posting, live rate, or source write-back claim.
- ADR: `docs/adr/0276-acquisition-fair-value-goodwill-bridge.md`.

### E-326 complete: acquisition bridge CLI boundary

- Added `reconforge consolidation acquisition-bridge --input` with an optional
  exact output path. The command accepts only the declared JSON request fields,
  reconstructs canonical Money values, and invokes the pure bridge without a
  second calculation or persistence path. Unknown fields and malformed input
  fail closed.
- Local command: `python -m pytest tests/test_consolidation_acquisition.py -q -ra`
  -> 8 passed, including stdout/file replay and unknown-field rejection. Full
  Ruff, Mypy, and diff-check pass.
- Corrected head `0dcadf2` passed CI run `30794127503`, including
  server-boundaries job `91623768262`, both Python jobs, all four
  engine-parity jobs, and Docker parity `91624882551`; Security
  `30794127496` and CodeQL `30794127540` also passed.
- Boundary: local read-only artifact preparation only. No approval, posting,
  database mutation, network call, live provider, or source write-back claim.
- ADR: `docs/adr/0277-acquisition-bridge-cli-boundary.md`.

### E-327 complete: acquisition purchase-price allocation detail

- `reconforge/domain/consolidation_ppa.py` adds the closed
  `acquisition-purchase-price-allocation-v1` contract. Source-bound asset and
  liability items carry exact book/fair values, valuation references, and
  signed fair-value adjustments. Stable item IDs canonicalize equivalent input
  permutations; the artifact reconciles book net assets to fair-value net
  assets and embeds the verified goodwill/bargain bridge.
- The result is maker-checker attributed through the request digest,
  replay/tamper-verifiable, balanced, and permanently `posted: false`. The
  read-only `reconforge consolidation acquisition-ppa` CLI uses bounded
  structured ingress and rejects unknown request or item fields.
- Boundary: no tax/deferred-tax effects, impairment, statutory accounting
  judgment, ledger posting, PostgreSQL persistence/parity, provider
  interoperability, or source-system write-back.
- Local evidence: the focused PPA target passed 5/5; the combined
  consolidation/ingress/module/threat target passed 34/34; the full current
  suite collected 2,317 tests with no failures, while environment-declared
  PostgreSQL/object-storage/Redis and privilege-dependent cases remained
  skipped. Ruff, Mypy, Bandit, dependency audit, package build, and diff-check
  passed.
- Remote evidence: commit `686880b6` passed CI run `30796453610` (Python 3.11
  and 3.12, four engine-parity cells, server-boundaries, and Docker parity),
  Security run `30796453664`, Docker run `30796453577`, and CodeQL run
  `30796453692`. No release, tag, merge, or deployment occurred.
- ADR: `docs/adr/0278-acquisition-purchase-price-allocation-boundary.md`.

### E-328 complete: enterprise policy conflict analysis

- `reconforge/auth/policy_analysis.py` adds the closed
  `enterprise-policy-conflict-analysis-v1` artifact. It analyzes an approved,
  tenant-bound grant snapshot for overlapping SoD permission pairs,
  human-governed permissions on service accounts, unscoped privileged grants,
  and duplicate active grants over overlapping scopes.
- Findings are sorted deterministically, carry severity, grant/permission
  references, scope digests, bounded reasons, and stable conflict IDs. The
  request and result are maker-checker attributed and replay/tamper-verifiable;
  no policy or authorization state is mutated.
- `reconforge policy analyze-conflicts` accepts the exact JSON contract through
  bounded structured ingress. Provider federation, PostgreSQL/RLS policy
  storage, enforcement adoption, distributed cache invalidation, and complete
  route/job/export/UI coverage remain open.
- Commit `734f4b04` passed CI `30798744771`, Security `30798744778`, Docker
  `30798744776`, and CodeQL `30798744767`; the PR remains draft and no merge,
  release, or deployment occurred.
- ADR: `docs/adr/0279-enterprise-policy-conflict-analysis.md`.

### E-329 in progress: PostgreSQL policy snapshot analysis boundary

- `reconforge/application/policy_analysis.py` now provides a backend-neutral
  `PolicyAnalysisApplicationService`; `reconforge/infrastructure/postgres_policy_analysis.py`
  loads active tenant-RLS user-role permissions and enabled service-account
  permissions into the existing deterministic analyzer.
- `POST /api/v1/admin/access/policy-analysis` is additive, read-only, and
  requires human-only `security.policy.manage`, an independent approver, and
  an explicit prior approval timestamp. It never mutates roles, sessions, or
  policy state.
- Local contract/API/parity tests pass, and the full local regression collected
  2,326 tests with zero failures/errors. CI server-boundaries run `30803066835`
  passed the live PostgreSQL test under the non-privileged role; the parity
  inventory now records this bounded adapter as `live_verified_current`.
- ADR: `docs/adr/0280-postgres-policy-snapshot-analysis.md`.

### E-330 in progress: PostgreSQL persisted policy permission scopes

- Alembic `0058_pg_policy_permission_scopes` adds a forced-RLS,
  append-only scope table binding role permissions to bounded workspace,
  entity, period, region, or data-classification dimensions.
- The policy snapshot adapter now groups active permissions by identical
  persisted scope and preserves an explicit tenant-wide wildcard when no
  scope row exists. The analyzer remains read-only; universal route/job/export
  enforcement is not inferred.
- Local contract tests pass. CI server-boundaries run `30805942878` passed
  migration, RLS, bounded scope projection, tamper/delete refusal, and valid
  revocation under the non-privileged role; parity is now
  `live_verified_current` for this bounded adapter.
- The full local regression at the slice head collected 2,328 tests with zero
  failures/errors; external-service and host-capability skips remain explicit.
- ADR: `docs/adr/0281-postgres-policy-permission-scopes.md`.

### E-331 in progress: PostgreSQL persisted policy amount bounds

- Alembic `0059_pg_policy_amt_bounds` extends the immutable scope table with
  exact finite PostgreSQL `NUMERIC` minimum/maximum bounds. The migration
  widens the active-scope uniqueness key, rejects reversed/non-finite or
  unbounded-only rows, and restores the 0058 trigger/index on safe downgrade;
  downgrade refuses while amount evidence exists.
- `PolicyScope` serializes optional bounds canonically as exact Decimal text,
  keeps old v1 payloads/digests unchanged when bounds are absent, and treats
  inclusive bounded intervals as overlapping only when their ranges intersect.
  The PostgreSQL snapshot adapter validates and projects the values without
  mutating policy state.
- Focused tests, Ruff, Mypy, diff-check, and the full local regression (2,330
  collected, zero failures/errors; declared capability skips remain) pass.
  CI run `30808822315` also passes the migration, RLS, exact amount projection,
  amount-tamper refusal, valid revocation, Python 3.11/3.12, engine parity,
  Docker parity, Security, and CodeQL gates.
- The bound has no implicit currency and is not universal route/job/export/UI
  enforcement; provider federation, distributed invalidation, and production
  effectiveness remain open.
- ADR: `docs/adr/0282-postgres-policy-scope-amount-bounds.md`.

### E-332 complete: PostgreSQL persisted non-posting acquisition PPA evidence

- Added the backend-neutral `AcquisitionPpaApplicationService` and the
  tenant-scoped `PostgresConsolidationPpaRepository` behind Alembic
  `0060_pg_consolidation_ppa`. The adapter stores canonical request/result
  JSONB, exact request/result digests, maker-checker attribution, and a
  permanently `posted: false` marker.
- Persistence recomputes and verifies the PPA result before insert, derives a
  deterministic tenant-bound artifact ID, makes identical retries idempotent,
  emits an audit event, and replay-verifies reads. PostgreSQL forced RLS plus
  trigger-enforced append-only rows prevent sibling-tenant reads and direct
  update/delete tampering.
- Local focused/full contracts, Ruff, Mypy, Bandit, package build, and
  diff-check pass. CI run `30811914832` passes Python 3.11/3.12, engine parity,
  Docker parity, Security, CodeQL, migration `0060`, and the unskipped
  PostgreSQL runtime gate; parity is now `live_verified_current` for this
  bounded adapter.
- Boundary: evidence storage only. No statutory acquisition accounting,
  tax/deferred-tax, impairment, journal posting, live rates, ERP/bank
  connector, source write-back, restore, HA/DR, or production-readiness claim.
- ADR: `docs/adr/0283-postgres-consolidation-ppa-evidence-is-non-posting.md`.

## P4-MAT-001 in progress: optimization-grade advanced matching portfolio

### E-260 complete: bounded grouped and netting matcher

- Existing `reconforge/domain/grouped_matching.py` and `reconforge/application/grouped_matching.py` provide the persistence-independent exact matcher for one-to-many, many-to-one, and true many-to-many/netting groups. Records carry exact Decimal amounts, currency/partition identity, non-negative fees, date windows, and explicit sourced FX conversion through the application boundary.
- Candidate subsets are bounded by declared cardinality and evaluation budgets. Minimum difference, cardinality, date span, and stable record identities define the deterministic tie-break. Equal optima and exhausted budgets return explicit `ambiguous` decisions; partition and identity violations fail closed.
- E-260 adds five domain contracts to the existing 12 application contracts (17/17 focused tests), covering true many-to-many, permutation-stable digest, netting, budget ambiguity, and duplicate/partition boundaries. ADR 0215 and package membership are included.
- E-261 adds explicit `partial-settlement` mode to the grouped domain/application/strategy contract. Exact candidates win first; bounded positive partial groups settle the smaller net total and expose `settled_amount`, `left_residual`, and `right_residual` in the decision and digest. The runtime manifest, Reconciliation-as-Code model, JSON schema, and published strategy document agree on the new mode. Focused domain/application/strategy/rule tests pass under ADR 0216; no posting or write-back occurs.
- E-262 adds `portfolio` mode without changing the single-group compatibility API. It selects a bounded maximum-cover set of non-overlapping exact groups, minimizes aggregate difference, exposes unmatched IDs, and returns explicit ambiguity on equal portfolios or generation/selection budget exhaustion. Application, runtime manifest, Reconciliation-as-Code, schema, published strategy document, and focused contracts are aligned under ADR 0217.
- E-263 adds the bounded FIFO carry-forward/sequence-window strategy. It allocates oldest eligible obligations within one currency/partition and date window, preserves Decimal residuals, is permutation-stable, and returns explicit ambiguity when ceilings are exhausted. No posting or write-back occurs.
- E-264 adds bounded reversal pairing. Opposite-sign records are paired within a currency/partition/date window, explicit `reversal_of` links outrank inferred candidates, one-to-one consumption is enforced, and ambiguity/unmatched outcomes remain visible. No journal mutation or posting occurs.
- E-265 adds explicit partial groups inside portfolio selection. Existing exact-only portfolio behavior is unchanged unless `allow_partial_settlement` is true; selected partial decisions carry settled amount and residuals, and the policy flag is digest-bound. No posting or write-back occurs.
- P4-MAT-001 remains open for broader crash-resume/failure injection,
  cross-engine properties, PostgreSQL scale, soak, and domain-diverse
  workloads. E-318 is one bounded live recovery path, not a general reliability
  or capacity claim.
- E-317 closes only the worker-runtime portion of the PostgreSQL boundary; the
  workstream remains open for broader cross-engine properties, PostgreSQL scale,
  soak, and domain-diverse workloads.

### E-355 complete: domain-diverse grouped-matching 10K profile

- Added `grouped-matching/10k-domain-diverse-v1` with 2,500 partitions and
  exactly 10,000 synthetic records cycling one-to-many, many-to-one, true
  many-to-many, fee-aware portfolio netting, FX-aware many-to-many, and
  partial-settlement portfolio cases. Every partition runs through the public
  strategy adapter and the application service.
- The published artifact records 2,084 matched partitions, 416 deliberate
  ambiguity outcomes for equal partial portfolios, zero unmatched partitions,
  zero adapter mismatches, zero permutation mismatches, decision digest
  `89e6a9f354f2501cf7fe1f2b5b804ddb7666e0dffdbd55671acd2e1c4ca00d86`, and
  manifest digest `9f4ab153c9733dc54bf2183fa92654a56fa8ce1a831547952d261ad4ab10d77d`.
  The observed Windows 11/Python 3.14.6 run was 6.8093s and 1.5709 MiB peak
  traced memory; timing is observational.
- Boundary: one host/process synthetic algorithm evidence. Carry-forward,
  sequence/window, reversal, PostgreSQL runtime parity, soak, distributed
  capacity, provider I/O, posting, and production sizing remain open.
- ADR: `docs/adr/0305-grouped-matching-domain-diverse-scale.md`.
- Repository gates after the slice: 2,401 tests collected and the suite exited
  0 (repository-declared skips); Ruff, Mypy, Bandit, package build, lock
  consistency, and diff checks passed.
- Hosted CI for commit `04a6c316` is green: CI run `30876285705`, Docker
  `30876285712`, Security `30876285779`, and CodeQL `30876285690`. The
  engine-parity mirror's 403 fallback was an annotation only; its jobs passed.

### E-356 complete: PostgreSQL durable-job 10K-effect tier

- Added `postgres-durable-job-load/10k-effects-v1`: 16 worker connections,
  2,500 jobs, four partitions per job, four tenant lanes, and 10,000 declared
  effects. The local PostgreSQL 16 run completed 2,500/2,500 jobs and
  10,000/10,000 effects with zero duplicates, zero queue/running residue, and
  625 completions per lane.
- Observed Windows 11/Python 3.14.6 runtime was 30.4805s at 82.0197 jobs/s.
  Effect digest: `62b8f8ea4b19b9644b4fd356db3fc6d96d5922ebfcfe1a4a5aa4aba035e83c2f`;
  manifest digest: `995184fd3d9bbbb1a8d8f54f619af700673a71e031a35b9c0f609a5cc741b512`.
- Boundary: one-host synthetic PostgreSQL correctness/concurrency evidence;
  soak, backpressure coupling, queue HA, automatic failover, host loss,
  cross-host fairness, RPO/RTO, and production sizing remain open.
- ADR: `docs/adr/0306-postgres-durable-job-10k-scale.md`.
- Repository gates after the slice: 2,404 tests collected and the suite exited
  0 (repository-declared skips); Ruff, Mypy, Bandit, package build, lock
  consistency, and diff checks passed.
- Hosted CI for commit `8fee1bb9` is green: CI `30878667892` with
  server-boundaries job `91895157424`, Docker `30878667913`, Security
  `30878667888`, and CodeQL `30878667878`; Python 3.11/3.12 and engine parity
  jobs also passed. The uv mirror 403 was an annotation-only fallback.

### E-357 complete: PostgreSQL durable-job lock-order remediation

- The hosted documentation rerun exposed an intermittent deadlock in the
  existing two-worker PostgreSQL contention contract. The cycle was caused by
  claim taking `durable_jobs` then `durable_job_leases`, while owned
  transitions took the inverse order.
- Owned-transition paths now take the durable-job row lock before the lease
  lock. Local repeated live evidence is 10/10 contention passes, plus a full
  local 10K profile pass with 2,500 jobs and 10,000 effects and no duplicate or
  residual work.
- ADR: `docs/adr/0307-postgres-durable-job-lock-order.md`.
- Hosted CI for commit `a131fe32` is green: CI `30880528118`,
  server-boundaries `91900726859`, Docker `30880528103`, Security
  `30880528153`, and CodeQL `30880528101`; Python 3.11/3.12, object-storage,
  docker-parity, and all engine-parity cells also passed.

## P4-CON-001 in progress: governed live connector foundation

- E-266 adds the synthetic provider-neutral `reference-rest-readonly` connector. It validates a closed JSON record page with exact Decimal text, unique identities, bounded cursor, canonical response digest, and the existing SSRF/TLS/secret/rate/retry/idempotency boundary. No real provider, credential, customer data, or write-back is included.
- E-267 adds the fail-closed provider-neutral write-back intent lifecycle. It requires an explicit feature flag, connector/operation allowlist, distinct human step-up/MFA approval, one-way dispatch, acknowledgement binding, and separate compensation idempotency. It performs no network I/O and does not claim a live provider or write capability.
- E-268 adds the synthetic transport-injected `reference-sftp-readonly` connector. It enforces exact SFTP egress, traversal-free roots, bounded files, extension allowlists, deterministic cursor ordering, credential isolation, and content digests without bundling SSH or making network calls.
- E-269 adds the synthetic transport-injected `reference-object-storage-readonly` connector. It enforces exact HTTPS egress, tenant scope, traversal-free prefixes, bounded objects, deterministic cursors, SHA-256 verification, and metadata scope without changing the existing object-store protocol or calling a cloud provider.
- E-270 adds the synthetic transport-injected `reference-database-readonly` connector. It exposes only two named query profiles, enforces tenant scope and exact Decimal rows, rejects arbitrary SQL by schema, and bounds rows/cells/cursors without opening a database connection.
- P4-CON-001 remains open for named ERP/bank/SFTP/database/object-store providers, provider sandboxes, provider-specific compensation semantics, signed executable packages, and production deployment evidence. The local/server request and provider-neutral transport boundaries are now separately evidenced.

### E-314 complete: reusable connector retry failure-injection gate

- `verify_network_retry_failure_injection` now exercises a caller-supplied
  network executor against a synthetic response sequence. It validates only
  retryable HTTP statuses, requires one bounded success attempt, checks the
  executor attempt count, and rejects transient-body leakage.
- Focused connector tests pass for successful recovery, invalid statuses, and
  retry-ceiling refusal. The helper is provider-neutral and performs no network
  I/O; live vendor interoperability and deployment evidence remain open.

### E-315 complete: posted consolidation-run certification

- The SQLite consolidation repository now binds certification metadata to a
  replay-verified run and rejects certification before `Posted` or `Reversed`.
  Preparation requires consolidation-management and approval-submit
  permissions; review requires consolidation-validation and approval-approve.
- Maker-checker separation is enforced by the existing certification guard, and
  read access replay-validates the underlying run before returning metadata.
- Authenticated API routes expose prepare, review, and read operations under
  `/api/v1/consolidation-close/runs/{run_id}/certification`. This remains local
  workflow metadata, not a legal signature, audit opinion, or compliance claim.

### E-316 complete: PostgreSQL consolidation certification parity

- `PostgresConsolidationCloseRepository` now exposes the same certification
  port as SQLite. Preparation and review lock and replay-verify the tenant
  run, permit only `Posted`/`Reversed`, and use the existing RLS-scoped
  `certification_records` repository for immutable maker-checker metadata.
- The live PostgreSQL contract grants the application role only the required
  certification table access and exercises prepare, self-review refusal,
  independent review, and replay-validated read. Local execution skips the
  live section when no PostgreSQL DSN is configured.
- This closes backend parity for workflow metadata only; PostgreSQL API
  exposure, statutory consolidation, legal signatures, and production claims
  remain outside the slice.

## P4-FIN-002 in progress: governed consolidation close lifecycle

### E-256 complete: local SQLite consolidation close lifecycle (control-journal foundation)

- Migration 25 adds a local SQLite consolidation close lifecycle for verified worksheet v1 artifacts only. The governed state machine is `Prepared -> Approved -> Posted -> ReversalPrepared -> Reversed`; each transition uses optimistic row versions and actor/reason/timestamp evidence. Preparation persists a bounded worksheet payload, its result digest, and exact balanced journal lines derived from approved zero-sum eliminations; both the writer and reader replay the worksheet before public use.
- Approval requires an actor independent of preparation; posting requires an actor independent of both preparation and approval; reversal approval requires an actor independent of reversal request and posting. `Posted` means an immutable balanced effect in ReconForge's local consolidation control journal only; it does not create Finance Core entries, statutory books, source-ERP postings, payments, tax effects, or statements. Reversal creates a second committed effect whose lines exactly negate the posting effect; the original is never edited or deleted.
- Period locks require an open/reopened state at the expected optimistic version and emit an immutable period event; reopen requires an actor independent of the locker and emits another event; re-lock after reopen records another event rather than overwriting the history. Locked periods block new runs and lifecycle changes until an independent reopen. Database triggers enforce immutable run lines/effects/effect lines, governed effect transitions, balanced committed effects, and self-approval refusal at the storage level.
- Local backup includes every consolidation lifecycle table; restore replays run transitions, effects, and period events through the installed schema triggers, verifies worksheet and effect integrity before replacing the target, and rejects rehashed or tampered payloads. The bounded `consolidation-worksheet-json-v1` profile rejects fractional JSON numbers and oversized values; module registry, repository boundary, backup table set, and structured-ingress inventories are updated; ADR 0212 and operator docs are added.
- E-256 records 8/8 focused contracts and a 43-test integration matrix (migration/registry/repo-boundary/backup/structured-ingress/domain-repository) with zero failures. Ruff and Mypy across 380 source files, Bandit, pip-audit, wheel/sdist build, and exact sdist membership (five new slice files) pass. P4-FIN-002 remains open: persisted ownership masters, acquisition/fair-value/goodwill/equity-method policy, ownership-change accounting, statutory statements, PostgreSQL parity, API/CLI/UI exposure, live rates, source-ERP/bank integration, and write-back are not implemented by this slice.

## P4-FIN-001 completed: deterministic consolidation translation artifact

- The first Phase 4 slice accepts at least two exactly balanced entity trial balances, one functional currency and source digest per entity, explicit source-to-group account mapping, and an explicit closing/average/historical rate type per mapped balance.
- Foreign-currency rates require one exact period/base/reporting/type/bucket key plus ID, source, source digest, positive Decimal value, and timezone-aware effective time. Buckets permit distinct historical layers in the same currency without arbitrary rate selection. Missing, duplicate, unused, mismatched, binary-float, excess-precision, mixed-currency, and unbalanced inputs fail closed.
- Currency-specific Money policy, unrounded values, line and total rounding deltas, pre-adjustment balance, and an operator-policy-named CTA proposal are retained. The proposal is always unposted and creates no ledger, elimination, approval, close, ERP, or bank effect.
- Canonical sorting makes request/result identity invariant to row and rate order. The closed schema-v1 artifact is replayed from declared inputs, so rehashing altered financial output is insufficient. The existing local object store provides immutable idempotent tenant/workspace retention and scope isolation.
- E-252 records 47/47 focused contracts and a fresh 2,104-test full run with zero failures/errors and 64 declared skips. Ruff, Mypy across 377 source files, Bandit, pip-audit, wheel/sdist build and membership, supply-chain validation, checksum-pinned Gitleaks history/tree scans, npm audit, TypeScript, 55/55 Vitest, web build, and 11-pass/5-live-only-skip Playwright gates pass. E-253 records Draft PR #67; its exact final head reports 15/15 successful checks and GitHub `CLEAN`/`MERGEABLE` state.
- `P4-FIN-002` is the next financial slice. Ownership/effective dates, eliminations, NCI, governed posting/reversal, maker-checker, locks/reopens, statements, SQLite/PostgreSQL lifecycle parity, live rates, and write-back are explicitly not delivered by P4-FIN-001.

## P3-ENT-007 completed at evidence-bounded Connector SDK scope

- `connector-manifest-v1` and `network-connector-registration-v1` are strict read-only data contracts. The built-in registry is static; generic CSV is local-file and SAP/Odoo are export profiles, never live connector claims.
- Bounded JSON packages authenticate manifest data with Ed25519 against a versioned active/revoked publisher-key registry and reject tampering, executable entry points, binary/oversized content, duplicate trust, and revoked keys. No external code is installed or executed.
- The synthetic network runtime enforces exact HTTPS egress, public-only DNS answers, IP-pinned hostname-verified TLS, no redirects, default-disabled secret references, bounded cursors/idempotency keys/responses/retries/timeouts, process-local rate control, and formal deterministic replay.
- Connector pages use the existing immutable object store and generation-fenced durable jobs. Connection-close/reclaim resumes from the committed cursor, skips the first effect, and yields the same two semantic effects and output digest as uninterrupted execution. An uncertain identical object write is re-read and verified before commit.
- The machine-checked E-209 audit verifies twelve gates and fifteen hostile paths. Its final governance/connector target passes 57/57; the locked current-tree snapshot passes 1,915 tests with 62 declared external-capability skips in 263.19 seconds. No live provider, production secret/vault, distributed quota, executable third-party package, write-back, external security review, or Enterprise-readiness claim is made. No publication action occurred.
- P3-ENT-008 (signed control and industry pack lifecycle) is the next internal Phase 3 slice; external pilots and independent security review remain separate external gates.

## P3-ENT-006 completed at evidence-bounded administration scope

- The exit audit is now `verified`: all fourteen declared gates have current file and runtime evidence across same-origin browser sessions, host-bounded HTTPS, audit verification, Security Center, identity/session lifecycle, access policy, integration/retention governance, PostgreSQL authorization, localization, disclosure rejection, and automated accessibility after the full privileged workflow.
- A dedicated audit regression rejects missing evidence, non-verified gates, publication activity, absent authority/disclosure/retention hostile paths, or removal of the external TLS, screen-reader, security-assurance, HA/DR, and Enterprise-readiness limitations. Completion means the documented P3-ENT-006 product boundary only; it is not an external certification or production approval.
- P3-ENT-007 (Connector SDK and conformance suite) is the next Phase 3 slice. Plans 1-3 remain active and no publication action occurred.

## E-207 complete: host-bounded same-origin HTTPS foundation

- `reconforge api serve` can now serve a built Studio after the API routes so `/admin-audit`, assets, and `/api/v1/*` share one origin. Enabling the web root requires exact hostname allowlisting; wildcards, schemes, paths, and ambiguous DNS names are rejected. Direct TLS requires certificate and key together, while reviewed upstream TLS termination is an explicit separate mode. API-only Community behavior remains unchanged.
- The response boundary adds a closed CSP and emits HSTS only for a declared secure transport. Unknown asset-like paths remain 404 rather than executable HTML; extensionless GET/HEAD paths support SPA routing. ADR 0200 and the operator runbook define proxy trust, secret handling, verification, limitations, and rollback.
- A real localhost Uvicorn TLS test with a short-lived synthetic certificate passed hostname validation, TLS 1.2/1.3 negotiation, same-origin SPA/API responses, HSTS/CSP, hostile Host rejection, and clean shutdown. Sixteen focused hosting/cookie/CSRF tests pass. An opt-in Chromium run then loaded the actual production Vite bundle from that HTTPS origin, observed zero `securitypolicyviolation` events, confirmed external-only scripts/styles, and fetched API health from the identical origin. The locked full snapshot passes 1,879 tests with 62 declared external skips; a later documentation/package-membership test and the credential-variable cleanup pass focused regression. Wheel/sdist build and exact archive membership pass. This does not prove an external reverse proxy, public certificate lifecycle, assistive-technology interoperability, or internet-facing hardening. No publication action occurred.

## E-206 complete: browser integration and evidence-retention governance

- The administration UI now exposes the existing native integration-disable and retention-policy lifecycle. It requires current human step-up, the cookie-bound CSRF proof, `security.policy.manage`, typed confirmation, and the server's state digest or lifecycle/retention version. It creates no shadow connector registry and never exposes destinations, secrets, credential material, or stored evidence references.
- Retention policy creation, exact metadata update, retirement, reactivation, and application to a transient operator-supplied evidence identifier are supported. The identifier is cleared after success or cancellation. PostgreSQL remains authoritative for tenant scope, audit atomicity, optimistic conflict handling, idempotent assignments, and preservation of the longest existing retention floor.
- TypeScript, 55 Vitest tests, production build, the full Chromium suite, and the focused mocked mutation lifecycle pass. A fresh PostgreSQL 17.10 database migrated 0001-to-0053 and the 4/4 current security-governance target passed under a non-superuser/NOBYPASSRLS role. The initial attempt on an older ambient schema failed due to catalog drift and is not counted. P3-ENT-006 remains open for deployed TLS/CSP and broader accessibility/exit evidence. No publication action occurred.

## E-205 complete: governed browser role and assignment lifecycle

- The administration UI now exposes the complete existing access-policy lifecycle: create a named role with an exact permission set, replace that set, replace one non-current user's exact roles, retire a role, and reactivate it. Every operation retains `roles.manage`, current step-up, session-bound CSRF, typed confirmation, and optimistic lifecycle state where applicable. Retired roles remain visible through the explicit `include_retired=true` read so reactivation is possible without a shadow record.
- Browser contracts accept only the exact role-change and user-assignment responses. The UI never renders role/user identifiers, state digests, audit-event IDs, credentials, email, raw IP, or user-agent values. It reloads permissions, roles, users, and sessions after every change. Permission, assignment, and retirement effects revoke impacted sessions; reactivation restores neither assignments nor sessions. Current-operator assignment is deliberately absent, while server last-manager enforcement remains authoritative.
- TypeScript and 54 Vitest tests pass, and the mocked Chromium flow covers all five writes plus exact-set behavior and disclosure rejection. A fresh PostgreSQL 17.10/Chromium flow passed create, permission replacement, exact target assignment, retirement, and reactivation. Final database state: role active at lifecycle 4 with `audit.read` and `audit.verify`, zero active target assignments, zero active/one revoked target session, and five corresponding audit events. The first live attempt correctly showed that leaving `observer` selected preserves it under exact replacement; the corrected rerun explicitly removed it and passed. No publication action occurred.

## E-204 complete: browser user disable and enable lifecycle

- An operator with `users.manage` and current privileged assurance can now disable or enable one non-current identity from the administration UI. The browser requires the exact `DISABLE` or `ENABLE` confirmation and submits the server lifecycle version with its session-bound CSRF proof. The current operator has no disable control; the server remains authoritative for self-disable, stale-version, and last-active-administrator rejection.
- The client accepts only the exact user-status response and never renders its user ID, lifecycle/state digest, audit-event ID, email, credential, IP, or user-agent material. A successful disable replaces only the returned user, reports the server's revoked-session count, and reloads the authoritative session snapshot. Re-enable restores sign-in eligibility but does not fabricate or resurrect revoked sessions.
- TypeScript, 53 Vitest tests, production build, and the mocked Chromium administration flow pass. A fresh explicitly opt-in localhost Chromium path through the same-origin Vite proxy and PostgreSQL 17.10 passed disable then enable for one synthetic observer. Direct database evidence shows final `disabled=false`, lifecycle version 3, zero active and one revoked target session, plus exactly one `identity.user.disabled` and one `identity.user.enabled` audit action. This is synthetic localhost evidence, not deployed TLS/CSP, role/policy, integration, retention, assistive-technology certification, or Enterprise readiness. No publication action occurred.

## E-203 complete: browser session revocation is the first bounded administration mutation

- After the existing same-origin sign-in and privileged step-up, an operator holding `users.manage` can revoke exactly one active session. The UI requires one closed reason code and the literal `REVOKE` confirmation before it sends the server's required lifecycle version and session-bound CSRF proof. It exposes no user/session identifier, state digest, raw IP, user-agent value, credential, or audit-event identifier.
- The browser accepts only the exact four-field revocation response and rejects expanded session disclosure before it can render. A returned stale lifecycle conflict is presented as a reload-and-review instruction; a non-current revocation replaces only that response's row. Revocation of the current browser session explicitly returns the view to sign-in and does not preserve privileged state.
- Final scoped gates pass: TypeScript; 52 Vitest tests across eight files; production Vite build; mocked Chromium confirmation/CSRF/no-audit-ID path; and an explicitly opt-in Chromium flow through a same-origin Vite proxy to synthetic PostgreSQL 17.10. The latter verifies current-session sign-out following real API authorization and audit-backed revocation. This is synthetic localhost evidence, not deployed TLS/CSP, user-disable, role/policy, integration, retention, assistive-technology certification, or Enterprise readiness. P3-ENT-006 remains in progress. No publication action occurred.

## E-202 in progress: P3-ENT-006 exit audit

- `docs/execution/P3_ENT_006_EXIT_AUDIT.yaml` now enumerates the browser-session, audit, security, identity/session, access, and integration/retention view evidence. The scoped local gates pass: TypeScript, 52 Vitest tests, production build, and Chromium regression including the declared Arabic/English Axe paths. Browser session revocation is now separately evidenced; other administration mutations remain absent. Each secondary authorization snapshot fails independently.
- A fresh disposable PostgreSQL 17.10 database migrated through head `0053` and the focused server/API matrix passes 13/13 under a synthetic non-superuser, non-BYPASSRLS application role. The matrix covers the current security, identity, access, governance, and server-identity boundaries. Its guarded non-empty downgrade assertion now preserves the pre-attempt Alembic head, avoiding a stale revision expectation as new migrations are added.
- An opt-in localhost Chromium test now verifies the actual same-origin browser cookie transport through an explicit Vite proxy and synthetic PostgreSQL 17.10 identity. It proves cookie-bound CSRF step-up plus real redacted audit, Security Center, identity/session, access-policy, integration, retention, and `/auth/me` reads with no browser bearer. The test exposed and repaired a server-profile bug where cookie principals were not bound by middleware for synchronous routes; the new focused regression preserves CSRF denial and principal propagation. This is synthetic localhost evidence only, not deployment-TLS evidence. The temporary API server and container are stopped; synthetic SQLite test files remain under `.codex-test-tmp/` because the environment blocked deletion.
- The audit deliberately remains `in_progress`: most standard E2E fixture calls are mocked and there is no current evidence of an actual deployed same-origin host, full assistive-technology validation, or reviewed user/access/governance mutation workflows. These gaps are recorded as unverified rather than silently promoted to an Enterprise or security claim. No publication action occurred.

## E-201 complete: read-only integration and retention snapshot in authenticated administration UI

- After the existing same-origin sign-in and privileged step-up, the administration view independently requests `security.policy.manage` integration and retention-policy lists. Closed browser contracts reject secret references, evidence IDs, and any other response expansion before rendering. The UI shows only integration kind/status and credential counts plus retention-policy name/description/classification/duration/state; it never displays destinations, secrets, scope/state digests, evidence references, or identifiers.
- This governance snapshot is isolated from audit, Security Center, identity, and access-policy reads. A denial cannot replace, hide, or synthesize another view. It is deliberately read-only: integration disable, retention-policy creation/update/retirement, and evidence retention application remain absent pending their own confirmation, reason, conflict, audit, and retention-floor UX proof.
- Final web gates pass: TypeScript typecheck; Vitest 51/51 across eight files; Vite production build; and Playwright 11/11 Chromium paths, including mocked sign-in/step-up/integration-retention rendering, redaction, RTL, and automated Axe coverage. This is local mocked-browser evidence, not live PostgreSQL authorization, provider disable/retention propagation, deployed security-header proof, accessibility certification, or Enterprise readiness. P3-ENT-006 remains in progress. No publication action occurred.

## E-200 complete: read-only access-policy snapshot in authenticated administration UI

- The existing administration session now independently requests `roles.manage`-governed role and permission lists after step-up. The browser validates exact permission and paginated role responses before rendering; expanded policy or identity fields are rejected. The UI reveals only role/permission names, descriptions, active-user/role counts, lifecycle state, and declared role permissions. It shows neither state digests, internal identifiers, credentials, emails, nor policy mutation controls.
- Access-policy authorization is isolated from audit, Security Center, and identity reads. A denied/unavailable access snapshot cannot erase separately authorized information or produce synthetic data. Creation, retirement/reactivation, permission replacement, and user-role assignment remain deliberately absent pending their own confirmation, optimistic-conflict, session-revocation, and audit-evidence UX proof.
- Final web gates pass: TypeScript typecheck; Vitest 50/50 across eight files; Vite production build; and Playwright 11/11 Chromium paths, including mocked sign-in, step-up, identity, access-policy, redaction, RTL, and automated Axe coverage. This is local mocked-browser evidence, not a live PostgreSQL authorization proof, deployed security-header proof, accessibility certification, complete lifecycle UI, or Enterprise readiness. P3-ENT-006 remains in progress. No publication action occurred.

## E-199 complete: read-only identity and session snapshot in authenticated administration UI

- The existing `/admin-audit` session now independently requests `users.manage`-governed user and session lists after privileged step-up. Its closed browser contracts reject response expansion, including email and raw client-IP fields, before rendering. The view shows only the server-approved username/display name, role names, active-session count, lifecycle status, and session status/timestamps; it does not render IDs, state digests, credentials, email addresses, IP addresses, user-agent values, or any synthetic identity record.
- Identity/session authorization is deliberately isolated from audit and Security Center authorization. If either identity read fails or is denied, the page retains the separately authorized audit and Security Center views and reports the unavailable snapshot; no broader data is substituted. This slice is read-only: no user disable/enable, session revocation, role mutation, or assignment is exposed in the browser.
- Final web gates pass: TypeScript typecheck; Vitest 49/49 across eight files; Vite production build; and Playwright 11/11 Chromium paths. The mocked browser flow proves sign-in, step-up, security snapshot, identity/session rendering, raw-IP non-disclosure, and RTL/Axe coverage. It is not evidence of deployed same-origin hosting, a live PostgreSQL authorization exercise, accessibility certification, complete administration lifecycle controls, or Enterprise readiness. P3-ENT-006 remains in progress. No publication action occurred.

## E-198 complete: closed-contract Security Center snapshot in the authenticated administration UI

- After the existing same-origin sign-in and privileged step-up, `/admin-audit` independently requests the read-only `security.center.read` snapshot without sharing or persisting a bearer credential. The Security Center request is deliberately non-blocking: an unavailable or unauthorized snapshot leaves the independently authorized audit browse and verification view usable, and the UI reports that separation rather than inventing a fallback.
- The browser contract accepts exactly the declared root, section, and attention-item fields; it checks both SHA-256 digests and the audit-chain boundary literal, rejecting added fields before rendering. The UI exposes only selected count fields, attention code/severity/count, and the server timestamp. It explicitly labels both an attention result and an observed-no-attention result as a count-only operational snapshot, not a security assurance or certification.
- Final web gates pass: TypeScript typecheck; Vitest 48/48 across eight files; Vite production build; and Playwright 11/11 Chromium paths, including existing English/Arabic automated Axe coverage and the mocked same-origin login/step-up/security contract flow. This is local browser regression evidence, not deployed same-origin/CSP proof, accessibility certification, a complete administration UI, or Enterprise readiness. P3-ENT-006 remains in progress for identity, policy, session, integration, retention views, disclosure consolidation, and the exit audit. No publication action occurred.

## E-197 complete: accessible same-origin redacted audit administration UI

- Studio now exposes `/admin-audit` in Arabic and English. The view begins with tenant-scoped browser sign-in, retains only the returned CSRF proof in component memory, requires the existing privileged step-up before any audit read, and uses only the closed redacted browse/verification responses. It has no bearer token field, local-storage token, URL token, synthetic fallback, or client-created audit data.
- The UI renders only source, event identity, sequence/time, action/object type, shortened event hash, and source-specific verification counts/status. Its contract validator rejects expanded event objects, including a hostile `actor_label`; it never renders raw actor/object/reason/request/metadata fields.
- Final web gates pass: TypeScript typecheck; Vitest 47/47 across eight files; Vite production build; and Playwright 11/11 Chromium paths. The E2E contract covers sign-in, step-up, redacted event rendering, password non-disclosure, and Arabic RTL; automated Axe scans now include `/admin-audit` in both declared language directions. This is browser regression evidence, not a complete accessibility certification, deployed reverse-proxy proof, or Enterprise readiness. P3-ENT-006 remains in progress for the remaining administration views, disclosure consolidation, and exit audit. No publication action occurred.

## E-196 complete: same-origin browser administration session boundary

- `POST /api/v1/auth/browser/login` now creates the existing server/local session without serializing its bearer credential. It sets only a host-only `__Host-reconforge_session` cookie with `HttpOnly`, `Secure`, `Path=/`, and `SameSite=Strict`, and returns a bounded session-bound CSRF proof plus expiry. Existing bearer login remains compatible.
- Authentication accepts the explicit Bearer header or the browser cookie. Unsafe requests using the cookie must supply the exact `X-ReconForge-CSRF` proof; the proof is HMAC-bound to that session and fails under another session. Explicit Bearer retains precedence and compatibility behavior. Browser logout revokes its session and clears only its cookie.
- Focused local/browser/API/authorization tests pass, including no-token serialization, cookie attributes, cookie-authenticated `GET /api/v1/admin/audit/events` under the PostgreSQL profile, missing/malformed CSRF denial, cross-session CSRF replay denial, invalid-login non-disclosure, bearer compatibility, and the closed authorization inventory. The final regression records 1,935 tests with zero failures/errors and 62 declared external-capability skips in 291.534 seconds. This is a server transport boundary, not a deployed browser login/step-up UI, CSP/reverse-proxy proof, full accessibility claim, or Enterprise readiness. P3-ENT-006 remains in progress.

## E-195 complete: administration UI readiness audit

- The existing Studio browser shell passes its declared local gates: TypeScript typecheck, 42 component tests, production build, and ten Chromium E2E tests covering the declared English/Arabic routes, Axe scans, keyboard focus, user accessibility preferences, mobile landmarks, and source-path redaction. This is scoped automated regression evidence, not a WCAG certification or assistive-technology interoperability claim.
- The audit explicitly found no browser authentication/session acquisition or privileged step-up contract for the PostgreSQL-only administration APIs. Their bearer/step-up boundary cannot safely be supplied by a build variable, URL, static fixture, or local storage. No decorative/shadow administration UI was added.
- `docs/execution/P3_ENT_006_UI_READINESS_AUDIT.md` records the passed gates, exact disclosure boundary, and required next contract: same-origin browser authentication, privileged assurance, CSRF policy for mutations, logout/revocation, and hostile browser tests before an authorized administration view is added. P3-ENT-006 remains in progress for that implementation, UI disclosure/accessibility consolidation, and the exit audit. No publication action occurred.

## E-194 complete: redacted consolidated PostgreSQL audit browsing

- A backend-neutral audit-browsing contract and tenant-scoped PostgreSQL adapter now present the existing domain and ledger-control chains together only as a deterministic redacted read model. The sources remain independently verified; no global sequence or global hash-chain claim is made.
- `GET /api/v1/admin/audit/events` requires human `audit.read`, current privileged assurance, and an operator-owned cursor key. Its cursor binds tenant, resource, ordering, timestamp, source, and event identity. It returns no raw actor/object IDs, labels, request IDs, reasons, or metadata. `GET /api/v1/admin/audit/verify` requires the corresponding human `audit.verify` boundary and returns only source-specific verification codes and heads.
- Migration 0053 makes `audit.read` and `audit.verify` human-only for all future service-account permission rows. It is intentionally `NOT VALID` to preserve installations that already hold legacy machine grants; central policy denies those principals at runtime until an operator remediates them. No grant is silently deleted.
- A synthetic isolated PostgreSQL 17.10 proof passed fresh 0001-to-0053 migration, tenant RLS with zero rows outside a configured scope, redacted two-source browse, independent verification, human password step-up, signed pagination, direct 0053-to-0052-to-0053 recovery with retained synthetic data, and exact container cleanup. The final repository regression passed 1,930 tests with zero failures/errors and 62 declared external-capability skips in 342.681 seconds. Repository-wide Ruff, mypy over 351 source files, Bandit, pip-audit, lock, diff, and isolated package/archive checks pass.
- The new API is a PostgreSQL administration read surface only. Historical Local/SQLite audit APIs remain compatible; it does not supply an accessible administration UI, a global audit chain, legal/object-store retention proof, external assurance, compliance, or Enterprise readiness. P3-ENT-006 remains in progress for accessible UI, disclosure/accessibility consolidation, and the exit audit. No publication action occurred.

## E-193 complete: native integration disable and monotonic evidence retention

- A backend-neutral Application contract and tenant-scoped PostgreSQL adapter now list and disable the real federation-link, SCIM-credential, service-account, and notification-route resources. There is no duplicate connector registry or configuration shadow plane.
- Six `/api/v1/admin/security/*` integration/retention routes require a human `security.policy.manage` principal and current central step-up/MFA. Signed cursors bind tenant, resource, inactive/retired filter, ordering, and tie-break identity. Responses exclude credential/token/hash, external-subject, destination, secret-reference, raw actor, email, IP, and user-agent material.
- Native disable/revocation, native lifecycle evidence where applicable, and bounded domain audit commit in one tenant-scoped transaction. Stale state digests fail closed. Service-account disable revokes all active credentials; federation, SCIM, service-account, and notification runtime paths all deny after the administrative transition.
- Migration 0052 adds forced-RLS retention policies and append-only assignments plus an evidence retention version/floor guard. Policy application is optimistic and idempotent, retains the later of the existing and policy floor, and never shortens retention. The legacy evidence metadata writer preserves omitted retention and rejects explicit shortening before SQL.
- A fresh PostgreSQL 17.10 database migrated 0001-to-0052. The 18-test focused live target passes under a synthetic NOSUPERUSER/NOBYPASSRLS role and proves signed pagination/tamper denial, tenant/RLS isolation, disclosure controls, four runtime disables, retention replay/version/retirement behavior, direct-SQL floor enforcement, audit-failure rollback, direct/long empty recovery, and guarded non-empty downgrade.
- The final exact-snapshot regression collected 1,920 tests and passed all 1,915 runnable tests in about 247.7 seconds. Five declared external-capability skips require Windows symbolic-link creation, live S3, live object-lock S3, disposable PostgreSQL backup services, and live Redis; none is counted as a pass. Ruff, mypy over 347 source files, Bandit, pip-audit, lock, supply-chain, migration, governance, diff, build, and archive-membership gates pass.
- E-193 governs database metadata only: object-store WORM propagation, legal retention approval, connector/provider interoperability, secret rotation orchestration, consolidated audit browsing, accessible UI, HA/DR, external assurance, and Enterprise readiness remain unclaimed.
- P3-ENT-006 remains in progress for consolidated audit browsing, accessible English/Arabic UI, disclosure/accessibility consolidation, and its exit audit. No publication action occurred.

## E-192 complete: authoritative PostgreSQL role and access-policy lifecycle

- A backend-neutral Application contract and tenant-scoped PostgreSQL adapter now provide bounded permission/role views, exact role creation and permission replacement, optimistic role lifecycle changes, and exact user-role replacement. Every mutation uses one tenant advisory lock and one transaction for policy state, affected-user lifecycle increments, active-session revocation, and bounded domain-audit evidence.
- Six `/api/v1/admin/access/*` routes require a human principal with `roles.manage` and current central step-up/MFA. Signed role cursors bind tenant, resource, retired-state filter, ordering, and tie-break identity. Responses exclude credentials, email, raw IP, raw user-agent, bearer material, and arbitrary audit text.
- Migration 0051 adds explicit active/version/grant/revoke metadata, named closed-state constraints, and bounded lookup indexes. Authorization reads ignore inactive assignments, roles, and policies. Role retirement revokes assignments; reactivation never resurrects old grants. Bootstrap conflict handling no longer mutates descriptions or silently reactivates revoked policy.
- The PostgreSQL profile now returns `local_identity_surface_disabled` for the historical `/api/v1/roles` SQLite routes, closing the remaining server identity shadow plane while preserving Community/local behavior. Cross-service guards prevent disabling the last active holder of either `users.manage` or `roles.manage`.
- The focused PostgreSQL 17.10 target passes 19/19 with zero skips under a synthetic non-superuser NOBYPASSRLS role. It proves tenant and forced-RLS isolation, signed pagination, exact mutations, duplicate/stale denial, retirement without resurrection, session invalidation, last-manager protection including the identity-disable path, atomic audit-failure rollback, guarded non-empty downgrade, and direct/long empty recovery.
- The final current-tree regression collected 1,903 tests and passed all 1,898 runnable tests in 308.338 seconds. Five external-capability cases remained declared skips for Windows symbolic links, live S3, object-lock S3, disposable PostgreSQL backup services, and live Redis; none is counted as a pass. Ruff, mypy across 344 source files, Bandit, pip-audit, lock, supply-chain policy, build, and archive-membership gates pass.
- P3-ENT-006 remains in progress for integration/retention administration, consolidated audit browsing, accessible UI, and its exit audit. No publication action occurred.

## E-191 complete: authoritative PostgreSQL user and session lifecycle

- A backend-neutral Application contract and tenant-scoped PostgreSQL adapter now provide bounded user/session views, optimistic user enable/disable, and attributable session revocation. User disable revokes every active session and appends bounded domain-audit evidence in the same transaction; an injected audit failure proves the entire mutation rolls back.
- Four `/api/v1/admin/identity/*` routes require human `users.manage` plus current central step-up/MFA. Signed cursor scopes bind tenant, resource, filter, and ordering. Responses exclude email, password material, bearer tokens, token hashes, raw IP addresses, and raw user-agent values.
- The PostgreSQL profile returns `local_identity_surface_disabled` for every historical `/api/v1/users` SQLite route, closing the user-management shadow plane while preserving Community/local behavior. E-192 subsequently closed the `/api/v1/roles` server shadow surface and added the authoritative role/policy lifecycle.
- Migration 0050 adds positive lifecycle versions, attributable status/revocation metadata, closed reason/state constraints, and pagination indexes. SCIM disable/reactivation now conforms to the same lifecycle and session-revocation contract. Non-empty downgrade refuses before losing governed evidence; empty direct and 0050-to-0011-to-0050 recovery pass.
- The PostgreSQL 17.10 live HTTP contract passes under a non-superuser NOBYPASSRLS role with synthetic data: tenant isolation, cursor mismatch/tamper denial, self-disable and last-admin denial, stale-version conflict, all-session invalidation, current-session invalidation, audit evidence, SCIM compatibility, and audit-failure rollback. The focused E-191 target passes 38 tests with one separately declared migration-service skip.
- The final clean exact-snapshot regression collected 1,890 tests and passed all 1,884 runnable tests in 379.616 seconds; six external-capability cases remained declared skips. Ruff, mypy across 341 source files, Bandit, pip-audit, lock, governance, YAML, diff, direct/long rollback, guarded non-empty downgrade, build, and archive membership gates pass. The first exact-snapshot attempt was interrupted by Docker Desktop stopping at 30% with no pytest failure; it is recorded as blocked tooling evidence, not a pass.
- P3-ENT-006 remains in progress for integration/retention administration, consolidated audit browsing, accessible UI, and the task exit audit. No publication action occurred.

## E-190 complete: human-governed count-only security overview

- `SecurityCenterApplicationService` creates a tenant-digest-bound schema-v1 snapshot from non-negative count invariants and one UTC whole-second boundary. The canonical digest changes with tenant, time, runtime state, or counts; returned sections contain no subject rows, credentials, destinations, financial values, arbitrary audit text, or cluster-global sequence values.
- `GET /api/v1/admin/security/overview` exists only in the PostgreSQL server profile. `security.center.read` requires a human principal and current privileged assurance; with WebAuthn configured it requires user-verified WebAuthn. Migration 0049 and the service-account Application validator independently prohibit granting the permission to a machine identity.
- The PostgreSQL adapter executes one static parameterized projection beneath tenant RLS over identity, sessions/MFA, federation/SCIM/service accounts, scope/emergency policy, notifications, evidence retention/verification, and audit volume. It reports audit-chain verification as not evaluated and directs the caller to the separately authorized audit verification endpoint.
- Fresh PostgreSQL 17.10 migrated 0001-to-0049 in 3.878 seconds. The final expanded focused target passes 92/92 in 13.582 seconds under a non-superuser NOBYPASSRLS role, including real login, password step-up, count-only HTTP response, sibling exclusion, hostile direct-SQL machine-grant denial, 0049-to-0011-to-0049 recovery, and direct 0049-to-0048-to-0049 rollback. The final exact-snapshot live regression passes all 1,871 runnable tests from 1,876 collected in 296.893 seconds; five declared external-capability skips are not counted as passes.
- The first live attempt exposed an old constraint-name assertion and a rollback collision with PostgreSQL's automatic regex-constraint name. The first full regression then exposed a historical E-189 audit test that incorrectly required migration 0048 to remain the repository head. None of these failures was counted as a pass; each has a regression correction. A build inspection also caught the new JSON Schema missing from the sdist manifest before finalization; the final sdist contains it exactly once.
- This is the first P3-ENT-006 slice, not the complete administration center. Identity/policy mutations, session revocation, integration/retention administration, audit browsing, accessible UI, consolidated disclosure testing, and exit audit remain. No publication action occurred.

## E-189 complete: hosted scheduler and bounded notification delivery

- `PostgresSchedulerWorker` polls a validated bounded tenant set in stable order, uses one whole-second UTC clock per cycle, and opens one fresh connection per tenant. It performs no delivery I/O; durable schedule, job, dispatch, cursor, notification-outbox, and initial audit effects remain atomic in PostgreSQL.
- Migration 0048 adds immutable versioned notification routes, explicit schedule subscriptions, and append-only delivery transitions under forced tenant/workspace/entity RLS. Every notification event carries only the closed schema-v1 identifier/timestamp/digest envelope and an exact destination digest; raw financial rows, amounts, arbitrary text, and secret values are rejected.
- Notification egress is disabled by default. HTTPS webhooks and SMTPS email require exact allowlists, validate every DNS answer as globally routable, pin the chosen address while retaining TLS hostname verification, and apply bounded timeouts/responses. Webhooks use HMAC-SHA-256 and a stable idempotency key. Delivery is explicitly at-least-once; provider/receiver idempotency remains required.
- The focused PostgreSQL 17.10 non-superuser NOBYPASSRLS target passes 50/50 with zero skips, including atomic notification enqueue, sibling isolation, retry, dead-letter, explicit replay, immutable delivery evidence, and both injected transports. Fresh 0001-to-0048 migration, empty direct rollback/re-upgrade, non-empty downgrade refusal with preserved head/data, and the 136-policy forced-RLS catalog checks pass.
- `P3_ENT_005_EXIT_AUDIT.yaml` binds nine gates and 14 hostile/failure paths to real tests and retains explicit single-node, synthetic-transport, external-provider, production-secret, HA/DR, compliance, assurance, and Enterprise-readiness limitations. P3-ENT-005 is closed at this bounded contract. No external message or publication action occurred. Next is P3-ENT-006, Administration and security center.

## E-188 complete: atomic PostgreSQL schedule dispatch

- Migration 0047 adds immutable versioned schedule registrations, monotonic current cursors, retained initial cursors and registration digests, immutable occurrence-to-job dispatches, and count-only audit evidence under forced workspace/entity RLS.
- Tenant-wide discovery uses `FOR UPDATE SKIP LOCKED`; the selected schedule narrows the same transaction before one stable occurrence identity creates or resolves a compatible durable job. Job, dispatch, cursor, and audit writes commit or roll back together. Higher versions supersede prior active versions; configuration mutation and cursor reversal are database-rejected.
- A fresh PostgreSQL 17.10 database migrated 0001-to-0047. The focused non-superuser NOBYPASSRLS target passes 14/14 with zero skips across two-worker coordination, catch-up, idempotent replay, sibling tenant/workspace/entity exclusion, append-only evidence, version supersession, and deliberate durable-job conflict rollback. Empty direct and long rollback pass; non-empty downgrade fails before schema mutation.
- Full live regression on the locked Python 3.12 environment collected 1,852 tests and passed every runnable test with five declared service/platform skips. The gate exposed both required repository/parity inventory drift and a pre-existing nondeterministic WebAuthn assurance tie; inventories now classify the new service and active assurance deterministically prefers user-verified WebAuthn. The real HTTP WebAuthn path passed five consecutive reruns.
- Ruff, mypy over 331 source files, Bandit, pip-audit, package build/membership, lock validation, nine execution YAML files, and diff checking pass. P3-ENT-005 remains in progress for a hosted polling runtime, optional notifications, egress allowlists, redaction, operational surfaces, and its exit audit. No publication action occurred.

## E-187 complete: deterministic timezone schedule semantics

- A pure schedule domain now evaluates versioned daily/weekly local times against explicit IANA zones without network or database effects. UTC boundaries and cursors require whole-second precision; host local time is never implicit.
- DST gaps are counted and skipped, ambiguous wall times select an explicit first/second occurrence, and stable occurrence keys hash schedule ID, version, and UTC time.
- Misfire policies are distinct: `skip` records discarded due occurrences, `fire_once` dispatches only the latest, and bounded `catch_up` advances through the last dispatched occurrence so remaining backlog is not silently lost. Excess lookback fails for operator review.
- Five focused tests plus Ruff and mypy pass. `tzdata>=2026.3` is direct rather than transitive. P3-ENT-005 remains in progress for durable persistence/coordination, idempotent job dispatch, notifications, egress controls, redaction, audit, live failure evidence, and exit audit.

## E-186 complete: consolidated P3-ENT-004 isolation exit

- `docs/execution/P3_ENT_004_EXIT_AUDIT.yaml` binds the eight required isolation gates to source, test, migration, and claim-boundary evidence, and its 14-entry hostile matrix resolves only to real denial, no-effect, or policy-preservation regression tests.
- A fresh disposable PostgreSQL 17.10 database migrated from 0001 to 0046. The consolidated target passed 63/63 with zero skips under a `NOSUPERUSER`/`NOBYPASSRLS` application role across hierarchy, durable workers, exports, object artifacts, business RLS, durable API scope authority, emergency/WebAuthn HTTP compatibility, operations, and migration/recovery contracts.
- The first complete live regression exposed two privileged-route fixtures without the new durable workspace grant and business schema installers that recreated tenant-only policies alongside stronger workspace policies. The fixtures now exercise real grants, and all 12 current business installers remove the compatibility policy whenever composed `tenant_scope` exists; static and live regressions prevent reintroduction.
- Direct 0046-to-0045-to-0046 and isolated 0046-to-0011-to-0046 rollback drills passed. The final catalog at head contains 130 policies over 130 RLS-enabled and forced-RLS tables.
- P3-ENT-004 is complete only for the current documented single-node boundary. Current object-store tests exercise the official local provider; S3-compatible evidence remains the prior synthetic localhost MinIO commit `9e49d5e`. HA, DR, production assignments, external penetration/assurance, compliance, and Enterprise-readiness claims remain excluded.

## E-183 complete: authorized RLS-backed Enterprise export

- A deterministic schema-v1 control-plane export now requires explicit workspace scope, `reports.read`, and exact tenant/workspace/entity grants before any snapshot query. Static allowlisted datasets are read only after transaction-local scope installation, with 10,000-row dataset and 32 MiB artifact ceilings.
- Migrations 0044-0045 compose every present direct business-scope dimension into PostgreSQL RLS, resolve 26 business child relationships through their authoritative parent, and add backward-compatible workspace attribution to eight legacy business roots. Legacy NULL-attribution rows remain tenant-global but are hidden from workspace-scoped sessions.
- Digest-addressed artifacts publish idempotently into hierarchical object storage and verify exact bytes plus tenant/workspace/entity metadata. Authorization, database, and storage failure paths return no artifact.
- Live PostgreSQL 17.10 `NOBYPASSRLS` tests exclude sibling direct and parent-scoped child rows, reject sibling writes, and preserve the explicit legacy tenant-global compatibility path. Migration 0046 adds append-only principal scope grants; authenticated server principals carry only active grants, and all PostgreSQL business boundaries reject missing or sibling workspace selection before opening a database transaction. The combined current live target passes 32/32. P3-ENT-004 remains open only for the consolidated exit audit across jobs, exports, objects, routes, migrations, and failure paths.

## E-182 complete: hierarchical object-artifact isolation

- Official local and S3-compatible stores now derive immutable keys from validated tenant/workspace/entity scope and bind the same hierarchy into checksum metadata. Entity scope without a workspace is invalid, sibling paths are distinct, and reads fail closed for absent or mismatched hierarchy.
- SQLite and PostgreSQL Evidence Application adapters pass their authoritative workspace only to stores that explicitly advertise hierarchical capability. They verify the returned tenant/workspace before registry persistence; legacy tenant-only providers retain their existing protocol without supporting an Enterprise isolation claim.
- The focused target passes, including sibling workspace/entity reads, metadata tampering, presigned-key scope, local parity, legacy-provider compatibility, and no-row-on-scope-mismatch failure behavior. A source-built MinIO commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a` passed the live S3 hierarchy contract.
- P3-ENT-004 remains in progress for PostgreSQL export scope, remaining domain tables, API authority composition, and the complete failure-path inventory.

## E-181 complete: durable worker workspace/entity isolation

- Migration 0042 binds durable jobs directly to transaction-local workspace/entity scope and makes transitions, leases, lease events, and partition effects visible only through a parent job visible in that scope.
- Tenant-wide claim remains an explicit scheduler operation. After locking one candidate, the repository narrows the same transaction before transition or lease evidence; heartbeat, checkpoint, completion, failure, cancellation, effect reads, and crash/resume operations re-establish the parent job scope.
- The final PostgreSQL 17.10 non-superuser job/hierarchy/Alembic target passes 12/12. It proves sibling job and transition reads are hidden, sibling child-evidence writes are denied, existing idempotency/fencing/crash-resume contracts remain green, and direct 0042-to-0041 downgrade/re-upgrade passes.
- P3-ENT-004 remains in progress for exports, object storage, remaining domain tables, API scope authority, and failure-path inventory.

## E-180 in progress: explicit hierarchical PostgreSQL execution scope

- An immutable transaction scope now validates and carries tenant, workspace, organization, and legal entity IDs through transaction-local PostgreSQL settings. A legal entity without its organization fails closed; commit and rollback clear every setting.
- Migration 0041 adds optional-child RLS constraints to workspaces, periods, workspace/organization ownership links, organizations, legal entities, and branches while preserving explicit tenant-wide administration.
- A PostgreSQL 17.10 non-superuser target passes 19/19 across the new hierarchy, foundation, operational-head, and Alembic contracts. It proves sibling workspace/organization/entity reads are hidden and a sibling-period write is rejected. Direct 0041-to-0040 downgrade and re-upgrade pass.
- P3-ENT-004 remains in progress: jobs, exports, object storage, remaining domain tables, API authority composition, and failure paths still require equivalent evidence.

## E-179 complete: user-verified WebAuthn MFA and P3-ENT-003 exit

- Optional `mfa` installs pinned `webauthn==3.0.0`; a closed 64 KiB v1 configuration enables exact RP/origin policy. WebAuthn is disabled by default and non-loopback origins require HTTPS.
- Migration 0040 adds forced-RLS five-minute challenges, public-key-only credentials, monotonic signature counters, and append-only evidence. Challenges bind tenant, user, session, and ceremony and commit consumption before verification. Registration and authentication require User Verification.
- A real synthetic P-256 authenticator completes registration and authentication through the live HTTP API. When WebAuthn is configured, password reauthentication alone receives `mfa_required` for every closed privileged permission; the same operation succeeds after a session-bound `webauthn_user_verified` assertion.
- The final PostgreSQL 17.10 non-superuser WebAuthn/API/migration/operational target passes 22/22. Direct 0040-to-0039 downgrade initially exposed append-only cleanup conflict; the migration now scopes trigger disable/delete/enable transactionally, and downgrade/re-upgrade passes.
- P3-ENT-003 is complete at its bounded exit contract: credential issuance/rotation/revocation/expiry, typed least-privilege machine principals, privileged step-up, governed emergency review, and WebAuthn MFA are all live-tested. Workload federation, hosted operation, recovery UX, broad authenticator interoperability, and independent assurance remain separate phase risks/gates.

## E-178 complete: governed emergency authority and mandatory review

- Migration 0039 adds forced-RLS request, permission, and append-only event storage with a deterministic database event sequence. The closed emergency registry permits only five operational/financial actions and excludes identity, role, policy, service-account, and security administration.
- A human may request authority only for self. A different stepped-up human approves; activation is bound to the requester's current stepped-up session for 5–60 minutes; every emergency-derived authorization records its exact permission and HTTP surface; end or expiry enters `ReviewPending`; a third independent stepped-up human reviews.
- Live PostgreSQL 17.10 non-superuser evidence passes 13/13 repository, HTTP, migration, and operational-head cases. Direct 0039-to-0038 downgrade and re-upgrade pass. Full repository regression, Ruff, mypy across 315 source files, Bandit, pip-audit, build, archive membership, and `git diff --check` pass.
- The live gate exposed and fixed empty-base-permission fallback, transaction-timestamp event ordering, and retained-fixture cleanup defects before the final green run. P3-ENT-003 remains in progress for true MFA, workload identity federation, hosted operational evidence, and independent assurance.

## E-177 complete: session-bound privileged human reauthentication

- Migration 0038 adds one forced-RLS, append-only assertion table bound to the existing tenant, human user, and session. Application assertions last at most ten minutes, the database caps them at fifteen minutes, and revoked/expired sessions cannot reuse them.
- The PostgreSQL profile now returns `step_up_required` for identity administration, Finance Core management/validation, close management, inventory posting, and credit override until `POST /api/v1/auth/step-up` re-verifies the current local password. Step-up never grants a permission and service accounts cannot invoke it.
- The first full regression exposed that policy enforcement had unintentionally reached Community/SQLite paths with no server assurance boundary. Enforcement is now explicitly server-profile-only; the six affected compatibility/SOD tests and the complete repository suite reran green.
- A clean PostgreSQL 17.10 non-superuser target passed 48/48 privileged-session, HTTP identity, service-account, policy, migration and operational-head cases. P3-ENT-003 remains open for governed emergency-access request/approval/expiry/post-use review and broader MFA/workload/independent evidence.

## E-176 complete: typed HTTP machine-principal composition

- Reserved `rfa_` bearer credentials now authenticate only through the forced-RLS service-account repository. The resulting server principal is explicitly typed, carries only the account's current direct permissions, never loads user roles, and revokes the presented credential on logout.
- Central policy denies explicit human-governed permissions and every `.approve`, `.review`, or `.complete` action to service principals. Dynamic workflow transitions are human-only, and policy evidence records the sanitized principal type.
- The final PostgreSQL 17.10 non-superuser HTTP/policy/service target passed 35/35 tests. A broader 41/41 target exposed and then verified the fix for Alembic disabling the authorization logger; `disable_existing_loggers=False` now preserves policy-audit evidence after migrations.
- Full repository regression, Ruff, mypy across 312 source files, Bandit, and pip-audit pass. P3-ENT-003 remains in progress for privileged human sessions, step-up, emergency-access expiry/review, workload identity federation, and independent operational evidence.

## E-175 complete: role-free service-account lifecycle foundation

- Migration 0037 adds four forced-RLS tables for service accounts, direct permissions, hash-only credentials, and append-only lifecycle events. PostgreSQL enforces 1-32 grants, human-only permission denial, immutable identity/credential fields, monotonic versions, account-scoped rotation, per-account TTL, and event immutability.
- The operator CLI creates accounts, reveals new tokens once, rotates/revokes credentials, and disables accounts with atomic all-credential revocation. Accounts have no password, local user, role, or human session.
- A disposable PostgreSQL 17.10 non-superuser target passed 14/14 lifecycle, hostile SQL, migration, rollback, operational-head, and tenant-isolation tests without service skips. A separate CLI smoke proved create/issue/rotate/revoke/disable and database inspection found only two valid SHA-256 hashes, both revoked.
- Full repository regression, Ruff, mypy, Bandit, pip-audit, and wheel/sdist build are green. P3-ENT-003 remains in progress: service-token HTTP composition, privileged human sessions, step-up, emergency access, expiry/review, and independent operational evidence remain open.

## E-174 complete: authenticated SCIM HTTP and credential lifecycle

- Migration 0036 adds tenant-scoped, forced-RLS, hash-only SCIM client credentials with bounded expiry, rotation lineage, last-use throttling, and revocation. The operator CLI returns a new opaque token once and never reads raw token material from storage.
- Fifteen `/scim/v2` operations provide authenticated discovery plus bounded User/Group create, exact-filter list, read, conditional replace/PATCH, deactivation/session revocation, and Group deletion. SCIM errors and media types are protocol-shaped; Bulk, sort, arbitrary filters/PATCH paths, and implicit RBAC fail closed.
- A PostgreSQL 17.10 non-superuser run passed all 21 SCIM/Alembic cases without skips, including cross-tenant denial, hash-only storage, rotation/revocation, HTTP lifecycle, stale ETag refusal, session revocation, fresh migration, direct downgrade/re-upgrade, and isolated rollback/recovery.
- The first full regression run exposed a wall-clock-expiring signed-SAML fixture. The fixture now derives certificate and assertion times per test; its focused rerun and the complete repository suite pass. P3-ENT-002 is complete only at this bounded contract. Hosted provider interoperability, MFA, production approval, and Enterprise readiness are not claimed.

## E-173 complete: forced-RLS SCIM lifecycle persistence

- Migration 0035 adds forced-RLS SCIM User, Group, same-domain membership, and sanitized lifecycle-event tables. Advisory transaction locks serialize each tenant/domain/type/external-ID identity; identical concurrent delivery preserves one stable server ID and version.
- Provisioning creates a role-free local identity with an inaccessible random verifier. Group writes never touch RBAC. Deactivation atomically disables both SCIM and local identity state and revokes all current sessions while retaining evidence.
- A PostgreSQL 17.10 non-superuser lifecycle proves concurrent idempotency, update/group version behavior, no role assignment, session revocation, and cross-tenant invisibility. Fresh migration, direct 0035 rollback/reapply, and isolated 0035-to-0011-to-0035 recovery pass.
- Live testing exposed and fixed two real regressions: JSON arrays were rejected by strict tuple-backed models, and operational migration status omitted revision 0035. P3-ENT-002 remains in progress for authenticated HTTP resources, filters, PATCH/ETag, discovery, and broader hostile/interoperability evidence.

## E-172 in progress: SCIM provisioning application boundary

- A provider-neutral SCIM 2.0 boundary now models a strict supported subset of RFC 7643 User and Group resources with exact schema URNs, bounded fields, tenant plus provisioning-domain scope, stable server IDs, scoped external-ID idempotency, deactivation, and sanitized audit outcomes.
- Client IDs, metadata, passwords, roles, permissions, unknown fields, control characters, duplicate schemas/members, and multiple primary emails fail closed. SCIM group membership is not ReconForge authorization and cannot implicitly grant a local role or permission.
- Eleven focused tests, Ruff, and mypy pass. P3-ENT-002 remains in progress for PostgreSQL forced-RLS persistence, authenticated HTTP resources, filter/PATCH/ETag/discovery semantics, session revocation, migration/rollback, and live hostile evidence. No SCIM interoperability or Enterprise-readiness claim is made.

## E-171 complete: server-issued challenge and bounded federation task exit

- `reconforge api serve` now accepts a bounded version-1.0 JSON configuration through `--federation-config` / `RECONFORGE_FEDERATION_CONFIG`. It rejects unknown fields, duplicate providers, private JWK members, private/invalid SAML certificate material, and federation without PostgreSQL; the default remains disabled.
- A fourth forced-RLS table stores only challenge/correlation hashes. Five-minute challenges are tenant/provider/protocol bound, one-time, serialized, stale-pruned, and capped at 100 active rows. Client-selected nonce or `InResponseTo` values cannot bypass the server-issued challenge.
- Real RSA OIDC and real signed SAML assertions traverse HTTP. A disposable PostgreSQL 17.10 non-superuser lifecycle proves challenge issuance, OIDC login, prelinked local roles, hash-only session authentication, `/me`, logout/revocation, replay denial, sanitized audit, subject hashing, and tenant isolation.
- The closed API inventory is 159 operations with digest `37bd9d54d27292fa32306e2a05a2a46c2465b9fb7288cbe7bf64050a207c2ec3`.
- P3-ENT-001 is complete at evidence-bounded adapter scope. Authorization-code exchange, discovery, IdP-initiated SAML, SCIM, MFA, provider single logout, hosted IdP interoperability, independent review, and Enterprise readiness are not claimed and remain separate tasks/risks.

## E-170 complete: fail-closed federated login API composition

- `POST /api/v1/auth/federated-login` now composes the provider-neutral policy, operator-owned verifier, atomic PostgreSQL replay store, prelinked local authority, existing hash-only session, and sanitized final outcome audit under one tenant RLS transaction.
- The route is disabled by default, rejects unsafe/extra request fields, exposes no provider claims, returns one uniform denial for verification/link failures, and carries the air-gap refusal policy. The closed route inventory intentionally advances from 157 to 158 operations with digest `8b2036388a300f3099f32580c09744150081438c67159688ff7b3107a373d19c`.
- The existing authenticated PostgreSQL logout route revokes the same session type created by federation; no parallel token or custom logout protocol was introduced.
- P3-ENT-001 remains in progress until supported operator configuration loading and at least one real signed OIDC and SAML assertion traverse the HTTP composition boundary. No SSO availability or production claim is made.

## E-169 complete: durable tenant-scoped federation replay and identity binding

- Migration `0034_postgres_federation` adds three tenant-keyed, forced-RLS tables for one-time assertion consumption, pre-provisioned external-to-local identity links, and append-only federation lifecycle events.
- Only SHA-256 assertion and issuer-subject identities are persisted; raw assertions, issuers, subjects, access tokens, and external group claims are not stored in the federation tables.
- Replay consumption is a single `INSERT ... ON CONFLICT DO NOTHING`. Login requires an enabled prelinked local user and refuses every externally mapped role not already assigned locally before creating the existing hash-only PostgreSQL session.
- A disposable PostgreSQL 17.10 service migrated from 0001 through 0034. The non-superuser live lifecycle passed without a service skip and proved one-time replay, local role/session binding, token authentication, hashed subject storage, and cross-tenant RLS invisibility. The isolated migration downgrade/re-upgrade contract also passed.
- P3-ENT-001 remains in progress: operator configuration, fail-closed API integration, and end-to-end logout through the existing revocable session path are the next slice. No SSO support, Enterprise readiness, production approval, or publication is claimed from E-169.

- `P0-001` Baseline reproducibility report: completed for this dirty snapshot.
- `P0-002` Claims Evidence Matrix: completed for this dirty snapshot.
- `P0-003` Documentation drift correction: completed with targeted link/claim evidence.
- `P0-004` Canonical Money and Currency registry: completed for the defined foundation exit evidence.
- `P0-005` Remove financial floats from critical paths: completed for the Phase 0 exit contract under ADR 0097. All 52 financial-policy defaults across 23 runtime files are strict v2; direct config/models/services, parsing, Money construction and scalar operators reject binary floats before conversion. Exact text/Decimal/integer inputs remain valid. The 73 lexical hits remain classified; 16 are explicit historical compatibility aliases/helpers or rejection/tag annotations, not implicit current defaults. Versioned historical readers may select legacy explicitly; supported-version/live-backend proof remains P0-009/hosted-gate scope.
- `P0-006` Stable source lineage identity: completed for the bounded stock/GL exit contract under ADR 0096. Decimal-scale, duplicate-identical multiset identity, source-location separation, row permutation, Pandas/DuckDB full scan, and forced-partition signature-v3 properties pass without row-index identity. Supported Python/backend versions and broader engine/strategy parity remain P0-009 scope; upstream authenticity and unavailable physical-copy identity are not claimed.
- `P0-007` Duplicate-identical-record policy: completed for the bounded stock/GL and deterministic platform matcher slice under ADR 0042.
- `P0-008` Property-based order invariance: completed for the bounded deterministic matcher contracts with 105 derandomized generated examples per run under ADR 0043.
- `P0-009` Cross-engine deterministic digest: completed. E-083 supplies the exact local four-cell/JUnit evidence; E-084 identifies all-green GitHub Actions run `30239994946` on `aaf2110`, where all four Python 3.11/3.12 lower/current-compatible NumPy/Pandas/DuckDB cells pass without skips. Live process/PostgreSQL recovery remains the separate P1-PLAT-004 scope.
- `P0-010` Golden finance dataset registry: completed at registry 1.1.0 for three bounded synthetic stock/GL cases with closed schema, layered SHA-256 digests, exact expected outputs, source-distribution packaging, and update policy under ADRs 0045 and 0048.
- `P0-011` Risk register normalization: completed for all 18 current risks with closed schema, role owners, triggers, deterministic ratings, mitigations/evidence, residual risk/actions, and review cadence. ADR 0046 established R-001..R-017; E-055/ADR 0070 added R-018 for incomplete hostile-file coverage without weakening the governance contract.
- `P0-012` Maturity labels enforcement: completed for all nine runtime modules and seven named publishing surfaces; three unsupported Beta labels were downgraded to Experimental under ADR 0047.
- `P0-SEC-001` Security Architecture v2: completed as a closed schema-v2 registry covering three conservatively labelled deployment modes, six data classes, seven trust boundaries, ten evidence-linked bounded/partial controls, role ownership, and normalized residual-risk parity under ADR 0062. This is repository architecture evidence, not deployed control-effectiveness, compliance, certification, or production-readiness evidence.
- `P0-SEC-002` Threat-model index by module: completed for all nine active runtime modules with exact registry maturity/capability/interface/data-class/test parity, eight scoped actors, eight shared threats, 20 classified assets, 33 module threat cases, architecture control/boundary/owner links, existing tests, normalized residual risks where exact, and explicit assumptions/limitations/exclusions under ADR 0063. This is design coverage, not deployed threat-mitigation or penetration-test evidence.
- `P0-SEC-003` Latest-stable ASVS mapping: completed against official OWASP ASVS 5.0.0 with its release tag/commit and 105,100-byte CSV SHA-256 pinned; the closed schema-v1 registry covers all 17 chapters and maps 55 selected requirements as four implemented, 33 partial, 10 planned, and eight not applicable while leaving 290 explicitly unassessed under ADR 0064. E-055 advances only bounded file-type requirement V5.2.2 from planned to partial. This is scoped repository evidence/gap governance, not a full assessment, ASVS level, deployed control proof, penetration test, compliance, or certification.
- `P0-SEC-004` SSDF implementation matrix: completed against official final NIST SP 800-218/SSDF 1.1 with PDF/table identities pinned, draft SSDF 1.2 explicitly excluded, and final SP 800-218A retained as a separate AI-profile assessment. The closed schema-v1 registry maps all four groups, 19 practices, and 42 tasks as 28 partial and 14 planned with Security Architecture owners, positive evidence/tests, gaps/actions, and 90-day review cadence under ADR 0065. This is not SSDF conformance or proof of an operating secure-development process.
- `P0-SEC-005` SLSA and provenance plan: completed against official Approved SLSA 1.2 with its tag/commit pinned. The closed schema-v1 plan keeps Build and Source UNEVALUATED while defining five artifact identities, seven trust boundaries, in-toto Statement v1/SLSA provenance v1, strict independent verification with 12 safe failure codes, evidence-preserving rollback, and 12 gates. E-053 exact-subject SBOM implementation evidence advances eight gates to partial while four remain planned under ADRs 0066-0068. This is not a signature, attestation, trusted-builder assessment, SLSA level, or verified-property claim.
- `P0-SEC-006` Signed release pipeline: completed for its exact non-publishing candidate exit. GitHub verifies signed annotated tag `v0.7.1` on clean merged `main` commit `d47edd8`; run `30243819239` built source, wheel, sdist, and digest-addressed OCI subjects, generated keyless provenance, enforced repository/workflow/ref/revision/GitHub-hosted-runner expectations, independently verified every bundle, and retained artifact `8644255664`. This does not claim OCI reproducibility, immutable GitHub Release/PyPI publication, SLSA level, compliance, certification, or production readiness.
- `P0-SEC-007` SBOM per artifact: completed for its exact generated/archived/verified candidate exit. Run `30243819239` produced subject-bound CycloneDX 1.7 documents for source (239 components), wheel (30), sdist (30), and the exact Syft-scanned OCI image (3972); all retain `completeness: unknown`. Five SBOM checksum records, four SBOM attestation bundles, and file/image provenance independently verify against `v0.7.1` and `d47edd8`. This does not claim inventory completeness, vulnerability/license/reachability assurance, immutable publication, compliance, certification, or production readiness.
- `P0-SEC-008` Secret and dependency policies: completed for its exact lock/constraint, secret-scan, update-cadence, exception-workflow, and CI-gate exit. The universal Python lock and zero-gap npm lock are enforced by the closed policy; all 211 current npm registry entries carry HTTPS resolution and SRI; the local clean install/audit/release/SBOM/web gates pass, while the cited Security `30240642293`, Docker `30240642306`, CI `30240642321`, and CodeQL `30240642386` evidence applies to the earlier 209-entry committed revision `d543309`. This is not hosted evidence for the two new accessibility-test packages, package provenance, package-code safety, reachability, licensing, malware absence, or release attestation evidence.
- Release closeout: E-086 records pre-merge readiness; E-087 records merged PR #54, GitHub-verified signed annotated `v0.7.1`, all-green exact-main checks, successful candidate run `30243819239`, retained artifact digest `sha256:0a59e3dd6a5e66118b44be5680e5abc312a44ad7b299579b7e16b64d35f42d63`, image digest `sha256:89c598e291188ff85d75c2c17ab6d67ae9a0902519a6984f49fd0dcc1ec870f4`, checksum verification, and independent subject/bundle verification.
- `P0-SEC-009` File ingestion abuse tests: completed for the exact Phase 0 exit evidence under ADR 0095. Fixed size/type/path/decompression/formula/XML/YAML hostile cases, path/source-safe public failures, runtime-policy parity, and exact direct tabular/JSON/YAML parser inventories pass; every current direct filesystem and persisted JSON decoder is bounded by prior slices. This does not close FI-012/FI-013 or R-018 and does not claim complete legacy-XLS inspection, malware/quarantine, authenticity, disclosure approval, secure uploads/connectors, real host-loss durability, or supported throughput.
- `P0-SEC-010` Authorization and SoD property tests: completed for the Phase 0 exit contract under ADR 0094. The central engine now requires a named permission, intersects every supplied tenant/workspace/entity/period with immutable grants, and defaults creator approve/review ownership checks on. A closed nine-surface platform service inventory uses one actor comparator; arbitrary generic overrides and trusted-local/user-backed self-approval paths fail. The locked 85-test focus and full 1,287-test collection pass (1,277 executed, ten service skips). This is not complete amount/region/data-class ABAC, emergency-access governance, or deployed enterprise authorization evidence.
- E-072 bounds SQLite audit metadata plus the PostgreSQL ledger audit writer/list/verifier path under one canonical finite-object contract with explicit resource ceilings. SQLite retains exact stored-text hashes; PostgreSQL reconstructs the historical canonical pre-JSONB text. Invalid metadata independently fails verification and list, and SQLite export refuses it before writing files instead of emitting a sentinel. Its earlier producer-coverage wording overstated the PostgreSQL scope: master-data, evidence, and reconciliation audit writers still used local unbounded encoders. E-073 found and corrected that omission; ADR 0088, D-069, DOC-038, and the E-073 regression inventory retain the correction rather than rewriting the historical evidence.
- E-073 binds all six PostgreSQL outbox producer call sites and list/claim/publisher handoff to `postgres-outbox-payload-json-v1`: canonical finite object JSON with unique keys and 4 MiB/100,000-node/depth-32/25,000-item/262,144-character ceilings. Corrupt claims roll back their lease/attempt mutation before publisher invocation; valid event identity, JSONB, lease, retry, and dead-letter behavior remains compatible. It also migrates the three PostgreSQL audit writers omitted by E-072 to the bounded audit contract. Thirteen dedicated cases, 103 focused tests (99 passed, four service skips), and the full locked 1,192-test collection (1,182 passed, ten skipped) pass. Six direct FI-013 generic export/reconciliation/Redis/matching/worker decoders, producer authenticity, centralized authorization, malware/classification, supported throughput, live PostgreSQL/external publisher behavior, and broader R-018 gaps remain open.
- E-074 binds PostgreSQL reconciliation `rule_json`, `attributes_json`, `lineage_json`, and `evidence_json` producers plus repository/worker consumers to four finite-object profiles over `postgres-reconciliation-object-v1`. Attributes retain the existing 100000-byte producer ceiling; rule/lineage/evidence use 4 MiB, and all apply 100,000-node/depth-32/25,000-item ceilings with explicit scalar limits. Corrupt rows fail before matcher/public use, partition lineage/evidence fail before output hashing or run locking, and JSONB rule text is re-canonicalized before established fingerprints. Twenty-eight dedicated collected cases, 130 focused tests (129 passed, one live-service skip), and the full locked 1,220-test collection (1,210 passed, ten skipped) pass. Three direct FI-013 generic export/Redis/matching decoders, producer authenticity, centralized authorization, malware/classification, supported throughput, live PostgreSQL behavior, and broader R-018 gaps remain open.
- E-075 binds the SQLite matching rule written to `match_jobs` and `match_rules`, idempotent replay, and public job readers to `sqlite-matching-rule-json-v1`. It uses 4 MiB/100,000-node/depth-32/25,000-item/262,144-character ceilings, finite unique-key object JSON, and one pre-transaction encoding while preserving the historical spaced sorted ASCII text, policy fields/defaults, result identity, matching digest, and idempotency behavior. New producers reject binary floats; historical finite floats remain readable. Fourteen dedicated cases, 115 focused tests, and the full locked 1,234-test collection (1,224 passed, ten skipped) pass. Two direct FI-013 generic export/Redis decoders, stored-row authenticity, centralized authorization, malware/classification, supported throughput, and broader R-018 gaps remain open.
- E-076 binds tenant-scoped Redis session writes/reads to the closed `redis-session-json-v1` profile: 16 KiB, 16 nodes, depth two, four fields, and 256 characters/scalar. It requires bounded string IDs, a lowercase SHA-256 token digest, and explicit UTC expiry; validates before client access; preserves compact bytes, tenant key hashing, TTL, missing-key, and ID-match behavior; and leaves corrupt values unchanged. Seventeen dedicated cases, 91 focused tests (90 passed, one live-Redis skip), and the full locked 1,251-test collection (1,241 passed, ten skipped) pass. The optional store remains outside the main login lifecycle; at the E-076 boundary generic export was the sole direct FI-013 call, subsequently closed by E-077.
- E-077 binds all five public SQLite export `_json` fields through an exact registry. Audit and matching-rule fields reuse their established profiles; legacy summaries and matching lineage add field-specific 4 MiB finite-object producer/consumer contracts. All payloads validate before destination creation or file writes; non-text/corrupt state produces neither sentinel nor `db_exported` effect; metadata/summary/rule objects and the historical `lineage_json` string remain format-v1 compatible. Fifteen dedicated cases, 81 focused tests, and the full locked 1,266-test collection (1,256 passed, ten skipped) pass. No direct FI-013 parser remains; authenticity, authorization, malware, crash-atomic multi-file publication, live-service, and throughput gaps remain under R-018.
- E-078 stages all nine format-v1 public database export payloads, adds an exact SHA-256/byte-length manifest, and publishes the verified directory with bounded rollback state. Existing payload shapes remain unchanged; successful replacement removes stale files, handled swap failure restores the prior tree, and `db export-recover` fails closed on ambiguous/tampered crash state. Eight dedicated cases, a 39-test locked focus, and the full locked 1,274-test collection (1,264 passed, ten skipped) pass. Local-filesystem observer intervals, pre-marker abrupt-loss staging, audit/filesystem cross-resource atomicity, source authentication, authorization, malware, and throughput remain explicit limitations under R-018.

## Current gates

- Pass after remediation: locked Python 3.11 Ruff, Mypy, 1,278/1,278 executed Python tests (10 additional service skips; 1,288 collected), Bandit, pip-audit, package build/membership assertions, doctor, validate, and demo, plus the prior npm audit, supply-chain validation, Gitleaks history/tree scans, six-workflow actionlint, and web install/typecheck/unit/build/E2E gates. E-082 exact JUnit/artifact evidence is recorded separately; hosted and remaining P0 gates are not inferred from this local run.
- Package evidence: wheel and source distribution contain `reconciliation-signature-v3`, `canonical-multiset-occurrence-v1`, strict/legacy financial-input policy, strict/legacy shared YAML configuration/rule/review/period/client-pack loading, client-pack/period-comparison/rule-result v1/v2 readers/writers/verifiers, anonymizer/generator v1/v2 and variance v1/v2/v3 runtime readers/current writers, bounded ambiguity policy/runtime code, matching/API/worker/report propagation, DuckDB partition summary ordering, the exact Hypothesis dev-extra pin, and nine Experimental module descriptors; sdist additionally contains their versioned schemas/contract tests, registry 1.1.0, dense-ambiguity CSVs, management schema v4, normalized risk governance, and maturity policy/schema, all governance/test artifacts verified absent from the runtime wheel.
- E-033 packaging boundary: the existing reconciliation worker remains in wheel and sdist; the new crash/lease regression is sdist-only and ADR 0049 is repository-only under the current manifest. Build success is not live crash evidence.
- E-034 packaging boundary: the canonically digested engine matrix, schema, guide, and contract test are sdist-only; the CI workflow and ADR 0050 are repository-only. No supported-version cell result is claimed from packaging or local Python 3.14 checks.
- E-035 packaging boundary: the three exact scalar helpers are in wheel and sdist; their extended existing contract test is sdist-only and ADR 0051 is repository-only. Packaging proves availability, not removal of the remaining 16 legacy compatibility lines.
- E-036 packaging boundary: strict Money factory/methods are in wheel and sdist; their extended existing contract test is sdist-only and ADR 0052 is repository-only. Legacy constructor/operator defaults remain packaged compatibility APIs.
- E-037 packaging boundary: strict Studio filter selection and the named legacy alias are in wheel and sdist; the extended Studio test is sdist-only and ADR 0053 is repository-only. The filter is an ephemeral read boundary, not persisted reconciliation evidence.
- E-038 packaging boundary: anonymizer v1/v2 runtime reader/current writer are in wheel and sdist; the v1/v2 JSON Schema and extended test are sdist-only; ADR 0054 is repository-only. The runtime wheel does not carry repository documentation schemas.
- E-039 packaging boundary: variance unversioned/v1/v2/v3 runtime readers/current writer are in wheel and sdist; the v1/v2/v3 JSON Schema and extended contract test are sdist-only; ADR 0055 is repository-only. Packaging proves distribution boundaries, not that historical reports were generated under strict policy.
- E-040 packaging boundary: synthetic-generator v1/v2 runtime reader/current writer are in wheel and sdist; the v1/v2 JSON Schema and extended contract test are sdist-only; ADR 0056 is repository-only. Packaging proves distribution contents, not fixture realism, historical strictness, or benchmark execution.
- E-041 packaging boundary: the strict/legacy config runtime reader is in wheel and sdist; its dedicated contract test is sdist-only, while ADR 0057 and the repository default config are in neither. Packaging proves availability, not config-document signing/digest or removal of the direct Python legacy default.
- E-042 packaging boundary: the shared safe YAML helper and rule runtime reader/writer/verifier are in wheel and sdist; the v1/v2 rule-results schema and dedicated contract test are sdist-only, while ADR 0058 is repository-only. Packaging proves distribution contents, not pack signing/approval, source-system authenticity, or removal of direct Python legacy defaults.
- E-043 packaging boundary: period/review runtime readers, writer, and verifier are in wheel and sdist; the v1/v2 period-comparison schema and dedicated contract test are sdist-only, while ADR 0059 is repository-only. Packaging proves distribution contents, not source-system authenticity, signature/attestation, currency-specific period identity, or removal of direct Python legacy defaults.
- E-044 packaging boundary: client-pack runtime redaction, v1/v2 manifest writer/reader, and verifier are in wheel and sdist; the client-pack manifest schema and dedicated contract test are sdist-only, while ADR 0060 is repository-only. Packaging proves distribution contents, not redaction completeness, disclosure approval, source authenticity, signature/attestation, or removal of direct Python legacy defaults.
- E-045 packaging boundary: evidence-binder strict/legacy CSV ingress plus v2/v3 index writer/reader/verifier runtime are in wheel and sdist; the evidence-index schema and dedicated contract test are sdist-only, while ADR 0061 is repository-only. Packaging proves distribution contents, not stable source identity, upstream source authentication, evidence completeness, audit approval/opinion, signature/attestation, or removal of direct Python legacy defaults.
- E-047 packaging boundary: Security Architecture v2 YAML, its readable Markdown view, closed schema, and dedicated contract test are sdist-only; ADR 0062 is repository-only, and none is in the runtime wheel. Packaging proves distribution contents, not deployed control operation, secure configuration, independent assessment, compliance, certification, or production readiness.
- E-048 packaging boundary: module threat-model YAML, its readable Markdown view, closed schema, and dedicated contract test are sdist-only; ADR 0063 is repository-only, and none is in the runtime wheel. Packaging proves distribution contents, not that threats are mitigated in a deployment, controls operate continuously, a penetration test occurred, or the product is compliant/certified/production-ready.
- E-049 packaging boundary: scoped ASVS 5.0.0 YAML, its readable Markdown view, closed schema, and dedicated contract test are sdist-only; ADR 0064 is repository-only, and none is in the runtime wheel. Packaging proves distribution contents, not a full ASVS assessment/level, deployed control effectiveness, penetration testing, independent validation, compliance, certification, or production readiness.
- E-050 packaging boundary: final-source-pinned all-task SSDF 1.1 YAML, its readable Markdown view, closed schema, and dedicated contract test are sdist-only; ADR 0065 is repository-only, and none is in the runtime wheel. Packaging proves distribution contents, not organizational SSDF conformance, a continuously operating secure-development process, release integrity/provenance, independent validation, compliance, certification, or production readiness.
- E-051 packaging boundary: Approved-SLSA-1.2-pinned plan YAML, its readable Markdown view, closed schema, and dedicated contract test are sdist-only; ADR 0066 is repository-only, and none is in the runtime wheel. Packaging proves distribution contents, not a signed attestation, trusted builder/source-control assessment, independent verifier execution, SLSA level/property, release integrity, compliance, certification, or production readiness.
- E-052 packaging boundary: release-manifest schema, signed-candidate runbook, and dedicated contracts are sdist-only; workflow, hash-locked requirements, manifest/normalizer scripts, and ADR 0067 are repository-only, and none is in the runtime wheel. Packaging and bounded local byte parity prove neither a clean hosted run nor OCI/cross-platform reproducibility, signature, attestation, immutable publication, SLSA level/property, compliance, certification, or production readiness.
- E-053 packaging boundary: SBOM-manifest schema, updated signed-candidate runbook, and five dedicated contracts are sdist-only; integrated workflow, SBOM builder/normalizer, and ADR 0068 are repository-only, and none is in the runtime wheel. Packaging and deterministic clean-HEAD package/source SBOM bytes prove neither hosted image inventory, signed attestation, completeness, vulnerability/license assurance, immutable publication, SLSA level/property, compliance, certification, nor production readiness.
- E-054 packaging boundary: two supply-chain schemas, readable policy, normative policy/zero-exception registries, and 13 dedicated contracts are sdist-only; `uv.lock`, Gitleaks/Dependabot/Docker/workflow definitions, the fail-closed validator, and ADR 0069 are repository-only, and none is in the runtime wheel. Locked local resolution, a clean advisory response, and leak scans do not prove package safety/reachability/provenance, hosted enforcement, container contents, npm SRI completeness, compliance, certification, or production readiness.
- E-055 packaging boundary: `reconforge/io/ingress.py` and the direct `defusedxml>=0.7.1` dependency are in the runtime wheel/sdist; the file-ingestion schema, normative inventory, readable boundary, and two dedicated tests are sdist-only; ADR 0070 is repository-only. Package presence and local hostile fixtures prove neither malware absence, upload/connector safety, legacy XLS internal inspection, source authenticity, hosted enforcement, compliance, certification, nor production readiness.
- E-056 packaging boundary: `reconforge/io/structured.py`, the unique-key YAML loader extension, and migrated runtime call sites are in wheel/sdist; the updated file-ingestion schema/inventory/readable boundary and dedicated structured-ingress test are sdist-only; ADR 0071 is repository-only. Package presence and hostile local fixtures prove neither remaining parser coverage, malware absence, source/rule authenticity, semantic correctness, upload/connector safety, hosted enforcement, compliance, certification, nor production readiness.
- E-057 packaging boundary: migrated `reconforge/close_workflow.py` and the shared structured reader are in wheel/sdist; the updated file-ingestion/security/risk governance and dedicated close structured-ingress test are sdist-only; ADR 0072 is repository-only. Package presence and hostile local fixtures prove neither template authorship, task correctness, approval/sign-off, remaining parser coverage, malware absence, upload/connector safety, hosted enforcement, compliance, certification, nor production readiness.
- E-058 packaging boundary: migrated client-pack/evidence manifest readers and the shared structured reader are in wheel/sdist; updated file-ingestion/security/risk governance and the dedicated generated-manifest structured-ingress test are sdist-only; ADR 0073 is repository-only. Package presence and hostile local fixtures prove neither FI-012 completion, redaction/copy safety, source authenticity, disclosure approval, malware absence, remaining parser coverage, upload/connector safety, hosted enforcement, compliance, certification, nor production readiness.
- E-059 packaging boundary: exact-lexeme structured JSON and migrated client-pack JSON-redaction runtime are in wheel/sdist; updated file-ingestion/security/risk governance and the dedicated redaction-ingress test are sdist-only; ADR 0074 is repository-only. Package presence and hostile local fixtures prove neither FI-012 completion, CSV/text or non-redacted copy safety, complete client-pack output atomicity, redaction completeness, source authenticity, disclosure approval, malware absence, remaining parser coverage, upload/connector safety, hosted enforcement, compliance, certification, nor production readiness.
- E-060 packaging boundary: bounded client-pack streaming-CSV redaction runtime is in wheel/sdist; updated file-ingestion/security/risk governance and the dedicated CSV-redaction ingress test are sdist-only; ADR 0075 is repository-only. Package presence and hostile local fixtures prove neither FI-012 completion, text or non-redacted copy safety, full pack-level atomicity, redaction completeness, source authenticity, disclosure approval, malware absence, remaining parser coverage, upload/connector safety, hosted enforcement, compliance, certification, nor production readiness.
- E-061 packaging boundary: bounded FI-012 source traversal/text/non-redacted copy/output-recheck and sibling-staging runtime is in wheel/sdist; updated security/risk governance and the dedicated copy/publication test are sdist-only; ADR 0076 is repository-only. Package presence and hostile local fixtures prove neither crash-atomic existing-directory replacement, recovery after process/host loss, redaction completeness, source authenticity, disclosure approval, malware absence, remaining parser coverage, upload/connector safety, hosted enforcement, compliance, certification, nor production readiness.
- E-062 packaging boundary: explicit integrity-checked client-pack recovery runtime and CLI are in wheel/sdist; updated security/risk governance and the dedicated recovery test are sdist-only; ADR 0077 is repository-only. Package presence and simulated abrupt-loss fixtures prove neither authentication, observer/crash-atomic replacement, real process/host/filesystem-loss durability, redaction completeness, source authenticity, disclosure approval, malware absence, remaining parser coverage, upload/connector safety, hosted enforcement, compliance, certification, nor production readiness.
- E-063 packaging boundary: bounded database backup/manifest restore runtime is in wheel/sdist; both current-writer JSON schemas, updated security/risk governance, and the dedicated hostile/compatibility test are sdist-only; ADR 0078 is repository-only. Package presence and local fixtures prove neither authenticated provenance, encryption, centralized restore authorization, archive safety, malware absence, real process/host/filesystem-loss recovery, cross-edition DR, hosted enforcement, compliance, certification, nor production readiness.
- E-064 packaging boundary: bounded legacy DB import runtime is in wheel/sdist; both compatibility schemas, updated security/risk governance, and the dedicated hostile/compatibility test are sdist-only; ADR 0079 is repository-only. Package presence and local fixtures prove neither semantic completeness, authenticated provenance, centralized authorization, encryption, malware absence, real recovery/DR, hosted enforcement, compliance, certification, nor production readiness.
- E-065 packaging boundary: bounded exact-text business-record runtime and migrated consumers are in wheel/sdist; updated security/risk governance and the dedicated hostile/exactness test are sdist-only; ADR 0080 is repository-only. Package presence and local fixtures prove neither business-semantic completeness, source authentication, centralized authorization, classification, malware absence, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-066 packaging boundary: bounded generated-artifact runtime and migrated Studio consumers are in wheel/sdist; updated security/risk governance and the dedicated hostile/companion/display test are sdist-only; ADR 0081 is repository-only. Package presence and local fixtures prove neither cryptographic companion binding, source authentication, disclosure authorization, classification, malware absence, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-067 packaging boundary: explicit generated CSV representation plus migrated variance/management-report consumers are in wheel/sdist; updated security/risk governance and the dedicated hostile/exact-text/display test are sdist-only; ADR 0082 is repository-only. Package presence and local fixtures prove neither producer/schema authentication, disclosure authorization, classification, malware absence, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-068 packaging boundary: generated-document stability verification plus migrated evidence/review/cache/provenance/CLI runtime are in wheel/sdist; updated security/risk governance and the dedicated hostile/cache/provenance/CLI test are sdist-only; ADR 0083 is repository-only. Package presence and local fixtures prove neither review-state JSON safety, producer/schema authentication, disclosure authorization, classification, malware absence, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-069 packaging boundary: parameterized stable generated JSON runtime plus migrated review-state/CLI/Studio/DB consumers are in wheel/sdist; updated FI-014 security/risk governance and the dedicated hostile/compatibility/change/safe-error test are sdist-only; ADR 0084 is repository-only. Package presence and local fixtures prove neither producer/schema authentication, actor/workspace authorization, disclosure authorization, classification, malware absence, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-070 packaging boundary: explicit generated-JSON value/mode runtime plus six migrated filesystem consumers are in wheel/sdist; the exact AST inventory, FI-015/FI-016 governance, and dedicated compatibility/hostile/resource/change/safe-error test are sdist-only; ADR 0085 is repository-only. Package presence and local fixtures prove neither persisted-value schema/size safety, producer/schema authentication, actor/disclosure authorization, classification, malware absence, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-071 packaging boundary: the shared persisted-JSON runtime, fractional-token rejection option, and AP/AR consumers are in wheel/sdist; the recursive response schema, inventory policy, and dedicated hostile/rollback/replay test are sdist-only; ADR 0086 is repository-only. Package presence and local fixtures prove neither safety of the ten remaining FI-013 direct decoders, stored-row producer authentication, actor/disclosure authorization, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-072 packaging boundary: the shared audit-metadata runtime and SQLite/PostgreSQL/export consumers are in the 220-entry wheel/sdist; the recursive audit schema, inventory policy, and dedicated hostile/hash/resource/export test are sdist-only; ADR 0087 is repository-only. Package presence and local fixtures prove neither safety of the seven remaining FI-013 direct decoders, stored-row producer authenticity, live PostgreSQL behavior, actor/disclosure authorization, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-073 packaging boundary: the shared persisted-JSON runtime and PostgreSQL outbox/ledger/master-data/close/evidence/reconciliation consumers are in the wheel and sdist; the recursive outbox schema, inventory policy, and dedicated producer/consumer/AST test are sdist-only; ADR 0088 is repository-only. Package presence and simulated database rows prove neither safety of the six remaining FI-013 direct decoders, stored-row authenticity, live PostgreSQL or external publisher behavior, actor/disclosure authorization, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-074 packaging boundary: the shared persisted-JSON runtime and PostgreSQL reconciliation repository/worker consumers are in the 220-entry wheel and 465-entry sdist; the recursive reconciliation schema, inventory policy, and dedicated producer/consumer/fingerprint/rollback/AST test are sdist-only; ADR 0089 is repository-only. Package presence and simulated rows prove neither safety of the three remaining FI-013 direct decoders, stored-row authenticity, live PostgreSQL rollback/driver behavior, actor/disclosure authorization, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-075 packaging boundary: the shared persisted-JSON runtime and SQLite matching producer/replay/public-reader consumers are in the 220-entry wheel and 467-entry sdist; the recursive matching-rule schema, inventory policy, and dedicated producer/consumer/rollback/compatibility/AST test are sdist-only; ADR 0090 is repository-only. Package presence and local SQLite fixtures prove neither safety of the two remaining FI-013 direct decoders, stored-row authenticity, actor/disclosure authorization, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-076 packaging boundary: the shared persisted-JSON runtime and optional Redis session producer/consumer are in the 220-entry wheel and 469-entry sdist; the closed Redis-session schema, inventory policy, and dedicated producer/consumer/resource/tenant/TTL/AST test are sdist-only; ADR 0091 is repository-only. At that boundary generic export remained open and was later closed by E-077. Package presence and fake-client fixtures prove neither live Redis operation, login-lifecycle integration, stored-value authenticity, actor/disclosure authorization, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-077 packaging boundary: persisted JSON plus public export, legacy-summary producer, and matching-lineage producer runtime are in the 220-entry wheel and 472-entry sdist; both new schemas, inventory policy, and dedicated 15-case contract are sdist-only; ADR 0092 is repository-only. Package presence and local SQLite fixtures prove neither stored-row/source authenticity, actor/disclosure authorization, malware absence, crash-atomic multi-file publication, supported throughput, hosted enforcement, compliance, certification, nor production readiness.
- E-078 packaging boundary: staged publication and explicit recovery runtime are in the 220-entry wheel and 474-entry sdist; the additive database-export manifest schema and dedicated publication test are sdist-only, while ADR 0093 is repository-only. The wheel is 645,923 bytes (SHA-256 `f3951e00...fc89ba9`) and sdist is 909,191 bytes (`91782443...e93977`). This does not prove remote-filesystem semantics, authenticated provenance, centralized authorization, malware absence, host-loss durability, supported throughput, compliance, certification, or production readiness.
- Environment unavailable: Docker daemon; live PostgreSQL/Redis/object-storage verification not run locally.
- Remote CI observation (not current-worktree evidence): Draft PR #54 run `30073610042` at `45c6573` passed Python 3.11, Python 3.12, Docker parity, Docker build, security, and CodeQL, but failed `server-boundaries` before collection because referenced test files were absent. Local HEAD `bdf63de` is one unpushed commit ahead and adds those nine test files. No rerun or fix result is claimed.

## Active task

`P1-PLAT-001` is in progress. E-088 replaces the previously unused repository-protocol claim with one production-shaped application boundary: workspace plus initial period plus two audit events commit atomically through a typed unit of work, and failure rolls back business rows and the audit-chain head. The application layer imports neither SQLite nor infrastructure. Remaining platform services still coupled to `sqlite3.Connection` prevent task or Phase 1 closure.

Current E-088 gates: repository/application focus 13 passed; full Ruff passed; Mypy passed over 216 source files; full pytest collected 1,301 tests with 1,291 passed and ten live-service skips in 205.10s; wheel/sdist build passed and contains every new runtime module.

E-089 adds the normative Phase 1–3 execution matrix and the previously missing
Phase 3 enterprise/external-validation backlog. Four focused contract tests pass.
No Phase 3 implementation or external gate is complete; both external gates
remain `planned` with empty evidence-artifact lists.

E-090 measures the exact runtime migration gap: 17 Platform services are
`direct_sqlite`, three are `partial_repository`, and one Application service is
`backend_neutral`. Three AST contracts fail on omitted services, false
classification, or count drift. This keeps P1-PLAT-001 explicitly in progress.

E-091 moves operational diagnostics composition behind explicit Application
ports and leaves a SQL-free compatibility adapter for the current CLI. The
current inventory is 16 direct-SQLite Platform services, three partial
repositories, one compatibility adapter, and two backend-neutral Application
services. The full Python collection passes with 1,300 tests executed and ten
live-service skips; wheel and sdist builds pass. P1-PLAT-001 remains in progress.

E-092 starts P1-PLAT-003 with the pure seven-state durable-job aggregate,
backend-neutral application lifecycle, SQLite migration 21, atomic scoped
idempotency and optimistic transitions, immutable transition evidence,
monotonic checkpoints, completion manifests, and backup/restore/export proof.
The repository inventory now contains three backend-neutral Application
services. Generic workers/leases, PostgreSQL parity, authorization, and real
crash recovery remain open, so P1-PLAT-003 remains in progress and P1-PLAT-004
is not closed. The full collection passes with 1,323 tests executed and ten
live-service skips; wheel/sdist build and runtime-module membership pass.

E-093 closes P1-PLAT-003's local durable-state exit with generation-fenced
leases, atomic claim/heartbeat/takeover/release, worker-owned transitions, all
seven persisted state paths, and immutable lease evidence. A real connection
close/reopen retains the last committed checkpoint and rejects the old worker,
so P1-PLAT-004 is now in progress. It is not complete until an actual workload
proves no duplicate business effect across injected termination. The inventory
contains four backend-neutral Application services.
The full collection passes with 1,328 tests executed and ten live-service
skips; the wheel and sdist build pass.

E-094 closes P1-PLAT-004's local safe-workload exit: migration 23 binds each
immutable partition effect to its fenced checkpoint/final transition. Injected
failure rolls effect and progress back together. An uninterrupted run and a
connection-close/restarted run finish with the same two semantic effects and
manifest; restart enumerates and skips the already committed partition. This
does not cover external systems or host loss. The full collection passes with
1,332 tests executed and ten live-service skips; Ruff, mypy over 221 source
files, the 65-test compatibility focus, wheel/sdist build, and diff checks pass.

## Next exact actions

1. Migrate the next transactionally coherent Platform use case into the Application layer and reduce the E-090 coupling counts without exposing a database connection.
2. Add live PostgreSQL parity for the next stable Application repository boundary; durable-job parity is now established by E-095.
3. Keep the Phase 1–3 matrix closed as implementation changes; never substitute synthetic evidence for the two external Phase 3 gates.
E-095 advances P1-PLAT-002 with live PostgreSQL durable-job parity. Migration
0012, forced RLS, atomic concurrent idempotency, optimistic versions, SKIP
LOCKED claims, generation fencing, connection-loss takeover, immutable effects,
SQLite semantic parity, and forward/downgrade/re-upgrade are verified. A fresh
PostgreSQL 17 database passes all 119 PostgreSQL/server-identity contract tests.
P1-PLAT-002 remains in progress for the other supported repository boundaries.
The non-live full suite passes 1,333 tests with eleven live-service skips; Ruff,
mypy over 222 source files, build, and diff checks pass.

E-096 adds PostgreSQL parity for the workspace/initial-period unit of work.
The unchanged Application service now has SQLite and PostgreSQL adapters;
PostgreSQL live evidence covers one-transaction commit, no-commit rollback,
second-audit failure rollback, RLS isolation, immutable events, concurrent
chain serialization, verification, semantic parity, and migration rollback.
The clean PostgreSQL sweep passes 121 tests. Repository migration and parity
remain in progress for the direct-SQLite services in the measured inventory.
The non-live full suite passes 1,334 tests with twelve live-service skips;
Ruff, mypy over 224 source files, build, and diff checks pass. SQLite and
PostgreSQL now call the same pure canonical audit-hash function, preventing
adapter drift in the chain algorithm.

E-097 adds operational diagnostics parity. Deployment mode is adapter-owned,
so PostgreSQL is no longer mislabeled `local_only`; SQLite compatibility is
unchanged. Live RLS, record-shape/count, audit-health, real Alembic status, and
migration rollback pass. The clean PostgreSQL sweep now passes 123 tests.
The non-live full suite passes 1,336 tests with thirteen live-service skips;
Ruff, mypy over 225 source files, build, and diff checks pass.

E-098 closes P1-PLAT-005. The evidence registry now accepts a backend-neutral
immutable object contract implemented by local filesystem and S3-compatible
adapters. The non-live suite passes 1,343 tests with fifteen live/environment
skips; the live MinIO focus passes all object-store/evidence cases except the
Windows symlink-privilege branch. Ruff, mypy over 225 source files, lock check,
build, and diff checks pass. Local sidecars are bounded and fail closed, but
are neither keyed against a malicious local writer nor crash-atomic as a pair.

E-099 closes P1-PLAT-006's defined generic-request exit. One backend-neutral
Application service now reserves, completes, expires, and replays bounded
responses through SQLite and PostgreSQL adapters. The owner capability is
digest-only at rest; changed request bytes conflict; concurrent requests elect
one owner; expired records rebind; stale completion fails; completed binary
responses survive SQLite backup/restore; PostgreSQL uses forced tenant RLS.
The repository inventory now records five backend-neutral Application
services. HTTP middleware composition remains open and no exactly-once
transport claim is made.

E-100 closes P1-PLAT-007. A bounded, versioned HMAC cursor binds allowlisted
ordering and a stable ID tie-breaker to tenant/resource/filter context. The
local evidence API supports explicit cursor mode while retaining offset mode;
mutation, duplicate-key traversal, insert/delete movement, direction, scope,
and configuration failures are tested. Tokens are authenticated encodings,
not encryption. PostgreSQL cursor execution remains open and fails explicitly
until a native keyset query is implemented.

E-101 closes P1-PLAT-008. API dependencies, platform services, Studio, and
dynamic workflow transitions now enforce permission, supplied scope, and SoD
context through `CentralPolicyEngine`. Application construction inventories
all 156 API operations and fails on missing, ambiguous, duplicate, or stale
authorization classifications; the current canonical map digest is
`494c5a0d5cfe72a99b50737307099b8b901bc54e09d0fabbe063e164db043d40`.
Versioned structured decision records retain safe reason/surface/request data
and hash actor/permission identities. They are not a durable tamper-evident
authorization ledger.

E-102 closes P1-PLAT-009's code baseline. Optional OpenTelemetry 1.44.0
providers instrument normalized API routes and durable-job submit/transition/
claim operations; standard logs receive request/trace/span correlation. The
default runtime imports no SDK and exports nothing. A closed attribute policy
rejects floats, arbitrary keys, oversized values, and tenant/workspace/entity/
actor/record/amount/currency/path/job identifiers. Real in-memory SDK tests
inspect spans and metrics. Collector security, sampling, retention, alerts,
dashboards, and SLO operation remain unproven deployment gates.

E-103 starts P1-PLAT-010 with an optional AES-256-GCM envelope around the
existing versioned Community SQLite backup. Operator keys enter only through a
bounded local raw/hex key file; the envelope is authenticated before restore
target mutation and is published as one exclusive staged file. Round-trip,
dry-run, wrong-key, tamper, existing-target preservation, key contract, and CLI
tests pass. The then-current 113-package lock and supply-chain policy included
cryptography 49.0.0; E-350 refreshes the active lock to 50.0.0 after the hosted
advisory review. Temporary plaintext protection, key rotation/KMS, PostgreSQL backup,
centralized restore authorization, and the full edition/version rollback
matrix remain open; P1-PLAT-010 is in progress.

E-104 extends P1-PLAT-010 through a backend-neutral authorized Application
boundary and PostgreSQL native-tool adapter. Exact create/restore permissions
are checked before the adapter; absolute ordinary executables run without a
shell; libpq service names keep credentials out of argv; custom dumps stream
through AES-256-GCM; and restore creates a new database that is schema-verified
or automatically dropped on failure. Seven adapter cases and a closed matrix
contract pass. A live PostgreSQL 17 drill restored Alembic 0015 with all 41
ReconForge tables, rejected a truncated dump, removed its partial target, and
cleaned both drill databases. Enterprise HA, regulated air gap, KMS/key
rotation, host loss, scheduled retention, cross-version upgrades, and measured
RPO/RTO remain planned, so P1-PLAT-010 remains in progress.

E-105 closes P1-REC-001. A backend-neutral immutable `MatchingStrategy`
protocol, exact-version registry, and schema-validated published manifest bind
the current indexed one-to-one algorithm, supported modes, deterministic
tie-break, explanation schema, and conservative limits. The compatibility
adapter preserves current results and exceptions while adding manifest,
permutation-invariant input, and complete decision digests. Binary floats,
non-finite values, colliding field names, invalid tolerance/date windows, and
limit excess fail before matching. Candidate accounting, grouped matching,
ambiguity v2, and benchmark thresholds remain open under P1-REC-002 onward.

E-106 closes P1-REC-002. The indexed matcher now stores exact Decimal amounts
in stable currency/precision partitions and finds inclusive tolerance windows
with binary search instead of scanning and reparsing every amount bucket per
left record. Missing-currency compatibility and explicit currency rejection are
preserved. Synthetic boundary evidence uses a billion-position lazy sequence
with at most 64 indexed lookups; duplicate/lower/upper boundary cases and all
existing matching/property/strategy tests pass. Candidate count, timeout,
search, and partition budgets remain open under P1-REC-003.

E-107 closes P1-REC-003 with `indexed-candidate-budget-v1`. Stable indexed
candidates are counted before scoring; more than 10,000 for one left record or
more than 1,000,000 evaluations in one run yields an explicit Ambiguous result
and matching-ambiguity exception, never a truncated partial match. Evidence
records the observed count, published ceilings, index inclusion basis, and
exclusion reason. Stable left identity makes total-budget behavior invariant to
row permutation. The deterministic search budget governs business output;
infrastructure wall-clock watchdogs may be added later without authorizing a
partial financial decision.

E-108 closes P1-REC-004 with the separate experimental
`bounded-grouped-subset-sum@1.0.0` strategy. Its pure domain and application
boundaries implement true one-to-many, many-to-one, and many-to-many exact-
Decimal group sums under common currency, partition, date, cardinality, and
search constraints. Selection and digests are invariant to input order; a
25,000-evaluation ceiling fails closed. The legacy CLI pair-capacity flags are
unchanged and are explicitly not presented as true grouped sums.

E-109 closes P1-REC-005. The grouped matcher is now fee-aware and explicit about
netting mode at domain, application, and strategy levels:

- `GroupedMatchPolicy.netting_mode` supports `gross` and `net`.
- Record-level fees are first-class and are validated as non-negative finite `Decimal`.
- Gross mode preserves prior behavior while `net` mode compares gross minus fee, with explicit fee fields and net totals emitted for grouped outputs.
- Strategy requests now carry `netting_mode`, `left_fee_field`, and `right_fee_field`; `net` mode requires both fee field names and is rejected in request validation when missing.
- Decision payloads now expose fee/totals and net totals for traceable group outcomes.

A focused slice run passed the new grouped matching/domain/application/strategy suite (27/27).

E-110 closes P1-REC-006. Grouped matching is now FX-aware with deterministic
currency conversion under explicit target-currency mode:

- `MatchingStrategyRequest` and `GroupedMatchRequest` support `target_currency`
  and `fx_rates`.
- Rate profiles are parsed with explicit `base_currency`, `quote_currency`, `rate`,
  `source`, `rate_type`, and canonical `effective_at`.
- Conversion is deterministic: same inputs under the same policy pick the latest
  valid rate by effective date with stable source/type/rate tie-breakers; missing
  reverse pairs are derived through safe inversion of inverse pairs.
- Conversion failures due to absent rates remain hard-fail and fail-closed, with
  no silent local currency truncation.
- Slice E-110 added/expanded application and strategy tests for direct conversion,
  inversion, and cross-currency failure behavior.

E-111 closes P1-REC-007. Equal-optimum grouped results are now explicit
`ambiguous` outcomes rather than arbitrary ties:

- `find_grouped_match` now detects multiple bounded groups with identical best
  `difference`, `group-size`, and `date-span` and returns `GROUP_MATCH_AMBIGUOUS`.
- `GroupedMatchDecision` carries `ambiguous_candidate_sets` for exact governance
  review.
- Ambiguity remains fail-closed: no row is selected without policy guidance, and
  budget overflow preserves existing `GROUP_SEARCH_BUDGET_EXCEEDED` behavior.
- Focused grouped domain, application, and strategy tests confirm the exact tie
  resolution sequence.

E-112 closes P1-REC-008. Grouped decision explainability now has `grouped-matching-explanation-v2`:

- Strategy manifest now publishes `grouped-matching-explanation-v2`.
- Grouped results expose ambiguous candidate sets for traceable, reviewer-facing
  explanations.
- The architectural strategy registry and runtime manifest are aligned to the v2
  explanation identity.

E-113 closes P1-REC-009. Reproducible reconciliation benchmark tiers now exist
for 10K and 100K synthetic profile outputs:

- `run_reconciliation_execution_benchmark_suite` executes profile-based runs and
  writes a suite manifest with per-profile SHA-256/digest and metadata.
- 10K and 100K outputs are retained as version-controlled evidence at
  `docs/execution/benchmarks/phase2/10k/reconciliation-execution.json`
  and
  `docs/execution/benchmarks/phase2/100k/reconciliation-execution.json`.
- Suite signature:
  `ae0fd0bae04630491c25d0dc9756121ae9e9a457b0ebfab94fdcdba6b659e59e`.
- Environment for these runs is a closed Windows 11 local boundary:
  `Python 3.14.6`, 16 CPU cores, `AMD64` platform metadata, and UTC timestamps
  in each payload.

E-114 closes P1-REC-010. Deterministic regression assertions now guard
benchmarks before acceptance:

- `assert_reconciliation_execution_regression` compares baseline/candidate by
  profile and verifies result counts, matched/exception rows, candidate count
  invariants, and bounded runtime/CPU/memory growth.
- Signature changes and major wall-clock/CPU regressions are now explicit failure
  conditions (unless `allow_signature_change=True` is deliberately set).
- Reproducible gate coverage is encoded in the generator benchmark test suite with
  mutated-baseline negative checks.
## E-115: Evidence Graph v1 manifest integrity and redaction

P2-001 is now implemented and tested:

- Added versioned `reconforge-evidence-graph` envelope + schema `1.0` with node/edge metadata in `reconforge/evidence/graph.py`.
- Added manifest-hash tamper verification and deterministic hashing over full node/edge payload context.
- Added node data-classification, retention policy, and redaction-mask support with redacted payload export.
- Added `docs/schemas/evidence_graph.schema.json` and validation in `tests/test_phase2_deliverables.py` (schema/tamper/redaction).

Runtime evidence command set used:

- `python -m pytest tests/test_phase2_deliverables.py`
- `python -m pytest tests/test_workflow_schemas.py`

This satisfies E-115 while keeping P2-002 (drill-down API and evidence retrieval) open.

## E-116: Metrics Service backend-neutral migration

P1-PLAT-001 advances further with the migration of `MetricsService`.
- Replaced the direct SQLite dependency in API routes with a backend-neutral `MetricsApplicationService`.
- Extracted infrastructure to `SQLiteMetricsRepository` and `PostgresMetricsRepository`.
- `PostgresMetricsRepository` includes tenant boundary awareness with RLS schemas and explicit role grants.
- API route injection is dynamic depending on Server mode, governed by `server_metrics_enabled` and `execute_postgres_metrics`.
- The historical connection-based API for `MetricsService` has been preserved as a compatibility adapter in `reconforge/platform/metrics.py`.
- Metrics are now tested across live PostgreSQL and SQLite for feature parity.
- The `REPOSITORY_BOUNDARY_INVENTORY.yaml` now reflects 9 backend-neutral application services (including the existing Outbox application boundary) and 15 direct-SQLite platform services, continuing to reduce direct-SQLite coupling.

## E-117: Authorized bounded Evidence Graph drill-down

P2-002 is closed for the current SQLite and tenant-scoped PostgreSQL contracts.
The `/api/v1/evidence/records/{evidence_id}/drill-down` route now has an
authorization-inventory identity, validates direction/depth/page inputs, masks
provenance by default, and requires `evidence.manage` before sensitive metadata
is returned. Both repositories enforce an eight-level depth ceiling, a
10,000-node graph ceiling, deterministic node/edge ordering, 1,000-node maximum
pages, and explicit incident-edge pagination semantics. Successful reads append
audit-chain events; read events do not publish business outbox messages.

## E-118: Reconciliation-as-Code v1 contract and rollback

P2-003 is closed by the packaged
`docs/schemas/reconciliation_as_code.schema.json` and the strict
`ReconciliationAsCodeSpec`. Bounded duplicate-safe YAML/JSON readers preserve
exact financial lexemes; executable hook keys and binary/scientific tolerance
values fail closed. Canonical documents produce stable SHA-256 manifests,
support the historical `normalization_rules` reader, contain typed sources,
policies, strategies, evidence requirements and synthetic golden cases, and can
atomically restore a previously validated YAML/JSON contract with explicit
overwrite authorization.

## E-119: Deterministic Reconciliation-as-Code operator tooling

P2-004 is closed for `matching-adapter-only-v1`. The CLI exposes `validate`,
`lint`, `test`, `diff`, `simulate`, `explain`, and `rollback` beneath
`rules recon-as-code`. Embedded synthetic fixtures execute through the existing
versioned indexed one-to-one or bounded grouped adapter and compare exact result
counts plus optional decision digests. Simulation emits a no-side-effect plan;
declarative validation/normalization steps remain data-only until separately
registered runtime adapters are implemented and tested.

Final local evidence on 2026-07-28: the full 1,450-test collection completed at
100% with no failures; Ruff passed repository-wide, mypy passed 245 source
files, focused Bandit returned no findings, `pip-audit` reported no known
third-party vulnerabilities while explicitly skipping the unpublished local
distribution, `git diff --check` passed, and the wheel/sdist build succeeded at
740,659 and 1,043,462 bytes. These gates close P2-002 through P2-004 only; they
do not close the complete Phase 1-3 objective or authorize publication.

E-120 advances the Phase 1 repository boundary: PostgreSQL outbox delivery now
adapts to the same backend-neutral application contract through a validated,
single-tenant binding. The focused 15-test contract set passes; the full suite
reaches 100% with exit code 0, Ruff passes repository-wide, mypy passes all 245
source files, and diff-check passes with only the existing MANIFEST.in line-ending
warning. The Platform inventory now records 14 direct-SQLite services,
three SQL-free compatibility adapters, and nine backend-neutral application
services. P1-PLAT-001 and P1-PLAT-002 remain in progress because broader service
migration and live PostgreSQL parity are not yet complete. No publication is
authorized.

E-121 advances P1-PLAT-001 by extracting the unified exception queue into a
typed application port plus SQLite infrastructure repository. Existing callers
retain the same connection-based compatibility facade. The focused 18-test set
and full suite pass to 100% with exit code 0; repository-wide Ruff passes, mypy
passes 247 source files, and diff-check passes. The boundary inventory contains 13
direct-SQLite services, four compatibility adapters, and ten backend-neutral
application services. PostgreSQL parity is still missing, so P1-PLAT-001/002 and
the Phase 1-3 objective remain open; publication remains prohibited.

E-122 extracts approval/certification persistence behind a typed application
port and preserves the historical facade. The security AST inventory now
follows the actual SQLite SoD guard after extraction. Twenty-two focused tests
and the full suite pass to 100% with exit code 0; the 14-test security-document
and inventory focus passes, Ruff passes, mypy passes 249 source files, and
diff-check passes. The boundary inventory now contains 12 direct-SQLite
services, five compatibility adapters, and eleven backend-neutral application
services. PostgreSQL approval parity is absent; the Phase 1-3 goal remains open
and publication remains prohibited.

E-123 closes P2-005 for a bounded browser-local Mapping Studio foundation. The
new route preserves CSV/TSV text, enforces resource and shape ceilings, requires
explicit canonical mappings, rejects duplicate mappings and invalid amount/
currency/calendar values, and keeps missing financial values visible instead of
zero-filling. TypeScript, 24 UI tests, the production build, and all three
Chromium E2E paths pass after installing the exact Playwright browser dependency.
The full Python suite also passes to 100% with exit code 0; Ruff, 249-file mypy,
and the production npm audit (zero reported vulnerabilities) pass.
No mapping persistence, approval, ingestion, upload, or publication is claimed.
The Phase 1-3 objective remains open and publication remains prohibited.

E-124 closes P2-006 for a local non-publishing Rule Studio foundation. Drafts
move through tested and approved states only when bounded exact synthetic cases
pass and a different human reviewer supplies a reason; canonical SHA-256 binds
approval to the tested rule, edits revoke evidence, and new versions reset to
draft. Thirty UI tests, production build, npm audit, and four Chromium E2E paths
pass. Routine screenshots now stay in memory unless an explicit documentation-
update environment flag is set, removing the observed Windows lock flake. The
full Python suite passes to 100% with exit code 0; Ruff and 249-file mypy also
pass. No
durable draft, authenticated approval, signature, server execution, or publish
path is claimed. The overall Phase 1-3 objective remains open.

E-125 closes P2-007 for an authorized live read-only Studio contract. The
additive `/live` route calls only the existing same-origin
`/api/v1/metrics/dashboard` endpoint, whose backend requires `metrics.read`.
The browser rejects malformed or expanded envelopes, preserves exact metric
text, reports freshness, and distinguishes loading, empty, stale, ready,
authentication, permission, server, and retry states. A failed live request
never loads a synthetic artifact. Forty-two UI tests, the production build,
and five Chromium E2E paths pass. This does not establish deployed session
authentication, live PostgreSQL behavior, source authenticity, or production
readiness. The Phase 1-3 objective remains open and publication is prohibited.

E-126 closes P2-008 with an executable accessibility/localization regression
gate. Axe-core validates WCAG 2 A/AA and WCAG 2.1 A/AA rules on all seven
native routes in English and Arabic/RTL, plus mobile landmarks in both
languages. Chromium also proves skip-link focus, command-dialog focus
wrapping and trigger restoration, retained minimum focus visibility, high-
contrast/color-safe/reduced-motion state, and absence of exposed filesystem
paths/raw-record attributes in Evidence. The implementation corrects invalid
chart ARIA, mobile search naming, and AA contrast tokens. Forty-two UI tests,
build, ten Chromium E2E
paths, and the production npm audit pass. This automated evidence is not a
manual screen-reader, cognitive, zoom/reflow, or independent WCAG conformance
assessment. The Phase 1-3 objective remains open and publication is prohibited.

E-127 advances P1-PLAT-001 by extracting deterministic journal controls behind
a typed, connection-free application port and a SQLite infrastructure adapter.
The historical `JournalControlService(connection)` and `JournalImportResult`
imports remain compatible for CLI and enterprise-demo callers. Exact Decimal
text, policy codes, exception queue effects, audit/outbox metadata, ordering,
and report shapes are preserved. Import and policy mutations now explicitly
roll back on handled failures; a forced audit failure proves no journal or
outbox residue. Twenty focused tests pass. The boundary inventory now records
11 direct-SQLite services, six compatibility adapters, and 12 backend-neutral
application services. PostgreSQL journal parity is absent, so P1-PLAT-001/002
and the Phase 1-3 objective remain open; publication remains prohibited.

E-128 advances P1-PLAT-001 by extracting control-library import, test planning,
result recording, remediation, reporting, and plan reads behind a complete typed
application port and SQLite adapter. The historical connection facade and
result import remain compatible. The extraction exposed and fixed a workspace-
scope defect: an ineffective result now creates its unified exception in the
workspace stored on the test plan, not always `default`. A non-default workspace
test proves the boundary, while forced audit failure proves result, plan-status,
exception, and audit effects roll back together. Twenty-two focused tests pass.
The inventory now records 10 direct-SQLite services, seven compatibility
adapters, and 13 backend-neutral application services. PostgreSQL control-
testing parity is absent; P1-PLAT-001/002 and the Phase 1-3 objective remain
open, and publication remains prohibited.

E-129 advances P1-PLAT-002 with a complete tenant-bound PostgreSQL adapter for
the journal application contract and Alembic migration 0016. SQLite and
PostgreSQL now call one pure deterministic policy evaluator; the server adapter
stores exact NUMERIC plus canonical decimal text and writes tenant-scoped
journal/control exceptions, the domain audit hash chain, and transactional
outbox inside one transaction. RLS is forced on all three new tables. Local
schema, missing-workspace rollback, exact-policy, migration-registry, SQLite
compatibility, and optional-live test definitions pass. No PostgreSQL DSN or
non-superuser application role is configured locally, so the live RLS/parity
test is skipped and P1-PLAT-002 remains in progress. The full Python suite,
repository Ruff, 256-file mypy, focused Bandit, build, artifact-membership
inspection, and diff check pass. The build gate exposed and fixed missing
Alembic assets in distributions; both artifacts now contain migration 0016.
Publication is prohibited.

E-141 advances P1-PLAT-001 by extracting all six file execution, benchmark,
job/result read, and pure record-matching use cases behind a typed Application
port and SQLite adapter. The historical constructor, public immutable types,
identity-policy constant, CLI/demo/worker/Reconciliation-as-Code callers,
private range-index test imports, and connection read seam remain compatible
through a SQL-free facade. Exact financial input, Decimal tolerance, record
identity, normalization, indexed candidate budgets, deterministic tie-breaking,
ambiguity, lineage, persisted rules, jobs/results, audit, outbox, and rollback
regressions remain executable. Inventory is now zero direct-SQLite services,
three partial repositories, 17 compatibility adapters, and 23 backend-neutral
Application services. P1-PLAT-001 remains open until the three partial
inventory boundaries are complete; PostgreSQL matching execution parity and
the overall Phase 1-3 objective remain open. Publication is prohibited.

E-130 advances P1-PLAT-002 with migration 0017 and a complete tenant-bound
PostgreSQL adapter for the control-testing application port. Four additive
tables force RLS; all seven use cases keep tenant predicates explicit, and
mutations commit their control state, correctly scoped unified exception,
domain audit-chain event, and outbox event together. Schema, missing-workspace
rollback, post-write Outbox-failure rollback, application, migration-registry,
SQLite compatibility, repository
Ruff/mypy, focused Bandit, full Python regression, build, artifact membership,
and diff checks pass. The build audit also fixed the missing importable
`reconforge_migration_sql` loader; an isolated wheel installation imports
migration 0017 and resolves its schema SQL. The optional live test defines non-superuser RLS,
cross-tenant isolation, SQLite report parity, workspace exception scope, and
audit/outbox assertions but is skipped because no PostgreSQL DSN/application
role is configured. The repository-wide Bandit command still reports seven
pre-existing medium B608 findings in static durable-job SQL construction;
these were not concealed or attributed to E-130. P1-PLAT-002 and the overall
Phase 1-3 objective remain open. Publication is prohibited.

E-131 restores the repository-wide Bandit gate after E-130 exposed seven B608
findings in durable-job SQL composition. Review confirms every interpolated
identifier comes exclusively from the immutable module-level `_JOB_COLUMNS`
tuple while all row values and scope values remain driver-parameterized. Seven
narrow expression-level B608 annotations retain visible manual-review notices;
no global rule or file is excluded. Bandit now exits zero with no findings,
the focused SQLite/PostgreSQL durable-job suite passes with one declared live
service skip, repository Ruff passes, and mypy checks 256 files. The existing
backup identifier suppression and these seven sites remain explicit review
points. No runtime behavior or schema changed. Publication remains prohibited.

E-132 advances P1-PLAT-001 by extracting all intercompany import, match,
settlement, and case-read behavior behind a complete typed application port and
SQLite infrastructure adapter. The historical connection constructor and
result import remain compatible. Exact Decimal parsing and canonical decimal
text are preserved; transaction IDs now complete the stable matching order.
Import, matching case/exception/outbox/audit effects, and settlement explicitly
roll back on handled failure. The extraction also fixes an orphan-evidence bug:
settling a missing case now fails before audit/outbox insertion. Twenty-nine
focused tests and the full Python suite pass; repository Ruff, 258-file mypy,
Bandit, build, artifact membership, and diff checks pass. Inventory is now nine
direct-SQLite services, eight compatibility adapters, and 14 backend-neutral
application services. PostgreSQL intercompany parity is absent, so
P1-PLAT-001/002 and the Phase 1-3 objective remain open. Publication is
prohibited.

E-149 starts the financial-critical PostgreSQL Payables boundary. Migration
0021 defines the complete nine-table aggregate with tenant-qualified parent
links, forced RLS, BIGINT minor-unit money, bounded exact quantities plus
canonical text, lifecycle checks, and JSONB idempotency responses. The adapter
implements supplier upsert/get/list with active currency and workspace scope,
transaction-local tenant context, audit/outbox atomicity, deterministic IDs,
and safe rollback. Focused schema, migration, tenant-read, missing-workspace,
Alembic, and parity-inventory tests pass with one declared live-service skip.
Twelve of fifteen methods remain, so Payables stays `absent`, P1-PLAT-002 stays
open, and publication remains prohibited.

E-149 next implements the complete purchase-order and receipt vertical slices.
Nine of fifteen port signatures now match exactly: supplier upsert/get/list;
purchase-order create/submit/approve/get; and receipt post/get. Purchase-order
lines preserve arbitrary exact decimal scale through PostgreSQL `NUMERIC` plus
canonical text rather than introducing a breaking `(38,12)` typmod. Supplier
currency equality, active masters, deterministic IDs, bounded lines, workspace
and branch scope, idempotency, optimistic versions, maker-checker approval,
over-receipt prevention, audit/outbox, and rollback are explicit. Six invoice
and three-way-match methods remain, so Payables remains `absent` and no
publication is allowed.

E-149 is completed at `live_test_available` maturity. All fifteen Payables port
signatures now match exactly across supplier, purchase-order, receipt,
supplier-invoice, deterministic three-way-match, approval, and read behavior.
Migration 0021 owns nine tenant-keyed forced-RLS tables. BIGINT minor-unit
money, arbitrary exact NUMERIC quantities plus canonical text, active currency
and scope validation, deterministic IDs, bounded lines, idempotency, optimistic
versions, maker-checker, cumulative over-receipt prevention, total equality,
HALF_UP variance conversion, unified control exceptions, audit/outbox, and
rollback are explicit. The optional non-superuser test covers the entire
lifecycle, 13-decimal-place quantities, self-approval refusal, and cross-tenant
invisibility but skips without a configured DSN/role. The inventory advances
to 0 current-live, 12 live-test-available, 2 contract-only, 11 absent, and 1
not-applicable. Publication remains prohibited.

E-148 starts the Matching persistence-boundary extraction without claiming a
PostgreSQL adapter. Currency precision is now resolved through the typed
Application `CurrencyPrecisionResolver` port. The SQLite repository supplies
the compatibility resolver by default, while pure `match_records` callers may
inject a database-independent registry. Trace-backed tests prove an injected
three-decimal KWD match performs no `currencies` query and preserves explicit
`UNKNOWN_CURRENCY` data-quality exceptions. The deterministic algorithm is
still physically interleaved with SQLite job/result persistence, so engine
extraction, output/digest/permutation parity, and PostgreSQL reconciliation
binding remain open. Publication remains prohibited.

E-148 now completes the persistence-independent engine extraction and hosted
worker binding. `DeterministicMatchingEngine` lives under reconciliation,
imports neither SQLite nor Infrastructure, and receives typed currency and
candidate-budget policy. SQLite delegates its pure calculation path while
retaining local jobs/results/evidence. The PostgreSQL reconciliation worker no
longer creates an in-memory SQLite database or runs local migrations; it calls
the same engine and retains PostgreSQL-owned inputs, checkpoints, results,
exceptions, audit, and outbox. The broad matching plus PostgreSQL worker suite
passes with one declared service skip. The full six-method PostgreSQL Matching
Application repository and a current live PostgreSQL run remain open, so
P1-PLAT-002 and the overall Phase 1-3 objective are not complete. Publication
remains prohibited.

Locked E-148 completion gates pass: repository Ruff; mypy across 289 source
files; Bandit with no findings and declared review warnings visible; the full
Python suite reaches 100% with the existing environment-dependent skips and
seven warning summaries; wheel and sdist build successfully and both contain
the new deterministic engine; BACKLOG YAML parses; and `git diff --check`
passes with line-ending warnings only. No publication action occurred.

E-147 is completed at `live_test_available` maturity. The next integrity-critical Matching parity boundary was
inspected first: its six-method Application port hides a large deterministic
engine physically interleaved with SQLite persistence and live currency lookup.
A wrapper or inheritance facade would preserve hidden SQLite coupling, so that
work is retained as a dedicated extraction plus digest/permutation slice rather
than falsely classified as PostgreSQL parity. The shared Master Data dependency
is being completed first. Migration 0020 adds optional workspace scope to the
existing organization and fiscal-period sources of truth plus two forced-RLS
ownership link tables; it does not duplicate financial masters. A complete
thirteen-method tenant-bound Application adapter now exists with workspace-
scoped organization/entity/branch/period reads, period-overlap locking,
pagination, bounded snapshots, and transactional evidence. Sixteen focused
tests pass; three declared live PostgreSQL tests skip without a service. The
optional non-superuser test covers two workspaces, cross-workspace same-name
periods, scoped summaries, evidence, and tenant isolation. The inventory is now
0 current-live, 11 live-test-available, 2 contract-only, 12 absent, and 1
not-applicable. Locked gates pass: Ruff, mypy across 288 source files, Bandit
with no findings, 1520 tests passed with 22 declared environment skips, wheel
and sdist builds including migration 0020, parity/Alembic tests, and
`git diff --check` with line-ending warnings only. Publication remains
prohibited.

E-133 advances P1-PLAT-002 with migration 0018 and a complete tenant-bound
PostgreSQL adapter for the five-use-case intercompany application contract.
Transactions and imbalance cases use exact NUMERIC plus canonical decimal text;
both new tables force RLS and use composite tenant/workspace keys. Import,
matching case/exception, settlement, domain audit, and outbox effects share
explicit transactions. Local tests prove float rejection before a transaction,
missing-workspace rollback before insertion, rollback of three inserted rows
when Outbox fails, and no audit/outbox effects for a missing settlement case.
Focused contracts, full Python regression, Ruff, 261-file mypy, focused Bandit,
build, artifact membership, and diff checks pass. Optional live coverage defines
SQLite semantic parity, exact case values, exception scope, non-superuser RLS,
and cross-tenant isolation, but is skipped without configured PostgreSQL
credentials and application role. P1-PLAT-002 and the overall Phase 1-3 goal
remain open. Publication is prohibited.

E-135 advances P1-PLAT-001 by extracting the 11-use-case account reconciliation
surface behind a typed application port and SQLite adapter. Exact balances and
materiality text, workflow/SoD transitions, roll-forward, audit/outbox effects,
CLI behavior, and backup/restore remain compatible. A forced-audit submit test
proves the business record, workflow object, and outbox all remain Prepared/
unchanged. Twenty-nine focused tests pass. Direct-SQLite services fall to seven;
PostgreSQL account parity is absent. Publication is prohibited.

E-136 advances P1-PLAT-001 by extracting all eight evidence registry use cases
behind a typed application port and SQLite adapter. Storage constants, checksum
verification result, local and S3-compatible providers, API/CLI/Studio callers,
retention metadata, redacted drill-down, and output shapes remain compatible.
Linked registration no longer commits link evidence separately: a forced second
audit failure proves registry, link, audit, and outbox tables all remain empty.
Thirty-five focused tests and the full Python suite pass; Ruff, 265-file mypy,
Bandit, build, artifact membership, and diff checks pass. Inventory is now six
direct-SQLite services, 11 compatibility adapters, and 17 backend-neutral
application services. PostgreSQL evidence convergence and the overall Phase 1-3
objective remain open. Publication is prohibited.

E-134 advances P1-PLAT-001 by moving all 11 local close-management methods
behind a typed, connection-free application port and SQLite adapter. The
historical constructor and `CloseReadiness` import remain compatible. Exact
Decimal readiness and dependency completion rules are preserved. The adapter
now rejects self and transitive task-dependency cycles, and reopening a missing
period fails before audit insertion rather than committing orphan evidence.
Twenty-five focused contract/readiness/dependency/atomicity/inventory tests and
the refreshed full Python suite pass. Repository Ruff, 261-file mypy, Bandit,
build, artifact membership, and diff checks pass. Inventory is now eight
direct-SQLite services, nine compatibility adapters, and 15 backend-neutral
application services. The existing PostgreSQL close repository is a separate
contract and has not yet converged, so P1-PLAT-001/002 and the Phase 1-3 goal
remain open. Publication is prohibited.

E-137 advances P1-PLAT-001 by extracting all 18 finance-core chart, account,
dimension, journal, entry-lifecycle, trial-balance, summary, and snapshot use
cases behind a typed Application port and SQLite adapter. The historical
constructor, constants, summary type, and atomic integrity-test seam remain
compatible through a SQL-free Platform facade. Exact financial line text and
governance context cross the port unchanged; the existing balance, precision,
period, dimension, SoD, immutable validation, database-lock, audit/outbox, and
rollback regressions remain executable. Inventory is now four direct-SQLite
services, three partial repositories, 13 compatibility adapters, and 19
backend-neutral Application services. PostgreSQL finance-core parity and the
overall Phase 1-3 objective remain open. Publication is prohibited.

E-138 advances P1-PLAT-001 by extracting all 19 inventory-core master,
movement, balance, control, summary, and snapshot use cases behind a typed
Application port and SQLite adapter. The historical constructor, constants,
summary type, API/CLI/planning/valuation paths, and connection/balance/integrity
fault-injection seams remain compatible through a SQL-free facade. Exact
quantity text and governance context cross the port unchanged; scaled-integer
quantity, lot/serial, period, location, negative-stock, posting/void,
error-redaction, locking, audit/outbox, and rollback regressions remain
executable. Inventory is now three direct-SQLite services, three partial
repositories, 14 compatibility adapters, and 20 backend-neutral Application
services. PostgreSQL inventory parity and the overall Phase 1-3 objective
remain open. Publication is prohibited.

E-139 advances P1-PLAT-001 by extracting all 15 supplier, purchase-order,
receipt, supplier-invoice, lifecycle, three-way-match, and read use cases behind
a typed Application port and SQLite adapter. The historical constructor and
public immutable line/result types remain compatible through a SQL-free
Platform facade. Integer minor units, canonical quantity text, currency,
idempotency, optimistic row versions, maker/checker, deterministic match,
exception, audit, and outbox behavior remain executable. Fault injection and
approval-surface governance now inspect the adapter that owns the transaction
and guard. Inventory is now two direct-SQLite services, three partial
repositories, 15 compatibility adapters, and 21 backend-neutral Application
services. PostgreSQL payables parity and the overall Phase 1-3 objective remain
open. Publication is prohibited.

E-140 advances P1-PLAT-001 by extracting all 13 customer, invoice, receipt,
allocation, exposure, aging, lifecycle, and read use cases behind a typed
Application port and SQLite adapter. The historical constructor and immutable
line/allocation inputs remain compatible through a SQL-free facade. Integer
minor units, canonical quantity text, currency, credit limits/holds/overrides,
idempotency, optimistic versions, maker/checker, allocation, deterministic
aging, audit, outbox, and rollback behavior remain executable. Approval and
persisted-JSON inventories now inspect the adapter that owns those effects.
Inventory is now one direct-SQLite service, three partial repositories, 16
compatibility adapters, and 22 backend-neutral Application services.
PostgreSQL receivables parity and the overall Phase 1-3 objective remain open.
Publication is prohibited.

E-142 advances P1-PLAT-001 by extracting all eleven inventory-valuation policy,
document, approval, cost-layer, summary, and snapshot use cases behind a typed
Application port and SQLite adapter. The historical constructor, constants,
summary and repository imports, API/CLI, reversal dependency, backup, and
fault-injection seams remain compatible through SQL-free facades. Integer minor
units, scaled quantities, FIFO ordering, deterministic half-even allocation,
maker-checker, balanced Finance drafts, audit/outbox, and rollback behavior
remain executable. Boundary inventory is now zero direct-SQLite services, two
partial repositories, eighteen compatibility adapters, and twenty-four
backend-neutral Application services. PostgreSQL valuation parity and the
overall Phase 1-3 objective remain open. Publication is prohibited.

E-143 advances P1-PLAT-001 by extracting all seven inventory-valuation reversal
use cases behind a typed Application port and SQLite adapter. Exact minor units,
original-document lineage, opposite-movement validation, cost-layer effects,
balanced reversing Finance drafts, maker-checker, audit/outbox, API/CLI/backup,
and rollback behavior remain executable through compatible facades. Inventory
is now zero direct-SQLite, one partial repository, nineteen compatibility
adapters, and twenty-five backend-neutral Application services. Inventory
planning is the final partial boundary; PostgreSQL parity and the Phase 1-3
objective remain open. Publication is prohibited.

E-144 completes the measured SQLite repository-contract extraction by moving all
thirteen inventory count, adjustment, reorder, summary, and snapshot use cases
behind a typed Application port and SQLite adapter. Exact quantity text,
count lifecycle, maker-checker, adjustment movements, deterministic reorder
signals, API/CLI/backup, audit/outbox, and rollback remain executable. The
inventory is now zero direct-SQLite, zero partial repositories, twenty
compatibility adapters, and twenty-six backend-neutral Application services.
Locked full-repository, build, artifact-membership, and diff gates pass, so
P1-PLAT-001 is completed. PostgreSQL parity and the Phase 1-3 objective remain
open. Publication is prohibited.

E-145 makes P1-PLAT-002 measurable across all twenty-six Application services.
The exact tested inventory records zero currently live-verified boundaries in
this environment, nine with live tests available, two contract-only adapters,
fourteen absent adapters, and one database-independent strategy. No PostgreSQL
DSN is configured, so skipped live tests are not promoted to passes. Existing
PostgreSQL ledger/master-data APIs do not implement the current Finance Core
port; that financial-critical boundary is selected next. Publication remains
prohibited.

E-146 is completed at `live_test_available` maturity. Migration 0019 and the additive PostgreSQL Finance Core
schema define eight tenant-keyed tables for charts, accounts, dimensions,
journals, draft/validated/voided entries, exact minor-unit lines, and line
dimensions. The tenant-bound adapter implements all eighteen Application port
methods. Draft replacement, exact currency precision, active/same-scope master
references, required dimensions, non-zero balance, maker-checker validation,
immutable validated lines, explicit voiding, trial balance, snapshot, tenant
RLS, and atomic audit/outbox effects are explicit. Fifteen focused inventory,
schema, signature, and guard tests pass; one live non-superuser lifecycle/RLS
test is available but skipped because this environment has no configured
PostgreSQL DSN. The parity inventory therefore advances only from `absent` to
`live_test_available` (0 current-live, 11 available, 2 contract-only, 12
absent, 1 not-applicable). Live parity and the broader P1-PLAT-002 task remain
open. Locked repository gates pass: Ruff, mypy across 287 source files,
Bandit with no findings, 1516 tests passed with 21 declared environment skips,
wheel/sdist build including migration 0019, focused Alembic/parity tests, and
`git diff --check` with line-ending warnings only. Publication remains
prohibited.
E-150 is in progress. Migration 0022 and the complete PostgreSQL Receivables
storage aggregate now cover customers, invoices and exact lines, receipts,
allocations, and idempotency. Tenant-qualified parent links, forced RLS,
BIGINT minor-unit money, unconstrained exact NUMERIC with canonical quantity
text, final-invoice immutability, and child-first rollback have focused tests.
The thirteen-method adapter and live lifecycle evidence are not implemented,
so Receivables remains `absent`; no parity or production-readiness claim is made.

E-150 is completed at `live_test_available` maturity. Migration 0022 and
`PostgresReceivablesRepository` implement the exact thirteen-operation port for
customers, invoices, approval, receipts, allocation, exposure, and aging.
BIGINT money, arbitrary-scale quantity text, maker-checker, customer/invoice/
receipt row locks, optimistic versions, idempotency, transactional audit/outbox,
forced RLS, immutable final records, and child-first rollback are explicit.
The non-superuser lifecycle/RLS test is present but skipped without configured
PostgreSQL credentials, so no current-live, production, or publication claim is
made. P1-PLAT-002 and the broader Phase 1-3 objective remain open.

Locked E-150 gates pass: Ruff, mypy over 291 source files, Bandit with zero
findings, 1540 tests passed with 24 declared environment skips, wheel/sdist
build including adapter and migration 0022, valid execution YAML, and clean
diff checking apart from existing line-ending warnings. No publication action
was taken.

## E-165 complete: Phase 2 evidence-bounded exit

All eighteen normative Phase 2 tasks are complete. The exit audit binds the four
required gates to deterministic matching, evidence integrity,
Reconciliation-as-Code, and measured-performance artifacts. The focused 104-test
gate passed, and the retained 10K/100K profile byte counts and SHA-256 values
were independently verified with hardware/software, CPU, runtime, peak-memory,
candidate-count, outcome, and result-signature fields present.

This closes the declared local deterministic/application-contract scope only.
It does not claim 1M/10M, database/distributed throughput, sustained production
capacity, disclosure approval, production readiness, or external assurance.
Work moves to Phase 3 Enterprise Product; no publication action was taken.

## E-166 in progress: enterprise federation policy boundary

The first P3-ENT-001 slice adds a provider-neutral Application boundary and
thirteen focused hostile/policy tests. ReconForge delegates all JOSE/XML parsing
and cryptographic verification to future reviewed library adapters, then enforces
exact issuer/audience/protocol/algorithm, signature state, bounded time, OIDC
nonce, SAML request correlation, one-time replay, allowlisted role mapping,
sanitized audit outcomes, and air-gap refusal.

P3-ENT-001 remains in progress. Real signed OIDC/SAML fixtures, durable
PostgreSQL replay/link/session persistence, logout, API integration, locked
dependencies and broader security tests remain. No SSO support or publication
claim is made.

## E-167 complete: real static-JWKS OIDC verification

The first cryptographic adapter uses locked joserfc 1.7.4 and real RS256 fixtures.
It accepts only bounded operator-owned public JWKS, forbids dynamic or token-
directed key URLs, limits algorithms, verifies signatures, validates required
OIDC claims, enforces nonce and multi-audience azp, bounds normalized claims,
and derives replay identity from the authenticated compact token. Nine adapter
tests and thirteen policy tests pass; Ruff, mypy, Bandit and pip-audit are green.

P3-ENT-001 remains in progress for SAML, durable replay/link/session persistence,
logout and API integration. No SSO or publication claim is made.

## E-168 complete: strict real-signature SAML verification

The SAML adapter uses locked python3-saml/xmlsec/lxml, a fixed synthetic IdP
certificate, strict signed-Response processing and independent signature/digest
allowlists. Real RSA-2048 X.509 fixtures prove valid normalization and rejection
of wrong issuer, audience, request correlation, post-signature tamper, wrong
certificate and unsafe endpoints. The combined 28-test Federation target passes;
Ruff, mypy, Bandit and pip-audit are green. The library's internal Python 3.14
`utcnow()` deprecation warning is recorded for upgrade monitoring.

P3-ENT-001 remains in progress for durable PostgreSQL replay/link/session
persistence, logout and API integration. No SSO or publication claim is made.

## E-164 complete: Phase 1 evidence-bounded exit

All ten normative Phase 1 tasks are complete. The machine-readable exit audit
binds the three required gates to current repository-boundary inventory,
unskipped PostgreSQL evidence, durable execution tests, policy/object-store/
telemetry controls, and verified Community/Team recovery cells. P1-PLAT-010 is
closed for the foundation scope after removing a circular dependency on Phase 3
HA and air-gap outcomes.

The backup/restore matrix remains overall partial: Enterprise HA and Regulated
air-gap cells remain planned under Phase 3, with no managed-key, host-loss,
RPO/RTO, production-readiness, compliance, or external-assurance claim. Work
now moves to the Phase 2 exit audit. No publication action was taken.

## E-163 complete: current-live PostgreSQL contract gate

A fresh disposable PostgreSQL 17.10 service exposed defects hidden by optional
test skips. The migration chain, adapters, metrics read model, and isolated
migration test were remediated. The complete inventory-derived gate then passed
140 Application and migration tests without a skipped live boundary using a
non-superuser application role. A separate containerized PostgreSQL 17 native
client run passed the encrypted backup, random isolated restore, verification,
artifact identity, and exact cleanup test.

P1-PLAT-002 is completed for the declared supported single-node Application
boundaries. The Team PostgreSQL 17 / Alembic 0033 backup matrix cell is verified.
P1-PLAT-010 remains open for HA, air-gap, managed keys, host loss, cross-version
drills, scheduled retention, and measured RPO/RTO. The Phase 1-3 objective is
not complete and no publication action was taken.

E-162 removes the last PostgreSQL Application `contract_only` classification.
The authorized native adapter now derives `RestoreOutcome.artifact_sha256` from
the exact envelope bytes consumed by successful GCM authentication and
plaintext digest/size verification. An opt-in live test executes encrypted
backup, isolated restore, schema verification, identity comparison, and exact
random-target cleanup through the Application service using explicitly
disposable libpq services. Local focused evidence passes and the live test
skips because those services are not configured. Inventory is therefore 25
`live_test_available`, zero `contract_only`, zero `absent`, and one pure
strategy; no current-live, production recovery, RPO/RTO, or publication claim
is made. Locked gates pass: Ruff, mypy over 301 source files, all runnable tests
with 36 declared environment/service skips, Bandit with zero findings,
pip-audit with no known third-party vulnerabilities, wheel/sdist build and
adapter membership, execution YAML, and diff checking. The broader Phase 1 exit
audit remains next.

E-154 is in progress. Migration 0026 introduces tenant-qualified valuation
reversal and immutable layer-effect tables under forced RLS. Database guards
require Draft creation, valid final transitions, exact Approved-original and
Posted-mirror dependencies, complete effects, a balanced Finance Draft, and
immutable approved movement/Finance evidence. Cost-layer balances now include
reversal effects using `original - consumptions + restores - removes`, and
downgrade restores the migration-0025 guard. Six focused tests pass with one
declared live-migration skip; Ruff, mypy, and targeted Bandit pass. The seven
operation adapter now implements every protocol signature. Draft creation
requires an Approved original and exact Posted mirror movement. Approval
revalidates scope and SoD, locks affected layers deterministically, records
complete Remove/Restore effects, updates the exact balance equation, mirrors
Finance lines and dimensions into a balanced Draft, and writes audit/outbox in
the same transaction. Cancellation and bounded reads/summary/snapshot are also
implemented. Thirteen focused tests pass with one declared migration skip;
Ruff, mypy, and targeted Bandit are green. A complete live lifecycle/RLS test
and locked full gates remain. The complete optional non-superuser test covers
Draft cancellation/reuse, maker-checker, exact layer removal, mirrored Finance
Draft, normal-valuation exclusion, unvalued-count exclusion, protected movement,
summary, and cross-tenant invisibility. It skips without PostgreSQL credentials,
so E-154 is `live_test_available`, not `live_verified_current`.

E-154 locked gates pass: Ruff; mypy over 295 source files; the complete runnable
pytest suite with only declared environment skips; Bandit with zero findings;
pip-audit with no known third-party vulnerabilities and only the local package
unavailable on PyPI; and wheel/sdist build including migration 0026 and the
reversal adapter. Execution YAML and diff checking pass apart from existing
line-ending warnings. E-154 is complete at `live_test_available`; no publication
action was taken.

E-155 is complete at `live_test_available`. Migration 0027 adds tenant-qualified count sessions,
immutable snapshot/result lines, and reorder rules under forced RLS. Exact
BIGINT scaled quantities, valid Draft/Counting/Submitted/Approved/Cancelled
transitions, complete-line submission, maker-checker approval, final evidence
immutability, and protected count adjustments are database-enforced. Approval
requires either no adjustment for zero variance or one exact Draft Adjustment
whose lines match every variance's item, UOM, lot, precision, quantity, and
location direction. The adapter implements all thirteen Application operations
with exact signature parity, atomic audit/outbox evidence, posted-stock
revalidation, deterministic Draft Adjustment generation, bounded reads, and
reorder signals. The complete optional non-superuser lifecycle covers count
approval, self-approval rejection, exact adjustment evidence, reorder output,
and cross-tenant invisibility, but it skips without PostgreSQL credentials.
Inventory Planning is therefore `live_test_available`, not
`live_verified_current`; parity is 18 available, 2 contract-only, 5 absent, and
1 not-applicable. Locked gates are recorded in EVIDENCE.md. No publication action
was taken.

E-156 is complete at `live_test_available`; all locked full gates pass.
Migration 0028 adds five tenant-qualified forced-RLS tables
for templates, checksum-bearing trial-balance rows, reconciliation records,
support items, and append-only transition evidence. The complete eleven-method
adapter preserves bounded ingress and exact arbitrary-scale NUMERIC plus
canonical decimal text, permits financial mutation only in Draft, enforces
Draft → Prepared → In Review → Reviewed → Complete, rejects preparer self-review,
rolls governance forward with a zero balance, and commits audit/outbox effects
atomically. The optional non-superuser test covers exact 15-decimal residue,
ingress, lifecycle, SoD, transition evidence, roll-forward, and RLS, but skips
without PostgreSQL credentials. Accounts is not `live_verified_current`; parity
is 19 available, 2 contract-only, 4 absent, and 1 not-applicable. Ruff, mypy
over 297 files, the complete runnable pytest suite, Bandit, pip-audit, package
build/membership, execution YAML, and diff checking pass with only declared
service skips and pre-existing warnings. No publication action was taken.

E-157 is complete at `live_test_available`; all locked full gates pass.
Migration 0029 adds tenant-qualified approval-request and
certification-metadata tables under forced RLS. The complete eight-method
adapter permits one Submitted → Approved/Rejected decision, prevents requester
self-approval, requires rejection reasons, rejects every override reason, and
permits one Prepared → Reviewed certification transition by a distinct actor.
Submission scope, decisions, reviewed metadata, and history are immutable;
audit/outbox effects are atomic and reads bounded. The optional non-superuser
test covers approval, rejection, certification SoD, evidence counts, and RLS,
but skips without PostgreSQL credentials. Approvals is not
`live_verified_current`; parity is 20 available, 2 contract-only, 3 absent, and
1 not-applicable. Ruff, mypy over 298 files, the complete runnable pytest suite,
Bandit, pip-audit, package build/membership, execution YAML, and diff checking
pass with only declared service skips and pre-existing warnings. No delegation,
legal-signature, compliance, or publication claim is made.

E-158 is complete at `live_test_available`; all locked local gates pass.
Migration 0030 adds a contract-compatible tenant/workspace
Close aggregate without altering the distinct legacy organization/fiscal-period
PostgreSQL repository. All eleven Application signatures cover serialized
non-overlapping periods, deterministic tasks, same-period acyclic dependencies,
exclusive blocker reasons, exact Decimal readiness, dependency-gated task
completion, 100.00-only locking, immutable locked state, reasoned reopening,
bounded reads, and atomic audit/outbox evidence. The optional non-superuser test
covers overlap rejection, transitive cycle rejection, dependency ordering,
readiness, lock/reopen, evidence counts, and RLS, but skips without PostgreSQL
credentials. Close is not `live_verified_current`; parity is 21 available, 2
contract-only, 2 absent, and 1 not-applicable. The lock is ReconForge workflow
metadata only. Ruff, mypy over 299 source files, 1,590 passing tests, Bandit,
pip-audit, package build/membership, execution YAML, and diff checking pass with
only declared service skips and pre-existing warnings. No source-ERP,
statutory-close, commit, push, pull request, or publication claim is made.

E-159 is complete at `live_test_available`; all locked local gates pass.
Migration 0031 adds a contract-compatible tenant/workspace
Evidence Registry aggregate without altering the distinct historical
tenant/external-reference repository. All eight exact Application signatures
cover local and explicit object-store registration, immutable artifact identity,
requirements, append-only links, checksum verification, coverage, bounded
listing/get, and bounded redacted drill-down. Identity is checked before an
object upload, provider-returned bytes and tenant metadata are verified, and
audit/outbox effects share the database transaction. The optional non-superuser
test covers local-file registration, linking, checksum verification, drill-down,
and RLS, but skips without PostgreSQL credentials. Evidence is not
`live_verified_current`; parity is 22 available, 2 contract-only, 1 absent, and
1 not-applicable. Object upload plus database commit is not a distributed
transaction; content-addressed keys and orphan cleanup remain required. No
signature, WORM, or non-repudiation claim is made. Ruff, mypy over 300 source
files, 1,595 passing tests, Bandit, pip-audit, package build/membership,
execution YAML, and diff checking pass with only declared service skips and
pre-existing warnings. No commit, push, pull request, or publication occurred.

E-160 is complete at `live_test_available`; all locked local gates pass.
Migration 0032 adds tenant/workspace exception records and
append-only transition history under forced RLS. The complete six-operation
adapter preserves source-idempotent upsert, assignment, flexible statuses,
filters, bulk update, and get while adding immutable source identity, bounded
inputs/reads, deterministic prelocking, all-target-before-mutation atomicity,
1,000-unique-target bulk limits, current-state-verified history, and
row-version-derived outbox identities. The optional non-superuser test covers
create, assign, atomic bulk status, history, and cross-tenant invisibility but
skips without PostgreSQL credentials. Exceptions is not
`live_verified_current`; measured parity is 23 available, 2 contract-only,
0 absent, and 1 not-applicable. Zero absent entries does not prove Phase 1 exit:
current-live cross-backend evidence, backup/restore, outbox contract closure,
permissions audit, and broader operational gates remain. No commit, push, pull
request, or publication occurred. Ruff, mypy over 301 source files, 1,599
passing tests, Bandit, pip-audit, package build/membership, execution YAML, and
diff checking pass with only declared service skips and pre-existing warnings.

E-161 is complete at `live_test_available`; all locked local gates pass.
Migration 0033 adds real `dead_lettered_at` evidence and a
database guard that freezes event identity/payload and enforces exclusive
Pending/Claimed/Published/Dead metadata. Application `pending` now includes
leased Claimed rows like SQLite. The five exact signatures retain bounded
tenant-scoped SKIP LOCKED claims, expiring leases, worker ownership, retry,
dead-letter, replay, canonical payload validation, and deterministic listing.
The optional non-superuser lifecycle proves two workers receive disjoint events,
pending sees active leases, failure records a real dead timestamp, replay and
publish succeed, and another tenant sees nothing; it skips without PostgreSQL
credentials. Outbox is not `live_verified_current`; parity is 24 available,
1 contract-only, 0 absent, and 1 not-applicable. Delivery remains at-least-once,
not exactly-once. No commit, push, pull request, or publication occurred.
Ruff, mypy over 301 source files, 1,600 passing tests, Bandit, pip-audit,
package build/membership, execution YAML, and diff checking pass with only
declared service skips and pre-existing warnings.

E-152 is in progress. Migration 0024 now defines the complete seven-table
PostgreSQL Inventory Core aggregate for units, items, warehouses, hierarchical
locations, lots/serials, movements, and exact scaled lines. Composite tenant
links, BIGINT quantities with explicit 0-6 precision, forced RLS, governed
Draft-to-Posted-to-Voided transitions, final header/line immutability, indexes,
and child-first rollback have focused tests. The eighteen-method adapter,
serialized stock projection, evidence, and live lifecycle are not implemented;
Inventory Core remains `absent` and no parity or publication claim is made.
Protocol inspection corrected the recorded adapter size from 18 to 19 operations.
The PostgreSQL adapter now implements all nineteen operations: governed UOM,
item, warehouse, hierarchical-location, and lot/serial upsert/list paths, all
inside tenant-scoped transactions with audit/outbox evidence. Referenced master
records are protected from unsafe semantic changes or deactivation. The
Draft movement creation/read now validates Open-period dates, exact quantities,
direction, entity/location scope, tracking mode, and serial uniqueness before
an atomic header/line replacement. Post/void/list enforce maker-checker,
Open-period voiding, sorted advisory transaction locks for affected stock and
serial keys, protected negative-stock policy, and zero-or-one serial on-hand.
On-hand derives exact Posted-only balances; deterministic controls cover
negative stock, positive expired stock, and missing inventory accounts;
summary/snapshot remain bounded. Protocol-signature inspection and a complete
non-superuser lifecycle/RLS test are present. Inventory Core is therefore
`live_test_available`, not `live_verified_current`, because PostgreSQL
credentials are absent in this environment.

E-152 locked gates pass after removing all adapter SQL-string suffix assembly:
Ruff, mypy over 293 source files, Bandit with zero findings, 1,555 tests passed
with 26 declared environment skips (1,581 collected), wheel/sdist build
including migration 0024, pip-audit with no known third-party vulnerabilities
and the local package correctly unaudited, valid execution YAML, and clean diff
checking apart from existing line-ending warnings. E-152 is complete at
`live_test_available`; current PostgreSQL execution is not claimed.

E-153 is complete at `live_test_available`. Migration 0025 establishes the six-table PostgreSQL FIFO
valuation aggregate for policies, documents, exact input costs, immutable
valuation lines, cost layers, and immutable layer consumptions. Tenant-qualified
foreign keys, integer minor values, scaled quantities, forced RLS, Draft-only
detail guards, balanced Finance approval checks, monotonic layer depletion, and
child-first rollback have focused tests. The eleven-operation adapter and a
complete optional non-superuser FIFO receipt/issue lifecycle are present;
current live execution remains unproven because PostgreSQL credentials are absent.

The E-153 adapter now implements all eleven operations: governed policy
upsert/get/list and Draft document create/cancel/get/list. Policy setup checks
workspace-bound active organization/entity, journal/chart/currency, posting
accounts, and unsupported required dimensions. Draft creation rejects non-Posted
and Transfer movements, validates inventory accounts, and requires one exact
minor-unit input cost for every inbound line before any write. Audit/outbox
evidence shares each transaction. FIFO approval locks the document and ordered
layers, enforces maker-checker and chronological valuation, allocates partial
minor values with half-even rounding, persists immutable consumptions, creates
a balanced Finance Draft, and approves atomically. Cost-layer listing, summary,
and snapshot are bounded. Inventory Core now blocks voiding a movement with an
Approved valuation. A complete non-superuser receipt/issue/Finance-Draft/
void-guard/RLS test now exists and skips explicitly without configured
credentials. Valuation is therefore `live_test_available`, not
`live_verified_current`; locked full gates remain before selecting E-154.

E-153 locked gates now pass: Ruff; mypy over 294 source files; the complete
1,582-test collection with 1,555 passed and 27 declared environment skips;
Bandit with zero findings; pip-audit with no known third-party vulnerabilities
and only the local package unavailable on PyPI; and wheel/sdist build including
the adapter and migration 0025. Execution YAML and diff checking also pass,
apart from pre-existing line-ending warnings. No publication action was taken.

E-151 is completed at `live_test_available` maturity. Migration 0023 binds each
matching run to one tenant workspace under forced RLS. The six-method
`PostgresMatchingRepository` reads bounded business-record documents, executes
the shared deterministic engine, resolves currency precision from PostgreSQL,
registers every source fingerprint and trusted position, persists all results
and exceptions through the reconciliation integrity store, and completes the
run atomically. Workspace identity participates in idempotency fingerprints;
direct matching and the runtime module contain no SQLite dependency. The
non-superuser lifecycle/RLS test is present but skipped without PostgreSQL
credentials. P1-PLAT-002 and the broader Phase 1-3 objective remain open, and
no publication action was taken.

Locked E-151 gates pass: Ruff, mypy over 292 source files, Bandit with zero
findings, 1545 tests passed with 25 declared environment skips, wheel/sdist
build including adapter and migration 0023, valid execution YAML, and clean
diff checking apart from existing line-ending warnings. No publication action
was taken.
## E-208 — Closed connector manifest and local synthetic conformance

P3-ENT-007 is in progress. `connector-manifest-v1` now provides a strict immutable
security/operations declaration and refuses write capability. The existing registry remains a
static source allowlist; generic CSV is a local-file adapter, while SAP and Odoo are explicitly
export profiles rather than live connectors. A deterministic local conformance suite proves the
three built-ins do not mutate synthetic input, accept its schema, and return data. A data-only
Ed25519 envelope authenticates bounded manifests against exact caller-trusted keys without loading
code. No network, credential, installation, or write-back capability was added. No commit,
push, pull request, release, or publication occurred.

## E-210 — Signed data-only pack lifecycle

P3-ENT-008 is complete at a local synthetic, evidence-bounded scope. Control and industry
pack envelopes now have authenticated identity, closed declarative/golden conformance,
platform and active-dependency compatibility, distinct maker-checker approval, immutable
local versions, atomic upgrade, disable, rollback, and actor/digest lifecycle events. The
locked full regression passes 1,924 tests with 62 declared external skips. This is not a
marketplace, externally verified publisher system, production trust administration,
distributed lifecycle, compliance, certification, or Enterprise readiness. No commit,
push, pull request, release, or publication was performed. The combined Phase 1-3 objective
remains open and proceeds to the next planned Phase 3 slice.

## E-211 — Multi-resource upgrade saga foundation

P3-ENT-009 is in progress. A closed upgrade plan and durable local orchestrator now require
all-resource preflight, independent approval, an atomic execution claim, ordered verified
effects, reverse rollback, and explicit classification of interrupted work. Nine tests pass,
including a real Community SQLite 23-to-24 compatibility/apply/later-failure/restore drill;
application/PostgreSQL/object/configuration/pack composition and supported-version drills remain
mandatory before exit. No production resource, external network, commit, push,
pull request, release, or publication was used.

## E-212 — Supported-version upgrade and rollback automation

P3-ENT-009 is complete at an evidence-bounded local/disposable scope. The closed matrix
separates the v0.7.1 operator from deployed versions and permits `supported` only when every
listed transition is verified. Concrete adapters cover tagged offline wheels, Community
SQLite, PostgreSQL encrypted restore plus Alembic, immutable local object catalogs, strict
`reconforge.yml`, and the existing signed-pack lifecycle. One plan completes all five real
local resource kinds in order; later-effect failures restore prior application, database,
object catalog, and configuration states, and signed-pack rollback restores the approved
source version. The disposable PostgreSQL 17.10 drill reached 0053 from 0052 after encrypted
backup/isolated restore, then returned to 0052 and removed the drill database/container.
Production secrets, customer data, network providers, commit, push, pull request, release,
and publication were not used. Zero downtime, HA/DR, host-loss recovery, production key
custody, compliance, certification, and Enterprise readiness remain unclaimed.

## E-213 — Single-host synchronous PostgreSQL failover drill

P3-ENT-010 is in progress. A named two-node PostgreSQL 17.10 Docker topology passed
physical streaming, synchronous remote-apply, encrypted isolated restore, replication-
network partition, exact-primary fencing, promotion, former-primary re-seed/read-only
verification, synchronous continuation, second fencing, and failback. The final run
recorded sequences 1-4, zero missing acknowledged transactions, 11.117-second failover
RTO, and 0.958-second failback RTO under a 60-second ceiling. Control and replication
networks are separate so fault injection does not remove the management path. The
partition write was not acknowledged and is correctly treated as uncertain, not lost.
Both nodes and the manual controller still share one host. Multi-host loss, quorum/witness
fencing, automatic failover, repeated measurements, production keys, and production SLO
evidence remain required before task exit. No publication occurred.

## E-214 — Closed offline installation input contract

P3-ENT-011 is in progress. `reconforge.sovereign.offline_bundle` and the closed JSON
schema verify a complete local file inventory, exact sizes/SHA-256 digests, normalized
paths, one application wheel, one hash-locked requirements file, deny-all/no-index
policy, and a non-shell `pip --no-index --require-hashes` argument vector. Hostile tests
reject tampering, extra files, URL requirements, unhashed requirements, duplicates, and
path escape; link rejection is implemented and its creation-dependent test is skipped
on Windows. No installer has yet run in an OS-level no-egress sandbox, and signature,
identity fallback, backup, upgrade, and rollback gates remain open. No publication occurred.

## E-215 — Real no-network Linux installation drill

P3-ENT-011 remains in progress. The reproducibility script built the current v0.7.1
wheel, exported selected runtime extras from the 124-package universal lock, downloaded
Linux wheels under the exported hashes, and re-locked the 60 actual selected files by
digest. A separate digest-pinned Python 3.14.1 slim container installed all files with
network mode none, read-only root/bundle, bounded tmpfs, no-index, no-deps, and require-
hashes; `reconforge doctor` exited zero. The closed report binds 98,913,160 bytes and
manifest SHA-256 `845f7190510e31e6ec651dad4201c30b4279f01b7580f61289cab6facac596ce`.
Offline signature trust, local identity, backup/restore, upgrade/rollback, repetition,
another platform, and physical-air-gap evidence remain open. No publication occurred.

## E-216 — Disconnected file-attestation verification

P3-ENT-011 remains in progress. A SHA-256-pinned gh 2.78.0 verifier and pinned Sigstore
trusted-root snapshot ran in a digest-pinned Python 3.14.1 slim container with network
mode none, read-only root, and read-only evidence/tool mounts. All 15 checksum subjects
and six attestation-bundle hashes matched. Exact repository, workflow, signer/source
commit, source tag, and hosted-runner constraints passed for 11 regular-file provenance
subjects and three file-artifact CycloneDX attestations. gh attempts registry resolution
for OCI subjects even with a local bundle; therefore two image bundles are integrity-only
and offline OCI subject verification remains explicitly zero. Identity recovery,
backup/restore, upgrade/rollback composition, repetition/platform coverage, physical
transfer custody, and OCI offline verification remain open. No publication occurred.

## E-217 — No-network local identity and encrypted recovery

P3-ENT-011 remains in progress. The real 60-file Linux mirror was rebuilt and installed
with no index, no dependency resolution, exact hashes, Docker network mode none, and a
read-only root/bundle. Inside that installed runtime, generated local credentials created
an admin and reviewer; authentication, admin permission, and the audit chain passed.
AES-256-GCM backup and isolated schema-24 restore returned both users and permissions; a
random wrong key failed without a partial target, and the pre-backup bearer session was
not restored. Doctor exited zero and cleanup removed the container/tmpfs. This proves
pre-provisioned local fallback, not forgotten-password recovery or hardware key custody.
Offline upgrade/rollback composition, repeat/platform coverage, physical transfer, and
OCI offline subject verification remain open. No publication occurred.

## E-218 to E-220 — No-network upgrade and signed-wheel sovereign profile exit

P3-ENT-011 is complete at an evidence-bounded Python-wheel profile. E-218 built the
immutable v0.7.0/v0.7.1 tags before isolation, mounted both wheels read-only, and used
the real application adapter under Docker network mode none. No-index/no-deps staging,
version/digest smoke checks, v0.7.1 cutover, and exact v0.7.0 content rollback passed.

E-219 removed the prior composition gap between signature evidence and installation:
the exact signed-release-candidate wheel SHA-256
`210e69770fe1ad55227173349ee22ca7f16e4f5270c093f12c78460c14b66f33`
that passed offline provenance and CycloneDX verification was installed unchanged from
the 60-entry mirror in the no-network/read-only runtime; doctor exited zero. E-220's
closed audit verifies all stated task gates and preserves limitations for OCI registry
resolution, dependency attestations, physical custody, hardware keys, forgotten-password
recovery, and single-platform/single-run evidence. No publication occurred.

## E-221 — Closed reliability policy and local recovery exercise

P3-ENT-012 is now in progress. A schema-closed policy evaluates seven bounded integer
signals without tenant, workspace, record, actor, currency, or amount dimensions. Missing
measurements produce `no_data`; every warning/critical threshold binds an SLO identifier
and RF-OPS-001 through RF-OPS-005. A synthetic in-memory drill exported all seven metrics,
made dependency readiness and memory capacity critical, correlated a recovery log with
one trace, and returned every signal to normal. This is not external collector/alert-manager,
independent-host HA, production SLO, or external-assurance evidence. P3-ENT-010 remains an
open dependency, so P3-ENT-012 cannot close. No publication occurred.

## E-222 — Operational-source reliability snapshot

P3-ENT-012 remains in progress. The HTTP source now records real FastAPI responses in a
bounded concurrent window and derives exact integer error basis points and nearest-rank
p95. The local collector reads aggregate durable-job depth/age, verifies the real audit
chain, calls explicit dependency probes, and consumes a bounded memory provider without
emitting identifiers. Unavailable or malformed sources are named by safe category and
their metrics remain absent, producing `no_data` rather than false health. The retained
drill now uses a freshly migrated temporary database and these real sources. PostgreSQL
parity, external collection/alert delivery, repeated load/capacity evidence, and the open
independent-host HA dependency remain required. No publication occurred.

The bounded `reconforge ops reliability` command exposes the same aggregate policy and
safe unavailable-source categories. `--require-complete` exits non-zero unless every
required signal is observed and normal. Process resident memory is read through standard
Windows/Unix APIs without adding a dependency or external call.

## E-223 — Explicit OTLP/HTTP collector delivery

P3-ENT-012 remains in progress. The official OTLP HTTP/protobuf exporter 1.44.0
is pinned and reachable only through explicit API CLI options. Non-loopback hosts
require exact allowlisting and HTTPS; plaintext is loopback-only; CA/mTLS inputs
are validated and ambient proxy/OTLP discovery is disabled. A real FastAPI request
delivered traces, metrics, and one schema-closed operational event to the standard local receiver paths, force-flushed,
and shut down cleanly with no prohibited marker in protobuf payloads. This is not
a full Collector/backend/alert-manager deployment or arbitrary application-log export. PostgreSQL
parity, repeated capacity/incident evidence, and independent-host HA remain open.
No publication occurred.

## E-224 — PostgreSQL reliability-source parity

P3-ENT-012 remains in progress. A reproducible Docker drill migrated fresh PostgreSQL
17.10 to Alembic `0053`, created a non-superuser application role, and exercised the
collector inside forced-RLS transactions. Queued jobs in two sibling tenants produced
exactly one visible job and 600-second age for the selected tenant; the sibling remained
excluded and the tenant audit aggregate verified cleanly. The labelled container was
removed. This is a synthetic single-node test, not repeated load/capacity, alert delivery,
independent-host HA, production SLO, or external assurance. No publication occurred.

## E-225 — Bounded capacity and backlog recovery

P3-ENT-012 remains in progress. On the named Windows 11/Python 3.12.13/16-logical-CPU
environment, 1,000 in-process FastAPI health requests completed with zero 5xx basis
points, 16 ms observed p95, 10,460 ms total wall time, and 130 MiB resident memory.
A disposable 1,000-job SQLite backlog triggered the exact critical threshold; after
synthetic recovery, depth and oldest age returned to normal/zero. The aggregate query
completed below the report's one-millisecond resolution. This is a single local run,
not network load, soak, distributed capacity, production sizing, or an SLO. No publication
occurred.

## E-226 — Pinned official Collector and file backend

P3-ENT-012 remains in progress. The digest-pinned official OpenTelemetry Collector
Contrib 0.153.0 ran with a read-only root, dropped capabilities, no-new-privileges,
loopback-only OTLP/HTTP, and the repository's traces/metrics/logs pipelines. A real API
request, queue metric, critical alert event, RF-OPS-002 runbook binding, and telemetry
policy persisted to a 5,426-byte file artifact with retained SHA-256. Prohibited marker
names were absent and the container/output were cleaned. Durable retention, independent
alert-manager acknowledgement, Collector HA, and production SLOs remain open. No
publication occurred.

## E-227 — Closed incident acknowledgement and recovery evidence

P3-ENT-012 remains in progress. A strict incident model now permits only ordered
`detected`, `acknowledged`, `mitigating`, `recovered`, and `closed` transitions,
monotonic UTC timestamps, safe operator/action references, and digest-only evidence.
Recovery fails unless every required reliability alert is present and normal; each
event commits to the previous digest and the final manifest is independently verified.
A retained local drill drove the real aggregate queue depth to 1,000/critical, bound
RF-OPS-002, acknowledged at 15 seconds, restored and independently validated zero
backlog/all-normal at 45 seconds, and closed at 60 seconds. The actors, timings, and
data are synthetic. External pager acknowledgement, durable incident retention,
real staffing/on-call evidence, repeated exercises, independent-host HA, and
production SLOs remain open. No publication occurred.

## E-228 — Three-run bounded HA/DR distribution

P3-ENT-010 remains in progress. The full synchronous-replication, encrypted
isolated-restore, partition, exact-ID fencing, failover, former-primary re-seed,
failback, integrity, and cleanup drill passed three consecutive clean runs. All
runs retained zero loss of acknowledged sentinel transactions and sequence four.
Failover RTO min/median/max was 11.075/11.094/11.117 seconds; failback was
0.912/0.945/0.958 seconds, below the 60-second development ceiling. The report
retains every result rather than selecting the fastest. Repetition does not remove
the one-Docker-host failure domain: independent host loss, quorum/witness fencing,
automatic failover, production key custody, and production SLO evidence remain
open. All labelled resources were absent after execution. No publication occurred.

## E-229 — Competitive capability matrix v1

P3-ENT-013 is now in progress. `docs/strategy/competitive-capability-matrix.md`
adds a dated, primary-source-based matrix across deployment sovereignty, determinism,
evidence lineage, matching breadth, scale evidence, connectors, AI governance, security,
UX accessibility, and extensibility. Every row is explicitly bounded to bounded local
or synthetic ReconForge evidence and lists what remains unknown. This file does not claim
enterprise certification or competitive superiority. No publication occurred.

## E-247 — Fail-closed PR #66 CI remediation

The four failing/cancelled PR #66 check families were reproduced and repaired locally without
changing any Phase 1–3 closure assertion. The full Python jobs now install every locked optional
feature extra used by collected tests; the PostgreSQL migration registry is checked against the
complete linear Alembic chain through `0053`; live metric and backup harnesses preserve least
privilege and native PostgreSQL command identity; and Gitleaks suppresses the single historical
`idempotency_scope` false positive only by exact fingerprints while retaining generated-directory
scope. Targeted regression, Ruff, mypy, Bandit, pip-audit, package build, two Gitleaks scans,
frontend type/test/build/E2E, CLI, and Docker gates passed. The full suite still has exactly one
intentional failure: the Phase 3 closure guard rejects the absent real external pilots and
independent review. The remediation is unpublished; no push, tag, release, or external claim
occurred.

## E-248 — Governed real public-financial-data evidence

P3-EXT-001 remains in progress. A closed manifest now pins eleven exact responses
from three official open-data publishers and drives three independent financial
experiments. The final clean-commit live run at `5eeb4e751a9d4361b3cea7bf7587da502b564d9e`
matched 967/967 records with zero unmatched records or exceptions, preserved
Treasury and World Bank cross-format/equation invariants, detected the governed UK
mixed encodings, reversal, and repeated references, and produced reproducibility
SHA-256 `890a4aa8f7b362981bfdd1f0f333d3bad55a886d842c0ff0a82ff165c48e26c5`.
Offline replay produced the same digest. The retained report is redacted and its
SHA-256 is `be71deea074786457b7e5a368fece18b14953d2fcdc0f3ffdea94beb3b9ebd21`.

A manual least-privilege GitHub workflow can run the exact experiment on an
independently controlled fork, checksum the report, issue and reverify a GitHub
artifact attestation, and retain an artifact identity. No external operator has
run or attested it yet, so the accepted operator count is zero and this evidence
does not close the pilot gate. No push, tag, release, customer-data use, or public
readiness claim occurred.

## E-249 — Independent security-review intake remains externally blocked

P3-EXT-002 remains in progress. The new review protocol defines independent-human
qualification and conflict boundaries, private disclosure, scope, finding,
remediation, retest, and residual-risk acceptance requirements. Read-only GitHub
API verification on 2026-08-01 returned `enabled=false` for private vulnerability
reporting. No setting was changed. Open-source scanners remain supporting evidence,
not an independent review; solicitation is blocked until the repository owner
enables and harmlessly verifies a private channel and a qualified independent
reviewer accepts the scope.

## E-250 — Parser-inventory regression closed without bypass

The first full 2,088-test collection exposed three real failures in the exact
production parser inventory plus the expected external-closure guard. Instead of
adding three direct-parser exceptions, the public manifest and JSON paths now use
the central bounded structured-ingress implementation. The sole necessary direct
mixed-encoding CSV parser is registered under new bounded surface FI-023 with its
entrypoints, controls, tests, residual risks, and claim limits. The focused
inventory/public-evidence target passes 18/18. The repeated full run has exactly
one failure: the intentional Phase 3 guard while external operator and independent
review evidence remain absent. No parser-inventory test was skipped or weakened.

## E-251 — Owner/team release authority supersedes mandatory external staffing

By explicit repository-owner decision, Phase 1–3 release closure no longer
requires recruiting external operators, profession-specific participants, or an
independent security reviewer. The 41 internal/team tasks are the required scope;
`P3-EXT-001` and `P3-EXT-002` remain truthfully unverified but are reclassified as
deferred optional assurance. `P3-ENT-013` is completed from the dated bounded
competitive matrix and retained technical evidence. External evidence may not be
simulated or claimed, and unsupported customer, independent-review, certification,
compliance, superiority, scale, or Enterprise-ready wording remains prohibited.
Actual publication still requires the exact candidate to pass the required local
and GitHub gates and receive owner/team approval. No push, tag, or release occurred
as part of this policy change.

The E-251 local verification replay is green: the complete 2,089-test collection
passed in 520.4 seconds; closure contracts pass 5/5; Ruff, mypy across 374 source
files, Bandit, dependency audit, wheel/sdist build, supply-chain validation,
frontend typecheck, 55/55 Vitest, production build, 11-pass/5-skip Chromium E2E,
and checksum-pinned Gitleaks history/tree scans all pass. The branch still requires
publication and remote GitHub verification before a release Go decision.

## E-271 — Durable-job retry/failure-injection profile

- `reconforge/benchmark/durable_job_retry.py` injects a synthetic transient
  fault after at most one committed partition under concurrent SQLite workers.
  The retry transition releases the lease; the next owner reads committed
  effects, skips the checkpointed partition, and completes the remaining work.
- Focused contracts pass 5/5. The profile proves exact retry count, retry
  ceiling, zero duplicate partition effects, complete queue/running drain, and
  deterministic effect/manifest digests. ADR 0226 and the benchmark document
  are included in the package manifest.
- This remains a bounded SQLite evidence slice. Provider backoff/jitter,
  PostgreSQL parity, external compensation, soak, and 10K/100K/1M/10M scale
  publication remain open.

## E-272 — Grouped matching crash/resume and cross-engine replay

- `reconforge/benchmark/grouped_matching_replay.py` evaluates four synthetic
  partitions across one-to-many, many-to-one, many-to-many, and portfolio
  partial-settlement modes through both the strategy adapter and application
  boundary. It persists each output as a durable-job effect.
- A fault after the first committed partition forces one retry. The resumed
  run matches an uninterrupted baseline digest, leaves zero duplicate effects,
  drains the job state, and passes the one-cent adversarial mutation sentinel.
- Focused contracts pass 5/5; ADR 0227, benchmark documentation, and package
  membership are included. PostgreSQL parity, mutation-tool score, and scale
  publication remain open.

## E-273 — PostgreSQL worker grouped matching contract adapter

- `reconforge/workers/postgres_grouped_matching.py` translates streamed
  tenant-scoped partitions into the closed grouped strategy request. It
  requires an explicit supported mode, exact non-binary tolerance, bounded
  date window, checkpoint skipping, and deterministic JSON-safe output.
- Focused contracts pass 5/5. The parity inventory deliberately continues to
  classify the pure grouped service as `not_applicable`; this worker adapter is
  not counted as live parity. A future PostgreSQL runtime drill must still
  prove migration, RLS/tenant isolation, checkpoint replay, and failure
  recovery.

## E-274 — Published 10K durable-job scale profile

- `reconforge/benchmark/durable_job_scale.py` declares 16 workers, 1,000
  jobs, ten partitions per job, and four tenant lanes (10,000 committed
  partition effects). The existing generation-fenced worker/checkpoint and
  idempotency contracts are reused; SQLite now waits up to a bounded 60
  seconds for transient writer contention.
- Two complete Windows 11/Python 3.14.6 runs drained all work with zero
  duplicate effects and identical effect-set digest
  `0e750959e9661f6f2c463dde311c87928bf53ad56facfdd9274b1feeca674dc3` and
  manifest digest `ef430b4033a81f93e3e5a38bd9c9773a346b48b29fe2d568a7c63049a23675ff`.
- Boundary: this is one-host SQLite evidence. PostgreSQL parity, backpressure,
  retry/backoff coupling, soak, HA/DR, SLOs, and 100K/1M/10M tiers remain
  unverified.

## E-279 — PostgreSQL ownership contract added

- Alembic 0054 and `PostgresConsolidationOwnershipRepository` now provide a
  tenant-scoped contract for the typed ownership master. The schema uses exact
  NUMERIC percentages, forced RLS, transaction-local `app.tenant_id`, and
  immutable update/delete triggers; the adapter performs locked overlap checks
  and emits audit evidence.
- Four contract tests and six inventory tests pass at the E-279 head. CI run `30754824673` passed
  both Python suites, all four engine-parity jobs, live `server-boundaries`, and
  `docker-parity`; that live job migrated PostgreSQL through `0054_pg_consol_ownership`
  and exercised the Alembic downgrade/upgrade boundary. The parity inventory
  was `contract_only` at that historical head because no dedicated live
  ownership-adapter runtime was wired yet; E-280 records the subsequent gate.

## E-280 — Live PostgreSQL ownership runtime

- The dedicated ownership runtime contract passed in CI under the
  non-privileged application role. It proves idempotent replay, tenant
  isolation, overlap refusal, and database-trigger immutability for synthetic
  ownership data. The parity inventory now records this boundary as
  `live_verified_current`.
- Boundary: one PostgreSQL 16 Alpine CI node only. Encrypted restore, PITR,
  HA/DR, RPO/RTO, broader consolidation posting, and statutory statements
  remain unverified.

## E-281 — Ownership-change adjustment proposal

- `ownership-change-adjustment-v1` now calculates a policy-bound, non-posting
  three-line proposal: rounded NCI delta, signed consideration effect, and a
  parent-equity balancing line. Exact Decimal inputs, source/policy/approval
  lineage, visible rounding delta, deterministic digests, and tamper-checked
  JSON output are covered by nine focused tests and a closed schema.
- Boundary: no statutory treatment, goodwill, purchase-price allocation,
  disposal accounting, ledger posting, persistence, restore, or HA/DR claim is
  made.

## E-278 — Persisted effective-dated consolidation ownership

- Migration 26 (`consolidation_ownership_masters`) adds an immutable local
  ownership master. `ConsolidationOwnershipApplicationService` and
  `SQLiteConsolidationOwnershipRepository` validate approved domain interests,
  exact Decimal percentages, preparer/approver separation, non-overlapping
  subsidiary intervals, workspace isolation, and deterministic effective-date
  resolution.
- Backup/restore now includes the ownership table. Three focused ownership
  tests plus the existing close/lifecycle contracts pass, including direct SQL
  update/delete refusal and restored effective ownership replay.
- Boundary: this is a local SQLite master-data slice. PostgreSQL parity,
  acquisition/ownership-change accounting, statutory statements, and API/CLI/UI
  exposure remain open.

## E-277 — Published 1M grouped-matching profile

- `reconforge/benchmark/grouped_matching_scale.py` now declares a 1,000,000
  record profile as 250,000 independent true many-to-many partitions. Every
  partition runs through `GroupedSubsetSumStrategy` and the backend-neutral
  application service; every 10,000th partition is replayed with reversed input
  order.
- Two Windows 11/Python 3.14.6 runs matched all 250,000 partitions with zero
  ambiguity/unmatched results, zero cross-engine/permutation mismatches, and
  identical effect digest `05c76d8c2d30dcf8e85893ce777f5edc27324beb0465538fc76c2e6ea1c4124f`
  and manifest digest `5da7ca5deeeddb1f8d4ee04c23b4d4f79a33b34c6cf2861bc1dbf50ccbc9f7be`.
  Runtime was 433.3014s / 427.1993s and peak traced memory was 77.5718 / 77.5585 MiB.
- Boundary: exact USD synthetic, one-process partitioned evidence only.
  PostgreSQL runtime parity, distributed load, soak/SLOs, provider I/O, and
  domain-diverse financial workloads remain unverified.

## E-276 — Published 100K grouped-matching profile

- `reconforge/benchmark/grouped_matching_scale.py` now declares a 100,000
  record profile as 25,000 independent true many-to-many partitions. Every
  partition runs through `GroupedSubsetSumStrategy` and the backend-neutral
  application service; every 1,000th partition is replayed with reversed input
  order.
- Two Windows 11/Python 3.14.6 runs matched all 25,000 partitions with zero
  ambiguity/unmatched results, zero cross-engine/permutation mismatches, and
  identical effect digest `dda82223212af64038094cc21d4a6fed08af76d86a5b9920c1f4bd187d33be41`
  and manifest digest `60aad17ab30533964f61e1b5c64aeba58e56915ee62ac5a75325c25a7133981a`.
  Runtime was 42.0286s / 40.7803s and peak traced memory was 7.7915 / 7.7700 MiB.
- Boundary: exact USD synthetic, one-process partitioned evidence only.
  PostgreSQL runtime parity, distributed load, soak/SLOs, financial-domain
  diversity, and 1M records remain unverified.

## E-275 — Published 10K grouped-matching profile

- `reconforge/benchmark/grouped_matching_scale.py` measures 10,000 records as
  2,500 independent true many-to-many partitions. Each partition runs through
  `GroupedSubsetSumStrategy` and the backend-neutral application service; every
  100th partition is replayed with reversed input order.
- Two Windows 11/Python 3.14.6 runs matched all 2,500 partitions with zero
  ambiguity/unmatched results, zero cross-engine/permutation mismatches, and
  identical effect digest `a6089d61b21e4b47ecff2554cd5116186c675be7b9aa5b0686ebba1974e1bc84`
  and manifest digest `0568cc8472d85ce72e19bfb8ff119f03e5d1e8619dc77b4c3d7db3476c25e46f`.
- Boundary: exact USD synthetic single-process evidence only. FX/fees/partial
  density, PostgreSQL runtime parity, distributed load, soak, and 100K/1M
  records remain unverified.

## E-385 — Server Finance Core adapter routes

- The server API now activates the forced-RLS `PostgresFinanceCoreRepository`
  for charts, account hierarchy, dimensions, journals, snapshot, and explicit
  entity/period/journal entry lifecycle operations. Every adapter call carries
  the authenticated tenant/workspace scope and re-checks the matching central
  Finance Core permission immediately before access.
- Focused route/scope tests pass, including sibling-workspace rejection and
  no-local-fallback behavior. A live-DSN route lifecycle test covers the same
  path when the configured non-privileged PostgreSQL role is available.
- Commit `d6c4b303` passed the local full suite/static/package gates and hosted
  CI `30965184880` (Python 3.11/3.12, server-boundaries, postgres-ha-dr,
  engine-parity, Docker-parity, object-storage), with Security `30965184879`,
  Docker `30965184887`, and CodeQL `30965184884` green. The optional live-DSN
  route test was not promoted as a separately executed hosted API claim.
- Boundary: legacy minimal posted-ledger requests remain on their compatibility
  adapter; this slice does not prove statutory consolidation, legal-book
  posting, live ERP/bank interoperability, write-back, throughput, HA/DR, or
  production readiness.

## E-386 — Bind intercompany evidence to PostgreSQL close runs

- **Status:** hosted-verified on commit `01f4de85`.
- Added `0064_pg_close_ic_links` and the forced-RLS immutable
  `consolidation_close_intercompany_links` table. A prepared close run can bind
  an existing `ice-*` artifact only through the server profile and
  `finance_core.manage`; the adapter replays the artifact and compares exact
  proposal fields, source period, reporting currency, workspace, matched IDs,
  unresolved count, and link digest.
- Approval now fails closed when a worksheet contains an
  `intercompany_transaction` elimination without exactly one matching linked
  artifact. Run detail and the additive close bundle expose the artifact
  result digests and matched elimination IDs.
- Complete local `uv run pytest -q`, Ruff, Mypy, Bandit, pip-audit, package
  build, and diff-check pass. Hosted CI `30968619652` passes Python 3.11/3.12,
  server-boundaries `92187914873` (including the live PostgreSQL close and
  intercompany-link path), engine parity, object storage, postgres-ha-dr
  `92187914777`, and Docker parity `92188812253`; Security `30968619726`,
  Docker `30968619657`, and CodeQL `30968619666` also pass.
- This remains bounded control-journal/evidence provenance, not
  statutory/legal-book posting, live ERP/bank write-back, throughput, HA/DR,
  compliance, certification, or production readiness.

## E-431 — Current live S3-compatible object-storage contract drill

- The real boto3-backed adapter completed against a disposable MinIO
  container pinned to image digest
  `sha256:13582eff79c6605a2d315bdd0e70164142ea7e98fc8411e9e10d089502a6d883`.
  Normal and Object Lock buckets proved hierarchical scope isolation,
  immutable conflict refusal, checksum tamper refusal, object-lock delete
  refusal, and cleanup; all five observations are true and the report digest
  is `5f4ef103abfe4b198bc64e348f554dc52e56d3ebb5d7f425faf1761ce6225c6a`.
- Boundary: one disposable single-node MinIO process with synthetic
  credentials/bytes. Replication, KMS, cross-site durability, provider
  interoperability, object-store HA/DR, malware scanning, authorized
  downloads, and production SLOs remain unverified.
- ADR: `docs/adr/0361-live-s3-object-storage-contract-drill.md`.

## E-432 — Remove hard-coded synthetic object-storage credentials from CI

- The digest-pinned CI MinIO job no longer stores a password literal in
  workflow `env` blocks. The startup and contract steps independently derive
  the same disposable credential from a non-secret seed at runtime, so the
  live boto3 contract remains authenticated without recording a reusable
  credential in repository text.
- `tests/test_s3_object_storage_live.py`, the closed supply-chain policy
  validator, Ruff, and `git diff --check` pass. No Gitleaks allowlist or rule
  weakening was added.
- Boundary: hosted Gitleaks history/tree execution remains required; this is
  CI secret-hygiene evidence, not a release approval or production claim.
- ADR: `docs/adr/0362-ci-synthetic-credential-hygiene.md`.

## E-433 — Current live Redis session and policy contract drill

- The real tenant-scoped Redis stores completed against Redis 7.4 Alpine
  digest `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`.
  The runtime proved tenant-key isolation, digest-only session persistence,
  shared policy-generation visibility across two clients, and cleanup; the
  report digest is
  `99fbd6b7aba969e0a41f4faa9e26d034e5e0f3b5a36e0e4e22bb2928ed9b44ca`.
- Boundary: one disposable single-node Redis process with synthetic keys and
  metadata. Replication, Sentinel/Cluster failover, cross-site durability,
  Redis HA, and production SLOs remain unverified.
- ADR: `docs/adr/0363-live-redis-session-policy-contract-drill.md`.

## E-434 — Full local regression after current runtime slices

- `uv run pytest -q --tb=short -ra` exits 0 in 356.1 seconds on the current
  Windows environment. No collection or executed test failure occurred.
- Declared PostgreSQL/Redis/S3 and Windows capability skips remain explicit;
  existing Starlette and legacy binary-financial-input warnings remain visible.
- Boundary: local compatibility only. Hosted Python/security/Docker matrices,
  statutory close, live vendors/write-back, independent HA/DR, distributed
  IAM, scale/soak, and release approval remain unverified.

## E-435 — Experimental retail POS settlement vertical slice

- Added the typed `retail-pos-settlement-v1` domain/application boundary for
  exported POS batches and processor settlements. Exact Money values, one
  currency per run, fees, refunds, chargebacks, scope mismatch, duplicate and
  unmatched detection, ambiguity refusal, tolerance decisions, deterministic
  ordering, input fingerprints, and decision digests are explicit.
- Added the local `reconforge retail settlement settlement-run` CLI, a closed
  digest-bound report schema, synthetic JSON/CSV fixtures, and the
  `retail-pos-settlement` declarative control pack. Runtime registry entry
  `retail.settlement` is experimental/implemented and has no database or
  network dependency because this first slice is export-based and non-posting.
- Focused retail/module/rules tests pass. The pack finds the expected
  missing-batch and net-variance exceptions; permutation replay produces the
  same decision digest; report tampering is rejected.
- Boundary: this does not prove live processor or ERP interoperability,
  settlement finality, fraud controls, statutory posting, write-back, API/UI
  persistence, HA/DR, production availability, or complete retail breadth.
- ADR: `docs/adr/0364-retail-pos-settlement-control-slice.md`.

## E-436 — Full local regression and release-tool gates after retail slice

- `uv run pytest -q --tb=short -ra` exits 0 in 343.2 seconds. No collection
  or executed test failure occurred; optional PostgreSQL/Redis/S3 and Windows
  capability skips remain declared, and existing Starlette/legacy financial
  input warnings remain visible.
- `uv run ruff check .`, `uv run mypy reconforge` (456 source files),
  `uv run bandit -q -r reconforge`, `uv run pip-audit --progress-spinner off`,
  the closed supply-chain policy validator, and `git diff --check` pass. The
  pip audit excludes the unpublished local distribution and reports no known
  vulnerabilities for auditable packages.
- Boundary: local evidence only. Hosted Python/security/Docker/browser gates,
  live processor/ERP write-back, statutory close, independent HA/DR,
  distributed IAM, scale/soak, and GitHub publication remain open.

## E-437 — Experimental bank statement to ledger control vertical slice

- Added the typed `bank-statement-control-v1` domain/application boundary for a
  local CAMT.053 statement and JSON ledger export. Exact Money values, one
  currency/tolerance policy, normalized references, booking-date windows,
  account/amount exceptions, duplicate IDs, ambiguity, unmatched records,
  deterministic ordering, input fingerprints, and decision digests are explicit.
- Added `reconforge bank statement control-run`, the closed digest-bound report
  schema, synthetic XML/JSON/CSV fixtures, and the
  `bank-statement-reconciliation` declarative control pack. Runtime registry
  entry `bank.cash-reconciliation` is experimental/implemented and has no
  database, provider, network, posting, or write-back dependency.
- Boundary: this does not prove bank authenticity, live bank/ERP interoperability,
  payment initiation, statutory posting, write-back, persistence/API/Studio,
  HA/DR, production availability, or complete banking breadth.
- ADR: `docs/adr/0365-bank-statement-control-slice.md`.

## E-438 — Full local regression and release-tool gates after bank control slice

- `uv run pytest -q --tb=short -ra` exits 0 in 344.6 seconds with no collection
  or executed failure. Optional PostgreSQL/Redis/S3 and Windows capability skips
  remain explicit, and existing Starlette/legacy financial-input warnings remain
  visible.
- `uv run ruff check .`, `uv run mypy reconforge` (459 source files),
  `uv run bandit -q -r reconforge`, `uv run pip-audit --progress-spinner off
  --timeout 60`, the closed supply-chain policy validator, `uv run python -m
  build --no-isolation`, and `git diff --check` pass. Pip-audit explicitly
  excludes the unpublished local distribution and reports no known
  vulnerabilities for auditable packages.
- Boundary: exact local Windows evidence only. Hosted matrices, live
  bank/ERP providers and write-back, statutory close, independent HA/DR,
  distributed IAM, scale/soak, and GitHub publication remain open.

## E-439 — Experimental manufacturing production-cost control vertical slice

- Added the typed `manufacturing-cost-control-v1` domain/application boundary
  for local production orders, material issues, completions, and scrap events.
  Exact Money/Quantity values, one currency/unit policy, standard/material and
  completion cost variance, planned-versus-completed quantity, scrap limits,
  unknown-order lineage, deterministic ordering, input fingerprints, and
  decision digests are explicit.
- Added `reconforge manufacturing cost-control run`, the closed digest-bound
  report schema, synthetic JSON/CSV fixtures, and the
  `manufacturing-production-cost` declarative control pack. Runtime registry
  entry `manufacturing.cost-control` is experimental/implemented and has no
  database, provider, network, posting, or write-back dependency.
- Boundary: this does not prove statutory or standard-cost valuation policy, live
  ERP/MRP interoperability, inventory/WIP/GL posting, write-back,
  persistence/API/Studio, HA/DR, production availability, or complete
  manufacturing breadth.
- ADR: `docs/adr/0366-manufacturing-production-cost-control-slice.md`.

## E-440 — Full local regression and release-tool gates after manufacturing slice

- `uv run pytest -q --tb=short -ra` exits 0 in 353.3 seconds with no collection
  or executed failure. Optional PostgreSQL/Redis/S3 and Windows capability skips
  remain explicit, and existing Starlette/legacy financial-input warnings remain
  visible.
- `uv run ruff check .`, `uv run mypy reconforge` (462 source files),
  `uv run bandit -q -r reconforge`, `uv run pip-audit -s osv --progress-spinner
  off --timeout 30` (no known vulnerabilities), the closed supply-chain policy
  validator, `uv run python -m build --no-isolation`, and `git diff --check` pass.
- Boundary: the OSV audit excludes the unpublished local distribution and is
  local dependency evidence only; hosted matrices, live ERP/MRP
  providers/write-back, statutory valuation/posting, independent HA/DR,
  distributed IAM, scale/soak, and GitHub publication remain open.
## Current slice — professional invoice-to-payment control (2026-08-05)

`professional.invoice-payment` is implemented as an experimental local,
non-posting module. The typed control compares exported invoices and client
payments using exact Money, normalized references, client identity, and a
bounded due-date window. It emits explicit matched, exception, ambiguous,
unmatched-invoice, and unapplied-payment decisions with a replay-verifiable
digest. Focused tests and the control-pack validation pass. E-442 is in progress
for the full local regression/static/security/package gate; no GitHub publication
has occurred.
The professional invoice/payment slice has now passed E-442: full local
pytest/static/security/package gates are green. This closes only the local
compatibility gate for the slice; the coherent-breadth workstream and all live
provider, posting, write-back, external-operator, hosted, and production gates
remain open. No GitHub publication occurred.
The historical Python 3.11 dependency-collection failure is not reproduced
with the current workflow profile: all named optional modules import and the
seven previously failing test files pass under locked `--all-extras`, with one
declared live-PostgreSQL skip. This is local compatibility evidence, not a
hosted CI result.
A fresh network-enabled public-data run also passed on the clean current
revision: 11 official responses, 967 matched, zero unmatched/exceptions, and
replay/permutation checks. It is useful open-data evidence for the deterministic
engine, but remains a maintainer run and does not satisfy the external-operator,
customer, independent-review, hosted-attestation, or production gates.
The PostgreSQL failure surfaces from the supplied CI log were then exercised on
the local PostgreSQL 17.10 service with an isolated database. Alembic reached
`0065_pg_deferred_tax`; the live PostgreSQL/SQLite metrics parity test and the
Alembic downgrade/re-upgrade command test both passed with the non-privileged
application role. This closes only the local reproduction of those two failures;
the hosted runner and native `pg_dump` backup capability remain unverified.
Checksum-verified Gitleaks 8.30.1 also scanned all 490 local commits and the
current tree with zero leaks. The earlier hosted one-leak result is therefore
not reproduced locally, but hosted security attestation remains open.
The same seven historical dependency-collection test files also pass under the
locked Python 3.12 all-extras profile: 48 passed, one declared live-PostgreSQL
skip, zero collection errors. Together with E-443, this closes local reproduction
on both supported CI Python versions without asserting hosted matrix success.
The digest-pinned production image also builds locally on Docker Engine 29.6.2;
its doctor, sample validation, audit-basic pack, and professional fixture CLI all
pass. The doctor still reports the sample's ten intentional warnings, so this is
container parity evidence rather than a claim of warning-free production data.
The Studio frontend also passes its local release gates: locked npm install,
zero high-or-worse audit findings, typecheck, 55 unit/component tests, production
build, and 11 Playwright paths. Five Playwright paths remain explicit skips for
live hosting/session configuration, so deployed HTTPS and hosted browser evidence
are still open.
The current locked Python 3.12 engine/golden selection also passes 55/55 tests
without skips. This is a single current-compatible environment and does not
replace the four lower-bound/current hosted matrix cells.
The live PostgreSQL 10K and 100K durable-job scale tests also pass together on
an isolated PostgreSQL 17.10 database with the non-privileged role; cleanup
removed the database. This strengthens the bounded single-host concurrency
evidence only and leaves soak, HA, host-loss, RPO/RTO, and production capacity
unverified.
The installed distribution also exposed a real namespace collision: the old
duplicate `reconforge/reliability.py` shadowed the `reconforge/reliability/`
package in non-editable execution and broke the quorum simulation script. The
duplicate was removed, ADR 0368 and a regression were added, and a fresh
non-editable Python 3.12 environment now runs the script successfully. This is
an importability fix, not deployed HA/DR evidence.
After the namespace repair and YAML evidence correction, the complete local
pytest/static/security/package gate is green again: pytest 0 in 353.3s, Mypy
465 files, Ruff, Bandit, OSV audit, supply-chain policy, build, and diff-check
all pass. Declared capability skips and existing warnings remain visible.
The native PostgreSQL backup contract also passes locally at the unit/security
boundary (11 passed); its one live test remains explicitly skipped because the
Windows host has no native `pg_dump`/`pg_restore`/`createdb`/`dropdb`/`psql` set.
The retry and fail-closed no-dump paths are therefore verified, while hosted
native-tool execution remains open.
The read-only network connector now preserves fixed query strings when they
are part of an exact operator-declared HTTPS destination. Credentials,
fragments, non-visible ASCII, undeclared endpoints, private DNS answers,
redirects, unbounded retries, and oversized responses remain fail-closed.
Focused network/SDK/database connector contracts pass 35/35 under ADR 0369.
Public no-auth registrations emit no authorization header, while credentialed
registrations require a secret reference. This enables fixed-parameter public
REST endpoints but does not establish live provider availability,
authentication interoperability, write-back, or production operations.
The exact PostgreSQL grouped-matching 500-partition and 10K-partition profiles
also pass on isolated PostgreSQL 17.10 databases with the non-privileged role:
67.9s and 336.2s respectively. The 10K profile completes 1,000 runs and 10,000
partitions over all five declared grouped modes with 24,000 result rows, no
duplicate identities, no failed runs, and no active runs. Both databases were
dropped after verification. This is bounded single-host synthetic evidence and
does not establish production throughput, soak, queue HA, host-loss,
cross-host fairness, RPO/RTO, or capacity sizing.
The current-revision public-financial verifier was also retried from a clean
tree. Treasury and World Bank isolated fetches were reachable, but the pinned
OpenDataNI March 2026 artifact returned HTTP 403, so the complete experiment was
not counted as passed. E-444 remains the last complete public-data run; this is
external source-availability drift, not evidence of a code regression.
The subsequent full local regression after these changes exits 0 in 379.8s.
No executed test failed; declared PostgreSQL/Redis capability skips and existing
framework/legacy-input warnings remain visible. This is current local
compatibility evidence only, not hosted matrix or release approval.
The final local static/security/package gate is also green: Ruff, Mypy over
465 source files, Bandit, OSV pip-audit after a successful retry, the closed
supply-chain validator, package build, and diff-check all pass. Existing
Bandit suppression warnings remain visible; hosted security/provenance and
release approval remain external.
The connector platform now includes a concrete World Bank public REST reference
connector. It pins the DS01556/RS00963 dataset to three exact page offsets,
uses no-auth public HTTPS through the shared pinned transport, rejects schema
drift/non-finite values, and computes canonical permutation-stable digests.
Focused tests pass and an opt-in live run fetched the first 1,000-row page with
source count 2,890. This is interoperability reference evidence only; source
freshness/availability, ERP or bank vendor integration, write-back, and
production operations remain open.
The hosted `server-boundaries` workflow now bootstraps and verifies the native
PostgreSQL client binaries before its live gates, removing the runner-image
assumption behind the supplied backup failure. This is workflow hardening, not
proof that hosted encrypted backup/restore passes; a fresh hosted run remains
required and GitHub publication is intentionally deferred.
The full local run exposed one legitimate inventory drift from the new network
connector: its intentional direct JSON parse was not declared. I closed that
drift by adding the exact FI-023 allowlist entry and connector test evidence;
the focused inventory contract now passes. No parser call was hidden or
silenced.
The current full local regression now exits 0 in 348.9s after the connector,
inventory, and CI bootstrap changes. No executed test failed; declared live
service capability skips and existing warnings remain visible. This closes the
local compatibility gate, not the hosted release gate or the unresolved
external HA/DR, vendor, and native-backup evidence.
The final local static/package gate also passes on this head: Ruff, Mypy over
466 source files, Bandit, OSV pip-audit, supply-chain policy, package build,
and diff-check. The one new public-manifest Bandit suppression is narrowly
scoped to a non-secret descriptive field; existing reviewed warnings remain
visible. Hosted security/provenance and release approval remain open.
Checksum-verified Gitleaks 8.30.1 also scanned all 508 local commits and the
current tree with zero leaks. This local reproduction does not erase the
previous hosted repository-security failure; the hosted workflow still must be
rerun before any publication decision.
The SDK documentation is now current with the implementation: it lists the
governed reference portfolio and gives the World Bank connector's exact bounded
usage and live-test command, without implying live SAP/Odoo/bank connectivity or
write-back. GitHub publication remains deferred.
The execution backlog itself was re-parsed after the latest evidence entries;
it now has 133 unique tasks and valid YAML. This closes documentation
serialization drift only and does not change the still-open hosted release,
provider, HA/DR, or native-backup gates.
The backlog has since grown with the current HA/DR, object-storage, and Redis
runtime and current-tree gate entries; its latest parse is 148 unique tasks
(E-460 through E-479 included).
The fresh repeated PostgreSQL HA/DR drill now provides stronger bounded runtime
evidence: three Docker 17.10 primary/standby cycles passed encrypted restore,
fencing, partition refusal, manual failover/failback, zero-loss sentinel replay,
and cleanup. The report remains explicitly single-host/manual/synthetic and does
not close cross-host DR, automatic failover, quorum, or production SLO gates.
The current MinIO object-storage drill also passes all five scoped integrity and
cleanup invariants against the image digest recorded in E-469. This strengthens
the local adapter evidence only; replication, KMS, cross-site durability,
object-store HA, and production SLO remain open.
The current Redis drill also passes tenant-key isolation, hashed-session-token
storage, shared policy-generation visibility, and cleanup against its recorded
image digest. This strengthens the local session/policy adapter evidence only;
Redis replication, Sentinel/Cluster failover, cross-site durability, HA, and
production SLO remain open.
The PostgreSQL close focus then exposed and fixed an internal-vs-business period
identity mismatch in intercompany artifact binding; the isolated PostgreSQL
17.10 financial contracts now pass 18/18. This is a correctness closure for the
local adapter only; statutory policy, hosted CI, live providers, and HA/DR
remain open.
The database-reference connector also passes its current PostgreSQL live focus
3/3 with named read-only queries and tenant isolation. This strengthens the
deployment-provided view adapter only; live ERP/bank vendors and write-back
remain open.
The fresh IAM/RLS focus also passes 23/23 selected PostgreSQL contracts under a
non-privileged role. This strengthens local tenant isolation and policy lifecycle
evidence only; federation interoperability, distributed invalidation, complete
surface adoption, HA/DR, and production IAM assurance remain open.
The final current-tree regression after these evidence artifacts exits 0 in
364.3s, and the current Ruff/Mypy/package/diff gate remains green. This closes
the local regression/package checkpoint only; declared external-service skips,
hosted matrices, hosted security/provenance, live vendor interoperability,
independent HA/DR, and production approval remain open.
The current grouped-matching 1M profile also ran twice from this tree with
identical effect and manifest digests and zero ambiguity, unmatched, engine, or
permutation mismatches. This strengthens deterministic single-process algorithm
evidence only; PostgreSQL parity, distributed capacity, soak, and production
SLO remain open.
The current PostgreSQL durable-job backpressure profile also passes with a
four-job lane cap, 24 rejected/retried submissions, complete 64-job/256-effect
drain, zero duplicates, and exact per-lane fairness. This strengthens bounded
single-host queue correctness only; capacity, queue HA, soak, RPO/RTO, and
production SLO remain open.
The current full regression after the PostgreSQL period-binding correction also
exits 0 in 356.4s. No collected or executed test failed; declared external
service/platform skips and existing warnings remain visible. This is a local
compatibility checkpoint only; hosted matrices, native backup tooling, hosted
security/provenance, live providers/write-back, statutory accounting,
independent HA/DR, and production approval remain open.
The live API follow-up then found and fixed a real authorization-consistency
defect: FinanceRead's any-of grant was narrowed to read-only during the second
server scope check. The legacy identity fixture also explicitly selects the
ledger compatibility boundary after Finance Core activation. On a fresh
PostgreSQL 17.10 database, the selected live API suite passes 24/24. This is a
route-consistency and bounded runtime closure only; complete enterprise IAM,
federation, providers/write-back, HA/DR, and production approval remain open.
The post-fix full local regression also exits 0 in 354.3s with no collection or
executed failure; declared capability skips and existing warnings remain
visible. This confirms current-tree compatibility after E-479 only and does not
replace hosted security/provenance, live-provider, statutory, HA/DR, or release
evidence.
The subsequent PostgreSQL application-parity batch passes all 117 selected
tests on a fresh migration-head 17.10 database under the non-privileged role,
including Finance Core API, master data, close, evidence, matching,
payables/receivables, inventory, journals, scopes, and workspace UoW. This is
bounded single-node synthetic parity evidence only; full parity, hosted backup,
providers/write-back, HA/DR, scale, and production approval remain open.
