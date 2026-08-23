# Execution State

Updated: 2026-08-23

## E-889 — Workflow contract protects hardened image gates (2026-08-23)

- `tests/test_container_hardening_workflow.py` parses both CI and release
  workflows, requires `--read-only`, `--cap-drop=ALL`, and
  `--security-opt=no-new-privileges`, and checks that release smoke precedes
  registry login and push.
- The focused test and Ruff pass. This protects workflow intent locally; it
  does not replace a fresh hosted run.

## E-888 — Release candidate hardened image gate (2026-08-23)

- `.github/workflows/release.yml` now runs the exact scanned candidate image
  with a read-only root filesystem, all Linux capabilities dropped, and
  `no-new-privileges` before registry login, push, or attestation.
- This prevents a candidate that only passes an unconstrained local smoke from
  reaching publication. It remains a hosted Linux smoke, not multi-arch,
  host-isolation, registry-availability, or production evidence.

## E-887 — Hardened container smoke required in CI (2026-08-23)

- The required `docker-parity` job now executes `reconforge doctor` with a
  read-only root filesystem, all Linux capabilities dropped, and
  `no-new-privileges`, in addition to the ordinary container checks.
- This transfers the local hardening boundary into hosted CI when the workflow
  runs. It does not prove host isolation, seccomp completeness, multi-arch
  parity, registry provenance, or production orchestration.

## E-886 — Local Docker Scout CycloneDX SBOM (2026-08-23)

- `docker scout sbom local://reconforge:current --format cyclonedx
  --output output/docker-scout-current-sbom.json` succeeded.
- The generated JSON is valid CycloneDX with 82 components, 331,173 bytes,
  and SHA-256
  `41af050007ebf534ebd42d4354c5e5c4fb7ad0606002e38bd7076354f2195c7e`.
- The raw file remains generated output; release SBOM signing/provenance and
  hosted artifact verification remain separate requirements.
- `python -m build --no-isolation` completed successfully afterward, and
  `reconforge_erp.egg-info/SOURCES.txt` contains ADR 0592, confirming the
  evidence decision is included in the source distribution manifest.

## E-885 — Docker Scout base-layer scan (2026-08-23)

- `docker scout cves local://reconforge:current --only-base --format packages`
  returned exit code 0 and reported `0C 0H 0M 0L` for the current base-layer
  view.
- The result supports retaining the current Python 3.11 Alpine digest while a
  future Python 3.12 upgrade is evaluated through the required compatibility
  matrix; no urgent base vulnerability remediation is claimed.

## E-884 — Python base-image upgrade remains gated (2026-08-23)

- Docker Scout recommends a smaller Python 3.12 Alpine alternative, while the
  current digest-pinned Python 3.11 Alpine line is up to date in its tag line.
- No base-image change was made. E-884 is intentionally `planned` until the
  supported Python/engine matrix, package/air-gap, Docker/API/web smoke, and
  rollback gates are executed against a refreshed digest.

## E-883 — Current Docker Scout local image scan (2026-08-23)

- Docker Scout `v1.24.0` scanned `local://reconforge:current` at digest prefix
  `e86d4871981c`, indexed 82 packages, reported `0C 0H 0M 0L`, and exited 0.
- The report uses an explicit local image reference and is recorded at
  `docs/execution/security/docker-scout-current-2026-08-23.md`.
- This is one local package scan, not hosted scanner parity, registry
  provenance/signing, malware/license assurance, or production security.

## E-882 — Hardened Docker runtime smoke (2026-08-23)

- `docker image inspect` reports configured user `10001:10001` and working
  directory `/app`; `docker run ... id` confirms the non-root `reconforge`
  identity.
- `reconforge doctor` succeeds under
  `--read-only --cap-drop=ALL --security-opt=no-new-privileges`.
- This is a local runtime-hardening boundary only. Image vulnerability
  scanning, signing/provenance, seccomp profile review, multi-arch parity, and
  production orchestration remain open.

## E-881 — Current Docker image parity and runtime smoke (2026-08-23)

- `docker build -t reconforge:current .` completed successfully; the local
  image manifest digest was `sha256:e86d4871981ce2e466c257428b906a9d3e9929bce61fb1224f67cd3fc90ffb6e`.
- Container smoke commands passed: `reconforge doctor`,
  `reconforge validate examples/sample_data`, and
  `reconforge rules validate --pack control-packs/audit-basic`.
- Doctor reported zero errors and ten warnings; validation reported the same
  declared synthetic sample-data warnings. No warning was converted to zero or
  hidden. This is one local Docker runtime, not a hosted image/provenance or
  production deployment claim.

## E-880 — Package membership after release-governance additions (2026-08-23)

- `python -m build --no-isolation` completed successfully after the latest CI,
  release, and evidence additions.
- `reconforge_erp.egg-info/SOURCES.txt` contains ADRs 0585, 0586, and 0587 plus
  the dated PostgreSQL durable-job benchmark JSON/Markdown artifacts.
- Benchmark index, release SBOM, signed-release, SLSA, and maturity policy
  tests pass; this is package/local evidence, not hosted provenance.

## E-879 — CI operational gates depend on web quality (2026-08-23)

- `docker-parity` and `server-boundaries` now declare `needs: [test, web]`.
- This makes a failed browser quality gate propagate to the primary Docker and
  live server operational cells while preserving independent parallel assurance
  boundaries for engine parity, object storage, and HA/DR.

## E-878 — Release workflow web artifact recheck (2026-08-23)

- `.github/workflows/release.yml` now rechecks the exact signed tag's web
  artifact after npm audit and before Python/package/image publication.
- The release job runs locked npm install, TypeScript typecheck, Vitest,
  production build, Chromium installation, and standard Playwright E2E using
  the pinned Node 22 toolchain.
- Live API-session and HTTPS production-bundle scenarios remain opt-in; this
  gate improves release integrity without inventing external credentials or
  provider evidence.

## E-877 — Web client required CI gate (2026-08-23)

- `.github/workflows/ci.yml` now includes a dedicated `web` job using pinned
  checkout/setup-node actions and Node 22 with npm lockfile caching.
- The job enforces typecheck, Vitest, production build, Playwright Chromium
  installation, and standard browser/accessibility E2E on normal push/PR CI.
- Explicit live API-session and HTTPS production-bundle scenarios remain
  opt-in, so CI does not invent credentials, provider access, or production
  deployment evidence.

## E-876 — Current provider-neutral transport conformance (2026-08-23)

- `tests/test_connector_provider_tls_sandbox.py`,
  `tests/test_connector_writeback_network.py`, and
  `tests/test_connector_network.py` passed 70 tests locally.
- Coverage includes certificate/pin validation, bounded retry/backoff,
  idempotency and acknowledgement binding, public-address egress refusal, and
  deterministic synthetic failure injection. This remains provider-neutral
  loopback evidence and does not prove live ERP/bank interoperability,
  credentials/vault behavior, or production egress.

## E-875 — Current PostgreSQL durable-job backpressure and soak (2026-08-23)

- The live local PostgreSQL run used `reconforge_app` and passed both targeted
  profiles without skips: backpressure completed 64/64 jobs and 256/256
  effects with zero duplicates and drained queue/running depth; repeated soak
  completed 3/3 iterations with 192/192 jobs and 768/768 effects, zero residue,
  and identical effect digests.
- The schema-closed report is recorded in
  `docs/execution/benchmarks/postgres-durable-job-current-2026-08-23.json` and
  indexed with its SHA-256. This is single-host synthetic evidence only; queue
  HA, cross-host fairness, capacity/SLO, RPO/RTO, and production operation are
  not claimed.

## E-874 — Current web client verification and E2E runtime portability (2026-08-23)

- `npm --prefix apps/web ci` completed with zero reported npm vulnerabilities.
- TypeScript typecheck, 15 Vitest files / 75 tests, and the production Vite
  build passed.
- Playwright passed 16 tests, including English/Arabic accessibility, keyboard
  focus, redaction, responsive/mobile routes, and screenshot flows; five tests
  were explicit opt-in live-session/HTTPS scenarios and remained skipped.
- `RECONFORGE_WEB_PORT` now controls the loopback E2E/Vite port while retaining
  4173 by default, allowing constrained CI hosts to select an available port.

This is local web verification, not hosted browser compatibility or production
HTTPS/API deployment evidence.

## Current full local regression gate (2026-08-23)

- `python -m pytest -q` completed with exit code 0 after the backlog contract
  rerun; the initial run exposed duplicate short YAML task entries, which were
  removed and verified by the phase/backlog contract suite before rerunning the
  full repository suite.
- Existing declared capability skips and framework/legacy-financial-input
  warnings remain visible. This is one local Windows/Python 3.14 run, not a
  hosted compatibility matrix or release approval.

## E-873 — Refresh static security and dependency gate evidence (2026-08-23)

- Bandit completed without failed findings after documenting the intentional
  Boolean evidence-field false positive in `reconforge/cli.py`.
- `python -m pip_audit -l --progress-spinner off` reported no known
  vulnerabilities; the local `reconforge-erp` project itself is not on PyPI
  and was listed as not auditable.
- Deployment/security focused tests passed 17 tests and Ruff passed.
- This remains static/local evidence, not penetration, hosted, provenance,
  malware, license, reachability, or production-security assurance.

## E-872 — Refresh release manifest and SBOM pipeline contract evidence (2026-08-23)

- `tests/test_release_sbom_pipeline.py`,
  `tests/test_signed_release_pipeline.py`, and
  `tests/test_slsa_provenance_plan.py` passed 28 tests.
- The contract suite covers exact release identity, subject SHA-256 binding,
  deterministic CycloneDX 1.7 output, source/package/image cross-binding,
  tamper and forbidden-path rejection, and release workflow gate ordering.
- This is local repository-controlled builder evidence only. No hosted signed
  provenance, registry signature, SLSA level, or independent verification is
  claimed; the optional cyclonedx-py utility was unavailable due to a missing
  `chardet` dependency.

## E-871 — Refresh current air-gapped recovery and upgrade rollback (2026-08-23)

- The full `verify_airgap_install.py` run completed in the digest-pinned
  network-none/read-only container.
- Identity recovery restored two local users, restored zero old sessions,
  rejected the wrong key, and preserved a valid audit chain at schema version
  43.
- The tagged `0.7.0 -> 0.7.1` cutover and exact rollback passed with zero
  network inputs; cleanup completed.
- Offline signature trust, hardware/physical air-gap custody, OCI verification,
  multi-node recovery, and production readiness remain unverified.

## E-870 — Refresh current offline base-install drill evidence (2026-08-23)

- `verify_airgap_install.py --base-install-only` completed successfully using
  the digest-pinned `python:3.14.1-slim` Linux image.
- The wheel-only bundle contained 68 entries and 100,627,876 bytes; install
  used `--network none`, read-only root, `--no-index`, `--no-deps`, and
  `--require-hashes`.
- `reconforge doctor` exited zero and the disposable container cleanup passed.
- This does not cover offline signatures, identity recovery, backup/restore,
  upgrade/rollback, physical air-gap isolation, or production readiness.

## E-869 — Refresh current PostgreSQL identity and scope governance runtime (2026-08-23)

- Eleven focused tests passed against PostgreSQL 16.14 using the
  `reconforge_app` application role.
- Coverage includes tenant-isolated identity administration, session
  invalidation, step-up requirements, last-administrator protection,
  append-only privileged assertions, deterministic scope grants/revocation,
  and policy-scope analysis.
- This is bounded synthetic single-host IAM evidence; external IdP/SSO,
  universal MFA, distributed revocation, production PAM, and independent IAM
  assurance remain open.

## E-868 — Refresh current PostgreSQL write-back receiver failover matrix (2026-08-23)

- The current matrix passed on digest-pinned PostgreSQL 16.14 and 17.10;
  every cell passed all 23 declared checks and cleanup.
- It observed acknowledged response-loss replay without a duplicate effect,
  synchronous partition uncertainty, one application after rejoin, exact
  fencing before promotion, endpoint rediscovery after restart, and equal
  SQLite/PostgreSQL canonical history with acknowledged-effect RPO `0`.
- This remains a two-node-per-version, single-host synthetic matrix with
  manual control; provider semantics, cross-host HA, and production
  exactly-once behavior remain open.

## E-867 — Refresh current PostgreSQL consolidation-close runtime evidence (2026-08-23)

- The focused close/consolidation/server suite passed 32 tests against the
  current PostgreSQL 16.14 service.
- The application identity was `reconforge_app` with `rolsuper=false` and
  `rolbypassrls=false`.
- Runtime coverage includes replay identity, tenant/RLS isolation,
  maker-checker certification, period lock/reopen, reversal controls,
  digest-bound close evidence, and server HTTP scope checks.
- This is synthetic, single-host runtime evidence only; statutory posting,
  hosted parity, HA/DR, production approval, and independent assurance remain
  open.

## E-866 — Refresh current bounded PostgreSQL HA/DR drill evidence (2026-08-23)

- `.github/scripts/verify_postgres_ha_dr.py` completed one clean disposable
  Docker run using PostgreSQL 17.10-alpine on Docker Engine 29.7.2.
- The report records encrypted isolated restore, exact-ID fencing, synchronous
  remote-apply, zero acknowledged sentinel loss, failover RTO 11.093 seconds,
  and failback RTO 1.041 seconds with final sequences `[1, 2, 3, 4]`.
- This remains one synthetic single-host failure domain with a manual
  controller; host/zone loss, automatic failover, production SLOs, and
  enterprise readiness remain unverified.

## E-865 — Refresh live PostgreSQL security governance/policy evidence (2026-08-23)

- `tests/test_postgres_security_governance.py` and
  `tests/test_postgres_policy_analysis_runtime.py` pass 5/5 with the current
  PostgreSQL service and `reconforge_app` (`rolsuper=false`, `rolbypassrls=false`).
- Runtime evidence covers tenant isolation, atomic retention/resource controls,
  and policy maker-checker scope. It is not a compliance/certification claim.

## E-864 — Add live PostgreSQL receiver idempotency gate (2026-08-23)

- Added a live-gated receiver test for atomic receipt/effect persistence,
  idempotent replay, stable canonical history digest, and delete refusal under
  the non-privileged application role.
- The current local PostgreSQL run passes 9/9 in the receiver test file; no
  provider transport or production receiver claim is made.

## E-863 — Refresh live PostgreSQL write-back append-only evidence (2026-08-23)

- `tests/test_postgres_writeback.py` passed 3/3 with the local PostgreSQL
  16.14 service and `reconforge_app` non-privileged role.
- Scoped idempotent history, append-only/tamper boundaries, and ERPNext payment
  history replay passed. Provider dispatch, secrets, cross-host recovery, and
  production write-back remain outside the evidence.

## E-862 — Refresh live PostgreSQL grouped 500/10K scale evidence (2026-08-23)

- With the same PostgreSQL 16.14 digest and `reconforge_app` non-superuser
  role, the live 500-partition and 10K-partition scale tests both passed.
- The declared profiles reported zero failed runs, duplicate result identities,
  and active runs. These are bounded local Docker measurements, not throughput
  sizing or production SLO evidence.

## E-861 — Refresh live PostgreSQL grouped matching replay evidence (2026-08-23)

- Runtime command passed with PostgreSQL 16.14 image digest
  `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777`:
  `tests/test_postgres_grouped_matching_runtime.py` and
  `tests/test_postgres_matching_application.py` (8 passed).
- The application role was `reconforge_app` with `rolsuper=false` and
  `rolbypassrls=false`; grouped persistence, tenant scope, and process-crash
  resume passed. This is one disposable host and synthetic data only.

## E-860 — Replay-test every registered matching strategy family (2026-08-23)

- The contract suite now re-executes all five registered families: indexed,
  grouped, duplicate detection, carry-forward, and reversal pairing.
- Each family reproduces the exact canonical envelope; indexed runs through a
  migrated SQLite service. This remains local strategy evidence.

## E-859 — Add deterministic strategy re-execution replay verifier (2026-08-23)

- `replay_strategy_result` now re-executes a strategy against the original
  request and compares canonical envelopes, after identity/digest validation.
- Successful replay and tampered-output rejection are covered by the matching
  contract suite. This is deterministic local evidence, not hosted parity.

## E-858 — Expose offline matching envelope validation CLI (2026-08-23)

- Added `reconforge match validate-result-envelope` for local, no-network
  validation of one closed matching result envelope.
- Output includes strategy/digest metadata and explicitly marks that a request
  is required for full replay verification; it never claims replay from the
  envelope alone.

## E-857 — Publish versioned matching result envelope schema (2026-08-23)

- Added `matching_strategy_result_envelope.v1.schema.json` with closed top-level
  fields, schema version, semantic strategy version, and digest patterns.
- Runtime contract tests validate emitted payloads against Draft 2020-12 and
  reject unsupported schema versions. This remains bounded evidence.

## E-856 — Enforce replay envelope at PostgreSQL worker boundaries (2026-08-23)

- Grouped and sequential PostgreSQL adapters now JSON round-trip and verify
  every strategy result before backend-specific projection.
- Worker contract suites and static checks pass. This is bounded local worker
  evidence; hosted multi-engine and production runtime evidence remain open.

## E-855 — Add closed JSON replay envelope for strategy results (2026-08-23)

- Strategy results now have a backend-neutral JSON-safe envelope with strict
  field closure and reconstruction. Replay verification covers strategy
  identity/version and all existing digests after transport serialization.
- The matching strategy contract suite and static checks pass. This is a
  transport/replay contract, not hosted cross-engine runtime evidence.

## E-854 — Bind strategy identity/version to matching results (2026-08-23)

- Matching strategy results now carry explicit strategy ID and version in
  addition to manifest/input/decision digests. Replay verification can reject
  identity or version drift at the adapter boundary.
- Contract plus PostgreSQL grouped/sequential worker suites pass; this closes
  result attribution only and does not prove cross-engine production readiness.

## E-853 — Compose regulated admission evidence (2026-08-23)

- Added a composite offline verifier and CLI that require complete regulated
  profile findings plus a non-local customer-managed key manifest, and bind
  child/composite digests.
- Focused admission/key/deployment/inventory tests pass 50/50, Ruff and Mypy
  pass. It remains a prerequisite check, not provider or production proof.

## E-852 — Add provider-neutral managed-key custody evidence (2026-08-23)

- Added a closed non-secret key custody manifest and
  `deployment verify-key-manifest` for provider/key identity, active status,
  customer ownership, AES-256-GCM purpose, scope, and rotation bounds.
- Focused key/deployment/inventory tests pass 44/44, Ruff and Mypy pass. No KMS,
  HSM, secret, key-byte, or provider-runtime claim is made.

## E-1006 progress audit (2026-08-23)

- E-1006 is now explicitly `in_progress` rather than `planned`; E-849 through
  E-851 provide the matrix, safe CLI reader, and profile-digest binding.
- Closure is still blocked by the declared scope: mode-specific operational
  runbooks and independent runtime drills must be current for every edition,
  and regulated key custody/independent failure-domain evidence remains open.

## E-851 — Bind runtime evidence to the immutable profile digest (2026-08-23)

- Runtime evidence now requires the exact selected edition profile digest and
  rejects profile drift or mismatched evidence before returning findings.
- Focused runtime/readiness tests pass 12/12, Ruff and Mypy pass. This binds
  local evidence identity only; external runtime enforcement remains open.

## E-850 — Expose deployment readiness evidence through the CLI (2026-08-23)

- Added `reconforge deployment readiness [--edition]`, backed by bounded safe
  YAML ingress, closed matrix validation, repository-contained evidence-path
  checks, and a canonical matrix digest. It performs no external calls or
  mutation.
- Focused readiness/runtime/profile/worker/inventory tests pass 36/36; Ruff and
  Mypy pass. The CLI reports partial/open evidence and cannot promote it.

## E-849 — Consolidate mode-specific deployment readiness evidence (2026-08-23)

- Added a schema-validated matrix covering Community, Team, Enterprise, and
  Regulated across eight common gates. It records only scoped/partial/open
  status and binds every evidence reference to a repository path.
- Matrix tests pass 2/2, with schema closure and unresolved regulated key and
  failure-domain gates explicitly asserted. No readiness claim is inferred.

## E-848 — Add digest-bound deployment runtime evidence (2026-08-23)

- Added a strict offline manifest for one deployment edition and the exact
  runtime facts consumed by profile validation, with deterministic digest and
  explicit findings. Added `deployment verify-runtime-evidence` CLI command.
- Focused runtime/profile/worker/inventory tests pass 31/31; Ruff and Mypy
  pass. The manifest is evidence input only and does not probe external
  systems or establish production readiness.

## E-847 — Expose worker manifest verification through the CLI (2026-08-23)

- Added `reconforge deployment verify-worker-manifest` for deterministic,
  network-free verification and digest display of a closed worker permission
  manifest. Invalid JSON/contracts fail closed; no IAM mutation occurs.
- Focused CLI/manifest/profile/inventory gates pass 18/18, Ruff and Mypy pass.
  Full `python -m pytest -q` exits 0 on the resulting tree. Hosted IAM
  enforcement remains unproven.

## E-846 — Add offline digest-bound worker permission manifest verifier (2026-08-23)

- A pure verifier validates the hosted worker permission manifest and emits a
  deterministic digest suitable for runtime evidence binding; it never mutates
  IAM or uses network access.
- Focused manifest/profile tests pass 15/15. Provisioning and hosted IAM remain
  unproven. Full `python -m pytest -q` exits 0 over the 3,119-test collection.

## E-845 — Gate hosted deployment profiles on worker discovery separation (2026-08-23)

- Hosted profile validation now requires explicit runtime evidence for separate
  worker discovery and execution permissions; Community remains local-first.
- Focused deployment-profile tests pass 9/9. Provisioning and production IAM
  rollout remain unproven. Full `python -m pytest -q` exits 0 over the
  3,119-test collection.

## E-844 — Separate reconciliation discovery and execution permissions (2026-08-23)

- Optional `discovery_policy_permission` enables least-privilege queue
  enumeration; claim/execution retain `policy_permission`, with explicit legacy
  fallback when unset.
- Focused tests pass 33/33 with one declared live PostgreSQL skip. Fleet
  rollout and production IAM enforcement remain unproven. Full
  `python -m pytest -q` on commit `7f44db68` exits 0 over 3,119 tests.

## E-843 — Propagate reconciliation exposure into worker policy rechecks (2026-08-23)

- The API persists exact `policy_amount` rule metadata; worker tenant and
  pre-claim scoped checks receive the same Decimal exposure before execution.
- Focused API/worker/policy tests pass 32/32 with one declared live PostgreSQL
  skip. Full `python -m pytest -q` exits 0 over the 3,119-test collection.
  Discovery-lane universal policy and production IAM remain unproven.

## E-842 — Bind reconciliation run submission to amount-bounded ABAC (2026-08-23)

- Canonical input amounts are parsed exactly and their gross absolute sum is
  passed to server policy before run persistence; incomplete coverage remains
  `None` for fail-closed bounded policies.
- Focused API tests pass 3/3; the post-slice full regression completed with exit
  code 0 over 3,119 collected tests. Universal route/job adoption and
  production IAM remain unproven.

## E-841 — Bind ownership-change preparation to amount-bounded ABAC (2026-08-23)

- Typed ownership-change inputs are converted before policy; exact gross
  exposure combines ownership delta and consideration before persistence.
- Focused route/domain/dependency tests pass 19/19 with one declared live
  PostgreSQL skip; universal route adoption and production IAM remain unproven.

## E-840 — Bind PPA preparation to amount-bounded ABAC (2026-08-23)

- Typed PPA consideration and NCI values are converted before policy; their
  gross absolute Decimal exposure is passed to server authorization before
  persistence, without counting allocation detail twice.
- Focused route/domain/dependency tests pass 16/16; universal route adoption
  and production IAM effectiveness remain unproven.

## E-839 — Bind deferred-tax preparation to amount-bounded ABAC (2026-08-23)

- Typed deferred-tax items are converted before policy; gross absolute
  fair-value Decimal exposure is passed to server authorization before
  persistence, without double-counting tax basis.
- Focused route/domain/dependency tests pass 15/15; universal route adoption
  and production IAM effectiveness remain unproven.

## E-838 — Bind intercompany preparation to amount-bounded ABAC (2026-08-23)

- Canonical intercompany lines are converted to typed Money, gross absolute
  Decimal exposure is computed, and server policy is re-evaluated before
  PostgreSQL proposal persistence.
- Focused route/domain/dependency tests pass 15/15; universal route adoption
  and production IAM effectiveness remain unproven.

## E-837 — Bind Finance Core entry creation to amount-bounded ABAC (2026-08-23)

- Both PostgreSQL Finance Core entry branches parse debit/credit values as
  exact non-negative decimals and pass gross debit into server policy before
  adapter access.
- Focused route/dependency tests pass 11 cases with one declared capability
  skip; Ruff and Mypy pass.
- Other financial routes and production IAM effectiveness remain unproven.
- Full regression completed with zero failures after updating the server
  identity contract assertion for the new amount field; PostgreSQL-dependent
  cases remain declared skips.

## E-836 — Bind impairment prepare to amount-bounded ABAC (2026-08-23)

- The server-only impairment prepare route converts canonical Money to the
  typed domain request, sums carrying amounts with Decimal arithmetic, and
  re-evaluates central policy with the exact amount before persistence.
- Focused route/policy/dependency tests pass 90/90; Ruff and Mypy pass.
- This is one high-risk route binding; universal route adoption and production
  IAM effectiveness remain unproven.

## E-835 — Fail closed on missing amount under bounded ABAC policy (2026-08-23)

- `CentralPolicyEngine` now denies `minimum_amount`/`maximum_amount` contexts
  without an exact finite `Decimal` amount using
  `amount_missing_for_bounded_policy`.
- Lower-only, upper-only, combined missing amounts, and existing exact amount
  boundaries pass the policy regression suite: 80/80.
- This closes a central omission gap while route/job/cache adoption and
  production IAM effectiveness remain unproven.
- Full regression after the slice completed with zero failures; Mypy covers 526
  source files and Ruff/diff-check pass.

## E-834 — Persist durable write-back recovery observations (2026-08-22)

- Added the immutable, digest-bound `WritebackRecoveryObservationRecord` and
  repository protocol with SQLite and PostgreSQL implementations.
- Added SQLite migration 43 and PostgreSQL Alembic revision 0090, including
  append-only triggers, intent/idempotency binding, scoped uniqueness, and
  PostgreSQL forced RLS.
- Recovery now persists the observation before accepted lifecycle mutation;
  the API exposes reviewer drill-down and idempotent replay.
- Focused tests pass 66/66; `mypy reconforge` passes across 526 files. The
  exact PostgreSQL 16.14/17.10 plus SQLite runtime matrix passed in 12.292s
  with shared records digest
  `768c363a6c196da78fe7c6ca40281f1d4ca051c194c8585f648b69c25574aa65`.
- Boundary: synthetic provider-neutral evidence on one Docker host; live
  provider semantics, accounting/settlement, cross-host HA/DR, and production
  assurance remain unproven.
- A post-commit rerun was attempted on 2026-08-23 but Docker Desktop's Linux
  engine was unavailable; the retained report is bound to commit
  `c88b8c03666e1f61ac34a58ebe7591e07b878561` and its exact source digests.

## E-833 — Classify provider status outcomes without lifecycle mutation (2026-08-22)

- Added the explicit recovery outcome taxonomy: `accepted`, `rejected`,
  `pending`, `not_found`, and `unknown`.
- Added `observe_recovery()`, a non-mutating boundary returning the original
  idempotency key, HTTP status, raw response-body SHA-256, provider reference
  and provider response digest when available, and a deterministic observation
  digest.
- `recover()` can advance the intent only for `accepted`; all other outcomes
  remain outside the lifecycle and require a later governed reconciliation.
  Legacy boolean-only provider responses remain digest-compatible.
- Focused connector transport/domain tests pass 55/55. Boundary: synthetic
  provider-neutral evidence only, not live status semantics or production.

## E-832 — Reject negative provider outcomes before acknowledgement (2026-08-22)

- Corrected a transport correctness gap: an explicit provider response with
  `accepted=false` can no longer become `ACKNOWLEDGED` through original
  dispatch or idempotency-status recovery.
- The shared parser now raises safe, non-sensitive errors before returning a
  lifecycle transition. The original intent remains `DISPATCHED` and the
  recovery path remains state-preserving; the existing compensation guard
  remains `COMPENSATION_REQUESTED` on a negative result.
- Positive responses, idempotency binding, migrations, APIs, and Community mode
  are unchanged. Focused connector transport/domain tests pass 46/46.
- Boundary: injected/synthetic provider responses only; no live provider,
  accounting posting, settlement, distributed delivery, or production claim.

## E-831 — PostgreSQL write-back recovery and compensation parity (2026-08-22)

- Added a closed, provider-neutral verifier for the append-only write-back
  lifecycle: `proposed`, `approved`, `dispatched`, `acknowledged`,
  `compensation_requested`, and `compensated`.
- A spawned process records synthetic provider acceptance and exits before
  acknowledgement persistence; recovery reuses the original idempotency key
  exactly once. A second crash window after synthetic compensation acceptance
  recovers through the distinct `<original-key>:compensation` key exactly once.
- SQLite and exact PostgreSQL 16.14/17.10 cells produce the same six-version
  canonical history SHA-256
  `d59b3648c99690c016c73a3ca9012ca6e7d806429dccc0cbd109081656c5db9d`.
  All 16 PostgreSQL checks per version, all 13 SQLite checks, role flags,
  tenant isolation, direct UPDATE/DELETE refusal, and cleanup pass.
- The retained report took 20.803 seconds and has digest
  `bdf1d82d0667f244160c43068cdab5c7516096d31fba17848e2ec1c33a3cdbb2`.
  Focused report and supply-policy tests pass 37/37.
- Boundary: synthetic provider acceptance markers only, one disposable node
  per version on one Docker Desktop host, no live provider/status API,
  accounting posting, settlement, cross-host quorum, automatic failover,
  production exactly-once, or production RPO/RTO claim.

## E-830 — Receiver replay across synchronous PostgreSQL failover (2026-08-22)

- Added a closed, additive failover verifier for the unchanged digest-only
  receiver contract. Each exact PostgreSQL 16.14 and 17.10 cell creates two
  volume-backed nodes, separate control/replication networks, physical
  streaming, and `synchronous_commit=remote_apply` under a non-privileged
  application role.
- The acknowledged request commits in a child process without delivering its
  response to the caller. Before failure, the read-only standby exposes exactly
  one receipt/effect. A second request begins after replication partition; the
  runner observes its backend waiting on `SyncRep` during COMMIT and terminates
  the client, retaining an uncertain—not failed or successful—outcome.
- The exact primary container is stopped, identity-checked, removed, and proved
  absent before standby promotion. The acknowledged request then replays with
  its exact response and no new effect. New mutations are controller-paused
  until the former primary volume is re-seeded and synchronous remote-apply is
  restored; only then does the uncertain identity apply once.
- Both nodes converge to two receipts/two effects and one canonical history.
  Restarting the promoted primary requires endpoint rediscovery on this Docker
  Desktop host; both identities replay afterward without count/history change.
- PostgreSQL 16.14, PostgreSQL 17.10, their rejoined standbys, both restarted
  primaries, and a same-input SQLite reference produce canonical SHA-256
  `5f5f48a2cf4071f93e064b127f2ecfa67fb5cbf29463a357aa93cfba52419f14`.
  Acknowledged-effect RPO is zero transactions inside this topology. Local
  fencing-to-exact-replay RTO is 6.168 seconds on 16.14 and 6.199 seconds on
  17.10, below the declared 60-second drill ceiling.
- The 64.067-second retained report digest is
  `5ae22491c01eb93daf38dd7fe6788c4daa7a0d648fb7dfa53ca7edf11d5e07d1`.
  Its closed schema fixes 23 true checks per cell, exact images, one failure
  domain, recovery semantics, source/policy digests, SQLite parity, and limits.
- Five development attempts exposed invalid timeout semantics, host-port
  readiness, a missing promoted-node replication alias, and dynamic endpoint
  reassignment. No failed attempt wrote a report. Every normal failure cleaned
  itself; the two operator-interrupted hangs were label-inspected and removed
  exactly before rerun. Progress checkpoints now make each topology transition
  visible without emitting secrets.
- Focused report and supply-chain-policy tests pass 37/37; Ruff, Mypy, Bandit,
  closed policy validation, JSON/YAML parsing, and whitespace gates pass. The
  first full regression correctly failed because E-830 named historical slice
  `E-228` as a standalone dependency even though it is recorded only inside
  the current P3-ENT-010 task. Removing that invalid dependency left the closed
  direct E-829 chain; the 15-test focused regression then passed. A fresh full
  run collected 3,085 tests: 2,970 passed, 115 declared capability skips and
  23 existing warnings in 531.47 seconds. Full-tree Ruff, Mypy across 525
  source files, Bandit, supply-chain policy, `uv lock --check`, the isolated
  Python 3.12 locked audit, package build/membership, JSON/YAML parsing, and
  whitespace gates pass. The sdist has 1,768 entries and contains all five
  E-830 evidence assets; the runtime-only wheel remains at 625 entries and has
  no new runtime payload.
- Ambient `python -m pip_audit` remains a failing host observation because its
  installed `pip 26.1.2` is affected by `PYSEC-2026-3721` (fixed in 26.2). The
  project-controlled Python 3.12.13 locked audit reports zero findings and zero
  exceptions across the 128-package policy graph.
- Gitleaks 8.30.1 scans the 663-commit / 25.28 MB complete history and a clean
  27.71 MB archive of the implementation commit with no findings. The exact
  temporary archive and directory were previewed with `git clean -nd`, removed
  with explicit targets, and verified absent. The final amended commit is
  rescanned before handoff.
- Boundary: two nodes still share one Docker Desktop host and one real failure
  domain. Fencing, promotion, endpoint discovery, and rejoin are manual runner
  controls. No quorum/witness, automatic failover, cross-host/zone/region loss,
  production key custody, live provider, posting, settlement, hosted execution,
  production RPO/RTO, publication, or exactly-once claim follows.

## E-829 — PostgreSQL receiver idempotency parity (2026-08-22)

- Added an optional `PostgresWritebackReceiverStore` without changing the
  E-828 request/response contract. psycopg is loaded only when a PostgreSQL
  operation is requested; importing Community/local connector surfaces remains
  network-free and does not require a database connection.
- A transaction-scoped advisory lock over the canonical receiver/key digest
  serializes contenders. The immutable receipt and synthetic effect commit in
  one transaction under the same composite identity. Bounded connection and
  statement timeouts, parameterized data values, digest checks, foreign keys,
  and UPDATE/DELETE refusal triggers fail closed.
- The retained matrix ran on exact digest-pinned PostgreSQL 16.14 and 17.10
  images. Each cell produced one sequential apply/replay, refused retargeting,
  converged eight spawned processes to one apply/seven replays, replayed after
  child exit following commit, and retained three receipts for three effects.
- Each cell used a role with superuser/create-database/create-role/replication/
  BYPASSRLS all false, refused direct receipt/effect mutation and malformed
  digest input, listed a native custom dump, restored into an independent
  database, preserved canonical history, and created no effect on restored
  replay. Exact disposable-container cleanup passed.
- PostgreSQL 16.14, PostgreSQL 17.10, and SQLite all produced canonical history
  SHA-256 `1c42c656b8e09897710e05411c78a91c709c15b70309d2e68f1e4417f1ac32f8`.
  The 14.142-second matrix report digest is
  `3e53b99e9d33598d5f010d2b0ad405cbc167936840976564221f8b27bb4d33b1`
  on Docker Engine 29.7.2 and Python 3.14.6.
- The report is closed by Draft 2020-12 schema, canonical digest, exact runtime
  image identities, source and supply-chain-policy digests, and negative
  mutations. CI is defined to run and retain it before the broader live server
  boundaries; no hosted run is claimed because D-485 prevents publication.
- The final local regression collected 3,075 tests: 2,960 passed, 115 declared
  capability skips, and 23 existing warnings in 716.62 seconds. Full-tree Ruff,
  Mypy across 525 source files, Bandit, supply-chain policy, `uv lock --check`,
  isolated Python 3.12 locked audit, JSON/YAML parsing, package build/membership,
  and whitespace gates pass. The sdist has 1,763 entries and the wheel 625;
  both contain their intended E-829 assets.
- Ambient `python -m pip_audit` remains a failing host observation because its
  installed `pip 26.1.2` is affected by `PYSEC-2026-3721`; the project-controlled
  Python 3.12.13 locked audit reports zero findings and zero exceptions.
- Gitleaks 8.30.1 scans the 662-commit / 25.18 MB complete history and a clean
  27.62 MB archive of the implementation commit with no findings. The exact
  temporary archive/directory were removed after the scan.
- Boundary: this is two sequential single-node PostgreSQL versions on one
  Docker Desktop host with synthetic digest-only effects. It does not prove a
  live vendor, cross-host consensus or database failover, settlement finality,
  accounting posting, HA/DR, production exactly-once effects, or publication.

## E-828 — Bounded receiver-side write-back idempotency (2026-08-22)

- Added a frozen, closed, digest-only receiver request and a SQLite reference
  store. `(receiver_id, idempotency_key)` is the effect identity; operation and
  payload digest are immutable bindings. Receipt and synthetic effect commit in
  one `BEGIN IMMEDIATE` transaction, and database triggers refuse direct update
  or deletion. No payload bytes or credentials are persisted.
- A retained runner proves sequential apply/replay, same-key payload-conflict
  refusal, one apply plus seven exact replays from eight spawned processes, and
  replay after a child exits immediately after commit but before returning its
  response. Three receipts equal three effects; canonical history SHA-256 is
  `1c42c656b8e09897710e05411c78a91c709c15b70309d2e68f1e4417f1ac32f8`.
- An independent SQLite backup restores all three receipts/effects, retains the
  exact canonical history digest, and replays the crash identity without a new
  effect. All eleven closed checks and temporary-directory cleanup pass. The
  2.473-second refreshed report digest is
  `cfe14335be6d04387d9f2c1be2909a1d843ebefe744e421f288cf096479274fb`
  on Python 3.14.6 / SQLite 3.50.4 using `spawn`.
- The first drill invocation exposed SQLite handles left open by context-manager
  transaction exit on Windows; it failed during cleanup and produced no report.
  Explicit connection/queue closure fixed the lifecycle, the exact failed-run
  temp directory was removed, and the successful retained run cleaned itself.
- Focused receiver/report/network/SDK/package tests pass, including a generated
  property for canonical digest stability and payload separation. The closed
  schema rejects false checks, cardinality drift, and undeclared evidence; CI is
  defined to run and preserve the report before broader server-boundary tests.
- The post-slice regression collected 3,058 tests: 2,943 passed and 115 were
  declared capability skips, with 23 existing warnings in 396.97 seconds.
  Ruff, Mypy across 524 source files, Bandit, the closed supply-chain policy,
  lock validation, isolated Python 3.12 dependency audit, build, package-content
  verification, JSON/YAML parsing, and whitespace checks pass. The 1,756-entry
  sdist and 624-entry wheel both contain the intended receiver assets.
- Ambient `python -m pip_audit` remains a failing host observation because
  installed `pip 26.1.2` is reported under `PYSEC-2026-3721`; the isolated
  Python 3.12.13 locked audit reports zero findings and no active exceptions.
- Gitleaks direct scans found the receiver assets clean after one synthetic
  idempotency-key literal was rewritten from fixed parts; no suppression or
  allowlist was added, and the final package artifacts were rebuilt.
- Boundary: this is same-host SQLite coordination with synthetic digest-only
  effects. It does not prove a live vendor, actual ERP/bank semantics,
  cross-host consensus, database failover, accounting posting, settlement
  finality, production exactly-once effects, hosted execution, or publication.

## E-827 — PostgreSQL write-back migration version matrix (2026-08-22)

- Refactored E-826 into one strict reusable observation function without
  changing its CLI, default PostgreSQL 17.10 image, report schema, or product
  behavior. Invalid image references, expected versions, and container prefixes
  fail before Docker I/O.
- The same observation path ran sequentially against the exact CI PostgreSQL
  16.14 digest and the existing PostgreSQL 17.10 digest. Each cell upgraded to
  0088, captured/listed a native pre-drift dump, created proposal drift, proved
  0089 refusal without revision/history/trigger mutation, restored independently,
  upgraded to 0089, rejected drift through the enhanced INSERT guard, and
  verified exact container cleanup.
- Both cells produced canonical valid-history SHA-256
  `ec931f9cf25e1b9f8c1b39cc83e6c38e2bc3384b669516505a46d4aaabb30886`
  and invalid-history SHA-256
  `7384d0a6b70c466e099461bb28b24a979f90cd0c78ea8ae97e5cdf1d77e950a4`.
  The 24.178-second retained matrix report digest is
  `6c9e41dd55ef0ff9292a52aacd15030766660db85c5ddda78391aeeb4ecb73f3`.
- The closed supply-chain policy now explicitly owns the PostgreSQL 16 CI
  digest as well as the PostgreSQL 17 drill digest. The CI server-boundaries job
  runs and uploads the matrix before the broader live suite; this is a checked
  workflow definition, not a hosted-run claim under D-485.
- The post-slice regression collected 3,042 tests: 2,927 passed and 115 were
  declared capability skips, with 23 existing warnings in 410.54 seconds.
  Ruff, Mypy across 523 source files, Bandit, the closed supply-chain policy,
  lock validation, isolated Python 3.12 dependency audit, build, package-content
  verification, JSON/YAML parsing, and whitespace checks pass. The 1,749-entry
  sdist contains both runners, both reports, the matrix schema, ADR, and tests;
  the 623-entry wheel contains Alembic 0089.
- Ambient `python -m pip_audit` remains a failing host-environment observation:
  host-installed `pip 26.1.2` is reported under `PYSEC-2026-3721`. The isolated
  locked audit uses Python 3.12.13 and reports zero findings; the ambient failure
  is not relabeled as a passing product gate.
- Gitleaks 8.30.1 direct scans of both migration runners and the changed policy
  found zero leaks. Its first post-implementation history scan covered 660
  commits / 25.03 MB with zero leaks; a clean `git archive` extraction scanned
  27.47 MB with zero leaks, and its exact temporary path was removed afterward.
- Boundary: one Docker Desktop Linux/AMD64 engine, two sequential single-node
  versions, synthetic records and credentials. No live provider, posting,
  rolling upgrade, replication, cross-host HA/DR, production recovery, push,
  PR, tag, release, or deployment occurred.

## E-826 — PostgreSQL write-back identity migration refusal and restore (2026-08-22)

- Added a reproducible Docker runner pinned to PostgreSQL 17.10 by image digest.
  It creates two isolated databases and uses container-native `pg_dump` and
  `pg_restore`; credentials and business records are generated synthetic data.
- At source revision 0088, the runner captured a valid proposed/approved
  history and native pre-drift backup, then inserted a payload-digest-drifted
  dispatched version permitted by the legacy UPDATE/DELETE-only trigger.
- Upgrade to 0089 raised the expected audit refusal. The Alembic revision
  remained 0088, the three-version history retained SHA-256
  `7384d0a6b70c466e099461bb28b24a979f90cd0c78ea8ae97e5cdf1d77e950a4`,
  and the trigger definition remained unchanged.
- The pre-drift dump SHA-256 is
  `157792de539a8b9fe06eb4530aa6096797c54d43fa7af4b1b0f06996d2ecffaf`.
  It restored into an independent database with the expected two-version
  history digest, upgraded to 0089, preserved that history, and rejected a
  drifted direct INSERT through the enhanced trigger.
- The closed retained report passes its Draft 2020-12 schema and canonical
  report-digest and source-binding tests. Cleanup of the exact temporary
  container is part of the report contract and passed. Three earlier development
  invocations failed safely on missing synthetic `created_at`, tenant, and
  migration-path fixtures; all cleaned their containers and none was treated as
  evidence.
- The post-slice full regression collects 3,032 tests: 2,917 pass and 115 are
  declared capability skips, with 23 existing warnings. The focused E-825/E-826
  boundary passes 88 tests with four declared live-service skips; the combined
  report/policy/parity contract passes 44/44. Ruff, Mypy across 523 source files,
  Bandit, closed supply-chain policy, lock check, isolated Python 3.12 locked
  dependency audit, build, package-content verification, JSON/YAML parsing, and
  whitespace checks pass.
- Ambient `python -m pip_audit` is not a passing product gate on this host: it
  correctly reports host-installed `pip 26.1.2` / `PYSEC-2026-3721`. The unified
  isolated audit resolves the locked project environment with fixed pip and
  reports zero findings. The ambient failure remains disclosed.
- Gitleaks 8.30.1 initially flagged the literal synthetic idempotency fixture as
  a generic API key. The fixture was rewritten without suppression or allowlist,
  the live report was regenerated and source-rebound, and the amended 659-commit
  history plus a clean 27.43 MB `git archive` scan report zero leaks.
- This is one Docker Desktop host, one PostgreSQL version, synthetic data, and
  single-node restore evidence. No live provider, accounting posting, cross-host
  HA/DR, production recovery, push, PR, tag, release, or deployment occurred.

## E-825 — Immutable write-back proposal identity (2026-08-22)

- Reproduced an internal-boundary defect where an allowed status transition
  could change the connector, operation, payload digest, idempotency key,
  requester, request time, or captured feature decision. Append-only rows did
  not by themselves prove that approval referred to the original mutation.
- Added a deterministic proposal digest and one shared transition validator.
  SQLite and PostgreSQL repositories now reject proposal drift before INSERT;
  full version digests still change as approval, acknowledgement, and
  compensation evidence is added.
- SQLite migration 42 and PostgreSQL Alembic 0089 audit existing history and
  install direct-INSERT guards for JSON/column identity, proposed first state,
  exact predecessor presence, immutable proposal fields, and allowed status
  adjacency. PostgreSQL continues to reject UPDATE and DELETE.
- SQLite uses a connection-local temporary audit table; a regression proves a
  same-named main-database table and its contents are not removed or changed.
- The authenticated connector API now returns the stable `proposal_digest` as
  an additive evidence field. Valid callers and historical migration behavior
  remain compatible; drifted history is deliberately refused for investigation.
- A digest-pinned PostgreSQL 17.10 Alpine container exercised both write-back
  histories through the enhanced trigger under a `NOBYPASSRLS` non-superuser
  role. A separate isolated database completed head upgrade, two deep
  downgrades, and three returns to current head 0089 before cleanup.
- The full local regression collects 3,027 tests and passes all executable
  tests: 2,912 passed and 115 declared capability skips. Ruff, Mypy across 523
  source files, Bandit, the closed supply-chain policy, lock check, sdist/wheel
  build, YAML contracts, and whitespace checks pass. No live provider call,
  posting, push, PR, tag, release, or deployment occurred; D-485 remains active.

## E-824 — Governed fixed VEX and retained OpenSSL block (2026-08-22)

- Independently traced the three Python CPE matches to the signed CPython
  3.11.16 source tag. CVE-2026-3644 and CVE-2026-4224 are named in the
  official 3.11.16 security record; the CVE-2026-7210 3.11 backport and
  bundled Expat 2.8.3 precede the tag. A hash-bound OpenVEX 0.2 document now
  records only these exact `fixed` decisions.
- The closed gate validates the VEX document, 30-day review ceiling, exact
  image product PURLs, Grype ignored-match rules, and per-finding evidence.
  Fixed matches remain visible in the five-High total and are never conflated
  with exceptions. Critical suppression, unreviewed status, stale review,
  product drift, or an unapplied decision fails closed.
- Supported official Alpine candidates remain on OpenSSL 3.5.7. The current
  3.11 and 3.12 bases retain five High matches before fixed disposition; 3.13
  remains outside the declared matrix and still has both OpenSSL matches. A
  Debian 3.11 slim candidate was rejected after its untrimmed base reported
  ten Critical and 38 High matches under the same scanner database.
- OpenSSL's upstream record places 3.5.7 in the affected range and repairs it
  in 3.5.8. Alpine 3.23/3.24 currently offer only 3.5.7-r0. No reachability
  VEX, severity override, or exception was self-approved. The exact image is
  still **blocked** by CVE-2026-14456 on libcrypto3 and libssl3.
- The container-gate file passes 16 executable tests with one declared Windows
  symlink capability skip. The combined E-824 policy/gate selector passes 43
  tests plus that skip on isolated Python 3.11 and 3.12 environments. The full
  local suite collects 3,009 tests and passes 2,894 with 115 declared capability
  skips; Ruff, mypy across 525 files, Bandit, policy/lock validation, JSON/YAML
  parsing, package build, and deterministic evidence regeneration all pass.
- Boundary: E-824 has made all safe current progress but remains externally
  blocked on an upstream-fixed supported base or independent security approval.
  D-485 still forbids push, PR, tag, release, or deployment.

## E-823 — Fail-closed exact-image container security gate (2026-08-22)

- Added a closed supply-chain policy for Syft 1.51.0 and Grype 0.117.0,
  checksum/commit/platform identity, Syft native schema/configuration, Grype
  database schema and 120-hour age ceiling, exact image configuration/manifest
  binding, suppressed-match refusal, Critical/High/Unknown handling, and 90%
  package-license inventory coverage. Critical findings cannot be excepted;
  High findings require an exact active container exception.
- The release workflow now builds and scans without registry credentials,
  enforces the gate before GHCR login, preserves blocked evidence, pushes only
  after a pass, and verifies the registry manifest bytes/configuration against
  the scanned subject. The security workflow repeats this on weekly/manual
  runs while remaining skipped on ordinary push and pull-request events.
- The exact local Alpine 3.24.1 image records 68 packages, 64 with usable
  license metadata (94.11%), and Grype database v6.1.9. It is correctly
  **blocked** by five unexcepted High findings: CVE-2026-14456 on libcrypto3
  and libssl3, plus CVE-2026-3644, CVE-2026-4224, and CVE-2026-7210 on Python
  3.11.16. No VEX or exception was inferred.
- Disposable PostgreSQL 17.10 Alpine and Python 3.14.1 slim drill runtimes now
  execute by reviewed digest while retaining their historical tag labels in
  existing report schemas.
- The 66-test focused release/supply-chain/drill selector and 14 execution
  contract tests pass. The full local suite collects 3,002 tests and every
  executable test passes; Ruff, mypy across 523 source files, Bandit, closed
  policy validation, locked audit in local isolated mode, package build, and
  whitespace checks pass.
- Boundary: this is local scanner evidence and a hosted workflow definition.
  The gate intentionally prevents release; no hosted run, legal license
  assessment, reachability decision, independent advisory validation, registry
  publication, or production-readiness assurance exists. E-824 is the next P0
  remediation task and D-485 remains active.

## E-822 — Bounded non-root container runtime (2026-08-22)

- Replaced the single-stage root image with two stages pinned to the same
  reviewed Python digest. The runtime carries the locked non-editable virtual
  environment and declared assets, omits uv/build manifests/source, and runs as
  `10001:10001` with `/app/output` as its sole image-owned writable location.
- Added a closed deny-by-default `.dockerignore` contract. The measured build
  context fell from 53.82 MB to 216.25 KB on the final tree; migration
  to the current official Python 3.11 Alpine digest plus removal of global
  build packages and runtime documentation reduced image size from 149,556,826
  to 58,773,988 bytes.
- A clean Docker Desktop run passed Doctor, sample validation, control-pack
  validation, and the complete demo with networking disabled, a read-only root,
  and bounded `/tmp`/`/app/output` tmpfs mounts. The demo gate found and fixed a
  relative-vs-absolute client-pack publication identity defect; focused
  publication/recovery/supply-chain tests pass.
- Docker Scout 1.24.0 rejected the intermediate Debian runtime with two
  Critical and eight High findings, then passed the final Alpine runtime after
  indexing 82 packages with zero findings at all severities.
- The full local suite collected 2,985 tests and completed with every executed
  test passing; Ruff, mypy, Bandit, lock/policy validation, package build, and
  whitespace checks pass.
- Boundary: one local Windows/Docker Desktop Linux-engine profile only. No
  hosted rerun, OCI reproducibility, future CVE/license completeness, signature,
  provenance, independent hardening, HA/DR, or production-readiness claim is
  made. D-485 remains active.

## E-821 — Non-destructive developer environment recovery (2026-08-22)

- Added a cross-platform developer environment manager with machine-readable
  `doctor` and explicit `bootstrap` operations. It binds exact uv, supported
  Python, current lock, all extras, non-editable installation, and product
  Doctor without using a shell or trusting the ambient environment.
- The local Doctor identified the existing Linux-origin `.venv` on Windows as
  `DEVENV-ENV-FOREIGN` and left it byte-for-byte in place. Bootstrap created the
  ignored `.venv-windows` with locked Python 3.12; subsequent Doctor returned
  `DEVENV-READY`, a repeated bootstrap succeeded, and that interpreter carried
  the full 2,981-test collection to 100% with every executed test passing.
- Boundary: local Windows developer bootstrap only. This does not establish a
  clean-host, hosted, macOS/Linux, private-index, proxy, or air-gap install, and
  does not change any application runtime or financial behavior. D-485 remains
  active.

## E-820 — Locked Python advisory remediation and audit-path convergence (2026-08-22)

- The universal lock now resolves `pip 26.2`, the first fixed release for
  `PYSEC-2026-3721` available inside the existing 2026-08-02 upload cutoff.
- One cross-platform runner now enforces exact uv identity, supported Python,
  policy/lock validation, an all-extras hash export, locked pip-audit execution,
  and report/exit-code enforcement. Local execution uses a temporary isolated
  environment and cache; CI/release use their already-synchronized lock.
- Focused runner/policy tests and real isolated Python 3.11/3.12 audits pass
  with 128 packages, zero active exceptions, and zero known findings. The full
  locked Python 3.12 regression reached 100% after collecting 2,972 tests; all
  executed tests passed and unavailable live-service capabilities remained
  explicit skips. Supported-version package build, CLI doctor/validation,
  static/security gates, 75 web unit tests, web build, npm audit, and 16 browser
  E2E tests also pass. E-820 is complete locally.
- Boundary: no application runtime, financial logic, schema, or persisted data
  changed. Hosted Python 3.11/3.12 reruns, provenance, malware/reachability
  analysis, independent assurance, and publication remain outside this local
  result. D-485 remains active.

## E-819 — Bounded server-boundary CI lifetime (2026-08-20)

- The hosted `server-boundaries` job now has a 30-minute job-level timeout.
  The live matrix historically completes below 20 minutes; the bound prevents
  a hung PostgreSQL/pytest process from consuming a runner indefinitely while
  retaining headroom for the declared test set.
- This is CI containment, not a claim that a cancelled run passed. The
  replacement run must complete all live tests and cleanup steps successfully.

## E-818 — Fail-closed deployment evidence gates (2026-08-20)

- Deployment profiles now require explicit runtime facts for backup/restore,
  rollback, and retention/privacy evidence in every edition, in addition to
  the existing storage, identity, queue, object-store, network, key, and
  failure-domain checks.
- The profile digest includes these requirements, and incomplete facts produce
  deterministic findings. Focused deployment tests, Ruff, mypy, and diff
  checks pass.
- Boundary: this enforces evidence prerequisites; it does not manufacture or
  verify a backup, restore, rollback, retention, or privacy drill. E-1006 and
  E-1007 remain open until those runtime artifacts exist.

## E-817 — Canonical identity enforcement for high-risk policy decisions (2026-08-20)

- Central SoD comparisons now canonicalize actor, object type, object ID, and
  action values with trim + casefold before evaluating conflicts. Ownership
  checks use the same canonical actor identity and cover certification in
  addition to approval/review.
- Hypothesis properties prove that casing and surrounding whitespace cannot
  bypass self-approval or a prior-prepare/review SoD conflict. Focused policy
  tests, Ruff, and mypy pass.
- Boundary: this closes a policy-evaluation normalization gap only. It does
  not claim universal route coverage, external IdP interoperability, or
  production authorization assurance; E-1005 remains in progress.

## E-816 — Deterministic connector manifest portfolio identity (2026-08-20)

- Added `build_manifest_portfolio_report` to the connector conformance layer.
  It validates the shared read-only/sandbox/threat/egress contract, canonicalizes
  manifest ordering, records each manifest SHA-256, and emits one portfolio
  digest suitable for drift detection and release evidence.
- The reference portfolio report is permutation-invariant and changes when a
  manifest version changes. Connector SDK/package/write-back focused tests,
  Ruff, and mypy pass.
- This closes no live provider or accounting write-back claim; network
  interoperability, customer secrets, signed package distribution, and
  production deployment remain explicitly outside this local manifest gate.

## E-815 — Live PostgreSQL close, metrics, migration, and strategy-registry gate (2026-08-20)

- A disposable PostgreSQL 16.14 service was upgraded with the complete Alembic
  chain through `0088_pg_currency_snapshot` using a separate migration owner.
- The live consolidation-close selector passed with a non-owner application
  role, covering tenant isolation, replayed run identity, certification SoD,
  immutable journal/effect rows, reversal, period lock/reopen, and linked
  impairment/deferred-tax/PPA/ownership/intercompany evidence.
- The live PostgreSQL metrics selector passed with SQLite parity, and the
  Alembic upgrade/downgrade selector passed. The encrypted native-backup
  selector remained an explicit skip because this local service does not expose
  the required disposable maintenance service and native-tool service profile.
- Added a single infrastructure factory for all five reviewed matching
  strategy adapters and routed Reconciliation-as-Code simulation through its
  immutable registry. Focused strategy, RAC, Ruff, mypy, and diff checks pass.
- Hosted PR #83 for commit `de9e347f` completed its required CI/security matrix:
  Python 3.11/3.12, server boundaries, PostgreSQL HA/DR, Docker parity,
  engine parity, object storage, CodeQL, dependency/security policy gates all
  passed. The PR remains open and merge-blocked by repository policy/branch
  freshness; no automatic merge was performed.
- Local runtime evidence and hosted CI now both exist for this slice; independent
  multi-site HA/DR, external provider interoperability, release
  provenance/signatures, and production capacity remain open.

## E-813 — Clean full local regression after drift repairs (2026-08-17)

- `python -m pytest -q --tb=no -ra` exits 0 after reaching 100%; 2,960 tests
  were collected, with no failures. Capability-gated live PostgreSQL/Redis/S3,
  public-network, object-lock, and Windows-privilege tests remain explicit
  skips, and warnings remain visible.
- This is local evidence only. Hosted CI, native PostgreSQL tools, live
  providers/write-back, independent HA/DR, release provenance/signatures, and
  owner-controlled publication approval remain open. D-485 is still active.

## E-812 — Regression drift repairs and locale verification (2026-08-17)

- Repaired five local contract drifts found by the full regression: benchmark
  canonical hashing, missing dependency records, additive close-schema guard,
  Windows native-tool path casing, and optional locale compatibility in Studio
  consumers.
- Focused Python repair tests pass 8/8; web typecheck passes; locale parity and
  formatter tests pass 5/5. E-813 records the subsequent clean full rerun.
- E-16931 is now completed with focused evidence; E-1007 remains in progress
  behind E-1006. No GitHub publication was performed.

## E-811 — Package build and membership gate (2026-08-17)

- Rebuilt both wheel and source distribution successfully after the deployment
  profile slice; both artifacts contain the new `reconforge.deployment`
  package.
- E-1007 is intentionally `in_progress`: its local implementation is present,
  but closure depends on the still-planned E-1006 deployment-readiness evidence.
- Publication freeze D-485 remains active; hosted CI, provenance/signatures,
  external providers, and independent deployment evidence remain open.

## E-810 — Fail-closed deployment edition profile contract (2026-08-17)

- Completed a local slice with immutable, digest-bound Community, Team,
  Enterprise, and Regulated profiles plus the read-only
  `reconforge deployment profiles` command. Focused tests and static checks
  pass; this does not establish external deployment readiness.
- Publication freeze D-485 remains active. No GitHub push, tag, merge, or
  release was performed.
- External gates remain open for hosted CI, native PostgreSQL backup/restore
  and metrics/migration evidence, live provider/write-back interoperability,
  independent HA/DR and RPO/RTO, hosted provenance/signatures, and owner
  closure of D-485.
## E-808 — Current Gitleaks history/tree scan (2026-08-17)

- Re-ran the exact configured Gitleaks 8.30.1 history and checked-out-tree
  commands inside the pinned `zricethezav/gitleaks:v8.30.1` container.
- Both scans passed with no findings across 733 commits and the current tree.
- This closes no hosted security or publication gate; D-485 remains the owner
  publication freeze and hosted repository-security evidence remains required.

## E-809 — Phase-4 YAML execution contract repair (2026-08-17)

- Fixed the malformed folded description for the E-806 benchmark entry in
  `docs/execution/BACKLOG.yaml`.
- The Phase-4 execution-contract and supply-chain policy selector now pass
  24/24 tests; lock, policy validation, and diff-check remain green.
- No task status, dependency, runtime, API, migration, or publication boundary
  was changed.

## E-16933 — Locale-aware Studio number rendering (2026-08-16)

- Routed preferences.locale into major read-only Studio modules via App.tsx
  for bank statement, retail settlement, manufacturing cost, professional invoice-
  payment, individual cashflow, mapping, rule, and admin-audit views.
- Added locale-aware count rendering in those module summaries (including filtered
  result counts, including the `LiveStudio` value and computed-at timestamp rendering,
  via existing shared locale format helpers.
- This update is presentation and accessibility hardening only; no API, policy,
  migration, financial-calculation, connector, or provider behaviors changed.

## E-16932 — Locale-aware dashboard formatting (2026-08-16)

- Added `apps/web/src/locale-format.ts` with deterministic locale profiles and
  format helpers for counts, percentages, days, and UTC dates.
- Updated `Dashboard` to receive and render locale-aware numeric strings from
  `preferences.locale`; `App` now passes the active locale into the dashboard.
- Added `apps/web/src/locale-format.test.ts` covering locale-specific numeric
  formatting behavior and date formatting determinism.
- Extended `App.test.tsx` locale-switch coverage with explicit document `lang`
  assertion (in addition to existing RTL coverage) so global accessibility and
  locale metadata are both verified in UI tests.
- This is a localization/UX hardening slice only; it does not alter financial
  calculation semantics, policies, migrations, APIs, or provider boundaries.

## E-1000 — Global Expansion Execution Track (2026-08-16)

- Opened a formal global-expansion execution track to tie together localization,
  evidence boundaries, and global-operability slices across identity, localization,
  deployment modes, and market-ready packaging.
- Added `docs/adr/0531-global-expansion-program-framework.md` with explicit
  non-claiming completion criteria and rollback-safe gates.
- Tracked this track in `docs/execution/BACKLOG.yaml` as `E-1000` (in_progress)
  with dependencies already open from locale and scale governance evidence.
- This track is currently coordination-and-planning-first: no runtime behavior
  change beyond the already shipped locale-aware UI slice (`E-16932`) and no new
  deployment or data-policy claim beyond documented execution boundaries.

## E-1001 — Expanded Global Expansion Slice Plan (2026-08-16)

- Added `E-1001` under `E-1000` to decompose the global objective into five
  execution slices: close/consolidation, advanced matching, governed connectors
  with write-back boundaries, enterprise identity/policy, and operational mode
  + localization coverage.
- `BACKLOG.yaml` now requires closure evidence for deterministic close lifecycle
  and SoD, strategy/version/digest-reproducible matching behavior, append-only
  approval/dispatched/acknowledged write-back checkpoints, RBAC+ABAC with
  deny-by-default financial control policy, and Community/Team/Enterprise/
  Regulated default-safe mode boundaries.
- This is an execution-planning extension and evidence contract only. No APIs,
  migrations, schema, or provider runtime semantics are changed in this slice.

## E-1002 to E-1006 — Global Expansion execution slice decomposition (2026-08-16)

- Added five concrete slices under `E-1000`/`E-1001`:
  - `E-1002` close/consolidation global closure evidence,
  - `E-1003` advanced matching determinism evidence,
  - `E-1004` governed connectors/write-back lifecycle evidence,
  - `E-1005` enterprise governance stack (RBAC+ABAC+SoD),
  - `E-1006` mode-specific deployment-readiness evidence (Community/Team/Enterprise/Regulated).
- Current status: `E-1001` and `E-1005` are in progress, while other slices are
  planned; this keeps objective movement explicit without promoting unearned global
  readiness claims.
- No runtime or migration behavior changed in this decomposition step; each slice
  now awaits bounded evidence closure in the same track.

## E-783 — WSL-native PostgreSQL native-backup proof (2026-08-15)

- In WSL2 Ubuntu, a disposable PostgreSQL 16 service was used to run the hosted
  native-backup restoration test with a temporary local `pg_wrapper` shim path.
  This proved `pg_config`, `pg_dump`, `pg_restore`, `createdb`, `dropdb`, and
  `psql` were discoverable by the native-tool adapter and that the
  encrypted backup-restore command path can complete.
- Command context:
  - Prepared a dedicated wrapper directory from `/usr/share/postgresql-common/pg_wrapper`
    as local `pg_config`, `pg_dump`, `pg_restore`, `createdb`, `dropdb`, `psql`
    tool names.
  - Ran `uv run --no-sync pytest tests/test_postgres_backup.py::test_live_postgres_native_adapter_encrypted_backup_isolated_restore_and_cleanup`.
- Result: PASS for the isolated encrypted backup, restore, and cleanup workflow under
  WSL with a fresh local PostgreSQL 16 service.
- Boundary: this is Linux/WSL runtime evidence only. The hosted Linux CI
  `E-461` native-tool gate for publication/closure is still open until executed
  in the declared hosted environment.

## E-16931 — Web UI locale parity guard (2026-08-16)

- Added `apps/web/src/i18n.test.ts` to enforce that every locale dictionary shares the
  exact `MessageKey` coverage and that each locale value is a non-empty string.
- `apps/web/src/i18n.ts` now exports the locale map so test-time coverage checks
  can validate parity explicitly.
- This is a global-interface hardening slice aligned with objective wording around
  localization and global accessibility. No production behavior or runtime service
  changed, and execution verification is intentionally pending a test run in the next
  validation step.

## E-806 — PostgreSQL durable-job 1M local scale gate

- Added the published `postgres-durable-job-load/1m-effects-v1` benchmark declaration
  and evidence entry to the existing durable-job scale family.
- A local PostgreSQL 16 synthetic run completed `1,000,000` declared partition effects
  across `2,500` jobs and four tenant lanes with `16` independent worker
  connections.
- The profile completed with `0` duplicate partition effects, drained queue/running
  depths to zero, exact per-lane completion counts (`625` each), and immutable
  effect/manifest digests:
  `95ba466b31a08f5b3a4506d0b8fc5b44742f01627c79aea772e46d7bd073ee5c` and
  `252eb01a1b679deb977141d9e1d931e89469d161877e8fdd1a4e88c6ae642103`.
- Observed local runtime was `1932.3678` seconds on Windows-11/Python 3.12.13 with
  `16` CPUs and `1.2937` jobs/s, retained only as an observation for this hardware.
- Boundary: bounded synthetic single-host evidence only. This does not prove
  queue HA/failover/host-loss/cross-host fairness, backpressure coupling,
  RPO/RTO, soak, throughput production claims, or deployment sizing.

## E-807 — Benchmark index coverage closure for durable-job tiers

- Added missing durable-job profile metadata entries to
  `docs/execution/benchmarks/INDEX.v1.json` so `10k-effects-v1`,
  `backpressure-tier-v1`, and `repeated-small-tier-v1` are now all indexed with
  explicit boundary language and digest fields.
- `postgres-durable-job-load/10k-effects-v1` and
  `postgres-durable-job-load/backpressure-tier-v1` remain local/synthetic
  one-host observations; `postgres-durable-job-soak/repeated-small-tier-v1`
  remains the existing bounded repeated-soak evidence.
- This keeps the index evidence map aligned with the closed P4-SCL-001
  profile artifacts and the local profile boundaries.

## E-719 — policy-bearing artifact constructors fail closed (2026-08-12)

- `VarianceThresholdPolicy`, `ClientPackOptions`, and `RulePackExecution` now
  validate and normalize `financial_input_policy` in `__post_init__`, so unsupported
  values fail closed before policy consumers, artifact generators, or rule outputs can
  observe them. Strict-v2 remains the default and explicit legacy-v1 remains named
  compatibility.
- The focused variance/client-pack/rule policy constructor tests pass, and Ruff
  and Mypy pass. This guard does not alter schema, migration, provider,
  posting, write-back, or publication behavior. The broader objective remains
  separate under D-485.

## E-718 — core result policy metadata fails closed (2026-08-11)

- `StockGLReconciliationResult`, `MatchRunResult`, and
  `DeterministicMatchOutput` now validate and normalize their frozen
  `financial_input_policy` in `__post_init__`. Unsupported runtime metadata is
  rejected before downstream report or persistence consumers can observe it;
  explicit legacy-v1 remains available for named compatibility and strict-v2
  remains the default.
- The focused Stock/GL, application-matching, reconciliation-policy, and report
  suite passes 33 tests; the current full local regression collects 2,935 tests
  and passes 100% with only declared capability skips and existing warnings.
  Ruff and Mypy pass. This additive guard changes no schema, migration,
  provider, posting, write-back, or publication behavior. Hosted execution and
  the broader release objective remain separate under D-485.

## E-717 — Work-order result policy construction fails closed (2026-08-11)

- `WorkorderReconciliationResult` now validates and normalizes its frozen
  `financial_input_policy` in `__post_init__`, so unsupported runtime metadata
  cannot escape from manual construction. Explicit legacy-v1 remains available
  only when a named compatibility caller selects it; the default remains
  strict-v2.
- The focused Work-order/report/CLI/reconciliation-policy suite passes 47
  tests; Ruff and Mypy pass. This additive guard changes no schema, migration,
  provider, posting, write-back, or publication behavior. The full local
  regression baseline remains the E-715 run, and hosted execution remains
  separate under D-485.

## E-716 — local PostgreSQL industry/API runtime gate (2026-08-11)

- A disposable PostgreSQL 16 runtime reached Alembic head
  `0088_pg_currency_snapshot` with a non-superuser application role. The
  manufacturing, retail, professional invoice-payment, and bank-statement
  PostgreSQL persistence plus authenticated server-API contracts passed
  (24 industry/API tests), alongside the live metrics parity and Alembic
  command-availability contracts (2 tests).
- The disposable Redis 7.4 service was available for the server profile, and
  both containers were removed after the run. Existing Starlette/httpx
  deprecation warnings were the only observed warnings.
- Boundary: one local Docker host with synthetic records. This does not prove
  hosted CI, native PostgreSQL backup binaries, live ERP/bank provider
  interoperability, source authenticity, payment initiation, statutory
  posting, write-back, independent HA/DR, or production readiness. GitHub
  publication remains frozen by D-485.

## E-715 — bind financial policy to work-order results (2026-08-11)

- `reconcile_workorders` now validates a keyword-only financial-input policy,
  passes it to every monetary ingress, and records it on
  `WorkorderReconciliationResult`; current CLI and Studio callers select
  strict-v2 explicitly, and the Work-order JSON/workbook artifacts expose it.
- Combined management-pack generation refuses unsupported or mixed Stock/GL
  and Work-order policies before writing output. Focused work-order/report/
  reconciliation-policy tests, Ruff, and Mypy pass. The full local pytest
  regression exits 0 at 100% with only declared capability skips/warnings;
  Bandit, OSV `pip-audit`, package build, diff-check, and Gitleaks 8.30.1
  (726 commits / 24.39 MB history; 31.12 MB tree) also pass. Hosted execution,
  statutory posting, and publication remain separate under D-485.

## E-714 — reject legacy financial policy at PostgreSQL reconciliation writers (2026-08-11)

- The low-level PostgreSQL `create_run` path now validates before any
  idempotency lookup or SQL: omitted policy is normalized to strict-v2, while
  explicit legacy or unknown policy values fail closed. Historical rows remain
  readable only through the named compatibility reader from E-713.
- Parameterized no-mutation tests cover legacy and unsupported policies;
  focused PostgreSQL/persisted-JSON/financial-input tests, Ruff, and Mypy pass.
  The full local regression and package/security gates pass; the
  post-implementation-commit Gitleaks scan covers 724 commits (24.38 MB
  history) and a 31.09 MB tree with no findings. Live PostgreSQL, hosted CI,
  statutory posting, and publication remain open under D-485.

## E-713 — bind strict financial policy at PostgreSQL reconciliation write boundary (2026-08-11)

- `PostgresReconciliationRepository.create_run` now copies every new rule and
  persists `strict-financial-input-v2` when a direct repository caller omits
  the optional policy. The worker's missing-field behavior is isolated in a
  named historical-reader helper, preserving replay for pre-existing rows
  without leaving a new-write default implicit.
- A repository contract proves the stored JSONB rule carries strict-v2;
  focused PostgreSQL/persisted-JSON/financial-input tests, Ruff, and Mypy pass.
  The full local regression and release/security/package gates pass; the
  post-implementation-commit Gitleaks scan covers 722 commits (24.37 MB
  history) and a 31.08 MB tree with no findings. Historical compatibility,
  live backend execution, hosted CI, statutory posting, and publication remain
  open under D-485.

## E-712 — reviewed per-run budgets for grouped matching (2026-08-11)

- `MatchingStrategyRequest` now accepts an optional `GroupedMatchBudget` that
  can lower the grouped strategy's reviewed cardinality/search ceilings.
  Values above the manifest or below the selected mode's floor fail closed;
  non-grouped strategies reject the field instead of ignoring it.
- The effective override is bound into the canonical request digest, while
  grouped decision digests already retain the effective policy. Focused
  contract tests, full local regression, static/security/package gates, and
  post-implementation-commit Gitleaks (720 commits/24.36 MB history;
  31.07 MB tree) pass. Distributed fault injection, live-backend parity,
  mutation coverage, throughput, production sizing, and publication remain
  open under D-485.

## E-711 — persisted currency-registry snapshots (2026-08-11)

- Workspace bindings now persist one canonical, digest-checked currency
  registry JSON snapshot per registry digest. SQLite migration 41 and
  PostgreSQL Alembic `0088_pg_currency_snapshot` add bounded storage;
  binding writes snapshot plus metadata atomically, and backup/export retain
  the snapshot without exposing raw financial data.
- Master-data reconciliation automatically selects the bound historical
  snapshot as its immutable operation context. It compares that context with
  the current installed registry and reports `drifted` rather than silently
  switching policy. Missing, malformed, or digest/version-mismatched snapshots
  fail closed; legacy pre-41 bindings must be rebound before reconciliation.
- Focused governance, master-data, backup/restore, export, PostgreSQL schema,
  and migration-chain tests pass locally. The full local regression, Ruff,
  Mypy, Bandit, OSV `pip-audit`, package build, structured-doc parsing,
  diff-check, FI-013 parser inventory, and post-commit Gitleaks scans
  (718 commits/24.34 MB history; 31.05 MB tree) also pass. Live PostgreSQL
  execution, hosted CI, independent HA/DR,
  and publication remain unverified and frozen under D-485.

## E-710 — immutable currency-registry operation context (2026-08-11)

- `CurrencyRegistry.context()` now captures one digest-checked immutable
  snapshot. `Money`, `MinorMoney`, and `ExchangeRate` can resolve through it;
  canonical-money restoration refuses mismatched registry lineage, and
  reconciliation freezes one context at operation start or accepts an
  explicit replay context.
- Registry updates remain explicit and process-wide; the context never mutates
  or switches them. Focused tests cover mutation isolation, minor-unit/FX
  behavior, snapshot round-trip, and governance replay. Independently
  persisted historical versions and automatic binding selection are now E-711;
  hosted/live PostgreSQL and publication remain open under D-485.
- The full local pytest regression exits 0 with no failures; declared
  capability skips and existing warnings remain visible. Ruff, Mypy (520
  source files), JSON/YAML parsing, package build, and diff-check also pass.

## E-709 — persisted workspace currency-registry binding (2026-08-11)

- Each workspace can now bind the installed currency-registry version and
  digest with an actor and UTC timestamp. Reconciliation reports explicit
  `unbound`, `current`, `drifted`, or sanitized `invalid` binding state and
  treats drift/invalid state as inconsistent rather than switching the
  process-wide registry.
- SQLite migration 40 and PostgreSQL Alembic `0087_pg_currency_binding` add
  workspace/tenant scope, PostgreSQL forced RLS, audit/outbox evidence, and
  backup/export retention. Authenticated API and local CLI bind paths are
  covered by focused contracts; hosted/live PostgreSQL execution and
  publication remain open under D-485. E-710 and E-711 extend operation
  context and historical snapshot replay without implying live or production
  assurance.
- The full local pytest regression exits 0 with no failed tests; only declared
  capability skips and existing financial-input/HTTP deprecation warnings
  remain. Ruff, Mypy (520 source files), JSON/YAML parsing, package build, and
  diff-check also pass. Gitleaks tree/history and hosted PostgreSQL/native
  backup evidence remain separate gates.

## E-708 — currency registry reconciliation evidence (2026-08-11)

- Master-data currency references now have a bounded, order-independent
  reconciliation contract against the installed `CurrencyRegistry` policy
  snapshot. It binds registry version/digest and a separate input digest, and
  surfaces malformed, duplicate, unknown, and minor-unit mismatch issues
  without echoing names or financial values.
- Local snapshots, the authenticated master-data API, PostgreSQL server route,
  and local CLI expose the read-only result. SQLite's current currency table is
  database-global, so workspace scope is recorded but is not presented as
  persistent per-workspace registry selection. Persistent selection and live
  backend context remain open; publication stays frozen by D-485.

## E-707 — explicit Management Pack financial-input quality issues (2026-08-11)

- Management Pack optional `risk_score` and amount candidate groups continue
  to parse under `strict-financial-input-v2`; when a present group has no valid
  value, the workbook Data Quality Warnings sheet and optional JSON
  `data_quality_warnings` property now contain a non-sensitive error row.
- Valid fallback fields remain usable without duplicate noise. The issue keeps
  frame/row/column/status metadata and never echoes raw financial values. This
  is additive report evidence only; statutory accounting, external providers,
  and publication remain outside the slice and frozen by D-485.

## E-706 — final local verification after the publication freeze (2026-08-11)

- The current local head passes the full `uv run --no-sync pytest -q -ra
  --tb=short` regression at 100%; only declared external-service/platform
  skips and existing warnings remain. Ruff, Mypy (519 files), the Phase-4
  execution contract, YAML parsing, package-focused docs/manifest tests,
  `python -m build --no-isolation`, and `git diff --check` also pass.
- Post-commit Gitleaks 8.30.1 scans pass for both the checked tree (30.87 MB)
  and complete local history (709 commits / 24.21 MB), with no findings. This
  is local evidence only. Hosted native PostgreSQL backup/restore, hosted
  security attestation, all seven P4 exit gates, and publication remain open
  under D-485.

## E-705 — Gitleaks history and checked-tree closure (2026-08-11)

- The checksum-verified Windows x64 Gitleaks 8.30.1 scan passes on the current
  tree (`dir`, 30.86 MB) and complete local history (`git --log-opts=--all`,
  708 commits / 24.21 MB), both with exit 0 and no findings.
- Two exact fingerprints cover wording in the immutable E-701 commit; the
  current docs use neutral authorization wording. No broad path, commit-range,
  regex, or rule exclusion was added. This is local evidence only; hosted
  repository-security attestation and publication remain external and frozen
  by D-485.

## E-704 — Python 3.11/3.12 all-extras collection closure (2026-08-11)

- Reproduced the locked CI dependency profile with
  `uv run --isolated --python 3.11/3.12 --all-extras --locked --no-editable`.
  `cbor2`, `cryptography`, and `opentelemetry.sdk.metrics` import successfully
  under both interpreters.
- The seven historical collection-failure modules pass on Python 3.11 and
  3.12: 48 passed per interpreter, with only the declared live-PostgreSQL
  WebAuthn skip. This closes the local optional-dependency reproduction, not
  hosted CI or E-461.
- Publication remains frozen by D-485.

## E-703 — bounded World Bank live reference refresh (2026-08-11)

- The opt-in `test_live_world_bank_public_page_is_bounded_and_schema_valid`
  passed through the real pinned HTTPS transport: one attempt, 1,000 rows,
  observed source count 2,508, request digest
  `ee621eaf822249cd61b8b921392e88c3b0c8e810fcf3dec9aa4acf8510e82e11`, and
  response digest `9f0e40df0fe72f2310e8e5747285f4657389ffe4f55b844e5ca405da6f88dc11`.
- This is public reference reachability/schema evidence only. Data is mutable;
  no freshness, SLA, ERP/bank provider, credential, write-back, or production
  availability claim is allowed. Publication remains frozen by D-485.

## E-702 — PostgreSQL RLS Payment Entry intent runtime (2026-08-11)

- Added a live-when-configured PostgreSQL server-boundary test for the
  provider-specific Payment Entry operation. A disposable tenant and
  non-privileged role persist the exact draft digest through proposal,
  independent approval, dispatch, and acknowledgement.
- The test proves idempotent proposal replay, version conflict refusal,
  sibling-tenant denial, digest binding, acknowledged status, and append-only
  database immutability. It is discovered through the existing PostgreSQL
  parity inventory/server-boundaries matrix.
- Boundary: one-node synthetic PostgreSQL intent persistence only; no live
  ERPNext/provider call, posting, compensation, statutory accounting,
  production write-back, or P4-CON-001 exit. Publication remains frozen by
  D-485.

## E-701 — ERPNext Payment Entry authenticated API replay fence (2026-08-11)

- The existing authenticated write-back intent API now has a dedicated
  provider-specific Payment Entry contract test. It stages the exact
  one-sided Decimal payload, enforces actor-bound proposal and independent
  approval, dispatches through explicit server registration, persists the
  acknowledgement, and replays without a second provider call.
- Assertions cover the exact `Payment%20Entry` path, authorization metadata,
  operation/idempotency headers, `docstatus=0`, exact payload bytes, and
  secret-free API output. The test uses a synthetic injected transport and
  SQLite persistence behind the server-operation seam.
- Boundary: this proves API governance/replay wiring only; it does not prove
  live ERPNext tenancy, provider status/idempotency semantics, posting,
  compensation, statutory accounting, production write-back, or P4-CON-001.
  Publication remains frozen by D-485.

## E-700 — ERPNext Payment Entry draft write-back boundary (2026-08-11)

- Added a provider-specific `Payment Entry` draft contract with exact
  non-negative Decimal text, exactly one positive paid/received side,
  same-account refusal, uppercase currency validation, deterministic JSON,
  fixed `docstatus=0`, token-only registration, and the existing disabled-by-
  default write-back policy.
- The real pinned HTTPS sandbox now exercises maker/checker approval, the
  provider registration, exact payload bytes, operation and idempotency
  headers, transient retry, digest-bound acknowledgement, and receipt secret
  hygiene. Package exports and sdist membership are covered.
- Boundary: this is synthetic provider-compatible draft evidence only. It does
  not prove live ERPNext tenancy, account mapping, vendor status/idempotency
  semantics, posting, compensation, production write-back, statutory
  accounting, or P4-CON-001; publication remains frozen by D-485.

## E-699 — API write-back recovery over pinned HTTPS status lookup (2026-08-11)

- The authenticated recovery route now has an end-to-end local contract over
  the real `PinnedHttpsRecoveryTransport`: a dispatched intent is recovered by
  one HTTPS GET to the declared idempotency-status endpoint, the provider
  acknowledgement is digest-validated and persisted at version 4, and a
  replay returns `already_acknowledged` without another GET or any POST.
- The test keeps the maker/checker and server-scoped persistence seam active,
  verifies the original idempotency key, recovery header, authorization,
  exact status path, and secret-free response, and pins the socket to a
  disposable loopback TLS sandbox after the public-address resolver gate.
- Boundary: this is synthetic local provider-compatible recovery evidence. It
  does not prove a real ERPNext/vendor status API, PostgreSQL deployment,
  external credential governance, compensation semantics, production
  operations, or P4-CON-001; publication remains frozen by D-485.

## E-698 — ERPNext write-back API route and replay fence (2026-08-11)

- The authenticated connector API now has a provider-specific ERPNext Journal
  Entry contract in the test matrix. A synthetic maker proposes and a distinct
  checker approves the balanced draft; the server-scoped dispatch route sends
  the exact ERPNext payload through the registered network executor, returns a
  digest-bound acknowledgement, and a replay returns `already_acknowledged`
  without a second provider call.
- The test asserts the exact Journal Entry endpoint, `token` authorization,
  operation name, idempotency key, payload bytes, provider reference, and
  absence of the synthetic credential from the HTTP response. It uses a
  SQLite persistence substitute behind the existing server-boundary seam and
  never contacts an external provider.
- Boundary: this proves API wiring and replay behavior for a synthetic
  provider-compatible registration only. It does not prove live ERPNext
  tenancy, PostgreSQL/RLS deployment of this route, vendor idempotency/status
  recovery, production write-back, or P4-CON-001; publication remains frozen
  by D-485.

## E-697 — ERPNext Journal Entry write-back over pinned HTTPS sandbox (2026-08-11)

- A disposable HTTPS provider-compatible endpoint now exercises the real
  ERPNext Journal Entry draft payload builder, write-back registration,
  maker-checker lifecycle, `WritebackNetworkExecutor`, and
  `PinnedHttpsPostTransport`. The endpoint returns one transient 503 followed
  by a 201 acknowledgement; the focused test exits 0 with two attempts,
  exact balanced payload bytes, token authentication, operation binding, and
  the same idempotency key on every request.
- The provider acknowledgement is digest-validated and bound to the intent;
  the receipt contains no credential bytes. The test uses only a generated
  localhost certificate, synthetic accounting rows, an injected public test
  address, and a loopback-pinned socket; no external ERPNext tenant or
  customer/provider secret is contacted.
- Boundary: this closes only a local provider-compatible HTTPS POST contract.
  It does not prove live ERPNext interoperability, vendor idempotency or
  status-recovery semantics, governed production write-back, compensation,
  external credentials, or P4-CON-001. The remaining Phase-4 exits remain
  open and publication stays frozen by D-485.

## E-696 — Live PostgreSQL federation replay/session/RLS gate (2026-08-11)

- The disposable current-head PostgreSQL service passed the non-superuser
  federation contract: a tenant-scoped OIDC principal link is persisted as a
  hash only, an assertion replay is accepted once and refused on reuse, an
  OIDC login challenge is consumed once and refused on replay, and a session
  is created and authenticated through the identity repository.
- A second tenant observes zero federation links, challenges, or assertion
  replays. Synthetic rows and credentials are cleaned up in guarded order.
  This selector is now an explicit hosted `server-boundaries` command with a
  phase-4 workflow-contract assertion.
- Boundary: one-host synthetic PostgreSQL/RLS federation evidence only. It does
  not prove provider interoperability, signed OIDC/SAML validation against a
  real IdP, SCIM provisioning, distributed session/cache invalidation, MFA
  assurance, HA/DR, or production IAM; P4-IAM-001 and the other Phase-4 exits
  remain open and publication stays frozen by D-485.

## E-695 — Current-head PostgreSQL consolidation-close lifecycle (2026-08-11)

- Upgraded the disposable PostgreSQL service from migration `0082` through
  Alembic head `0086_pg_close_reopened`, then ran the direct non-superuser
  consolidation-close lifecycle. Prepare/replay, independent approval,
  control-journal posting, certification maker-checker, reversal, period
  lock/reopen, impairment/deferred-tax/PPA/ownership evidence links,
  intercompany binding, append-only tamper refusal, digest replay, and
  sibling-tenant isolation all passed.
- The authenticated HTTP consolidation-close suite also passed both live
  contracts, including Alembic-head verification and RLS/maker-checker route
  behavior. The direct backend selector is now an explicit hosted
  `server-boundaries` command, so it cannot be hidden inside another filter.
- This is current-head, one-host, synthetic PostgreSQL/RLS control evidence.
  It is not statutory/legal-book accounting, live rates, external ERP/bank
  posting, independent HA/DR, restore/DR proof, or production assurance;
  P4-FIN-002 and the other Phase-4 exits remain open and publication stays
  frozen by D-485.

## E-694 — Live PostgreSQL sequence-window ambiguity closure (2026-08-11)

- The live sequential-worker fixture now includes four equal-value obligations
  and one settlement that produces two equal-cost contiguous windows. PostgreSQL
  completed the run without selecting either candidate: all five source rows
  are `Ambiguous`, `matched_count` is zero, and five concrete `Left`/`Right`
  review exceptions carry `SEQUENCE_WINDOW_AMBIGUOUS_EQUAL_COST`.
- The adapter now projects ambiguity to the durable schema's concrete source
  sides instead of emitting the invalid `source_side=Both`. Every exception
  and result lineage carries the same strategy-result digest as direct
  `CarryForwardFifoStrategy` execution. Unit and live PostgreSQL tests exit 0.
- This is bounded, one-host synthetic PostgreSQL/RLS and non-posting evidence.
  It does not establish global optimality, hosted execution on this branch,
  distributed recovery, provider behavior, posting/write-back, HA/DR, or
  production sizing. P4-MAT-001 and the other Phase-4 exits remain open;
  publication stays frozen by D-485.

## E-693 — Live PostgreSQL sequence-window worker parity (2026-08-11)

- Extended the existing disposable PostgreSQL sequential-worker fixture with a
  real `sequence-window` run alongside carry-forward and reversal pairing.
  The live non-privileged worker persisted two contiguous allocations into one
  settlement, one visible unmatched obligation, the strategy lineage and
  reason code, and a result digest equal to direct `CarryForwardFifoStrategy`
  execution.
- The focused live selector exited 0; the sequential projection suite and the
  complete grouped/sequential runtime file pass with the expected capability
  skips. This also remains covered by the existing explicit `server-boundaries`
  worker selector.
- This is one-host synthetic PostgreSQL/RLS, non-posting evidence. It does not
  establish hosted execution on this branch, global optimality, distributed
  recovery, provider behavior, posting/write-back, HA/DR, or production
  sizing. P4-MAT-001 and the other Phase-4 workstream exits remain open;
  publication stays frozen by D-485.

## E-692 — Live HTTP scoped-export service-account and RLS contract (2026-08-11)

- Added a real `TestClient` contract for
  `test_live_server_scoped_export_http_is_service_scoped_and_tenant_isolated`.
  Against the disposable PostgreSQL 16.14 service, a least-privilege service
  account with `reports.read` and explicit workspace/organization/entity grants
  received a deterministic `/api/v1/exports/scoped` response; a sibling
  workspace was denied before snapshot access and a sibling tenant token was
  rejected.
- The test creates only synthetic tenants/hierarchy rows, uses no customer or
  provider data, and removes its rows in guarded dependency order. The focused
  live command exited 0; the complete scoped-export file remains green with
  one declared no-DSN skip. The server-boundaries workflow now invokes this
  selector separately from the durable-job filter, with a phase-4 contract
  assertion.
- This is single-host local HTTP/PostgreSQL/RLS evidence only. It does not
  establish hosted execution, object-store/KMS/replication durability, live
  ERP/bank behavior, write-back, independent HA/DR, or production IAM. E-461
  and all seven Phase-4 workstream exits remain open; publication stays frozen
  by D-485.

## E-691 — Hosted invocation fence for live RLS-scoped exports (2026-08-11)

- Added the live `test_scoped_exports.py` hierarchy-isolation selector to the
  `server-boundaries` workflow as a separate command, so it cannot be hidden by
  the durable-job `-k` filter. The phase-4 contract remains green with 9 tests,
  Ruff and YAML parsing pass.
- The hosted job will now exercise PostgreSQL forced-RLS workspace/entity
  export exclusion and local publication semantics alongside the other live
  boundaries. No hosted rerun has occurred on this unpushed branch.
- This is a CI coverage fence only; it does not claim provider object storage,
  KMS, replication, write-back, HA/DR, or production deployment. Publication
  remains frozen by D-485.

## E-690 — Fail-closed CI invocation for native backup and metrics gates (2026-08-11)

- Corrected `.github/workflows/ci.yml` so the live `test_postgres_backup.py`
  encrypted backup/isolated restore selector and the live
  `test_application_metrics.py` PostgreSQL/SQLite parity selector run as
  explicit commands before the durable-job `-k` matrix. The earlier combined
  command could filter both tests out because its `-k` expression only matched
  durable-job names.
- Added phase-4 contract assertions for both exact selectors; the focused
  workflow contract passes 9 tests, Ruff passes, and the workflow parses as
  YAML. This is a local workflow-fence correction, not hosted execution.
- E-461 still requires a Hosted Linux run with native PostgreSQL tools to prove
  encrypted backup, isolated restore, and cleanup; publication remains frozen
  by D-485.

## E-689 — Fresh repeated PostgreSQL HA/DR Docker drill (2026-08-11)

- Ran `.github/scripts/verify_postgres_ha_dr_repeated.py` for exactly three
  disposable PostgreSQL 17.10 primary/synchronous-standby cycles. All runs
  passed encrypted backup/isolated restore, fencing, manual promotion,
  rejoin/failback, sentinel sequence verification, and labelled-resource
  cleanup.
- Each run ended at sequence 4 with zero acknowledged transaction loss. The
  observed failover RTO range was 11.359–11.476 seconds and failback RTO range
  was 1.121–1.250 seconds, below the 60-second drill ceiling. The durable
  report is `docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION_2026-08-11.json`
  with SHA-256
  `6e527ae12c9cb3e6123fac5136d31b6b2b3c0a4bebbf64267cd0c5e1f3ec749b`.
- This remains two containers on one Docker host with a manual controller,
  synthetic data/key, no quorum/witness, and no independent failure domain;
  it does not close E-461 or prove automatic failover, site-loss DR, managed
  key custody, or production availability. Publication remains frozen by
  D-485.

## E-688 — Fresh Redis shared policy-generation and read-reconnect runtime (2026-08-11)

- Ran two live Redis foundation contracts against the disposable local
  `redis:7.4-alpine` service. Both tests exited 0: two independent connection
  factories observed the same policy-cache generation after atomic bumps, and
  a session read recovered after an explicit connection-pool disconnect.
- This refreshes the cross-process policy-cache invalidation and safe read
  reconnect boundary only. It is single-node synthetic evidence; Redis
  Sentinel/Cluster failover, replication durability, cross-site recovery,
  distributed rate-limit/quota guarantees, and production SLOs remain open.
- P4-IAM-001/P4-REL-001 and E-461 remain open; publication remains frozen by
  D-485.

## E-687 — Fresh PostgreSQL durable-job 100K-effect runtime (2026-08-11)

- Re-ran the current 16-worker PostgreSQL durable-job 100K profile against the
  disposable PostgreSQL 16.14 service with the non-privileged
  `reconforge_app` role. The test exited 0 and completed 2,500 jobs across four
  tenant lanes, 40 partitions per job, and 100,000 committed partition effects.
- Structural result: zero duplicate partition effects, zero final queued jobs,
  zero final running jobs, and exactly 625 completions per tenant lane. The
  effect-set digest is
  `c3ea127dc2bcdd0b626170bd67a1e6461b2a4b3985d210ae64f471a664d85051` and the
  profile manifest digest is
  `50e53748b1064f1e749aeaa1342bd3537d5f8b2ecde3bc4b8bfc275567d622b6`.
- Observed Windows/Python runtime was 269.682 seconds (9.2702 jobs/second);
  this is a hardware/load observation only. No new artifact was emitted or
  rewritten. Queue HA, automatic failover, host loss, cross-host fairness,
  soak/backpressure coupling, RPO/RTO, and production sizing remain open.
- Publication remains frozen by D-485; P4-SCL-001/P4-REL-001 and E-461 remain
  open.

## E-686 — Fresh bounded World Bank public-data connector run (2026-08-11)

- With `RECONFORGE_TEST_PUBLIC_NETWORK=1`, the current World Bank read-only
  reference connector suite exited 0 with 7 passing tests. One bounded page
  request used the manifest's fixed public endpoint and exercised finite
  Decimal parsing, the closed schema, count/page-size bounds, canonical
  response digest, retry/idempotency metadata, and network egress policy.
- This is public open-data interoperability evidence only. The connector has
  no credentials, is read-only, and is not an ERP/bank customer connector,
  source-authenticity attestation, payment path, write-back, provider SLA,
  HA/DR, or production operations claim.
- P4-CON-001 remains open for named live providers, sandbox/conformance
  coverage, governed write-back, signed executable-package deployment, and
  operational evidence. Publication remains frozen by D-485.

## E-685 — Live PostgreSQL RLS-scoped export and immutable local publication (2026-08-11)

- Ran the existing live scoped-export contract against the disposable
  PostgreSQL 16.14 service with the non-privileged `reconforge_app` role. The
  test exited 0 and exercised workspace/entity hierarchy context, forced-RLS
  snapshotting, sibling workspace/organization/entity/job/evidence exclusion,
  deterministic bytes, and publication through the hierarchical local object
  store.
- The entity-scoped path omits the workspace-only evidence registry dataset by
  policy, publishes the exact snapshot bytes under the scoped object key, and
  the test cleanup removes the synthetic tenant and rows. No customer or
  external-provider data was used.
- This is one-host synthetic PostgreSQL/RLS plus local object-store evidence;
  it does not establish API HTTP coverage, MinIO/S3 interoperability, KMS,
  replication, cross-site durability, live provider behavior, write-back,
  HA/DR, or production SLOs. P4-IAM-001/P4-CON-001 and E-461 remain open.
- Publication remains frozen by D-485.

## E-684 — Fresh PostgreSQL 10K grouped-matching runtime after pool reuse (2026-08-11)

- Re-ran the declared live PostgreSQL 10K grouped-matching profile after
  E-679's worker/pool reuse hardening, using the disposable PostgreSQL 16.14
  service and the non-privileged `reconforge_app` role. The Python runtime was
  3.11.15 on the Windows host; the command exited 0.
- The profile's structural assertions completed 1,000/1,000 runs,
  10,000/10,000 partition checkpoints, and 24,000/24,000 result rows, with
  zero duplicate result identities, zero failed runs, zero active runs, and
  200 completed runs in each of the five declared modes (`fx-many-to-one`,
  `many-to-many`, `many-to-one`, `one-to-many`, and `portfolio`).
- This run emitted no new measured report or digest and did not rewrite the
  checked-in benchmark artifact. It is fresh one-host synthetic correctness
  and bounded-concurrency evidence only; it does not claim throughput,
  capacity, soak, HA/DR, PITR, RPO/RTO, provider integration, posting, or
  write-back. The synthetic tenant remains in the disposable audit database.
- Publication remains frozen by D-485; E-461 and the remaining Phase-4 exit
  gates are still open.

## E-683 — Version-locked PostgreSQL native-tool workflow fence (2026-08-11; ADR 0513)

- Added `.github/scripts/verify_postgres_native_tools.py`, a stdlib-only,
  fail-closed verifier for `pg_config`, `pg_dump`, `pg_restore`, `createdb`,
  `dropdb`, and `psql`. It checks the expected major version, the absolute
  `pg_config --bindir`, each executable's own reported version, and the
  executable actually resolved on `PATH`.
- The `server-boundaries` workflow now installs the client matching the pinned
  PostgreSQL 16 service, runs the verifier before Python dependencies, and
  persists the verified bindir through `GITHUB_PATH`. Both native-tool and live
  test shell blocks explicitly use `set -euo pipefail`; the custom-format dump
  and `pg_restore --list` smoke probe therefore cannot silently use a different
  client or continue after a failed command.
- The focused workflow/native-tool contract passes 12 tests; Ruff, Mypy, YAML
  parsing, and `git diff --check` pass. This is repository-local workflow and
  deterministic fake-tool evidence only; the hosted Linux encrypted backup /
  isolated restore gate E-461 still must execute successfully.
- Publication remains frozen by D-485. Independent HA/DR, PITR, distributed
  IAM, live provider/write-back, and the remaining Phase-4 workstreams remain
  open.

## E-682 — PostgreSQL native-backup stdout compatibility fence (2026-08-11; ADR 0512)

- Hardened `PostgresNativeBackupAdapter` with a final native-runner-only
  compatibility path. After the three closed `--file` argument forms return
  without a usable dump, stdout is redirected directly to the private dump
  file and then passes through the existing size, digest, and AES-256-GCM
  encryption boundary.
- The injected compatibility contract passes 15 PostgreSQL backup tests,
  including the new streamed-stdout fallback. Test runners that do not expose
  the explicit native fallback remain fail-closed, so an arbitrary connector
  cannot introduce an unreviewed output channel.
- The post-slice full Python suite reaches 100% with exit 0; Ruff, Mypy (518
  source files), Bandit, package build, and diff-check pass. A fresh pip-audit
  retry timed out while contacting PyPI; no dependency or lockfile changed,
  and the successful E-681 audit remains the latest completed dependency gate.
- This is a wrapper-resilience slice only. It does not substitute for the
  hosted Linux native-tool/isolated-restore gate E-461, independent HA/DR,
  PITR, or production RPO/RTO evidence. GitHub publication remains frozen by
  D-485.

## E-681 — CI-failure remediation and fail-closed publication guard (2026-08-11; ADR 0511)

- Revalidated the historical hosted failure surfaces locally on the current tree:
  - isolated Python 3.11 all-extra import probe loads `cbor2`, `cryptography`,
    and `opentelemetry.sdk.metrics` successfully;
  - the Python 3.12 all-extra collection slice passes 48 tests with one
    declared live-PostgreSQL skip and no ImportError;
  - a disposable PostgreSQL 16.14 database at Alembic head `0086_pg_close_reopened`
    passes the live metrics-parity and Alembic upgrade/downgrade tests (2/2)
    under the non-privileged `reconforge_app` role;
  - Gitleaks 8.30.1 scans 684 commits and a 30.65 MB working tree with zero
    findings;
  - the release-pipeline contract passes 17 tests, and the new guard blocks
    active D-485 while allowing only an explicit `Status: closed` marker.
- The hosted encrypted native-backup test remains unverified locally because
  Windows has no native PostgreSQL client binaries. E-461 therefore remains
  open; local Docker metrics/Alembic success is not hosted CI evidence.
- No runtime/API/schema or public-release action was performed. GitHub
  publication remains frozen by D-485.

## E-680 — Full local objective sweep and publication freeze reaffirmed (2026-08-11)

- Re-ran the core local hardening sweep end-to-end:
  - `python -m ruff check .` -> pass.
  - `python -m mypy reconforge` -> pass, 518 files, no issues.
  - `python -m pytest` -> pass, **2775 passed / 110 skipped** (23 warnings, 9m 17s).
  - `python -m bandit -q -r reconforge` -> pass (warnings/comments only).
  - `python -m pip_audit` -> pass, **No known vulnerabilities found**.
  - `python -m build --no-isolation` -> pass.
  - `git diff --check` -> pass.
  - Frontend:
    - `npm --prefix apps/web ci`
    - `npm --prefix apps/web run typecheck`
    - `npm --prefix apps/web run test:run` (13 files / 70 tests)
    - `npm --prefix apps/web run build`
    - `npm --prefix apps/web run e2e` (16 passed, 5 skipped, 21 total)
  - Runtime:
    - `reconforge doctor`
    - `reconforge validate examples/sample_data`
    - `reconforge demo run --output output/baseline-demo`
    - `docker build -t reconforge:baseline .`
    - `docker run --rm reconforge:baseline reconforge doctor`
  - Focused hosted-runtime checks (live PostgreSQL/maintenance):
    - `uv run --no-sync pytest -q -rs tests/test_postgres_metrics.py::test_live_postgres_metrics_and_sqlite_parity`
    - `uv run --no-sync pytest -q -rs tests/test_alembic_postgres.py::test_alembic_upgrade_command_is_available_when_server_extra_is_installed`
    - `uv run --no-sync pytest -q -rs tests/test_postgres_backup.py::test_live_postgres_native_adapter_encrypted_backup_isolated_restore_and_cleanup`
    - Result: **3 skipped** (live PostgreSQL service/migration/maintenance services not provisioned in this session).
- Resulting evidence status:
  - `docs/execution/BASELINE.md` updated to match this run.
  - `docs/execution/DECISIONS.md` publication deferral (D-485/D-441) remains in force.
  - `E-461` remains the only objective-critical external-live blocker currently unresolved in this workspace.

## E-678 — Exit-audit slice hardening completed (2026-08-11)

- Re-ran exit-audit gates on the current head:
  - `uv run --no-sync pytest tests/test_phase_1_3_execution_contract.py tests/test_phase_1_exit_audit.py tests/test_phase_2_exit_audit.py`
  - Result: **12 passed**.
- This complements the prior full objective sweep in `E-676`/`E-668` and confirms:
  - phase-1_3 execution contract still green,
  - phase 1 and phase 2 exit-audit suites still green.
- Local hosted-runtime dependency checks remain unchanged:
  - `uv run --no-sync pytest -q -rs tests/test_postgres_backup.py::test_live_postgres_native_adapter_encrypted_backup_isolated_restore_and_cleanup`
    -> skipped: requires disposable PostgreSQL source and maintenance services.
  - `uv run --no-sync pytest -q -rs tests/test_postgres_metrics.py::test_live_postgres_metrics_and_sqlite_parity tests/test_alembic_postgres.py::test_alembic_upgrade_command_is_available_when_server_extra_is_installed`
    -> both skipped due missing live PostgreSQL service path.
- Publication deferral remains in force until all `in_progress` backlog slices and `E-461`
  hosted evidence are closed.

## E-679 — PostgreSQL grouped matching scale fixture hardening (2026-08-11)

- `reconforge/benchmark/postgres_grouped_matching_scale.py`
  now reuses `worker_factory(worker_id)` objects per run profile instead of recreating them on each cycle.
  This reduces churn and preserves connection lease locality under long run profiles.
- `tests/test_postgres_grouped_matching_scale.py`
  now asserts post-run pool behavior (snapshot taken before close) to prove:
  - pool is not marked closed before explicit close,
  - no leased connections remain,
  - connection count remains within declared bounds after workload.
- Focused gate execution:
  - `uv run --no-sync pytest -q tests/test_postgres_grouped_matching_scale.py -k "test_postgres_grouped_matching_scale_profile_is_bounded_and_declares_expected_shape or test_postgres_grouped_matching_scale_profile_rejects_unbounded_mode_changes or test_postgres_grouped_matching_scale_profile_declares_10k_partition_tier or test_postgres_grouped_matching_scale_artifacts_are_in_source_manifest"` -> 4 passed.
  - `uv run --no-sync pytest -q tests/test_postgres_grouped_matching_scale.py` -> 4 passed, 3 skipped (live-profile tests require live PostgreSQL DSN).
- Publication remains deferred; this is scoped to local+fixture hardening and does not close hosted live PostgreSQL parity evidence (`E-461`), scale environment evidence, or production throughput claims.

## E-676 — Local execution hardening re-run completed (2026-08-11)

- Re-ran full local objective gates after the prior request:
  - `uv run --no-sync pytest -q --tb=short -ra` -> all passing, with expected live-service/privilege skips only.
  - `uv run --no-sync ruff check .` -> pass.
  - `uv run --no-sync mypy reconforge` -> 518 files, no issues.
  - `uv run --no-sync bandit -q -r reconforge` -> pass with comment/noise warnings only.
  - `uv run --no-sync python -m pip_audit` -> no known vulnerabilities.
  - `uv run --no-sync python -m build --no-isolation` -> pass.
  - `git diff --check` -> pass.
  - Frontend:
    - `npm --prefix apps/web ci`
    - `npm --prefix apps/web run typecheck`
    - `npm --prefix apps/web run test:run` (13 files, 70 tests)
    - `npm --prefix apps/web run build`
    - `npm --prefix apps/web run e2e` (16 passed, 5 skipped)
  - Runtime:
    - `reconforge doctor`
    - `reconforge validate examples/sample_data` (10 warnings, 0 errors)
    - `reconforge demo run --output output/baseline-demo`
    - `docker build -t reconforge:baseline .`
    - `docker run --rm reconforge:baseline reconforge doctor`
  - `uv run --no-sync pytest tests/test_postgres_backup.py::test_live_postgres_native_adapter_encrypted_backup_isolated_restore_and_cleanup`,
    `uv run --no-sync pytest tests/test_postgres_metrics.py::test_live_postgres_metrics_and_sqlite_parity`,
    `uv run --no-sync pytest tests/test_alembic_postgres.py::test_alembic_upgrade_command_is_available_when_server_extra_is_installed`
    -> skipped locally (missing native PostgreSQL client runtime + disposable live service path).
- Publication status unchanged: GitHub publish/deploy remains intentionally deferred while open live-runtime gates (`E-461`) are not yet demonstrated in hosted evidence.

## Current phase

Phase 4 — Global Capability Expansion (active; Phase 1–3 owner/team scope remains complete)

## Remaining blockers to objective closure

- Active backlogs still `in_progress` in `docs/execution/BACKLOG.yaml`:
  - `P4-FIN-002`, `P4-MAT-001`, `P4-CON-001`, `P4-SCL-001`, `P4-REL-001`, `P4-IAM-001`, `P4-PLAT-001`, `E-461`.
- `P4-PLAT-001` is blocked by the seven other active workstreams above.
- `E-461` (hosted PostgreSQL native-tool backup bootstrap gate) remains open: a reproducible local WSL proof exists, but the encrypted backup/isolated restore gate itself remains a hosted CI requirement for release evidence.

## E-668 — Full objective closure baseline sweep completed locally (2026-08-11)

- All quality and baseline execution gates now pass locally on the same tree:
  - `python -m ruff check .`
  - `python -m mypy reconforge`
  - `python -m pytest -q`
  - `python -m bandit -q -r reconforge`
  - `python -m pip_audit`
  - `python -m build --no-isolation`
  - `git diff --check`
- Frontend baseline gates pass:
  - `npm --prefix apps/web ci`
  - `npm --prefix apps/web run typecheck`
  - `npm --prefix apps/web run test:run`
  - `npm --prefix apps/web run build`
  - `npm --prefix apps/web run e2e`
- Runtime proof runs pass:
  - `reconforge doctor`
  - `reconforge validate examples/sample_data` (10 warnings, 0 errors)
  - `reconforge demo run --output output/baseline-demo`
  - `docker build -t reconforge:baseline .`
  - `docker run --rm reconforge:baseline reconforge doctor`
- Existing open items remain explicit and unresolved before any release-readiness claim:
  - live environment publish-readiness and HA/DR external controls remain scoped to
    hosted and independent evidence gates.
  - GitHub publication remains deferred by `docs/execution/DECISIONS.md` (D-485)
    until the owner approves closure of all remaining phase gate criteria.

## E-600 — Full local baseline + UI/runtime gates after prior closeout (2026-08-09)

- Frontend production stack is now green locally:
  - `npm --prefix apps/web ci`
  - `npm --prefix apps/web run typecheck`
  - `npm --prefix apps/web run test:run` (12 files, 67 tests)
  - `npm --prefix apps/web run build`
  - `npm --prefix apps/web run e2e` (15 passed, 5 skipped)
- Runtime and workflow commands are now green locally:
  - `reconforge doctor` success
  - `reconforge validate examples/sample_data` (0 errors, 10 warnings)
  - `reconforge demo run --output output/baseline-demo` success with full artifact set
- Python quality/security/package gates are now green locally:
  - `python -m ruff check .`
  - `python -m mypy reconforge` (500 source files, no issues)
- `python -m pytest` (2686 passed, 92 skipped, 0 failed)
  - `python -m bandit -q -r reconforge`
  - `python -m pip_audit`
  - `python -m build --no-isolation`
  - `git diff --check`
- Blocked environment evidence:
  - `docker build -t reconforge:baseline .` and `docker run --rm reconforge:baseline reconforge doctor` are blocked locally by missing Windows Docker daemon (`npipe:////./pipe/dockerDesktopLinuxEngine`).
- Release posture remains non-final until all `in_progress` slices and hosted `E-461` gated evidence close.

## E-613 — PostgreSQL outbox revocation fence (focused gate passed)

- `PostgresOutboxWorker` now re-evaluates the configured central service-account
  policy immediately before each publisher side effect, after the lane claim
  has completed.
- A revoked permission fails closed before publisher I/O and before the
  published acknowledgment; the claimed event remains lease-recoverable.
- `tests/test_postgres_outbox.py` passes 15 tests plus 2 declared PostgreSQL
  capability skips; Ruff, Mypy, and diff-check pass for the changed slice.
- This is synthetic single-process revocation-window evidence only. It does
  not close distributed invalidation, broker exactly-once delivery, external
  provider behavior, HA/DR, or production IAM. GitHub publication remains
  deferred by owner policy.

## E-615 — PostgreSQL scheduler revocation fence (focused gate passed)

- `PostgresSchedulerWorker` now re-evaluates the configured service-account
  policy immediately before scheduled-work dispatch, after the pre-connection
  lane check.
- A synthetic revocation blocks `process_due` entirely and the fresh database
  connection is still closed deterministically.
- `tests/test_postgres_scheduler_worker.py` passes 7 tests; Ruff and Mypy pass
  for the changed worker/test slice.
- The fresh full `python -m pytest -q --tb=short -ra` regression reaches 100%
  and exits 0; `python -m build --no-isolation` and Bandit also exit 0. The
  declared optional-service skips and existing warnings remain visible.
- This is fake-connection, process-local authorization-fence evidence only. It
  does not close distributed invalidation, queue HA, broker semantics, live
  PostgreSQL, or production scheduling SLOs. GitHub publication remains
  deferred by owner policy.

## E-614 — PostgreSQL backpressure retry ceiling (focused gate passed)

- The PostgreSQL durable-job backpressure profile now uses a finite per-job
  submission-attempt budget (default 1,000) and capped exponential backoff
  (2 ms initial, 250 ms maximum) when the queue cap rejects a producer.
- A dependency-free failure-injection contract proves successful recovery,
  delay capping, and deterministic refusal after the finite budget; the
  existing live PostgreSQL profile remains bounded and capability-gated.
- `tests/test_postgres_durable_job_backpressure.py` passes 12 tests and Ruff,
  Mypy, and diff-check pass for the changed slice.
- This closes an unbounded-loop safety gap only. It does not establish
  throughput, capacity, queue HA, cross-host fairness, soak, RPO/RTO, or
  production retry defaults. GitHub publication remains deferred by owner
  policy.

## E-616 — PostgreSQL scoped-export revocation fence (focused gate passed)

- The bounded scoped-export publisher accepts an optional revocation-aware
  policy supplier and re-evaluates the exact hierarchy immediately before the
  object-store write.
- Failure injection proves a revoked `reports.read` permission leaves the
  snapshot work completed but creates no external artifact. The focused
  scoped-export suite and static gates pass under ADR 0456.
- The subsequent full pytest regression reaches 100% and exits 0; full Ruff,
  Mypy (500 source files), Bandit, pip-audit, package build, supply-chain
  validation, and diff-check also exit 0.
- This is opt-in, process-local authorization evidence only. Distributed
  invalidation, live object storage, provider behavior, HA/DR, and production
  IAM remain open. GitHub publication remains deferred by owner policy.

## E-617 — PostgreSQL reconciliation claim revocation fence (focused gate passed)

- The PostgreSQL reconciliation worker re-evaluates the exact service-account
  policy inside the fresh transaction immediately before `claim_run`.
- A synthetic revocation raises a dedicated no-effect denial, closes the
  connection, and leaves the queued run untouched; matcher failures retain the
  existing retryable failure path.
- Focused worker tests, Ruff, and Mypy pass under ADR 0457. Distributed
  invalidation, live multi-host behavior, queue HA/DR, and production IAM
  remain open.
- The subsequent full pytest regression reaches 100% and exits 0; full Ruff,
  Mypy (500 source files), Bandit, pip-audit, package build, supply-chain
  validation, and diff-check also exit 0.
- GitHub publication remains deferred by owner policy.

## E-618 — Write-back provider-dispatch revocation fence (focused gate passed)

- Normal and compensation write-back routes re-evaluate
  `connectors.writeback.dispatch` after staging and immediately before
  provider mutation.
- Failure injection proves revocation yields 403 with zero provider calls; the
  staged intent remains retryable and an authorized retry completes.
- Focused API tests, Ruff, and Mypy pass under ADR 0458. The subsequent full
  pytest regression reaches 100% and exits 0; full Ruff, Mypy (500 source
  files), Bandit, pip-audit, package build, supply-chain validation, and
  diff-check also exit 0. Distributed invalidation, live vendor semantics,
  vault operation, HA/DR, and production write-back remain open. GitHub
  publication remains deferred by owner policy.

## E-619 — Write-back recovery revocation fence (focused gate passed)

- The recovery route re-evaluates `connectors.writeback.reconcile` after loading
  the staged dispatched intent and immediately before provider status I/O.
- Failure injection proves revocation returns 403 with zero recovery calls and
  leaves the dispatched intent/version unchanged; the authorized retry uses the
  existing no-POST recovery transport and completes.
- Focused API tests and static gates pass under ADR 0459. The subsequent full
  pytest regression reaches 100% and exits 0; full Ruff, Mypy (500 source
  files), Bandit, pip-audit, package build, supply-chain validation, phase-4
  execution contract, and diff-check also exit 0. Distributed invalidation,
  live vendor semantics, vault operation, HA/DR, and production recovery
  remain open. GitHub publication remains deferred by owner policy.

## E-620 — Bounded contiguous sequence-window matching (focused gate passed)

- `sequence-window` is now a real strategy mode: it searches contiguous unused
  obligation windows with exact Decimal tolerance and published date, scope,
  cardinality, and evaluation bounds.
- Equal-cost candidate windows become an explicit ambiguity; duplicate IDs and
  budget exhaustion fail closed. Worker projection retains allocation residuals,
  sequence rank, reason code, and digest lineage.
- Domain/strategy/worker tests, Ruff, and Mypy pass under ADR 0460. The
  subsequent full pytest regression reaches 100% and exits 0; full Ruff, Mypy
  (500 source files), Bandit, pip-audit, package build, supply-chain
  validation, phase-4 execution contract, and diff-check also exit 0. This is
  experimental local evidence only; live PostgreSQL parity, distributed
  recovery, global optimality, production sizing, and posting remain open.
  GitHub publication remains deferred by owner policy.

## E-621 — Sequential matching replay and adapter parity (focused gate passed)

- `reconforge/benchmark/sequential_matching_replay.py` now runs bounded
  carry-forward, sequence-window, and reversal-pairing partitions through the
  durable-job checkpoint path and the PostgreSQL-worker projection contract.
- Fault injection after each non-terminal checkpoint produces exactly one
  retry, zero duplicate effects, drained queue/running state, and the same
  effect digest as the uninterrupted baseline. The direct strategy and worker
  lineage digests agree, and the one-cent mutation sentinel changes the digest.
- `tests/test_sequential_matching_replay.py` passes 6/6 with Ruff and Mypy.
  The full regression reaches 100% and exits 0; full Ruff, Mypy (501 source
  files), Bandit, pip-audit, package build, phase/supply-chain contracts, and
  diff-check also pass. This remains synthetic SQLite replay evidence, not
  live PostgreSQL parity, independent HA/DR, scale, or posting evidence.
  GitHub publication remains deferred by owner policy.

## E-622 — Sequential matching 10K/100K/1M scale profiles (verified local)

- The new partitioned benchmark covers exact 10K, 100K, and 1M record shapes
  across carry-forward, sequence-window, and reversal-pairing. It preserves
  finite per-partition search limits rather than constructing an unbounded
  cross-partition search.
- Current reports record 2,000/20,000/200,000 matched partitions, zero
  ambiguity/unmatched partitions, explicit unmatched-record counts, zero
  sampled worker-adapter mismatches, zero permutation mismatches, and a killed
  one-cent mutation guard. Measured runtime/peak memory are 11.8138s/0.6831MiB,
  61.4204s/6.329MiB, and 674.4884s/62.8245MiB on Windows/Python 3.14.6.
- The focused scale/index tests and benchmark-index verifier pass. The
  subsequent full pytest regression, Ruff, Mypy (502 source files), Bandit,
  package build, phase/supply-chain contracts, and diff-check pass. `pip-audit`
  was attempted but is blocked by a PyPI TLS read timeout in this environment;
  no audit result is inferred from that blocked command. These are one-host
  synthetic algorithm observations, not live PostgreSQL, distributed capacity,
  soak, SLO, provider, or production-sizing evidence. GitHub publication
  remains deferred by owner policy.

## E-623 — PostgreSQL migration and row-replay compatibility fences (verified local)

- Migration `0078_pg_close_scope` now detects whether each close table has
  `created_at`; legacy runs and child-line tables use an immutable primary-key
  fallback for the hierarchy index. The PPA `0069` downgrade removes the
  trigger actually created by its upgrade.
- PostgreSQL impairment decoding now uses the persisted table order after
  hierarchy columns were appended, preventing replay digests from reading
  the result payload as the request payload.
- Docker PostgreSQL 16.14 upgrades from `0061_pg_writeback_intents` to
  `0081_pg_prof_invoice`; the Alembic round-trip, live close,
  impairment/deferred-tax/PPA/ownership suites, and metrics parity pass.
  Gitleaks 8.30.1 history/tree scans pass, and the final local `pip-audit`
  rerun reports no known vulnerabilities (the project itself is not published
  on PyPI). The native backup test remains skipped locally because Windows
  lacks versioned PostgreSQL client tools on PATH. GitHub publication remains
  deferred by owner policy.
- This closes local migration/replay compatibility evidence only. Hosted CI,
  independent HA/DR, backup/restore, providers, and production readiness
  remain open.

## E-624 — Explicit CI PostgreSQL native-tool dependency contract (verified local)

- The `server-boundaries` workflow now installs both `libpq-dev` and
  `postgresql-client`: `libpq-dev` supplies the `pg_config` utility and the
  client package supplies the versioned native binaries. The existing
  `pg_config --bindir` assertions remain fail-closed for `pg_dump`,
  `pg_restore`, `createdb`, `dropdb`, and `psql`.
- A phase-4 contract test binds the service-file based source and maintenance
  identities, the parity-inventory backup and metrics entries, and the
  explicit Alembic test to the live matrix. `python -m pytest
  tests/test_phase4_execution_contract.py -q --tb=short` passes 8 tests.
- This closes workflow dependency/selection drift locally under ADR 0464. It
  does not promote E-461: a fresh hosted encrypted backup/isolated restore run
  is still required, and GitHub publication remains deferred by owner policy.

## E-625 — Explicit hosted PostgreSQL sequential-worker runtime gate (verified local)

- The server-boundaries workflow now explicitly selects
  `test_live_postgres_grouped_matching_worker_persists_group_lineage_and_is_tenant_scoped`.
  This keeps the worker runtime gate visible even though the parity inventory
  intentionally classifies the pure grouped strategy as `not_applicable`.
- Against Docker PostgreSQL 16.14 with a non-superuser `reconforge_app`, the
  selected integration passes. It persists carry-forward and reversal results,
  verifies strategy-result digests and lineage, and refuses a sibling tenant.
- The phase-4 workflow contract passes after the selector addition. This is
  synthetic single-node/non-posting evidence; fresh hosted CI, distributed
  scale, soak, providers, and production readiness remain open. GitHub
  publication remains deferred by owner policy.

## E-601 — Legacy metrics module path compatibility shim (passed locally)

- Added `tests/test_postgres_metrics.py` as a compatibility shim that re-exports
  `test_live_postgres_metrics_and_sqlite_parity` from `tests/test_application_metrics.py`.
- This keeps older workflow paths that still reference the legacy test module
  name from failing collection while preserving the existing skip/behaviour semantics.
- Local Ruff, targeted pytest, and adapter tests pass. No new runtime or production
  claim is introduced.

## E-498 — Opt-in public network runtime after transport address-retry hardening (passed locally)

- `PinnedHttpsGetTransport` now retries every resolved public IPv4/IPv6 address
  before returning `connector_transport_failed`, and it preserves deterministic
  sorted attempt order plus the existing exact-allowlisted fixed query path.
- New focused transport coverage now verifies:
  1) first-address failure with second-address success,
  2) all-address failure -> `connector_transport_failed`,
  3) non-public destination fail-closed, and
  4) schema/tamper boundary behavior under synthetic fixtures.
- With `RECONFORGE_TEST_PUBLIC_NETWORK=1`, the live reference test
  `test_live_world_bank_public_page_is_bounded_and_schema_valid` passes and returns
  a bounded schema-valid page with request/response digests.
- Boundary remains unchanged: synthetic read-only connector scope, no vendor write-back,
  no SLA, no production deployment evidence.

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

## E-599 — Historical and tree secret-scan closure after hosted false-positive report (passed locally)

- Added four exact `.gitleaksignore` fingerprints to close historical/current false
  positives from docs wording (gitleaks generic-api-key rule) without introducing broad
  gitleaks policy exceptions.
- Confirmed:
  - `python .github/scripts/validate_supply_chain_policy.py --project-root .` exits with status `valid`.
  - `uv run --no-sync pytest tests/test_supply_chain_policy.py` exits `15 passed`.
  - Gitleaks local scan was not executed in this workstation image (binary not installed).
- Boundary statement: local workspace and synthetic ignore entries only; hosted CI security
  attestation, branch protection evidence, and release enforcement remain external
  by policy until publication.

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
  authenticated checker is distinct from the requester after actor normalization.
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

- Branch: `consolidation-journal-lifecycle`, current published head `3a15229bc5246c83d68419028cc3f5d74d3a27a8`; PR #84 is merged.
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
- Historical PR #67 and PR #68 branch names are retained only as immutable historical references in GitHub; no remote branch containing `codex` is used for current publication.
- PR #84 merged the current branch head `3a15229bc5246c83d68419028cc3f5d74d3a27a8` into `main` after all required checks passed. No tag, release, deployment, production mutation, or repository-setting change occurred.

## Task status

## P4-SCL-001 in progress: high-volume concurrent operations and backpressure

### E-257 complete: reproducible durable-job multi-worker load profile (first slice)

- `reconforge/benchmark/durable_job_load.py` drives the existing durable-job worker loop (claim/commit_partition/complete_partition) under real ThreadPoolExecutor contention on a shared SQLite database over a declared small tier (8 workers, 64 jobs, 4 partitions per job, 4 tenants = 256 declared partition effects). It reuses `SQLiteDurableJobRepository`, `DurableJobApplicationService`, and `DurableJobWorkerService` exactly as callers already use them; no new persistence primitive, domain type, repository method, or migration is introduced.
- Each worker is statically pinned to one tenant so per-tenant contention is fair (workers-per-tenant must be an exact multiple); a worker that has handled its fair share exits. The closed schema-v1 manifest carries only the structural outcome (declared shape, completed jobs, committed partition effects, duplicate count, final queue/running depth, per-tenant completions, deterministic effect-set digest, environment, explicit limitations) and excludes observed runtime/peak-memory/throughput from the manifest digest, so the digest is reproducible across runs and hardware while timing varies honestly.
- `verify_load_manifest` asserts completed jobs equal the declared count, duplicate partition effects are zero, the queue drains to zero, committed effects equal completed * partitions_per_job, per-tenant completions sum to the declared count, and limitations retain honest non-claim wording. ADR 0213 documents scope, consequences, and rollback.
- E-257 records 8/8 focused contracts and a 94-test integration matrix (durable-job domain/application/recovery, sqlite durable jobs, consolidation close, module registry, repository boundary, backup/restore, structured ingress, domain repository, generator benchmark) with zero failures. Ruff and Mypy across 381 source files, Bandit, and exact MANIFEST.in membership pass. An E-256 migration-25 regression in `test_sqlite_durable_jobs.py` (hardcoded `current_version == 24` and `applied_versions == [21,22,23,24]`) was discovered by the focused gate and corrected to the repo's `MIGRATIONS[-1].version` convention as part of the E-256 amend.
- P4-SCL-001 remains open: backpressure, soak, PostgreSQL load parity, and 10K/100K/1M/10M named-hardware tier publication are not implemented by these slices. SQLite serializes writes under `BEGIN IMMEDIATE`, so measured contention bounds multi-worker coordination, not database partition parallelism. Retry/backoff coupling was addressed in E-271.

### E-258 complete: queued and running cancellation profiles

- `reconforge/benchmark/durable_job_cancellation.py` reuses the existing application/worker/repository contracts. The small declared profile cancels a queued subset before claims, proves 48/64 completion with 16 cancellations and 192 exact partition effects, then separately proves running-owner cancellation after a committed prefix with clean lease release. Duplicate effects, queue/running depth, and orphaned leases are checked structurally; timing and peak memory are observations outside the manifest digest.
- E-258 focused tests cover profile validation, queued-cancellation drain and no-duplicate effects, two-run structural digest reproducibility, running cancellation/lease release, closed manifest limitations, and distribution membership. P4-SCL-001 remains open for backpressure, soak, PostgreSQL load parity, distributed capacity, and named-hardware 10K/100K/1M/10M publication.

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
`idempotency`-scoped false positive only by exact fingerprints while retaining generated-directory
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
  ceiling, zero duplicate partition effects, complete queue/running drain, local
  bounded retry-delay coupling (`delay = min(max, base * 2^attempt)`) via recorded
  samples, and deterministic effect/manifest digests. ADR 0226 and the benchmark
  document are included in the package manifest.
- This remains a bounded SQLite evidence slice. Provider-managed backoff/jitter,
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
- One Windows 11/Python 3.14.6 run matched all 250,000 partitions with zero
  ambiguity/unmatched results, zero cross-engine/permutation mismatches, and
  identical effect digest `05c76d8c2d30dcf8e85893ce777f5edc27324beb0465538fc76c2e6ea1c4124f`
  and manifest digest `5da7ca5deeeddb1f8d4ee04c23b4d4f79a33b34c6cf2861bc1dbf50ccbc9f7be`.
  Runtime was 617.0014s and peak traced memory was 77.5685 MiB.
- Boundary: exact USD synthetic, one-process partitioned evidence only.
  PostgreSQL runtime parity, distributed load, soak/SLOs, provider I/O, and
  domain-diverse financial workloads remain unverified.

## E-276 — Published 100K grouped-matching profile

- `reconforge/benchmark/grouped_matching_scale.py` now declares a 100,000
  record profile as 25,000 independent true many-to-many partitions. Every
  partition runs through `GroupedSubsetSumStrategy` and the backend-neutral
  application service; every 1,000th partition is replayed with reversed input
  order.
- One Windows 11/Python 3.14.6 run matched all 25,000 partitions with zero
  ambiguity/unmatched results, zero cross-engine/permutation mismatches, and
  identical effect digest `dda82223212af64038094cc21d4a6fed08af76d86a5b9920c1f4bd187d33be41`
  and manifest digest `60aad17ab30533964f61e1b5c64aeba58e56915ee62ac5a75325c25a7133981a`.
  Runtime was 57.9982s and peak traced memory was 7.7881 MiB.
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
  ERP/MRP interoperability, inventory or GL posting, write-back,
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
runtime and current-tree gate entries; its latest parse is 161 unique tasks
(E-460 through E-494 included).
The server-identity fixture, final local gate, PostgreSQL grouped runtime,
public-network evidence, canonical duplicate-detection, final local-gate, RAC
adapter, live Redis cache drill, and final local-gate entries extend that parse
to 183 unique tasks (E-495 through E-516 included): 172 completed, 1 blocked,
8 in progress, and 2 deferred. This administrative ratio is not a
product-readiness percentage;
 the open workstreams and external release gates remain authoritative.
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
The current grouped-matching 1M profile also ran once from this tree with
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
The write-back transport now has an explicit idempotency recovery boundary for
uncertain provider outcomes. A provider-specific injected lookup can bind a
status response to the original key without resolving a payload or issuing a
second POST; the focused suite passes 18/18. Provider status-API
interoperability, distributed idempotency, live ERP/bank write-back, accounting
posting, HA/DR, and release approval remain open.
The recovery primitive is now reachable through the authenticated server route
`POST /api/v1/connectors/writeback/intents/{intent_id}/recover`, protected by
`connectors.writeback.reconcile` and the 239-route authorization inventory
digest recorded in E-483. Local mode remains disabled; provider-specific status
API interoperability and production write-back remain unverified.
The route's optimistic replay was then corrected: a lost response can retry
with the original dispatched version and receive `already_acknowledged` without
another provider lookup. Stale versions still fail closed; no migration or
external-provider claim was added.
The PostgreSQL write-back persistence fixture then installed the shared RLS
foundation in the target disposable database before creating its write-back
table. PostgreSQL 16.14 passed the live write-back history test 2/2 under a
non-privileged role, including tenant/workspace scope, append-only history,
idempotency, version conflict, and immutable-update refusal. This remains
single-node synthetic persistence evidence; live provider status APIs,
distributed idempotency, accounting posting, HA/DR, and production write-back
remain open.
The grouped-matching follow-up adds four bounded adversarial contracts combining
fee/netting equal optima, fee-aware FX permutation replay, dense search-budget
refusal, and mixed partition/currency rejection. All four pass with explicit
matched/ambiguous/unmatched outcomes and no partial identity selection. This
strengthens algorithm correctness evidence only; fuzzing, mutation score, live
rates, PostgreSQL parity, performance, posting, write-back, and production
assurance remain open.
The write-back recovery boundary now also has a real pinned HTTPS transport:
registrations bind an optional exact status URL to the egress allowlist, and the
transport performs a bounded TLS GET with the original idempotency key and no
body. The local TLS sandbox passed three POST retries followed by one GET
recovery with zero additional POSTs. This is loopback/provider-neutral evidence;
vendor status semantics, accounting posting, distributed idempotency, HA/DR,
and production write-back remain open.
The pinned recovery transport was followed by a fresh full local regression: the
current tree collected 2,570 tests and reached 100% with no collection or
executed failure. Declared live-service/platform skips and existing warnings
remain; hosted CI, native backup tools, live providers, distributed scale,
HA/DR, and release approval are still external gates.
The advanced matching replay harness now also runs a fault matrix against fresh
SQLite databases for every non-terminal checkpoint (partitions 1, 2, and 3).
All three cases reproduce the uninterrupted effect digest, retain parity and
the mutation guard, leave no duplicate effects, and drain the queue. This
strengthens bounded replay evidence only; PostgreSQL/distributed queue failure,
mutation-tool score, throughput, and production SLOs remain open.
The checkpoint fault-matrix slice was followed by a fresh full regression and
static gate run: 2,570 tests reached 100%, Ruff/Mypy/Bandit/pip-audit passed,
and the package build included ADR 0383. Hosted CI/security/provenance and
external runtime evidence remain separate release gates.
The durable-job follow-up now repeats the public load harness across isolated
SQLite databases for a bounded soak tier. Each iteration preserves the declared
effect digest, has no duplicate partition effects, and drains queued/running
state; runtime and peak memory remain observations only. This closes a local
repetition contract, not PostgreSQL/distributed soak, queue HA, host-loss
recovery, capacity, SLO, or production readiness.
The post-soak full gate then collected 2,576 tests and exited 0 with no
collection or executed failure. Ruff/Mypy/Bandit/pip-audit passed and the
package build included ADR 0384 plus the soak module/test. This is a local
compatibility/package checkpoint only; hosted CI/security/provenance and
external runtime gates remain separate.
The live server-boundaries install is now pinned to the locked `--all-extras`
profile because its selected matrix spans observability, MFA/WebAuthn,
federation, connector, backup, and server dependencies. The workflow contract
test protects this against partial-profile drift; only a fresh hosted run can
prove native-tool and live runtime success.
The post-fix local gate collected 2,577 tests and exited 0; Ruff, Mypy, Bandit,
pip-audit, package build, and diff-check passed. This verifies local compatibility
of the workflow contract only; it does not replace the required hosted rerun.
The server-identity PostgreSQL fixture then aligned itself with the complete
close/PPA dependency contract: domain foundation, application master-data,
identity, approvals, emergency access, service accounts, scope authority,
intercompany artifacts, close links, and domain audit-ledger privileges are now
installed/granted in migration order. A newly created disposable PostgreSQL
16.14 database passes the live server-identity test; the configured service
passes metrics parity and Alembic upgrade tests. This closes fixture drift and
the misleading masked 503, not statutory consolidation, live providers/
write-back, distributed scale, independent HA/DR, or production readiness.
After that fixture repair, the full local regression again reached 100% with no
collection or executed failure; Ruff, Mypy, Bandit, OSV pip-audit, package build,
and diff-check all passed, and ADR 0386 is present in the source distribution.
This is a local quality checkpoint only; hosted CI/security/provenance, native
backup tooling, and external runtime/release gates remain open.

E-499 adds the experimental bounded canonical duplicate-detection strategy.
It groups each input side by an explicit or default canonical projection,
normalizes exact Decimal amounts, preserves every occurrence with stable
ordinals, and exposes duplicate/unique groups without silent de-duplication.
Repeated identities, binary floats, malformed amounts, and published input
ceilings fail closed; permutation-stable input/decision digests are covered by
27 focused strategy/contract tests, Ruff, Mypy, ADR 0389, and the architecture
manifest. This is exact duplicate evidence only; near-duplicate/probabilistic
matching, fraud detection, provider interoperability, PostgreSQL scale, and
production readiness remain open. GitHub publication remains deferred by owner
instruction.

E-501 exposes duplicate detection through Reconciliation-as-Code v1. The
contract now accepts `duplicate_detection`/`duplicate-detection`, dispatches the
bounded adapter in embedded golden tests, and reports an additive
`duplicate_group_count` instead of treating duplicates as financial matches.
The closed schema, Pydantic model, compatibility tests, and ADR 0390 align;
live-provider/PostgreSQL execution and all production gates remain open.

E-502 reran the complete local regression and release-quality gates after the
RAC adapter: pytest exited 0 with no collection or executed failure; Ruff,
Mypy (469 files), Bandit, OSV pip-audit, package build, and diff-check passed.
Existing declared skips/warnings and all hosted/external release gates remain
separate; GitHub publication remains deferred by owner instruction.

E-503 extends the disposable live Redis drill to the actual optional
`PolicyDecisionCache` boundary. Two independent cache instances use separate
Redis clients; a repeat is served from the second local cache, then global
invalidation in the first advances the shared generation and forces a fresh
evaluation in the second. The current report records all five invariants true,
including `policy_cache_cross_process_invalidation`, with digest
`b7f35cc2e9741cf06587f951a57048f3b5f454e51b558e1e52dc41284d48091e`. This is
single-node synthetic evidence only; Redis HA/failover, federation, complete
surface adoption, and production IAM remain open.

E-504 closed the required post-E-503 local gate: 2,587 tests reached 100% with
no collection or executed failure; Ruff, Mypy (469 files), Bandit, OSV
pip-audit, package build, and diff-check passed. Hosted CI/security/provenance,
native backup tooling, live providers/write-back, independent HA/DR, and
release approval remain external. GitHub publication remains deferred by owner
instruction.

E-505 fixed a real PostgreSQL native-backup command boundary: `pg_dump` now
receives the validated service through `--dbname service=<name>` rather than a
positional database argument. The focused backup suite reports 11 passes with
one declared disposable-service skip, and a PostgreSQL 16 Alpine client
produced a 5,168,214-byte custom dump using the corrected PGSERVICEFILE shape.
This is command-construction evidence only; hosted encrypted backup/restore,
key custody, cross-site recovery, and production RPO/RTO remain open.

E-506 closed the required full regression/static/package gate after E-505:
2,587 tests reached 100% with no collection or executed failure; Ruff, Mypy
(469 files), Bandit, OSV pip-audit, package build, and diff-check passed.
Hosted CI/security/provenance, native backup restore, live providers/
write-back, independent HA/DR, and release approval remain external. GitHub
publication remains deferred by owner instruction.

E-507 adds the bounded `consolidation-impairment-bridge-v1` artifact. It
calculates exact per-unit impairment loss and recoverable headroom from
source-bound carrying/recoverable inputs, preserves maker-checker and source
lineage, verifies canonical digests and derived fields, validates the closed
schema, and exposes a read-only CLI. The result is explicitly non-posting;
valuation methodology, cash-generating-unit policy, statutory recognition,
tax, journal posting, ERP write-back, and production readiness remain open.
GitHub publication remains deferred by owner instruction.

E-508 closes the post-impairment local gate: 2,592 tests reached 100% with no
collection or executed failure; the focused impairment/module/threat-model
suite passed 19 tests; Ruff, Mypy (470 files), Bandit, OSV pip-audit, package
build, and diff-check passed. Hosted CI/security/provenance, live providers/
write-back, independent HA/DR, and release approval remain external. GitHub
publication remains deferred by owner instruction.

E-500 reran the complete local regression and release-quality gates after the
duplicate-detection slice: pytest exited 0 with no collection or executed
failure; Ruff, Mypy (469 files), Bandit, OSV pip-audit, package build, and
diff-check passed. Existing declared skips/warnings and all hosted/external
release gates remain separate; GitHub publication remains deferred by owner
instruction.

E-509 adds Alembic `0066_pg_impairment`, a backend-neutral impairment
application service, and a forced-RLS append-only PostgreSQL repository. The
adapter stores canonical request/result JSONB, recomputes digests, makes
tenant/result retries idempotent, verifies reads, requires distinct identity
actors, emits creation audit evidence, and refuses posted/update/delete paths.
The disposable runtime contract is prepared but declares its PostgreSQL skip
when `RECONFORGE_TEST_POSTGRES_DSN` is absent; no live runtime pass is claimed.
This remains bounded non-posting evidence, not valuation methodology,
statutory accounting, journal posting, provider write-back, HA/DR, or
production readiness. GitHub publication remains deferred by owner instruction.

E-510 closes the required current-tree regression/static/package gate after
the new migration and adapter: 2,595 tests reached 100% with no collection or
executed failure; the impairment PostgreSQL runtime remains a declared skip
without `RECONFORGE_TEST_POSTGRES_DSN`; Ruff, Mypy (472 files), Bandit, OSV
pip-audit, package build, and diff-check passed. Hosted CI/security/provenance,
live PostgreSQL availability, live providers/write-back, independent HA/DR,
and release approval remain external.

E-511 exposes the impairment evidence boundary through the authenticated
PostgreSQL server profile. The POST and GET routes use strict canonical
Money/unit contracts, bind preparation to the authenticated actor, require an
independent approver, re-evaluate tenant policy, and fail closed without
PostgreSQL. Focused API/server-scope tests pass and the authorization inventory
now contains 241 contracts with digest
`4e456e05005444abe0e5a70c03f6d11177aa6629b58051e8ac773586b43158f2`. This is
non-posting evidence only; GitHub publication remains deferred by owner
instruction.

E-512 closes the required current-tree regression/static/package gate after
the API route: 2,598 tests reached 100% with no collection or executed
failure; the impairment PostgreSQL runtime remains a declared skip without
`RECONFORGE_TEST_POSTGRES_DSN`; Ruff, Mypy (474 files), Bandit, OSV pip-audit,
package build, authorization inventory, and diff-check passed. Hosted
CI/security/provenance, live PostgreSQL API runtime, live providers/write-back,
independent HA/DR, and release approval remain external.

E-513 binds the non-posting impairment artifact to a PostgreSQL consolidation
close run. Migration `0067_pg_close_impairment_links` adds forced-RLS,
append-only run/artifact/entity links; the repository replays and validates
period, currency, and worksheet entity, requires an independent linker, and
adds sorted impairment result digests to the close bundle. The server API
exposes strict `finance_core.manage`-protected impairment linking. Static,
bundle, and injected scope contracts pass; the live PostgreSQL link runtime is
still a declared skip without `RECONFORGE_TEST_POSTGRES_DSN`. GitHub
publication remains deferred by owner instruction.

E-514 closes the post-link full regression/static/package gate: the exact tree
collects 2,601 tests and reaches 100% with no collection or executed failure;
the close/impairment PostgreSQL runtime remains a declared skip without
`RECONFORGE_TEST_POSTGRES_DSN`; Ruff, Mypy (474 files), Bandit, OSV pip-audit,
package build, authorization inventory (242 routes, digest
`7fb88ae62d503dd7fe060398b9fba9131396e4a6f3f3966002e3c5faae1a262a`), and
diff-check pass. Hosted CI/security/provenance, live PostgreSQL availability,
providers/write-back, independent HA/DR, and release approval remain external.

E-515 binds the non-posting deferred-tax artifact to a PostgreSQL
consolidation close run. Migration `0068_pg_close_deferred_tax_links` adds
forced-RLS, append-only run/artifact/entity links; the repository replays and
validates period, currency, and worksheet entity, requires an independent
linker, and adds sorted deferred-tax result digests to the close bundle. The
server API exposes strict `finance_core.manage`-protected deferred-tax
linking. Static, bundle, and injected scope contracts pass; the live
PostgreSQL link runtime is still a declared skip without
`RECONFORGE_TEST_POSTGRES_DSN`. GitHub publication remains deferred by owner
instruction.

E-516 closes the post-deferred-tax full regression/static/package gate: the
exact tree collects 2,604 tests and reaches 100% with no collection or
executed failure; close/impairment/deferred-tax PostgreSQL runtimes remain
declared skips without `RECONFORGE_TEST_POSTGRES_DSN`; Ruff, Mypy (474 files),
Bandit, OSV pip-audit, package build, authorization inventory (243 routes,
digest `3455d30255baf6e130cc8ad55cbf2da25ff2364d48c77e0175e891d2671dee98`),
and diff-check pass. Hosted CI/security/provenance, live PostgreSQL
availability, providers/write-back, independent HA/DR, and release approval
remain external.

E-517 binds the non-posting PPA artifact to a PostgreSQL consolidation close
run. Migration `0069_pg_close_ppa_links` adds forced-RLS, append-only
run/artifact/entity links; the repository replays and validates period,
currency, and subsidiary entity, requires an independent linker, and adds
sorted PPA result digests to the close bundle. The server API exposes strict
`finance_core.manage`-protected PPA linking. Static, bundle, and injected
scope contracts pass; the live PostgreSQL link runtime is still a declared
skip without `RECONFORGE_TEST_POSTGRES_DSN`. GitHub publication remains
deferred by owner instruction.

E-523 closes the local regression/static/package gate after the CLI slice:
2,617 collected tests pass with no collection or executed failure; declared
PostgreSQL, Redis, object-storage, network, and platform skips remain visible.
Ruff, Mypy (476 source files), Bandit, OSV pip-audit, package build including
ADR 0401 and the CLI test, and diff-check pass. Hosted CI/security/provenance,
native backup tools, live providers/write-back, independent HA/DR, and release
approval remain external. GitHub publication remains deferred by owner
instruction.

E-518 closes the post-PPA full regression/static/package gate: the exact tree
collects 2,607 tests and reaches 100% with no collection or executed failure;
close/impairment/deferred-tax/PPA PostgreSQL runtimes remain declared skips
without `RECONFORGE_TEST_POSTGRES_DSN`; Ruff, Mypy (474 files), Bandit, OSV
pip-audit, package build, authorization inventory (244 routes, digest
`2e9808463d622cc82d134ed3660e0164d264d878b553c3e3afed49d5dcc19db2`), and
diff-check pass. Hosted CI/security/provenance, live PostgreSQL availability,
providers/write-back, independent HA/DR, and release approval remain external.
GitHub publication remains deferred by owner instruction.

E-519 adds the policy-neutral PostgreSQL ownership-change evidence boundary.
Migration `0070_pg_ownership_change` and the backend-neutral application
service persist canonical request/result JSONB under forced tenant RLS. Reads
replay the domain request, verify request/result digests, require distinct
preparer/approver identities, enforce `posted: false`, emit an audit event,
and reject update/delete paths. This remains evidence provenance only: no
statutory ownership accounting, goodwill/tax policy, journal posting,
provider write-back, restore, HA/DR, or production claim follows.

E-520 binds that immutable artifact to PostgreSQL consolidation close runs.
Migration `0071_pg_close_ownchg_links` adds forced-RLS append-only links with
run/artifact/entity uniqueness and data-loss-safe downgrade. The close
repository replay-verifies the artifact, binds period/currency/entity to the
worksheet, requires an independent linker, and includes sorted result digests
in the close bundle. The server exposes strict, `finance_core.manage`-
protected ownership-change evidence linking. The live PostgreSQL link runtime
is still a declared skip without `RECONFORGE_TEST_POSTGRES_DSN`.

E-521 closes the current local regression/static/package gate after the
ownership-change binding: 2,614 tests pass with no collection or executed
failure; Ruff, Mypy (476 files), Bandit, OSV pip-audit, package build,
authorization inventory (245 routes, digest
`edc399307cf840f553d238b984cb3e4f4ce7a15b5d65ca277d4c22aafe780b9b`), parser
and repository inventories, maturity/phase-2 audits, YAML parsing, and
diff-check pass. Capability-gated live PostgreSQL, hosted CI/security/
provenance, live providers/write-back, independent HA/DR, and release
approval remain external. GitHub publication remains deferred by owner
instruction.

E-522 adds the local `reconforge consolidation ownership-change` command.
It accepts one bounded JSON request with exact Decimal ownership percentages
and canonical Money, invokes the existing policy-neutral domain contract, and
emits a balanced digest-bound `posted: false` result without persistence,
provider I/O, or input mutation. Focused CLI/domain contracts pass; ADR 0401,
the CLI test, and the source-distribution manifest are aligned. This improves
local operator usability only and does not close statutory ownership-change
policy, journal posting, PostgreSQL live runtime, provider write-back, HA/DR,
hosted release gates, or the overall objective. GitHub publication remains
deferred by owner instruction.

E-523 closes the local regression/static/package gate after the CLI slice:
2,617 collected tests pass with no collection or executed failure; declared
PostgreSQL, Redis, object-storage, network, and platform skips remain visible.
Ruff, Mypy (476 source files), Bandit, OSV pip-audit, package build including
ADR 0401 and the CLI test, and diff-check pass. Hosted CI/security/provenance,
native backup tools, live providers/write-back, independent HA/DR, and release
approval remain external. GitHub publication remains deferred by owner
instruction.

E-524 adds the reference ERP HTTPS sandbox and expected-entity guard. The
connector can now fail closed when a validated page is outside the requested
entity scope, while the disposable TLS sandbox drives the real pinned GET
transport and network executor through retry, cursor/idempotency headers,
address pinning, canonical digest, and secret-redaction assertions. Focused
ERP/REST/network/SDK tests pass 39/39. This is provider-neutral loopback
evidence only; live ERP, vault, provider-version, posting, write-back, HA/DR,
and production claims remain open. GitHub publication remains deferred by
owner instruction.

E-525 closes the post-ERP-sandbox regression and package gate: the exact tree
collects 2,619 tests and reaches 100% with no collection or executed failure;
declared external-service capability skips remain visible. Ruff, Mypy (476
source files), Bandit, OSV pip-audit, 26/26 phase/execution/parity/maturity
contracts, package build with ADR 0402 plus ERP connector docs/test, and
diff-check pass. Hosted CI/security/provenance, live PostgreSQL/provider
runtimes, write-back, independent HA/DR, and release approval remain external.
GitHub publication remains deferred by owner instruction.

E-526 adds the payment-statement HTTPS sandbox and expected-account guard. The
connector can now fail closed when a validated statement page is outside the
requested bank-account scope, while the disposable TLS sandbox drives the real
pinned GET transport and network executor through retry, cursor/idempotency
headers, address pinning, canonical digest, and secret-redaction assertions.
The focused payment-statement/ERP/REST/network/SDK suite passes 46/46. This is
provider-neutral loopback evidence only; live bank, licensed dialect,
settlement, payment initiation, write-back, HA/DR, and production claims remain
open. GitHub publication remains deferred by owner instruction.

E-527 closes the post-payment-statement regression and package gate: the exact
tree collects 2,621 tests and reaches 100% with no collection or executed
failure; declared external-service capability skips remain visible. Ruff,
Mypy (476 source files), Bandit, OSV pip-audit, 26/26 phase/execution/parity/
maturity contracts, package build with ADR 0403 plus payment-statement
documentation/test, and diff-check pass. Hosted CI/security/provenance, live
PostgreSQL/provider runtimes, write-back, independent HA/DR, and release
approval remain external. GitHub publication remains deferred by owner
instruction.

E-528 adds fail-closed replay verification to every current matching strategy.
`MatchingStrategyResult.verify_against` recomputes the canonical manifest,
input, and output digests before indexed, grouped, carry-forward,
duplicate-detection, or reversal results cross a worker or persistence
boundary. Focused strategy, grouped-worker, sequential-worker, carry-forward,
reversal, and duplicate contracts pass; adversarial tests reject manifest,
input, and output tampering. ADR 0404 and the strategy contract test are in
the source distribution. This closes result-envelope integrity only; live
PostgreSQL capacity, distributed consensus, providers, independent
validation, HA/DR, and production readiness remain open. GitHub publication
remains deferred by owner instruction.

E-529 closes the current regression/static/package gate after the matching
replay verifier. The tree collects 2,623 tests and reaches 100% with no
collection or executed failure; declared PostgreSQL, Redis, object-storage,
public-network, and platform skips remain visible. Ruff, Mypy (476 source
files), Bandit, OSV pip-audit, 39/39 phase/execution/parity/maturity-related
contracts, package build with ADR 0404 and the matching strategy contract test,
and diff-check pass. Hosted CI/security/provenance, live PostgreSQL/provider
runtimes, independent HA/DR, and release approval remain external. GitHub
publication remains deferred by owner instruction.

E-530 adds the authenticated PostgreSQL scoped-control-plane export route at
`GET /api/v1/exports/scoped`. The route requires `reports.read`, binds the
request to the authenticated tenant/workspace hierarchy, re-evaluates the
central policy for the selected tenant/workspace/entity before repository
access, and returns the canonical artifact digest without SQLite fallback or
object-store publication. The focused route
contract passes; the boundary remains server-profile-only and does not prove
worker/UI adoption, distributed IAM, live providers, HA/DR, or production
readiness.

E-531 closes the post-export regression and packaging gate. The exact tree
collects 2,625 tests and the full pytest run reaches 100% with no collection
or executed failure in 334.3 seconds; declared PostgreSQL, Redis,
object-storage, public-network, and platform capability skips remain visible.
Ruff passes; Mypy reports no issues in 478 source files; Bandit exits 0 with
reviewed existing nosec/comment warnings; OSV pip-audit reports no known
vulnerabilities for the editable-local environment; the phase/execution/
parity/maturity inventory target passes 45/45; the package build succeeds and
the source distribution contains the new ADR, route, helper, and test; and
git diff --check passes. Hosted CI/security/provenance, live PostgreSQL and
provider runtimes, independent HA/DR, and release approval remain external.
GitHub publication remains deferred by owner instruction.

E-532 carries PostgreSQL reconciliation workspace attribution through the
worker lane. The repository exposes an optional workspace lookup for bounded
discovery; the worker accepts an explicit scope-aware service-account supplier,
requires an exact tenant/workspace/entity context, rejects the legacy
tenant-only supplier for a workspace run, and passes `workspace_id` into claim,
streaming input, heartbeat, checkpoint, result, cancellation, and failure
transactions. Focused worker, policy, and workspace-attribution contracts
pass, including `app.workspace_id` propagation. Reconciliation runs still
lack authoritative entity attribution; scheduler/outbox/export/UI adoption,
federation, distributed invalidation, live PostgreSQL, scale, HA/DR, and
production IAM remain open. ADR 0406 is packaged. GitHub publication remains
deferred by owner instruction.

E-533 closes the regression and package gate after the workspace worker slice:
the exact current tree reaches 100% in the full pytest run (2,627 collected;
no collection or executed failure; declared external-service/platform skips
remain) in 405.5 seconds; Ruff passes; Mypy reports no issues in 478 source
files; Bandit exits 0 with reviewed existing suppression/comment warnings;
OSV pip-audit reports no known vulnerabilities for the editable-local
environment; the focused phase/execution/parity/maturity plus worker suite
passes 62 tests with two declared live-PostgreSQL skips; the package build
succeeds and the source distribution contains ADR 0406; and `git diff --check`
passes. Hosted
CI/security/provenance, live PostgreSQL/provider runtimes, independent HA/DR,
and release approval remain external. GitHub publication remains deferred by
owner instruction.

E-534 carries PostgreSQL reconciliation attribution through organization and
legal-entity scope. Migration `0072_pg_recon_entity_scope` adds nullable
hierarchy columns, tenant-safe organization/entity foreign keys, a composite
lookup index, and RLS predicates. Discovery returns immutable
workspace/organization/entity attribution; claim SQL binds each supplied
dimension or requires NULL for legacy runs; and every worker transaction
restores the exact hierarchy through input streaming, heartbeat, checkpoint,
completion, cancellation, and failure handling. The focused reconciliation,
persisted-JSON, and Alembic contracts pass 66 tests with two declared
live-PostgreSQL skips, including exact GUC and claim-parameter assertions.
This is one worker lane only; universal IAM surface adoption, federation,
distributed invalidation, live provider interoperability, scale, HA/DR, and
production IAM assurance remain open. ADR 0407 is packaged. GitHub
publication remains deferred by owner instruction.

E-535 closes the entity-scoped worker regression and package gate. The exact
current tree collects 2,629 tests and the full pytest run passes 100% in
324.9 seconds with no collection or executed failure; declared external
service/platform skips and existing warnings remain visible. Ruff passes;
Mypy reports no issues in 479 source files; Bandit exits 0 with reviewed
existing suppression/comment warnings; OSV pip-audit reports no known
vulnerabilities; the migration registry matches all 72 linear Alembic
revisions; the package build succeeds and `SOURCES.txt` contains ADR 0407,
migration 0072, and the schema helper; and `git diff --check` passes. Hosted
CI/security/provenance, live PostgreSQL/provider runtimes, independent HA/DR,
and release approval remain external. GitHub publication remains deferred by
owner instruction.

E-536 carries exact scope through the PostgreSQL scheduler lane. An optional
deterministic `(tenant, workspace, entity)` supplier and three-argument policy
context authorize each lane before connection access; entity lanes require a
workspace; and workspace/entity filters flow through the application service
into the PostgreSQL row-lock query. The same scope is restored before
dispatch, durable-job, and notification writes. Focused scheduler/application
contracts pass 9 tests with one declared live-PostgreSQL skip; Ruff and Mypy
pass. ADR 0408 is packaged. The transactional outbox remains tenant-only in
this slice, and universal IAM adoption, federation, distributed invalidation,
live providers, scale, HA/DR, and production IAM assurance remain open.

E-537 closes the scoped scheduler worker regression and package gate. The
exact current tree collects 2,631 tests and the full pytest run passes 100% in
328.6 seconds with no collection or executed failure; declared external
service/platform skips and existing warnings remain visible. Ruff passes;
Mypy reports no issues in 479 source files; Bandit exits 0 with reviewed
existing suppression/comment warnings; OSV pip-audit reports no known
vulnerabilities; the package build succeeds and `SOURCES.txt` contains ADR
0408; and `git diff --check` passes. Hosted CI/security/provenance, live
PostgreSQL/provider runtimes, independent HA/DR, and release approval remain
external. GitHub publication remains deferred by owner instruction.

E-538 adds hierarchy-scoped PostgreSQL transactional-outbox delivery. Migration
0073 adds nullable workspace/organization/legal-entity attribution, transaction
defaults, a pending index, and explicit hierarchy RLS. Atomic claims bind the
requested scope and return attribution; the worker authorizes deterministic
four-part lanes before connection access, restores the same scope for every
transition, and fails closed on mismatch. Focused outbox/worker/migration/
policy contracts pass and ADR 0409 is packaged. Live providers, distributed
queue fairness, HA/DR, throughput, and production readiness remain open.

E-539 closes the regression/package gate for this slice: 2,634 collected tests
pass 100% in 355.5 seconds with five declared live-PostgreSQL skips; Ruff,
Mypy (480 source files), Bandit, OSV pip-audit, build/source-distribution,
migration registry, and diff-check pass. Hosted CI/security/provenance, live
providers, distributed queue fairness, HA/DR, and production readiness remain
external. GitHub publication remains deferred by owner instruction until the
complete objective is closed.

E-540 adds the organization-aware policy primitive. Central ABAC now evaluates
organization scope deny-by-default, the allowed-only cache keys and invalidates
organization scope, and outbox organization lanes require a four-argument
hierarchy policy supplier. Legacy three-argument suppliers fail closed before
database access. Focused policy/cache/outbox contracts pass. The post-change
full tree collects 2,637 tests and passes 100% in 335.9 seconds; Ruff, Mypy,
Bandit, OSV pip-audit, build, and diff-check pass. Federation, route-wide
adoption, distributed invalidation, live IAM providers, and production
readiness remain open. GitHub publication remains deferred.

E-541 closes the hierarchy attribution gap in PostgreSQL outbox consumer
receipts. Migration 0074 adds nullable workspace/organization/legal-entity
columns, transaction defaults, scope indexing, and explicit RLS. The consumer
restores the requested hierarchy, verifies source-event attribution before
effect invocation, and records immutable receipts with the same scope; legal
entities require organizations. Downgrade refuses to discard non-empty
receipts. Focused contracts pass; external broker exactly-once, throughput,
HA/DR, and production readiness remain open.

E-542 closes the regression/package gate for E-541. The current tree collects
2,638 tests and passes 100% in 333.3 seconds with no collection or executed
failure; declared live-service capability skips remain visible. Ruff, Mypy
(481 source files), Bandit, OSV pip-audit, migration-registry contracts,
package build/source membership, and diff-check pass. Hosted
CI/security/provenance, live provider runtimes, external broker semantics,
HA/DR, and release approval remain external. GitHub publication remains
deferred by owner instruction.

E-543 extends the scoped consumer result envelope so both first application
and duplicate replay return the persisted workspace/organization/legal-entity
attribution. Legacy tenant-only calls remain compatible. E-544 reruns the
full 2,638-test regression and all local static/package gates successfully.
E-545 records checksum-verified local Gitleaks history and clean-archive tree
scans with zero leaks; the supplied hosted security failure still requires a
fresh hosted rerun after publication.

E-546 adds organization binding to central server policy re-evaluation. For
workspace-scoped server requests the helper derives the organization from the
validated header when needed, passes authorized organization IDs into ABAC, and
rejects explicit/header mismatch before evaluation. E-547 records a green
2,638-test regression and local static/package gate; universal surface
adoption, live IAM/provider runtime, HA/DR, and hosted approval remain open.
E-548 also passes the local closed supply-chain policy validator with zero
active exceptions and zero npm integrity gaps. Hosted security jobs and
required-context status still need a fresh external run.

E-549 adds organization scope to durable jobs across the domain, SQLite, and
PostgreSQL modes. Migration 33 and PostgreSQL revision 0075 preserve the
hierarchy in replay identity, queue bounds, claims, evidence reads/writes,
backup import/export, and RLS. Focused checks and package build pass; live
PostgreSQL remains capability-gated. E-550 closes the 2,642-test full
regression and static/security/package gates; live PostgreSQL, hosted
CI/security/provenance, HA/DR, and release approval remain external. GitHub
publication remains deferred by owner instruction.

E-551 proves additive backup compatibility for this slice: a schema-version-32
SQLite backup containing a durable job without organization attribution restores
and upgrades to the current schema with an empty legacy scope. The focused
regression and complete backup/export suite pass. PostgreSQL native restore,
cross-site recovery, RPO/RTO, and GitHub publication remain deferred.

E-552 reruns the complete local regression after that coverage: 2,643 tests pass
in 335.4 seconds with no collection or executed failure, while declared service
and platform skips remain visible. Hosted CI/security/provenance, live database
restore, HA/DR, release approval, and GitHub publication remain deferred.

E-553 verifies the historical Python 3.11 dependency failures under the locked
all-extras profile: 48 tests pass, one live-PostgreSQL test is declared skipped,
and `cbor2`, `cryptography`, and `opentelemetry.sdk` import successfully. This
is local dependency evidence; hosted matrix/security reruns and publication
remain deferred.

E-554 closes the RAC declaration gap for existing sequential adapters. The
closed contract now supports carry-forward, sequence-window, and reversal
pairing, with digest-verified local simulations and visible residual/pair
counts. The focused 45-test gate, schema validation, and package membership
pass. PostgreSQL worker runtime, cross-engine/scale evidence, posting,
provider interoperability, and GitHub publication remain deferred.

E-555 reruns the complete local regression after this slice: 2,647 tests pass
in 380.3 seconds with no collection or executed failure and declared external
service/platform skips visible. Hosted CI/security/provenance, live providers,
HA/DR, release approval, and GitHub publication remain deferred.

E-556 closes the reconciliation read-policy gap locally: five read surfaces and
the mutation guards re-evaluate the full tenant/workspace/organization/entity
hierarchy immediately before PostgreSQL access. The synthetic route/scope gate
passes 14 tests and ADR 0414 is packaged. Complete enterprise IAM adoption,
live PostgreSQL, federation, HA/DR, and GitHub publication remain deferred.

E-557 reruns the complete local regression after the IAM route slice: 2,647 tests
pass in 340.7 seconds with no collection or executed failure and declared
external service/platform skips visible. Hosted CI/security/provenance, live
PostgreSQL, federation, HA/DR, release approval, and GitHub publication remain
deferred.

E-558 closes the evidence-route hierarchy gap locally: all PostgreSQL evidence
reads, manage actions, and checksum verification now re-evaluate tenant,
workspace, organization, and legal-entity scope before adapter access. The
focused evidence/server-scope gate passes 10 tests and ADR 0415 is packaged.
Complete API/job/export/UI IAM adoption, federation, live providers, HA/DR,
release approval, and GitHub publication remain deferred.

E-559 reruns the complete local regression after the evidence hierarchy slice:
2,647 tests pass in 336.1 seconds with no collection or executed failure and
declared external service/platform skips visible. Hosted CI/security/provenance,
live providers, federation, HA/DR, release approval, and GitHub publication
remain deferred.

E-560 extends the hierarchy policy closure to the intercompany evidence API:
prepare and read now pass tenant/workspace/organization/legal-entity into ABAC
before PostgreSQL access. Five focused route contracts pass and ADR 0416 is
packaged. The required full regression for this new slice is still pending;
GitHub publication remains deferred.

The first E-561 attempt exposed a documentation-contract failure rather than a
product failure: `pending` is not an allowed backlog status. Changing it to
the declared `in_progress` value restored the execution contract; the rerun
passed all 2,647 tests in 337.1 seconds, so E-561 is now complete. The initial
failure remains recorded in EVIDENCE.md.

E-562 generalizes the central policy boundary to tenant-scoped calls: optional
organization/legal-entity headers are normalized and fail closed on mismatch or
missing parent even when no workspace is selected. Twenty-three focused policy
and dependent-route tests pass and ADR 0417 is packaged. E-563 then passed all
2,647 tests in 404.2 seconds with declared external-service skips visible;
tenant-only persistence, hosted release evidence, and GitHub publication remain
deferred.

E-564 begins closing the storage-side gap for consolidation evidence: PPA
artifacts now have an additive migration, hierarchy-aware RLS and uniqueness,
optional repository/API scope, and explicit legacy-row compatibility. Focused
contracts and package membership pass; E-565 then passed all 2,650 tests in
380.5 seconds with declared external-service skips visible. Impairment and
deferred-tax persistence still require equivalent migrations, and GitHub
publication remains deferred.

E-566 extends the storage-side hierarchy closure from PPA to impairment and
deferred-tax artifacts with migration 0077, scoped uniqueness/RLS, repository
filters, and server GUC propagation. E-567 then passed the 2,651-test local
regression in 337.0 seconds, alongside focused contracts, package build, Ruff,
Mypy, and diff-check. Live hierarchy PostgreSQL, statutory posting/judgment,
providers, HA/DR, and GitHub publication remain deferred.

E-572 reconciles `POSTGRES_PARITY_INVENTORY.yaml` with migration head 0078 and
records that the existing live close claim must be rerun before hierarchy
runtime evidence can be promoted. This is a documentation boundary update,
not live PostgreSQL proof.

E-573 triages the supplied CI failures: locked Python 3.11 security imports,
the supply-chain policy, and clean-checkout Gitleaks scans are green locally;
the workflow includes native PostgreSQL client bootstrap and head-0078
migrations. Docker/native PostgreSQL are unavailable on this Windows host, so
live server-boundary rerun and hosted promotion remain blocked externally.

E-568 closes a scope-reset defect in the PostgreSQL close path: authenticated
organization/workspace/legal-entity context is now preserved by the close and
certification approval repositories whenever they set transaction-local GUCs,
and the server adapter passes the complete execution scope. Focused contracts
pass; E-569 then passed the 2,653-test full regression in 336.9 seconds with
the declared external-service skips visible. Package build is rerun after this
update. This does not yet provide close-table hierarchy persistence or live
multi-entity RLS evidence.

E-570 adds the missing PostgreSQL close-table persistence boundary. Migration
0078 adds organization/legal-entity attribution, tenant-safe references,
hierarchy indexes, workspace-aware period/run policies, all-table hierarchy
RLS, and NULL-aware scoped identities with a guarded rollback. Focused static
and migration contracts pass. E-571 then passed all 2,655 collected tests in
338.4 seconds, package build, Ruff, Mypy, and diff-check with declared
external-service skips visible. Live hierarchy PostgreSQL, statutory posting,
providers, HA/DR, and GitHub publication remain deferred.

E-574 closes a migration-safety gap found during the continuation audit:
PostgreSQL downgrades for reconciliation, outbox, durable-job, PPA,
impairment, and deferred-tax hierarchy slices now check for non-NULL
attribution in a database-side guard before removing scope columns. Static
contracts pass; the current 2,655-test full regression exits 0 in 373.8
seconds, package build/Ruff/Mypy/diff-check pass, and declared external-service
skips remain visible. Live downgrade execution, providers, statutory posting,
HA/DR, and GitHub publication remain deferred.

E-575 closes the server-profile scale resource boundary: API construction now uses a bounded
`PostgresPooledConnectionFactory` with explicit size/lease timeout and shutdown
cleanup while retaining the existing factory subtype checks. Focused contracts
pass with one declared live-PostgreSQL skip; the current 2,655-test regression
exits 0 in 358.4 seconds, package build/Ruff/Mypy/diff-check pass. This remains
resource-reuse evidence only, not capacity, soak, HA/DR, or production sizing
proof.

E-576 closes the reported PostgreSQL metrics gate at its root: the parity
fixture now installs every schema family referenced by the metrics queries
instead of allowing an absent table to surface as a generic operation failure.
Focused/static contracts pass with one declared local live-PostgreSQL skip; the
current 2,655-test regression exits 0 in 358.7 seconds, package build and
diff-check pass. Live hosted PostgreSQL execution remains the required runtime
check.

E-577 closes the Bandit B608 findings exposed during the security rerun. The
eight hierarchy query compositions now carry precise line-level rationale:
`_scope_where()` is a fixed internal allowlist and all values are bound
parameters. Full Bandit reports no failed findings; Ruff/Mypy and focused
security tests pass. This is scanner coverage only, not penetration testing or
production assurance.

E-578 closes the release-gate drift: the live Alembic migration-status
assertion now names the supported `0078_pg_close_scope` head, matching the
registry and migration chain. Static contracts, the 2,655-test full local
regression, Ruff, Mypy, package build, and diff-check pass. The actual
PostgreSQL migration run remains hosted-only on this Windows environment, so
GitHub publication and final objective closure remain deferred.

E-579 closes the adjacent server lifecycle leak: Redis server profiles now
register the existing lazy client factory's `close()` callback on application
shutdown, matching PostgreSQL pool cleanup. The contract is local and does not
open a network connection; Redis availability, replication, HA/DR, and hosted
runtime evidence remain external. GitHub publication remains deferred.

E-580 closes a bounded scheduler resource-churn defect: each configured
reconciliation worker slot now reuses one lazily-created worker across polling
cycles. The focused contract, Ruff, Mypy, package build, diff-check, and the
2,655-test full local regression pass (385.1 seconds, with declared
external-service/platform skips). This does not prove throughput, fairness,
capacity, soak, distributed scheduling, HA/DR, or production sizing; hosted
providers and GitHub publication remain deferred.

E-581 adds explicit lifecycle closure for the cached reconciliation workers.
`PostgresReconciliationScheduler.close()` is idempotent, invokes each optional
worker hook once, and rejects later cycles; the PostgreSQL worker delegates once
to its optional connection-factory close hook. Focused lifecycle tests and
static checks pass; the caller must stop polling before close. Provider
availability, throughput, HA/DR, and GitHub publication remain deferred.

E-582 serializes scheduler cycles with lifecycle close through a cycle lock
separate from the worker-cache lock. A concurrent shutdown therefore waits for
the active bounded cycle without blocking worker-thread cache lookup. This is
lifecycle serialization evidence, not throughput, fairness, capacity, soak,
distributed scheduling, HA/DR, or production operations evidence.

E-583 adds optional, disabled-by-default scheduler telemetry. Each Worker cycle
emits a safe low-cardinality span and job transition through the existing
ObservabilityRuntime; failure transitions are recorded before the original
error is raised, and no tenant/record/amount identifiers are exported. The
current 2,660-test regression and static checks pass. Collector delivery,
alerting, capacity, HA/DR, and GitHub publication remain deferred.

E-584 completes the durable-job terminal worker telemetry boundary: completion,
final-partition completion, retry, failure, pause, and cancellation now emit
optional safe low-cardinality transitions; checkpoints and partition effects
remain intentionally uninstrumented for scale. The current 2,660-test full
regression, Mypy, package build, and diff checks pass. Collector delivery,
alerting, capacity, HA/DR, and GitHub publication remain deferred.

E-585 closes the local migration-status contract around the reported CI
failure: current-head and unknown-revision behavior are explicit, connections
close deterministically, and blank locators fail before connection access.
Five focused tests, phase execution contracts, and the 2,663-test full
regression pass (336.4 seconds), with Mypy, package build, and diff-check
passing. A fresh hosted Alembic upgrade is still required before promoting
E-461.

E-586 completes a bounded ERPNext connector slice: the Connector SDK now
supports backward-compatible provider auth schemes and fixed cursor query
parameters, and a concrete ERPNext GL Entry read-only adapter validates exact
debit/credit text, one company per page, bounded offset cursors, canonical
digests, and hardened operator endpoints. The focused suite, parser inventory,
phase contracts, 2,673-test full regression (337.0 seconds), Mypy on 486
source files, Ruff, Bandit, pip-audit, package build, and diff-check pass. No
live ERPNext, posting, or write-back claim is made.

E-587 completes a bounded ERPNext write-back slice: a deterministic
`docstatus=0` Journal Entry payload builder requires exact Decimal amounts,
one positive side per line, and an exactly balanced document. The governed
write-back registration is exact-path, token-authenticated, and disabled by
default; synthetic transport tests prove maker-checker/feature gating,
payload/acknowledgement binding, endpoint hardening, legacy Bearer digest
compatibility, and secret isolation. The current 2,681-test full regression
passes in 406.9 seconds; Mypy (487 files), Ruff, Bandit, pip-audit, package
build, source membership, and diff-check pass. Live ERPNext posting, account
mapping, compensation, and production write-back remain external.

E-588 closes the provider-side scope refinement for ERPNext GL Entry reads.
The network executor now validates and digest-binds bounded sorted query
parameters without rewriting operator-declared query text. ERPNext sends an
exact company `filters` predicate when scope is requested and accepts a
bounded `limit_page_length`; the local response/company guard remains in
place. Focused network/ERPNext tests cover URL construction, fixed-query
preservation, duplicate/control rejection, page limits, and digest binding.
The current 2,689-test full regression passes in 349.2 seconds; Mypy (487
files), Ruff, Bandit, pip-audit, package build, source membership, and
diff-check pass. Live ERPNext filtering and production isolation remain
external.

E-589 adds a bounded CAMT.053 HTTPS bank-statement source on top of the
existing `defusedxml` parser and governed network executor. The adapter uses an
exact HTTPS path, runtime secret-reference authentication, an 8 MiB response
ceiling, optional expected-account isolation, and request/raw-response/
normalized-source digests. Focused connector, parser-inventory, registry, and
network tests pass. The full 2,697-test local regression exits 0 in 349.8
seconds; Mypy reports no issues in 488 source files; Ruff, Bandit, pip-audit,
package build, source-distribution membership, and diff-check pass. Provider
dialect, source authenticity, certificate and credential lifecycle, settlement,
posting, write-back, and production availability remain external; GitHub
publication remains deferred.

E-590 adds a bounded ERPNext Payment Entry read-only adapter. It binds the
exact resource path, token auth, `limit_start` pagination, provider-side JSON
company filter, local company guard, exact paid/received Decimal text, and
canonical response digest. Focused schema/auth/endpoint/secret tests and the
FI-039 parser inventory pass. The full 2,710-test local regression exits 0 in
357.1 seconds; Mypy reports no issues in 489 source files; Ruff, Bandit,
pip-audit, package build, source-distribution membership, and diff-check pass.
Live ERPNext tenant, provider version, settlement, posting, write-back, and
production evidence remain external.

E-591 closes the shared provider read-manifest conformance boundary. The
reference Connector SDK portfolio now includes the bounded CAMT.053 HTTPS
source and ERPNext GL Entry/Payment Entry registrations. A synthetic replay
test runs each registration twice through the governed executor and requires
read-only capability, exact HTTPS egress, secret-reference authentication,
bounded retry/cursor declarations, identical request/response identity, and
bounded 503/429 transient recovery.
The focused SDK/provider connector suite passes; the 2,713-test local
regression exits 0 in 355.7 seconds, Mypy covers 489 source files without
issues, and Ruff/Bandit/pip-audit/build/archive-membership/diff-check pass.
This aligns the provider-specific adapters with one common safety contract; it
does not establish live bank/ERP interoperability, source authenticity,
settlement, posting, write-back, or production availability. GitHub publication
remains deferred by owner policy.

E-592 closes the current local Gitleaks finding without weakening secret
scanning. The checksum-verified Gitleaks 8.30.1 scan reports no leaks across
602 commits after recording only the exact historical and checked-tree
fingerprints for the synthetic observability redaction fixture. A clean
`git archive` checkout scan covers 25.12 MB and also exits clean. The local
workspace scan is not release evidence because generated environments reach
the 120-second timeout after reading about 6.30 GB. Hosted security
attestation and branch enforcement remain external; GitHub publication remains
deferred by owner policy.

E-593 adds a local HTTPS runtime sandbox for the bounded CAMT.053 and ERPNext
GL Entry/Payment Entry sources. Each adapter uses the actual pinned TLS
transport with a temporary certificate, survives a synthetic 503 retry, parses
the closed response, enforces account/company scope, retains cursor/query
semantics, and proves bearer/token isolation. This strengthens the adapter
transport boundary only. The full repository regression collected 2,716 tests
and exited 0 in 366.5 seconds. Live provider tenants, dialect/version
compatibility, source authenticity, settlement, posting, write-back, and
production availability remain external. GitHub publication remains deferred
by owner policy.

E-594 adds bounded deterministic Hypothesis coverage for grouped matching.
Generated Decimal amounts/fees, currencies, partitions, and dates exercise
permutation-stable decisions/digests, closed selection invariants, budget
refusal, portfolio non-overlap, and replay digest stability. Twenty focused
grouped tests pass with the existing adversarial/replay/mutation contracts.
The full repository regression collected 2,719 tests and exited 0 in 368.6
seconds with declared capability skips and existing warnings only. This
improves synthetic property/fuzz evidence only; mutation-tool score,
PostgreSQL parity, distributed fault coverage, live-rate validation, and
production sizing remain open. GitHub publication remains deferred by owner
policy.

E-595 adds a dependency-free targeted source-mutation campaign for grouped
matching. A disposable child package runs a closed contract against three
explicit mutants covering partial settlement, date-window boundaries, and
absolute-difference handling; the baseline passes and all three mutants are
killed (3/3, zero survivors). The focused grouped suite reaches 27 tests.
The full repository regression collected 2,720 tests and exited 0 in 365.1
seconds with declared capability skips and existing warnings only. This is a
targeted mutation result, not a domain-wide score; PostgreSQL parity,
distributed fault coverage, live-rate validation, and production sizing remain
open. GitHub publication remains deferred by owner policy.

E-596 adds a tenant-scoped persistent durable-job scheduler cursor to SQLite
migration 34 and PostgreSQL migration `0079_pg_job_cursor`. The cursor binds an
ordered lane digest and count to a scheduler key, advances atomically before a
lease-fenced claim, survives scheduler restart, rejects lane drift, and is
included in local backup/export. Focused durable-job, migration, backup,
Alembic/static, and package contracts pass. This is bounded shared-cursor
coordination evidence only; live PostgreSQL multi-process/cross-host fairness,
throughput, queue HA/failover, soak, capacity, and production readiness remain
open. The full repository regression collected 2,722 tests and exited 0 in
373.9 seconds with declared capability skips and existing warnings only.
GitHub publication remains deferred by owner policy.

E-611 adds the lazy-loaded `/professional-invoice-payment` modern Studio route
as a strict, synthetic-only projection of the deterministic professional
invoice/payment control. The read-only English/Arabic view validates the
contract marker, source boundary, exact amount/day strings, bounded statuses,
unique decision IDs, summary consistency, and replay digest shapes before
showing client/payment references, variance reasons, filters, and evidence
digests. The module registry and threat-model index now declare the modern
Studio interface and browser test evidence. Live billing/provider/API behavior,
receivables allocation, revenue recognition, posting, write-back, HA/DR, and
production professional-services evidence remain open. Web TypeScript checks and
UI gates are verified:
TypeScript build, `npm run typecheck`, `npm run test:run` (67/67), and
`npm run build` pass; Playwright accessibility and UX evidence now includes
15/15 executed Chromium paths plus 5 skipped (focused synthetic local flows),
including same-origin sign-in/step-up, Arabic RTL, command-dialog focus flow,
and admin/mapper disclosure boundaries.  The full local Python regression exits 0
in 483.8 seconds, with Ruff, Mypy (496 files), Bandit, pip-audit, supply-chain
validation, package build, and diff-check passing. GitHub publication remains
deferred by owner policy.

E-612 adds local persistence for the professional invoice/payment control:
`reconforge professional invoice-payment run --persist` and the local
SQLite-backed repository now store replayable decision artifacts, policy
fingerprints, and workspace-scoped metadata. The same API surface
`POST /api/v1/professional/invoice-payments` and list/read routes now support
bounded dual-mode persistence: local mode persists to SQLite, while server mode
routes to the authenticated PostgreSQL repository when the profile configures it.
Server mode returns an explicit capability-bound 503 error when PostgreSQL
selection is unavailable. Focused tests cover idempotent replay, tamper
refusal, workspace isolation, manifest inclusion, and restore round-trips. This
closes the dual-mode persistence boundary for this slice while keeping live
billing/payment connectivity, posting, ERP write-back, HA/DR, and production
operations out of scope.

E-597 extends the scheduler cursor evidence with two independent SQLite
connections reserving the same lane sequence from separate executor threads.
Twelve reservations commit with six selections per lane, final index zero, and
cursor version twelve; connections are created and closed inside their owning
threads. This is local transaction-serialization evidence only. PostgreSQL
lock behavior, cross-host fairness, throughput, queue HA/failover, soak,
capacity, and production SLO evidence remain open. The full repository
regression collected 2,723 tests and exited 0 in 360.3 seconds with declared
capability skips and existing warnings only. GitHub publication remains
deferred by owner policy.

E-598 hardens the retail POS settlement report reader. The serialized run now
rebuilds and checks its nested decision digest, canonical decision ordering,
and status-count projection after the outer artifact digest. The focused
retail suite passes 10/10, including rejection of a changed monetary decision
even when the outer envelope is recomputed. This is local serialized
artifact-integrity evidence only; source authenticity, live provider
settlement, persistence, posting, write-back, and production retail evidence
remain open. GitHub publication remains deferred by owner policy.

E-599 extends the same nested decision-artifact integrity contract to the
bank-statement, manufacturing-cost, and professional invoice/payment modules.
The shared verifier checks schema/algorithm identity, canonical decision order,
sorted unique input fingerprints, derived status counts, and the exact nested
digest. Focused module suites pass 21 tests, including an outer-rehash tamper
regression for each module. This is serialized local artifact-integrity
evidence only; source authenticity, live provider operations, persistence,
posting, write-back, and production readiness remain open. GitHub publication
remains deferred by owner policy.

E-600 adds a bounded process-local circuit breaker to the provider-neutral
network connector executor. Per connector/endpoint, exhausted retryable
transport or 5xx failures now open a fail-fast window; a later successful read
clears the state. The focused network suite passes 24 tests with failure
injection and zero transport calls while open. This is local synthetic
resilience evidence only; distributed quota coordination, live provider
availability, vault operation, and production SLOs remain unverified. GitHub
publication remains deferred by owner policy.

E-601 extends the circuit evidence with scope-isolation and configuration-bound
regressions. A circuit opened for one declared endpoint or credential reference
does not block another lane, and invalid threshold/window values are refused.
The focused network suite passes 26 tests; implementation Ruff and Mypy pass.
This remains process-local synthetic evidence only, not distributed quota or
live-provider behavior. GitHub publication remains deferred by owner policy.

E-602 adds a repository contract for the hosted PostgreSQL native-tool
bootstrap. It requires `server-boundaries` to install `postgresql-client`
before locked dependencies and to resolve executable `pg_dump`, `pg_restore`,
`createdb`, `dropdb`, and `psql` from `pg_config --bindir`. The focused phase-4
and connector suites pass 37 tests with Ruff and diff-check. A fresh hosted
encrypted backup/restore run is still required. GitHub publication remains
deferred by owner policy.

E-603 adds SQLite migration 35 and `SQLiteRetailSettlementRepository` for
workspace-scoped immutable retail settlement evidence. Repeated puts are
idempotent, reads verify outer and nested replay digests plus persisted status
and algorithm fields, tampering is refused, and local backup/restore includes
the table. Retail persistence, backup/restore, inventory, and related focused
tests pass; static/package gates are being rerun before the local commit. This
is local SQLite evidence only. The full local pytest regression exits 0 in
408.4 seconds with declared capability skips and existing warnings. Retail
API/Studio, live processor authenticity, posting, write-back, PostgreSQL
parity, HA/DR, and production operations remain open. GitHub publication
remains deferred by owner policy.

E-604 exposes that verified evidence through an opt-in CLI persistence flag and
authenticated local API POST/list/read routes. The write route requires
`finance_core.manage`, reads use the finance read/manage/validate policy, and
server identity mode refuses explicitly rather than falling back to SQLite.
The closed startup authorization inventory is now 249 routes with digest
`39f5354d214e6454d008ca778ccf126609a7c64aa9fae4478a424823e4684736`. Focused
API/CLI/repository tests, full pytest (exit 0 in 370.0 seconds), and
static/package gates pass. PostgreSQL parity,
Retail Studio, live providers, posting, write-back, HA/DR, and production
operations remain open. GitHub publication remains deferred by owner policy.

E-605 adds the PostgreSQL retail settlement adapter and migration `0080`. The
server routes now bind workspace to the authenticated execution scope and use
forced tenant/workspace RLS, immutable triggers, bounded report replay, and
transaction-scoped idempotent inserts. Local contract tests and focused API,
migration, module, and threat-model tests pass. The live non-privileged
PostgreSQL drill is explicitly skipped because the current environment has no
`RECONFORGE_TEST_POSTGRES_DSN`; hosted native-tool, HA/DR, live provider,
posting, write-back, Studio, and production evidence remain open. The full
local regression exits 0 in 370.6 seconds and static/security/dependency/
package gates pass. GitHub publication remains deferred by owner policy.

E-606 adds the read-only modern Studio route `/retail-settlement`. It consumes
one synthetic-only projection of the deterministic report, validates exact
decimal strings/digest shapes/status and summary invariants, and exposes
English/Arabic filtering, variance reasons, and replay evidence without a
second calculation or write path. Web typecheck, 58 component tests, build,
and 6/6 accessibility E2E tests pass. This closes the local retail Studio
review surface only; live browser authentication, provider authenticity,
settlement finality, posting, write-back, hosted deployment, HA/DR, and
production retail evidence remain open. GitHub publication remains deferred
by owner policy.

E-607 adds an explicit CI import probe immediately after the locked all-extra
installation for `cbor2`, `cryptography`, and `opentelemetry.sdk`. The local
workflow contract passes 7/7 and an isolated Python 3.11 all-extra sync
imports all three modules. This gives a precise pre-collection failure signal;
it is not hosted CI evidence and does not close live PostgreSQL/Redis/native
backup, HA/DR, provider, or production gates. GitHub publication remains
deferred by owner policy.

E-608 adds the machine-readable benchmark evidence index and verifier. Five
selected matching/durable-job JSON artifacts are bound by repository-relative
path, SHA-256, profile ID, declared digest fields, workload family, status,
and non-production wording. The verifier passes local artifacts and rejects
tampered hashes/path escape/global-claim fixtures; CI runs it before Pytest.
The first full regression exposed the new JSON parser calls as an undeclared
FI-040 inventory surface; that allowlist was added and the final full pytest
exits 0 in 379.1 seconds with declared capability skips and existing warnings.
This improves reproducibility of published observations only and does not
close distributed capacity, hosted runtime, provider, HA/DR, or production
gates. GitHub publication remains deferred by owner policy.

E-609 adds the lazy-loaded `/bank-statement` modern Studio route as a strict,
synthetic-only projection of the deterministic local bank statement control.
The read-only English/Arabic view validates the contract marker, source
boundary, exact decimal strings, bounded statuses, unique decision IDs,
summary consistency, and replay digest shapes before showing filters, variance
reasons, algorithm identity, and evidence digests. The module registry now
declares the modern Studio interface and browser test evidence. Web typecheck,
production build, the full component suite (61/61), and the accessibility E2E
suite (7/7) pass. This is local synthetic UI evidence only; live bank/API/
provider behavior, payment initiation, posting, write-back, HA/DR, and
production banking evidence remain open.
GitHub publication remains deferred by owner policy.

E-610 adds the lazy-loaded `/manufacturing-cost` modern Studio route as a
strict, synthetic-only projection of the deterministic manufacturing cost
control. The read-only English/Arabic view validates the contract marker,
source boundary, exact quantity/variance strings, bounded statuses, unique
order IDs, summary consistency, and replay digest shapes before showing
production quantities, cost variances, scrap reasons, filters, and evidence
digests. The module registry and threat-model index now declare the modern
Studio interface and browser test evidence. This is local synthetic UI
evidence only; web typecheck, production build, the full component suite
(64/64), and the accessibility E2E suite (8/8) pass. Live MRP/ERP/API behavior,
inventory, work-in-progress, and general-ledger posting, write-back, HA/DR, and production manufacturing
evidence remain open. GitHub publication remains deferred by owner policy.

## E-626 — Close certification evidence binding (2026-08-09)

- SQLite migration 37 and PostgreSQL Alembic revision `0082_pg_cert_evidence`
  add an immutable optional `evidence_digest` to certification metadata.
- SQLite and PostgreSQL consolidation-close adapters compute the digest
  server-side from the replay-verified `close_bundle`; certification reads
  recompute the bundle and fail closed on mismatch.
- PostgreSQL triggers include the digest in immutable prepared evidence, while
  generic approval certifications retain an empty digest compatibility path.
- Focused SQLite, PostgreSQL, API, bundle, approval, and Alembic contract tests
  pass. Local PostgreSQL 16.14 with a non-privileged role passes the live close
  certification and tenant-scoped approval certification tests.
- The full local `python -m pytest -q --tb=short -ra` regression exits 0 at
  100% with only declared capability skips; Ruff, Mypy (502 files), Bandit,
  pip-audit, Gitleaks 8.24.2, package build, and diff-check also pass.
- This proves binding of local control-journal and management evidence only. It
  does not establish statutory/legal-book close, external audit, hosted
  promotion, live ERP/bank providers, write-back, HA/DR, or production
  readiness. GitHub publication remains deferred by owner policy.

## E-627 — PostgreSQL pool lifecycle observability (2026-08-09)

- `PostgresConnectionPoolSnapshot` now exposes bounded `max_size`, `total`,
  `idle`, `leased`, and `closed` counters without DSN, tenant, or financial
  data; the pooled factory exposes the same snapshot for diagnostics.
- A 16-worker, 128-lease synthetic lifecycle contract proves the physical
  connection count never exceeds four, rollback-on-release occurs, shutdown
  closes idle connections, and post-close leases fail closed.
- `tests/test_postgres_foundation.py` passes 13 tests plus one declared live
  PostgreSQL skip; Ruff and Mypy pass for the changed surface.
- This is process-local pool lifecycle evidence only. It does not claim
  throughput, distributed fairness, queue HA, host-failure recovery, or
  production SLOs. GitHub publication remains deferred by owner policy.

## E-628 — Tenant-scoped durable-job queue health projection (2026-08-09)

- `DurableJobQueueSnapshot` is a backend-neutral, read-only projection with
  explicit status counts, queue depth, lease count, and oldest queued/running
  timestamps. It intentionally contains no job IDs, idempotency keys, input
  digests, or financial payloads.
- SQLite and PostgreSQL repositories implement the same fixed-scope contract;
  PostgreSQL evaluates both aggregate and lease queries inside tenant RLS
  scope. The application service records only bounded operational metrics.
- The SQLite durable-job suite passes 13 tests. The PostgreSQL live contract
  now checks tenant isolation plus queued/running/retrying and lease counts
  when `RECONFORGE_TEST_POSTGRES_DSN` and a non-privileged role are available.
- This proves a bounded observability projection only. Distributed queue HA,
  host-failure recovery, throughput, capacity, fairness, and production SLO
  evidence remain open. GitHub publication remains deferred by owner policy.

## E-629 — Sanitized durable-job queue CLI surface (2026-08-09)

- `reconforge ops durable-job-queue --tenant ...` now reads the E-628
  projection through the local SQLite application/repository boundary and
  supports optional workspace, organization, and entity lane filters.
- The detail output contains only scope, status counts, queue/total depth,
  lease count, and oldest timestamps; it does not print job IDs, idempotency
  keys, digests, or financial payloads.
- The CLI contract passes with a synthetic queued job and explicitly asserts
  the job identifier is absent. This is a local read-only operator surface,
  not PostgreSQL API exposure, distributed authorization, queue HA,
  throughput, or production operations evidence. GitHub publication remains
  deferred by owner policy.

## E-630 — Benchmark drain checks use the shared queue projection (2026-08-09)

- SQLite durable-job load and PostgreSQL durable-job scale profiles now use
  `DurableJobQueueSnapshot` per declared tenant lane for final queue/running
  drain counts. Raw SQL remains only for immutable partition-effect
  duplicate/digest inspection, which the sanitized projection deliberately
  does not expose.
- Focused load, soak, scale, and durable-job contract tests pass; live
  PostgreSQL tests remain declared skips when no DSN is configured. This is an
  evidence-path consistency improvement, not a throughput, capacity,
  distributed fairness, queue HA, or production-sizing claim.

## E-631 — Grouped matching cross-engine parity contract (2026-08-09)

- The persistence-free PostgreSQL grouped-matching adapter is now compared with
  the canonical `GroupedSubsetSumStrategy` for all five supported grouped
  modes: one-to-many, many-to-one, many-to-many, partial-settlement, and
  portfolio.
- Every projected row carries a strategy-result digest equal to the direct
  strategy decision digest. A one-cent canonical input mutation is asserted to
  change that digest, preventing a stale or second-calculation projection.
- The focused grouped-worker suite passes 14 tests; Ruff and Mypy pass for the
  changed test surface.
- This is local adapter-boundary evidence only. Live PostgreSQL execution,
  cross-engine SQL parity, distributed scale, HA/DR, providers,
  posting/write-back, and production readiness remain open. GitHub publication
  remains deferred by owner policy.

## E-632 — Public open-data connector live probe (2026-08-09)

- The existing World Bank public read-only reference connector was exercised
  with `RECONFORGE_TEST_PUBLIC_NETWORK=1` against its exact allowlisted
  dataset/resource endpoint.
- The full connector file passes 7/7, including the live page probe's bounded
  response, closed schema, finite Decimal values, one-attempt policy, and
  canonical response digest.
- This is a dated external observation that can drift with the upstream public
  dataset. It does not promote the connector to a live ERP/bank integration or
  prove authenticated provider contracts, payment/write-back, HA/DR, or
  production readiness. GitHub publication remains deferred by owner policy.

## E-633 — PostgreSQL durable-job null-scope replay and scale rerun (2026-08-09)

- A live backpressure rerun exposed a real defect: replay readers converted a
  nullable organization column to the literal string `None`, which made RLS
  hide effects and transition lineage for organization-less jobs.
- `_optional_scope_text` now preserves SQL NULL across lease renewal, effect,
  transition, and lease-event readers. The focused conversion regression and
  Ruff/Mypy pass.
- On the existing PostgreSQL 16.14 service with a non-superuser role, the
  backpressure profile, 10K effects, and 100K effects profiles pass; grouped
  worker, 500-partition, and 10K-partition gates also pass.
- This is one-host synthetic runtime evidence. Distributed fairness, queue HA,
  host failure, soak/SLOs, RPO/RTO, provider behavior, and production capacity
  remain open. GitHub publication remains deferred by owner policy.

## E-634 — Repeated PostgreSQL HA/DR drill (2026-08-09)

- The current-tree verifier passes 3/3 disposable Docker PostgreSQL 17.10
  primary/synchronous-standby runs on Docker Engine 29.6.2.
- Every run has zero acknowledged failover/failback transaction loss, cleanup
  success, final sequence 4, failover RTO 10.960–11.402s, and failback RTO
  1.109–1.170s under the bounded 60s ceiling.
- This remains one physical host and one failure domain with a manual
  controller. Independent hosts, quorum/witness, automatic failover, site loss,
  production SLOs, and HA/DR readiness remain open. GitHub publication remains
  deferred by owner policy.

## E-635 — Sanitized durable-job queue API and PostgreSQL metrics boundary (2026-08-09)

- Added authenticated `GET /api/v1/ops/durable-jobs/queue` with `ops.read`.
  Local mode requires an explicit tenant query; server mode derives the tenant
  from `X-ReconForge-Tenant`, rechecks tenant policy, and uses the PostgreSQL
  RLS boundary. Optional workspace/organization/entity lane filters are
  explicit.
- The response contains only fixed status counts, queue/total depth, lease
  count, scope, and oldest timestamps. Focused tests assert that job IDs and
  input digests are absent. Authorization inventory is 253 routes with digest
  `b648629d7612ff65cc4e1731cd2623189cace6a2ff311cec1956fa3c9dddca37`.
- Repaired the PostgreSQL metrics wrapper to use the configured identity
  factory and `PostgresTenantBoundary` instead of the stale nonexistent
  `postgres_pool` state. Focused API metrics and operations tests pass, Ruff
  passes, and Mypy reports no issues in 503 source files.
- This is bounded API observability and route-boundary evidence. Distributed
  invalidation, queue HA, throughput, host loss, provider behavior, and
  production SLOs remain open. GitHub publication remains deferred by owner
  policy.

## E-636 — Live PostgreSQL HTTP queue-health contract (2026-08-09)

- Added an opt-in live API test that provisions two disposable tenants, a
  least-privilege `ops.read` service account, forced-RLS durable-job and scope
  authority schemas, and one synthetic queued job.
- The real `TestClient` request authenticates through the PostgreSQL identity
  pool, returns the tenant/workspace/entity projection with the expected
  queued count and queue depth, excludes the job identifier and input digest,
  and rejects the credential in the sibling tenant.
- The local PostgreSQL 16.14 non-privileged run passes. Without the declared
  disposable service the test is an explicit capability skip. This is
  one-host synthetic HTTP/RLS evidence only. The server-boundaries workflow
  now invokes the complete operations API file after the parity matrix; no
  hosted result is inferred until that workflow actually runs. Distributed
  policy invalidation, queue HA, throughput, host loss, provider behavior,
  and production SLOs remain open. GitHub publication remains deferred by
  owner policy.

## E-637 — Live PostgreSQL metrics HTTP contract (2026-08-09)

- Added an opt-in live API test for `/api/v1/metrics/dashboard` and
  `/api/v1/metrics/lineage` using two disposable tenants, a least-privilege
  `metrics.read` service account, PostgreSQL identity authentication, and the
  tenant boundary with forced RLS.
- The local PostgreSQL 16.14 non-privileged run passes. The dashboard returns
  an empty tenant-scoped snapshot projection and lineage returns the seeded
  definitions; the same credential presented with the sibling tenant is
  rejected with HTTP 401.
- The `server-boundaries` workflow now invokes `tests/test_api_metrics.py`
  explicitly after the operations API contract. This makes the fixed metrics
  identity-factory wrapper an intentional hosted gate, but no hosted result is
  inferred while GitHub publication is deferred.
- This remains one-host synthetic API/RLS evidence only. Distributed IAM,
  provider behavior, throughput, HA/DR, and production SLOs remain open.

## E-638 — Local manufacturing cost-control persistence and API (2026-08-09)

- Migration 38 adds an immutable, workspace-scoped SQLite table for the
  deterministic manufacturing cost-control report. Repository writes require
  `finance_core.manage`, are idempotent by decision digest, and verify the
  artifact digest, status counts, and full replay payload on every read.
- Authenticated local routes now provide create/list/read for the report with
  `finance_core.read`, `finance_core.validate`, and `finance_core.manage`
  boundaries. Payloads are bounded and network dispatch is explicitly disabled;
  PostgreSQL server mode returns a deliberate unsupported response until a
  parity adapter is implemented.
- Focused persistence/API, tamper, workspace-isolation, backup/restore,
  authorization-inventory, Ruff, and Mypy checks pass. This closes only the
  local evidence path for the manufacturing control; statutory valuation,
  live ERP/MRP, inventory/WIP/GL posting, write-back, HA/DR, and production
  readiness remain open. The full local Python regression exits 0 with only
  declared capability skips; package build, Bandit, pip-audit, Ruff, Mypy, and
  diff-check also pass. GitHub publication remains deferred by owner policy.

## E-639 — PostgreSQL manufacturing cost-control parity (2026-08-09)

- Alembic revision `0083_pg_manufacturing` adds the tenant/workspace-scoped
  `reconforge.manufacturing_cost_control_runs` table with JSONB report/status
  projections, exact digest constraints, forced RLS, immutable triggers, and a
  downgrade that refuses to discard non-empty evidence.
- The PostgreSQL repository uses the existing tenant boundary and transaction
  advisory lock for idempotent decision-digest replay. The authenticated API
  now selects this adapter in server mode, while local mode continues to use
  SQLite; both paths explicitly disable network dispatch and financial posting.
- Static schema/API contracts and a disposable PostgreSQL 16 run using a
  non-superuser role pass RLS tenant isolation, replay/list/get, tamper refusal,
  and server-route selection. Hosted CI/native-tool execution, ERP/MRP,
  valuation, inventory/WIP/GL posting, write-back, HA/DR, and production
  readiness remain open. GitHub publication remains deferred by owner policy.

## E-640 — Live manufacturing PostgreSQL server API contract (2026-08-10)

- A disposable PostgreSQL 16 run provisions a non-superuser application role,
  service-account credential, workspace scope grant, and one replay-verified
  manufacturing report. Real `TestClient` list/read requests authenticate
  through the PostgreSQL identity factory and select the PostgreSQL adapter.
- The HTTP contract returns server-mode source metadata and the expected
  digest, rejects a sibling workspace, and rejects the same credential in a
  sibling tenant. The test removes its temporary rows and the container after
  execution.
- This proves one-host synthetic HTTP/RLS behavior only. Hosted CI, live
  ERP/MRP interoperability, statutory/standard-cost valuation, inventory/WIP/
  GL posting, write-back, HA/DR, and production readiness remain open. GitHub
  publication remains deferred by owner policy.

## E-641 — Static live-Redis token removal (2026-08-10)

- `.github/scripts/verify_redis_live.py` now creates a cryptographically random
  token for each disposable Redis drill; no fixed live-token literal remains.
- `tests/test_redis_live_report.py` passes, and Gitleaks 8.30.1 scans all 649
  commits with no leaks. This is repository secret-hygiene evidence only; it
  does not prove hosted security execution, provider security, or release
  approval. GitHub publication remains deferred by owner policy.

## E-642 — Live retail settlement PostgreSQL server API contract (2026-08-10)

- A disposable PostgreSQL 16 run provisions a non-superuser application role,
  service-account credential, workspace scope grant, and one replay-verified
  retail settlement report. Real TestClient list/read requests authenticate
  through the PostgreSQL identity factory, return server-mode source metadata
  and the expected digest, reject a sibling workspace, and reject the same
  credential in a sibling tenant.
- The server-boundaries workflow now invokes the retail PostgreSQL repository
  and HTTP contract files. Local focused tests and the disposable live run
  pass. This is one-host synthetic API/RLS evidence only; processor/ERP
  authentication, settlement finality, posting, write-back, HA/DR, and
  production readiness remain open. GitHub publication remains deferred by
  owner policy.

## E-643 — Live professional invoice/payment PostgreSQL server API contract (2026-08-10)

- A disposable PostgreSQL 16 run provisions a non-superuser application role,
  service-account credential, workspace scope grant, and one replay-verified
  professional invoice/payment report. Real TestClient list/read requests
  authenticate through the PostgreSQL identity factory, return server-mode
  source metadata and the expected digest, reject a sibling workspace, and
  reject the same credential in a sibling tenant.
- The server-boundaries workflow now invokes the professional PostgreSQL
  repository and HTTP contract files. Local focused tests and the disposable
  live run pass. This is one-host synthetic API/RLS evidence only; billing
  provider authentication, revenue recognition, posting, write-back, HA/DR,
  and production readiness remain open. GitHub publication remains deferred
  by owner policy.

## E-644 — Live consolidation-close PostgreSQL server API contract (2026-08-10)

- Added an opt-in live HTTP test that provisions two disposable tenants, a
  non-superuser service-account credential, a workspace scope grant, and one
  replay-verified consolidation control-journal run.
- Real `TestClient` list/read requests authenticate through the PostgreSQL
  identity factory and forced-RLS repository, return server-mode source
  metadata plus worksheet/journal evidence, reject a sibling workspace, and
  reject the same credential in a sibling tenant.
- Fixed a real server-only serialization defect: the PostgreSQL replay reader
  now removes its internal Money-bearing `worksheet_object` before returning
  API records. Local focused tests and the disposable PostgreSQL 16 run pass.
- This is one-host synthetic HTTP/RLS evidence only. Statutory/legal-book
  posting, live ERP/bank sources, write-back, HA/DR, and production readiness
  remain open. GitHub publication remains deferred by owner policy.

## E-645 — Live reconciliation PostgreSQL server API contract (2026-08-10)

- Added an opt-in live HTTP test that provisions two disposable tenants, a
  non-superuser service-account credential, a workspace scope grant, and one
  synthetic reconciliation run with two exact-decimal inputs.
- Real `TestClient` submit/list/detail/input requests authenticate through the
  PostgreSQL identity factory and forced-RLS repository. The response keeps
  amount values as strings representing exact decimals, rejects a sibling
  workspace, and rejects the same credential in a sibling tenant.
- Local focused tests pass against PostgreSQL 16. Hosted execution, live
  bank/ERP interoperability, worker completion, posting, write-back, HA/DR,
  and production readiness remain open. GitHub publication remains deferred
  by owner policy.
# E-646 — local bank-statement evidence persistence (2026-08-10)

- Status: completed locally; GitHub publication intentionally deferred by owner policy.
- Additive SQLite migration 39 adds immutable `bank_statement_control_runs` with
  workspace-scoped decision/artifact uniqueness and bounded report JSON.
- `SQLiteBankStatementRepository` verifies the outer artifact digest, the
  deterministic decision digest, status counts, and the bank-control replay
  contract before idempotent persistence; conflicts, tampering, and missing
  migration fail closed.
- Authenticated local API routes now provide POST/list/read at
  `/api/v1/bank/statement-controls` and explicitly return
  `network_dispatch=disabled`; at this slice PostgreSQL server mode was still a
  deliberate 501 boundary, later superseded by E-647 parity.
- Backup/restore includes the table and audit events. Focused SQLite/API,
  authorization inventory (259 routes; digest
  `d8cc36e1a44ba1fe069d639f2107f36a6aecd6cb5ba04b1023dd31426e31e8ba`), migration,
  and restore tests pass; Ruff, Mypy, and diff-check pass.
- Evidence limit: synthetic local files only. Live bank/provider authentication,
  source authenticity, PostgreSQL parity, worker execution, payment initiation,
  posting, ERP write-back, HA/DR, and production operations remain open.

## E-647 — PostgreSQL bank statement evidence server boundary (2026-08-10)

- Additive Alembic 0084 and `PostgresBankStatementRepository` persist the same
  replay-verified control report as bounded JSONB with forced tenant/workspace
  RLS, immutable triggers, workspace-scoped idempotency, and fail-closed replay
  verification.
- Authenticated server-profile POST/list/read requests select PostgreSQL through
  the existing identity factory; local mode remains SQLite and both modes keep
  `network_dispatch=disabled`.
- `tests/test_postgres_bank_statement.py` and
  `tests/test_api_server_bank_statement.py` pass against disposable PostgreSQL
  16 with a non-superuser role, proving migration, replay/list/read, workspace
  isolation, sibling-tenant denial, and immutable-update refusal.
- Evidence boundary: synthetic one-host persistence/HTTP/RLS only. Live bank or
  provider authentication, source authenticity, payment execution, posting,
  ERP write-back, worker completion, hosted CI, HA/DR, and production operation
  remain unverified. GitHub publication remains deferred by owner policy.

## E-648 — Modern Studio accessibility and browser gate (2026-08-10)

- `npm --prefix apps/web run typecheck` passes.
- `npm --prefix apps/web run test:run` passes 12 files / 67 tests.
- `npm --prefix apps/web run build` produces the production Vite bundle.
- `npm --prefix apps/web run e2e -- e2e/accessibility.spec.ts` passes 9/9,
  including English/Arabic critical routes, keyboard focus/dialog behavior,
  contrast/reduced-motion/color-safe states, redaction, retail/bank/
  manufacturing/professional evidence projections, and mobile landmarks.
- Boundary: local synthetic/read-only browser evidence only. No authenticated
  live API browser session, provider authenticity, posting/write-back, hosted
  deployment, HA/DR, or production availability is implied. GitHub publication
  remains deferred by owner policy.

## E-649 — Public World Bank reference connector online revalidation (2026-08-10)

- `RECONFORGE_TEST_PUBLIC_NETWORK=1 uv run --no-sync pytest -q
  tests/test_connector_world_bank_public.py --tb=long -ra` passes 7/7.
- The run covers the bounded live HTTP fetch, finite-decimal schema,
  pagination/count checks, canonical response digest, cross-format parity, and
  unsafe-input/network-policy refusals.
- A direct current-tree fetch on the same allowlisted endpoint returned 1,000
  rows from source count 2,508 in one attempt with response digest
  `9f0e40df0fe72f2310e8e5747285f4657389ffe4f55b844e5ca405da6f88dc11`.
- Boundary: this is open public-data reference evidence only. It does not prove
  a live bank/ERP customer connector, source authenticity, provider SLA,
  payment execution, write-back, hosted deployment, or production operations.
  GitHub publication remains deferred by owner policy.

## E-650 — Individual and freelancer cashflow control slice (2026-08-10)

- Added the experimental `individual.cashflow` module: exact local income and
  expense aggregation by period/type/category, optional budget lines, visible
  within-budget, over-budget, unbudgeted, and no-activity outcomes, and
  canonical decision plus outer artifact digests.
- Recorded this slice under the `P4-PLAT-001` `completed_slices` backlog path.
- Added local CLI (`reconforge individual cashflow run`), authenticated
  stateless API (`POST /api/v1/individual/cashflow-controls/run`), bounded
  examples, JSON Schema, and a declarative control pack. API responses keep
  `network_dispatch=disabled` and create no database or provider side effect.
- Focused domain/CLI/API, module-registry, threat-index, and route-inventory
  tests pass; the strict read-only Studio component is covered in English and
  Arabic, web typecheck/build pass, and the accessibility route gate covers
  `/individual-cashflow` in both locales.
- Boundary: this is local experimental personal-finance control evidence only.
  It does not prove bank authenticity/connectivity, tax or legal treatment,
  posting, write-back, hosted persistence, HA/DR, or production readiness.
  GitHub publication remains deferred by owner policy.

## E-651 — PostgreSQL least-privilege trigger hardening and local gate rerun (2026-08-10)

- A live disposable PostgreSQL 16 Finance Core HTTP test reproduced an
  `InsufficientPrivilege` failure: inventory-reversal dependency triggers could
  not inspect protected reversal evidence when an ordinary non-superuser
  application role wrote a Finance Core entry.
- The three trigger functions now use `SECURITY DEFINER` with the fixed
  `pg_catalog, reconforge` search path. Alembic 0085 reapplies the idempotent
  schema for existing installations and downgrades only the function security
  attributes; it never deletes evidence rows. ADR 0489 records the boundary.
- After upgrade, the previously failing live HTTP test passes. The expanded
  disposable PostgreSQL suite passes 330 tests, the durable-job 10K/100K/
  backpressure profiles pass, and grouped-matching scale/runtime tests pass.
  Native `pg_dump`/`pg_restore` smoke passes inside the pinned PostgreSQL image.
- The Redis live verifier returns `status=verified`, with tenant-key isolation,
  cross-process policy-cache invalidation, raw-token absence, and cleanup true;
  report digest `3aeec3811c6606e55c679bc36a7af4adb08f73b0570111e483413dbce1590ed1`.
- Full local Python regression passes with only declared capability skips and
  existing warnings. Ruff, Mypy (515 files), Bandit, pip-audit, package build,
  web typecheck/Vitest (13 files/70 tests)/build, and Playwright accessibility
  (10/10) pass. Hosted CI, HA/DR, live provider/write-back, statutory posting,
  and production readiness remain open; GitHub publication remains deferred.

## E-652 — Authenticated PostgreSQL ownership-change evidence API (2026-08-10)

- Added server-profile-only `POST /api/v1/consolidation-ownership-change` and
  tenant-scoped replay `GET /api/v1/consolidation-ownership-change/{artifact_id}`.
- The request uses strict canonical Money objects and Decimal text for
  ownership percentages. The authenticated principal is bound as
  `prepared_by`; the domain still requires a distinct approved actor and the
  persisted result remains explicitly `posted: false`.
- The helper uses the existing PostgreSQL tenant boundary and the repository's
  forced-RLS, immutable, replay-verified evidence table. Local mode returns a
  deliberate 503 rather than silently falling back to SQLite.
- Focused API/auth-inventory tests pass (7 tests); the live PostgreSQL identity
  test now covers create/read, non-posting output, and sibling-tenant denial.
  The artifact is tenant-scoped rather than workspace-scoped by design.
  Hosted CI, live bank/ERP providers, write-back, HA/DR, statutory
  posting, and production readiness remain open. GitHub publication remains
  deferred by owner policy.

## E-653 — Live PostgreSQL consolidation evidence API gate (2026-08-10)

- Added a clean-runtime HTTP gate for the existing deferred-tax and impairment
  evidence APIs. A pinned PostgreSQL 16 Alpine database was exercised through
  a non-superuser, non-`BYPASSRLS` application role with authenticated bearer
  sessions, strict actor binding, forced tenant RLS, idempotent POST replay,
  replay-verified GET responses, and sibling-tenant denial.
- The gate passes both `/api/v1/consolidation-deferred-tax` and
  `/api/v1/consolidation-impairment`; every persisted result remains explicitly
  `posted: false`. The ownership-change fixture was hardened to install its
  privileged-session and emergency-access dependencies and passes on the same
  clean runtime.
- The fixture installs direct schema SQL, including the existing nullable
  hierarchy-attribution schema. It does not exercise the Alembic upgrade path.
  Evidence is synthetic, single-node, and tenant-scoped when hierarchy headers
  are absent.
- Boundary: no statutory tax accounting or impairment methodology, live
  provider, journal posting, write-back, restore drill, HA/DR, RPO/RTO,
  hosted CI, or production-readiness claim. GitHub publication remains
  deferred by owner policy.

## E-654 — Alembic-head consolidation evidence API gate (2026-08-10)

- Reworked the live deferred-tax/impairment API fixture to run the repository's
  Alembic chain from an empty PostgreSQL 16 Alpine database through head
  `0085_pg_reversal_definer` before granting the application role.
- The non-superuser/non-`BYPASSRLS` HTTP run passes authenticated POST/GET,
  strict preparer binding, independent approver checks, idempotent replay,
  replay verification, sibling-tenant denial, and explicit `posted: false`
  output for both deferred-tax and impairment. The hardened ownership-change
  fixture also passes on the same migration-head runtime.
- This supersedes the direct-schema-only runtime evidence for current parity
  status; the migration path is now verified, while downgrade/rollback remains
  a separate gate.
- Boundary: synthetic single-node tenant-scoped evidence only. No statutory
  tax or impairment methodology, journal posting, live provider, write-back,
  restore, HA/DR, RPO/RTO, hosted CI, or production-readiness claim is made.
  GitHub publication remains deferred by owner policy.

## E-656 — Cross-platform benchmark provenance and current secret-gate closure (2026-08-10)

- Benchmark evidence verification now hashes a canonical LF representation of
  tracked JSON artifacts. This removes the Windows CRLF versus hosted-Linux LF
  drift that previously rejected the first grouped-matching artifact in CI;
  the checked-in digest now matches the Git checkout bytes.
- The direct verifier inserts the repository root before importing ReconForge,
  so a stale installed package cannot mask source-tree changes. Focused index
  tests pass, including a CRLF fixture and a subprocess invocation of the
  script; the verifier emits eight verified entries.
- The current full-history/tree Gitleaks 8.30.1 scan is clean. The existing
  `.gitleaksignore` entries remain narrow, fingerprinted synthetic false
  positives and do not exclude source, fixtures, docs, or lockfiles broadly.
- Boundary: this is local cross-platform provenance and current-tree secret
  scanning evidence. It does not prove hosted rerun, independent security
  review, live provider behavior, HA/DR, or production readiness. GitHub
  publication remains deferred by owner policy.

## E-657 — PostgreSQL native client/service major-version compatibility (2026-08-10)

- A real Linux probe using PostgreSQL 17 client tools against the pinned
  PostgreSQL 16 service reproduced restore failure on the unsupported
  `transaction_timeout` setting, after dump creation and validation succeeded.
- The server-boundaries workflow now installs `postgresql-client-16` beside
  `libpq-dev`, asserts that `pg_config` and `pg_dump` report major version 16,
  and retains the existing `pg_config --bindir` checks for all five tools.
- The phase-4 contract test covers package selection and version assertions.
  A matching PostgreSQL 16 client probe completed dump/list/restore/cleanup;
  hosted encrypted backup/restore is still the required E-461 evidence.
- Boundary: this closes client/service selection drift only. It does not prove
  hosted CI, cross-major restore, PITR, HA/DR, RPO/RTO, or production readiness.
  GitHub publication remains deferred by owner policy.

## E-655 — Alembic-head authenticated consolidation-close lifecycle gate (2026-08-10)

- Added a live server-boundary test that starts from an empty pinned PostgreSQL
  16 Alpine database, runs Alembic through head `0086_pg_close_reopened`, and
  grants the minimum close/identity/evidence tables to a non-superuser,
  non-`BYPASSRLS` application role.
- The authenticated HTTP lifecycle passes period creation and deterministic
  replay, worksheet preparation, self-approval refusal, independent approval,
  posting with committed effects, reversal request/approval, period lock and
  reopen, replay-verified run detail, sibling-workspace denial, and
  sibling-tenant denial.
- PostgreSQL now persists `Reopened` for consolidation-close periods and allows
  locking from `Open` or `Reopened`; migration `0086_pg_close_reopened` refuses
  downgrade while reopened rows exist. The adapter and PostgreSQL contract
  tests were updated to preserve this backend-neutral lifecycle state.
- Evidence is synthetic, single-node, and local. It does not prove statutory
  consolidation, legal-book posting, live ERP/bank providers, write-back,
  restore, HA/DR, RPO/RTO, hosted CI, or production readiness. GitHub
  publication remains deferred by owner policy.

## E-658 — PostgreSQL persistent scheduler multi-process fairness gate (2026-08-10; ADR 0495)

- `test_live_postgres_persistent_scheduler_coordinates_spawned_processes` now
  starts two spawned worker processes. Each process opens its own PostgreSQL
  connection and scheduler instance, reserves the shared tenant-scoped lane
  cursor, claims one exact workspace/entity lane, and cancels the synthetic job
  through the normal lease-fenced worker path.
- Three repeated local runs returned one claim for each lane (`[0, 1]`), left
  no leases, and left the cursor at the expected next index/version (`1, 3`).
  The server-boundaries workflow invokes this gate alongside the existing
  PostgreSQL durable-job contracts.
- Evidence boundary: two independent local processes on one PostgreSQL 16
  service only. This closes neither cross-host fairness nor queue HA/failover,
  throughput, soak, capacity, RPO/RTO, nor production scheduling SLOs. GitHub
  publication remains deferred by owner policy.

## E-659 — PostgreSQL worker crash-after-checkpoint recovery (2026-08-10; ADR 0496)

- A real spawned worker process claims a synthetic two-partition job, commits the
  first checkpoint, and exits without releasing its lease. A newly connected
  recovery worker reclaims the expired lease with generation 2, sees the
  persisted checkpoint, and completes the remaining partition.
- Three local repetitions pass with exactly two effects and ordered lease
  actions `claimed`, `taken_over`, `released`; no duplicate effect or residual
  lease remains. The server-boundaries workflow invokes this crash/resume gate.
- Evidence boundary: one synthetic PostgreSQL 16 service and one-host process
  failure only. Queue HA, cross-host recovery, capacity, soak, RPO/RTO, and
  production SLOs remain unverified. GitHub publication remains deferred by
  owner policy.

## E-660 — Write-back crash window recovery without duplicate provider mutation (2026-08-10; ADR 0497)

- A real spawned worker process now stages a dispatched write-back intent,
  sends an injected provider response that records acceptance, and exits via
  `os._exit` before the durable acknowledgement is written. The parent
  verifies the append-only repository still contains `DISPATCHED` version 3.
- A fresh recovery executor performs one idempotency-status lookup using the
  original key, never resolves the mutation payload, never invokes the POST
  transport, and persists the provider reference as `ACKNOWLEDGED` version 4.
  The marker proves exactly one provider POST before the crash and the recovery
  transport records exactly one status lookup.
- Focused write-back network tests and Ruff pass. This is a synthetic
  cross-process SQLite/provider-boundary failure injection; it does not prove
  vendor status-API interoperability, distributed idempotency, live ERP/bank
  semantics, accounting posting, HA/DR, or production write-back. GitHub
  publication remains deferred by owner policy.

## E-661 — Redis bounded read reconnect and mutation retry fence (2026-08-10; ADR 0498)

- Redis reads and health checks now permit one reconnect after a classified
  connection/timeout failure. The reconnect closes the stale pool first and
  then retries exactly once; configuration, data, and dependency errors remain
  fail-closed. Mutating operations (`SET`, `INCR`, lock scripts, and revokes)
  never retry an ambiguous network result.
- Unit failure injection proves the one-attempt ceiling for session and policy
  reads and proves mutation operations do not reconnect/replay. The live Redis
  suite passes 13/13 against the disposable `redis:7-alpine` service, including
  a real connection-pool disconnect followed by a successful session read.
- This is bounded one-host adapter evidence. Redis Sentinel/Cluster or server
  failover, cross-host durability, distributed quotas, outage RPO/RTO, and
  production SLOs remain open. GitHub publication remains deferred by owner
  policy.

## E-662 — Fresh local MinIO object-storage integrity and retention drill (2026-08-10; ADR 0499)

- A real boto3-backed `S3ObjectStore` run against the local MinIO image
  (`sha256:13582eff79c6605a2d315bdd0e70164142ea7e98fc8411e9e10d089502a6d883`)
  creates normal and Object Lock buckets and proves all five invariants:
  hierarchical tenant/workspace/entity isolation, immutable overwrite refusal,
  checksum-tamper refusal, retention-protected delete refusal, and cleanup.
- The schema/digest-bound report is retained at
  `docs/execution/S3_OBJECT_STORAGE_LIVE_DOCKER_DRILL_2026-08-10.json` with
  report digest `22597553e1833cf7ec8735ee1091f8309d0117997133b56bd9ee7119c27e1d49`.
  The current-report contract now validates all three dated artifacts.
- This is a fresh one-host disposable MinIO contract only. Replication, KMS,
  cross-site durability, provider interoperability, object-store HA/DR,
  malware scanning, authorized downloads, and production SLOs remain open.
  GitHub publication remains deferred by owner policy.

## E-663 — Narrow-terminal CLI error contract regression (2026-08-10; ADR 0500)

- The first full-suite rerun after E-662 exposed one compatibility failure in
  the existing ownership-change CLI test: Rich folded the phrase `exactly the
  declared contract` at a narrow TTY width, so the error contract was not
  machine-contiguous even though validation correctly failed closed.
- `_safe_cli_error` now uses `soft_wrap=True`, preserving complete error phrases
  on narrow terminals without changing validation, output schemas, financial
  calculations, or exit codes. The focused regression test and the complete
  local suite now pass.
- This is a presentation/CLI compatibility fix only; it does not establish
  hosted, provider, HA/DR, or production evidence. GitHub publication remains
  deferred by owner policy.

## E-664 — PostgreSQL backend-fault checkpoint recovery (2026-08-10; ADR 0501)

- A real spawned PostgreSQL worker commits `database-fault/p1`, reports its
  backend PID, and remains active. The parent administration session executes
  `pg_terminate_backend` against that exact worker session, modeling a
  database-connection failure after durable checkpoint commit.
- A fresh non-superuser recovery worker claims only after the logical lease
  expires, observes generation 2 and the first effect, commits
  `database-fault/p2`, and leaves exactly the ordered
  `claimed/taken_over/released` events with no duplicate effects or residual
  lease. Three local PostgreSQL 16.14 repetitions pass.
- This is one-host synthetic PostgreSQL session-fault evidence. It does not
  prove host/site loss, automatic failover, queue HA, cross-host recovery,
  RPO/RTO, throughput, or production scheduling. GitHub publication remains
  deferred by owner policy.

## E-665 — Canonical stock/GL result ordering (2026-08-10; ADR 0502)

- Stock/GL output frames now sort by stable match, record-instance, or
  exception identity. Mutable source position and source row remain attached
  lineage metadata but no longer determine CSV/JSON result order.
- A focused permutation regression covers matched, unmatched, invalid, and
  aggregate exception frames. This makes emitted local artifacts reproducible
  without changing decisions or discarding source location evidence.
- Boundary: local stock/GL ordering only. Cross-engine hosted parity, live
  providers, posting, HA/DR, and production sizing remain open. GitHub
  publication remains deferred by owner policy.

## E-666 — Current PostgreSQL HA/DR failover and failback drill (2026-08-10; ADR 0503)

- The repeated verifier completed three fresh disposable Docker PostgreSQL
  17.10 primary/synchronous-standby cycles on Docker Engine 29.6.2.
- All three runs recorded final sequence 4, zero acknowledged transaction
  loss, cleanup success, failover RTO 11.117–11.321 seconds, and failback RTO
  0.931–1.082 seconds under the 60-second drill ceiling.
- The schema-valid report is retained at
  `docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION_2026-08-10.json` and
  included in `MANIFEST.in`.
- Boundary: one Docker host/failure domain and a manual controller. This does
  not establish quorum/witness, automatic failover, host/site loss, production
  SLOs, or the hosted native-tool backup gate E-461. GitHub publication remains
  deferred by owner policy.

## E-667 — Strict management-pack financial ingress (2026-08-10; ADR 0504)

- Management-pack amount, risk, WIP, and close-completion helpers now pass
  `STRICT_FINANCIAL_INPUT_POLICY` explicitly.
- A regression rejects binary `float` input (`0.1`) at the report calculation
  boundary; malformed optional values remain visible as unquantified instead
  of being silently converted.
- Focused reports/generated-ingress/reconciliation-input-policy tests and Ruff
  pass. Named legacy compatibility callers, statutory accounting, hosted
  evidence, live providers, and production readiness remain open. GitHub
  publication remains deferred by owner policy.

## E-668 — Current local operator and Studio web validation (2026-08-10; ADR 0505)

- `reconforge doctor`, `reconforge validate examples/sample_data`, and a fresh
  `reconforge demo run` output directory exit successfully. The sample fixture
  reports ten intentional validation warnings and zero errors.
- `npm --prefix apps/web run typecheck`, `test:run` (13 files/70 tests), and
  `build` pass. Playwright reports 16 passed and five declared live-browser/
  HTTPS capability skips.
- An existing demo output directory is rejected when its client-pack recovery
  siblings are ambiguous; the successful evidence uses a fresh output path.
  Hosted deployment, live providers, and production readiness remain open.
  GitHub publication remains deferred by owner policy.

## E-670 — Python 3.12 all-extra collection gate (2026-08-10; ADR 0506)

- A fresh isolated Python 3.12 environment installed the locked all-extra
  profile and ran the seven modules named by the historical CI ImportErrors.
- Result: 48 passed, one declared live-PostgreSQL skip, and one existing
  Starlette deprecation warning; no collection ImportError. This is local
  dependency/test evidence only and does not replace hosted CI, native backup
  tools, or release attestation. GitHub publication remains deferred.

## E-671 — Python 3.12 full local regression (2026-08-10; ADR 0507)

- `uv run --isolated --python 3.12 --all-extras --locked --no-editable pytest
  -q --tb=short -ra` reaches 100% and exits 0 on the current tree.
- The collection contains 2,877 tests. PostgreSQL, Redis, S3/object-lock,
  public-network, and Windows-privilege capability skips remain explicit, with
  existing framework/legacy-input warnings only. Hosted CI, native backup,
  independent HA/DR, providers, and release approval remain open.

## E-672 — Local PostgreSQL CI-failure triage (2026-08-10; ADR 0508)

- Against local Docker PostgreSQL 16 with a non-privileged application role,
  the metrics/Alembic focused suite passes 11 tests, including migration
  upgrade/downgrade/re-upgrade.
- The native-backup suite passes with one explicit skip because Windows lacks
  `pg_config`/`pg_dump`/`pg_restore` on `PATH`. The historical metrics and
  migration failures are not reproduced locally; hosted E-461 remains open.

## E-673 — Local PostgreSQL server-boundary matrix (2026-08-10; ADR 0509)

- A fresh disposable PostgreSQL 16 database reached Alembic head
  `0086_pg_close_reopened`; the non-privileged `reconforge_app` role passed
  selected foundation, master-data, ledger, identity, evidence,
  reconciliation, metrics, migration, sector API, and durable-job
  backpressure/10K suites.
- The database `reconforge_codex_20260810` was dropped after verification.
  This is one-host synthetic evidence only; native backup binaries, hosted CI,
  independent HA/DR, live providers, and production readiness remain open.

## E-674 — Repeated PostgreSQL durable-job soak (2026-08-10; ADR 0510)

- Added `reconforge.benchmark.postgres_durable_job_soak`, reusing the existing
  PostgreSQL multi-worker scale harness for three isolated synthetic tenant
  iterations in one disposable PostgreSQL 16 host.
- The live profile completed 192/192 jobs and 768/768 partition effects with
  zero duplicates, zero queued/running residue, and the same effect-set digest
  in all three iterations. Stable job IDs are isolated by unique tenant lanes,
  preserving the tenant-scoped primary key boundary.
- The digest-bound report is
  `docs/execution/benchmarks/postgres-durable-job-soak-current-2026-08-10.json`
  with report digest
  `ed6d63068cb6468c154b09cee2fe0abfe23e70703220e129f06333e8dd3b285a`.
- Boundary: one disposable host and bounded synthetic repetition only.
  Distributed soak, queue HA, automatic failover, host loss, capacity,
  throughput, RPO/RTO, and production scheduling remain unverified. GitHub
  publication remains deferred by owner policy.
