# ReconForge Execution Decisions Log

> This document records all decisions made during the ReconForge transformation execution.
> Each decision follows the format: ID, Date, Context, Decision, Rationale, Reversibility.

## Decisions

### D-305: Treat the post-IAM local gate as correctness evidence, not release approval
- **Date**: 2026-08-05
- **Context**: The tenant-policy hardening changed central request authorization
  and required a full regression after the live PostgreSQL checks.
- **Decision**: Record the full local pytest/static/security/package gate as
  E-400 while keeping hosted, provider, independent-HA/DR and production
  release claims separate.
- **Rationale**: A green local suite proves current repository compatibility;
  it cannot prove external services or independent failure domains.
- **Reversibility**: Replace the E-400 evidence entry if a later run supersedes
  it; no runtime or migration rollback is required.
- **Verification**: Pytest, Ruff, Mypy, Bandit, pip-audit, build and diff-check
  all exit successfully.

### D-304: Require request-tenant equality for every server-scoped policy check
- **Date**: 2026-08-05
- **Context**: Server route adapters pass tenant/workspace values into the
  central policy helper. Tenant-wide administration now has an equality guard,
  but workspace-scoped routes also need protection from a future adapter bug
  that supplies a sibling tenant.
- **Decision**: Make `enforce_server_scoped_permissions` compare the adapter
  tenant with the validated `X-ReconForge-Tenant` header and fail closed before
  policy evaluation on mismatch.
- **Rationale**: The request tenant is the authoritative security boundary;
  adapter arguments must not be able to widen it.
- **Reversibility**: Remove the equality check, ADR 0346, package entry and
  E-399 record; no migration or persisted-data change is required.
- **Verification**: Focused execution-scope tests pass with sibling-tenant
  refusal.

### D-303: Promote tenant-wide policy enforcement only on a non-superuser fresh database
- **Date**: 2026-08-05
- **Context**: The new tenant-wide central-policy route boundary needed live
  PostgreSQL evidence. A first attempt used a superuser and a previously used
  database, so RLS cleanup assertions were not meaningful.
- **Decision**: Retain only a fresh PostgreSQL 16 run with the non-superuser
  `reconforge_app` (`NOBYPASSRLS`) as runtime evidence; record the superuser
  attempt as diagnostic failure, not as a passing retry.
- **Rationale**: A role that bypasses RLS cannot validate tenant isolation, and
  contaminated state cannot validate guarded downgrade behavior.
- **Reversibility**: Remove E-398 and its matrix entry if the runtime profile
  is withdrawn; code and migrations are unchanged.
- **Verification**: Access administration, security governance and identity
  administration live contracts pass 3/3 on the fresh database.

### D-302: Bind tenant-wide administration to central policy at request time
- **Date**: 2026-08-05
- **Context**: PostgreSQL identity, role, scope-grant, and security-retention
  administration used human permission dependencies but did not uniformly
  re-evaluate the same permission immediately before repository access.
- **Decision**: Add `enforce_server_tenant_permission` with a request-tenant
  equality guard and adopt it across the four tenant-wide administration route
  families. Do not manufacture a workspace scope for resources that are
  intentionally tenant-wide.
- **Rationale**: This closes a real authorization boundary while preserving
  least privilege, step-up requirements and local SQLite compatibility.
- **Reversibility**: Remove the helper, route calls, ADR 0345 and E-397; no
  migration or persisted-data change is needed.
- **Verification**: Focused route and execution-scope tests pass 15/15.

### D-301: Exercise the reference REST reader through disposable HTTPS
- **Date**: 2026-08-05
- **Context**: The reference REST connector's schema, cursor and retry rules
  were covered by injected transports but not by the actual TLS/HTTP GET path.
- **Decision**: Add a loopback-only HTTPS sandbox that returns one transient
  `429` and then a valid page. Drive the standard pinned transport and require
  stable idempotency/cursor headers, secret-reference handling, digest parity
  and deterministic cleanup. Clone the manifest only inside the test to bind
  the ephemeral endpoint; keep the packaged reference manifest unchanged.
- **Rationale**: This adds meaningful transport integration evidence while
  preserving the no-vendor/no-internet boundary and the existing allowlist.
- **Reversibility**: Remove the test, ADR 0344, package entry and E-395
  records; runtime code and migrations are unchanged.
- **Verification**: The focused sandbox passes 1/1.

### D-300: Exercise write-back transport through a disposable local HTTPS server
- **Date**: 2026-08-05
- **Context**: Injected write-back transports proved retry and acknowledgement
  rules, but did not exercise the actual TLS/HTTP stack.
- **Decision**: Add a local-only HTTPS sandbox using a short-lived synthetic
  certificate, two transient `503` responses, and one digest-valid provider
  acknowledgement. Keep the resolver/public-address guard active while the
  test connection factory pins the socket to loopback. Require stable payload
  and idempotency values and secret-free receipts.
- **Rationale**: This closes a meaningful transport integration gap without
  introducing internet calls, provider credentials, or a false live-provider
  claim.
- **Reversibility**: Remove the focused test, ADR 0343, package entry and
  E-394 records; application defaults and migrations are unchanged.
- **Verification**: The focused sandbox passes 1/1 and the connector/write-back
  regression set passes 42/42.

### D-299: Keep the current competitive matrix official-source and bounded
- **Date**: 2026-08-05
- **Context**: The execution goal requires ethical comparison with open-source
  and commercial financial/ERP platforms without copying proprietary claims or
  treating a marketing page as independent assurance.
- **Decision**: Add a dated official-source supplement citing first-party Odoo,
  ERPNext and Apache Fineract documentation. Separate source observations from
  ReconForge code/evidence and record every missing comparison as an open gap.
  Do not infer performance, compliance, customer outcomes, security assurance,
  pricing or superiority.
- **Rationale**: This preserves useful market context while keeping the claim
  boundary auditable and aligned with the repository's evidence policy.
- **Reversibility**: Remove the supplement, ADR 0342, regression test, package
  entries and E-393 records; no runtime or migration state changes.
- **Verification**: `tests/test_official_competitive_matrix.py` passes with the
  five required official links, local evidence references and bounded-language
  guardrails.

### D-298: Bound PostgreSQL grouped-matching scale with explicit connection reuse
- **Date**: 2026-08-05
- **Context**: The first 10K grouped-matching probe failed closed from Windows
  ephemeral-port exhaustion because worker phases opened fresh connections.
- **Decision**: Add a dependency-free `PostgresConnectionPool` with explicit
  size/timeout limits, rollback-on-release, idempotent proxy close, and clear
  idle/active shutdown. Use it in the bounded 10K grouped-matching harness;
  do not change the default unpooled application boundary implicitly.
- **Rationale**: Connection reuse removes avoidable TCP churn while preserving
  tenant-local transaction scopes and an observable resource ceiling. The
  pool's lifecycle is directly tested before the larger profile is promoted.
- **Reversibility**: Remove the pool, foundation tests, 10K profile/test,
  artifact, benchmark note, workflow selector, ADR, manifest entries, and
  execution records; lower grouped-matching tiers remain unchanged.
- **Verification**: Local PostgreSQL 16 run passes 10,000/10,000 partitions,
  24,000/24,000 rows, zero duplicate identities, zero failed/active runs, and
  200 completed runs per mode.

### D-297: Do not promote a PostgreSQL grouped-matching 10K tier after connection exhaustion
- **Date**: 2026-08-05
- **Context**: A disposable 10,000-partition grouped-matching probe failed
  after partial progress because the worker opens fresh PostgreSQL connections
  for each transaction phase and Windows reported `Address already in use`.
- **Decision**: Retain no 10K profile or workflow gate. Record the probe as a
  blocked engineering finding and require a separately reviewed connection
  lifecycle/pooling design before retrying a larger tier.
- **Rationale**: Publishing partial results would hide a reproducible resource
  exhaustion boundary and would misrepresent the current worker as scalable at
  that tier. The existing 500-partition correctness gate remains the allowed
  bounded wording.
- **Reversibility**: This is a documentation decision; a future pooling or
  bounded-reuse slice may supersede it with new tests and evidence.
- **Verification**: Probe failed closed at 304 runs/3,108 checkpoints/7,458
  result rows; no artifact or runtime claim was promoted.

### D-296: Add a PostgreSQL durable-job backpressure runtime gate
- **Date**: 2026-08-05
- **Context**: SQLite had a producer-cap profile, while PostgreSQL had load,
  retry, and contention gates but no runtime proof that the bounded-submit cap
  holds while independent PostgreSQL workers drain each lane.
- **Decision**: Add `postgres-durable-job-load/backpressure-tier-v1` with eight
  workers, four producer lanes, 64 jobs, four partitions per job, and a
  four-job queued/retrying cap per tenant/workspace/entity lane. Keep it
  synthetic, non-provider, and skipped without a configured live DSN.
- **Rationale**: This exercises atomic cap enforcement, retry-without-mutation,
  forced-RLS isolation, lease fencing, checkpoint/effect commits, and queue
  drain on the real PostgreSQL adapter without turning one-host timing into a
  capacity claim.
- **Reversibility**: Remove the profile, tests, workflow selector, benchmark
  note/artifact, ADR, manifest entries, and execution records. Existing
  durable-job runtime and lower profiles remain unchanged.
- **Verification**: Local disposable PostgreSQL run passes 64 jobs/256 effects
  with maximum queue depth four, 12 rejected attempts, zero duplicates/residue,
  and 16 completions per lane. Hosted evidence is intentionally pending until
  the owner authorizes the deferred GitHub publication.

### D-295: Register connector boundaries as an evidence-bounded module
- **Date**: 2026-08-05
- **Context**: Connector implementations had individual contracts but no
  first-class runtime module, maturity ceiling, or threat-model parity.
- **Decision**: Add `connectors.boundary` with explicit interfaces,
  import/export contracts, data classifications, test evidence, activation and
  retention boundaries, and a matching threat-model entry. Keep it experimental
  and foundation-stage with no migration or default network activation.
- **Rationale**: Registry parity prevents connector claims from escaping the
  same governance controls used by finance, inventory, and workflow modules.
  It improves discoverability without mislabeling provider-neutral code as a
  live ERP/bank integration.
- **Reversibility**: Remove the descriptor, threat entry, maturity ceiling,
  ADR, manifest entry, tests, and execution records; connector code remains.
- **Verification**: Registry, threat-model schema/parity, and maturity tests
  pass with eleven active modules.

### D-294: Add a bounded offline CAMT.053 statement boundary
- **Date**: 2026-08-05
- **Context**: Banking statement formats are required for the connector
  workstream, but a provider-neutral file parser must not be presented as a
  live bank integration or payment capability.
- **Decision**: Add one read-only CAMT.053 `BkToCstmrStmt/Stmt` parser with
  `defusedxml`, an 8 MiB payload limit, a 100,000-entry limit, bounded text,
  exact finite Decimal strings, stable entry/service references, explicit
  booking/value dates, opening/closing balances, and a deterministic digest.
  Expose it only through the local `parse-camt053` CLI and a closed JSON Schema.
  Add a local projection into the existing bounded payment-statement page model,
  preserving signed line identity and source references with an offset cursor.
- **Rationale**: This creates a useful banking vertical input contract and
  replayable evidence while preserving fail-closed XML, identity, date, and
  amount semantics. It does not invent provider credentials, transport,
  payment initiation, ERP mapping, or write-back semantics.
- **Reversibility**: Remove the parser, schema, fixture, CLI command, tests,
  manifest entries, ADR, and execution records; existing connector SDK
  contracts remain unchanged.
- **Verification**: Focused CAMT.053 and connector integration tests pass
  locally; hosted provider interoperability remains unverified.

### D-293: Publish a PostgreSQL durable-job 100K-effect tier
- **Date**: 2026-08-05
- **Context**: The live PostgreSQL durable-job gate previously stopped at 10,000
  effects, while SQLite already had a bounded 100K tier.
- **Decision**: Publish `postgres-durable-job-load/100k-effects-v1` with 16
  independent workers, 2,500 jobs, forty partitions per job, and four
  forced-RLS tenant lanes. Keep the 10K and 256-effect profiles as compatibility
  tiers and require the same profile in hosted `server-boundaries`.
- **Rationale**: This increases PostgreSQL workload evidence while preserving
  deterministic job/effect/tenant invariants and the explicit rule that
  one-host timings are not capacity, SLO, HA/DR, or production-sizing claims.
- **Reversibility**: Remove the tier factory, live test, artifact/schema,
  benchmark note, manifest/workflow entries, and execution records; existing
  durable-job runtime and lower tiers remain unchanged.
- **Verification update**: Hosted CI `30970795278` / `server-boundaries`
  `92194440053` passed both the 10K and 100K live profile gates; the associated
  Security, Docker, CodeQL, HA/DR, and Docker-parity jobs are green.

### D-289: Persist intercompany elimination proposals as replay-verified evidence
- **Date**: 2026-08-05
- **Context**: The pure exact intercompany bridge had no server persistence, so
  a close operator could not retain a tenant/workspace-scoped replay artifact.
- **Decision**: Add migration `0063_pg_ic_elimination` and a PostgreSQL
  server-profile API that computes the proposal from typed source lines, stores
  immutable request/result JSONB and digests under forced RLS, and binds the
  authenticated preparer/workspace. Reads must replay before returning data.
  Keep the artifact explicitly non-posting.
- **Rationale**: This deepens close evidence without inventing statutory posting,
  FX, tolerances, provider semantics, or autonomous financial authority.
- **Reversibility**: Revert the API/adapter and use the data-loss-refusing
  migration downgrade only after an explicit retention decision.
- **Verification**: Hosted CI `30961377710` / `server-boundaries` job
  `92165832615` passed migration, forced-RLS scope, idempotent replay,
  sibling-tenant exclusion, and database immutability. The bounded parity
  inventory is promoted to `live_verified_current`.

### D-288: Require exact reciprocal evidence before intercompany elimination
- **Date**: 2026-08-05
- **Context**: Intercompany matching and consolidation worksheets were separate
  boundaries. Automatically inferring accounts, FX, or statutory treatment
  would turn incomplete source data into an unsafe financial effect.
- **Decision**: Add `intercompany-elimination-v1` as a pure, non-posting bridge.
  Require explicit reporting-currency signed Money, account mapping/type,
  reciprocal entity/counterparty coverage, and exact zero-sum Decimal balance.
  Emit a digest-bound negating `ConsolidationElimination` only for proven
  groups; retain all other groups as unresolved with a reason. Expose a
  read-only CLI and replay verifier over original typed lines.
- **Rationale**: The bridge improves close depth while preserving fail-closed
  financial correctness and the existing worksheet's explicit approval/posting
  boundary.
- **Boundary**: Local synthetic evidence only; no statutory/legal-book posting,
  live FX/provider semantics, persistence parity, write-back, HA/DR, or
  production readiness.
- **Reversibility**: Remove the additive domain/application/CLI surfaces and
  retain existing intercompany matching and worksheet contracts.
- **ADR**: `docs/adr/0333-intercompany-elimination-proposals-are-exact-and-nonposting.md`.

### D-287: Keep signed-package admission CLI read-only and digest-only
- **Date**: 2026-08-04
- **Context**: Operators need a reproducible local check without turning a
  signed manifest envelope into an installer or executable plugin loader.
- **Decision**: Add `reconforge connectors verify-package` with explicit public
  key inputs; invoke trust-plus-conformance admission and emit only the
  digest-bound result. Invalid trust/signature/conformance exits non-zero.
- **Rationale**: A narrow CLI makes owner/team testing repeatable while
  preserving the no-network, no-code-loading boundary.
- **Boundary**: Local data-only package evidence; no provider or marketplace
  claim.
- **Reversibility**: Disable the command without deleting package evidence.
- **ADR**: `docs/adr/0332-signed-package-admission-cli.md`.

### D-286: Require connector package conformance after signature verification
- **Date**: 2026-08-04
- **Context**: Ed25519 envelope verification authenticated publishers, but did
  not itself prove the signed manifest satisfied the connector safety contract.
- **Decision**: Add a data-only admission helper that verifies one trust source,
  runs the existing read-only manifest conformance gate, and binds trust,
  manifest, signature, and admission digests. No executable package loading is
  permitted.
- **Rationale**: Trust and capability conformance are independent controls;
  combining them at an explicit boundary prevents signature-only promotion.
- **Boundary**: Synthetic manifest/package evidence only; no live provider,
  write-back, or marketplace claim.
- **Reversibility**: Additive helper; disable package admission without
  deleting envelope evidence.
- **ADR**: `docs/adr/0331-signed-connector-package-admission.md`.

### D-285: Keep compensation dispatch server-only and payload-resolver bound
- **Date**: 2026-08-04
- **Context**: Compensation request and provider-neutral transport existed,
  but exposing a browser-supplied reversal payload would violate the secret and
  financial-data boundary, while persisting before acknowledgement could claim
  a reversal that never occurred.
- **Decision**: Add a privileged server-profile dispatch route that obtains
  bytes from an explicit short-lived in-memory resolver, verifies a caller-bound
  SHA-256 digest, delegates transport safeguards, and appends `compensated` only
  after accepted acknowledgement. Local mode remains network-disabled.
- **Rationale**: Provider side effects need an operator-configured payload
  boundary and an append-only acknowledgement gate; the API must not become a
  generic financial-payload upload surface.
- **Boundary**: Synthetic/injected provider and hosted server-identity gate;
  no live vendor, accounting posting, or production claim.
- **Reversibility**: Disable the server profile or connector registration;
  retain intent evidence and migrate forward.
- **ADR**: `docs/adr/0330-governed-writeback-compensation-dispatch-api.md`.

### D-284: Expose compensation requests as a separately permissioned, scoped API transition
- **Date**: 2026-08-04
- **Context**: Provider-neutral compensation transport existed, but no API
  boundary recorded the authenticated requester or guarded stale lifecycle
  transitions.
- **Decision**: Add a dedicated human permission and actor-bound,
  tenant/workspace-scoped, optimistic-versioned compensation-request endpoint.
  Persist reason, actor, and UTC time; allow only exact immediate replay; keep
  provider execution separate.
- **Rationale**: A reversal trail must be attributable and race-safe without
  granting the API implicit network or accounting authority.
- **Boundary**: Local SQLite migration and synthetic API/repository contracts;
  PostgreSQL permission provisioning remains tenant-administered under RLS;
  live provider semantics and production assurance are not inferred.
- **Reversibility**: Additive route, permission, and JSON metadata; retain
  append-only evidence and migrate forward rather than deleting history.
- **ADR**: `docs/adr/0329-governed-writeback-compensation-request-api.md`.

### D-281: Promote PostgreSQL grouped portfolio fees and residuals only through a bounded runtime gate
- **Date**: 2026-08-03
- **Context**: The pure grouped strategy supported fee-aware netting and
  explicitly enabled partial settlement inside a non-overlapping portfolio,
  while the PostgreSQL worker had only live evidence for exact same-currency
  and FX groups.
- **Decision**: Add one synthetic portfolio run with exact Decimal fees,
  `netting_mode: net`, and `allow_partial_settlement: true`; require persisted
  residual/settled lineage and direct portfolio digest parity before counting
  the worker boundary.
- **Rationale**: This closes a concrete server-side replay gap for a common
  statement/ledger settlement shape without conflating a proposal with an
  external settlement or statutory posting.
- **Boundary**: Single-node PostgreSQL CI evidence only. Live providers,
  posting, external acknowledgement, scale/soak/backpressure, HA/DR, and
  statutory accounting treatment remain open.
- **Reversibility**: Test and documentation only; no schema or runtime
  behavior change.
- **ADR**: `docs/adr/0288-postgres-grouped-portfolio-partial-runtime-evidence.md`.

### D-282: Exercise same-tenant PostgreSQL job claim contention without widening scale claims
- **Date**: 2026-08-03
- **Context**: The durable-job PostgreSQL gate covered two tenant lanes but used
  one worker per tenant, leaving same-tenant claim ownership under contention
  untested.
- **Decision**: Add four synthetic jobs with three partitions each and drain
  them with two independent worker connections. Require terminal completion and
  exact per-job effect cardinality before counting the boundary.
- **Rationale**: This directly tests the database lease/claim boundary and
  duplicate-effect invariant while keeping the workload bounded and synthetic.
- **Boundary**: No throughput, fairness SLO, soak, distributed supervision,
  queue HA, automatic failover, or production-readiness claim follows.
- **Reversibility**: Test and documentation only; no migration or public API
  behavior changes.
- **ADR**: `docs/adr/0289-postgres-durable-job-claim-contention-runtime.md`.

### D-283: Bind verified HA/DR status to multiple observed failure domains
- **Date**: 2026-08-03
- **Context**: The HA/DR profile already required all verification booleans for
  `verified`, but did not require the observed topology to contain more than
  one failure domain.
- **Decision**: Require `observed.failure_domains >= 2` whenever status is
  `verified`, with a regression test for the all-true/one-domain case.
- **Rationale**: A verified HA claim must be structurally incapable of using a
  single-host measurement as independent-domain evidence.
- **Boundary**: Schema guard only; no host, quorum, failover, site-loss, or
  production-SLO execution is added.
- **Reversibility**: Additive schema constraint and test; the current partial
  profile remains backward compatible.
- **ADR**: `docs/adr/0290-ha-dr-verified-profile-requires-independent-domains.md`.

### D-284: Keep sequential matching provider-neutral until the PostgreSQL gate passes
- **Date**: 2026-08-03
- **Context**: Carry-forward FIFO and reversal pairing had deterministic local
  strategies but no hosted worker adapter or persisted lineage contract.
- **Decision**: Add a persistence-free adapter with explicit modes and reuse the
  existing PostgreSQL worker result/exception schema. Require a live synthetic
  server-boundary run and direct strategy digest parity before promoting it in
  the PostgreSQL parity inventory.
- **Rationale**: This extends advanced matching without introducing a second
  persistence protocol or silently turning experimental strategies into posting
  or write-back behavior.
- **Boundary**: Local evidence is complete for this slice; live PostgreSQL,
  posting, write-back, scale, HA/DR, and production readiness remain open until
  the runtime gate passes.
- **Reversibility**: Additive adapter, test, and documentation; no migration or
  existing mode behavior changes.
- **ADR**: `docs/adr/0291-postgres-sequential-matching-runtime-evidence.md`.

### D-264: Bounded PostgreSQL durable-job concurrency parity
- **Date**: 2026-08-03
- **Context**: Existing high-volume evidence is SQLite-only, while the
  PostgreSQL worker contract had no concurrent multi-tenant load assertion.
- **Decision**: Add a small live server-boundaries workload with two tenant
  lanes, three jobs per lane, and two partitions per job, each lane using a
  separate PostgreSQL connection.
- **Rationale**: This directly exercises PostgreSQL claim/checkpoint/effect
  behavior without converting a small synthetic run into a capacity or SLO
  claim.
- **Reversibility**: Test and documentation only; no migration or runtime
  behavior changes.

### D-265: Connector retry failure injection is a reusable synthetic gate
- **Date**: 2026-08-03
- **Context**: Network connector retry behavior was covered by individual
  tests but lacked one reusable conformance boundary for failure injection.
- **Decision**: Add a provider-neutral helper that injects bounded retryable
  statuses through a caller-owned executor, requires eventual success within
  the declared ceiling, and verifies that transient response bodies cannot
  leak into the successful result.
- **Rationale**: Shared failure semantics reduce drift across REST, ERP, and
  payment-statement references without pretending that synthetic transport is
  a live provider sandbox.
- **Reversibility**: Additive helper and tests only; no network, schema, or
  credential behavior changes.

### D-266: Consolidation certification attaches only to replay-verified posted runs
- **Date**: 2026-08-03
- **Context**: The close lifecycle had immutable posting/reversal effects but
  no API-visible certification step bound to their final state.
- **Decision**: Reuse the existing local certification record for
  `consolidation_close_run`, permit preparation only for `Posted`/`Reversed`
  runs, require separate management/validation plus approval permissions, and
  replay-verify the run on reads.
- **Rationale**: Certification must describe an immutable financial-control
  result without becoming a source-ERP journal, legal signature, or silently
  certifying an unposted worksheet.
- **Reversibility**: Additive repository methods and API routes; existing run
  states and certification records remain backward compatible.

### D-267: PostgreSQL certification reuses the tenant-scoped certification repository
- **Date**: 2026-08-03
- **Context**: Local posted-run certification existed, while PostgreSQL close
  runs had no backend-neutral certification parity.
- **Decision**: Add certification methods to the PostgreSQL close adapter. Lock
  and replay-verify the run inside the tenant transaction, then use the
  existing RLS `PostgresApprovalRepository` for certification persistence and
  maker-checker review.
- **Rationale**: Reusing the established certification triggers, RLS, audit,
  and outbox boundary avoids a second certification schema and preserves exact
  backend semantics.
- **Reversibility**: Additive adapter methods and live tests; no migration or
  existing run-state change.

### D-293: Local Delegations Are Immutable and Tenant-Scoped
- **Date**: 2026-08-02
- **Context**: Expiring delegation evaluation needs durable administration evidence without hidden wall-clock or cross-tenant lookup behavior.
- **Decision**: Store grants in migration 27 with immutable identity/scope/permission/approval fields. Permit only an independent active-to-revoked transition; effective reads require tenant, workspace, and explicit timezone-aware evaluation time.
- **Rationale**: The record can be replayed and audited, and revocation cannot silently rewrite the approved authority.
- **Reversibility**: Additive local migration with linear rollback through the existing database backup/restore process; no provider contract change.

### D-294: Promote Durable Jobs Only Through a Live PostgreSQL Gate
- **Date**: 2026-08-02
- **Context**: The durable-job adapter had a live-test contract but was not counted as current PostgreSQL parity.
- **Decision**: Promote the application and worker boundaries only after the pinned CI PostgreSQL service exercises concurrency, idempotency, lease recovery, partition effects, stale-worker refusal, and reconnect resume under a non-privileged role.
- **Rationale**: This provides stronger evidence for the high-volume workstream without widening a single-node result into HA or scale claims.
- **Reversibility**: Inventory status and documentation only; no schema or runtime behavior change.

### D-295: Promote Intercompany Only as a Control Workflow
- **Date**: 2026-08-02
- **Context**: The PostgreSQL intercompany adapter had an unskipped server-boundary contract but was not counted as current parity.
- **Decision**: Promote only the exact import/match/exception/settlement workflow with RLS and SQLite parity; retain explicit exclusions for statutory consolidation and posting.
- **Rationale**: It strengthens the close foundation without conflating an operational control case with legal-accounting treatment.
- **Reversibility**: Inventory and documentation status only.

### D-296: Gate the Reference Connector Portfolio as One Read-Only Contract
- **Date**: 2026-08-02
- **Context**: Five provider-neutral reference manifests had individual tests but no shared portfolio-level invariant.
- **Decision**: Require every reference manifest to pass common read-only, synthetic/idempotent, schema/threat, secret-reference, and egress checks before counting the SDK slice.
- **Rationale**: A single deterministic contract prevents one adapter from silently weakening the SDK safety boundary.
- **Reversibility**: Additive conformance function and tests only; no provider or network behavior change.

### D-297: Keep Governed Job Authorization Explicit and Opt-In
- **Date**: 2026-08-02
- **Context**: Durable jobs have internal lifecycle correctness but callers need a shared deny-before-mutation policy boundary.
- **Decision**: Add a typed wrapper requiring policy context and explicit permission for submit/cancel while preserving the existing lifecycle service for callers with separate authorization.
- **Rationale**: Explicit adoption avoids silently weakening compatibility while making the safe path testable and auditable.
- **Reversibility**: Additive application class and tests; no schema change. The
  PostgreSQL runtime promotion is recorded separately in ADR 0249.

### D-299: Add ERP as a Read-Only Reference Connector
- **Date**: 2026-08-03
- **Context**: The connector portfolio covered generic REST and payment statements but had no ERP-specific financial page contract.
- **Decision**: Add a provider-neutral entity-scoped ERP ledger-line connector using the existing read-only HTTPS executor. Keep write-back, vendor credentials, and live provider claims outside the reference package.
- **Rationale**: An ERP-shaped exact Decimal contract makes the SDK useful for integration testing without confusing an export profile or synthetic endpoint with a live connector.
- **Reversibility**: Additive module, manifest, documentation, and tests only; no schema or network default changes.

### D-300: Publish HA/DR Targets Without Widening the Failure-Domain Claim
- **Date**: 2026-08-03
- **Context**: The repeated PostgreSQL synchronous-standby drill has measured single-host results, but operators need one machine-readable profile connecting those results to targets and a runbook.
- **Decision**: Publish a `partial` operational profile with zero acknowledged-transaction-loss and 60-second failover/failback targets, bound to the retained report and explicit limitations.
- **Rationale**: Operators can reproduce and review the bounded drill without mistaking one-host evidence for independent-domain HA or production SLO evidence.
- **Reversibility**: Additive schema, profile, and tests only; no database or deployment behavior changes.

### D-301: Make Policy Caching Opt-In and Allowed-Only
- **Date**: 2026-08-03
- **Context**: Enterprise deployments need bounded decision caching, but stale grants or cross-tenant keys could weaken deny-by-default.
- **Decision**: Add a bounded cache that includes the full policy context and policy version in its key, stores only allowed non-delegated decisions, and requires explicit tenant/workspace/global invalidation. Do not enable it implicitly in existing routes.
- **Rationale**: Adoption can be wired beside each mutation authority and audited without making cache freshness an invisible security dependency.
- **Reversibility**: Additive module and tests only; current callers remain uncached.

### D-302: Persist PostgreSQL Delegations as Immutable RLS-Scoped Grants
- **Date**: 2026-08-03
- **Context**: Temporary delegation evaluation was durable only in Community SQLite, leaving the enterprise identity boundary without a PostgreSQL representation.
- **Decision**: Add a linear PostgreSQL migration and repository with forced tenant RLS. Database triggers reject deletes and all field changes except an independent active-to-revoked transition; effective reads always bind tenant, workspace, and an explicit instant.
- **Rationale**: Authority history must remain replayable and tenant-isolated even when the application role is non-privileged. The contract stays additive until a live CI gate proves the migration and adapter together.
- **Reversibility**: Downgrade refuses to discard retained rows; migration and repository are additive and can be retired through an evidence-preserving backup/restore process.

### D-303: Make API Policy Caching Explicit and Mutation-Invalidated
- **Date**: 2026-08-03
- **Context**: The bounded decision cache was safe in isolation but had no adopted API path or freshness rule.
- **Decision**: Add an opt-in API setting and use the cache for all/any permission dependencies only when enabled. Invalidate the instance cache after every non-safe HTTP request, including failed mutations; keep the default disabled.
- **Rationale**: This provides a reversible performance path without allowing stale authorization decisions to survive an API mutation or changing existing deployments silently.
- **Reversibility**: Set `policy_cache_enabled=False`; no schema or client contract migration is required.

### D-304: Keep the Consolidation Trial-Balance Projection Non-Statutory
- **Date**: 2026-08-03
- **Context**: Close review needs a deterministic, explainable projection without silently presenting the worksheet as regulated financial reporting.
- **Decision**: Add a pure management trial-balance artifact over verified non-posting worksheets with exact amounts, source references, a zero balance, and a canonical digest; create no posting effect.
- **Rationale**: This advances close explainability while preserving boundaries around statutory presentation, accounting judgments, persistence parity, and external write-back.
- **Reversibility**: Additive domain module, schema, docs, and tests only; no database or source-system mutation.

### D-305: Separate Field Authorization from Field Masking
- **Date**: 2026-08-03
- **Context**: Enterprise policy needs field-level deny-by-default and safe redaction without treating a redacted value as permission.
- **Decision**: Add explicit requested/authorized field sets to central evaluation and a separate allowlisted projection primitive that masks only authorized fields and records deterministic evidence.
- **Rationale**: The separation prevents accidental disclosure and makes route-by-route migration auditable while preserving compatibility for callers that do not request field scoping.
- **Reversibility**: Additive policy fields and pure helper; callers can omit field sets and no existing route behavior changes.

### D-306: Persist Write-Back Intent History Append-Only
- **Date**: 2026-08-03
- **Context**: The provider-neutral write-back lifecycle had approval and acknowledgement contracts but no durable local history for retries, operator review, or replay.
- **Decision**: Add migration 28 and an append-only SQLite repository keyed by intent/version and tenant/workspace. Store only canonical intent JSON and digest; require optimistic versions and an explicit allowed transition; keep payloads, credentials, and network dispatch outside the repository.
- **Rationale**: Durable immutable history makes retries and compensation auditable without mutating a financial source or silently enabling external writes.
- **Reversibility**: The migration is additive; disable the repository path and retain the backup before any future provider adapter is enabled.

### D-307: Expose Write-Back Proposals Without Dispatch
- **Date**: 2026-08-03
- **Context**: Durable intents existed as a library boundary but had no authenticated operator surface.
- **Decision**: Add a permissioned local POST route that persists only a closed proposal, binds the actor, supports idempotent replay, and explicitly disables network dispatch.
- **Rationale**: Operators can create auditable proposals without silently turning the local deployment into an external mutation client.
- **Reversibility**: Remove or disable the route and permission; no provider credentials, source-system state, or external network behavior is introduced.

### D-308: Keep Write-Back Approval Separate from Proposal
- **Date**: 2026-08-03
- **Context**: Proposal persistence now had an authenticated API, but approval needed a distinct permission and maker-checker path.
- **Decision**: Add migration 29 and a separate approval endpoint that loads the scoped immutable intent, requires a distinct actor, validates the lifecycle/version, and appends the approved version without dispatch.
- **Rationale**: Separation of proposal and approval prevents self-approval and makes the future provider mutation gate auditable.
- **Reversibility**: Disable the approval route/permission; no external provider state is changed.

### D-309: Enforce Durable-Job Backpressure Inside the Submission Transaction
- **Date**: 2026-08-03
- **Context**: The existing backpressure benchmark polled queue depth outside
  the repository, so concurrent producers could overrun a declared cap and
  idempotent retries had no explicit full-queue behavior.
- **Decision**: Add an additive bounded submission contract. Count `queued` and
  `retrying` work in the `(tenant_id, workspace_id, entity_id)` lane, resolve
  identical idempotency before the cap, and reject only new work at capacity.
  SQLite serializes with `BEGIN IMMEDIATE`; PostgreSQL serializes with a
  transaction-scoped lane advisory lock under forced RLS.
- **Rationale**: The invariant belongs at the persistence boundary, where the
  count and insert can be atomic and backend parity can be tested without
  adding a queue vendor or weakening existing submit compatibility.
- **Boundary**: No global quota, distributed fairness SLO, throughput, soak,
  HA/DR, or production-capacity claim follows from this bounded primitive.
- **Reversibility**: Additive API/repository methods only; callers can stop
  using `submit_bounded` without a migration or data rewrite.
- **ADR**: `docs/adr/0292-atomic-durable-job-backpressure.md`.

### D-292: Delegated Authority Requires an Explicit Evaluation Instant
- **Date**: 2026-08-02
- **Context**: Enterprise policy needs expiring delegation without hidden wall-clock behavior that makes decisions non-replayable.
- **Decision**: Carry a delegation ID, timezone-aware expiry, and caller-supplied evaluation instant in `PolicyEvaluationContext`; deny missing evaluation time and deny at/after expiry with stable reason codes.
- **Rationale**: The decision is deterministic and auditable while preserving compatibility for callers without delegation.
- **Reversibility**: Optional context fields only; no migration or provider contract changes.

### D-290: PostgreSQL Consolidation Close Is a Control-Journal Boundary
- **Date**: 2026-08-02
- **Context**: SQLite already carries the governed consolidation-close lifecycle, while PostgreSQL parity was absent.
- **Decision**: Add a tenant-scoped PostgreSQL JSONB adapter with explicit lifecycle state, RLS, optimistic versions, maker-checker separation, and immutable effect records. Keep it `contract_only` until an unskipped CI runtime gate proves the adapter against the migration.
- **Rationale**: This closes the persistence boundary without falsely claiming statutory posting, ERP write-back, HA/DR, or production readiness.
- **Reversibility**: Migration is linear and has an explicit downgrade that removes only the new control-journal tables.

### D-207: Access Changes Use Exact Sets and Never Restore Revoked Authority
- **Date**: 2026-07-30
- **Context**: The authoritative access API supports role creation, exact permission replacement, exact user-role replacement, retirement, and reactivation. Additive-looking checkbox UX can accidentally preserve authority unless current selections and exact replacement semantics are explicit.
- **Decision**: Treat checked permissions and roles as the complete requested set, preload current assignments, and require the operator to explicitly remove anything no longer authorized. Reload all access, identity, and session views after every write. Keep retired roles visible for reactivation; reactivation never restores assignments or sessions. Hide current-operator assignment controls and retain server last-manager protection.
- **Rationale**: Exact sets make the requested authority reproducible and auditable. Non-restoration prevents a retired policy from silently regaining users or authenticated sessions when reactivated.
- **Reversibility**: Front-end/client-contract change only; no API, schema, migration, audit, or authentication change.

### D-206: User Status Changes Preserve Revoked Sessions and Server Authority
- **Date**: 2026-07-30
- **Context**: The PostgreSQL identity service already atomically disables a user, revokes every active session, appends audit evidence, prevents self-disable and last-administrator loss, and supports re-enable without restoring sessions.
- **Decision**: Expose only this existing status transition in the browser. Require the current step-up and CSRF boundary, exact `DISABLE` or `ENABLE` confirmation, and the lifecycle version. Hide the current operator's disable control, but retain all server guards. After mutation, replace only the closed returned user and reload sessions from the authoritative API; never infer session state or restore revoked sessions.
- **Rationale**: Identity recovery and access removal must follow the same server transaction and lifecycle evidence as API clients. Treating re-enable as a new eligibility state rather than undoing revocation prevents silent session resurrection.
- **Reversibility**: Front-end/client-contract change only. No API, database, migration, audit, authentication, or bearer compatibility change.

### D-205: Browser Mutation Starts With One Explicitly Confirmed Session Revocation
- **Date**: 2026-07-30
- **Context**: The PostgreSQL identity lifecycle API already supports optimistic, audited single-session revocation, while broader browser mutations (user status, roles, integrations, and retention) have materially different consequences and unproved interaction paths.
- **Decision**: Expose only active-session revocation first. Require `users.manage`, the existing human step-up and cookie-bound CSRF proof, a closed reason code, the exact literal `REVOKE`, and the server lifecycle version. Accept only the closed response, do not disclose its audit-event identifier or session digest, and clear local privileged state if the current session was revoked.
- **Rationale**: This creates a narrow, reversible browser write vertical slice with explicit operator intent, stale-state protection, audit evidence, and a verifiable sign-out consequence without implying that broader identity or policy administration is safe to expose.
- **Reversibility**: Front-end/client-contract change only. The existing API, persistence, audit event, migration, and bearer compatibility remain unchanged; the control can be removed without data migration.

### D-204: Server Cookie Sessions Bind the Same Request Principal as Bearer Sessions
- **Date**: 2026-07-30
- **Context**: The PostgreSQL server middleware eagerly bound a `ServerPrincipal` only for Bearer credentials. Browser-cookie authentication could validate in a dependency but did not provide that context to synchronous step-up handlers, causing a real same-origin browser session to fail despite valid credentials.
- **Decision**: Resolve the host-only browser session cookie in the server middleware after Bearer precedence, bind the resulting principal and transport to the request, and preserve CSRF enforcement in `get_current_user` whenever the bound transport is a browser cookie.
- **Rationale**: A cookie session must be authorization-equivalent to the declared Bearer session without becoming a CSRF bypass. Request-level binding also prevents sync/async execution-context differences from silently removing the authenticated human principal.
- **Reversibility**: Source-only compatibility fix. Bearer precedence, local mode, cookie attributes, API schemas, and database migrations remain unchanged.

### D-203: Governance Metadata Is Read Before It Can Disable or Extend Retention
- **Date**: 2026-07-30
- **Context**: Integration disable and retention-policy APIs have immediate or monotonic operational consequences, while their browser disclosure and interaction boundaries had not yet been proved.
- **Decision**: Present only independently authorized, closed-contract integration and retention metadata. Do not expose disable, policy lifecycle, or evidence-retention application controls until each has a tested confirmation, reason, optimistic conflict, audit, and retained-floor interaction.
- **Rationale**: Read visibility does not justify operational authority. Keeping the browser surface read-only prevents accidental connector disruption or retention-state changes before an accountable human workflow is proved.
- **Reversibility**: Fully reversible front-end/documentation slice; no API, persistence, migration, provider call, or financial calculation changes.

### D-202: Access Policy Is Read Before It Is Mutable in the Browser
- **Date**: 2026-07-30
- **Context**: Server-side role lifecycle APIs are optimistic, audited, and session-revoking, but the browser had no proof that it could safely present a closed policy read model without coupling distinct permissions or exposing extra state.
- **Decision**: Add only separately authorized, read-only role and permission snapshots. Reject expanded responses and isolate access-read failure from other administration views. Defer all role/permission/user-role mutations until their full authorization, confirmation, conflict, session invalidation, and audit-evidence interactions are testable together.
- **Rationale**: Privileged policy changes require stronger proof than a list view; making a write button visible before that proof would weaken the human-governed control boundary.
- **Reversibility**: Fully reversible front-end/documentation slice; no API, persistence, migration, or financial calculation changes.

### D-201: Identity Read Model Remains Separate From Lifecycle Mutation
- **Date**: 2026-07-30
- **Context**: The server exposes optimistic, audited identity and session lifecycle writes, but the browser administration surface had not yet proved its read authorization, disclosure boundary, or accessibility behavior.
- **Decision**: Add only independently authorized read-only user/session snapshots to the authenticated page. Their exact response contracts are rejected on disclosure expansion, and their failure does not gate audit or Security Center reads. Defer every identity, session, and role mutation until its confirmation, conflict, session-revocation, and audit-evidence UX can be tested as one vertical slice.
- **Rationale**: A browser UI must not make privileged lifecycle changes merely because an API exists; read authorization and redaction are separate security boundaries that need proof first.
- **Reversibility**: Fully reversible front-end/documentation slice; no API, persistence, migration, or financial calculation changes.

### D-200: Security Snapshot Must Not Broaden or Gate Audit Disclosure
- **Date**: 2026-07-30
- **Context**: The Security Center endpoint has a distinct `security.center.read` permission and a declared count-only, non-assurance response. Reusing its result as an audit prerequisite or tolerating extra browser fields would create an authorization and disclosure coupling not present in the server contract.
- **Decision**: Validate the complete browser response as a closed contract, including digest shapes and the audit-verification boundary literal. Request the snapshot after audit authorization succeeds, but isolate its failure from the independently authorized audit view; render only an allowlisted count summary and explicit attention items with the server's non-assurance boundary.
- **Rationale**: Least privilege requires independent permissions to remain independent. Closed client validation prevents accidental presentation of newly disclosed fields before a reviewed UI and server contract change.
- **Reversibility**: Fully reversible front-end/documentation slice; no API, persistence, migration, or financial calculation changes.

### D-191: Deterministic Timezone Schedule v1
- **Date**: 2026-07-29
- **Context**: Scheduler correctness requires explicit DST, misfire, cursor, and occurrence-identity semantics before persistence or external effects.
- **Decision**: Start with a closed daily/weekly IANA-timezone contract, explicit gap/ambiguity handling, three bounded misfire policies, review-boundary refusal, and digest-addressed occurrences.
- **Rationale**: The same schedule version and cursor must produce the same dispatch identities without depending on host local time or an underspecified cron parser.
- **Reversibility**: Fully reversible before a persistence migration; this slice has no call sites or network effects.
- **ADR**: `docs/adr/0191-deterministic-timezone-schedule-v1.md`.

### D-190: Runtime Schema Installers Cannot Weaken Composed RLS
- **Date**: 2026-07-29
- **Context**: PostgreSQL permissive policies compose with OR, so re-adding tenant-only `tenant_isolation` beside migrated `tenant_scope` bypassed workspace restrictions.
- **Decision**: All 12 current business schema installers drop the compatibility policy and recreate it only when no composed `tenant_scope` exists; static and live regressions enforce the invariant.
- **Rationale**: Isolation must not depend on whether a compatibility installer runs before or after migration 0044.
- **Reversibility**: Reversible only for schemas predating composed RLS; weakening a current-head policy is not an allowed rollback.
- **ADR**: `docs/adr/0190-schema-installers-preserve-composed-rls.md`.

### D-189: API Scope Comes From Durable Principal Grants
- **Date**: 2026-07-29
- **Context**: Client hierarchy headers cannot be treated as authority, while tenant-only business transactions bypass workspace RLS.
- **Decision**: Migration 0046 stores immutable user/service-account scope grants; authentication snapshots them and every PostgreSQL business boundary requires an authorized workspace before opening its transaction.
- **Rationale**: Separating selector from authority prevents sibling header spoofing and accidental tenant-wide financial reads.
- **Reversibility**: Reversible through migration 0046 downgrade; Community/SQLite behavior is unchanged.
- **ADR**: `docs/adr/0189-api-scope-comes-from-durable-principal-grants.md`.

### D-001: Baseline-First Approach
- **Date**: 2026-07-24
- **Context**: Large prompt requests comprehensive transformation
- **Decision**: Complete full baseline audit before any code changes
- **Rationale**: Cannot improve what is not measured. Risk of breaking working code without understanding current state.
- **Reversibility**: Fully reversible (documentation only)

### D-002: Config amount_tolerance Float → Decimal (Planned)
- **Date**: 2026-07-24
- **Context**: `reconforge/config.py:47` declares `amount_tolerance: float = Field(default=2.0, ge=0)`. The matching engine converts this to Decimal at the boundary via `Decimal(str(config.amount_tolerance))`. While this works for common values, float representation can introduce subtle precision issues.
- **Decision**: Change `amount_tolerance` config field from `float` to a type that preserves exact decimal representation
- **Rationale**: Financial correctness principle — no float in any value that affects financial amounts. The config value propagates directly to matching tolerance comparisons.
- **Reversibility**: Reversible with config migration
- **Status**: IMPLEMENTATION PRESENT; current Ruff/Mypy/full-suite gates are not green

### D-003: Execution Documentation Location
- **Date**: 2026-07-24
- **Context**: Need persistent execution state tracking
- **Decision**: Use `docs/execution/` directory for all execution tracking files
- **Rationale**: Already partially exists in repo (`docs/execution/`). Keeps execution artifacts with the project.
- **Reversibility**: Fully reversible

### D-004: No Bulk Refactoring
- **Date**: 2026-07-24
- **Context**: cli.py is 247KB single file, enterprise_demo.py is 55KB
- **Decision**: Do NOT refactor large files in Phase 0. Focus on correctness first.
- **Rationale**: Large file refactoring carries regression risk. Current tests pass. Refactoring belongs in Phase 1 after baseline stability is confirmed.
- **Reversibility**: N/A (decision to defer)

### D-005: Explicit Repository Protocols
- **Date**: 2026-07-24
- **Context**: Domain repositories were coupled directly to SQLite connections, making database-neutral persistence testing and PostgreSQL implementation difficult to enforce statically.
- **Decision**: Formalize `typing.Protocol` contracts for domain repositories in `reconforge/domain/protocols.py` (`WorkspaceRepositoryProtocol`, `PeriodRepositoryProtocol`, `AuditEventRepositoryProtocol`).
- **Rationale**: Clean Architecture & Hexagonal Ports/Adapters pattern — domain services depend on abstract protocols rather than concrete database drivers.
- **Reversibility**: Fully reversible

### D-006: Central Policy Engine and API Contracts
- **Date**: 2026-07-24
- **Context**: Authorization logic and API pagination/idempotency handling were scattered across route functions and dependencies without a single source of evaluation truth.
- **Decision**: Create `CentralPolicyEngine` in `reconforge/auth/policy.py` for evaluating RBAC permissions, Segregation of Duties (SoD), ownership constraints, and add `get_idempotency_key` + `get_cursor_pagination` to `reconforge/api/dependencies.py`.
- **Rationale**: Single Responsibility Principle & Security-by-Default — centralized policy engine enforces 'Deny by default' and prevents self-approval paths.
- **Reversibility**: Fully reversible

### D-007: Evidence Graph and Reconciliation-as-Code Schemas
- **Date**: 2026-07-24
- **Context**: Audit evidence binders were stored as flat dictionaries, and reconciliation definitions lacked versioned YAML schema validation.
- **Decision**: Implement `EvidenceGraph` with node types and edge relations in `reconforge/evidence/graph.py`, `ReconciliationAsCodeSpec` in `reconforge/rules/recon_as_code.py`, and Arabic/RTL BIDI utilities in `reconforge/utils/rtl.py`.
- **Rationale**: Evidence Lineage & Reconciliation-as-Code principles — end-to-end SHA-256 graph manifest traceability and declarative YAML policy definition.
- **Reversibility**: Fully reversible

### D-008: Bind Baseline Evidence to the Dirty Worktree Snapshot

- **Date**: 2026-07-24
- **Context**: The active branch contains 11 commits over `origin/main`, while 112 tracked and 99 untracked files span several unfinished slices. Previous execution documents described gates as green even though current Ruff, Mypy, Pytest, and whitespace gates fail.
- **Decision**: Record Baseline evidence against the exact branch/commit plus dirty-worktree boundary. Do not attribute those results to `HEAD`, `main`, or a release, and do not create a broad commit merely to make the tree appear clean.
- **Rationale**: Financial and release evidence must be reproducible and honestly scoped. Preserving existing work is safer than destructive cleanup, while explicit snapshot boundaries prevent false claims.
- **Reversibility**: Fully reversible documentation decision; later isolated commits may establish cleaner evidence snapshots.

### D-009: Canonical Decimal Value, Not Lexical Scale, Defines Reconciliation Identity

- **Date**: 2026-07-24
- **Context**: The same generated amount was serialized as `2203.80` in one CSV and `2203.8` after a read/shuffle/write cycle. Both parse to the same Decimal value, but row fingerprints, match IDs, output amounts, and reconciliation signatures treated their lexical scales as different.
- **Decision**: Normalize finite Decimal values to a plain, scale-independent canonical string for stable row fingerprints and decision signatures. Emit matched amounts through strict `Money` construction so output precision follows the explicit currency registry.
- **Rationale**: Formatting is not a financial identity attribute. Equal amounts in the same currency must produce equal stable IDs and digests, while over-precise values continue to be rejected before matching.
- **Compatibility**: Existing finite-float ingress remains a boundary reader and is converted immediately to Decimal; no float arithmetic was added. Public output values remain numeric Decimal objects with currency precision.
- **Reversibility**: Reversible only with a versioned identity/digest migration after these IDs are published; changing it silently would break replay evidence.

### D-010: Unknown Currency Codes Fail Closed Under a Versioned Policy Snapshot

- **Date**: 2026-07-24
- **Context**: The initial registry silently created a two-minor-unit specification for any unknown code and existing `Money` values re-read mutable registry policy during later conversions.
- **Decision**: Install an offline versioned/digested currency-policy snapshot, reject unknown codes, capture resolved policy inside each `Money`, and permit only explicit bounded atomic file updates or process-local registration. ISO 4217 minor units and ReconForge rounding policy have separate provenance.
- **Rationale**: An invented precision or policy drift can change a financial decision without changing its source record. Captured policy and fail-closed resolution make the result explainable and replayable.
- **Compatibility**: Missing currency in the current stock/GL CSV contract still defaults to USD; a present unknown code is invalid. Legacy Money `{amount, currency}` serialization remains, with a richer canonical form added.
- **ADR**: `docs/adr/0030-versioned-currency-policy-registry.md`.
- **Reversibility**: Registry snapshots can be replaced/reset explicitly. Published canonical policy digests must not be changed without a versioned migration.

### D-011: Preserve Financial CLI Text Until Decimal Validation

- **Date**: 2026-07-24
- **Context**: Typer converted accounts materiality, journal high-value, and intercompany tolerance options to binary float before the Decimal application-service boundary, collapsing distinguishable user inputs.
- **Decision**: Keep option names/default meaning but accept their CLI representation as text and parse exactly once inside the existing financial validation boundary.
- **Rationale**: CLI parsing must not discard precision before business policy evaluation. String ingress also allows malformed/scientific input to become a controlled validation error rather than an altered number.
- **Compatibility**: Service methods continue accepting finite floats as legacy boundary inputs and immediately convert them through the strict parser; no database migration is needed because canonical Decimal text columns already exist.
- **Reversibility**: The option annotation is reversible, but restoring float parsing would reintroduce a proven decision-changing defect.

### D-012: Version Variance Threshold Policy Without Breaking Numeric Fields

- **Date**: 2026-07-24
- **Context**: Variance thresholds and summary readers crossed binary-float boundaries, but changing the existing JSON `thresholds` fields from numbers to strings would break the documented contract.
- **Decision**: Parse CLI and summary numeric lexemes exactly, use unrounded Decimal comparisons, publish report schema version 2 with a canonical digested `threshold_policy`, and retain the legacy threshold names/types by encoding Decimal directly as JSON number lexemes. Provide a reader for unversioned/v1 and v2 artifacts.
- **Rationale**: Financial decisions must not depend on binary approximation, while additive versioning and an explicit compatibility reader preserve local automation. Canonical strings give new consumers a portable exact representation; the retained numeric object avoids a forced migration for old consumers.
- **Compatibility**: Legacy finite-float service callers convert immediately through the strict parser. Existing `thresholds.amount_threshold` and `thresholds.percent_threshold` remain JSON numbers; v2-aware callers verify and use `threshold_policy`. No database migration is required.
- **ADR**: `docs/adr/0031-versioned-exact-variance-thresholds.md`.
- **Reversibility**: The v2 writer can be rolled back without losing v1 readability. Restoring float decisions is not a safe rollback.

### D-013: Separate Shareable Anonymized Output from Reversible Private Mapping

- **Date**: 2026-07-24
- **Context**: Amount noise still used float/random-uniform arithmetic and forced two decimals, while the default output included `anonymization_map.csv` with every original identifier beside its alias. Reusing an output folder could retain this or other stale sensitive files.
- **Decision**: Use versioned exact global Decimal noise with source-scale rounding; require new/empty output outside the input tree; replace the default raw map with a schema-v1 manifest containing policy/manifest/output digests and an explicit privacy boundary. Preserve the legacy `group,original,masked` CSV only through `--private-map-output` outside input/shareable output, never overwriting an existing path.
- **Rationale**: An intentional synthetic perturbation must still be exact and reproducible, and a reversible map cannot coexist with an output described as shareable. A global factor also preserves cross-file equalities that per-column noise broke.
- **Compatibility**: Exact CLI text replaces float parsing; finite-float service inputs remain a strict legacy reader. The private CSV shape is unchanged but its default location is intentionally removed for secure-by-default behavior. Existing non-empty outputs require operator review/move/cleanup; ReconForge does not delete them.
- **ADR**: `docs/adr/0032-exact-anonymization-and-private-mapping-boundary.md`.
- **Reversibility**: Operators can explicitly export the legacy map to a protected separate path. Restoring it inside the shareable default output or restoring float noise is not a safe rollback.

### D-014: Preserve Exact Studio Queries and Forbid Implicit Cross-Currency Report Totals

- **Date**: 2026-07-24
- **Context**: FastAPI converted Studio's minimum-amount query to binary float before Decimal comparison. The management pack could sum under the ambient Decimal context, apply a fixed two-place display, omit currency from matched rows, and label mixed-currency totals as `output_currency` despite having no FX policy.
- **Decision**: Preserve bounded plain-decimal query text through strict comparison; retain currency on matched rows; resolve one versioned report currency policy before output creation; reject differing explicit currencies; sum independently of ambient context; expose currency provenance and unquantified counts in schema-v1 report output.
- **Rationale**: Filtering and reporting must not invent equality, precision, zero amounts, or currency conversion. A report that cannot establish one aggregation currency must fail before creating artifacts.
- **Compatibility**: Existing route/metric names remain. Service-level finite-float filters are a legacy ingress reader only. Rows with no currency retain the legacy `output_currency` assumption, now disclosed in report policy metadata. New columns/root fields are additive.
- **ADR**: `docs/adr/0033-exact-studio-filters-and-currency-scoped-reports.md`.
- **Reversibility**: Additive metadata can be ignored by old readers; restoring float parsing or implicit cross-currency totals is unsafe.

### D-015: Version Synthetic Financial Values and Currency Policy

- **Date**: 2026-07-24
- **Context**: The synthetic generator used `random.uniform` binary floats for costs/mismatch factors, quantized all currencies to two decimals, parsed scenario rates as CLI floats, and emitted no algorithm/currency-policy/output identity.
- **Decision**: Introduce `exact-decimal-v1` integer-step Decimal draws, exact text rate ingress, registry-resolved currency precision, explicit currency columns on monetary datasets, LF-stable CSV output, and schema-v1 policy/manifest/output digests. Validate policy before target creation and preserve the eight-CSV return list.
- **Rationale**: Synthetic fixtures drive tests, demos, reconciliation, and benchmarks. Their financial semantics and byte identity must be reproducible and cannot invent two-decimal precision for JPY/KWD or hide an algorithm change.
- **Compatibility**: Existing generated CSVs remain readable. Regenerating the same old seed changes values because the former algorithm was unversioned; this intentional break is recorded. Finite-float library rate inputs remain a strict compatibility reader. The manifest is an additive ninth artifact.
- **ADR**: `docs/adr/0034-versioned-exact-synthetic-financial-generator.md`.
- **Reversibility**: Preserve historical artifacts/checksums when needed. Restoring the float algorithm as the default is unsafe; future generator changes require a new algorithm version.

### D-016: Make Evidence and Close Decisions Exact and Fail Closed

- **Date**: 2026-07-24
- **Context**: Evidence selection coerced scores through Pandas/float and could omit, zero, truncate, or crash on invalid data. Close readiness used float division and PostgreSQL converted readiness to float before the approval/lock comparison.
- **Decision**: Adopt evidence policy `integer-0-to-100-v1`, preserve malformed explicit scores as null-valued data-quality cases in schema-2 evidence, calculate readiness with exact two-decimal Decimal arithmetic from integer counts, and require exact `100.00` for PostgreSQL approval/locking.
- **Rationale**: These scores choose review evidence and authorize workflow state. Invalid data and near-boundary values must not be silently coerced into a decision.
- **Compatibility**: Valid score values, routes, close statuses, filenames, and two-decimal readiness presentation remain. Evidence schema-2 fields are additive for valid cases; malformed cases intentionally change from omission/zero/failure to visible null status. SQLite storage affinity is unchanged pending a separate migration.
- **ADR**: `docs/adr/0035-exact-control-decision-scores.md`.
- **Reversibility**: Historical schema-1 artifacts remain readable. Restoring silent zeroing, truncation, or float completion comparison is unsafe.

### D-017: Let the Trusted Database Schema Apply Restore Defaults

- **Date**: 2026-07-24
- **Context**: The backup bridge parsed omitted-column SQL defaults in Python, converting non-integer numeric text through binary float and treating some database expressions as literal values. Current exact financial defaults were not affected because they are integer/text, but the fallback was unsafe for future migrations.
- **Decision**: Build a parameterized insert column set per row, omit missing defaulted/nullable columns, and let the freshly created trusted SQLite schema apply its defaults. Keep strict failure for missing required no-default columns and validated/quoted allowlisted identifiers.
- **Rationale**: SQLite owns its default grammar and evaluation. A partial application parser cannot preserve every numeric/expression semantic and is unnecessary when omission invokes the declared default safely.
- **Compatibility**: Backup formats, commands, complete-row inserts, version checks, compatibility shims, and foreign-key/lifecycle verification remain. Backup data supplies values only and cannot supply SQL. Exact fractional defaults must be canonical quoted text or minor units.
- **ADR**: `docs/adr/0036-database-owned-restore-defaults.md`.
- **Reversibility**: Historical restored DBs remain usable. Restoring the float/default parser is unsafe.

### D-018: Make Governed Metric Text Canonical

- **Date**: 2026-07-24
- **Context**: Local governed metrics calculated count ratios and readiness through float and derived `value_text` from the approximate projection, despite already storing a separate text field.
- **Decision**: Calculate count-derived percentages and readiness averages with local-context Decimal arithmetic, make `value_text` canonical, retain `value REAL` as a compatibility projection, and fail closed on non-finite/out-of-range readiness. Validate/quantize SQLite aging output without claiming exact time aggregation.
- **Rationale**: Reviewer-facing control metrics need a deterministic representation, while existing numeric API/Studio readers require an additive migration path.
- **Compatibility**: Metric keys, routes, lineage, and numeric `value` remain. `value_text` formatting becomes explicit (`0.00` percentages, integer count text) and is the recommended reader boundary. No metric authorizes a close or financial decision.
- **ADR**: `docs/adr/0037-exact-governed-metric-values.md`.
- **Reversibility**: Legacy readers retain `value`; restoring float-derived canonical text is unsafe.

### D-019: Size DuckDB Work-Order Partitions with Integer Arithmetic

- **Date**: 2026-07-25
- **Context**: DuckDB bucket sizing converted record/work-order counts to float. A reproduced beyond-2^53 boundary returned seven buckets where exact ceiling arithmetic required eight.
- **Decision**: Calculate `ceil(target * work_orders / records)` with integer ceiling division and preserve existing lower/upper bounds and low-record fallback.
- **Rationale**: Batching is not financial arithmetic, but deterministic replay must not depend on binary integer precision or choose a different safeguard path for equal integer inputs.
- **Compatibility**: Matching rules, partition keys, results, and signature format remain. Some very-large-count batching changes intentionally; this is not a supported-volume claim.
- **ADR**: `docs/adr/0038-integer-duckdb-partition-sizing.md`.
- **Reversibility**: Restoring float ceiling arithmetic is unsafe.

### D-020: Version and Enforce Reconciliation Signature Financial Fields

- **Date**: 2026-07-25
- **Context**: The generic signature serializer did not assert the exact-value contract for `stock_amount`, `gl_amount`, or `value_difference`; changing it silently would also make historical digests uninterpretable.
- **Decision**: Keep explicit `reconciliation-signature-v1` for historical reproduction and make `reconciliation-signature-v2` the engine writer. V2 embeds its policy, rejects binary floating-point/boolean financial cells before null handling, canonicalizes finite Decimal/integer/plain text, and returns the policy beside the digest.
- **Rationale**: A deterministic digest must prove which canonicalization contract was applied and must not normalize invalid financial types into plausible evidence.
- **Compatibility**: The v1 golden digest is unchanged and opt-in. EngineResult gains one defaulted field. V2 intentionally changes digest values; confidence/reference suggestion scores remain non-financial compatibility values.
- **ADR**: `docs/adr/0039-versioned-strict-reconciliation-signatures.md`.
- **Reversibility**: Explicit v1 can reproduce historical evidence. Relabeling v1/v2 or restoring v1 as an implicit writer is unsafe.

### D-021: Introduce Strict and Legacy Financial Input Policies

- **Date**: 2026-07-25
- **Context**: Public amount helpers accepted finite Python/NumPy floating scalars through shortest-text conversion, but internal callers had no named strict alternative and could not prove that a financial lexeme had been preserved.
- **Decision**: Define warning `legacy-financial-input-v1` and rejecting current `strict-financial-input-v2` policies. Add strict parser entry points; migrate official dataset coercion, Decimal tolerance reads, and v2 signature text parsing; explicitly retain legacy PyYAML config compatibility.
- **Rationale**: Compatibility and correctness need separate, visible contracts. Internal exact paths should fail before binary values become plausible Decimal data, while existing callers receive a staged migration instead of an undocumented break.
- **Compatibility**: Existing parser defaults and finite-value results remain v1; accepted public v1 uses now issue a deprecation warning. File readers already produce text. Direct programmatic dataset coercion of floating scalars intentionally becomes data quality under strict v2.
- **ADR**: `docs/adr/0040-versioned-financial-input-policy.md`.
- **Reversibility**: Callers can explicitly select v1 during migration. Strict readers must not silently fall back; removing/changing the v1 default requires a breaking-release boundary.

### D-022: Persist Reconciliation Financial-Input Policy Per Run

- **Date**: 2026-07-25
- **Context**: Stock/GL and platform matching could select strict or compatibility parsing only through implicit call behavior, so persisted runs could not prove which input contract governed amounts.
- **Decision**: Add a typed policy to reconciliation results and matching rules; make current Engine/CLI/Studio/API writers strict v2; treat historical missing-policy rules as legacy v1; repeat local policy in rule, audit, outbox, JSON/Excel evidence; and forbid idempotency replay across policies. Management-pack output advances to schema v2 while the schema retains an explicit v1 compatibility branch.
- **Rationale**: Reproducibility requires the parser contract beside the rule and result. Compatibility must remain readable without relabeling historical evidence.
- **Compatibility**: Direct Python defaults remain legacy and warn. Historical PostgreSQL rules without a field remain legacy. New PostgreSQL API submissions require strict exact tolerance text semantics, and JSON binary numeric tolerances fail before queueing.
- **ADR**: `docs/adr/0041-version-reconciliation-ingress-policy-per-run.md`.
- **Reversibility**: An explicit writer may temporarily select legacy with recorded evidence, but policy omission, historical relabeling, cross-policy idempotency, and schema-v2-to-v1 downgrading are unsafe.

### D-023: Separate Canonical Duplicate Identity from Source Location

- **Date**: 2026-07-25
- **Context**: Duplicate-identical stock/GL rows shared match identity, and `source_row` had no cross-backend definition. Using row/query order as identity breaks replay, while deleting a known CSV row weakens diagnostics.
- **Decision**: Adopt `canonical-multiset-occurrence-v1`: hash non-internal canonical record fields, number equivalent copies as a stable output multiset, expose fingerprint/ordinal/count, and keep trusted source location as non-identity evidence. CSV/stock rows use one-based data position and header-offset row; JSON has position but no tabular row; hosted records without trusted location use explicit unavailable nulls. Signature v3 includes record identity and excludes mutable source location; v1/v2 remain replay formats. Current writers select the policy, historical missing-policy rules remain labeled legacy, idempotency cannot cross policies, and management-pack output advances to schema v3 with explicit v1/v2 compatibility branches.
- **Rationale**: Identical physical copies cannot be distinguished after permutation without intrinsic source identity. The correct invariant is a stable multiset of instance identifiers, not a false physical-copy claim.
- **Compatibility**: Existing single-record IDs and v1/v2 digests remain reproducible. Result lineage and EngineResult fields are additive. Duplicate match IDs and current management-pack schema intentionally change under named versioned contracts.
- **ADR**: `docs/adr/0042-versioned-multiset-record-identity.md`.
- **Reversibility**: Historical readers remain. Trusting caller-reserved fields, hashing source rows into decisions, relabeling historical evidence, or silently dropping occurrence identity is unsafe.

### D-024: Use a Pinned Derandomized Property-Test Engine

- **Date**: 2026-07-25
- **Context**: Fixed permutation regressions did not explore combinations of duplicate, invalid, and tied inputs; unseeded custom loops would drift and would not shrink failures.
- **Decision**: Pin official Hypothesis `6.161.2` in the dev extra only. Run three derandomized 35-example properties with no timing deadline over all stock/GL strategies, platform grouping modes, duplicates, invalid values, exact ties/tolerances, and source-row relocation.
- **Rationale**: Reproducible generation plus shrinking gives stronger deterministic evidence without making runtime installations depend on a test framework or conflating machine speed with correctness.
- **Compatibility**: Runtime dependencies and public APIs are unchanged. Dev installs gain one exact direct pin and the existing `sortedcontainers` transitive. Example sizes remain bounded and make no scale claim.
- **ADR**: `docs/adr/0043-deterministic-property-based-matching-tests.md`.
- **Reversibility**: Minimized failures must become explicit regressions before replacement/removal; unseeded random loops are not an acceptable rollback.

### D-025: Make Ordered Summaries Part of Bounded Cross-Engine Parity

- **Date**: 2026-07-25
- **Context**: Generated CSV-level parity found equal signature-v3 decisions but alphabetical DuckDB partition summary rows versus the established Pandas/full-scan domain order.
- **Decision**: Reindex partition aggregates to the established six-metric order and compare the complete EngineResult contract across original/permuted Pandas, DuckDB full-scan, and forced-partition runs using ten derandomized cases plus two explicit regressions.
- **Rationale**: A deterministic digest is necessary but not sufficient when an observable ordered output differs across execution paths. The reader and partition boundaries must be exercised together.
- **Compatibility**: Metric values and signature v3 do not change. Partitioned summary row order intentionally changes to match the existing default contract. Evidence is limited to Python 3.14.6, Pandas 3.0.3, and DuckDB 1.5.5 and is not a supported-version claim.
- **ADR**: `docs/adr/0044-bounded-cross-engine-output-parity.md`.
- **Reversibility**: Any different order requires a versioned output contract; comparing summaries as unordered data would conceal the regression and is unsafe.

### D-026: Freeze Synthetic Finance Inputs and Expected Outputs as a Digested Registry

- **Date**: 2026-07-25
- **Context**: Generator manifests proved input provenance, while sample documentation allowed output counts to drift and therefore could not act as deterministic golden evidence.
- **Decision**: Create a closed schema-v1 registry with two synthetic stock/GL cases, exact file byte/hash records, canonical expected-output/case/registry digests, and executable Pandas/DuckDB full/partition checks. Package the evidence in sdist only and govern updates through an explicit versioning policy.
- **Rationale**: Input identity and expected decisions must be reviewed together but independently. Layered digests make accidental byte/output drift visible without pretending that a checksum proves accounting correctness.
- **Compatibility**: Runtime wheel/API behavior is unchanged. Existing sample bytes are frozen by reference; a new focused case adds only synthetic test data. Future behavior changes require a new registry/case version and the relevant compatibility ADR.
- **ADR**: `docs/adr/0045-versioned-golden-finance-dataset-registry.md`.
- **Reversibility**: Preserve old versions as compatibility evidence; never rewrite expected output merely to make a changed implementation pass.

### D-027: Make the Risk Register a Validated Governance Contract

- **Date**: 2026-07-25
- **Context**: The narrative risk table had strong content but implicit ownership and no validated triggers, likelihood, residual risk, or review schedule.
- **Decision**: Preserve R-001 through R-017 in a closed schema-v1 YAML source with role owners, deterministic likelihood-by-impact ratings, mitigations, repository evidence, residual rationale/actions, and cadence-bound review dates; require exact Markdown ID parity.
- **Rationale**: Risk state must be queryable and fail visibly when IDs, evidence, scoring, or review governance drift, without claiming that a role label proves a staffed control function.
- **Compatibility**: The readable Markdown narratives and IDs remain. This adds governance metadata and source-distribution evidence only; runtime APIs and wheel contents are unchanged.
- **ADR**: `docs/adr/0046-schema-validated-risk-register-governance.md`.
- **Reversibility**: Any replacement must retain schema/rating/evidence/review validation and risk history; prose-only implicit ownership is not an acceptable rollback.

### D-028: Cap Public and Module Maturity at Recorded Evidence

- **Date**: 2026-07-25
- **Context**: The product evidence ceiling was Alpha/Experimental while three CLI-visible module descriptors were labeled Beta.
- **Decision**: Downgrade every current module to Experimental, retain future Beta/Stable schema values, and enforce a schema-v1 policy linking all module ceilings and seven public publishing surfaces to the Claims Evidence Matrix and prohibited unqualified wording.
- **Rationale**: Maturity metadata is a public claim. Promotions must fail unless evidence and the governing ceiling change intentionally; boundary guides must still be able to quote forbidden phrases outside publishing scans.
- **Compatibility**: Module IDs/capabilities/runtime are unchanged. The Beta filter now returns an empty current set. Policy/schema are source-distribution governance artifacts only.
- **ADR**: `docs/adr/0047-evidence-bounded-public-and-module-maturity.md`.
- **Reversibility**: Restore a higher label only with corresponding evidence/policy/ADR updates; deleting the promotion regression is unsafe.

### D-029: Leave Equal-Cost Assignments Unresolved Under a Bounded Opt-In Policy

- **Date**: 2026-07-25
- **Context**: Stable keys made tied assignments replayable but did not make one financially unique; exhaustive alternate-assignment enumeration would be unsafe.
- **Decision**: Preserve `stable-tie-break-v1` as the default, add opt-in `unresolved-equal-cost-v1`, split only the conservative path into connected components, prove non-uniqueness by bounded selected-edge exclusion, and fail closed above 64 candidates or 32 checks. Record explicit ambiguity evidence and advance management-pack output to schema v4 and the golden registry to 1.1.0.
- **Rationale**: Determinism and trustworthiness are separate properties. A bounded unresolved outcome is safer than presenting an equally optimal pairing as unique, while the versioned default avoids silently changing existing decisions.
- **Compatibility**: Historical default signatures remain unchanged. The new result/engine policy field is additive; management-pack v1/v2/v3 remain closed compatibility readers. Signature v3 remains a decision digest and the golden outer digests bind configuration.
- **ADR**: `docs/adr/0048-bounded-unresolved-equal-cost-matching.md`.
- **Reversibility**: Preserve labeled v4/registry-1.1 artifacts and never weaken the budget or rewrite old expectations; reverting the current writer requires a versioned migration.

### D-030: Verify Lease-Based Takeover Separately from Managed Retry

- **Date**: 2026-07-25
- **Context**: The reconciliation worker's existing resume regression converted a matcher exception to `Failed` and required explicit requeue, so it did not cover the `Running` state and live lease left by abrupt termination.
- **Decision**: Raise a test-only unhandled `BaseException` immediately after the first partition transaction commits, reject a replacement worker before lease expiry, advance a deterministic test clock, then require attempt two to skip the checkpoint and reproduce the uninterrupted input/result/partition hashes without duplicate IDs or outputs. Bind the test double to the actual queued-or-expired SQL predicate.
- **Rationale**: Managed retry and crash takeover have different state transitions. Exact digest equality and no-duplicate assertions provide stronger bounded evidence than a final `Complete` status alone.
- **Compatibility**: Runtime code and schemas are unchanged. This is a local repository/worker control-flow contract, not a live PostgreSQL, process-kill, supported-version, RTO, or durability claim; `P1-PLAT-004` remains planned.
- **ADR**: `docs/adr/0049-bounded-reconciliation-crash-resume-contract.md`.
- **Reversibility**: Removing the contract reopens the crash-resume evidence gap; a future live replacement must retain pre-expiry exclusion and exact hash/no-duplicate checks.

### D-031: Make Supported Engine Parity an Exact No-Skip CI Matrix

- **Date**: 2026-07-25
- **Context**: The existing Python 3.11/3.12 CI job installed no DuckDB extra, so optional parity tests could skip; local Python 3.14 evidence could not substitute for the supported matrix.
- **Decision**: Define a closed four-cell contract over Python 3.11/3.12 and reviewed lower/current-compatible direct pins (NumPy 1.26.4/2.4.3, Pandas 2.2.0/3.0.5, DuckDB 1.0.0/1.5.5), verify resolved versions, run all named parity suites, and fail on any skip. Bind CI, `pyproject.toml`, official PyPI metadata, and golden registry 1.1.0 through repository tests.
- **Rationale**: Explicit dated cells make dependency drift and optional-engine absence visible. A configured job remains a plan until an identified GitHub run proves every cell.
- **Compatibility**: Runtime dependency ranges, application code, and outputs are unchanged. The direct CI pins do not create upper support bounds or a full lockfile and make no performance/live-backend claim.
- **ADR**: `docs/adr/0050-reviewed-supported-engine-parity-matrix.md`.
- **Reversibility**: Any replacement must preserve the supported-Python × lower/current cross-product, resolved-version checks, named suites, and no-skip behavior; floating latest-only coverage is unsafe.

### D-032: Isolate Legacy Financial Scalar Helpers from Production Call Sites

- **Date**: 2026-07-25
- **Context**: Public rounding, difference, and tolerance helpers still need legacy-v1 behavior until a breaking-release boundary, but using them internally would allow compatibility acceptance to spread silently.
- **Decision**: Add strict-v2 exact scalar counterparts, migrate all production arithmetic to them after any explicit compatibility parse, and enforce the boundary with an AST test that rejects production calls to the three legacy names.
- **Rationale**: A staged migration needs a safe current path and a mechanically enforced compatibility perimeter. Lexical type annotations alone neither prove current behavior nor justify breaking external callers.
- **Compatibility**: Historical helper names, results, and deprecation warnings remain unchanged. APIs, schemas, persisted evidence, digests, and current rule/period compatibility inputs are unchanged; P0-005 remains open.
- **ADR**: `docs/adr/0051-strict-financial-scalar-helper-boundary.md`.
- **Reversibility**: Any replacement must retain strict binary-float rejection and the no-production-legacy-call guard; silently routing current code through a compatibility name is unsafe.

### D-033: Make Strict Money Construction and Scalar Arithmetic Explicit

- **Date**: 2026-07-25
- **Context**: `Money` had an explicit strict policy argument but its legacy default suppressed deprecation warnings, and scalar dunder operations had no named strict alternative.
- **Decision**: Add `Money.from_exact`, `multiply_exact`, and `divide_exact`; warn after successful legacy binary-float construction; and AST-enforce explicit `input_policy=` at every production constructor call.
- **Rationale**: Current code needs a discoverable fail-closed path while external compatibility survives until a documented breaking-release boundary. Silent legacy construction defeats staged migration.
- **Compatibility**: Constructor/operator values are unchanged. Legacy construction now emits the existing warning; strict and invalid inputs do not. Persisted schemas, digests, routes, and evidence formats are unchanged; P0-005 remains open.
- **ADR**: `docs/adr/0052-strict-money-construction-and-scalar-operations.md`.
- **Reversibility**: Retain strict rejection and the explicit-policy AST guard; changing public defaults requires a versioned breaking-release migration, not silent in-place replacement.

### D-034: Select Strict Studio Amount Filtering Explicitly

- **Date**: 2026-07-25
- **Context**: The Studio HTTP route already carried exact text, but the underlying direct service reader accepted finite floats through an implicit legacy default.
- **Decision**: Split exact and legacy filter input aliases, add a financial-input policy to the filter/parser, make the application select strict v2, and AST-enforce explicit policy at production call sites.
- **Rationale**: A read-only filter can change the visible review set even though it does not persist a decision. Current web behavior must not depend on an implicit compatibility reader.
- **Compatibility**: HTTP/OpenAPI/form contracts are unchanged. Direct Python service calls retain warning legacy-v1 behavior; schemas, digests, database state, audit, and reconciliation evidence are unchanged.
- **ADR**: `docs/adr/0053-version-studio-amount-filter-ingress.md`.
- **Reversibility**: Preserve explicit strict application selection and the AST guard; changing the direct-service default requires a breaking-release migration or separate legacy entry point.

### D-035: Persist Anonymizer Financial-Input Policy in Manifest v2

- **Date**: 2026-07-25
- **Context**: Anonymizer outputs are durable financial transformations, but schema-v1 recorded the exact percentage/algorithm without identifying whether legacy or strict parsing governed ingress.
- **Decision**: Thread a named policy through percentage/factor/cell masking; keep the service legacy by default; make CLI strict; AST-enforce explicit production selection; and advance the writer to manifest v2 with policy in its digest while retaining v1 as an implicit-legacy reader.
- **Rationale**: Durable transformed values require parser provenance beside algorithm, seed, rounding, and output hashes. Historical manifests must remain verifiable rather than rewritten.
- **Compatibility**: Service values and algorithm are unchanged; finite-float service input warns and v2 records legacy. CLI exact text writes strict v2. Checked-in/user v1 remains valid; schemas, routes, and private-map boundary otherwise remain.
- **ADR**: `docs/adr/0054-version-anonymizer-financial-input-policy.md`.
- **Reversibility**: Preserve v1/v2 readers and their digests; never strip/relabel v2 policy or silently return the current writer to unversioned ingress.

### D-036: Persist Variance Financial-Input Policy in Report v3

- **Date**: 2026-07-25
- **Context**: Variance schema v2 proved exact threshold values and comparisons but could not show whether its durable flags came through the legacy or strict parser.
- **Decision**: Split exact/legacy threshold aliases, thread a named policy through service decisions, keep direct service compatibility, make CLI strict, AST-enforce production selection, and advance the report to v3/threshold-policy v2 with parser policy inside the digest. Preserve unversioned/v1 and v2 as implicit-legacy readers.
- **Rationale**: Exact canonical values alone do not disclose whether binary floating point was accepted before canonicalization. Decision artifacts need both value and ingress provenance.
- **Compatibility**: Arithmetic, flags, rounding, report rows, legacy numeric threshold keys, and service results are unchanged. Historical bytes/digests remain valid; current schema branches prevent v2/v3 policy relabeling.
- **ADR**: `docs/adr/0055-version-variance-financial-input-policy.md`.
- **Reversibility**: Preserve all historical readers and v3 digests; never drop or relabel the v3 policy field, and do not restore an implicit current CLI path.

### D-037: Persist Synthetic-Generator Financial-Input Policy in Manifest v2

- **Date**: 2026-07-25
- **Context**: Generator manifest v1 proved exact rates, algorithm, currency policy, and output bytes but not whether a compatibility float was accepted before canonicalization.
- **Decision**: Split exact/legacy rate aliases, make internal numeric parsing strict, keep direct service compatibility, make CLI strict, AST-enforce production selection, and advance the writer to manifest v2 with parser policy inside both digests while retaining v1 as an implicit-legacy reader.
- **Rationale**: Synthetic fixtures drive correctness and benchmark inputs; reproducibility requires the parser provenance as well as the canonical value and byte hashes.
- **Compatibility**: `exact-decimal-v1`, scenario/currency arithmetic, equivalent-input CSV bytes, output inventory, and eight-path return value are unchanged. V1 bytes/digests remain valid and are never relabeled.
- **ADR**: `docs/adr/0056-version-synthetic-generator-financial-input-policy.md`.
- **Reversibility**: Preserve v1/v2 verification and digests; never strip/relabel v2 policy or restore an implicit current CLI path.

### D-038: Preserve YAML Decimal Lexemes Before Strict Configuration Validation

- **Date**: 2026-07-25
- **Context**: Safe PyYAML converted historical unquoted decimal tolerances to binary floating point before the versioned Pydantic parser, while rejecting those files outright would break common configurations.
- **Decision**: Give `load_config` a named policy; preserve YAML floating-scalar source text with a SafeLoader-derived strict reader; make CLI, benchmark, and Studio select strict-v2; quote current default tolerance output; AST-enforce production selection; retain direct model/loader legacy defaults.
- **Rationale**: Exactness must be established before conversion, and compatibility must remain a separate visible contract. Intercepting the safe YAML scalar tag preserves both without weakening tag safety.
- **Compatibility**: Existing unquoted decimals and canonical results remain valid; subtle lexemes gain exact current behavior. Direct Python compatibility still warns. No API route, database, config schema/signature, reconciliation algorithm, or durable artifact format changes.
- **ADR**: `docs/adr/0057-version-configuration-financial-input-policy.md`.
- **Reversibility**: Keep the explicit legacy reader, strict current callers, safe-tag rejection, and lexeme regression; changing public defaults or adding a config artifact schema requires a separately documented migration.

### D-039: Bind Current Rule Decisions to Exact Ingress and Local Provenance

- **Date**: 2026-07-25
- **Context**: Control-pack YAML converted unquoted decimal rule literals through binary floating point, and historical rule-result JSON did not identify parser policy, pack content, or input bytes.
- **Decision**: Reuse the shared safe exact-lexeme YAML reader; thread named policy through rule loading/evaluation; make CLI/demo/explain/control-matrix strict; preserve direct legacy defaults and the unversioned writer; and add a schema-v2 current execution artifact with policy, normalized executable `pack.yml`/`rules.yml` digest, sorted CSV hashes, timestamp-independent decision digest, full artifact digest, and v1/v2 reader/verifier.
- **Rationale**: A control decision needs exact input semantics and reproducible local provenance, while historical contracts must not be silently relabeled. Content digests provide consistency checks but are not author/source authentication.
- **Compatibility**: Existing list-returning execution and unversioned output remain. Numeric rule literals retain their public source-shaped representation; equivalent existing integer rules keep their decisions. Current CLI output intentionally advances to v2.
- **ADR**: `docs/adr/0058-version-rule-financial-ingress-and-results.md`.
- **Reversibility**: Preserve explicit v1 readers/writers and v2 verification; never restore implicit current policy selection, strip v2 provenance, or describe local digests as signatures.

### D-040: Bind Current Period Decisions to Exact Exception Ingress

- **Date**: 2026-07-25
- **Context**: Review and period readers allowed pandas to infer monetary CSV fields before Decimal parsing, malformed/missing fallback amounts became zero, and historical comparison JSON had no parser, input-byte, algorithm, or digest provenance.
- **Decision**: Thread the named financial-input policy through exception collection, review-register export, and comparison; make current CLI/demo callers strict while retaining direct legacy defaults; preserve review workbook first-sheet compatibility while adding policy metadata; and advance current comparison JSON to schema v2 with recognized input fingerprints, path-independent decision digest, complete artifact digest, and v1/v2 reader/verifier.
- **Rationale**: New/recurring/resolved classification is a financial-control decision. Its source lexemes, invalid-value semantics, selected policy, and local input bytes must be reproducible without falsely relabelling historical output.
- **Compatibility**: Direct Python defaults and unversioned JSON remain explicit legacy paths. The review register stays the first Excel sheet. V2 still uses the historical two-fractional-digit `ROUND_HALF_UP` identity rule and does not claim currency-specific precision or authenticated source provenance.
- **ADR**: `docs/adr/0059-version-period-comparison-financial-ingress.md`.
- **Reversibility**: Preserve v1/v2 readers, explicit legacy selection, strict current callers, first-sheet order, and v2 verification; never collapse strict invalid/missing values into valid zero or describe local hashes as signatures.

### D-041: Bind Current Client-Pack Redaction to Exact JSON Ingress

- **Date**: 2026-07-25
- **Context**: JSON redaction crossed binary floating point before amount bucketing, applied buckets twice, exposed local source paths, and wrote an unversioned manifest with optional output-only hashes and no parser policy.
- **Decision**: Make current CLI/demo generation strict while preserving direct legacy defaults; retain JSON decimal lexemes and apply scalar redaction once; omit current local paths; and advance the manifest to schema v2 with required selected-source/included-output fingerprints, path-independent content digest, full artifact digest, plus v1/v2 reader/verifier.
- **Rationale**: A privacy transformation must not change financial bucket decisions through parser approximation, and a sharing artifact needs verifiable local content without implying that hashes authorize disclosure or prove redaction completeness.
- **Compatibility**: Explicit legacy direct calls keep the unversioned manifest and optional checksum behavior. Current strict redacted JSON may emit non-amount decimals as strings; unredacted files remain byte-identical. The CLI checksum flag remains as a compatibility request while v2 always hashes inputs/outputs.
- **ADR**: `docs/adr/0060-version-client-pack-redaction-ingress.md`.
- **Reversibility**: Preserve v1/v2 readers, strict current selection, exact lexemes, required v2 fingerprints, path omission, and best-effort boundary; never restore implicit binary parsing or call hashes disclosure approval.

### D-042: Bind Current Evidence-Binder Decisions to Exact CSV Ingress

- **Date**: 2026-07-25
- **Context**: Evidence risk scores were Decimal-validated only after pandas could infer binary floating point, while schema-v2 indexes lacked parser policy, selected input-byte provenance, and document digests.
- **Decision**: Make current CLI/demo generation strict while preserving direct legacy defaults; read recognized CSV fields as text; keep invalid explicit scores visible; and advance current indexes to schema v3 with selected exception/match/rule/review fingerprints, path-independent content digest, full artifact digest, plus v2/v3 reader/verifier.
- **Rationale**: Risk-score selection changes the review evidence set. The exact source lexeme, named parser policy, selected local bytes, and resulting cases must remain reproducible without relabeling historical indexes.
- **Compatibility**: Direct Python defaults retain the exact schema-v2 shape and read as `legacy-unverified`. Current strict output retains `case_count`/`cases` but adds v3 provenance; newly visible invalid rows may intentionally shift report-local sequential case IDs.
- **ADR**: `docs/adr/0061-version-evidence-binder-financial-ingress.md`.
- **Reversibility**: Preserve v2/v3 readers, strict current selection, exact lexemes, and v3 verification; never restore implicit current inference, hide invalid scores, relabel v2, or call local hashes signatures/audit approval.

### D-043: Make Security Architecture an Evidence-Bounded Registry

- **Date**: 2026-07-25
- **Context**: The prose security baseline could not enforce trust-boundary, edition, data-class, control-owner/evidence, or governed residual-risk consistency.
- **Decision**: Adopt a closed schema-v2 YAML registry plus readable view; model Community Local as bounded, Team/Server as experimental, and Regulated as planned-only; require every control/boundary evidence path and map security-related risk owners/ratings directly to the normalized risk register.
- **Rationale**: Security architecture must distinguish repository evidence from deployment effectiveness and make drift fail tests instead of relying on prose review.
- **Compatibility**: No runtime, API, persistence, identity, or deployment behavior changes. Existing security docs remain readable companions; standards mappings and module threat models remain separate backlog tasks.
- **ADR**: `docs/adr/0062-version-security-architecture-registry.md`.
- **Reversibility**: Preserve the v2 registry/schema/tests and introduce a versioned successor rather than returning to prose-only or relabeling planned/partial controls.

### D-044: Bind Every Active Module to a Closed Threat Model

- **Date**: 2026-07-25
- **Context**: The prose threat model and Security Architecture v2 did not fail when a runtime module, interface, data class, permission surface, or declared test changed without module-specific assets, actors, threats, controls, evidence, and ownership.
- **Decision**: Adopt a closed schema-v1 module threat-model index with exact runtime-registry parity; reuse architecture owners/boundaries/data classes/controls and normalized risk IDs; require existing tests, assumptions, residual limitations, and out-of-scope capabilities for every module and threat case.
- **Rationale**: Module coverage must be mechanically complete and conservatively evidence-bounded without creating parallel control/risk truth or turning repository tests into deployed security assurance.
- **Compatibility**: No runtime module, API, data, identity, permission, or deployment behavior changes. All nine modules remain Experimental and the readable threat model remains the human entry point.
- **ADR**: `docs/adr/0063-version-module-threat-model-index.md`.
- **Reversibility**: Preserve schema-v1 and version successors; never return to prose-only coverage, invent a missing risk score, delete limitations, or allow an active module without a matching threat entry.

### D-045: Pin Stable ASVS and Keep Unassessed Coverage Visible

- **Date**: 2026-07-25
- **Context**: ASVS `master` is a mutable Bleeding Edge release, while a repository-only review cannot credibly claim full verification of all 345 stable requirements.
- **Decision**: Pin official ASVS 5.0.0 release/source identity and digest; map 55 high-relevance version-qualified requirements across all 17 chapters with narrow implemented/partial/planned/not-applicable statuses; declare the remaining 290 unassessed and prohibit ASVS level/compliance claims.
- **Rationale**: A reproducible, reviewable and explicitly incomplete mapping is stronger evidence than mutable identifiers or hundreds of unsupported paper statuses.
- **Compatibility**: No runtime, API, file, identity, cryptography, deployment, or release behavior changes. Upstream requirement prose is not copied; identifiers/levels/counts are attributed to the CC BY-SA 4.0 official source.
- **ADR**: `docs/adr/0064-pin-scoped-owasp-asvs-5-mapping.md`.
- **Reversibility**: Preserve schema-v1 and the stable source pin; use a versioned successor for a new stable ASVS and never repoint this artifact to master or erase unassessed counts.

### D-046: Pin Final SSDF and Keep Every Core Task Visible

- **Date**: 2026-07-25
- **Context**: NIST SSDF 1.2 is an Initial Public Draft, SSDF 1.1 remains the final core publication, and repository files alone cannot prove a continuously operating secure-development program.
- **Decision**: Pin official SP 800-218/SSDF 1.1 PDF/table identities; map all 4 groups, 19 practices, and 42 tasks with architecture owners, bounded evidence/tests, explicit gaps/actions, and a 90-day review cadence; keep SP 800-218A as a separate required AI-profile assessment.
- **Rationale**: Complete task visibility with conservative statuses prevents draft drift, silent omissions, and unsupported SSDF-alignment or conformance language.
- **Compatibility**: No runtime, API, source-control, CI execution, release, personnel, or vulnerability-response behavior changes. The first review records 28 partial and 14 planned tasks, with none promoted to implemented-bounded or not-applicable.
- **ADR**: `docs/adr/0065-pin-final-nist-ssdf-all-task-mapping.md`.
- **Reversibility**: Preserve schema-v1/source identities and use a versioned successor for a final revision; never repoint the artifact to a draft, erase gaps, or call repository links conformance evidence.

### D-047: Version Provenance Trust and Failure Contracts Before Signing

- **Date**: 2026-07-25
- **Context**: Approved SLSA 1.2 adds a Source Track, while current build/SBOM workflows generate no release-bound signed provenance and cannot self-assert builder trust or a SLSA level.
- **Decision**: Keep Build/Source tracks UNEVALUATED; pin official v1.2 tag/commit; define wheel/sdist/image/SBOM identities, seven trust boundaries, in-toto Statement v1/SLSA provenance v1 fields, signature expectations, independent fail-closed verification, safe failure codes, evidence-preserving rollback, and 12 owned/testable implementation gates before changing the release pipeline.
- **Rationale**: Cryptographic output without independent expectations, builder isolation, publication coupling, failure behavior, and rollback would be unverifiable ceremony rather than supply-chain assurance.
- **Compatibility**: No runtime, API, workflow execution, source-control, signing, publication, or release behavior changes. Two gates are partial from repository definitions and ten planned; no level or verified property is claimed.
- **ADR**: `docs/adr/0066-version-slsa-provenance-plan-before-pipeline.md`.
- **Reversibility**: Preserve the v1 plan/source pin and use versioned successors; on drift or lost evidence return to UNEVALUATED, never weaken verification or overwrite forensic release records.

### D-048: Separate Signed Candidates from Irreversible Publication

- **Date**: 2026-07-25
- **Context**: P0-SEC-006 needs clean source/package/image provenance, but publishing a GitHub Release or PyPI package before repository immutability and remote verification are reviewed would create difficult-to-reverse external state.
- **Decision**: Implement a signed-tag-only candidate workflow with workflow-level deny-all permissions, exact tag/version/main/clean-tree checks, GitHub-verified annotated-tag identity, six official-wheel-hash-locked build tools including the Windows-conditional dependency, full-SHA action pins, commit-time `SOURCE_DATE_EPOCH`, fail-closed deterministic sdist normalization, a closed source/wheel/sdist/image manifest, keyless SLSA attestations, preserved bundles, and strict repository/workflow/ref/revision/runner verification before short-retention candidate upload. Keep GitHub Release and PyPI publication absent and human-gated.
- **Rationale**: Cryptographic material is useful only when exact subjects and independent expectations fail closed. Separating reviewable candidates from immutable publication prevents a workflow definition or partial registry write from being mislabeled a release.
- **Compatibility**: No runtime/API/CLI/database behavior changes. The release-manifest contract is new schema v1 and records source epoch; the candidate image uses a commit-specific discovery tag but is identified only by its OCI manifest digest. Two same-machine Python 3.14.6 builds reproduced source/wheel/normalized-sdist bytes, not a supported-version, cross-platform, image, hosted, signature, or SLSA result. P0-SEC-006 remains in progress until a reviewed hosted run and independent verification exist.
- **ADR**: `docs/adr/0067-tag-only-signed-release-candidates-before-publication.md`.
- **Reversibility**: Disable the workflow/environment without publishing; preserve any candidate digests, bundles, and run evidence. Never move a signed version tag, overwrite a subject, delete failure evidence, or weaken verification to recover.

### D-049: Generate One Evidence-Bounded SBOM per Exact Release Subject

- **Date**: 2026-07-26
- **Context**: The separate SBOM workflow installed a floating tool and described the runner environment rather than the source, wheel, sdist, and OCI subjects built by the release job.
- **Decision**: Replace that path with deterministic CycloneDX 1.7 documents bound to every release-manifest subject; require exact Python source/wheel/sdist declaration parity, include matching npm-lock inventory only in the source document, scan the exact image digest with checksum/commit/platform-verified Syft 1.49.0, preserve `unknown` completeness, record a closed SBOM manifest, and separately attest and strictly verify each CycloneDX predicate before non-publishing candidate upload.
- **Rationale**: A single runner-environment inventory can be fresh and syntactically valid while describing none of the artifacts consumers receive. Exact subject hashes, conservative completeness, and independent expectations make omissions and drift visible without overstating dependency safety.
- **Compatibility**: No runtime/API/CLI/database/browser behavior changes. The SBOM manifest is new schema v1; the old independent workflow is removed. Local clean-HEAD package/source outputs and synthetic image normalization pass, but no hosted image scan, signature, publication, vulnerability/license assurance, or SLSA level is established. P0-SEC-007 remains in progress.
- **ADR**: `docs/adr/0068-bind-cyclonedx-sbom-to-each-release-subject.md`.
- **Reversibility**: Disable candidate generation rather than restoring floating tooling or bypassing verification. Preserve existing subject/SBOM digests, manifests, bundles, and failures; corrections require a reviewed generator-policy successor and new attestation, never overwrite.

### D-050: Lock Application Resolution and Bound Every Supply-Chain Exception

- **Date**: 2026-07-26
- **Context**: Runtime/server CI and Docker resolved broad Python bounds at execution time, pip-audit described ambient state, npm and secret scans were absent from the candidate gate, and no closed exception ownership/expiry contract existed.
- **Decision**: Adopt universal uv.lock under exact uv 0.11.32 and an absolute upload cutoff; consume it with `--locked` in normal/server/security/candidate CI and checksum-pinned Docker; audit its hash export on Python 3.11/3.12; audit the npm lock at high severity; scan all Git history and the checked tree with checksum-pinned Gitleaks and redacted output; require weekly four-ecosystem updates and closed 30-day exact-subject exceptions with two non-owner approvers; run all gates before candidate registry authentication and fail closed on scanner errors.
- **Rationale**: One reviewable resolution and exact, expiring exceptions prevent adjacent runs or broad suppressions from silently changing the release dependency/security boundary. Separating broad package metadata from the application lock preserves downstream compatibility.
- **Compatibility**: Public Python dependency bounds, runtime APIs, CLI, database, and browser contracts remain unchanged. The developer profile now explicitly carries the declared setuptools/wheel backend so locked `build --no-isolation` succeeds; candidate bootstrap remains separately hash-locked under ADR 0067. Local Python 3.11 all-extra sync/hash-audit/build/full-suite, npm audit, 69-commit/tree scans, policy contracts, and actionlint pass. Hosted Python 3.11/3.12, Docker, branch/release enforcement, package safety/provenance, and closure of the 155-entry npm SRI gap are not established; P0-SEC-008 remains in progress.
- **ADR**: `docs/adr/0069-lock-dependencies-and-fail-closed-supply-chain-gates.md`.
- **Reversibility**: Revert Docker/workflow/lock/policy changes as one reviewed unit, preserve exception/audit evidence, and keep publication disabled. Never silently fall back to unlocked installation, erase an expired decision, expose scanner secrets, or weaken a gate to recover.

### D-051: Preflight Tabular Files and Fail on Unregistered Parser Growth

- **Date**: 2026-07-26
- **Context**: Local operator-selected files remain untrusted, while canonical pandas, direct DuckDB, mapping, plugins, reports, review, and Studio paths did not share one resource/active-content boundary. A helper alone could not prove that direct parser calls had not bypassed it.
- **Decision**: Introduce versioned `tabular-file-ingress-v1` before canonical pandas and direct DuckDB reads; set explicit byte/row/column/cell/field/archive/member/decompression budgets; reject non-regular/symlinked, type-mismatched, unsafe/duplicate/encrypted/unsupported-compression XLSX members, DTD/entities, external relationships, formulas, active/embedded content, sparse excess columns, and aggregate excess worksheets with stable code-only errors. Route mapping header and the built-in CSV adapter through the canonical reader. Maintain a closed schema-v1 13-surface inventory whose AST contract exactly allowlists every pandas and stdlib delimited-parser path. Record incomplete hostile-file coverage as R-018 and advance only the bounded ASVS V5 mapping evidence.
- **Rationale**: Pre-parser limits reduce predictable resource/active-content exposure, while an exact inventory makes partial compatibility readers and future bypasses visible. Conservative rejection is preferable to silently trusting an extension or workbook feature at a financial-data boundary.
- **Compatibility**: Valid supported canonical CSV/XLS/XLSX semantics remain; CSV is scanned once before pandas and XLSX XML/archive structures are scanned before pandas/openpyxl. Formula-bearing XLSX input is now rejected at protected paths. Legacy XLS remains accepted under size/OLE checks only. JSON/YAML/generated-artifact readers, malware/quarantine, HTTP uploads, source authenticity, and future connectors remain partial; `P0-SEC-009` and R-018 stay open. The direct `defusedxml>=0.7.1` runtime declaration does not expand the 103-package non-root lock because it was already transitive.
- **ADR**: `docs/adr/0070-bounded-tabular-file-ingress-and-inventory.md`.
- **Reversibility**: Revert policy, call sites, inventory/schema/tests, direct dependency metadata, and governance links together. Do not remove preflight while retaining enforced wording, and do not weaken an abuse test or register a bypass as bounded merely to recover compatibility.

### D-052: Bound Structured Documents and Reject Ambiguous YAML/JSON

- **Date**: 2026-07-26
- **Context**: Safe YAML tags alone did not bound parser resources, PyYAML silently accepted duplicate keys, standard JSON accepted duplicate keys/non-finite constants, and direct parser growth was not mechanically closed.
- **Decision**: Introduce `structured-document-ingress-v1` with fixed byte/node/depth/collection/scalar/alias ceilings, safe code-only errors, duplicate/merge/cycle/multiple-document/unsafe-tag/non-finite rejection, and exact AST inventory of direct PyYAML parsers. Migrate FI-010 configuration, mapping, control-pack, and Reconciliation-as-Code YAML while leaving close-workflow and generated/restore JSON callers explicitly partial.
- **Rationale**: Domain validation after an ambiguous or unbounded parse is too late. One versioned boundary plus an exact direct-parser gate makes resource and last-key-wins behavior visible without pretending all file surfaces are closed.
- **Compatibility**: Valid current YAML and strict decimal lexemes remain compatible; duplicate keys now fail instead of selecting the last value, and invalid configuration summaries no longer expose paths or input details. The bounded JSON helper is not evidence that its remaining callers are protected.
- **ADR**: `docs/adr/0071-bounded-structured-document-ingress.md`.
- **Reversibility**: Revert reader, loader option, call sites, inventory/schema/tests, and governance evidence as one unit. Use a versioned limit successor for reviewed compatibility pressure; never register an unbounded bypass as bounded.
### D-053: Reuse the shared structured boundary for close workflow files

- Date: 2026-07-26
- Decision: Route FI-011 close checklist JSON and JSON/YAML templates through `structured-document-ingress-v1`; preserve the existing generic CLI parse messages and valid task normalization; reject ambiguous/unsafe structures before normalization; remove the direct close-workflow PyYAML allowlist entry only with passing AST and compatibility tests.
- Rationale: Post-parse task validation cannot bound parser resource use or prevent duplicate-key ambiguity. Reusing the versioned boundary avoids a divergent close-only parser policy while preserving the public workflow contract.
- Consequence: FI-011 is bounded for the documented local file paths, but template authorship, task correctness, malware absence, approvals, audit opinions, generated artifacts, uploads, and connector behavior remain outside the claim.
- ADR: `docs/adr/0072-bound-close-workflow-structured-ingress.md`

### D-054: Bound generated manifests without changing financial redaction

- Date: 2026-07-26
- Decision: Route client-pack manifest and evidence-index JSON verification through `structured-document-ingress-v1`, preserve public invalid-JSON and current/legacy digest contracts, and keep JSON/CSV/text redaction outside this slice because strict redaction depends on exact decimal lexemes.
- Rationale: Manifest schema/digest validation occurs too late to bound parser resources or reject duplicate-key ambiguity, while an indiscriminate migration of redaction parsing would regress financial bucketing semantics.
- Consequence: Two FI-012 readers are bounded, but FI-012 remains partial and no malware, provenance, disclosure-approval, redaction-completeness, signature, or source-authenticity claim is added.
- ADR: `docs/adr/0073-bound-generated-manifest-json-readers.md`

### D-055: Preserve exact JSON float lexemes inside the bounded redaction reader

- Date: 2026-07-26
- Decision: Add an opt-in exact-float-lexeme representation to `structured-document-ingress-v1`, migrate client-pack JSON redaction to it in strict mode while preserving legacy finite-float behavior, preflight selected JSON before destination preparation, and reject malformed JSON rather than reinterpret it as unrestricted text.
- Rationale: Standard float construction changes financial bucket boundaries, while the prior custom parser bypassed fixed resource and ambiguity controls. A representation option preserves financial meaning without weakening the shared rejection policy.
- Consequence: FI-012 JSON redaction is bounded and deterministic hostile JSON fails before ordinary output mutation, but concurrent source mutation can still leave a prepared/partial destination and CSV/text, provenance, disclosure authorization, scanning, and quarantine remain partial. No redaction-completeness or safe-redistribution claim is added.
- ADR: `docs/adr/0074-bound-client-pack-json-redaction.md`

### D-056: Preflight and stream CSV redaction without numeric inference

- Date: 2026-07-26
- Decision: Route selected FI-012 CSV redaction through `tabular-file-ingress-v1` before fingerprint/output work, reject duplicate headers, preserve CSV fields as exact strings, and stream transformed rows through a same-directory temporary file followed by per-file atomic replace.
- Rationale: Row accumulation and direct writes exposed avoidable memory/partial-output risk, while dataframe or float inference would change financial bucket semantics. Reusing the established tabular budgets keeps parser growth visible through the exact AST inventory.
- Consequence: CSV redaction is bounded and one CSV target publishes atomically, but FI-012 remains partial because text/non-redacted copies, pack-wide rollback under concurrent mutation, provenance, disclosure authorization, malware scanning, and quarantine remain open.
- ADR: `docs/adr/0075-bound-streaming-client-pack-csv-redaction.md`

### D-057: Bound and stage the complete client-pack copy boundary

- Date: 2026-07-26
- Decision: Freeze and resource-bound FI-012 source selection, stream strict text and non-redacted bytes, build the complete client pack in a sibling staging directory, and restore prior output on handled publication failure; explicitly retain the Windows two-rename crash window rather than claiming directory-swap atomicity.
- Rationale: Whole-file replacement decoding, unbounded metadata-preserving copies, late-file inclusion, and destructive destination clearing could exhaust resources, copy unmanifested bytes, or destroy the prior pack before a valid replacement existed.
- Consequence: Predictable hostile/resource inputs and handled generation/publication failures preserve the prior destination, but process/host crash recovery, observer-atomic replacement, malware/authenticity/disclosure controls, and remaining file surfaces stay open.
- ADR: `docs/adr/0076-bound-client-pack-copy-and-staged-publication.md`

### D-058: Recover interrupted client-pack publication from a closed local state table

- Date: 2026-07-26
- Decision: Write a path-minimized, schema-v1, canonical-SHA-256 transaction marker before the existing-output rename; bind exact staging/rollback basenames and bounded previous/staged tree digests; expose only an explicit CLI recovery operation that accepts four closed states and refuses multiple/tampered markers, changed trees, unexpected siblings, reparse points, or ambiguity.
- Rationale: An abrupt loss can bypass handled-error rollback, while guessing from hidden sibling names risks deleting or publishing unrelated bytes. A finite state table plus byte binding gives deterministic local recovery without silent mutation.
- Consequence: Simulated interruption states are recoverable, but replacement remains non-observer-atomic/non-crash-atomic. Unkeyed SHA-256 is self-consistency, not authentication; file fsync is not proof of parent-directory durability, and real host/filesystem loss remains untested.
- ADR: `docs/adr/0077-integrity-checked-client-pack-publication-recovery.md`

### D-059: Bound the existing two-file database restore format without adding archives

- Date: 2026-07-26
- Decision: Route `manifest.json` and `backup.json` through the shared duplicate-safe structured engine using a named 64-MiB/1,000,000-node backup profile, bracket parsing with bounded stable fingerprints, enforce closed manifest/backup/table-name contracts and exact checksum/byte/schema agreement, and publish current-writer schemas before any restore temporary-file or target mutation.
- Rationale: The real FI-009 restore surface was two unbounded JSON reads; inventing ZIP/TAR would expand rather than reduce exposure. Manifest checksum verification after an ambiguous/unbounded parse did not constrain allocation or last-key-wins behavior.
- Consequence: Current and additive version-six backup restoration remain compatible, while stale manifest byte counts, duplicate keys, unknown tables/fields, reparse points, changed files, and resource excess fail closed. DB import JSON, archive support, encryption, authenticated provenance, centralized restore authorization, malware scanning, and real DR/host-loss exercises remain open.
- ADR: `docs/adr/0078-bound-database-backup-restore-json.md`

### D-060: Bound legacy database import JSON and reject ambiguous empty effects

- Date: 2026-07-26
- Decision: Route legacy account-reconciliation/control-test DB imports through database-legacy-import-json-ingress-v1, preserve direct-list/single-envelope/keyed-map compatibility, reject multiple aliases and arbitrary silently-empty objects, and retain the parsed-byte digest/size/profile through import evidence.
- Rationale: Replacing json.loads alone would leave file races and semantic ambiguity; provenance recalculated after parsing could describe bytes different from those actually imported.
- Consequence: FI-009's two inventoried parser entrypoints are resource-bounded and duplicate-safe before mutation, while permissive record semantics, unkeyed provenance, authorization, encryption, malware scanning, and DR remain explicit gaps.
- ADR: `docs/adr/0079-bound-legacy-database-import-json.md`

### D-061: Bind business-record parsing and provenance to the same bytes

- Date: 2026-07-26
- Decision: Route all inventoried FI-008 CSV/JSON entrypoints and their matching consumers through `business-record-ingress-v1`, preserve fractional/exponent lexemes as text, reject ambiguous/non-object records, and carry the stable parsed-byte digest/size/profile into import evidence while retaining the generic compatibility shim.
- Rationale: A parser substitution alone would leave unbounded CSV rows, silent JSON record loss, binary-float financial construction, file races, and checksums describing bytes other than those imported.
- Consequence: FI-008 parser coverage is bounded and existing valid shapes remain readable; service-specific semantic validation, authenticated provenance, centralized authorization, classification, malware scanning, and supported-scale evidence remain outside the slice.
- ADR: `docs/adr/0080-bound-business-record-ingress.md`

### D-062: Bound Studio artifacts without changing display typing

- Date: 2026-07-26
- Decision: Route all FI-007 Studio CSV/JSON reads through `generated-artifact-ingress-v1`, preserve pandas `keep_default_na=False` display typing and legacy CSV-only empty-state behavior, bracket parsing with stable fingerprints, and require companion JSON shape/count consistency when a companion exists.
- Rationale: Replacing parser calls without source stability would leave TOCTOU and resource risks; forcing exact-string dataframe typing or mandatory manifests would change established Studio display and historical output compatibility.
- Consequence: FI-007 parser coverage is bounded and rejected inputs no longer surface route tracebacks, but companions do not cryptographically bind CSV bytes and source authenticity, disclosure authorization, classification, malware scanning, and supported throughput remain open.
- ADR: `docs/adr/0081-bound-studio-generated-artifact-ingress.md`

### D-063: Use one bounded generated-report reader with explicit CSV representation

- Date: 2026-07-26
- Decision: Extend `generated-artifact-ingress-v1` with recorded `display` and `exact-text` CSV modes, retain display as the Studio default, route FI-006 variance CSV through exact text, and route its variance/management JSON through the exact-lexeme bounded reader.
- Rationale: FI-006's bounded label contradicted direct unrestricted parser calls, while reusing display inference for financial policy inputs could cross a binary-float boundary and silently discard leading-zero/scale representation.
- Consequence: FI-006 parsing is resource-bounded, ambiguity-safe, change-detecting, and representation-explicit without changing valid Studio views; producer authentication/schema binding, disclosure authorization, classification, malware quarantine, legacy XLS, uploads/connectors, and supported scale remain open.
- ADR: `docs/adr/0082-bound-generated-report-ingress.md`

### D-064: Bind FI-005 evidence/review CSV parsing and v3 fingerprints to one cached document

- Date: 2026-07-26
- Decision: Route FI-005 through explicit exact-text/display generated-artifact modes, fail closed for hostile present files, cache every selected binder CSV once, and derive/recheck evidence-index v3 CSV fingerprints from those parsed documents.
- Rationale: Direct pandas calls remained unbounded; per-exception rule/match reads could grow quadratically; separately hashing a path after parsing could bind evidence to bytes different from those used for case decisions.
- Consequence: Valid strict/legacy behavior remains, parser work is bounded by selected files, and fingerprints name the parsed bytes. Review-state JSON, producer/schema authentication, disclosure/classification, malware quarantine, legacy XLS, uploads/connectors, and supported scale remain open.
- ADR: `docs/adr/0083-bound-evidence-review-csv-ingress.md`

### D-065: Fail closed on hostile review-state JSON while preserving valid legacy coercion

- Date: 2026-07-26
- Decision: Route FI-014 through the narrower named `review-state-json-ingress-v1` profile, retain missing-file/direct-map/envelope and entry-coercion compatibility, and reject malformed present data through stable code-only failures before workflow or database mutation.
- Rationale: Unrestricted `json.loads(read_text())` could exhaust resources, accept duplicate ambiguity, race the file, or silently convert invalid persisted review evidence into an empty state.
- Consequence: Valid historical state remains readable and unsafe files become visible failures; unkeyed hashes, producer/schema authentication, actor authorization, disclosure/classification, malware quarantine, legacy XLS, uploads/connectors, and supported scale remain open.
- ADR: `docs/adr/0084-bound-review-state-json-ingress.md`

### D-066: Close direct JSON calls and make numeric representation explicit

- Date: 2026-07-26
- Decision: Add an exact direct-JSON AST allowlist, classify persisted/package-text exclusions, route all six filesystem calls through stable bounded value/object readers, and require callers to select display or exact-text numeric representation explicitly.
- Rationale: The inventory could not detect a newly introduced direct JSON file read, while an unconditional exact-lexeme migration changed current period/rule digests and Studio numeric contracts.
- Consequence: No direct filesystem `json.load(s)` remains, valid historical behavior is preserved deliberately, and hostile files fail safely. Producer/schema authentication, actor authorization, disclosure/classification, malware quarantine, persisted-value size/schema contracts, legacy XLS, uploads/connectors, and supported scale remain open.
- ADR: `docs/adr/0085-close-direct-filesystem-json-parser-inventory.md`

### D-067: Use one integer-token-only contract for AP/AR idempotency JSON

- Date: 2026-07-26
- Decision: Canonicalize and validate AP/AR idempotency responses under a shared 4 MiB/100,000-node/depth-32 structural schema, reject binary/fractional JSON numbers, and require producer failure to roll back the transaction while corrupt replay fails before a new business effect.
- Rationale: Idempotency replay protects financial mutations, but the two unrestricted producer/consumer pairs had no size, graph, ambiguity, or financial-number contract and could persist values that later decode differently.
- Consequence: Valid string/integer object responses remain compatible and two direct JSON calls leave the AST allowlist. FI-013 is partial because its ten audit/outbox/reconciliation/Redis/matching/worker direct calls remain separately unbounded.
- ADR: `docs/adr/0086-bound-financial-idempotency-json.md`

### D-068: Validate audit metadata independently from chain hashes

- Date: 2026-07-26
- Decision: Apply one bounded canonical object contract to SQLite/PostgreSQL audit metadata producers and list/verifier consumers; retain SQLite exact stored-text hashing, reconstruct PostgreSQL's historical pre-JSONB canonical bytes, and refuse corrupt SQLite audit export before output writes.
- Rationale: Sentinel normalization could turn malformed stored evidence into a plausible object, while hashing PostgreSQL's rendered JSONB text would falsely invalidate correct historical rows.
- Consequence: Valid audit bytes and hashes remain compatible, malformed metadata becomes an explicit integrity/list/export failure, and three direct JSON calls leave the allowlist. Seven other FI-013 direct decoders remain open.
- ADR: `docs/adr/0087-bound-audit-metadata-json.md`

### D-069: Use one bounded payload contract before PostgreSQL outbox publication

- Date: 2026-07-26
- Decision: Canonicalize all six PostgreSQL outbox producer call sites under one finite-object resource contract, decode claims/lists under the same contract, and roll back a corrupt claim before publisher handoff; also close the remaining PostgreSQL audit-producer gap found while tracing those writers.
- Rationale: Permissive non-object wrapping and fragmented encoders could make corrupt stored state plausible publisher input, while E-072 had not actually bound every PostgreSQL audit writer it claimed.
- Consequence: Valid event IDs, JSONB objects, leases, retries, and publisher bytes remain compatible; one direct decoder leaves the allowlist and six FI-013 direct decoders remain. Live service-backed publication is still unproved.
- ADR: `docs/adr/0088-bound-postgresql-outbox-payload-json.md`

### D-070: Bind PostgreSQL reconciliation JSONB before matching and public return

- Date: 2026-07-26
- Decision: Apply four named bounded profiles over one recursive object schema to PostgreSQL reconciliation rules, input attributes, decision lineage, and exception evidence; canonicalize JSONB text before established fingerprinting; fail corrupt records before matcher use or public return.
- Rationale: Three direct decoders and fragmented producers had no end-to-end duplicate, finite-value, graph, and resource contract; JSONB whitespace could also diverge from historical compact rule fingerprint bytes.
- Consequence: Valid object rows and digests remain compatible, the existing 100000-byte attributes ceiling is preserved, and three direct calls leave the allowlist. Three FI-013 direct decoders and live PostgreSQL rollback evidence remain open.
- ADR: `docs/adr/0089-bound-postgresql-reconciliation-jsonb.md`

### D-071: Preserve SQLite matching-rule bytes while bounding producer and replay

- Date: 2026-07-26
- Decision: Apply one bounded finite-object profile to both SQLite matching-rule table writes, idempotent replay, and public job readers; encode once before the transaction; preserve historical spaced sorted ASCII text and legacy missing-policy defaults; reject binary floats only from new producers.
- Rationale: The stored rule selects financial and identity semantics, but its direct decoder and producer had no resource or ambiguity boundary. Compact re-encoding or strict historical-float rejection would break existing text/API compatibility without improving current financial parsing policy.
- Consequence: Valid rule bytes, matching identities/digests, and legacy replay remain compatible; corrupt state fails before a new effect or public return. Two direct FI-013 decoders and stored-row authenticity remain open.
- ADR: `docs/adr/0090-bound-sqlite-matching-rule-json.md`

### D-072: Make Redis session metadata a closed bounded credential-adjacent contract

- Date: 2026-07-26
- Decision: Bind tenant-scoped Redis session writes and reads to a four-field, 16 KiB profile requiring bounded string identifiers, a lowercase SHA-256 token digest, and an explicit UTC expiry; validate before client access and preserve tenant key hashing and TTL behavior.
- Rationale: Session values are credential-adjacent internal state, not generic JSON. Unbounded ambiguous decoding and implicit timestamp zones could hide corrupt authentication state, while changing key or TTL semantics would break coordination compatibility.
- Consequence: Prior producer values remain byte-compatible, corrupt values fail without replacement/deletion, and the direct Redis parser leaves the allowlist. The optional store is still not integrated into the main login lifecycle; generic export remained the last FI-013 direct decoder at this decision boundary and was subsequently closed by D-073.
- ADR: `docs/adr/0091-bound-redis-session-json.md`

### D-073: Validate every public SQLite export JSON field before publication

- Date: 2026-07-27
- Decision: Maintain an exact five-field export registry; reuse audit/rule profiles; add bounded legacy-summary and matching-lineage producer/consumer profiles; validate all payloads before destination creation; preserve every valid format-v1 field shape including raw `lineage_json` text.
- Rationale: One unrestricted generic decoder hid corruption behind a plausible sentinel, lineage bypassed validation, and destination creation preceded proof that every row was exportable.
- Consequence: Corrupt/non-text state fails before files or the export audit effect, the exporter leaves the direct-parser allowlist, and valid public shapes remain compatible. Stored-row authenticity, disclosure authorization, crash-atomic multi-file replacement, malware controls, and supported throughput remain open.
- ADR: `docs/adr/0092-bound-public-database-export-json.md`

### D-074: Publish a complete integrity-bound database export directory

- Date: 2026-07-27
- Decision: Stage all nine format-v1 payloads, publish an additive exact artifact manifest, replace directories through bounded marker/rollback state, and expose explicit integrity-verifying recovery.
- Rationale: Sequential destination writes exposed partial old/new mixtures after failure and retained stale files; no closed artifact inventory supported safe recovery.
- Consequence: Valid payload shapes stay compatible and handled failures preserve the previous tree. The additive manifest changes exact file-set expectations; local observer/crash gaps, unauthenticated SHA-256, and audit/filesystem non-atomicity remain explicit.
- ADR: `docs/adr/0093-integrity-bound-database-export-publication.md`

### D-075: Deny unspecified access and remove ordinary self-approval overrides

- Date: 2026-07-27
- Decision: Require an explicit permission policy, deny supplied tenant/workspace/entity/period scopes absent immutable grants, default creator approve/review refusal on, and bind the exact current platform approval/review surface inventory to one actor identity comparator including trusted-local labels.
- Rationale: Identity alone was treated as access, ABAC fields were inert, generic override text authorized self-approval, and several local paths skipped SoD when no database user resolved.
- Consequence: Distinct-actor workflows remain compatible; self-approval and non-empty generic approval overrides fail visibly. The CLI option remains parseable but deprecated. Broader ABAC integration and privileged emergency access remain separate work.
- ADR: `docs/adr/0094-deny-by-default-scope-and-sod-policy.md`

### D-076: Close only the evidence-defined hostile-ingress gate

- Date: 2026-07-27
- Decision: Mark P0-SEC-009 complete for its exact size/type/path/decompression/formula/XML/YAML and safe-error contract after direct hostile tests, runtime-policy parity, and exact parser inventories pass; retain FI-012/FI-013 and R-018 as partial/open.
- Rationale: The recorded exit is finite and reproducible. Implicitly adding malware, authenticity, disclosure, host-loss, future-upload, connector, and throughput programs would obscure rather than govern those separate residual risks.
- Consequence: No runtime or compatibility behavior changes. Wording remains bounded and cannot claim malware absence, authenticated evidence, safe redistribution, secure upload, complete legacy-XLS inspection, or deployed effectiveness.
- ADR: `docs/adr/0095-close-bounded-file-ingress-exit-gate.md`

### D-077: Close bounded source identity separately from supported-version parity

- Date: 2026-07-27
- Decision: Mark P0-006 complete for its exact stock/GL no-row-index, permutation, partition, and cross-engine digest contract; keep supported-version and broader backend/strategy execution under P0-009.
- Rationale: Canonical multiset occurrence identity, source-location separation, signature v3, and generated Pandas/DuckDB full/forced-partition properties satisfy the written identity exit. Conflating this with the separate version matrix duplicates P0-009 and makes ownership unclear.
- Consequence: No runtime behavior changes. The claim remains bounded and excludes universal strategy/backend lineage, upstream authenticity, and physical-copy identity when the source provides no distinguishing evidence.
- ADR: `docs/adr/0096-close-bounded-source-lineage-identity-gate.md`

### D-078: Make every financial-input default strict and preserve legacy only explicitly

- Date: 2026-07-27
- Decision: Change all 52 `FinancialInputPolicy` defaults across 23 runtime files to strict v2, make Money scalar operators strict, retain legacy v1 only as an explicit compatibility argument or version-implied historical reader, and publish a breaking migration guide.
- Rationale: Warning-only legacy defaults still allowed irreversible binary approximation to affect direct Python financial decisions. Existing explicit current callers and AST inventories were insufficient while a public default remained permissive.
- Consequence: Direct Python callers passing float must migrate to exact text, `Decimal`, integers/minor units, or explicitly own a temporary legacy replay boundary. Default current artifacts advance to their strict versioned forms. Historical version readers remain compatible.
- ADR: `docs/adr/0097-make-financial-input-defaults-strict-v2.md`

### D-079: Require dependency-aware lower-bound installs and canonical null text

- Date: 2026-07-27
- Decision: Keep the exact four-cell engine matrix, but allow the exact binary-only NumPy/Pandas/DuckDB override to resolve its transitive dependencies; canonicalize missing required non-financial text to the existing empty-string representation before identity and reconciliation.
- Rationale: The first real Python 3.11 lower-bound execution proved `--no-deps` omitted Pandas 2.2's `pytz`, while DuckDB 1.0 materialized an empty CSV field as `None` and the shared string coercer converted it to the literal `"None"`, changing record identity and the digest. Neither behavior represents a financial decision difference.
- Consequence: Exact direct engine pins and binary-wheel enforcement remain unchanged. Missing required text has one backend-neutral representation, historical signature-v1 digest tests still pass, all four local cells pass without skips, and P0-009 remains open until an identified hosted run passes.
- ADR: `docs/adr/0098-engine-matrix-lower-bound-compatibility.md`

### D-080: Close supported engine parity only from the identified hosted matrix

- Date: 2026-07-27
- Decision: Close P0-009 on GitHub Actions run `30239994946` at committed revision `aaf2110`, where every declared Python/dependency cell executes the closed no-skip parity command successfully.
- Rationale: E-083 established the exact local matrix, while the backlog explicitly withheld closure until an identified hosted run proved the same four cells. The run also passes the full supported Python, live server-boundary, and Docker-parity jobs without broadening the digest claim.
- Consequence: The supported-version Pandas/DuckDB digest gate is complete. Arbitrary versions, other backends/strategies, performance, and live process/PostgreSQL crash recovery remain outside this exit and under later gates.
- ADR: `docs/adr/0050-declare-supported-engine-parity-matrix.md`, `docs/adr/0098-engine-matrix-lower-bound-compatibility.md`

### D-081: Require SRI for every npm registry lock entry

- Date: 2026-07-27
- Decision: Regenerate the npm v3 lock from the reviewed manifest, retain exact resolved versions, require HTTPS registry resolution and SRI on all 209 non-root entries, and set the policy's known integrity gap to zero.
- Rationale: The prior lock fixed versions but left 155 downloads dependent on mutable registry response metadata. npm can emit exact resolution and integrity for the same graph, so retaining the gap is unnecessary.
- Consequence: Clean installation verifies every registry tarball against the committed lock. The exact revision passed hosted Security, Docker, CI, and CodeQL runs, so P0-SEC-008's written exit is complete. This does not prove publisher provenance, package safety, reachability, licensing, malware absence, or registry availability.
- ADR: `docs/adr/0069-lock-dependencies-and-fail-closed-supply-chain-gates.md`

### D-082: Preserve protected security aggregation and advance a unique candidate version

- Date: 2026-07-27
- Decision: Restore the exact protected `python-security` status as a fail-closed aggregate over both locked Python matrix audits and the repository secret/npm job; prepare v0.7.1 as the next unique patch candidate while retaining v0.7.0 documentation as historical evidence.
- Rationale: Branch protection still required the historical context name after matrix display names changed, leaving an otherwise green PR blocked. The tag-only workflow requires `v<project-version>`, while v0.7.0 already exists and cannot identify the new merged revision.
- Consequence: PR #54 becomes clean/mergeable only when every security prerequisite and all other protected checks pass. Wheel/sdist metadata and current release links identify v0.7.1. Merge, signing-key enrollment, signed tag creation, and candidate execution remain explicit human-gated actions.
- ADR: `docs/adr/0067-tag-only-signed-release-candidate.md`, `docs/adr/0069-lock-dependencies-and-fail-closed-supply-chain-gates.md`

### D-083: Close Phase 0 only on retained signed-candidate evidence

- Date: 2026-07-27
- Decision: Close P0-SEC-006 and P0-SEC-007, and therefore the 22-task Phase 0 exit, only after PR #54 is merged, GitHub verifies signed annotated tag `v0.7.1` on exact `main` commit `d47edd8`, candidate run `30243819239` passes every fail-closed build/scan/attest/verify step, and the downloaded retained artifact independently verifies its checksums and subject-bound provenance/SBOM bundles.
- Rationale: A green pull request or workflow definition cannot prove tag identity, hosted image inventory, attestation authenticity, archive retention, or consumer verification. The combined GitHub tag API, exact-main runs, candidate job, retained artifact metadata, checksum revalidation, and independent `gh attestation verify` executions provide the evidence required by the two written exits.
- Consequence: Phase 0 is 22/22 complete as an evidence-bounded foundation milestone. The candidate remains non-publishing; SBOM completeness is unknown, OCI reproducibility and SLSA levels are unclaimed, and GitHub Release/PyPI promotion, compliance, certification, independent assurance, production readiness, real adoption, and later platform phases remain outside this closure.
- ADR: `docs/adr/0067-tag-only-signed-release-candidate.md`, `docs/adr/0068-bind-cyclonedx-sbom-to-each-release-subject.md`

### D-084: Start backend neutrality at an atomic application boundary

- Date: 2026-07-27
- Decision: Introduce a typed domain unit-of-work port and a SQLite adapter around the workspace plus first-period bootstrap use case. Keep existing direct repository constructors autocommitting by default for compatibility, but disable per-repository commits inside the unit of work so business rows and both audit events share one owned transaction.
- Rationale: The Phase 0 protocols were runtime-unused and their tests only proved structural compatibility of three SQLite classes. Migrating an atomic use case exposes transaction ownership, rollback, audit-chain, and backend-leakage requirements that isolated repository tests cannot prove.
- Consequence: Application code now depends only on domain ports and rejects malformed dates/text before opening a transaction. A second-audit failure rolls back workspace, period, first audit event, and ledger head. P1-PLAT-001 remains in progress because most platform services still depend directly on SQLite; no PostgreSQL parity or broad repository abstraction is claimed.
- Reversibility: Remove the new application/adapter modules and restore the two repository constructors; existing callers retain their default autocommit behavior throughout the slice.
- ADR: `docs/adr/0099-atomic-application-unit-of-work-port.md`

### D-085: Make all three requested phases a closed, testable execution contract

- Date: 2026-07-27
- Decision: Map every post-Phase-0 backlog task exactly once into Platform Foundation, Matching and Evidence 2.0, or Enterprise Product; add the missing enterprise and external-validation tasks; and make real pilots plus independent security review fail-closed external gates.
- Rationale: Phase 3 was absent from the executable backlog, so task-count completion could silently omit identity federation, operations, connectors, upgrade/rollback, air-gap, external pilots, or independent review. A normative machine-tested matrix prevents that scope collapse.
- Consequence: Completion requires every technical task and gate plus non-simulated external evidence. CI rejects missing/duplicate tasks, later-phase dependencies, empty gate evidence, and unsupported completion shortcuts. The matrix creates no readiness, compliance, scale, superiority, pilot, or independent-assurance claim by itself.
- ADR: `docs/adr/0100-close-phase-1-3-execution-contract.md`

### D-086: Count active service coupling instead of repository declarations

- Date: 2026-07-27
- Decision: Maintain a closed AST-tested inventory of all Platform and Application service classes, classifying direct SQLite, partial repository, and genuinely connection-free application boundaries.
- Rationale: Protocol definitions and optional repository constructor arguments do not prove that active services are backend-neutral when authorization, audit, outbox, schema, or other operations still consume a SQLite connection.
- Consequence: The measured baseline is 17 direct-SQLite Platform services, three partial-repository Platform services, and one backend-neutral Application service. P1-PLAT-001 stays in progress until implementation reduces the coupling and its behavioral contracts pass; the inventory itself is not backend parity.
- ADR: `docs/adr/0101-measure-runtime-repository-boundaries.md`

### D-087: Preserve the operations API while moving decisions behind ports

- Date: 2026-07-27
- Decision: Move operational result composition into a backend-neutral Application service, put SQLite reads and audit/migration adaptation in infrastructure, and keep `platform.OperationsService(connection)` as a thin compatibility adapter.
- Rationale: The health/jobs/errors path is active CLI behavior with a small, sanitized contract, making it a bounded first migration that proves the inventory can decrease without breaking users.
- Consequence: Direct-SQLite Platform services decrease from 17 to 16 and backend-neutral Application services increase from one to two. The compatibility adapter executes no SQL. PostgreSQL behavior and the rest of P1-PLAT-001 remain open.
- ADR: `docs/adr/0102-extract-operational-diagnostics-application-port.md`

### D-088: Make job progress and transitions versioned financial-control evidence

- Date: 2026-07-27
- Decision: Define one immutable schema-v1 job aggregate with seven closed states, integer progress, digest-addressed inputs/config/checkpoints/outputs, bounded retries, safe failure codes, tenant-scoped idempotency, and atomically persisted transition evidence.
- Rationale: Operational history and a specialized reconciliation runner did not provide a common durable application contract. A job marked complete without full progress and an output identity, or retried without a ceiling, cannot support reproducible financial operations.
- Consequence: SQLite migration 21 and a backend-neutral Application service now provide local atomic create/replay/transition/checkpoint/backup/restore behavior. Stale versions and evidence-write failures roll back. Generic leases/workers, PostgreSQL parity, authorization, scheduling, and real crash recovery remain open.
- ADR: `docs/adr/0103-versioned-durable-job-state-machine.md`

### D-089: Treat lease generation—not worker identity—as the write authority

- Date: 2026-07-27
- Decision: Fence every worker write with an exact tenant/job/owner/generation lease that expires, renews only forward, increments from immutable history on every claim, and is verified in the same transaction as checkpoints or terminal state.
- Rationale: Worker names and status flags cannot stop a pre-crash process from writing after takeover. A monotonically increasing generation makes old authority objectively stale.
- Consequence: Migration 22 and the worker Application service close the local P1-PLAT-003 exit and advance P1-PLAT-004. Real process reconnection retains the committed checkpoint; stale writes fail. External workload effects, PostgreSQL parity, and host loss remain unproven.
- ADR: `docs/adr/0104-generation-fenced-job-worker-leases.md`

### D-090: A checkpoint is valid only with its committed partition effect

- Date: 2026-07-27
- Decision: Persist each deterministic partition effect, cumulative progress, checkpoint/final transition, and lease evidence in one fenced transaction; resume by enumerating immutable committed effects.
- Rationale: Checkpoint-only durability can duplicate output or skip missing output depending on which side of a crash commits first.
- Consequence: Migration 23 and the safe partition-worker methods close P1-PLAT-004's local exit. Uninterrupted and restarted runs have identical semantic outputs and no duplicate partition. External systems remain outside the atomic SQLite resource and need independent controls.
- ADR: `docs/adr/0105-atomic-partition-effects-and-checkpoints.md`
### D-091: PostgreSQL durable-job operations own transactions and fencing

- **Decision**: Implement the same backend-neutral durable-job ports through a PostgreSQL adapter whose operations set transaction-local tenant scope, atomically compare versions, and fence every worker write by owner, generation, and unexpired lease. Claims use row locks with `SKIP LOCKED`; effects and transitions are append-only.
- **Reason**: Method-name similarity is not backend parity. Real concurrency, connection loss, RLS, and migration rollback must be exercised on PostgreSQL.
- **Consequence**: E-095 proves this boundary on PostgreSQL 17 and compares its semantic effects with SQLite. It does not close P1-PLAT-002 for unrelated repository boundaries.

### D-092: Preserve the local workspace contract behind a PostgreSQL UoW

- **Decision**: Bind the current workspace/initial-period ports to a tenant-specific PostgreSQL unit of work. Use dedicated `domain_` compatibility tables, forced RLS, one transaction, an append-only audit chain, and row-locked chain-head serialization.
- **Reason**: Reusing enterprise Organization/FiscalPeriod tables would silently change the current local-first domain contract. A compatibility adapter enables measured backend parity while canonical-model migration remains explicit.
- **Consequence**: E-096 proves atomicity, rollback, tenant isolation, concurrency, audit verification, and SQLite semantic parity. The compatibility tables are not an enterprise canonical-model claim.

### D-093: Operational health reports storage mode from its adapter

- **Decision**: Add `is_local_only` to the operational repository port and support integer SQLite plus string Alembic revisions. PostgreSQL diagnostics use forced-RLS tables and the shared audit verifier.
- **Reason**: Hard-coded `local_only=true` becomes false information as soon as the same Application service runs on PostgreSQL.
- **Consequence**: E-097 preserves the response field while reporting it accurately and proves record-shape/RLS parity. It does not certify future diagnostic writers as redaction-complete.

### D-094: Object identity is immutable across local and S3 adapters

- **Decision**: Put evidence bytes behind one tenant-scoped protocol whose local and S3 adapters reject overwrite, bound reads and writes, verify checksum and tenant metadata, disable delete by default, and honor configured retention.
- **Reason**: A provider-specific class or unchecked local path cannot provide a portable evidence boundary, and an ordinary S3 delete marker does not prove deletion of a retained version.
- **Consequence**: E-098 closes P1-PLAT-005's bounded exit, including live MinIO object-lock behavior. Local two-file publication fails closed after interruption but is not pair-atomic or authenticated against a malicious local writer.
- **ADR**: `docs/adr/0109-immutable-object-store-contract.md`

### D-095: Bind idempotency to request bytes and a short-lived owner capability

- **Decision**: Reserve tenant/scope/key atomically against a request digest, store only the owner-capability digest, complete before canonical expiry, and replay a bounded digest-verified response.
- **Reason**: A key alone cannot distinguish a legitimate retry from reuse for different financial input, and a plaintext owner token would turn persistence or backup access into execution authority.
- **Consequence**: E-099 closes P1-PLAT-006 for generic requests while preserving the specialized durable-job contract. Middleware composition and capability generation remain caller responsibilities.
- **ADR**: `docs/adr/0110-atomic-request-idempotency.md`

### D-096: Authenticate keyset cursors and bind them to query context

- **Decision**: Encode a stable keyset position and authenticate it with an operator-owned HMAC key while binding it to resource, tenant, filters, order, direction, and a stable ID tie-breaker.
- **Reason**: Offset movement can skip/repeat records, while unsigned or cross-context cursors permit position and scope manipulation.
- **Consequence**: E-100 closes P1-PLAT-007 for the backend-neutral contract and local evidence route. Tokens are not confidential, key rotation invalidates them, and PostgreSQL native keyset execution remains explicitly open.
- **ADR**: `docs/adr/0111-signed-keyset-pagination.md`

### D-097: Fail application construction for unclassified authorization surfaces

- **Decision**: Route enforcement through one central evaluator, annotate immutable permission dependencies, classify every API operation, and digest the normalized route map at application construction.
- **Reason**: A policy engine beside direct membership checks does not prevent drift, and an undocumented new route can silently escape a permission-to-action review.
- **Consequence**: E-101 closes P1-PLAT-008 for the current API/platform/Studio/workflow surfaces. Redacted decision logs are operational audit evidence, not a tamper-evident retained ledger.
- **ADR**: `docs/adr/0112-central-policy-enforcement-and-route-inventory.md`

### D-098: Require explicit exporter injection and a closed telemetry schema

- **Decision**: Keep observability disabled/no-export by default, use isolated OpenTelemetry providers when enabled, and reject every attribute outside a bounded low-cardinality allowlist.
- **Reason**: Environment-driven auto-export or arbitrary span attributes can create hidden egress and disclose tenant or financial data.
- **Consequence**: E-102 closes P1-PLAT-009's code-level trace/metric/log-correlation baseline. Collector security, sampling, retention, dashboards, alerting, and SLO operation remain deployment evidence.
- **ADR**: `docs/adr/0113-no-export-by-default-opentelemetry-baseline.md`

### D-099: Encrypt local backups with operator-owned authenticated keys

- **Decision**: Keep the versioned plaintext compatibility format and add an optional AES-256-GCM envelope whose exact 32-byte key is read only from an operator-supplied local file.
- **Reason**: Checksums detect change but neither conceal credential verifier and financial data nor authenticate it against an attacker who can rewrite both files.
- **Consequence**: E-103 adds bounded authenticated local backup and fail-safe restore without mandatory networking or dependencies. Temporary plaintext, key custody/rotation, PostgreSQL backup, centralized authorization, and real DR exercises remain open, so P1-PLAT-010 is not complete.
- **ADR**: `docs/adr/0114-operator-keyed-local-backup-envelopes.md`

### D-100: Restore PostgreSQL into a new verified database or remove it

- **Decision**: Invoke prevalidated native tools through closed shell-free argv and libpq service names, stream-encrypt dumps, require central operation permissions, and restore only into a new database that is verified or dropped on failure.
- **Reason**: Restoring over an active database cannot provide a safe rollback boundary, while credentials in argv and arbitrary tool lookup expand disclosure and command-execution risk.
- **Consequence**: E-104 verifies the adapter contracts and a PostgreSQL 17 native restore/failed-restore drill. Cross-platform adapter execution, service-file custody, managed keys, HA/cutover, host loss, and RPO/RTO remain open; the matrix is partial.
- **ADR**: `docs/adr/0115-isolated-postgresql-native-restore.md`

### D-101: Bind matching behavior to an exact strategy manifest

- **Decision**: Put matching behind an immutable typed protocol and exact-version registry, publish its manifest and limits, and digest the manifest, permutation-invariant inputs, and complete decisions.
- **Reason**: A generic matcher method cannot distinguish strategy capabilities or reproduce a decision after algorithms and defaults evolve.
- **Consequence**: E-105 closes P1-REC-001 while preserving current one-to-one output compatibility. Candidate accounting, grouped strategies, explanation v2, and measured scale remain open tasks.
- **ADR**: `docs/adr/0116-versioned-matching-strategy-contract.md`

### D-102: Binary-search exact Decimal amount windows

- **Decision**: Partition right-side amounts by currency/precision, sort exact Decimal values with stable record keys, and use inclusive binary-search boundaries for tolerance lookup.
- **Reason**: Scanning and reparsing every distinct amount bucket for each left record defeats indexed candidate generation even though it avoids a literal row cross product.
- **Consequence**: E-106 closes P1-REC-002 with logarithmic boundary lookup and unchanged existing outputs. Returned candidates still require linear scoring, and caps/time/search budgets remain P1-REC-003.
- **ADR**: `docs/adr/0117-exact-decimal-range-index.md`

### D-103: Exceeding a candidate budget is ambiguity, never truncation

- **Decision**: Count stable indexed candidates before scoring, cap one left record at 10,000 and one run at 1,000,000 evaluations, and select none for an over-budget record while emitting explicit ambiguity evidence.
- **Reason**: Choosing the first N candidates would turn a resource safeguard into an arbitrary financial decision, while wall-clock time alone is not reproducible across machines.
- **Consequence**: E-107 closes P1-REC-003 with deterministic search budgets and fail-closed output. Configurable/grouped budgets and infrastructure watchdogs remain separate.
- **ADR**: `docs/adr/0118-fail-closed-candidate-budgets.md`

### D-104: True grouped sums use a separate bounded strategy

- **Decision**: Introduce `bounded-grouped-subset-sum@1.0.0` rather than relabeling the legacy pair-capacity flags. Enforce exact Decimal sums, currency/partition/date/cardinality constraints, stable tie-breaks, and a deterministic 25,000-evaluation fail-closed budget.
- **Why**: Reusing individually equal edges is not grouped financial reconciliation, while unrestricted subset search is unsafe and non-operational.
- **Consequence**: E-108 closes P1-REC-004 for one group per request. Batch group assignment, FX/netting governance, governed ambiguity, and throughput evidence remain open.
- **ADR**: `docs/adr/0119-bounded-true-grouped-matching.md`

### D-105: Make grouped matching fee- and netting-aware by explicit policy

- **Decision**: Extend grouped matching through explicit `netting_mode` and explicit source fee fields, with `gross` preserving previous behavior and `net` comparing gross minus fees. Keep grouped strategy requests deterministic and stable by versioning new knobs.
- **Reason**: Invoices, commissions, fees, and settlement drag are part of financial meaning. Ignoring them in group reconciliation breaks traceability and can create irreconcilable exceptions.
- **Consequence**: E-109 enables fee totals and net totals in grouped decisions without changing public legacy pair-capacity flags. Strategy requests now require explicit fee field names in `net` mode and persist fee/net metrics in explainable outputs. FX-aware matching remains a separate planned slice.
- **ADR**: `docs/adr/0120-fee-aware-netting-in-grouped-matching.md`

### D-106: Make grouped matching FX-aware with explicit conversion contracts

- **Decision**: Add `target_currency` and `fx_rates` to grouped matching requests, with
  deterministic rate selection based on pair + effective date and strict, reversible failure when conversion is missing.
- **Reason**: Currency-mixed records are common across reconciliation domains; without explicit FX policy, conversions are either implicitly assumed (silent) or non-reproducible.
- **Consequence**: E-110 propagates FX-aware conversion from strategy contract to application service, parses versioned rate metadata (`base/quote/source/rate_type/rate/effective_at`) and enforces inversion for reverse pairs. Conversion mismatches now fail-closed instead of silently normalizing to record currency.
- **ADR**: `docs/adr/0121-fx-aware-grouped-matching.md`

### D-107: Govern tied grouped outcomes as ambiguity

- **Decision**: For grouped matching, ties across equal minimum business-cost candidates must not be resolved automatically. Grouped matching now emits `status="ambiguous"` and `reason_code="GROUP_MATCH_AMBIGUOUS"` when multiple candidates share identical `difference`, `cardinality`, and `date-span`, and publishes every tied candidate set through `ambiguous_candidate_sets`.
- **Reason**: Determinism is achieved by deterministic ordering, not by hidden automatic tie selection. Without explicit governed ambiguity, equal outcomes can still be operationally arbitrary and under-explained.
- **Consequence**: E-111 introduces explicit ambiguity governance for grouped ties. Matched status remains single-selection only when exactly one minimum-cost candidate exists; bounded search-overflow still uses `GROUP_SEARCH_BUDGET_EXCEEDED`.
- **ADR**: `docs/adr/0122-explicit-grouped-matching-ambiguity-governance.md`

### D-108: Use grouped matching explanation schema v2 with explicit ambiguity evidence

- **Decision**: Publish grouped matching explanation and runtime contract under `grouped-matching-explanation-v2`, and include `ambiguous_candidate_sets` in grouped outputs whenever governance review is required.
- **Reason**: Without v2-aligned explainability, governance teams cannot trace all tied candidates from deterministic outputs.
- **Consequence**: E-112 aligns the architecture strategy registry, runtime manifest, and grouped decision payload to v2 and surfaces concrete ambiguity sets in all tied-group governance outcomes while keeping backward-compatible fields intact.
- **ADR**: `docs/adr/0123-grouped-matching-explanation-v2-and-ambiguous-candidate-evidence.md`

### D-113: Add reproducible reconciliation benchmark tiers for 10K and 100K synthetic profiles

- **Date**: 2026-07-27
- **Context**: Phase 2 closure requires measured 10K and 100K hardware-scoped execution evidence rather than only functional correctness claims.
- **Decision**: Extend the local deterministic benchmark stack with a profile-based suite API that emits checksummed per-profile artifacts and a suite-level digested manifest.
- **Rationale**: Reproducible matching performance must be tied to the same deterministic core behavior used for correctness and compatibility gates before release claims about scale are accepted.
- **Consequence**: E-113 adds `run_reconciliation_execution_benchmark_suite`, suite manifest emission, output SHA-256 inventory, and environment metadata capture for each profile. 10K and 100K synthetic executions are now measured and reproducible.
- **Reversibility**: Suite format is additive and version-free from the perspective of existing behavior; profile IDs and metrics are explicit.
- **ADR**: None.

### D-114: Add deterministic regression assertions for benchmark outcomes

- **Date**: 2026-07-27
- **Context**: Performance tuning can change timing without visible correctness drift, and timing-only checks miss candidate/exhaustive-result regressions.
- **Decision**: Add closed-form regression assertion helpers for reconciliation benchmark suites that verify result counts, match/exception counts, candidate counts/means, signature behavior, and bounded runtime/CPU/memory growth.
- **Rationale**: A release gate must prevent silent correctness drift and unbounded resource growth while still allowing controlled threshold tuning through explicit policy.
- **Consequence**: E-114 adds `assert_reconciliation_execution_regression` and profile-level invariant checks for matched/exception counts, candidate telemetry, signature equality (optional), and runtime/CPU/memory budgets.
- **Reversibility**: Assertion thresholds are explicitly parameterized and can be widened for controlled re-baselines.
- **ADR**: None.

### D-115: Evidence Graph v1 schema, manifest integrity, and redaction contracts

- **Date**: 2026-07-27
- **Context**: P2-001 required a versioned evidence lineage envelope with deterministic integrity and safe redaction for sensitive payload fields before enabling downstream drill-down and audit exports.
- **Decision**: Make Evidence Graph payloads explicitly versioned with fixed `artifact_type` and `schema_version`, enforce node data-classification/retention metadata, make manifest hashing deterministic over nodes and edge metadata, add tamper verification, and export redacted payload views using declared redaction masks.
- **Rationale**: Financial and operational lineage cannot be trusted when graph hashes ignore edge context or can be altered without detection; sensitive fields must stay masked in constrained views while retaining audit continuity.
- **Consequence**: E-115 adds `docs/schemas/evidence_graph.schema.json`, upgrades `reconforge/evidence/graph.py` with manifest verification and redaction, and extends `test_phase2_deliverables.py` with schema + tamper + redaction regressions.
- **Reversibility**: Redaction policy and schema versioning are additive; any contract expansion must use a versioned manifest migration.
- **ADR**: `docs/adr/0125-evidence-graph-manifest-schema.md`

### D-116: Evidence drill-down uses bounded pages and audits successful reads

- **Date**: 2026-07-28
- **Context**: P2-002 required explainable evidence-to-object traversal without exposing local paths, checksums, or storage references to every evidence reader and without allowing an unbounded graph response.
- **Decision**: Keep one additive `/api/v1/evidence/records/{evidence_id}/drill-down` contract across SQLite and PostgreSQL, fail closed above eight levels or 10,000 discovered nodes, expose deterministic offset pages of at most 1,000 nodes with incident-edge semantics, redact provenance by default, require `evidence.manage` for sensitive views, and append access-audit events without publishing business outbox messages.
- **Rationale**: Graph traversal is operationally useful only when consumers can reason about page boundaries, authorization, and access history. A read audit is governance evidence but is not a domain event.
- **Consequence**: E-117 closes the bounded code contract for P2-002. Cursor pagination, authenticated manifest serving, a graph explorer, live PostgreSQL evidence, and supported throughput remain separate gates.
- **Reversibility**: The route is additive. Page defaults and ceilings can evolve through explicit API compatibility policy; removing masking or access auditing would require a security decision.
- **ADR**: `docs/adr/0127-bounded-audited-evidence-drill-down.md`

### D-117: Reconciliation-as-Code v1 is declarative and matching simulation is adapter-only

- **Date**: 2026-07-28
- **Context**: P2-003/P2-004 require versioned rule packs, deterministic review, golden cases, diff/simulation, and rollback without turning YAML into an arbitrary code execution surface or implying that unimplemented rule stages run.
- **Decision**: Define a closed v1 schema with bounded YAML/JSON ingress, exact decimal strings, typed data-only steps, explicit human approval, canonical SHA-256 manifests, embedded synthetic fixtures, registered matching adapter execution, deterministic structural diff, no-side-effect simulation plans, and atomic validated file rollback. Validation/normalization declarations remain non-executable until separate adapters exist.
- **Rationale**: A narrower honest execution boundary is safer and more reproducible than executing arbitrary expressions or reporting a simulated full pipeline that does not exist.
- **Consequence**: E-118/E-119 close P2-003/P2-004 for `matching-adapter-only-v1`; Rule Studio publication, signatures, control-pack installation, and full validation/normalization execution remain planned.
- **Reversibility**: Major contract changes require a new schema version and compatibility reader. The historical `normalization_rules` key is accepted and canonicalized to `normalization`.
- **ADR**: `docs/adr/0126-reconciliation-as-code-v1-execution-boundary.md`

### D-118: Bind PostgreSQL outbox repositories to one tenant at the application boundary

- **Date**: 2026-07-28
- **Context**: The shared outbox application service expects a tenant-free repository protocol, while PostgreSQL correctly requires an explicit tenant on every persistence operation.
- **Decision**: Add a tenant-bound PostgreSQL adapter that validates and captures one tenant, delegates every operation with that scope, maps event/status fields, and translates repository errors. Preserve the existing low-level PostgreSQL repository and SQLite compatibility facade.
- **Reason**: Capturing scope once prevents accidental tenant omission or mixing while allowing one application orchestration path across backends.
- **Consequence**: E-120 advances P1-PLAT-001/002 without claiming live PostgreSQL parity. Because PostgreSQL has no dead-letter transition timestamp column, the optional shared field remains null rather than receiving invented evidence.
- **Reversibility**: The adapter is additive. It can be removed without changing the low-level repository or persisted schema.

### D-119: Extract the shared exception queue without changing its public local API

- **Date**: 2026-07-28
- **Context**: One direct-SQLite queue is called from four finance/control services plus CLI, API, Studio, and demos, making it a central coupling point.
- **Decision**: Introduce a complete typed application port and delegation service, move SQLite behavior into infrastructure, and retain `ExceptionQueueService(connection, autocommit=...)` as a SQL-free compatibility facade.
- **Reason**: This establishes one stable use-case contract before adding PostgreSQL and avoids simultaneously rewriting all existing callers.
- **Consequence**: E-121 reduces direct-SQLite Platform services from 14 to 13 while preserving behavior. PostgreSQL parity remains explicitly unproven.
- **Reversibility**: The facade preserves imports, constructor arguments, methods, return shapes, error type, and constants; reverting the wiring requires no data migration.

### D-120: Keep approval SoD inventory attached to the enforcing implementation

- **Date**: 2026-07-28
- **Context**: Extracting ApprovalService behind an application port would leave its compatibility facade without the `same_actor` calls that the AST security inventory historically inspected.
- **Decision**: Move SQLite behavior behind a typed application port, preserve the public facade, and explicitly route approval-surface discovery and guard inspection to `SQLiteApprovalRepository` for the extracted approval methods.
- **Reason**: Security evidence must inspect the code that enforces requester/preparer separation, not a delegating wrapper.
- **Consequence**: E-122 advances repository separation while keeping SoD regression evidence meaningful. PostgreSQL and central policy parity remain future gates.
- **Reversibility**: Public APIs and persisted schemas are unchanged; inventory paths can move again when enforcement moves into a richer application policy service.

### D-121: Keep Mapping Studio preview browser-local, bounded, and non-publishing

- **Date**: 2026-07-28
- **Context**: P2-005 needs a usable mapping workflow without creating an unbounded upload surface or hiding invalid financial text.
- **Decision**: Parse bounded CSV/TSV previews in-browser, require explicit canonical mappings, preserve raw text, render invalid values as issues, and provide no persistence or publication action in this foundation.
- **Reason**: A reviewable mapping is safer and more honest than an implicit import path without provenance, approval, or server-side validation.
- **Consequence**: E-123 closes P2-005 while persistence, signed/versioned mapping artifacts, malware controls, source authentication, and execution remain later gates.
- **Reversibility**: The route and parser are additive and store no data.
- **ADR**: `docs/adr/0128-bounded-browser-local-mapping-preview.md`

### D-122: Bind local Rule Studio approval to the exact tested digest

- **Date**: 2026-07-28
- **Context**: A rule editor can falsely imply governance if a user tests one draft and approves another or can self-approve without review evidence.
- **Decision**: Use a local draft/tested/approved state machine; revoke evidence on edit; test exact amounts with scaled integers; bind approval to canonical SHA-256; require a different reviewer and reason; and expose no publication action.
- **Reason**: Tested-content identity and fail-closed SoD are the minimum honest foundation for a future governed rule lifecycle.
- **Consequence**: E-124 closes P2-006 locally while durable identity, audit, signatures, server execution, and publication remain explicitly absent.
- **Reversibility**: The route and state module are additive and persist no data.
- **ADR**: `docs/adr/0129-local-rule-studio-governance-state-machine.md`

### D-123: Fail closed when the live Studio contract is unavailable

- **Date**: 2026-07-28
- **Context**: P2-007 requires a browser-visible live contract, but silently substituting synthetic showcase data after an authorization, network, or schema failure would misrepresent operational state.
- **Decision**: Read the existing same-origin `metrics.read`-guarded dashboard endpoint, validate a closed envelope and allowlisted metric fields, preserve exact value text, calculate freshness client-side, and expose every failure as an explicit retryable state. Never request a synthetic artifact from the live loader.
- **Reason**: Reviewers must be able to distinguish authorized current data, no data, stale data, and unavailable data without ambiguity.
- **Consequence**: E-125 closes P2-007 locally; deployed identity/session behavior, live PostgreSQL execution, signed response provenance, and production availability remain unproven.
- **Reversibility**: The route, loader, and types are additive and read-only.
- **ADR**: `docs/adr/0130-live-studio-fail-closed-contract.md`

### D-124: Make accessibility an executable cross-route release gate

- **Date**: 2026-07-28
- **Context**: Isolated RTL and preference tests did not prove semantic validity, contrast, focus containment/restoration, masking, or regressions across the new Mapping, Rule, and Live Studio routes.
- **Decision**: Add axe-core WCAG 2 A/AA and WCAG 2.1 A/AA scans to Chromium E2E, exercise every native route in English and Arabic/RTL plus mobile landmarks in both directions, verify keyboard and preference behavior separately, and preserve a minimum visible focus indicator even when the optional strong-outline preference is disabled.
- **Reason**: Accessibility behavior must fail the same executable gate as functional workflows; a user preference cannot disable the minimum keyboard focus requirement.
- **Consequence**: E-126 closes P2-008 with automated evidence while manual assistive-technology, cognitive, zoom/reflow, and independent conformance assessment remain explicit limitations.
- **Reversibility**: The gate and token changes are additive/revertible; no data migration is needed.
- **ADR**: `docs/adr/0131-accessibility-localization-regression-gate.md`

### D-125: Extract journal controls as one atomic application port

- **Date**: 2026-07-28
- **Context**: Journal import and policy execution mixed input normalization, exact financial comparisons, SQL, unified exceptions, audit, and outbox effects inside a connection-bound Platform service.
- **Decision**: Define one complete application protocol for import, policy run, exception reads, and reports; move SQLite behavior to infrastructure; call the SQLite exception repository directly within the shared transaction; and retain a SQL-free historical Platform facade.
- **Reason**: Splitting only reads or writes would leave transaction ownership and policy effects coupled. One complete port preserves atomic financial-control behavior while enabling a later PostgreSQL adapter.
- **Consequence**: E-127 reduces direct-SQLite Platform services to 11 and adds explicit handled-failure rollback. It does not establish PostgreSQL journal parity or broaden the existing local authorization model.
- **Reversibility**: Public constructor, methods, defaults, result type, persisted schema, policy codes, and output shapes remain unchanged; no migration is required.
- **ADR**: `docs/adr/0132-journal-control-application-boundary.md`

### D-126: Bind ineffective control exceptions to the test plan workspace

- **Date**: 2026-07-28
- **Context**: Control test plans persist a workspace ID, but ineffective-result handling historically passed the literal `default` workspace into the unified exception queue.
- **Decision**: Extract the complete control-testing surface behind one application port, resolve the plan's persisted workspace name inside the SQLite adapter, and create the unified exception within that exact scope and transaction.
- **Reason**: Cross-workspace exception leakage contradicts tenant/workspace boundaries and makes result evidence inconsistent with its plan.
- **Consequence**: E-128 fixes the local scope defect and proves rollback across result, plan status, exception, and audit. PostgreSQL parity and stronger tenant authorization remain future gates.
- **Reversibility**: Public methods and schemas are unchanged. Reverting the adapter would reintroduce the scope defect and is not an acceptable operational rollback.
- **ADR**: `docs/adr/0133-control-testing-workspace-atomic-boundary.md`

### D-127: Share journal policy semantics and keep PostgreSQL effects atomic

- **Date**: 2026-07-28
- **Context**: Implementing PostgreSQL journal persistence by copying SQLite policy logic would allow financial-control decisions to drift between backends, while separate exception/audit/outbox transactions could leave incomplete evidence.
- **Decision**: Move deterministic policy evaluation to a database-free domain helper; make both adapters consume exact decimal text; bind the PostgreSQL adapter to one validated tenant; and persist journal exceptions, unified control exceptions, audit-chain evidence, and outbox messages inside the caller operation transaction under forced RLS.
- **Reason**: Backend parity requires one decision function and one business-effect boundary, not merely similar table shapes.
- **Consequence**: E-129 adds code and optional live parity coverage. Its build gate also makes the Alembic configuration, environment, template, and revisions explicit sdist/wheel data and tests those declarations. Live non-superuser RLS behavior remains unproven in this environment, so P1-PLAT-002 stays open.
- **Reversibility**: Migration 0016 drops only the three additive tables; the SQLite schema and public application contract are unchanged.
- **ADR**: `docs/adr/0134-postgres-journal-contract-parity.md`

### D-128: Bind PostgreSQL control testing to tenant, workspace, and one effect boundary

- **Date**: 2026-07-28
- **Context**: The extracted control-testing application port had complete SQLite behavior but no server adapter; implementing only its primary rows would leave ineffective-result exceptions and evidence outside the business transaction.
- **Decision**: Add four tenant-keyed PostgreSQL tables under forced RLS and implement all seven port methods. Resolve plans and controls inside the tenant scope, persist ineffective-result exceptions with the plan workspace, and append domain audit plus transactional outbox effects before committing each mutation. Package the shared migration SQL loader as an importable module and verify revision import from an installed wheel.
- **Reason**: Backend parity is the equality of scoped business effects and failure behavior, not just compatible method signatures or row counts.
- **Consequence**: E-130 supplies code-contract, post-write rollback, installed-artifact, and optional live parity coverage. Live non-superuser PostgreSQL evidence remains unavailable locally, so P1-PLAT-002 stays open.
- **Reversibility**: Migration 0017 drops only its four additive tables. The shared control-exception table, SQLite schema, public application contract, and compatibility facade remain unchanged.
- **ADR**: `docs/adr/0135-postgres-control-testing-contract-parity.md`

### D-129: Treat constant durable-job identifiers as reviewed Bandit exceptions

- **Date**: 2026-07-28
- **Context**: Bandit B608 reported seven durable-job statements because fixed column identifiers are assembled from immutable module tuples. Row values, tenant IDs, job IDs, and timestamps already use driver placeholders.
- **Decision**: Retain the fixed identifier construction, add narrowly scoped `nosec B608` annotations at only the reported expressions, and document why each exception cannot contain user-controlled identifiers. Keep the complete SQLite/PostgreSQL durable-job regression as behavioral evidence.
- **Reason**: Replacing constant identifier lists with duplicated query literals increases column-order drift risk without reducing injection exposure; broad Bandit configuration exclusions would hide unrelated future findings.
- **Consequence**: The repository-wide Bandit command returns exit 0 with no findings and visible reviewed-suppression notices. Any future dynamic identifier source requires a new security decision and validation.
- **Reversibility**: Each annotation is local and can be replaced by a typed SQL composition API or literal statement without schema or application-contract changes.
- **ADR**: `docs/adr/0136-durable-job-static-sql-identifiers.md`

### D-130: Extract intercompany cases as one exact, atomic application boundary

- **Date**: 2026-07-28
- **Context**: Intercompany import, Decimal aggregation, imbalance case creation, unified exceptions, settlement, audit, and outbox effects were coupled to a SQLite connection in the Platform layer. Settlement of a missing case committed audit/outbox evidence before the subsequent read reported that no case existed.
- **Decision**: Move all five public use cases behind one typed application port and SQLite adapter; use the extracted exception repository within the shared transaction; add stable transaction IDs to ordering; explicitly roll back handled failures; and require exactly one updated case before emitting settlement evidence.
- **Reason**: Intercompany balances and case evidence must be reproducible and cannot claim a settlement for a nonexistent case. A complete boundary enables later PostgreSQL parity without splitting financial effects.
- **Consequence**: E-132 reduces direct-SQLite Platform services to nine and removes the orphan-evidence path. PostgreSQL parity and richer entity/currency authorization remain open.
- **Reversibility**: Public constructor, methods, defaults, result import, persisted schema, exact decimal text, case IDs, and CLI calls remain compatible. Reintroducing settlement evidence for a missing case is not an acceptable rollback.
- **ADR**: `docs/adr/0137-intercompany-application-boundary.md`

### D-131: Preserve exact intercompany effects under tenant-bound PostgreSQL

- **Date**: 2026-07-28
- **Context**: The complete intercompany application port had only a SQLite adapter. A partial server implementation could diverge in Decimal aggregation, case identity, exception scope, or settlement evidence while exposing cross-tenant rows.
- **Decision**: Add migration 0018 and a complete PostgreSQL repository using NUMERIC plus canonical decimal text, composite tenant/workspace keys, forced RLS, stable grouping order, the shared control-exception queue, and one transaction for domain, audit, and outbox effects. Require a successful tenant-scoped case update before settlement evidence.
- **Reason**: Backend parity means the same exact imbalance decision and atomic evidence effects, not merely compatible table or method names.
- **Consequence**: E-133 supplies local schema, pre/post-write rollback, missing-case, packaging, and optional live parity coverage. Live non-superuser PostgreSQL behavior remains unavailable locally, so P1-PLAT-002 stays open.
- **Reversibility**: Migration 0018 drops only the two additive tables. The SQLite adapter, application contract, compatibility facade, and shared exception table remain unchanged.
- **ADR**: `docs/adr/0138-postgres-intercompany-contract-parity.md`

### D-132: Make close dependencies acyclic and close evidence entity-bound

- **Date**: 2026-07-28
- **Context**: The local close service mixed 11 use cases, SQLite, readiness mutation, dependency policy, and audit commits. It allowed self/transitive dependency cycles and could append reopen audit evidence for a nonexistent period.
- **Decision**: Extract the complete surface behind one application port and SQLite adapter; preserve exact Decimal readiness; reject a dependency when the proposed target already reaches the source; validate and update exactly one period before reopen evidence; and keep the historical facade SQL-free.
- **Reason**: Cyclic close tasks can never satisfy completion prerequisites, and audit evidence must never state that a missing accounting period was reopened.
- **Consequence**: E-134 reduces direct-SQLite Platform services to eight and closes both local invariant defects. The separate PostgreSQL close repository still does not implement this application contract.
- **Reversibility**: Public methods, internal compatibility flags, defaults, result type, schema, task IDs, and readiness calculation remain compatible. Restoring cycles or orphan evidence is not an acceptable rollback.
- **ADR**: `docs/adr/0139-close-management-application-boundary.md`

### D-133: Keep account workflow and exact balances in one repository boundary

- **Date**: 2026-07-28
- **Context**: Trial-balance import, templates, exact balances/materiality, workflow transitions, SoD review, roll-forward, audit, and outbox effects were implemented directly in a SQLite-bound Platform service.
- **Decision**: Extract the complete 11-use-case surface behind one application protocol and SQLite adapter; preserve the existing WorkflowService transaction participation and finalize each business operation only with its outbox and audit effects.
- **Reason**: Separating only account rows from workflow or evidence would allow backend adapters to diverge in lifecycle state or commit partial financial-control effects.
- **Consequence**: E-135 reduces direct-SQLite services to seven. Exact Decimal and transition rollback tests remain executable; PostgreSQL account parity remains open.
- **Reversibility**: Public methods, constructor, result import, statuses, schema, IDs, CLI, and backup format remain compatible.
- **ADR**: `docs/adr/0140-account-reconciliation-application-boundary.md`

### D-134: Commit linked evidence and both evidence events atomically

- **Date**: 2026-07-28
- **Context**: Registering evidence with an object link committed the link audit/outbox before the evidence-registration audit. A failure in the second audit could leave a partially evidenced registration.
- **Decision**: Extract all eight registry use cases behind an application port; define object storage structurally without infrastructure imports; append link audit/outbox without committing; and let the final registration audit commit the registry row, link, both audits, and both outbox effects together.
- **Reason**: Evidence lineage is not trustworthy when a link or its audit can survive without the registration event that owns it.
- **Consequence**: E-136 reduces direct-SQLite services to six and proves second-audit rollback across all four ledgers. Existing local/S3 behavior and sensitive drill-down controls remain compatible.
- **Reversibility**: Public constants, result type, object-store behavior, service constructor, API/CLI/Studio imports, schemas, and graph response shapes remain unchanged. The split-commit defect must not be restored.
- **ADR**: `docs/adr/0141-evidence-registry-application-boundary.md`

### D-135: Keep all governed finance-core invariants behind one typed port

- **Date**: 2026-07-28
- **Context**: The 18 chart, account, dimension, journal, entry, and trial-balance use cases mixed their public contract with SQLite persistence and transaction ownership.
- **Decision**: Extract the complete surface into a connection-free Application protocol and SQLite adapter; retain the historical constructor, constants, summary type, and atomic integrity-test seam through a SQL-free facade.
- **Reason**: Backend substitution must preserve balance, exact currency precision, period, dimension, account, SoD, immutability, audit, and rollback rules as one contract rather than a partial CRUD abstraction.
- **Consequence**: E-137 reduces direct-SQLite Platform services to four. PostgreSQL finance-core parity remains unproven and P1-PLAT-001/002 stay open.
- **Reversibility**: No schema or stored data changed. The facade can be redirected without a data migration; weakening financial or atomicity invariants is not an acceptable rollback.
- **ADR**: `docs/adr/0142-finance-core-application-boundary.md`

### D-136: Keep inventory quantities and movement effects behind one typed port

- **Date**: 2026-07-28
- **Context**: Nineteen inventory-master, movement, balance, and control use cases mixed their public contract with SQLite persistence and transaction ownership.
- **Decision**: Extract the complete surface into a connection-free Application protocol and SQLite adapter; preserve the historical constructor, constants, summary, and fault-injection seams through a SQL-free facade.
- **Reason**: Backend substitution must preserve scaled quantities, stock direction, periods, locations, tracking, negative-stock policy, posting/voiding, audit, and rollback as one contract.
- **Consequence**: E-138 reduces direct-SQLite Platform services to three. PostgreSQL inventory parity remains unproven and P1-PLAT-001/002 stay open.
- **Reversibility**: No schema or stored data changed. The facade can be redirected without migration; weakening quantity or atomicity invariants is not an acceptable rollback.
- **ADR**: `docs/adr/0143-inventory-core-application-boundary.md`

### D-137: Keep purchase-to-pay financial effects behind one typed port

- **Date**: 2026-07-28
- **Context**: Fifteen supplier, PO, receipt, invoice, approval, match, and read use cases mixed their public contract with SQLite transactions.
- **Decision**: Extract the complete surface into a connection-free Application protocol and SQLite adapter; move immutable input/result types to Application and preserve Platform imports through a SQL-free facade.
- **Reason**: Backend substitution must preserve integer minor units, exact quantity, idempotency, optimistic concurrency, SoD, three-way-match exceptions, audit, and outbox as one contract.
- **Consequence**: E-139 reduces direct-SQLite Platform services to two. PostgreSQL payables parity remains unproven and P1-PLAT-001/002 stay open.
- **Reversibility**: No schema or stored data changed. The facade can be redirected without migration; weakening financial or atomicity invariants is not an acceptable rollback.
- **ADR**: `docs/adr/0144-payables-application-boundary.md`

### D-138: Keep receivable credit and allocation effects behind one typed port

- **Date**: 2026-07-28
- **Context**: Thirteen customer, invoice, receipt, allocation, exposure, aging, and approval use cases mixed their public contract with SQLite transactions.
- **Decision**: Extract the complete surface into a connection-free Application protocol and SQLite adapter; move immutable inputs to Application and preserve Platform imports through a SQL-free facade.
- **Reason**: Backend substitution must preserve minor units, exact quantity, idempotency, credit policy, optimistic concurrency, SoD, allocation, exposure, aging, audit, and outbox as one contract.
- **Consequence**: E-140 leaves MatchingService as the only direct-SQLite Platform service. PostgreSQL receivables parity remains unproven and P1-PLAT-001/002 stay open.
- **Reversibility**: No schema or stored data changed. The facade can be redirected without migration; weakening financial, credit, or atomicity invariants is not an acceptable rollback.
- **ADR**: `docs/adr/0145-receivables-application-boundary.md`

### D-139: Keep deterministic matching policy and persistence behind one typed port

- **Date**: 2026-07-28
- **Context**: Six matching execution/read methods mixed SQLite jobs/results with the pure indexed engine, candidate budgets, identity, normalization, ambiguity, and evidence policy.
- **Decision**: Extract the complete surface into a connection-free Application protocol and SQLite adapter; move public immutable types to Application and preserve historical imports/read seams through a SQL-free facade.
- **Reason**: Backend substitution must preserve exact financial inputs, candidate bounds, deterministic outcomes, ambiguity, lineage, rules, audit, and outbox as one contract.
- **Consequence**: E-141 reduces direct-SQLite Platform services to zero. Three partial inventory repositories remain, so P1-PLAT-001/002 stay open.
- **Reversibility**: No schema or stored data changed. The facade can be redirected without migration; weakening determinism, budgets, or evidence is not an acceptable rollback.
- **ADR**: `docs/adr/0146-matching-application-boundary.md`

### D-140: Keep valuation policy, layers, and Finance draft effects behind one typed port

- **Date**: 2026-07-28
- **Context**: Eleven valuation use cases had a partial row repository but retained SQLite schema, transaction, exact allocation, approval, audit, and outbox coordination in the Platform service.
- **Decision**: Extract the complete use-case surface into a connection-free Application protocol and SQLite adapter; preserve the historical constructor, constants, summary, repository imports, and reversal connection seam through SQL-free facades.
- **Reason**: Backend substitution must preserve FIFO ordering, integer minor units, scaled quantity, half-even allocation, period/policy controls, SoD, balanced Finance drafts, and atomic evidence as one contract.
- **Consequence**: E-142 reduces partial repositories from three to two and raises compatibility adapters to eighteen. PostgreSQL valuation parity and P1-PLAT-001/002 remain open.
- **Reversibility**: No schema or stored data changed. The facade can be redirected without migration; weakening financial or rollback invariants is not acceptable.
- **ADR**: `docs/adr/0147-inventory-valuation-application-boundary.md`

### D-141: Keep compensating valuation effects and lineage behind one typed port

- **Date**: 2026-07-28
- **Context**: Seven reversal use cases retained SQLite coordination around a partial persistence repository.
- **Decision**: Extract the complete surface into a connection-free Application protocol and SQLite adapter while preserving historical imports through SQL-free facades.
- **Reason**: Original lineage, opposite movement, layer restoration/removal, balanced reversing Finance drafts, SoD, and audit/outbox atomicity must not diverge by backend.
- **Consequence**: E-143 leaves inventory planning as the sole partial repository. PostgreSQL reversal parity remains open.
- **Reversibility**: No schema or data changed; weakening compensating or atomicity invariants is not acceptable.
- **ADR**: `docs/adr/0148-inventory-valuation-reversal-application-boundary.md`

### D-142: Keep count approval, adjustment, and reorder policy behind one typed port

- **Date**: 2026-07-28
- **Context**: Thirteen inventory-planning use cases retained SQLite coordination around a partial persistence repository.
- **Decision**: Extract the complete surface into a connection-free Application protocol and SQLite adapter while preserving historical constructors, injection, constants, summaries, and imports through SQL-free facades.
- **Reason**: Exact counts, lifecycle/SoD, adjustment movements, reorder policy, and audit/outbox atomicity must remain one substitutable contract.
- **Consequence**: E-144 reduces both direct-SQLite and partial Platform services to zero. PostgreSQL parity remains separately open under P1-PLAT-002.
- **Reversibility**: No schema or data changed; weakening quantity, approval, adjustment, or rollback invariants is not acceptable.
- **ADR**: `docs/adr/0149-inventory-planning-application-boundary.md`

### D-143: Measure PostgreSQL parity without inferring it from filenames

- **Date**: 2026-07-28
- **Decision**: Inventory every Application service with mutually exclusive current-live, live-test-available, contract-only, absent, or not-applicable status; validate coverage, adapter symbols, tests, evidence fields, and counts in CI.
- **Reason**: A PostgreSQL-named class can implement an older or narrower contract, and a skipped live test is not current runtime proof.
- **Consequence**: E-145 records 0 current-live, 9 live-test-available, 2 contract-only, 14 absent, and 1 pure boundary. Finance Core is prioritized next because its existing PostgreSQL components do not implement the current eighteen-use-case port.
- **ADR**: `docs/adr/0150-measure-postgres-application-parity.md`

### D-144: Store governed PostgreSQL Finance Core amounts as currency minor units

- **Date**: 2026-07-28
- **Decision**: Implement the complete eighteen-use-case Finance Core port in one tenant-bound adapter and store entry/line amounts as constrained `BIGINT` minor units, with lifecycle evidence in the same transaction.
- **Reason**: The current port includes master governance, balanced drafts, maker-checker validation, voiding, dimensions, and trial balance; splitting these invariants across the older ledger/master-data adapters would create divergent semantics and retain `NUMERIC` conversion ambiguity.
- **Consequence**: E-146 advances Finance Core from absent to live-test-available. No current-live claim is allowed until the optional non-superuser PostgreSQL test runs successfully in a configured environment.
- **ADR**: `docs/adr/0151-postgres-finance-core-minor-units.md`

### D-145: Scope PostgreSQL Master Data without duplicating financial masters

- **Date**: 2026-07-28
- **Decision**: Keep existing PostgreSQL currency, organization, entity, branch, and fiscal-period tables as the single source of truth; add optional Application workspace identity and forced-RLS ownership links for the complete thirteen-use-case port.
- **Reason**: Copying masters into new Application-only tables would let Finance Core and Master Data disagree. Tenant-only reads would leak references between workspaces.
- **Consequence**: Same-name periods may exist and overlap across different workspaces but not inside one workspace. Organization codes remain tenant-global for compatibility with existing server APIs. E-147 advances Master Data from absent to live-test-available, not current-live.
- **ADR**: `docs/adr/0152-postgres-master-data-workspace-scope.md`

### D-146: Run one deterministic engine on SQLite and hosted PostgreSQL paths

- **Date**: 2026-07-28
- **Decision**: Move the pure matcher into the reconciliation layer, inject currency precision and candidate budgets, and make SQLite persistence plus the PostgreSQL worker call the same engine.
- **Reason**: The hosted worker previously created and migrated an in-memory SQLite database only to access the algorithm, leaving hidden cross-backend coupling despite the Application facade.
- **Consequence**: Hosted calculation has no SQLite dependency and retains PostgreSQL-owned durable persistence. Full six-method PostgreSQL Matching Application parity and current-live execution remain open.
- **ADR**: `docs/adr/0153-persistence-independent-deterministic-matching-engine.md`

### D-147: Keep PostgreSQL Payables one exact governed aggregate

- **Date**: 2026-07-28
- **Decision**: Implement all 15 Payables methods over nine forced-RLS tables with BIGINT minor-unit money, exact NUMERIC quantities plus canonical text, composite tenant foreign keys, idempotency, lifecycle controls, three-way-match evidence, audit, and outbox.
- **Reason**: Supplier, order, receipt, invoice, match, and approval invariants fail if implemented as unrelated CRUD tables. A `(38,12)` quantity typmod would also introduce an undocumented compatibility break.
- **Consequence**: E-149 advances Payables from absent to live-test-available. Current-live parity remains unproven until the optional non-superuser lifecycle runs against configured PostgreSQL.
- **ADR**: `docs/adr/0154-postgres-payables-aggregate-boundary.md`

### D-136: Keep exact inventory state and movement governance in one port

- **Date**: 2026-07-28
- **Context**: Nineteen inventory master, movement, balance, and control operations mixed SQLite with scaled quantities, tracking, period, location, lifecycle, audit, and rollback policy.
- **Decision**: Extract the complete surface behind a typed Application protocol and SQLite adapter; retain the historical constructor, constants, summary, connection, balance-read, and movement-integrity test seams through a SQL-free facade.
- **Reason**: A partial CRUD repository could diverge on projected stock, serial uniqueness, quantity scale, negative-stock policy, or evidence atomicity.
- **Consequence**: E-138 reduces direct-SQLite Platform services to three. PostgreSQL inventory parity remains unproven and P1-PLAT-001/002 stay open.
- **Reversibility**: No schema or stored data changed. The facade can be redirected without data conversion; weakening inventory correctness is not an acceptable rollback.
- **ADR**: `docs/adr/0143-inventory-core-application-boundary.md`
### D-155: Keep Receivables credit and allocation in one serialized PostgreSQL aggregate

- **Decision**: Implement all thirteen Receivables port methods over migration 0022, with customer locks during credit approval and receipt/invoice locks during allocation.
- **Reason**: Credit-limit and outstanding-balance invariants require serialization across concurrent approvals and allocations; table presence alone cannot prove financial parity.
- **Evidence**: ADR 0155, `tests/test_postgres_receivables.py`, and the focused Receivables/API/CLI/Application regression target.
- **Boundary**: The available live test is skipped without PostgreSQL service credentials, so the adapter is not current-live or production-approved.
### D-156: Bind persisted Matching runs to workspaces without duplicating the engine

- **Decision**: Add a tenant-qualified run/workspace link and implement the six-method PostgreSQL Matching port as orchestration over the single deterministic engine and existing reconciliation integrity repository.
- **Reason**: A second algorithm would create digest drift, while tenant-only runs leave workspace ownership unverifiable. Complete source registration is required before the existing completion verifier can prove coverage and allowed-use constraints.
- **Evidence**: ADR 0156, migration 0023, `tests/test_postgres_matching_application.py`, and the existing deterministic/reconciliation regression suites.
- **Boundary**: The live test is available but skipped without PostgreSQL credentials; no current-live, scale, or production claim follows.
### D-157: Preserve scaled-integer Inventory quantities across PostgreSQL

- **Decision**: Migration 0024 uses BIGINT scaled quantities plus explicit 0-6 unit precision across one tenant-bound seven-table aggregate, with database lifecycle and immutability guards.
- **Reason**: Inventory posting, negative-stock prevention, serial uniqueness, valuation, and reversal must share one exact movement source of truth; floating point or split ownership would invalidate those controls.
- **Evidence**: ADR 0157 and `tests/test_postgres_inventory_core.py`.
- **Boundary**: The storage slice is not the eighteen-method adapter and does not establish parity or current-live behavior.

### D-168: Require one inventory-derived live PostgreSQL gate

- **Decision**: Close supported PostgreSQL Application parity only after every inventory-named live test, isolated migration downgrade/re-upgrade, and native encrypted backup/restore contract runs against a disposable service without boundary skips; CI derives the list from that inventory and pins the database image digest.
- **Reason**: Adapter presence and optional tests concealed runtime defects in migration execution, row representations, schema drift, ordering, triggers, and test isolation.
- **Evidence**: ADR 0168, E-163, `docs/execution/POSTGRES_PARITY_INVENTORY.yaml`, `tests/test_alembic_postgres.py`, and `tests/test_postgres_backup.py`.
- **Boundary**: This is single-node synthetic Team evidence, not HA, host-loss, managed-key, RPO/RTO, production-readiness, compliance, scale, or external-assurance evidence.

### D-169: Close foundation recovery at Community and Team scope

- **Decision**: Define the Phase 1 P1-PLAT-010 exit as verified current Community SQLite and single-node Team PostgreSQL recovery; retain Enterprise HA, Regulated air gap, managed keys, host loss, upgrades, and operational objectives in their existing Phase 3 tasks.
- **Reason**: Requiring Phase 3 outcomes inside a prerequisite Phase 1 task created a circular completion condition and blurred edition maturity.
- **Evidence**: ADR 0169, E-164, `docs/execution/PHASE_1_EXIT_AUDIT.yaml`, and the verified/planned cells in `docs/operations/backup-restore-matrix.v1.yaml`.
- **Boundary**: The overall recovery matrix correctly remains partial and no production-readiness or external-assurance claim follows.

### D-170: Require artifact verification for the Phase 2 exit

- **Decision**: Bind all normative Phase 2 tasks and gates in a machine-readable audit and verify retained benchmark profile bytes/digests plus environment and resource fields, rather than accepting task labels or Markdown alone.
- **Reason**: Phase completion requires current evidence at the same scope as the deterministic, integrity, Reconciliation-as-Code, and 10K/100K performance claims.
- **Evidence**: ADR 0170, E-165, `docs/execution/PHASE_2_EXIT_AUDIT.yaml`, and `tests/test_phase_2_exit_audit.py`.
- **Boundary**: The measurements are local single-host/single-process evidence and support no 1M/10M, distributed, database, sustained-load, production-readiness, or external-assurance claim.

### D-171: Keep federation cryptography outside the ReconForge policy core

- **Decision**: Library adapters exclusively parse and cryptographically verify OIDC/SAML artifacts; the backend-neutral Federation service enforces exact trust configuration, time, correlation, replay, role mapping, sovereign-mode, and sanitized audit policy.
- **Reason**: JOSE and XML Signature are security protocols, while provider-to-local authorization and deployment policy are ReconForge responsibilities. Combining them would encourage home-grown verification and make library replacement unsafe.
- **Evidence**: ADR 0171, E-166, `reconforge/auth/federation.py`, and `tests/test_federation_application.py`.
- **Boundary**: No OIDC or SAML login is supported until real library adapters, durable replay/link/session persistence, logout and route integration pass.

### D-172: Verify OIDC only against bounded operator-owned JWKS

- **Decision**: Use locked joserfc with provider-configured algorithm allowlists and static public JWKS; reject private keys, duplicate or missing key IDs and token-controlled key URLs, and require OIDC issuer/audience/time/nonce plus multi-audience azp.
- **Reason**: Dynamic or token-directed key retrieval expands SSRF and key-substitution boundaries, while custom JOSE is prohibited.
- **Evidence**: ADR 0172, E-167, `reconforge/infrastructure/oidc.py`, `tests/test_oidc_verifier.py`, and the locked federation extra.
- **Boundary**: This verifies ID Tokens only; login routes, authorization-code exchange, SAML, durable replay/session linkage and logout remain absent.

### D-173: Delegate SAML XML Signature to xmlsec with stricter local policy

- **Decision**: Verify SAML Responses through locked python3-saml/xmlsec and fixed IdP certificates, then independently constrain signature/digest algorithms, issuer, audience, request correlation and bounded attribute projection.
- **Reason**: XML Signature and wrapping defenses must not be reimplemented, while generic toolkit validity alone does not own ReconForge trust and role-mapping policy.
- **Evidence**: ADR 0173, E-168, `reconforge/infrastructure/saml.py`, `tests/test_saml_verifier.py`, and the locked federation extra.
- **Boundary**: Durable replay, identity links, sessions, logout and routes remain; the dependency deprecation warning requires upgrade monitoring.

### D-174: Prelink federated subjects to local authority under forced RLS

- **Date**: 2026-07-28
- **Decision**: Persist only hashes of assertion identity and `issuer + NUL + subject`; consume assertion replay keys atomically; require an active pre-provisioned local identity whose existing roles contain every mapped external role; issue the existing hash-only PostgreSQL session inside the same tenant transaction.
- **Reason**: An identity provider proves an external subject but must not silently provision local authority, widen roles, leak raw assertions, or permit cross-tenant replay.
- **Evidence**: ADR 0174, E-169, migration 0034, `reconforge/infrastructure/postgres_federation.py`, `tests/test_postgres_federation.py`, and the fresh PostgreSQL 17.10 non-superuser lifecycle.
- **Boundary**: Operator configuration, API integration, complete logout evidence, SCIM, MFA, and external assurance remain open; this is not an Enterprise-ready or production-approved claim.

### D-175: Compose federation through one disabled-by-default public login route

- **Date**: 2026-07-28
- **Decision**: Register one strict public authentication route only when PostgreSQL identity can be used; require operator-owned provider/verifier maps, execute verification/replay/local binding/session/audit in one tenant transaction, and reuse the existing revocable session/logout contract.
- **Reason**: A second token system or automatic identity provisioning would split revocation authority and permit external claims to become local permissions. Persisting only the final sanitized outcome prevents raw assertion disclosure while preserving denial evidence.
- **Evidence**: ADR 0175, E-170, `tests/test_api_federation.py`, the updated closed API authorization digest, and the E-170 focused/live gates.
- **Boundary**: The app factory seam is not yet an operator configuration loader, and real OIDC/SAML signatures have not yet traversed HTTP end to end; P3-ENT-001 remains open.

### D-176: Require a server-issued one-time challenge before assertion verification

- **Date**: 2026-07-28
- **Decision**: Load only bounded versioned public verification configuration, issue tenant/provider/protocol-bound five-minute challenges, persist hashes under forced RLS, consume atomically before verification, and cap serialized active challenges.
- **Reason**: Comparing a signed assertion to a nonce or request ID supplied by the same caller does not establish server correlation. The challenge must originate at ReconForge and be independently one-time.
- **Evidence**: ADR 0176, E-171, `reconforge/auth/federation_config.py`, migration 0034, `tests/test_federation_config.py`, `tests/test_api_federation.py`, and `tests/test_postgres_federation.py`.
- **Boundary**: This closes the bounded direct assertion-verification adapter task, not authorization-code exchange, discovery, IdP-initiated SAML, SCIM, MFA, provider single logout, hosted interoperability, independent assurance, or Enterprise readiness.
### D-177 — SCIM provisioning groups cannot grant ReconForge authority

- Date: 2026-07-28
- Status: accepted
- ADR: `docs/adr/0177-scim-provisioning-is-not-authorization.md`
- Decision: scope SCIM resources by tenant and provisioning domain, treat external IDs as idempotency identities only inside that scope, deactivate rather than erase provisioned users, and prohibit implicit mapping from SCIM group labels to ReconForge roles or permissions.
- Rationale: RFC 7643 does not define authorization semantics for groups. Local explicit approval must remain the authority boundary for financial and administrative permissions.

### D-178 — SCIM deactivation and session revocation share one transaction

- Date: 2026-07-28
- Status: accepted
- ADR: `docs/adr/0178-scim-forced-rls-lifecycle-storage.md`
- Decision: store SCIM resources in forced-RLS tenant/domain tables, serialize concurrent external identities, keep provisioned identities role-free, and atomically disable the identity plus revoke sessions during deprovisioning.
- Rationale: a shadow-only SCIM record would leave active access behind, while external group-to-role writes would allow upstream privilege escalation.

### D-192 — Schedule occurrence dispatch and cursor advance share one transaction

- Date: 2026-07-29
- Status: accepted
- ADR: `docs/adr/0192-postgres-scheduler-dispatch-is-atomic-and-versioned.md`
- Decision: persist immutable schedule versions with initial-registration digests, claim due rows through bounded `SKIP LOCKED` discovery, narrow the same transaction to workspace/entity scope, and atomically create or resolve a digest-addressed durable job before appending dispatch/audit evidence and advancing the cursor.
- Rationale: separate commits can lose an occurrence or duplicate its business effect after a crash. Versioned immutable configuration, durable idempotency, and cursor-after-dispatch ordering provide reproducible recovery without claiming exactly-once transport.
- Rollback: empty scheduler schemas may downgrade to 0046. Non-empty downgrade is rejected before mutation and requires a verified backup plus approved data migration; scheduled durable jobs are never deleted by migration 0047.
- Limits: hosted polling, email/webhook transports, egress allowlists, redaction, HA, operational UI, and P3-ENT-005 exit remain open.

### D-193 — Notification egress is exact, redacted, pinned, and at-least-once

- Date: 2026-07-29
- Status: accepted
- ADR: `docs/adr/0193-notifications-are-redacted-allowlisted-and-at-least-once.md`
- Decision: make network delivery default-off; store immutable workspace/entity-scoped route versions and exact schedule subscriptions; enqueue only a closed digest-bound schema-v1 payload in the schedule transaction; require exact HTTPS/SMTPS/domain allowlists; validate every DNS answer and pin the selected public address to TLS; reuse bounded outbox retry/dead-letter/replay and append every state transition as immutable delivery evidence.
- Rationale: arbitrary endpoints, a second DNS lookup, raw outbox forwarding, mutable destinations, or hidden exactly-once assumptions would create SSRF, exfiltration, audit, and duplicate-effect risks.
- Rollback: empty 0048 may downgrade to 0047. Any route, subscription, notification outbox row, or delivery event blocks downgrade before mutation and requires a verified backup plus approved forward data migration.
- Limits: provider tests are injected and synthetic; real email/webhook interoperability, production secret custody, receiver idempotency after crash-between-send-and-ack, HA, and external assurance remain unverified.

### D-194 — Security overview is count-only, human-only, and not assurance

- Date: 2026-07-29
- Status: accepted
- ADR: `docs/adr/0194-security-center-is-count-only-and-human-governed.md`
- Decision: aggregate current tenant security state through one backend-neutral count contract and one static RLS-backed PostgreSQL projection; require `security.center.read`, a human principal, and current configured privileged assurance; return a closed tenant/digest-bound schema without subjects, credentials, destinations, financial data, free-form audit content, or cluster-global sequence values.
- Rationale: joining identity/security tables in a browser or returning row details would create an excessive disclosure surface, while a generic green posture would misrepresent current assurance. Counts plus explicit attention codes support triage without pretending to certify security.
- Migration: 0049 names and strengthens the service-account permission constraint so direct SQL cannot grant the overview permission to a machine principal. Downgrade restores the prior ceiling without changing data tables.
- Limits: this slice is read-only and PostgreSQL-only; lifecycle mutation, accessible UI, hosted interoperability, complete disclosure testing, and independent security assurance remain open.
# E-174 — SCIM request principals and hash-only credentials

- Accepted ADR 0179. SCIM machine principals are separate from user sessions and RBAC. A routing tenant only selects the forced-RLS scope; authority comes from an unexpired, unrevoked credential hash found inside that scope.
- Raw credentials are returned once by the operator CLI and are never retrievable. Rotation is one transaction that issues a successor and revokes its predecessor.
- P3-ENT-002 closes at the advertised bounded RFC 7643/7644 subset. Unsupported capabilities remain explicit, and hosted interoperability or Enterprise readiness require separate evidence.
# E-175 — Role-free service accounts with direct least privilege

- Accepted ADR 0180. Machine identities are separate from users, sessions, and roles; their credentials are hash-only, bounded, revocable, and tenant scoped.
- Human identity administration, policy administration, service-account administration, and emergency permissions cannot be delegated to a service account. Permission and TTL ceilings are enforced in PostgreSQL as well as Application code.
- This closes only the service-account lifecycle slice. P3-ENT-003 remains open until machine HTTP principals and governed privileged human step-up/emergency review are implemented and verified.

# E-176 — Machine principals cannot perform human-governed decisions

- Accepted ADR 0181. Reserved `rfa_` credentials authenticate only as typed service-account principals inside a forced-RLS tenant transaction and never become user sessions or receive user roles.
- Central policy is the second denial boundary: explicit human-governed permissions and every `.approve`, `.review`, or `.complete` suffix fail for machines. Dynamic workflow transitions are human-only.
- Alembic must preserve existing loggers because disabling the authorization logger removes runtime policy-audit evidence. The discovered regression is now locked by test.
- This completes HTTP machine composition only. P3-ENT-003 remains open for privileged human step-up and governed emergency access.

# E-177 — Privileged server actions require session-bound reauthentication

- Accepted ADR 0182. A closed registry of high-risk PostgreSQL permissions requires an existing human role grant plus a fresh assertion bound to the same tenant, user and session.
- Password reauthentication uses the established lockout-aware verifier and produces a forced-RLS append-only assertion for at most ten minutes. It is deliberately not described as MFA.
- Community/SQLite remains compatible because step-up enforcement is a server-session control, not a generic authorization prerequisite.
- P3-ENT-003 remains open for emergency-access request, independent approval, bounded activation, expiry, and post-use review.

# E-178 — Emergency authority requires maker-checker activation and independent review

- Accepted ADR 0183. Emergency authority is human-only, self-requested, independently approved, session-bound, time-limited, and distinguishable from base RBAC.
- Every emergency-derived authorization must append permission and surface evidence before the protected operation; end or expiry requires an independent post-use review.
- The registry deliberately excludes identity, role, policy, service-account, and security administration. P3-ENT-003 remains open for true MFA, workload identity federation, hosted operational proof, and independent assurance.

# E-179 — WebAuthn is the configured privileged MFA method

- Accepted ADR 0184. User-verified WebAuthn provides a distinct origin-bound possession factor through a pinned standards library; no private authenticator key or shared MFA secret is stored.
- Enabling the closed RP/origin configuration changes the privileged policy contract: password reauthentication remains sufficient for enrollment but not privileged execution, which requires `webauthn_user_verified` assurance.
- P3-ENT-003 closes at its bounded exit contract. Recovery, attestation governance, workload federation, hosted operation, broad authenticator interoperability, and independent assurance remain explicit separate work.

# E-180 — Hierarchical execution scope is transaction-local and database-enforced

- Accepted ADR 0185. Tenant, workspace, organization, and legal-entity context is immutable, validated, and installed with transaction-local settings.
- Empty child scope is an explicit tenant-wide operation; a supplied child adds an RLS constraint, and legal entity without organization is invalid.
- Migration 0041 covers the authoritative hierarchy only. P3-ENT-004 remains open until jobs, exports, object storage, remaining domain tables, API composition, and failure paths pass equivalent isolation gates.

# E-181 — Durable workers narrow after tenant-wide discovery

- Accepted ADR 0186. Scheduler discovery is tenant-wide, but the selected job's workspace/entity becomes the active transaction scope before any state or evidence write.
- Resume and read paths derive scope from the durable parent and re-query beneath RLS; child evidence is visible only through a visible parent job.
- This closes the background-job portion of P3-ENT-004 only. Export, object-storage, API-authority, remaining-domain, and failure-path gates remain open.

# E-182 — Object artifacts bind key and metadata to hierarchy

- Accepted ADR 0187. Official object stores require validated tenant/workspace/entity hierarchy, place every supplied segment in the immutable key, and repeat that scope in integrity metadata.
- Evidence registration verifies returned hierarchy before database persistence. Existing tenant-only providers remain compatible through an explicit capability boundary but provide no multi-workspace isolation evidence.
- This closes the object-storage portion of P3-ENT-004 only. PostgreSQL export scope, remaining domain RLS, API authority, and full failure-path coverage remain open.

# E-183 — Enterprise exports are authorized RLS snapshots

- Accepted ADR 0188. A control-plane export requires explicit workspace scope, `reports.read`, exact contextual grants, bounded static queries under PostgreSQL RLS, canonical digests, and hierarchy-aware immutable publication.
- Migration 0043 closes tenant-only Evidence Application reads and the workspace-parent gap for entities/branches. The transaction also sets the job engine's `app.entity_id` alias from the legal-entity scope.
- Workspace-only Evidence is excluded from entity exports until an authoritative entity field exists. This closes the export portion of P3-ENT-004, not remaining domain/API/failure-path isolation.

# E-191 — PostgreSQL is the authoritative server user/session lifecycle

- Accepted ADR 0195. Server authentication and user/session administration must address one PostgreSQL authority; the historical SQLite `/api/v1/users` routes now fail closed only in the PostgreSQL profile.
- User disable, all-session revocation, and bounded domain-audit evidence are one optimistic transaction. Self-disable, last-active-administrator removal, stale versions, sibling identifiers, and machine principals fail closed.
- Public session administration exposes only metadata presence flags, never raw tokens, hashes, IP addresses, user-agent values, email, or passwords. Signed cursors bind tenant/resource/filter/order.
- E-191 does not govern roles or policies. E-192 must replace or disable the remaining server `/api/v1/roles` shadow surface before P3-ENT-006 can close.

# E-192 — PostgreSQL is the authoritative server role/policy lifecycle

- Accepted ADR 0196. Server authorization reads and administration now address one PostgreSQL role, role-permission, and user-role authority; historical `/api/v1/roles` reads fail closed before SQLite opens in the server profile and remain compatible locally.
- Role names are immutable, deletion is replaced by retirement, and reactivation never resurrects revoked assignments. Permission and user-role mutations replace exact sorted sets under optimistic versions and invalidate every affected active session.
- The HTTP permission registry is read-only. Tenant-serialized final-manager checks prevent retiring the last management role, removing its final `roles.manage` policy, or stripping the last active human manager.
- Audit append, assignment/policy state, user lifecycle increments, and session revocation share one transaction. Migration 0051 refuses downgrade when governed access evidence would be lost.
- This slice does not implement full ABAC, policy approval workflows, integration/retention lifecycle, administration UI, HA, production IAM assurance, certification, or Enterprise readiness.

# E-193 — Govern native integration state and monotonic evidence retention

- Accepted ADR 0197. Integration administration projects the native federation-link, SCIM-credential, service-account, and notification-route tables instead of creating a generic shadow connector registry.
- Human `security.policy.manage` plus current privileged assurance, an exact state digest, and a closed reason are required. Native disable/revocation, lifecycle evidence, and bounded domain audit share one tenant transaction.
- Tenant retention policies are versioned and retired rather than deleted. Evidence assignments are append-only and idempotent by evidence, policy, and policy lifecycle version.
- The evidence registry owns a monotonic retention floor and explicit retention version. The old metadata path preserves omitted retention and refuses explicit shortening before SQL; PostgreSQL independently enforces the floor.
- Retention is metadata only. External object-lock propagation, legal approval, connector interoperability, secret rotation orchestration, accessible administration UI, HA, certification, and Enterprise readiness remain outside this slice.

# E-194 — Consolidated audit browsing is redacted and source-specific

- Accepted ADR 0198. The PostgreSQL administration view combines the domain and ledger-control audit sources only for deterministic browsing; it does not convert them into a global chain or sequence.
- Browse returns one-way actor/object/metadata digests and existing integrity hashes, never raw actor labels or identifiers, object identifiers, request identifiers, reasons, or metadata. Every browse cursor is signed and tenant/resource/order/source/event-bound.
- `audit.read` and `audit.verify` are human-only privileged permissions. Migration 0053 rejects future machine grants without deleting historic grants; central policy denies historic machine principals until explicitly remediated.
- This slice does not govern the historical Local/SQLite audit API, a full audit UI/accessibility pass, external timestamping, legal/object-store retention, independent assurance, compliance, or Enterprise readiness.

# E-195 — Browser administration must not manufacture bearer authority

- The existing Studio's synthetic and read-only routes are not repurposed as an administration surface. The server administration APIs require an explicit Bearer principal and current privileged assurance; a browser client must not obtain that authority from a build variable, URL, fixture, or persistent browser storage.
- Before any administrator view is implemented, define and test a browser-specific same-origin session, privileged-assurance, CSRF, logout/revocation, disclosure, and failure contract. The view may consume only the existing closed/redacted API responses and must fail closed when the contract is unavailable.
- Current Chromium/Axe/RTL/keyboard evidence applies only to the named Studio routes. It is regression evidence, not a full accessibility-conformance or assistive-technology claim.

# E-196 — Same-origin browser sessions keep bearer credentials out of JavaScript

- Accepted ADR 0199. The existing bearer API remains the API/CLI contract. Browser login instead places the session bearer only in a host-only HttpOnly/Secure/SameSite=Strict cookie and returns a CSRF proof bound by HMAC to that exact session.
- Cookie-authenticated unsafe requests require `X-ReconForge-CSRF`; explicit Bearer takes precedence and retains existing compatibility behavior. Logout revokes and clears only the session transport actually used.
- This transport boundary requires same-origin HTTPS and is not a static-hosting topology, CSP policy, browser login/step-up UX, reverse-proxy proof, accessibility certification, or Enterprise readiness.

# E-197 — Administration UI consumes only closed redacted contracts

- The first Studio administration route is audit-only. It cannot browse or verify until browser login and the existing human step-up succeed; it keeps tenant and CSRF proof only in component memory and has no bearer or synthetic fallback path.
- Browser rendering is constrained to the E-194 allowlisted fields. The client validator rejects a wider event response before rendering, so a server-side disclosure regression such as `actor_label` does not become an accidental browser disclosure.
- This does not create identity, role, integration, retention, or security-center UI; it does not prove browser deployment topology, CSP, full accessibility conformance, or Enterprise readiness.
## D208 - Browser governance writes use native concurrency tokens and transient evidence references

- Date: 2026-07-30
- Status: accepted
- Decision: The administration UI may disable only already-authorized native integrations and may create, edit, retire, reactivate, and apply retention policies only through the existing human step-up and CSRF-bound API. Integration disable submits the returned state digest; policy updates submit the returned lifecycle version; evidence application submits an operator-provided retention version. Destructive transitions require typed literals. Evidence identifiers are transient form values cleared after success or cancellation and are never populated from list responses.
- Consequence: The browser does not become a connector provisioning or evidence discovery surface, and no secret, destination, credential, or stored evidence reference is disclosed. PostgreSQL remains responsible for tenant scope, optimistic conflicts, append-only audit, and the non-shortening retention floor. Retired policies preserve prior assignments and reactivation does not rewrite evidence.
- Rollback: Remove the mutation component and helpers while retaining the pre-existing read-only governance tables and all server-side enforcement. Existing integration disablement and retention assignments are deliberately not reversed by a UI rollback.
## D209 - A deployed administration browser uses one exact-host HTTPS origin

- Date: 2026-07-30
- Status: accepted
- Decision: Allow the API composition root to serve a pre-built Studio only when an exact Host allowlist is configured. Bind direct TLS certificate/key files together or require an explicit secure-transport assertion for reviewed upstream termination. Emit HSTS only in secure mode and apply the closed browser policy to API and static responses. Preserve asset 404s and use SPA fallback only for extensionless GET/HEAD paths.
- Consequence: Secure browser cookies, CSRF, HTML, assets, and API calls can share a deployable origin without a development proxy or bearer-token persistence. Forwarded headers remain untrusted and external proxy/certificate policy remains an operator responsibility.
- Rollback: Remove the web-root and secure-hosting options. API-only local operation resumes without schema or data changes.
## D210 - Connector manifest v1 is data-only, static-allowlisted, and read-only

- Date: 2026-07-30
- Status: accepted
- Decision: Add a strict immutable manifest and deterministic conformance boundary before any network or package loading. Preserve the historical registry API but classify SAP/Odoo adapters as export profiles. Reject write capability in v1 and keep discovery as a fixed source allowlist.
- Consequence: Current local adapters gain auditable boundaries without creating live integration, credential, network, or arbitrary-code claims. The SHA-256 manifest digest is integrity metadata only and cannot substitute for publisher signature verification.
- Rollback: Remove the manifest/conformance package and adapter declarations; no stored state or schema is affected.

## D211 - Network connector pages are exact-egress durable read effects

- Date: 2026-07-30
- Status: accepted
- Decision: Permit only schema-closed read-only HTTPS GET registrations over signed manifest data. Require exact endpoint allowlisting, public-only DNS answers, IP-pinned hostname-verified TLS, no redirects, runtime-only secret references, bounded idempotency/cursor/response/rate/retry policy, and one immutable object plus generation-fenced durable-job effect per page.
- Consequence: Crash/reclaim resumes from a digest-verified committed cursor without replaying committed effects, while Community remains network-free by default. The runtime remains synthetic and vendor-neutral; process-local rate state, operator trust/vault composition, provider interoperability, and distributed quotas are explicit limitations. Write-back and executable third-party packages remain prohibited.
- Rollback: Disable/remove network registrations and workers. Retain existing immutable page/job evidence according to governed retention; no schema downgrade is required.

## D212 - Signed packs are approved declarative data, never executable extensions

- Date: 2026-07-30
- Status: accepted
- Decision: Admit only bounded closed JSON packs whose complete manifest is Ed25519-authenticated under an operator-owned trust snapshot. Require strict declarative rule/golden conformance, platform and active dependency compatibility, distinct maker-checker approval, immutable version rows, one enabled version, and actor/digest events for install, disable, and rollback. Upgrade is a complete new data version; executable migration or module hooks are forbidden.
- Consequence: Control and industry pack lifecycle is locally reproducible without granting publisher code execution. Existing repository YAML packs remain compatible and are not retroactively called signed. Legal publisher identity, public marketplace, production trust administration, customer-data migration, multi-node activation, and external assurance remain outside the evidence.
- Rollback: Stop admissions and remove the local lifecycle database after governed event export/retention. Existing built-in YAML pack loading remains unchanged.

## D213 - Multi-resource upgrades are approved sagas with explicit uncertainty

- Date: 2026-07-30
- Status: accepted
- Decision: Bind application, database, object-store, configuration, and pack changes into one closed digest-addressed plan. Complete all rollback/compatibility preflights before mutation, require a distinct maker/checker, claim execution atomically, verify every receipt, and roll applied resources back in reverse. Interrupted adapters must report provably not applied, applied with a recoverable receipt, or unknown; unknown state fails into isolation rather than a false rollback claim.
- Consequence: Upgrade coordination does not pretend that independent stores share a distributed transaction or exactly-once transport. Concrete adapters remain responsible for idempotency, backups, compatibility readers, and resource-specific integrity.
- Rollback: Disable the orchestrator while retaining its journal. Existing resource-specific migration, backup, restore, configuration, object, and pack tools remain authoritative.

## D214 - Operator tooling version is distinct from deployed resource versions

- Date: 2026-07-30
- Status: accepted
- Decision: Bind the running operator version independently from the deployed application source and target. Publish only closed, schema-validated transitions whose named compatibility readers, target digests, and mandatory rollback drills pass. PostgreSQL preflight must authenticate an encrypted backup, migrate an isolated restore, and remove that drill database before source mutation; local object upgrades change only a verified catalog and never rewrite immutable evidence bytes.
- Consequence: The v0.7.1 operator can truthfully upgrade a tagged v0.7.0 deployment, and a matrix cannot claim `supported` while any listed resource transition is blocked. This establishes bounded local/disposable operation, not zero downtime, distributed atomicity, production key custody, HA/DR, or Enterprise readiness.
- Rollback: Mark the matrix `candidate`, reject new plans, and retain journals/backups/quarantines. Resource adapters restore only their verified predecessor state; unknown state remains isolated for manual investigation.

## D215 - Promotion requires positive fencing and failure-domain disclosure

- Date: 2026-07-30
- Status: accepted
- Decision: A standby may be promoted only after the controller proves the former writer's exact identity is stopped and fenced. Every HA/DR report must name infrastructure, independent failure domains, replication and commit mode, failure injection, RPO unit, RTO measurement boundaries, backup/restore integrity, and residual limitations.
- Consequence: The synchronous two-container result is evidence for a controlled replication partition, process failure, rejoin, and failback, not host-loss HA. Zero missing acknowledged transactions follows only from remote-apply after streaming readiness; a timed-out/unacknowledged transaction remains uncertain. The recorded 11.117-second failover and 0.958-second failback are one development run, not production SLOs.
- Rollback: Refuse promotion when fencing cannot be proven. Remove only resources bearing the current unique drill label and retain the report as bounded evidence.

## D216 - Offline installation consumes a closed local hash-locked inventory

- Date: 2026-07-30
- Status: accepted
- Decision: Air-gapped installation inputs must declare every local regular file by normalized relative path, role, size, and SHA-256. Requirements are exact and individually hashed; derived pip execution is argv-only with `--no-index` and `--require-hashes`. URLs, links, traversal, extras, and integrity drift fail before install.
- Consequence: E-214 establishes local artifact-integrity input, not mirror completeness, signature trust, successful installation, OS egress isolation, or Air-gap readiness.
- Rollback: Reject/quarantine the whole bundle without partial installation; removing the verifier restores the task to planned and changes no deployment.

## D217 - Offline install proof separates connected assembly from disconnected consumption

- Date: 2026-07-30
- Status: accepted
- Decision: Dependency acquisition occurs only in an explicit connected assembly stage under `uv.lock` hashes. The consumption stage receives a digest-closed wheel inventory and runs with Docker network mode none, read-only root/bundle, bounded writable tmpfs, and pip no-index/no-deps/require-hashes. A successful doctor check is required.
- Consequence: E-215 proves one Linux no-network installation of the current wheel. It does not prove physical transfer controls, offline signature trust, identity/recovery ceremonies, repeated platforms, or production readiness.
- Rollback: Remove the disposable container and tmpfs state, preserve only the closed report, and reject the bundle on any verification/install/doctor failure.

## D218 - Offline attestation trust is pinned and OCI-bounded

- Date: 2026-07-30
- Status: accepted
- Decision: Pin the verifier binary and trusted-root snapshot by digest, verify release checksum inventories before signatures, and enforce exact repository/workflow/signer/source/ref/runner constraints with no shell and no network fallback. Treat OCI bundle integrity separately from OCI subject verification.
- Consequence: E-216 proves offline cryptographic identity for regular-file provenance and file-artifact SBOM attestations. Because gh 2.78.0 resolves OCI subjects at the registry, the image bundles are integrity-only in this drill and no offline OCI signature claim is allowed.
- Rollback: Quarantine the evidence directory on any digest, identity, signature, or trust-root failure; no runtime or publication is mutated.

## D219 - Sovereign fallback uses pre-provisioned local identity and invalidates sessions on restore

- Date: 2026-07-30
- Status: accepted
- Decision: An isolated deployment must test local identities before disconnection and protect them through authenticated encrypted backup. Restore carries verifier material and roles but never active bearer sessions; wrong-key recovery is atomic and fail-closed. Runtime credentials and keys are generated ephemerally for drills.
- Consequence: E-217 proves local login and encrypted SQLite identity recovery in one no-network Linux runtime. It does not create self-service forgotten-password recovery, a permanent bypass account, or hardware-backed key custody.
- Rollback: Delete the isolated restored database and runtime tmpfs; preserve the encrypted artifact only under operator custody. No external identity or published asset is mutated.

## D220 - Signed installation evidence must bind the exact verified subject digest

- Date: 2026-07-30
- Status: accepted
- Decision: A signed-air-gap claim is permitted only when the application wheel accepted by the offline installer has the exact SHA-256 subject verified by the provenance and SBOM attestations. Locally rebuilt wheels remain valid test inputs but cannot inherit another artifact's signature evidence.
- Consequence: E-219 installs the exact signed candidate wheel and closes the prior evidence-composition gap. Dependency wheels remain hash-locked rather than individually attested, and OCI is a distinct profile.
- Rollback: Reject the bundle before install on any external-wheel digest or metadata mismatch; deleting the disposable runtime reverses the drill without remote mutation.

## D221 - Air-gap task exit is profile-specific, not a universal deployment claim

- Date: 2026-07-30
- Status: accepted
- Decision: P3-ENT-011 may exit for the Python-wheel Linux sovereign profile once closed bundle, mirror, same-signed-artifact install, no-network enforcement, local identity, encrypted recovery, and exact upgrade/rollback gates pass. OCI and physical-transfer assurance remain explicitly separate.
- Consequence: E-220 is a bounded task completion, not an air-gap certification, multi-platform guarantee, OCI signature claim, or Enterprise readiness statement.
- Rollback: Reopen P3-ENT-011 if any bound report, digest, runtime gate, or compatibility transition becomes invalid or unsupported.

## D222 - Reliability signals are closed, dimension-free, and fail explicit on no data

- Date: 2026-07-30
- Status: accepted
- Decision: Operational alerts consume only named bounded integer measurements. Tenant, workspace, actor, record, amount, and currency dimensions are forbidden. Missing input is `no_data`, never healthy; each threshold must bind a stable SLO identifier and an operator runbook.
- Consequence: Local evaluation and telemetry are deterministic and resistant to high-cardinality or financial-data disclosure. Initial thresholds are operator defaults, not measured production SLOs, and a local in-memory exporter does not establish collector or alert-manager operation.
- Rollback: Disable reliability recording/evaluation while retaining the prior no-export-by-default tracing boundary; remove the policy only after preserving drill evidence and reverting its documentation claims.

## D223 - Measurement-source failure must remove the metric, not manufacture zero

- Date: 2026-07-30
- Status: accepted
- Decision: Operational collectors may publish a metric only after its source succeeds and validates. Database, schema, timestamp, or provider failure produces a closed source-category marker and omits the affected value; downstream policy therefore reports `no_data`. Aggregate collectors must not return tenant, workspace, job, actor, record, amount, or currency identifiers.
- Consequence: Zero means an observed zero, while unavailable remains distinguishable and cannot create false green health. Local SQLite, API-window, audit, dependency, and capacity sources are implemented; PostgreSQL parity and external delivery remain separate gates.
- Rollback: Stop injecting the explicit reliability window or collector. Existing API and no-export observability behavior remains compatible; retained reports must be downgraded if the source contract becomes invalid.

## D224 - OTLP egress requires explicit origin and ignores ambient discovery

- Date: 2026-07-30
- Status: accepted
- Decision: Use the official version-matched OTLP HTTP/protobuf exporter only when an operator supplies a path-free explicit origin. Permit plaintext only on loopback; require exact allowlisting for remote HTTPS; validate CA and paired mTLS files; set exporter sessions to ignore environment proxies and accept no header credentials.
- Consequence: Traces, metrics, and closed operational events can reach a vendor-neutral receiver while default Community/API operation retains no exporter or network egress. Arbitrary application-log forwarding, a full Collector distribution, backend retention, and alert delivery remain open.
- ADR: `docs/adr/0208-otlp-export-is-explicit-allowlisted-and-no-env.md`.
- Rollback: Omit the endpoint and remove the optional exporter factory/dependency after downgrading E-223 evidence; existing disabled observability behavior remains intact.

## D225 - Server reliability collection is tenant-scoped at the database boundary

- Date: 2026-07-30
- Status: accepted
- Decision: PostgreSQL operational aggregation must run as a non-superuser inside transaction-local tenant scope with forced RLS. It may return only aggregate depth, age, audit-issue count, and closed source-availability categories; sibling identifiers and values never enter the snapshot.
- Consequence: E-224 establishes SQLite/PostgreSQL source parity for the current job/audit signals without weakening tenant isolation. A database failure removes both database-derived metrics and yields `no_data`; it never manufactures zero.
- Rollback: Disable the PostgreSQL collector and retain the SQLite/local policy. Reopen the parity gate if migration, RLS, or live sibling-exclusion evidence no longer passes.

## D226 - Capacity claims bind the exact environment and measurement boundary

- Date: 2026-07-30
- Status: accepted
- Decision: Record hardware/runtime profile, sample count, transport boundary, wall time, p95, error basis points, resident memory, queue size, query time, recovery state, and limitations together. A single in-process run may validate alert/recovery mechanics but cannot define a production SLO or sizing promise.
- Consequence: E-225 can support the bounded 1,000-request/1,000-job local result only. Network load, soak, repeated variance, distributed capacity, and production sizing remain separate gates.
- Rollback: Remove the benchmark claim and retained report if its script, environment identity, or closed schema no longer reproduces; reliability correctness remains independent of the performance number.

## D227 - The reference Collector is pinned, least-privileged, and backend-bounded

- Date: 2026-07-30
- Status: accepted
- Decision: Pin the official Collector distribution by digest, expose OTLP only on an operator-selected private interface, mount configuration read-only, use a read-only root, drop capabilities, set no-new-privileges, and treat the file exporter as an ephemeral sovereign reference backend only.
- Consequence: E-226 proves the complete local traces, metrics, and closed-events pipeline plus artifact persistence without granting a durable retention, alert-manager, multi-node Collector, or production SLO claim.
- Rollback: Stop and remove the labelled Collector and output mount, omit the application OTLP endpoint, and retain no egress. Any replacement backend requires a new explicit allowlist, retention policy, recovery test, and evidence update.

## D228 - Incident recovery requires a closed ordered evidence chain

- Date: 2026-07-30
- Status: accepted
- Decision: Reliability incidents use five non-skippable monotonic states, safe identifiers, digest-only evidence, prior-event hash linkage, and a final deterministic manifest. Recovery requires a complete all-normal policy evaluation and should use a validator distinct from the mitigating operator.
- Consequence: E-227 proves local lifecycle mechanics and tamper detection without accepting raw commands, credentials, customer identifiers, or financial rows. Synthetic actor separation is not evidence of a staffed on-call function or external acknowledgement.
- ADR: `docs/adr/0209-reliability-incidents-are-ordered-hash-chained-and-closed.md`.
- Rollback: Remove the optional module and drill artifacts. No database, API, CLI, financial schema, or existing telemetry contract changes.

## D229 - HA repetition retains every result and does not widen topology claims

- Date: 2026-07-30
- Status: accepted
- Decision: Run the complete HA/DR drill exactly three times, retain all RPO/RTO values, compute min/median/max without discarding outliers, and require labelled-resource cleanup after every child run.
- Consequence: E-228 closes the bounded repetition gap and reports the observed distribution, but it does not change the explicit single-host/failure-domain status or satisfy quorum, automatic failover, or production SLO gates.
- Rollback: Remove the aggregate report if any child result, resource-cleanup check, schema, or calculation becomes unreproducible; retain the earlier single-run E-213 evidence at its narrower maturity.

## D230 - Competitive claims must stay evidence-bounded and explicit on unknowns

- Date: 2026-07-30
- Status: accepted
- Decision: Competitive capability statements must use dated primary sources, explicit feature-level boundaries, and explicit cost/scale/assurance unknowns. Competitor comparison is only allowed to map what is implemented, what is bounded, and what remains unproven.
- Consequence: E-229 introduces `docs/strategy/competitive-capability-matrix.md` as a bounded evidence-led matrix for `P3-ENT-013` and blocks claims that imply certification, compliance superiority, or external commercial readiness without external pilots and security review gates.
- Rollback: Delete or replace the matrix before publication and retain a “planned” status for any comparative public claim until `P3-EXT-001` and `P3-EXT-002` evidence are present.

## D231 - Docker runtime must be operational before closing HA/DR evidence gates

- Date: 2026-07-31
- Status: accepted
- Context: Three production-dependent evidence runs are blocked in the current environment by Docker runtime connectivity (`npipe:////./pipe/dockerDesktopLinuxEngine`) before exercise assertions execute.
- Decision: Treat `verify_postgres_reliability.py`, `verify_postgres_ha_dr.py`, and `verify_otel_collector_distribution.py` as environment-blocked for this run context. Do not move `P3-ENT-010` or `P3-ENT-012` to closed status from this evidence set until reruns succeed with a healthy Docker API and unchanged cleanup/infrastructure checks.
- Consequence: Local evidence remains valid for `E-221` / `E-222` / `E-223` / `E-224` / `E-225` / `E-226` / `E-227`, but production-recovery and live-op resilience claims remain open and are not promoted.
- Rollback: When Docker connectivity is restored, rerun those scripts and only then update closure logic; if any rerun check changes, revise this decision and retain prior claims by historical scope.

## D232 - CI remediation repairs execution fidelity and never bypasses external closure

- Date: 2026-08-01
- Status: accepted
- Context: PR #66 exposed missing optional test dependencies, a stale PostgreSQL migration registry, insufficient disposable-role reads for the complete metrics query, Debian PostgreSQL wrapper command-identity loss, and one historical Gitleaks false positive.
- Decision: Full-suite CI installs all locked feature extras; the PostgreSQL registry must equal the parsed linear Alembic chain; live harnesses grant only named required reads and resolve real versioned native clients; secret-scan exceptions must be exact fingerprints and generated-path allowlists must remain bounded. The Phase 3 closure guard is never skipped, excluded, retried away, or changed to accommodate these repairs.
- Consequence: E-247 can repair the remote CI failure fingerprints reproducibly while the absent external pilots and independent security review continue to fail closed. A green remediation does not imply publication readiness, Enterprise readiness, certification, or completion of the six closure conditions.
- Rollback: Revert the CI-remediation slice and restore the prior test harness/configuration. No production data, schema, API, migration, or public-release mutation is required; the external closure state remains unchanged either way.

## D233 - Public-data evidence is real but never self-approving

- Date: 2026-08-01
- Status: accepted
- Decision: Use only fixed, officially published, openly licensed financial-data slices under an exact manifest. Bind raw SHA-256, closed schemas, exact Decimal semantics, source equations, deterministic matching, row-permutation parity, clean source revision, redacted output, and runtime provenance. A maintainer run is technical evidence only. A public-data run may count toward P3-EXT-001 only after a distinct independent human controls the run, provides environment/failure/feedback evidence, signs the operator statement, and passes upstream verification; three accepted records from three independent operators are required.
- Consequence: E-248 strengthens real-data reproducibility without relabeling a maintainer, bot, repeated account, or successful workflow as an external pilot. The report permanently records zero accepted external operators and cannot mutate the external gate.
- Rollback: Remove the workflow, manifest, runner, protocol, and report, then downgrade the public-data claim. No API, database, production system, or customer data is mutated.

## D234 - Automated security evidence cannot replace independent human review

- Date: 2026-08-01
- Status: accepted
- Decision: Treat CodeQL, Scorecard, Bandit, dependency/secret scans, hostile tests, and public-data evidence as inputs to a qualified independent human reviewer. Require a private disclosure channel, conflict declaration, exact scope/commit, reproducible findings, remediation and retest state, plus residual-risk acceptance by a human distinct from the implementer/reviewer. Do not solicit public testing while no private channel operates.
- Consequence: Read-only API evidence that GitHub private vulnerability reporting is disabled keeps P3-EXT-002 blocked. No automated green result, maintainer self-review, or public issue may close it or imply certification/compliance/security assurance.
- Rollback: Withdraw solicitation and retain the gate as engaged. Replacing the intake channel requires an equally private, verified, documented route and does not alter historical findings.

## D235 - Public evidence parsers remain centrally bounded and exactly inventoried

- Date: 2026-08-01
- Status: accepted
- Decision: Route the public-evidence manifest YAML and downloaded JSON through the existing `reconforge.io.structured` bounded ingress with explicit size, depth, node, string, number, and duplicate-key policies. Preserve exact numeric lexemes for `Decimal` validation. Keep only the mixed-encoding CSV reader as a direct parser and register that exact call site as FI-023 with named entrypoints, controls, tests, residual risks, and claim limits.
- Consequence: The parser inventory remains fail closed and the public-data experiment cannot expand accepted formats or parser surfaces silently. The full-suite regression was repaired without wildcard allowlists, test exclusions, skips, retries, or `continue-on-error`; the only remaining failure is the intentional Phase 3 external-evidence guard.
- Rollback: Remove the public-data experiment and FI-023 together, or replace the CSV path with a central bounded adapter and delete FI-023 only after the exact inventory and hostile-input tests pass. Do not retain an orphaned parser exception.

## D236 - Owner and project team control release approval; external assurance is optional

- Date: 2026-08-01
- Status: accepted by repository owner
- Decision: Make the repository owner and authorized project team the release authority. Treat `P3-EXT-001` controlled pilots and `P3-EXT-002` independent review as optional assurance items with `deferred` status, not prerequisites for Phase 1–3 owner/team publication. Close required work only from retained internal/team code, test, runtime, build, security, migration, restore, and rollback evidence.
- Consequence: Phase 1–3 contains 41 required tasks and two optional assurance items. External participants, accountants, engineers, customers, or an independent reviewer are not staffing requirements for owner/team release. Internal evidence still cannot be described as customer validation, an external pilot, an independent review, certification, compliance, universal superiority, or unqualified Enterprise readiness. Known unaccepted Critical/High findings and failed required technical gates remain release blockers.
- Rollback: Restore the two assurance items as release-blocking gates, set required closure false, and rerun the exact contract and release gates. Historical external-evidence records remain intact under either policy.

## D237 - Financial consolidation starts with explicit balanced translation, not automatic posting

- Date: 2026-08-01
- Status: accepted
- Decision: Start Phase 4 with a versioned deterministic translation artifact over at least two exactly balanced entity trial balances. Require one functional currency and source digest per entity, explicit source-to-group account mapping, explicit rate type and bucket per line, one source-bound rate per period/currency/type/bucket key, versioned Money policy, canonical ordering, complete rounding/CTA evidence, replay verification, and immutable tenant/workspace artifact scope. Treat the CTA only as an unposted proposal.
- Consequence: The slice creates a reliable financial primitive for later consolidation workflows without claiming ownership consolidation, eliminations, NCI, statutory statements, journal approval, remeasurement, live rate feeds, source write-back, accounting-standard compliance, Enterprise readiness, or global superiority. Full close/consolidation remains `P4-FIN-002`.
- ADR: `docs/adr/0210-consolidation-translation-is-balanced-explicit-and-non-posting.md`.
- Rollback: Remove the optional domain/application/object adapter, schema, module metadata, and documentation. No SQLite/PostgreSQL migration, ledger mutation, API/CLI compatibility change, source call, tag, release, or production rollback is required.

## D238 - Effective ownership and NCI remain replayable presentation until governed posting exists

- Date: 2026-08-01
- Status: accepted
- Decision: Build worksheet v1 only from a replay-valid translation artifact. Require exact effective-dated non-overlapping direct ownership with distinct preparer/approver, one active controlling parent per non-root entity, an acyclic rooted graph, exact path multiplication, visible NCI net-assets/current-profit presentation and rounding, and explicit source-bound elimination proposals that balance to zero. Keep every NCI/elimination result unposted and the complete worksheet at `posting_effect=none`.
- Consequence: The first P4-FIN-002 slice can explain historical selection, indirect ownership, NCI percentage, and elimination effects without fabricating an acquisition model or bypassing a future journal/period lifecycle. It does not close P4-FIN-002 and cannot be described as statutory consolidation, posted books, accounting-standard compliance, or production readiness.
- ADR: `docs/adr/0211-consolidation-ownership-is-effective-dated-and-worksheets-do-not-post.md`.
- Rollback: Remove the optional lifecycle domain contract, application method, schema, test, and metadata/docs. No database, journal, network, source system, tag, release, or deployment rollback is required.

## D239 - Local consolidation close state is replayable control-journal evidence, not legal-book posting

- Date: 2026-08-01
- Status: accepted
- Decision: Persist verified consolidation worksheets only through a local SQLite migration-25 lifecycle with close periods, immutable run lines, exact posting/reversal control-journal effects, and period lock/reopen events. Require permissioned maker-checker approval, actor-attributed SoD, bounded worksheet JSON persistence, trigger-enforced lifecycle transitions, atomic audit rollback, backup/restore replay through the same triggers, and integrity verification over worksheet/result/effect/period-event digests.
- Consequence: P4-FIN-002 gains a governed local close-lifecycle foundation without claiming statutory consolidation, legal-book posting, acquisition accounting, PostgreSQL parity, API/CLI/UI operation, live provider integration, source-ERP/bank mutation, independent assurance, or production readiness. Source systems and Finance Core legal books remain outside the mutation boundary.
- ADR: `docs/adr/0212-consolidation-close-lifecycle-is-local-and-replayable.md`.
- Rollback: Restore from a verified pre-migration backup, or remove migration-25/application/repository/schema/manifest/docs/test changes before adoption. No source ERP, bank, hosted service, tag, release, or production system is mutated by this slice.

## D240 - Durable-job load profile is structural and non-claim

- Date: 2026-08-01
- Status: accepted
- Decision: Add `reconforge/benchmark/durable_job_load.py` as the first P4-SCL-001 slice. It drives the existing durable-job worker loop under real ThreadPoolExecutor contention on a shared SQLite database over a declared small tier (8 workers, 64 jobs, 4 partitions per job, 4 tenants = 256 declared partition effects). The closed schema-v1 manifest carries only the structural outcome and excludes observed runtime/peak-memory/throughput from the manifest digest so it is reproducible across runs and hardware. `verify_load_manifest` asserts completed jobs equal the declared count, duplicate partition effects are zero, the queue drains to zero, committed effects equal completed * partitions, per-tenant completions sum to the declared count, and limitations retain honest non-claim wording.
- Consequence: P4-SCL-001 gains the first reproducible multi-worker load profile with no-duplicate-effect proof under contention, but it does not claim a scale tier, SLO, backpressure behaviour, soak result, cancellation-under-load, distributed capacity, PostgreSQL load parity, or 10K/100K/1M/10M tier publication. SQLite serializes writes under `BEGIN IMMEDIATE`, so measured contention bounds multi-worker coordination, not database partition parallelism. No new persistence primitive, domain type, repository method, migration, API, CLI, UI, PostgreSQL, tag, release, or deployment is introduced.
- ADR: `docs/adr/0213-durable-job-load-profile-is-structural-and-non-claim.md`.
- Rollback: Remove `reconforge/benchmark/durable_job_load.py`, `tests/test_durable_job_load_profile.py`, ADR 0213, the execution-state entries, and the MANIFEST.in/test-membership lines. No database migration, domain change, repository change, API, CLI, UI, tag, release, or deployed service rollback is required.

## D241 - Durable-job cancellation evidence is bounded and structural

- Date: 2026-08-02
- Status: accepted
- Decision: Add a local SQLite cancellation harness over the existing durable-job contracts. Cancel only a declared queued subset before claims, assert no effects for cancelled jobs and exactly-once completion for the remainder, and exercise a separate running-owner cancellation that releases its lease after a bounded committed prefix. Keep runtime/peak-memory observations outside the structural digest and retain explicit limitations.
- Consequence: P4-SCL-001 gains reproducible queued and running cancellation evidence without a new migration, repository primitive, API, CLI, UI, provider, or scale claim. Backpressure, soak, retry/backoff coupling, PostgreSQL parity, distributed capacity, and 10K/100K/1M/10M tiers remain open.
- ADR: `docs/adr/0214-durable-job-cancellation-profile-is-structural-and-non-claim.md`.
- Rollback: Remove the cancellation harness, tests, ADR, manifest entry, and execution evidence. No database, source system, hosted service, release, or production state is mutated.

## D242 - Grouped matching is bounded, exact, and non-posting

- Date: 2026-08-02
- Status: accepted
- Decision: Add a pure grouped matcher with exact Decimal records, explicit settlement currency and sourced FX, signed fee adjustments, bounded subset enumeration, and non-overlapping maximum-cover selection. Equal-optimum groupings and exhausted budgets remain explicit ambiguity; stable IDs provide deterministic replay digests.
- Consequence: P4-MAT-001 gains evidence for one-to-many, many-to-one, and true many-to-many/netting without hidden greedy choices or cross-currency coercion. Partial settlement, carry-forward/sequence strategies, mutation/crash-resume integration, engine parity, and scale benchmarks remain open. The slice performs no posting or connector write-back.
- ADR: `docs/adr/0215-bounded-grouped-matching-is-explainable-and-non-posting.md`.
- Rollback: Remove `reconforge/reconciliation/grouped_matching.py`, its tests, manifest entry, ADR, and execution records. No migration, source system, hosted service, release, or deployment state is changed.

## D243 - Partial settlement is a visible proposal, never silent closure

- Date: 2026-08-02
- Status: accepted
- Decision: Extend the existing bounded grouped matcher with an explicit `partial-settlement` mode. Enumerated exact groups win first; otherwise positive groups settle the smaller net total and carry immutable left/right residuals into the decision digest. Existing partition, date, cardinality, search-budget, and ambiguity rules remain mandatory.
- Consequence: The matching portfolio can express fee/FX-aware partial settlement without pretending that an outstanding balance was reconciled. It does not post, write back, allocate across multiple runs, or implement carry-forward/sequence/reversal-specific policies.
- ADR: `docs/adr/0216-bounded-partial-settlement-keeps-residuals-visible.md`.
- Rollback: Remove the new mode, residual fields, tests, strategy/schema/manifest updates, ADR, and execution records. No database or external system state is changed.

## D244 - Portfolio matching is bounded set selection, not greedy repetition

- Date: 2026-08-02
- Status: accepted
- Decision: Add `portfolio` mode as a separate result contract. Enumerate exact grouped candidates under existing ceilings, select a maximum-cover non-overlapping set with minimum aggregate difference, and expose unmatched IDs. Equal optima and budget exhaustion remain unresolved ambiguity.
- Consequence: Several disjoint settlements can be replayed from one partition without record reuse or call-order dependence. The existing single-group result remains backward compatible. Partial groups inside portfolios, carry-forward/sequence/reversal-specific policy, mutation/crash-resume, engine parity, and scale benchmarks remain open.
- ADR: `docs/adr/0217-bounded-non-overlapping-group-portfolio.md`.
- Rollback: Remove portfolio mode, application/strategy wiring, tests, manifest/schema/documentation entries, ADR, and execution records. No database or external state is changed.

## D245 - Carry-forward is bounded FIFO with visible residuals

- Date: 2026-08-02
- Status: accepted
- Decision: Add an experimental `bounded-carry-forward-fifo` strategy for one currency/partition. Sort by business date and stable IDs, allocate exact Decimal amounts to the oldest eligible obligation within a declared date window, and expose every residual. Search/allocation ceilings fail closed with explicit ambiguity.
- Consequence: Sequence/window matching now has a replayable non-posting contract. Reversal pairing, multi-currency conversion, crash resume, cross-engine parity, and scale performance remain unimplemented and unclaimed.
- ADR: `docs/adr/0218-bounded-carry-forward-fifo-keeps-residuals-visible.md`.
- Rollback: Remove the carry-forward domain/strategy, tests, manifest entry, ADR, and execution records. No database or external state is changed.

## D246 - Reversal pairing prefers explicit lineage and never posts

- Date: 2026-08-02
- Status: accepted
- Decision: Add an experimental bounded reversal-pairing strategy for one currency/partition. Require opposite signs, prefer `reversal_of` lineage, then rank amount difference/date span/stable identity; consume each original once and return ambiguity on equal candidates or budget exhaustion.
- Consequence: Reversal-specific matching becomes replayable and explainable without silently closing or mutating financial records. Approval, journal posting, compensation, crash resume, cross-engine parity, and scale evidence remain separate requirements.
- ADR: `docs/adr/0219-bounded-reversal-pairing-is-explicit-and-non-posting.md`.
- Rollback: Remove the reversal domain/strategy, tests, manifest entry, ADR, and execution records. No database or external state is changed.

## D247 - Portfolio partial settlement is opt-in and residual-preserving

- Date: 2026-08-02
- Status: accepted
- Decision: Keep portfolio exact-only by default. Add a digest-bound `allow_partial_settlement` flag that enables positive unequal candidates; exact groups remain eligible, non-overlap and budgets remain enforced, and residuals are emitted in each selected decision.
- Consequence: Portfolio callers cannot silently change from exact reconciliation to partial proposals. Equal-cost portfolios remain unresolved ambiguity; no posting or external mutation is performed.
- ADR: `docs/adr/0220-portfolio-partial-settlement-requires-explicit-policy.md`.
- Rollback: Remove the flag, candidate logic, tests, ADR, and execution records. No database or external state is changed.

## D248 - Reference REST integration is schema-closed and read-only

- Date: 2026-08-02
- Status: accepted
- Decision: Add a synthetic provider-neutral REST connector over the existing governed network executor. Require exact allowlisted HTTPS, operator secret references, bounded cursors/idempotency/retries, and a closed record page with exact Decimal text and unique IDs. Keep write capability absent.
- Consequence: Connector SDK has one executable reference integration without claiming a live ERP/bank relationship. Provider credentials, acknowledgement reconciliation, compensation, and write-back remain separate gates.
- ADR: `docs/adr/0221-reference-rest-connector-is-read-only-and-schema-closed.md`.
- Rollback: Remove the connector, tests, docs, ADR, and manifest entries. No external or database state is changed.

## D249 - Write-back is an approved, acknowledged, and compensatable intent

- Date: 2026-08-02
- Status: accepted
- Decision: Add a closed provider-neutral write-back lifecycle. Keep the feature flag disabled by default; require an allowlisted connector/operation and a distinct human actor with step-up/MFA assurance; dispatch only from the approved state; bind acknowledgement to the original idempotency key and response digest; and require a separate explicit compensation transition.
- Consequence: Future adapters receive a stable governance/idempotency boundary without exposing payloads, secrets, destinations, or pretending that a live ERP/bank mutation exists. The connector manifest remains read-only until a provider-specific write capability is separately reviewed.
- ADR: `docs/adr/0222-governed-writeback-is-approved-and-acknowledged.md`.
- Rollback: Remove `reconforge/connectors/writeback.py`, exports, tests, docs, ADR, and package entries. No database or external state is changed.

## D250 - Reference SFTP is transport-injected and read-only

- Date: 2026-08-02
- Status: accepted
- Decision: Add a synthetic `reference-sftp-readonly` connector with exact SFTP egress, runtime secret reference, traversal-free root, bounded file count/size, extension allowlist, deterministic cursor ordering, and content digests. Keep SFTP registration separate from the HTTPS executor and inject the transport protocol rather than bundling SSH or making network calls.
- Consequence: SFTP security/replay behavior is testable without external accounts; host-key policy, SSH implementation, provider conformance, credential rotation, and live evidence remain unclaimed. The connector is read-only.
- ADR: `docs/adr/0223-reference-sftp-is-transport-injected-and-read-only.md`.
- Rollback: Remove the SFTP module, tests, docs, ADR, exports, and manifest changes. No database or external state is changed.

## D251 - Reference object storage is tenant-scoped and read-only

- Date: 2026-08-02
- Status: accepted
- Decision: Add a synthetic object-storage reader with exact HTTPS egress, runtime credential reference, explicit tenant ID, traversal-free key prefix, bounded objects/bytes, deterministic cursor, and SHA-256 verification. Keep it on a dedicated transport protocol so the existing immutable ObjectStoreProtocol and adapters remain compatible.
- Consequence: Object-storage connector behavior is testable without cloud accounts; IAM, encryption, provider pagination/retry, and live evidence remain unclaimed. No write/delete/presign capability is added.
- ADR: `docs/adr/0224-reference-object-storage-is-tenant-scoped-and-read-only.md`.
- Rollback: Remove the object connector module, tests, docs, ADR, exports, and manifest entries. No database or external state is changed.

## D252 - Reference database access is named-query and tenant-scoped

- Date: 2026-08-02
- Status: accepted
- Decision: Add a synthetic database reader with two closed named-query profiles, exact HTTPS egress, runtime credential reference, explicit tenant scope, bounded rows/cells, cursor pagination, stable ordering, duplicate rejection, and exact Decimal row validation. Never accept SQL or arbitrary identifiers; inject the transport.
- Consequence: SQL injection is structurally absent from the connector SDK and tests run without a live database. Prepared statements, least privilege, timeouts, cancellation, consistency, migration compatibility, and live provider evidence remain adapter responsibilities.
- ADR: `docs/adr/0225-reference-database-is-named-query-and-tenant-scoped.md`.
- Rollback: Remove the database connector module, tests, docs, ADR, exports, and manifest entries. No database or external state is changed.

## D253 - Durable retries must resume committed checkpoints

- Date: 2026-08-02
- Status: accepted
- Decision: Add a bounded concurrent failure-injection harness that faults after at most one committed partition, schedules the existing `retrying` transition, and verifies that the next lease resumes from the checkpoint without duplicate partition effects. Keep retry eligibility immediate and provider-neutral for this slice.
- Consequence: SQLite evidence now covers retry/checkpoint coupling and retry ceilings under contention. Provider-specific backoff/jitter, PostgreSQL parity, external compensation, and scale/soak evidence remain unclaimed.
- ADR: `docs/adr/0226-durable-job-retry-failure-injection.md`.
- Rollback: Remove the retry harness, tests, benchmark document, ADR, and manifest/execution entries. No schema or production behavior changes.

## D254 - Grouped matching replay is checkpointed and cross-engine compared

- Date: 2026-08-02
- Status: accepted
- Decision: Add a four-partition synthetic replay harness covering grouped strategy modes. Compare the public strategy adapter with the application boundary, persist effects through the existing durable-job checkpoint contract, inject a post-checkpoint fault, and require the resumed effect digest to equal an uninterrupted baseline.
- Consequence: Advanced matching now has direct crash/resume and adapter/application parity evidence, plus an adversarial one-cent mutation sentinel. PostgreSQL parity, a mutation-testing tool score, and scale benchmarks remain unclaimed.
- ADR: `docs/adr/0227-grouped-matching-replay-parity.md`.
- Rollback: Remove the replay harness, tests, benchmark document, ADR, manifest, and execution entries. No schema or production behavior changes.

## D255 - PostgreSQL grouped matching remains a worker adapter, not a second algorithm

- Date: 2026-08-02
- Status: accepted
- Decision: Add a persistence-free `PostgresGroupedMatchingAdapter` that translates streamed PostgreSQL worker partitions into the existing grouped strategy contract, enforces exact input boundaries, skips committed checkpoints, and returns JSON-safe deterministic output. Keep all database I/O and durable effects in the existing worker/repository.
- Consequence: The PostgreSQL parity inventory now exposes the adapter as `contract_only`, avoiding a false live-parity claim while providing a stable integration point for a future real PostgreSQL drill.
- ADR: `docs/adr/0228-postgres-grouped-matching-worker-boundary.md`.
- Rollback: Remove the adapter, tests, ADR, manifest, inventory, and execution entries. No schema or production behavior changes.

## D256 - Publish one hardware-scoped 10K durable-job tier

- Date: 2026-08-02
- Status: accepted
- Decision: Declare 1,000 durable jobs with ten partition effects each, 16 workers, and four tenant lanes as the first 10K scale profile. Reuse generation-fenced leases, checkpoints, idempotency, and duplicate-effect audits. Raise SQLite's bounded busy wait to 60 seconds so transient writer contention does not fail a valid local workload.
- Consequence: ReconForge now has two reproducible 10K runs with 10,000 committed effects and identical structural/effect digests. The result is local SQLite evidence only; it does not establish PostgreSQL capacity, backpressure, soak, HA/DR, SLO, or larger tiers.
- ADR: `docs/adr/0229-durable-job-10k-tier-is-hardware-scoped.md`.
- Rollback: Remove the scale wrapper/report/tests, ADR, manifest entries, and revert the bounded busy-timeout change. No schema or external state is changed.

## D257 - Publish a partitioned 10K grouped-matching tier

- Date: 2026-08-02
- Status: accepted
- Decision: Measure 10,000 records as 2,500 independent true many-to-many partitions. Run each partition through the public grouped strategy and application boundary, keep the published per-partition search ceilings, and sample reversed input order for permutation evidence.
- Consequence: The matching workstream now has a reproducible 10K-record result with zero ambiguity/unmatched partitions, zero adapter/application mismatches, and stable digests. This is exact-USD synthetic single-process evidence; FX/fee/partial density, PostgreSQL runtime, distributed load, and larger tiers remain open.
- ADR: `docs/adr/0230-grouped-matching-10k-is-partitioned-and-bounded.md`.
- Rollback: Remove the benchmark module, tests, report, ADR, and manifest entries. No schema or external state is changed.

## D258 - Publish a partitioned 100K grouped-matching tier

- Date: 2026-08-02
- Status: accepted
- Decision: Extend the bounded partitioned benchmark to 100,000 exact-USD records as 25,000 independent four-record true many-to-many partitions. Run every partition through the public strategy and application boundaries, sample reversed-order replay, and retain per-partition search ceilings.
- Consequence: ReconForge now has a reproducible 100K algorithmic observation with zero ambiguity/unmatched partitions, zero adapter/application mismatches, stable permutation behavior, and identical structural/effect digests across two runs. The result is one-host single-process evidence only; it does not establish PostgreSQL parity, distributed capacity, SLOs, soak, or 1M performance.
- ADR: `docs/adr/0231-grouped-matching-100k-is-partitioned-and-bounded.md`.
- Rollback: Remove the 100K wrapper, tests, report, ADR, and manifest entries. No schema or external state is changed.

## D259 - Publish a partitioned 1M grouped-matching tier

- Date: 2026-08-02
- Status: accepted
- Decision: Extend the bounded partitioned benchmark to 1,000,000 exact-USD records as 250,000 independent four-record true many-to-many partitions. Execute every partition through the public strategy and application boundaries, sample every 10,000th partition under reversed input order, and require identical effect and manifest digests across complete runs.
- Consequence: The advanced matching workstream now has a reproducible 1M algorithmic observation with zero ambiguity/unmatched partitions, zero adapter/application mismatches, stable permutation behavior, and identical digests across two runs. This remains one-host single-process evidence and does not establish PostgreSQL parity, distributed capacity, SLOs, soak, or domain-diverse financial performance.
- ADR: `docs/adr/0232-grouped-matching-1m-is-partitioned-and-bounded.md`.
- Rollback: Remove the 1M wrapper, tests, report, ADR, and manifest entries. No schema or external state is changed.

## D260 - Persist effective-dated consolidation ownership masters

- Date: 2026-08-02
- Status: accepted
- Decision: Add SQLite migration 26 and a backend-neutral application port for immutable approved direct ownership interests. Store exact Decimal text, effective intervals, source digest, preparation/approval actors, and approval timestamp; reject overlapping intervals for one subsidiary within a group and resolve one active interest by reporting date.
- Consequence: Consolidation close can now source its effective ownership inputs from a durable, tenant/workspace-isolated local master with deterministic replay and backup/restore coverage. This does not add acquisition accounting, ownership-change postings, statutory statements, PostgreSQL parity, or external write-back.
- ADR: `docs/adr/0233-persist-effective-dated-consolidation-ownership.md`.
- Rollback: Revert migration 26, adapter/application files, backup table wiring, tests, and documentation. Existing migration-25 databases remain readable before applying migration 26.

## D261 - Add PostgreSQL ownership parity at contract-only maturity

- Date: 2026-08-02
- Status: accepted
- Decision: Add Alembic 0054 and a tenant-scoped PostgreSQL adapter for the same typed ownership contract. Use NUMERIC percentages, forced RLS keyed by `app.tenant_id`, immutable triggers, transaction-scoped overlap checks, and a reversible migration. Mark the parity inventory `contract_only` until a disposable non-superuser live run is executed.
- Consequence: Enterprise deployments now have a reviewed PostgreSQL schema/adapter path without falsely counting static tests as runtime parity. SQLite remains the locally executed persistence mode; live migration, RLS, isolation, rollback, and restore evidence remain explicit next gates.
- ADR: `docs/adr/0234-postgres-consolidation-ownership-contract.md`.
- Rollback: Downgrade Alembic 0054 and remove the adapter/schema/tests/docs; no customer data or external service is touched by the contract-only slice.

## E-280 — Execute the PostgreSQL ownership adapter under a non-privileged role

- Decision: Add one dedicated live runtime contract to the existing server-boundaries gate. The test provisions unique synthetic tenants, grants only the test application role's table/schema access, and exercises the adapter through the configured PostgreSQL connection factory.
- Controls: Verify same-input replay returns the same immutable ID, effective resolution is tenant-scoped, overlapping effective intervals fail closed, and direct updates are rejected by the database trigger. No real credentials or customer data are used.
- Evidence: GitHub Actions run `30755552134` passed the test on PostgreSQL 16 Alpine; the parity inventory records the boundary as `live_verified_current` with explicit single-node/no-restore/no-HA limits.
- Rollback: Revert the test and inventory/docs changes. No production database or external provider is changed.

## E-281 — Keep ownership-change accounting policy-bound and non-posting

- Decision: Add a pure-domain `ownership-change-adjustment-v1` contract that calculates NCI delta from prior/new group ownership and balances a signed consideration effect with a parent-equity line.
- Controls: Require one reporting currency, finite Decimal percentages, distinct preparer/approver with approval-before-preparation ordering, source digest, policy ID/version, visible rounding delta, exact three-line balance, deterministic request/result digests, and `posted: false`.
- Boundary: The contract does not select statutory treatment, goodwill, purchase-price allocation, disposal accounting, or ledger posting. Those require separate approved policy and application slices.
- Evidence: Eight focused domain/schema/tamper tests pass; package manifest and finance-core module evidence include the new contract.
- Rollback: Remove the pure module, schema, test, manifest entry, registry evidence, ADR, and benchmark report. No migration or external data is touched.
# E-282 — 100K durable-job tier is bounded SQLite evidence

- Date: 2026-08-02
- Decision: publish a 10,000-job/100,000-effect profile with 16 workers and
  four statically tenant-pinned lanes. Keep the 600-second lease and
  300-second busy timeout scoped to this benchmark only.
- Rationale: 32 workers and the default 60-second timeout both produced
  SQLite lock failures; the bounded profile completed twice without duplicate
  effects or queue residue.
- Boundary: this is not PostgreSQL, distributed-capacity, backpressure, soak,
  HA/DR, or production-sizing evidence.
# E-283 — PostgreSQL close-management lifecycle runtime evidence

- Date: 2026-08-02
- Decision: record the current CI non-privileged runtime contract as evidence,
  while retaining the inventory's `live_test_available` status until a
  dedicated current-live gate is recorded.
- Evidence: tenant-scoped periods/tasks/dependencies, dependency-cycle refusal,
  readiness and lock/reopen transitions, locked mutation refusal, audit/outbox
  parity, and tenant isolation.
- Boundary: this does not close consolidation posting, eliminations/NCI,
  statutory statements, restore, HA/DR, or RPO/RTO.
# E-284 — Payment-statement reference connector remains read-only

- Date: 2026-08-02
- Decision: add a synthetic payment-statement connector on the governed REST
  executor, with a closed schema and read capability only.
- Rationale: statement ingestion is a useful connector vertical slice while
  preserving local-first operation and avoiding an unverified bank/provider
  claim.
- Boundary: no live bank contract, settlement proof, payment posting, or
  write-back is introduced.
# E-285 — Add bounded amount, region, and data-class ABAC attributes

- Date: 2026-08-02
- Decision: extend the central policy context with optional exact Decimal
  amount floors/ceilings and explicit region/data-classification scopes.
- Rationale: these are additive, deny-by-default attributes needed for
  enterprise authorization while preserving existing callers and local mode.
- Boundary: policy-engine behavior is covered; broad surface migration and
  identity-provider/RLS administration remain open.
# E-286 — Backpressure is measured as an explicit local producer cap

- Date: 2026-08-02
- Decision: keep the backpressure experiment in a separate benchmark module;
  do not alter the published 10K/100K manifest contract or production queue
  defaults.
- Evidence: a producer cap of eight queued jobs held at depth 8 while workers
  completed all 64 jobs and 256 effects without duplicates.
- Boundary: this is local SQLite evidence, not distributed backpressure or an
  SLO/capacity claim.
# E-287 — Provider write-back transport is injected and acknowledgement-bound

- Date: 2026-08-02
- Decision: add a transport protocol and fail-closed dispatch helper after
  approval, without selecting or invoking a real provider.
- Evidence: synthetic success, provider timeout, and idempotency mismatch
  tests pass; only digest-bound intent metadata crosses the boundary.
- Boundary: no live network, credential, settlement, or posting evidence.
# E-288 — Grouped matching mutation campaign is targeted, not universal

- Date: 2026-08-02
- Decision: publish three deterministic request-level financial mutants and
  require every one to change its corresponding decision digest.
- Evidence: 3/3 mutants killed, zero survivors.
- Boundary: no source-code mutation engine score or whole-platform mutation
  coverage is claimed.
# E-289 — Separate current-live gate for Close Management

- Date: 2026-08-02
- Decision: promote only `CloseManagementApplicationService` after its
  current PostgreSQL runtime contract, keeping Consolidation Close separate.
- Evidence: the gate records PostgreSQL 16 CI, non-privileged execution,
  lifecycle/tenant/audit-outbox checks, and explicit single-node limits.
- Boundary: no claim for consolidation posting, restore, HA/DR, or RPO/RTO.

# E-309 — Provider acknowledgement reconciliation remains local and digest-bound

- Date: 2026-08-03
- Decision: expose a separately authorized acknowledgement route only for an
  already-dispatched immutable intent; require the original idempotency key and
  persist provider reference/response digest as a new version.
- Evidence: migration 30, scoped API tests, lifecycle tests, Ruff, and Mypy
  pass. The response explicitly keeps network dispatch disabled.
- Boundary: no live provider, credentials, settlement, compensation, or
  production write-back claim is made.

# E-310 — Consolidation close API is read-only and replay-verified

- Date: 2026-08-03
- Decision: expose the existing local consolidation-close lifecycle through a
  permissioned read-only API. Pass the authenticated actor into the repository,
  scope list operations by workspace, and require replay verification before
  run details are returned.
- Evidence: 13 focused API/repository/authorization tests, Ruff, Mypy, and
  diff-check pass. Tampered worksheet payloads and unknown workspaces fail
  closed.
- Boundary: this does not add statutory posting, PostgreSQL parity, UI
  mutation, or source-system write-back.

# E-311 — PostgreSQL close reads must replay and reopening must be independent

- Date: 2026-08-03
- Decision: treat PostgreSQL JSONB as untrusted persisted evidence at every read
  boundary; reproduce the worksheet and compare canonical/journal digests.
  Persist lock/reopen events with supplied reasons and require a different actor
  for reopening a period.
- Evidence: adapter contract tests pass locally; the existing CI server-boundary
  test executes the strengthened lifecycle against PostgreSQL 16 under the
  non-privileged role.
- Boundary: one-node synthetic control-journal evidence only; no statutory,
  HA/DR, restore, or source-system posting claim.
## D263 - HA/DR verification status is conditional on explicit topology evidence

- **Decision**: Require seven explicit HA/DR verification gates in the
  operational profile and reject `status: verified` unless all are true.
- **Rationale**: A measured single-host drill can prove useful bounded
  behavior, but it cannot establish independent failure domains, quorum,
  automatic failover, or production SLOs. Conditional schema validation keeps
  future documentation fail-closed.
- **Consequence**: The retained profile stays `partial`; no runtime or
  deployment behavior changes, and independent-host/site-loss evidence remains
  open under P4-REL-001.

## D264 - Project grouped decisions at the PostgreSQL worker boundary

- **Decision**: Keep the grouped algorithm persistence-free, but project each
  decision into the existing per-source PostgreSQL result/exception schema.
  Matched groups emit deterministic Cartesian edges; unresolved groups emit
  explicit single-sided outcomes and review exceptions. Preserve complete
  group evidence and strategy digests in lineage, and let database-owned
  canonical columns override shadowing JSON attributes.
- **Rationale**: The worker's completion invariant requires every registered
  source identity to be represented, while duplicating grouped logic in SQL
  would create backend drift. A projection closes the runtime gap without a
  second algorithm or a new schema.
- **Evidence**: Focused adapter/reconciliation tests pass, and the new live
  server-boundaries contract exercises a non-superuser PostgreSQL worker with
  RLS, checkpointing, direct strategy digest parity, and sibling-tenant
  isolation.
- **Boundary**: This is one bounded synthetic runtime proof; PostgreSQL scale,
  soak/backpressure, distributed capacity, HA/DR, live connectors, posting,
  and write-back remain unclaimed.
- **ADR**: `docs/adr/0268-postgres-grouped-matching-runtime-parity.md`.

## D265 - Preserve checkpointed grouped output across PostgreSQL worker loss

- **Decision**: Treat an unhandled worker loss as a lease-expiry recovery, not
  a normal matcher failure. Keep already committed partitions immutable, fence
  replacements until the lease expires, and resume only keys returned by the
  checkpoint table.
- **Rationale**: Catching process-termination signals as ordinary failures could
  hide partial execution. The existing atomic checkpoint/result transaction and
  generation-bound lease provide a safer recovery boundary without a second
  matching implementation.
- **Evidence**: E-318 adds a live non-superuser PostgreSQL contract with two
  partitions, deliberate process-crash injection, lease fencing, takeover, and
  exact no-duplicate result assertions.
- **Boundary**: One synthetic recovery path only; no process supervisor,
  automatic failover, HA/DR, capacity, live providers, posting, or write-back
  claim is made.
- **ADR**: `docs/adr/0269-postgres-grouped-matching-crash-resume.md`.

## D266 - Persist PostgreSQL consolidation journal and effect lines

- **Decision**: Add migration `0057_pg_consol_journal_lines` with tenant-scoped
  run-line and effect-line tables. Materialize only verified worksheet lines,
  store exact minor units plus canonical decimal text, and protect child rows
  and effects with forced RLS and append-only triggers. Replays compare the
  canonical line/effect digests before a run is exposed.
- **Compatibility**: Rows created before 0057 remain readable as legacy
  worksheet/effect metadata. A subsequent governed effect transition may
  materialize the exact compatibility lines; no silent rehash or mutation is
  accepted.
- **Evidence**: Focused PostgreSQL schema/migration/registry and SQLite/API
  compatibility suites pass locally. Implementation commit `9b9ff98d` and
  final documentation-bound head `04019689` and final evidence-bound head
  `17170ce1` both passed the live PostgreSQL server-boundaries contract under
  the non-privileged role, including runtime parity, tamper refusal, and tenant
  isolation.
- **Boundary**: This does not claim statutory consolidation, acquisition or
  equity-method accounting, live source-system posting/write-back, HA/DR,
  scale, or production readiness.
- **ADR**: `docs/adr/0270-postgres-consolidation-journal-line-parity.md`.

## D267 - Expose one backend-neutral FX evidence projection

- **Decision**: derive `translation_evidence` from the replay-verified
  `ConsolidationTranslationResult` at both SQLite and PostgreSQL read
  boundaries. Bind the existing result digest and add a canonical line-level
  lineage digest plus exact currency/rate/rounding summary fields.
- **Rationale**: Reviewers need a stable currency-control projection without a
  second FX calculation or backend-specific JSON interpretation. An additive
  projection preserves existing schemas and keeps the full worksheet as the
  source of truth.
- **Boundary**: This improves explainability only; it does not establish live
  rates, statutory treatment, ERP/bank write-back, HA/DR, scale, or production
  readiness.
- **ADR**: `docs/adr/0271-consolidation-translation-evidence-projection.md`.

## D268 - Make mutating API route policy fail closed at startup

- **Decision**: validate the route authorization inventory during app
  construction. Public/identity mutation routes must be in explicit handshake
  allowlists; other mutations require permission-bearing or dynamic policy
  contracts, while SCIM is explicitly classified as its own protocol boundary.
- **Rationale**: A new mutation with a missing or overly broad dependency must
  fail deterministically before serving requests. The existing inventory digest
  remains stable; this adds a validation gate rather than silently changing
  route contracts.
- **Boundary**: API route/action classification only; federation, policy
  administration, distributed invalidation, and jobs/exports/UI coverage stay
  open.
- **ADR**: `docs/adr/0272-api-mutating-authorization-surface-gate.md`.

## D269 - Prove the PostgreSQL transient retry path with real leases

- **Decision**: add a live server-boundaries scenario that commits one
  partition, schedules a transient retry, and recovers from a new worker lease.
  The recovery must preserve the committed checkpoint and complete the
  remaining partition once.
- **Rationale**: Lease takeover/crash evidence is not the same as a normal
  retryable fault. Exercising the repository transition and checkpoint tables
  closes that distinct runtime branch without inventing a queue or provider.
- **Boundary**: synthetic two-partition runtime only; capacity, soak,
  distributed supervision, HA/DR, and production retry policy remain open.
- **ADR**: `docs/adr/0273-postgres-durable-job-retry-runtime-gate.md`.

## D270 - Add a statement-shaped management evidence artifact

- **Decision**: derive a sectioned `ManagementStatementPackage` from the
  replay-verified worksheet, grouped by account type and bound to exact section
  totals, zero balance, worksheet digest, and artifact digest. Expose it through
  both close adapters without a schema migration.
- **Rationale**: Reviewers need a stable statement-shaped drill-down while the
  project does not yet have enough policy to claim statutory presentation. The
  package reuses the verified trial-balance lines and cannot drift into a second
  financial calculation path.
- **Boundary**: management-only evidence; statutory classification, acquisition
  accounting, cash-flow semantics, live rates, and source posting remain open.
- **ADR**: `docs/adr/0274-management-statement-package.md`.

## D271 - Expose consolidation evidence through a read-only CLI

- **Decision**: add `consolidation runs`, `consolidation run`, and
  `consolidation summary` commands that call the existing replay-verified
  close application service and SQLite adapter.
- **Rationale**: local operators need a CLI evidence path that shows the
  existing management statement and translation evidence without duplicating
  accounting calculations or adding an unreviewed mutation surface.
- **Boundary**: additive read-only local inspection. It does not implement
  lifecycle mutation, statutory statements, live rates, source write-back,
  PostgreSQL CLI parity, or UI exposure.
- **ADR**: `docs/adr/0275-consolidation-close-cli-drilldown.md`.

## D272 - Add a governed acquisition fair-value/goodwill bridge

- **Decision**: add `acquisition-fair-value-goodwill-bridge-v1` as a pure
  Decimal/Money proposal. Calculate consideration plus NCI fair value less
  identifiable net assets as goodwill, or as an explicitly policy-allowed
  bargain purchase, then emit a balanced, digest-bound non-posting bridge.
- **Rationale**: acquisition depth needs a deterministic arithmetic boundary,
  but statutory classification, tax, impairment, and journal posting require
  separate policy and review. The fail-closed bargain rule prevents silently
  converting a negative bridge into an accounting conclusion.
- **Boundary**: no purchase-price allocation, tax, impairment, step
  acquisition/disposal, legal opinion, source write-back, or posting claim.
- **ADR**: `docs/adr/0276-acquisition-fair-value-goodwill-bridge.md`.

## D273 - Expose the acquisition bridge through a strict local CLI

- **Decision**: add `reconforge consolidation acquisition-bridge` as a
  read-only JSON boundary. Require an exact top-level request field set,
  reconstruct Money under the currency registry, and route all arithmetic to
  `prepare_acquisition_fair_value_bridge`.
- **Rationale**: operators need reproducible automation without a second
  accounting implementation. Exact-field validation avoids silently ignoring
  unreviewed policy or source inputs.
- **Boundary**: no database/network side effect, approval, posting, statutory
  workflow, provider integration, or source write-back.
- **ADR**: `docs/adr/0277-acquisition-bridge-cli-boundary.md`.

## D274 - Add non-posting acquisition purchase-price allocation detail

- **Decision**: add `acquisition-purchase-price-allocation-v1` as a pure
  Decimal/Money artifact over an explicitly supplied, bounded list of
  identifiable assets and liabilities. Canonically order items by stable ID,
  reconcile book and fair-value net assets, and embed the existing verified
  goodwill/bargain bridge.
- **Rationale**: deep-close review needs traceable valuation detail without
  inventing tax, impairment, or statutory judgments. A distinct artifact
  prevents the existing goodwill bridge from silently becoming a full PPA or
  posting engine.
- **Boundary**: no tax/deferred-tax effects, impairment, statutory treatment,
  equity method, ledger posting, PostgreSQL persistence/parity, source
  write-back, or independent valuation assurance.
- **ADR**: `docs/adr/0278-acquisition-purchase-price-allocation-boundary.md`.

## D275 - Add read-only enterprise policy conflict analysis

- **Decision**: add `enterprise-policy-conflict-analysis-v1` as a deterministic
  artifact over an approved tenant-bound policy snapshot. Detect overlapping
  prepare/review/submit/approve permissions, service-account human permissions,
  unscoped privileged grants when required, and duplicate active grants.
- **Rationale**: policy administration needs explainable conflict detection
  before a provider-backed mutation surface is widened. Keeping the analyzer
  read-only prevents it from becoming an unreviewed authorization bypass.
- **Boundary**: no enforcement mutation, CentralPolicyEngine replacement,
  federation, PostgreSQL/RLS storage, distributed cache invalidation, or
  universal route/job/export/UI coverage.
- **ADR**: `docs/adr/0279-enterprise-policy-conflict-analysis.md`.

## D276 - Add PostgreSQL policy snapshot analysis boundary

- **Decision**: expose a read-only PostgreSQL policy snapshot loader and
  application service behind `POST /api/v1/admin/access/policy-analysis`.
  The route requires human-only `security.policy.manage`, an independent
  approved actor and timestamp, and executes under the existing tenant RLS
  transaction.
- **Rationale**: the local analyzer becomes useful for governed operations only
  when it can inspect the authoritative server RBAC/service-account snapshot.
  Reusing the same typed deterministic analyzer avoids a second policy dialect
  and keeps provider I/O and authorization mutation out of the path.
- **Boundary**: existing PostgreSQL role/permission tables are read only;
  tenant-wide grants are represented explicitly as unscoped analysis scopes.
  No entity/period persistence, federation, distributed invalidation, role
  mutation, session mutation, or write-back is introduced.
- **ADR**: `docs/adr/0280-postgres-policy-snapshot-analysis.md`.

## D277 - Persist bounded PostgreSQL role-permission scopes

- **Decision**: add `identity_role_permission_scopes` through Alembic
  `0058_pg_policy_permission_scopes`. Scope rows are tenant-bound, forced-RLS,
  append-only records that bind one role permission to workspace/entity/period,
  region, or data-classification dimensions. The policy snapshot loader
  groups permissions by identical active scope and retains an explicit
  tenant-wide wildcard when no row exists.
- **Rationale**: the analyzer can already reason about scope overlap, but a
  tenant-only persisted model cannot prove whether a privileged grant is
  bounded. A separate immutable table preserves compatibility with existing
  role-permission rows and makes scope evidence reviewable without silently
  widening every authorization route.
- **Boundary**: this slice does not persist amount floors/ceilings, perform
  universal policy enforcement, add federation, invalidate distributed caches,
  or create a scope-administration API. Downgrade refuses while scope evidence
  exists.
- **ADR**: `docs/adr/0281-postgres-policy-permission-scopes.md`.

## D278 - Persist exact PostgreSQL policy amount bounds

- **Decision**: add Alembic `0059_pg_policy_amt_bounds` with nullable exact
  `NUMERIC` minimum/maximum amounts on the immutable role-permission scope
  table. The typed analyzer canonicalizes finite Decimal text and uses
  inclusive interval overlap while preserving old payloads when absent.
- **Rationale**: central-policy amount floors/ceilings cannot be reviewed as
  part of a server snapshot if they are discarded at persistence boundaries.
  Keeping them in the same tenant-RLS append-only scope record preserves
  replayable evidence without silently changing authorization consumers.
- **Boundary**: amount bounds are currency-agnostic analysis evidence, not
  universal enforcement or conversion. The migration rejects non-finite,
  reversed, and evidence-losing downgrade paths; federation, distributed
  invalidation, and complete route/job/export/UI adoption remain open.
- **ADR**: `docs/adr/0282-postgres-policy-scope-amount-bounds.md`.

## D279 - Persist non-posting PostgreSQL acquisition PPA evidence

- **Decision**: add Alembic `0060_pg_consolidation_ppa`, a backend-neutral
  `AcquisitionPpaApplicationService`, and a tenant-RLS PostgreSQL adapter for
  the existing deterministic PPA artifact. Store canonical request/result
  JSONB, digests, maker-checker identity, audit evidence, and an immutable
  `posted: false` marker; verify by recomputation on writes and reads.
- **Rationale**: deep-close evidence needs durable, tenant-isolated replay
  without silently creating a statutory posting path. Idempotent artifact
  identity and append-only database guards make retries and tamper attempts
  reviewable.
- **Boundary**: no statutory acquisition accounting, tax/deferred tax,
  impairment, journal posting, live rates, provider connector, source
  write-back, restore, HA/DR, or production-readiness claim. Downgrade refuses
  while PPA evidence exists.
- **ADR**: `docs/adr/0283-postgres-consolidation-ppa-evidence-is-non-posting.md`.

## D280 - Expose PPA evidence through an authenticated PostgreSQL API only

- **Decision**: add additive `POST`/`GET` PPA routes to the explicit PostgreSQL
  server profile, with strict canonical Money bodies, authenticated actor
  binding, independent approval, central permission checks, and no SQLite
  fallback.
- **Rationale**: the durable E-332 artifact needs a controlled server consumer,
  while keeping local Community behavior and the non-posting boundary intact.
- **Boundary**: API contract tests and underlying repository runtime evidence
  do not establish live hosted API operation. No statutory posting, tax,
  impairment, provider integration, write-back, restore, HA/DR, or universal
  policy enforcement is introduced.
- **ADR**: `docs/adr/0284-postgres-ppa-api-is-server-profile-and-non-posting.md`.
-
## D246 - Durable-job fairness is exact-lane and process-scoped

- Date: 2026-08-03
- Status: accepted
- Decision: Add `DurableJobLane` and `RoundRobinDurableJobScheduler` as an
  application-level primitive. Every claim may be filtered by the complete
  tenant/workspace/entity lane, and the scheduler rotates a local cursor after
  each selected lane. SQLite and PostgreSQL keep their existing transactional,
  RLS, `SKIP LOCKED`, and lease-fencing boundaries.
- Consequence: P4-SCL-001 gains deterministic no-cross-lane fairness evidence
  for one scheduler loop. The cursor is not shared or durable; distributed
  fairness, throughput, soak, HA/DR, SLO/RPO/RTO, and production capacity stay
  unverified. No cross-tenant privileged query, migration, provider, or
  write-back is introduced.
- ADR: `docs/adr/0293-deterministic-fair-durable-job-lane-scheduling.md`.
- Rollback: Remove the scheduler types, optional claim filters, tests, ADR, and
  execution entries. No database or external system state is mutated.

## D247 - Governed write-back intent persistence is evidence-only

- Date: 2026-08-03
- Status: accepted
- Decision: add Alembic `0061_pg_writeback_intents` and a PostgreSQL
  `PostgresWritebackIntentRepository` for the existing governed write-back
  intent lifecycle. Persist only canonical intent JSON, digest, lifecycle
  version, tenant/workspace scope, and timestamp. Enforce forced RLS,
  idempotent replay, optimistic transitions, and append-only mutation refusal.
- Rationale: the connector lifecycle needs durable, tenant-isolated evidence in
  the server profile before any provider-specific dispatch is considered.
- Boundary: this proves persistence and tamper/isolation behavior only. It does
  not add provider payloads, credentials, network calls, ERP/bank
  interoperability, compensation execution, throughput, HA/DR, or production
  write-back.
- ADR: `docs/adr/0294-postgres-writeback-intent-runtime-evidence.md`.
- Rollback: downgrade refuses while intent evidence exists; after archival or
  an empty disposable database, remove migration 0061, adapter, tests, and
  execution entries without touching external systems.

## D248 - PostgreSQL server-profile write-back API is a scoped evidence boundary

- Date: 2026-08-03
- Status: accepted
- Decision: when the explicit PostgreSQL server profile is enabled, proposal,
  maker-checker approval, and acknowledgement routes use the tenant/workspace
  scoped PostgreSQL intent repository. The authenticated actor and request
  scope must match the intent; local mode remains SQLite; network dispatch stays
  disabled.
- Rationale: server deployments must not silently fall back to a local shared
  database for governed intent evidence, while Community mode must retain its
  existing behavior.
- Boundary: route contract plus the existing live repository gate prove only
  backend selection, actor/scope binding, and durable intent evidence. They do
  not prove provider I/O, secret-vault interoperability, compensation,
  throughput, HA/DR, or production write-back.
- ADR: `docs/adr/0295-postgres-writeback-api-server-boundary.md`.
- Rollback: remove the factory alias and server route branch; no database or
  external provider state is mutated.

## D249 - Write-back transport is explicit, payload-digest-bound, and provider-neutral

- Date: 2026-08-03
- Status: accepted
- Decision: add a separate `WritebackNetworkRegistration` and injected/pinned
  HTTPS POST transport. It requires an enabled feature, an already dispatched
  approved intent, exact allowlisted HTTPS egress, a short-lived payload whose
  digest equals the intent, secret-reference resolution at call time, and a
  closed provider acknowledgement envelope. Retries reuse the same
  idempotency key and are bounded by the registration policy.
- Rationale: the existing write-back lifecycle had durable evidence and an
  injected provider seam but no concrete transport contract. This closes the
  safe adapter shape without weakening the default read-only manifest or
  performing unapproved network I/O.
- Boundary: synthetic transport and local pinned-request shape only; no vendor
  interoperability, customer credentials, hosted secret vault, compensation,
  posting, HA/DR, or production write-back claim.
- ADR: `docs/adr/0296-writeback-network-transport-is-explicit-and-digest-bound.md`.
- Rollback: remove the transport module and exports; intent repositories and
  proposal-only APIs remain unchanged.

## D250 - PostgreSQL source access is fixed named-query and read-only

- Date: 2026-08-04
- Status: accepted
- Decision: add a separate `database_source` manifest and
  `PostgresNamedQueryTransport` for the two versioned database profiles. The
  registration pins an exact credential-free PostgreSQL endpoint; the runtime
  DSN must match its host, port, and database path. Queries are fixed,
  parameterized, bounded by a statement timeout, and executed in an explicit
  `READ ONLY` transaction with transaction-local tenant context.
- Rationale: the prior database connector intentionally stopped at a
  transport-injected synthetic boundary. A concrete local PostgreSQL adapter
  gives the connector workstream an executable, least-privilege read gate
  without inventing ERP/bank provider interoperability or opening arbitrary
  SQL.
- Consequence: deployments must expose the two documented views and grant
  `SELECT` to the application role. Canonical Decimal output and cursor/replay
  evidence are available; provider schema compatibility, vault/TLS operations,
  write-back, throughput, HA/DR, and production readiness remain open.
- ADR: `docs/adr/0301-postgres-named-query-readonly-connector.md`.
- Rollback: remove the adapter, registration, tests, CI entry, and docs; the
  existing synthetic database connector remains unchanged.

## D251 - Quorum and fencing safety is a separate deterministic state machine

- Date: 2026-08-04
- Status: accepted
- Decision: add an orchestration-neutral HA/DR state machine requiring three
  voter failure domains plus a witness. Failover requires a monotonic detection
  tick, witness acknowledgement, and quorum; fencing is recorded before
  election; stale leaders cannot commit; rejoining nodes must catch up exactly
  and receive independent repromotion authorization.
- Rationale: the existing Docker drill is deliberately single-host and manual.
  Modeling the safety decisions separately advances split-brain and replay
  correctness without falsely converting container namespaces into host-level
  failure domains.
- Consequence: PostgreSQL, queue, object-store, and external fencing adapters
  can target a stable contract. The generated report is `simulation_only`; it
  does not establish network failover, wall-clock RPO/RTO, host loss, or a
  production SLO.
- ADR: `docs/adr/0302-ha-dr-quorum-fencing-safety-state-machine.md`.
- Rollback: remove the reliability module, verifier, schema, report, tests,
  CI invocation, and execution entries without changing the existing drill.
## D252 - Exercise the optional S3 boundary against digest-pinned MinIO

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add a separate CI job for a real boto3-backed S3-compatible
  object-store run. Start a digest-pinned MinIO process, create normal and
  object-lock buckets with synthetic credentials, run hierarchical isolation,
  immutable-create, checksum-tamper, retention-delete, and cleanup checks, and
  retain a digest-bound report as a CI artifact.
- **Reason**: Transport-injected tests cannot expose conditional-create,
  object-lock, or provider metadata behavior. A disposable open-source process
  supplies stronger provider evidence without changing the local-first default
  or using customer data.
- **Boundary**: One process on one CI host only. No replication, KMS,
  cross-site durability, provider interoperability, object-store HA/DR,
  malware scanning, authorized download, or production SLO claim follows.
- **ADR**: `docs/adr/0303-live-s3-compatible-object-storage-gate.md`.
- **Rollback**: remove the CI job, verifier, schema, tests, report upload, and
  execution records; the local filesystem default and S3 adapter remain.

## D253 - Share explicit policy-cache invalidation through a Redis generation

- Date: 2026-08-04
- Status: accepted
- **Decision**: When both the API policy cache and Redis server profile are
  explicitly enabled, include a Redis-backed monotonic generation in local
  allowed-decision cache keys and increment it on non-safe request
  invalidation. Redis stores only the generation; it never stores policy
  decisions or credentials.
- **Reason**: A process-local cache cannot invalidate sibling API workers. A
  generation is deterministic, inspectable, and avoids pub/sub subscriber
  state while preserving the local-first default.
- **Boundary**: Redis generation reads that fail bypass local caching. The
  contract is coarse global invalidation; Redis HA/failover, outage recovery,
  complete route/job/export/UI adoption, federation, and production IAM
  assurance remain unverified.
- **ADR**: `docs/adr/0304-redis-shared-policy-cache-generation.md`.
- **Rollback**: remove the version-store class, cache hook, tests, and
  execution records; process-local opt-in caching remains available.

## D281 - Publish a domain-diverse grouped-matching 10K profile

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add `grouped-matching/10k-domain-diverse-v1` with 2,500 bounded
  partitions and 10,000 synthetic records cycling one-to-many, many-to-one,
  true many-to-many, fee-aware portfolio netting, FX-aware many-to-many, and
  partial-settlement portfolio cases. Require adapter/application digest
  equality, reversed-input permutation equality, exact mode counts, and
  explicit expected ambiguity for equal partial candidates.
- **Reason**: Existing 10K/100K/1M profiles are deliberately homogeneous
  exact USD many-to-many workloads. The new profile adds domain diversity
  without widening algorithm ceilings or converting a workstation observation
  into a capacity claim.
- **Boundary**: One host/process synthetic algorithm evidence only. Sequence,
  carry-forward, reversal, PostgreSQL parity, soak, distributed capacity,
  provider I/O, posting, and production sizing remain separate gates.
- **ADR**: `docs/adr/0305-grouped-matching-domain-diverse-scale.md`.
- **Rollback**: remove the benchmark module, artifact/schema, tests, package
  entries, and execution records; existing grouped strategies are unchanged.

## D282 - Publish a PostgreSQL durable-job 10K-effect tier

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add `postgres-durable-job-load/10k-effects-v1` with 16
  independent worker connections, 2,500 synthetic jobs, four partitions per
  job, and four forced-RLS tenant lanes. Keep the 256-effect profile as the
  compatibility baseline and reuse the existing lease, checkpoint,
  idempotency, and partition-effect uniqueness contracts.
- **Reason**: SQLite already has published 10K/100K tiers, while PostgreSQL
  concurrency evidence stopped at 256 effects. A real 10K PostgreSQL service
  run closes a material backend-parity gap without turning one host into a
  capacity or SLO claim.
- **Boundary**: One PostgreSQL host and synthetic data only. Soak,
  backpressure coupling, queue HA, automatic failover, host loss, cross-host
  fairness, RPO/RTO, and production sizing remain unverified.
- **ADR**: `docs/adr/0306-postgres-durable-job-10k-scale.md`.
- **Rollback**: remove the tier factory, test, artifact/schema, benchmark
  note, manifest entries, and execution records; the 256-effect baseline and
  durable-job runtime remain unchanged.

## D283 - Order PostgreSQL durable-job aggregate and lease locks consistently

- Date: 2026-08-04
- Status: accepted
- **Decision**: Owned durable-job transition transactions must lock the
  `durable_jobs` row with `FOR UPDATE` before checking and locking the matching
  `durable_job_leases` row. This matches the existing `claim_next` order.
- **Reason**: Hosted server-boundary rerun evidence showed an intermittent
  deadlock cycle between the aggregate and lease rows during two-worker
  contention. A single lock order removes the cycle without weakening the
  optimistic version fence, lease ownership check, RLS, or append-only effect
  evidence.
- **Boundary**: This is a transaction-order availability fix only. It does not
  establish PostgreSQL soak, queue HA, automatic failover, distributed
  fairness, or production SLOs. Local evidence is 10/10 repeated contention
  passes plus a successful 10K-effect profile; hosted verification remains a
  required gate for closure.
- **ADR**: `docs/adr/0307-postgres-durable-job-lock-order.md`.
- **Rollback**: revert the `_lock_job` helper and its two call sites; no schema
  or public API migration is required.

## D284 - Promote the PostgreSQL HA/DR drill to a hosted runtime gate

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add a separate `postgres-ha-dr` CI job that runs the existing
  Docker synchronous-standby drill three times with locked dependencies,
  execution-date metadata, labelled-resource cleanup checks, and an uploaded
  schema-validated report.
- **Reason**: The repository had real local backup/failover/failback behavior
  but the default CI only ran the orchestration-neutral quorum simulation. A
  dedicated hosted job makes the runtime evidence repeatable and reviewable
  without converting one host into an independent-HA claim.
- **Boundary**: The gate remains single-host, manual-controller, synthetic
  evidence. Independent failure domains, quorum/witness, automatic promotion,
  site-loss recovery, managed keys, and production SLOs remain unverified.
- **ADR**: `docs/adr/0308-postgres-ha-dr-runtime-gate.md`.
- **Rollback**: remove the job, report artifact, contract test, ADR, and
  manifest entry; the existing drill scripts remain available locally.

## D285 - Record hosted PostgreSQL HA/DR gate evidence

- Date: 2026-08-04
- Status: accepted
- **Decision**: Mark E-358 as a complete bounded slice after hosted CI run
  `30884962171` and `postgres-ha-dr` job `91914021265` passed all three
  repeated Docker drills and uploaded the report artifact.
- **Boundary**: The evidence is still two containers on one host with a
  manual controller and synthetic data/key. It does not satisfy the
  independent-failure-domain exit criteria in P4-REL-001.
- **ADR**: `docs/adr/0308-postgres-ha-dr-runtime-gate.md`.
- **Rollback**: revert the hosted job and documentation evidence; retain the
  local drill only if the runtime gate is intentionally withdrawn.

## D286 - Promote the PostgreSQL durable-job 10K tier to a hosted gate

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add the existing 10K-effect PostgreSQL profile to the hosted
  `server-boundaries` command rather than creating a parallel worker path.
- **Reason**: Local 10K evidence covered the real repository but did not run on
  the hosted PostgreSQL service. The explicit test invocation makes the
  declared concurrency/effect invariants reviewable without claiming capacity.
- **Boundary**: Single-node synthetic correctness/concurrency only. Soak,
  backpressure coupling, queue HA, host loss, cross-host fairness, RPO/RTO,
  and production sizing remain open.
- **Result**: Hosted CI run `30887647946` passed; `server-boundaries` job
  `91922298719` executed the explicit 10K test successfully, and the full
  workflow remained green.
- **ADR**: `docs/adr/0309-postgres-durable-job-10k-hosted-gate.md`.
- **Rollback**: remove the explicit test invocation, contract assertion, ADR,
  and manifest entry; retain the local and 256-effect hosted profiles.

## D287 - Bound the hosted PostgreSQL grouped-matching scale gate

- Date: 2026-08-04
- Status: accepted
- **Decision**: Reuse the public grouped strategy and existing PostgreSQL
  checkpoint worker for a bounded 500-partition hosted test instead of
  creating a parallel matching implementation. The initial 2,000-partition
  candidate failed in hosted `server-boundaries` run `30890782410` / job
  `91932080667` after 2m34s and remains an unverified boundary.
- **Reason**: Local domain-diverse matching evidence and small PostgreSQL
  runtime gates did not jointly exercise the five grouped modes over a larger
  concurrent partition set. The bounded gate makes result cardinality,
  duplicate prevention, terminal state, and per-mode distribution reviewable
  without exceeding the worker's drain window.
- **Boundary**: Hosted single-node synthetic correctness/concurrency only.
  Throughput, soak, backpressure, cross-host fairness, provider
  interoperability, posting, write-back, HA/DR, and production sizing remain
  open.
- **Result**: Hosted CI run `30894602923` passed; `server-boundaries` job
  `91944412213` verified 500 completed partitions, exact result-row
  cardinality, zero duplicate result identities, zero failed/active runs, and
  50 completed runs per grouped mode.
- The run also drove a stale active-page race to a concrete fix: terminal
  reconciliation observations now raise the existing busy signal so a
  competing worker skips them instead of converting a completed run into a
  worker failure; a focused regression preserves this behavior.
- **ADR**: `docs/adr/0310-postgres-grouped-matching-2000-partition-hosted-gate.md`.
- **Rollback**: remove the explicit test invocation, contract assertion, ADR,
  and manifest entry; retain the existing 64-partition and local domain-
  diverse profiles.

## D288 - Bind replay-verified close artifacts into one evidence bundle

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add `consolidation-close-bundle-v1` as a pure, additive
  read-time manifest over the artifacts already replay-verified by the SQLite
  and PostgreSQL close adapters. Expose it from detailed run reads without a
  migration or new mutation path.
- **Reason**: Separate worksheet, translation, statement, journal, and effect
  responses were individually integrity-checked but not bound to one consumer-
  visible identity. A canonical bundle prevents accidental cross-run evidence
  composition while retaining existing lifecycle compatibility.
- **Boundary**: Local control-journal and management-only evidence. Statutory
  reporting, external posting, provider acknowledgement, write-back, HA/DR,
  and production assurance remain open.
- **Result**: Focused SQLite bundle/lifecycle tests pass 15/15; PostgreSQL
  close/bundle tests pass 7/7 with one no-DSN skip, and the live local
  PostgreSQL close contract passes 8/8; Ruff and Mypy pass for the changed
  modules.
- **ADR**: `docs/adr/0311-consolidation-close-evidence-bundle.md`.
- **Rollback**: remove the bundle module, adapter projection, focused tests,
  manifest entry, and ADR; persisted rows remain readable because the bundle
  is derived at read time.

## D289 - Make hosted queue-policy and lane-fairness tests explicit

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add a separate `server-boundaries` invocation for the existing
  PostgreSQL durable-job queue-cap/retry/isolation contract and process-scoped
  round-robin lane-fairness contract. Keep the 10K load command separate.
- **Reason**: The implementation already had these protections, but the
  current hosted command selected only the 10K scale test. Explicit selection
  prevents future workflow drift from silently dropping queue and fairness
  evidence.
- **Boundary**: One synthetic PostgreSQL service and one scheduler loop.
  Throughput, distributed fairness, soak, queue HA, failover, capacity, and
  production SLOs remain open.
- **Result**: Hosted CI run `30898382499` / `server-boundaries` job
  `91956632669` passed the explicit queue-policy and lane-fairness tests, with
  the remaining required matrix jobs also green.
- **ADR**: `docs/adr/0312-hosted-postgres-queue-policy-and-fairness-gate.md`.
- **Rollback**: remove the extra workflow command, ADR, manifest entry, and
  execution evidence; retain the existing 10K hosted gate.

## D290 - Bind server write-back routes to central hierarchy policy

- Date: 2026-08-04
- Status: accepted
- **Decision**: Keep the existing named-permission and header-equality checks,
  then re-evaluate proposal, approval, and acknowledgement permissions against
  the authenticated PostgreSQL tenant/workspace/entity grant snapshot before
  repository access. Local SQLite routes remain unchanged.
- **Reason**: A coarse permission dependency proves capability but not the
  selected resource hierarchy. The write-back surface is a sensitive,
  human-governed boundary and must fail closed if the workspace grant is
  missing or the required assurance is stale.
- **Result**: Focused API execution-scope and write-back tests pass 8/8;
  Ruff and Mypy pass. This is one centrally scope-bound route family, not
  universal route/job/export/UI migration or live provider evidence.
- **ADR**: `docs/adr/0313-server-writeback-policy-is-scope-bound.md`.
- **Rollback**: remove the helper and the three route calls, tests, ADR, and
  ledger entries; retain the prior coarse permission/header checks.

## D291 - Bind the PostgreSQL consolidation-close API to execution scope

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add a dedicated server adapter and route branch for the
  consolidation-close API. Resolve tenant/workspace/organization/entity from
  the authenticated grant snapshot, pass it through the PostgreSQL RLS
  boundary, query by workspace, and reject any returned row outside that
  workspace. Include all eight routes in the authorization inventory.
- **Reason**: The PostgreSQL repository already provided replay-verified close
  evidence, but the API remained SQLite-only and its routes were invisible to
  the authorization drift gate. Tenant-only RLS does not replace explicit
  hierarchy checks.
- **Boundary**: This is control-journal API parity and isolation evidence. It
  does not implement statutory consolidation, external posting, live provider
  integration, write-back, HA/DR, or universal enterprise IAM.
- **Result**: Focused API/server-scope/inventory tests pass 16/16; Ruff and
  Mypy pass. Local SQLite compatibility remains unchanged. Hosted
  no-regression verification is green in CI `30904707354`, Security
  `30904707336`, Docker `30904707413`, and CodeQL `30904707431`; no live
  authenticated route fixture was added.
- **ADR**: `docs/adr/0314-postgres-consolidation-close-api-is-scope-bound.md`.
- **Rollback**: remove the adapter, route branches, inventory inclusion, tests,
  ADR, manifest entry, and ledger additions; no schema rollback is required.

## D292 - Expose effective-dated consolidation ownership through a scoped API

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add strict authenticated save/effective-resolution routes over
  the existing backend-neutral ownership service. Bind the preparer to the
  authenticated actor, preserve the declared independent approver, and use
  SQLite locally or PostgreSQL under the authenticated hierarchy/RLS boundary
  in server mode.
- **Reason**: Ownership persistence and deterministic effective-date replay
  existed in both backends but were not consumable through the API. A route
  contract closes that exposure gap without duplicating financial logic.
- **Boundary**: The API does not prove a separate approver session, statutory
  consolidation treatment, live ERP/bank integration, write-back, HA/DR, or
  production readiness.
- **Result**: Focused API and server-scope tests pass 12/12; authorization
  inventory is 219 routes with digest
  `46a0eac80865dbf7219a2b8230c8dc576d41cd503bdae224c9e01e442828e8f8`; Ruff
  and Mypy pass. The configured local PostgreSQL 16 ownership repository gate
  passes 5/5. Hosted no-regression CI `30907636302`, Security `30907636780`,
  Docker `30907634915`, and CodeQL `30907635562` are green for commit
  `b8e30bab`.
- **ADR**: `docs/adr/0315-consolidation-ownership-api-is-scope-bound.md`.
- **Rollback**: remove the route/server adapter, inventory entry, tests,
  manifest entry, and ADR; persisted ownership rows and migrations remain.

## D293 - Promote consolidation ownership API to a live server-identity gate

- Date: 2026-08-04
- Status: accepted
- **Decision**: Extend the existing live PostgreSQL server-identity fixture to
  install the ownership schema, grant the non-privileged role only the needed
  table access, and exercise authenticated ownership create/resolve plus
  sibling-workspace denial through the real FastAPI stack.
- **Reason**: Mocked scope tests proved route control flow, but did not prove
  middleware identity, request hierarchy, RLS, and ownership persistence as one
  runtime path.
- **Boundary**: Synthetic single-node PostgreSQL and one API process; no claim
  of independent approver authentication, statutory consolidation, providers,
  write-back, HA/DR, or production readiness.
- **Result**: The combined local API/identity/ownership gate passes 25/25;
  Ruff and Mypy pass. Hosted CI `30909580514`, Security `30909580496`, Docker
  `30909580586`, and CodeQL `30909580604` are green for commit `0f9a7eb`.
- **ADR**: `docs/adr/0316-live-consolidation-ownership-api-gate.md`.
- **Rollback**: remove the fixture schema/grant/assertions and this ADR; no
  production schema or migration rollback is required.

## D294 - Promote consolidation-close API to a live server gate

- Date: 2026-08-04
- Status: accepted
- **Decision**: Install the existing PostgreSQL consolidation-close schema in
  the live server-identity fixture, grant only its RLS tables/certification
  storage, and exercise authorized period listing plus sibling-workspace
  refusal through the real API.
- **Reason**: Mocked route scope tests did not prove middleware identity,
  PostgreSQL RLS, and the consolidation-close adapter together.
- **Boundary**: Empty synthetic period set on one PostgreSQL node; no claim of
  statutory or posted close correctness, HA/DR, providers, write-back, or
  production readiness.
- **Result**: The combined local API/identity/ownership/close gate passes 29/29;
  Ruff and Mypy pass. Hosted CI `30910990925`, Security `30910991025`, Docker
  `30910990850`, and CodeQL `30910990719` are green for commit `b9fd51d`.
- **ADR**: `docs/adr/0317-live-consolidation-close-api-gate.md`.
- **Rollback**: remove the fixture schema/grants/assertions and ADR; no
  application migration rollback is required.

## D295 - Verify consolidation ownership approver identity at save time

- Date: 2026-08-04
- Status: accepted
- **Decision**: Resolve `approved_by` through the local user repository or the
  tenant-scoped PostgreSQL identity repository during the ownership save
  operation. Require an enabled, distinct identity with
  `finance_core.manage` or `finance_core.validate`; reject unknown, disabled,
  self, or unauthorized identities before persistence.
- **Reason**: A declared approver string is not maker-checker evidence. The
  check belongs inside the same backend transaction and authenticated scope as
  the ownership write, while keeping SQLite/local-first compatibility.
- **Boundary**: This proves identity existence and permission lookup only. It
  does not prove a separate approver session, MFA ceremony, statutory
  consolidation, live providers, write-back, HA/DR, or production IAM.
- **Result**: Local ownership API tests pass 3/3 and the combined live
  API/identity/ownership/close gate passes 29/29; Ruff, Mypy, diff-check, and
  package build pass. Hosted head `6eb71f2a` is green in CI `30913043618`
  (including `server-boundaries`, `postgres-ha-dr`, and `docker-parity`),
  Security `30913043237`, Docker `30913043606`, and CodeQL `30913043202`.
- **ADR**: `docs/adr/0318-consolidation-ownership-approver-identity.md`.
- **Rollback**: remove the identity lookup methods, route checks, tests, ADR,
  and manifest entry; no schema rollback is required.

## D296 - Expose a scoped consolidation-close period write boundary

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add strict authenticated `POST /api/v1/consolidation-close/periods`
  over the existing application/repository port. Local mode uses SQLite;
  server mode uses the authenticated PostgreSQL tenant/workspace hierarchy and
  binds the actor to the bearer identity. Identical period identities replay;
  sibling workspaces fail before repository access.
- **Reason**: The close API exposed evidence and certification but had no
  authenticated period-entry boundary. A period-only write slice advances the
  lifecycle without inventing a second calculation or posting path.
- **Boundary**: Period creation only. Run preparation, approval/posting,
  reversal, locks/reopens, statutory statements, provider/write-back, HA/DR,
  and production assurance remain unverified.
- **Result**: The local close API/inventory tests pass 9/9; the configured live
  PostgreSQL API/identity/ownership/close gate passes 30/30; authorization
  inventory is 220 routes with digest
  `3adace1833893004e67851b0be16791f8cff078bb0a55babe49a7a5c216f05c0`; Ruff,
  Mypy, and diff-check pass. Hosted head `8c2589ef` is green in CI
  `30915384871` (including `server-boundaries`, `postgres-ha-dr`, and
  `docker-parity`), Security `30915375062`, Docker `30915374854`, and CodeQL
  `30915379664`.
- **ADR**: `docs/adr/0319-consolidation-close-period-api-write-boundary.md`.
- **Rollback**: remove the route, request model, tests, inventory update, ADR,
  and manifest entry; no database migration rollback is required.

## D297 - Expose the governed consolidation-close lifecycle through one API boundary

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add strict authenticated routes for replay-verified run
  preparation, independent approval, control-journal posting, reversal
  request/approval, and optimistic period lock/reopen. Route operations reuse
  the backend-neutral SQLite/PostgreSQL application ports and verify returned
  workspace scope in server mode.
- **Reason**: Period creation alone left the existing tested close lifecycle
  unreachable through the API. Reusing the port closes the gap without a new
  posting engine or raw journal ingress.
- **Boundary**: Synthetic control-journal evidence only. PostgreSQL currently
  represents reopen as `Open` while SQLite returns `Reopened`; statutory close,
  legal books, live providers, HA/DR, and production assurance remain open.
- **Result**: Local full lifecycle API tests pass 6/6; the live
  API/identity/close/inventory gate passes 14/14; inventory is 227 routes with
  digest `9e4e4f568df98a482a0eaf34d9c9c359330caf22df43b89e2cb14f771b183fc5`;
  Ruff, Mypy, and diff-check pass. Exact code head `672b2282` is green on CI
  `30919182900` (server-boundaries `92025004869`, PostgreSQL/HA-DR
  `92025004440`, Docker parity `92026761956`), Security `30919182689`, Docker
  `30919183050`, and CodeQL `30919183059`.
- **ADR**: `docs/adr/0320-consolidation-close-api-full-lifecycle-boundary.md`.
- **Rollback**: remove the routes, request models, tests, inventory update,
  ADR, and manifest entry; no schema rollback is required.

## D298 - Add an opt-in governed server write-back hand-off

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add a dedicated dispatch permission/migration and a
  server-profile-only route that persists `approved -> dispatched` before an
  explicitly registered provider-neutral network executor. Persist the
  verified acknowledgement only after response-digest and idempotency-key
  validation; local mode remains network-disabled.
- **Reason**: The existing transport was safely implemented but unreachable
  from the API, while the connector router was outside the startup
  authorization inventory. The hand-off closes both gaps without claiming a
  live vendor or enabling default egress.
- **Boundary**: Synthetic injected transport and one API process only. Live
  ERP/bank interoperability, customer vault, accounting posting,
  compensation delivery, distributed quotas, HA/DR, and production write-back
  remain open.
- **Result**: Connector/API and authorization-inventory tests pass 7/7; the
  live PostgreSQL server-identity fixture passes 4/4 with real RLS proposal,
  approval, and synthetic executor acknowledgement; the inventory is 231 routes with digest
  `5ab85f381b3ef49f060b27f539b342af01a91d739788da5601db383a5b15ebdd`; Ruff
  and Mypy pass. Exact code head `392b7907` is green on CI `30926588702`
  (server-boundaries `92050378455`, PostgreSQL/HA-DR `92050378311`, Docker
  parity `92052163349`), Security `30926583902`, Docker `30926589234`, and
  CodeQL `30926584585`.
- **ADR**: `docs/adr/0321-governed-server-writeback-dispatch-boundary.md`.
- **Rollback**: remove the route, permission migration, tests, inventory
  inclusion, ADR, and manifest entry.

## D299 - Re-evaluate central hierarchy policy before close mutations

- Date: 2026-08-04
- Status: accepted
- **Decision**: Before a PostgreSQL server-profile consolidation-close or
  consolidation-ownership mutation reaches its repository, re-evaluate the
  required `finance_core.manage` or `finance_core.validate` permission with
  the authenticated tenant and workspace. Keep the local SQLite compatibility
  path and read permission contracts unchanged.
- **Reason**: A role-level permission and a matching workspace header are not
  sufficient evidence that the selected business mutation is authorized. The
  central policy engine already evaluates hierarchy grants and step-up state;
  binding it immediately before persistence closes this route-level widening
  gap without changing schemas or introducing a second policy engine.
- **Result**: Focused close/ownership/execution-scope tests pass 15/15, the
  final full pytest suite, Ruff, Mypy, build, and diff-check pass. Exact code
  head `8521b15d` is green on CI `30929398907`, Security `30929399364`, Docker
  `30929398698`, and CodeQL `30929399241`.
- **Boundary**: Close and ownership mutation families only; federation,
  complete route/job/export/UI adoption, distributed invalidation, live
  provider operation, independent HA/DR, and production IAM assurance remain
  open.
- **ADR**: `docs/adr/0322-server-scoped-close-and-ownership-mutations.md`.
- **Rollback**: remove the helper calls, focused assertions, ADR, and
  manifest entry. No data or schema rollback is required.

## D300 - Bind close-management mutations to server execution scope

- Date: 2026-08-04
- Status: accepted
- **Decision**: Before PostgreSQL server-profile close-management period
  initialization, task status, lock, or reopen reaches the repository,
  re-evaluate `close.manage` with the authenticated tenant/workspace. Keep
  read routes and local SQLite behavior unchanged.
- **Reason**: Close-control RLS and a role-level permission are necessary but
  not sufficient proof of mutation authority for the selected hierarchy. The
  central policy helper supplies the missing route-level binding without a
  new schema or policy engine.
- **Result**: Focused identity/scope tests pass 7/7; the final full pytest,
  Ruff, Mypy, and diff-check pass. Exact code head `6d2a926a` is green on CI
  `30931676837`, Security `30931676624`, Docker `30931675916`, and CodeQL
  `30931676434`.
- **Boundary**: Close-management routes only; federation, complete
  route/job/export/UI adoption, distributed invalidation, live provider
  operation, independent HA/DR, and production IAM assurance remain open.
- **ADR**: `docs/adr/0323-server-scoped-close-management-mutations.md`.
- **Rollback**: remove the four helper calls, focused assertions, ADR, and
  manifest entry. No data or schema rollback is required.

## D301 - Bind finance-ledger mutations to server execution scope

- Date: 2026-08-04
- Status: accepted
- **Decision**: Before PostgreSQL server-profile account upsert or atomic
  ledger-entry creation reaches the ledger repository, re-evaluate
  `finance_core.manage` with the authenticated tenant/workspace. Keep reads,
  unsupported capability boundaries, and SQLite unchanged.
- **Reason**: These operations mutate financial control data; role membership
  and RLS alone do not provide a route-level proof of the selected hierarchy.
  Reusing the central policy helper adds that proof without changing the
  ledger schema or inventing statutory posting semantics.
- **Result**: Focused identity/scope tests pass 7/7; the final full pytest,
  Ruff, Mypy, and diff-check pass. Exact code head `35c09f63` is green on CI
  `30932859161`, Security `30932857268`, Docker `30932856740`, and CodeQL
  `30932859207`.
- **Boundary**: Two server finance-ledger mutation endpoints only; full
  Finance Core parity, statutory posting, federation, complete route/job/
  export/UI adoption, live providers, independent HA/DR, and production IAM
  assurance remain open.
- **ADR**: `docs/adr/0324-server-scoped-finance-ledger-mutations.md`.
- **Rollback**: remove the two helper calls, focused assertions, ADR, and
  manifest entry. No data or schema rollback is required.

## D302 - Bind master-data mutations to server execution scope

- Date: 2026-08-04
- Status: accepted
- **Decision**: Before PostgreSQL server-profile currency, organization,
  legal-entity, branch, fiscal-period, or period-status mutation reaches the
  repository, re-evaluate `master_data.manage` with the authenticated
  tenant/workspace. Keep explicit server workspace limits and local SQLite
  compatibility unchanged.
- **Reason**: Master data controls the hierarchy used by posting and close;
  tenant RLS and role membership alone do not prove selected-scope authority.
  The central policy helper closes that route-level gap without schema change.
- **Result**: Focused identity/scope and master-data route tests pass; full
  pytest, Ruff, Mypy, build, and diff-check pass. Exact head `d8bc4dd8` is
  green on hosted CI `30937323538` (server-boundaries `92086636635`,
  postgres-ha-dr `92086636683`, Docker parity `92088189807`), Security
  `30937323640`, Docker `30937323622`, and CodeQL `30937323585`.
- **Boundary**: Master-data mutation family only; full parity, federation,
  complete route/job/export/UI adoption, distributed invalidation, live
  providers, independent HA/DR, and production IAM assurance remain open.
- **ADR**: `docs/adr/0325-server-scoped-master-data-mutations.md`.
- **Rollback**: remove helper calls, focused assertions, ADR, and manifest
  entry. No data or schema rollback is required.

## D305 - Separate governed write-back compensation transport

- Date: 2026-08-04
- Status: accepted
- **Decision**: Add an explicit opt-in compensation operation to the HTTPS
  write-back executor. A connector registration must allow the original
  operation for compensation; the executor derives a separate operation
  marker and `:compensation` idempotency key, validates a caller-supplied
  payload digest, and requires a matching acknowledgement before the intent
  becomes `compensated`.
- **Reason**: Replaying the original write-back payload is not a safe
  compensation strategy. A separate allowlist, payload, operation, and
  idempotency domain makes reversal intent visible and fail closed.
- **Result**: Focused connector tests pass 24/24, including missing allowlist,
  tampering, retry/failure injection, separate headers, rejected-provider
  acknowledgement refusal, and acknowledgement binding. Ruff and Mypy pass
  for the changed connector surfaces.
- **Boundary**: Provider-neutral transport contract only; live ERP/bank
  compensation semantics, provider sandbox, vault, signed package, production
  egress, and HA/DR remain unverified.
- **ADR**: `docs/adr/0328-governed-writeback-compensation-transport.md`.
- **Rollback**: remove the allowlist field, executor/conformance method,
  tests, ADR, and manifest entry. No migration is required.

## D303 - Preserve OR permission compatibility for reconciliation scope

- Date: 2026-08-04
- Status: accepted
- **Decision**: Reconciliation submit, cancel, and requeue keep their existing
  `reconciliation.manage` OR `match.run` contract while using a reusable
  server-scoped any-permission evaluator before PostgreSQL repository access.
- **Reason**: Requiring only one alternative would silently narrow existing
  roles; duplicating policy logic would create authorization drift.
- **Result**: Focused reconciliation/scope tests pass 9/9; full local gates
  pass. Exact head `d8bc4dd8` is green on hosted CI `30937323538`, Security
  `30937323640`, Docker `30937323622`, and CodeQL `30937323585`.
- **Boundary**: Reconciliation route family only; distributed worker
  authorization, federation, universal route/job/export/UI coverage, live
  providers, independent HA/DR, and production IAM assurance remain open.
- **ADR**: `docs/adr/0326-server-scoped-reconciliation-run-mutations.md`.
- **Rollback**: remove the helper, route calls, tests, ADR, and manifest entry.

## D304 - Bind evidence mutations to server execution scope

- Date: 2026-08-04
- Status: accepted
- **Decision**: Evidence registration, linking, requirements, sensitive
  drill-down, and checksum verification re-evaluate `evidence.manage` or
  `evidence.verify` against authenticated tenant/workspace before the
  PostgreSQL evidence repository. Local SQLite and ordinary reads remain
  unchanged.
- **Reason**: Evidence underpins close and reconciliation claims; raw role
  membership is not proof of selected hierarchy authority. Central scope
  policy also removes the former raw permission-set special case.
- **Result**: Focused evidence/scope/inventory tests pass 12/12; full pytest,
  Ruff, Mypy, build, and diff-check pass. Exact head `3778811` is green on
  hosted CI `30940202330` (server-boundaries `92096349955`, postgres-ha-dr
  `92096349776`, Docker parity `92097921442`), Security `30940202609`, Docker
  `30940202853`, and CodeQL `30940202230`.
- **Boundary**: Evidence mutation routes only; workspace-level persistence,
  universal route/job/export/UI adoption, federation, live providers,
  independent HA/DR, and production IAM assurance remain open.
- **ADR**: `docs/adr/0327-server-scoped-evidence-mutations.md`.
- **Rollback**: remove helper calls, focused assertions, ADR, and manifest
  entry. No data or schema rollback is required.
### D-291: Activate the PostgreSQL Finance Core API adapter

- **Date**: 2026-08-05

- **Decision**: use a dedicated request-scoped `server_finance_core` executor and
  the existing forced-RLS Finance Core repository for rich server operations;
  retain the old posted-ledger adapter for minimal legacy payloads.
- **Rationale**: this adds real chart/account/dimension/journal and draft lifecycle
  semantics without silently changing or downgrading existing clients.
- **Verification**: ADR 0335, `tests/test_api_server_finance_core.py`, and the optional
  live-DSN route lifecycle gate.
- **Boundary**: no statutory posting, live vendor connector, write-back, scale,
  HA/DR, or production-readiness claim.

### D-292: Bind intercompany proposals to prepared PostgreSQL close runs

- **Date**: 2026-08-05

- **Decision**: add an immutable `consolidation_close_intercompany_links`
  table and a server-only attachment route. The PostgreSQL close adapter
  replays the linked intercompany artifact, checks exact proposal fields,
  workspace/period/currency, and stores a digest-bound matched-ID set. A
  prepared run containing `intercompany_transaction` eliminations cannot be
  approved until all such eliminations are covered exactly once.
- **Rationale**: a persisted proposal and a persisted control journal need an
  explicit provenance edge before maker-checker approval; matching by ID alone
  would allow tampered or cross-period evidence.
- **Verification**: ADR 0336, migration/schema contracts, exact proposal
  replay tests, API scope test, close-bundle round-trip tests, complete local
  gates, and hosted head `01f4de85` under CI `30968619652` (server-boundaries
  `92187914873`, postgres-ha-dr `92187914777`, Docker parity `92188812253`),
  Security `30968619726`, Docker `30968619657`, and CodeQL `30968619666`.
- **Boundary**: bounded evidence/control-journal integration only; no
  statutory/legal-book posting, live ERP/bank connector, write-back,
  throughput, HA/DR, compliance, certification, or production-readiness claim.
### D-310: Bind consolidation PPA routes to tenant policy

- **Date**: 2026-08-05
- **Decision**: Re-evaluate `finance_core.manage` before PPA preparation and
  `finance_core.read` OR `finance_core.manage` before PPA reads, using the
  validated request tenant and no workspace scope.
- **Rationale**: The current PostgreSQL PPA artifact is tenant-scoped. Central
  policy must be bound to the request tenant without inventing a workspace that
  would distort authorization semantics.
- **Verification**: ADR 0347, focused PPA API tests (3 passed), and the full
  server-identity API file (3 passed, 1 declared skip).
- **Boundary**: This is route-family IAM evidence only; statutory acquisition
  accounting, providers, write-back, independent HA/DR, distributed IAM and
  complete worker/export/UI adoption remain open.
- **Rollback**: Remove the helper calls, focused test, ADR and manifest entry;
  no schema or data rollback is required.

### D-311: Bind tenant-wide audit and security views to central policy

- **Date**: 2026-08-05
- **Decision**: Re-evaluate `audit.read`, `audit.verify`, and
  `security.center.read` against the validated request tenant before their
  PostgreSQL repositories; use `workspace_id=None` for these tenant-wide
  projections.
- **Rationale**: A raw permission snapshot is not sufficient authority for a
  selected tenant. The views do not carry a workspace key, so a synthetic one
  would be misleading and could deny valid tenant operators.
- **Verification**: ADR 0348; audit/security-center focused tests pass 4/4,
  with one declared PostgreSQL skip; Ruff and Mypy pass.
- **Boundary**: This is route IAM coverage only; complete worker/export/UI
  adoption, federation, distributed invalidation, independent HA/DR, and
  production IAM assurance remain open.
- **Rollback**: Remove the helper calls, focused assertions, ADR and manifest
  entry; no migration or data rollback is required.

### D-312: Record the post-E-402 local gate as non-release evidence

- **Date**: 2026-08-05
- **Decision**: Record the complete local pytest/static/security/package gate as
  E-403 while keeping hosted matrices, external providers, independent HA/DR,
  distributed IAM and production approval separate.
- **Rationale**: The gate proves repository compatibility after the IAM route
  additions, but the remaining objective requires evidence outside one local
  workstation and one PostgreSQL profile.
- **Verification**: Pytest, Ruff, Mypy, Bandit, pip-audit, build and
  `git diff --check` all exit successfully; Mypy reports no issues in 447 files.
- **Rollback**: Replace E-403 with a later superseding run; no runtime or
  migration rollback is required.

### D-313: Bind server metrics reads to tenant policy

- **Date**: 2026-08-05
- **Decision**: Re-evaluate `metrics.read` against the validated request tenant
  before PostgreSQL dashboard and lineage reads, with `workspace_id=None`.
- **Rationale**: Metrics are tenant-wide projections; central policy must bind
  the selected tenant without fabricating a business workspace.
- **Verification**: ADR 0349 and `tests/test_api_metrics.py` pass 1/1 with
  both route calls captured.
- **Boundary**: Route IAM control only; no SLO, compliance, federation,
  distributed invalidation, independent HA/DR or production claim.
- **Rollback**: Remove the helper, test, ADR and manifest entry; no schema
  rollback is required.

### D-314: Retry a missing native PostgreSQL dump once

- **Date**: 2026-08-05
- **Decision**: Require a non-empty dump after a successful `pg_dump`; retry
  once with the equivalent equals-form file argument and fail closed after a
  second absence.
- **Rationale**: This addresses wrapper argument parsing without hiding a
  non-zero tool failure or introducing unbounded retries or external I/O.
- **Verification**: ADR 0350 and the focused backup suite pass 11/11 with one
  declared native-tool skip.
- **Boundary**: Wrapper resilience only; no hosted CI, HA/DR, restore RPO/RTO,
  or production backup claim.
- **Rollback**: Remove retry code, tests, ADR, manifest and execution records;
  no schema/data rollback is needed.

### D-315: Record the final post-backup local gate as bounded evidence

- **Date**: 2026-08-05
- **Decision**: Record the complete local suite and static/security/package
  gates as E-406 while withholding any hosted, external-provider, statutory,
  independent-HA/DR, distributed-IAM or production-release claim.
- **Rationale**: The current branch is clean and compatible locally, but the
  remaining workstreams require evidence that cannot be produced by one local
  workstation and synthetic services.
- **Verification**: Pytest exits 0 in 356.6s; Ruff, Mypy, Bandit, pip-audit,
  build and diff-check all exit successfully.
- **Rollback**: Supersede E-406 with a later gate record; no runtime or
  migration rollback is required.

### D-316: Add a deterministic non-posting acquisition deferred-tax bridge

- **Date**: 2026-08-05
- **Decision**: Add `acquisition-deferred-tax-bridge-v1` for exact temporary
  differences, signed by asset/liability kind and rounded through the installed
  currency policy. Require source/policy lineage and independent maker-checker
  actors; expose a closed CLI/JSON Schema contract and always return
  `posted: false`.
- **Rationale**: This advances the acquisition close workstream with a real
  reviewable calculation while avoiding an unverified claim of statutory tax
  accounting, tax-law recognition, valuation allowances, or journal posting.
- **Verification**: Five focused tests pass, including schema/CLI,
  permutation-stable digest, arithmetic/totals, maker-checker/rate rejection,
  and tamper detection. Ruff, Mypy, and diff-check pass for changed files.
- **Boundary**: Live tax rates, tax filing, statutory/legal-book treatment,
  posting, independent HA/DR, and production close assurance remain open.
- **Rollback**: Remove the module, CLI, schema, tests, ADR, manifest and
  execution records; no migration or data rollback is required.

### D-317: Record the full local gate after the deferred-tax slice

- **Date**: 2026-08-05
- **Decision**: Record E-408 as local compatibility evidence and keep all
  hosted, external-provider, statutory, independent-HA/DR, distributed-IAM,
  scale, and production-release claims separate.
- **Verification**: Full pytest exits 0 in 325.9s; Ruff, Mypy (448 files),
  package build, and diff-check pass. Only declared skips and existing
  deprecation/legacy-input warnings remain.
- **Boundary**: A green local suite does not close the global objective or
  authorize GitHub publication.
- **Rollback**: Supersede E-408 with a later gate record; no runtime or
  migration rollback is required.

### D-318: Keep witness acknowledgement separate from voter quorum

- **Date**: 2026-08-05
- **Decision**: Require a healthy-voter count at least equal to configured
  quorum for failover and repromotion, while requiring witness acknowledgement
  independently. Reject topologies whose witnesses all share voter failure
  domains.
- **Rationale**: A witness is a fencing/election observer, not a voting
  replica. Counting it as a voter could permit one healthy voter to elect in a
  three-voter topology; co-location would also undermine domain independence.
- **Verification**: HA/DR simulation tests pass 5/5, including co-located
  witness and one-voter-plus-witness rejection; Ruff, Mypy, and diff-check pass.
- **Boundary**: Model safety only; no live PostgreSQL/network, automatic
  failover, external fencing, wall-clock RPO/RTO, or production HA claim.
- **Rollback**: Remove the checks, tests, ADR, manifest and execution records;
  no schema or data rollback is needed.

### D-319: Record the final local gate after HA/DR hardening

- **Date**: 2026-08-05
- **Decision**: Record E-410 as local regression/package evidence without
  treating it as hosted release approval or completion of the global objective.
- **Verification**: Pytest exits 0 in 326.3s; Ruff, Mypy (448 files), Bandit,
  pip-audit, build, and diff-check pass.
- **Boundary**: External providers/write-back, statutory close, independent
  HA/DR, distributed IAM, scale/soak, breadth, and production approval remain
  open.
- **Rollback**: Supersede E-410 with a later gate record; no runtime or
  migration rollback is required.

### D-320: Bind PostgreSQL evidence reads to central scope policy

- **Date**: 2026-08-05
- **Decision**: Re-evaluate `evidence.read` OR `evidence.manage` for ordinary
  evidence reads against the authenticated tenant/workspace before PostgreSQL
  access; keep sensitive drill-down on `evidence.manage`.
- **Rationale**: A dependency-level permission check does not bind a selected
  server tenant/workspace. Read projections need the same request-time central
  policy boundary as evidence mutations.
- **Verification**: ADR 0353 and `tests/test_api_server_evidence.py` pass 1/1,
  capturing all read/manage/verify calls; Ruff, Mypy, and diff-check pass.
- **Boundary**: Route IAM only; worker/export/UI adoption, federation,
  distributed invalidation, providers, HA/DR, and production IAM remain open.
- **Rollback**: Remove the helper calls, test, ADR, manifest and execution
  records; no schema or data rollback is required.

### D-321: Record the final local gate after evidence-read IAM adoption

- **Date**: 2026-08-05
- **Decision**: Record E-412 as local regression/package evidence while
  withholding hosted, external-provider, statutory, independent-HA/DR,
  distributed-IAM, scale, breadth, and production-release claims.
- **Verification**: Pytest exits 0 in 322.8s; Ruff, Mypy (448 files), Bandit,
  pip-audit, build, and diff-check pass.
- **Boundary**: The green local gate does not complete the global objective or
  authorize GitHub publication.
- **Rollback**: Supersede E-412 with a later gate record; no runtime or
  migration rollback is required.

### D-322: Bind legacy PostgreSQL audit views to tenant policy

- **Date**: 2026-08-05
- **Decision**: Re-evaluate `audit.read` and `audit.verify` with the validated
  tenant before legacy ledger audit adapter access, using tenant-wide policy
  semantics without a synthetic workspace.
- **Rationale**: The dependency-level permission did not bind the selected
  tenant; newer audit-administration routes already required this boundary.
- **Verification**: ADR 0354 and the focused server-audit/server-identity/
  audit-administration gate pass 4/4 with one declared skip; Ruff, Mypy, and
  diff-check pass.
- **Boundary**: Route IAM only; worker/export/UI adoption, federation,
  distributed invalidation, providers, HA/DR, and production IAM remain open.
- **Rollback**: Remove helper calls, test, ADR, manifest and execution records;
  no schema or data rollback is required.

### D-323: Record the final local gate after legacy-audit IAM adoption

- **Date**: 2026-08-05
- **Decision**: Record E-414 as local regression/package evidence while keeping
  hosted, external-provider, statutory, independent-HA/DR, distributed-IAM,
  scale, breadth, and production-release claims separate.
- **Verification**: Pytest exits 0 in 325.3s; Ruff, Mypy (448 files), Bandit,
  pip-audit, build, and diff-check pass.
- **Boundary**: The green local gate does not complete the global objective or
  authorize GitHub publication.
- **Rollback**: Supersede E-414 with a later gate record; no runtime or
  migration rollback is required.

### D-324: Bind legacy PostgreSQL Finance reads to tenant policy

- **Date**: 2026-08-05
- **Decision**: Re-evaluate `finance_core.read` tenant-wide before legacy
  PostgreSQL ledger summary/account/trial-balance/entry reads; retain the
  existing workspace-bound `finance_core.manage` checks for mutations.
- **Rationale**: The compatibility ledger schema rejects workspaces, but its
  dependency-level read permission still needed request-tenant binding.
- **Verification**: ADR 0355 and the focused legacy-finance/server-identity/
  Finance Core gate pass 6/6 with one declared skip; Ruff, Mypy, and diff-check
  pass.
- **Boundary**: Route IAM only; statutory posting, worker/export/UI adoption,
  federation, distributed invalidation, providers, HA/DR, and production IAM
  remain open.
- **Rollback**: Remove helper calls, assertions, ADR, manifest and execution
  records; no schema or data rollback is required.

### D-325: Record the final local gate after legacy Finance-read IAM adoption

- **Date**: 2026-08-05
- **Decision**: Record E-416 as local regression/package evidence while
  withholding hosted, external-provider, statutory, independent-HA/DR,
  distributed-IAM, scale, breadth, and production-release claims.
- **Verification**: Pytest exits 0 in 322.7s; Ruff, Mypy (448 files), Bandit,
  pip-audit, build, and diff-check pass.
- **Boundary**: The green local gate does not complete the global objective or
  authorize GitHub publication.
- **Rollback**: Supersede E-416 with a later gate record; no runtime or
  migration rollback is required.

### D-326: Govern durable-worker claim authorization

- **Date**: 2026-08-05
- **Decision**: Add an opt-in worker facade that evaluates central policy before
  a durable-job claim and requires a service-account identity matching the
  worker id plus exact tenant/workspace/entity scope.
- **Rationale**: Route-level authorization does not protect a worker process
  that calls the lease primitive directly; the claim boundary is the smallest
  reversible adoption point that preserves Community compatibility.
- **Verification**: ADR 0356 and `tests/test_governed_worker_policy.py` pass
  3/3; denied claims leave the queued job and lease-event history unchanged,
  while a scoped `match.run` service identity claims exactly one job.
- **Boundary**: This is not universal worker/export/UI adoption, distributed
  invalidation, federation, live provider, HA/DR, or production IAM evidence.
- **Rollback**: Stop wrapping workers with the facade; no schema or data
  rollback is required.

### D-327: Record the final local gate after governed worker adoption

- **Date**: 2026-08-05
- **Decision**: Record E-418 as local full-suite/package evidence while keeping
  hosted, external-provider, statutory, independent-HA/DR, distributed-IAM,
  scale, breadth, and production-release claims separate.
- **Verification**: Pytest exits 0 in 323.9s; repository inventories, Ruff,
  and Mypy pass. Existing declared skips and warnings remain visible.
- **Boundary**: The green local gate does not complete the global objective or
  authorize GitHub publication.
- **Rollback**: Supersede E-418 with a later gate record; no runtime or schema
  rollback is required.

### D-328: Gate the PostgreSQL reconciliation worker by central policy

- **Date**: 2026-08-05
- **Decision**: Add an optional tenant policy supplier to the PostgreSQL
  reconciliation worker and evaluate it before discovery and claim. Require a
  service-account actor match and exact tenant-only scope.
- **Rationale**: The worker is a separate execution surface and must not gain
  tenant work solely from database connectivity; the current schema cannot
  honestly claim workspace/entity scope.
- **Verification**: ADR 0357 and the focused worker-policy tests pass 2/2;
  the existing worker contract file passes 15 tests with one declared skip.
- **Boundary**: Opt-in tenant-only worker control; universal worker/export/UI
  adoption, revocation, federation, distributed invalidation, providers,
  independent HA/DR, and production IAM remain open.
- **Rollback**: Do not configure the optional supplier; no schema or data
  rollback is required.

### D-329: Record the final local gate after PostgreSQL worker policy adoption

- **Date**: 2026-08-05
- **Decision**: Record E-420 as the complete local regression result for the
  optional PostgreSQL reconciliation worker policy boundary.
- **Verification**: Pytest exits 0 in 324.6s with declared skips; the changed
  worker and existing repository compatibility contracts all pass.
- **Boundary**: This does not promote hosted, provider/write-back, statutory,
  independent-HA/DR, distributed-IAM, scale, breadth, or production claims.
- **Rollback**: Supersede E-420 with a later gate record; no runtime/schema
  rollback is required.

### D-330: Persist the acquisition deferred-tax bridge as non-posting evidence

- **Date**: 2026-08-05
- **Decision**: Add migration `0065_pg_deferred_tax`, a
  backend-neutral application service, and a forced-RLS append-only adapter
  for the deterministic acquisition deferred-tax artifact. Recompute before
  insert, replay-verify request/result payloads, make retries idempotent, and
  emit an audit event; reject any posted result.
- **Rationale**: Team deployments need durable, tenant-isolated evidence while
  the project has not established tax-law recognition, statutory/legal-book
  posting, or source-system write-back. Keeping this boundary non-posting
  prevents a calculation bridge from silently becoming a ledger authority.
- **Verification**: ADR 0358; focused PostgreSQL schema and authenticated API
  contracts pass, and the disposable PostgreSQL 16 non-superuser runtime gate
  passes 1/1 for RLS, idempotent replay, tenant isolation, replay verification,
  and trigger immutability.
- **Boundary**: No tax advice, statutory accounting, legal-book posting, live
  rates, ERP/bank provider, write-back, restore, HA/DR, or production claim.
- **Rollback**: Remove the application/adapter/API and migration in a code
  rollback; migration downgrade refuses to discard non-empty evidence.

### D-331: Record the deferred-tax evidence/API gate

- **Date**: 2026-08-05
- **Decision**: Record E-421 as local schema/API and inventory evidence while
  withholding live PostgreSQL, statutory, provider, HA/DR, scale, breadth, and
  GitHub publication claims.
- **Verification**: Focused schema/API contracts and the disposable PostgreSQL
  runtime gate pass; inventories report 43 backend-neutral services, 43 parity
  rows, and 238 authorization contracts.
- **Boundary**: The green local slice does not complete the global objective or
  authorize GitHub publication.
- **Rollback**: Supersede E-421 with a later gate record; migration downgrade
  refuses to remove non-empty evidence.

### D-332: Record the deferred-tax runtime and ingestion-control evidence

- **Date**: 2026-08-05
- **Decision**: Promote the local disposable PostgreSQL 16 runtime result to
  E-421 evidence while keeping the parity inventory status `contract_only`
  until a repeatable hosted/current gate exists.
- **Verification**: Alembic `0065_pg_deferred_tax` applies cleanly; the
  non-superuser runtime test passes 1/1 for forced RLS, idempotent replay,
  sibling-tenant exclusion, replay verification, and append-only triggers;
  FI-034 closes the direct-JSON parser allowlist.
- **Boundary**: Single-node synthetic runtime only; no statutory tax, live
  provider, write-back, restore, HA/DR, or production claim.
- **Rollback**: Remove the runtime evidence entry and keep the migration/API
  implementation behind the existing bounded claim boundary.

### D-333: Record the final local regression after deferred-tax persistence

- **Date**: 2026-08-05
- **Decision**: Record E-422 as a passing local regression/package gate and
  continue withholding GitHub publication until the full objective exits.
- **Verification**: Pytest exits 0 in 351.9s; Ruff, Mypy (452 files), Bandit,
  pip-audit, build, and diff-check pass with declared skips/warnings only.
- **Boundary**: This does not establish hosted release approval, statutory
  close, live providers/write-back, independent HA/DR, scale, breadth,
  distributed IAM, or production readiness.
- **Rollback**: Supersede E-422 with a later complete gate; no runtime/data
  rollback is required.

### D-334: Keep the Alembic compatibility contract on the current head

- **Date**: 2026-08-05
- **Decision**: Update the isolated PostgreSQL migration test expectation from
  the superseded `0064_pg_close_ic_links` head to `0065_pg_deferred_tax`.
- **Rationale**: A migration addition must advance both the registry and every
  version-pinned runtime assertion. Leaving the old expectation caused a real
  server-boundaries failure even though the migration chain itself was valid.
- **Verification**: The disposable PostgreSQL 16 isolated upgrade/downgrade/
  re-upgrade contract passes 1/1 locally; focused static and compatibility
  tests remain green.
- **Boundary**: This repairs test compatibility only; it is not evidence for
  statutory accounting, provider write-back, HA/DR, scale, or production.
- **Rollback**: Revert the single expectation change if the migration head is
  intentionally rolled back together with migration `0065`.

### D-335: Keep CI test dependencies in the all-extras profile

- **Date**: 2026-08-05
- **Decision**: Retain the existing CI test installation command
  `uv sync --locked --all-extras --no-editable` and verify it locally on Python
  3.11 rather than weakening tests or adding ad-hoc imports to runtime code.
- **Rationale**: The historical collection failures were missing optional test
  packages (`opentelemetry`, `cryptography`, `cbor2`), not application import
  behavior. The repository already declares those capabilities in optional
  extras, so the safe fix is to keep the matrix on the complete locked profile.
- **Verification**: The refreshed Python 3.11 environment collects 49 affected
  tests and passes 48 with one explicit live-service skip; the current CI YAML
  uses `--all-extras` for the test job.
- **Boundary**: Local environment evidence only; it does not replace hosted
  reruns or establish production readiness.
- **Rollback**: If the CI profile is intentionally narrowed, add an explicit
  reviewed test-dependency profile and update the lock/evidence together.

### D-336: Record the Python 3.11 full regression boundary

- **Date**: 2026-08-05
- **Decision**: Treat the Python 3.11 all-extras full-suite result as local
  compatibility evidence while keeping external-service and production gates
  explicit and unclaimed.
- **Verification**: The full suite exits 0 in 366.7s after the complete locked
  all-extras sync; optional live-service/platform skips and known warnings are
  retained rather than converted into passes.
- **Boundary**: No hosted matrix, live provider/write-back, statutory close,
  independent HA/DR, distributed IAM, scale, or release approval follows.
- **Rollback**: Supersede E-425 with the next exact-environment regression;
  no runtime/data rollback is required.

### D-337: Retain a fresh repeated single-host HA/DR report

- **Date**: 2026-08-05
- **Decision**: Keep the new three-run Docker PostgreSQL synchronous-standby
  report as dated runtime evidence while preserving the partial single-host
  boundary.
- **Verification**: All runs pass with zero acknowledged transaction loss and
  cleanup; failover RTO is 11.084–11.175s and failback RTO is 0.981–1.023s.
  The report is schema-validated and packaged.
- **Boundary**: Two containers share one host and a manual controller. No
  independent failure domains, quorum/witness, automatic failover, site-loss,
  managed-key, or production-SLO claim is authorized.
- **Rollback**: Remove the dated report and its manifest/test pointer if the
  drill is invalidated; retain the prior report as historical evidence.

### D-338: Gate hosted scheduler and outbox workers with central policy

- **Date**: 2026-08-05
- **Decision**: Add an opt-in shared service-worker authorization guard to the
  PostgreSQL scheduler and transactional-outbox workers before connection
  access.
- **Verification**: Four focused contracts pass: denial-before-I/O and
  allowed service identity for each worker. Existing unconfigured and local
  worker behavior remains unchanged.
- **Boundary**: Tenant-only worker rows do not support workspace/entity scope;
  universal worker/export/UI adoption, revocation, federation, distributed
  invalidation, providers, HA/DR, and production IAM assurance remain open.
- **Rollback**: Remove the additive guard/settings and retain the prior
  unconfigured worker contract.

### D-339: Record the post-IAM full local regression

- **Date**: 2026-08-05
- **Decision**: Keep the complete local regression as compatibility evidence
  after adding the hosted scheduler/outbox policy guard.
- **Verification**: Pytest exits 0 in 345.7s; declared external-service and
  platform skips plus existing warnings remain visible.
- **Boundary**: No hosted matrix, live provider/write-back, statutory close,
  independent HA/DR, distributed IAM, scale/soak, breadth, or release
  approval follows.
- **Rollback**: Supersede E-428 with the next exact-environment regression;
  no runtime/data rollback is required.

### D-340: Record local static/security/package gates with audit boundary

- **Date**: 2026-08-05
- **Decision**: Retain the post-E-427 static, dependency, package, and diff
  checks as local evidence while stating the pip-audit project exclusion.
- **Verification**: Ruff, Mypy (453 files), Bandit, pip-audit 2.10.1, package
  build, and `git diff --check` pass; known warnings remain visible.
- **Boundary**: No hosted secret/dependency gate, signed SBOM/provenance,
  trusted-builder assessment, or release approval follows.
- **Rollback**: Supersede E-429 with the next exact-environment gate; no
  runtime/data rollback is required.

### D-341: Retain the current no-network sovereign deployment drill

- **Date**: 2026-08-05
- **Decision**: Keep the fresh Docker install, local-identity recovery, and
  exact tagged application rollback as current dated evidence.
- **Verification**: 68 hash-locked bundle entries, 100,386,256 bytes, network
  mode none, read-only mounts, doctor success, two-user recovery, wrong-key
  atomic refusal, zero old-session restoration, zero network upgrade inputs,
  and exact rollback all pass.
- **Boundary**: Connected assembly and one Linux/Python runtime only; no
  signature trust, physical custody, OCI verification, hardware-backed keys,
  multi-platform repetition, HA/DR, or production readiness follows.
- **Rollback**: Remove the dated report/schema/test pointer and retain the
  historical 2026-07-30 drill artifacts.

### D-342: Retain the current live S3-compatible object-storage drill

- **Date**: 2026-08-05
- **Decision**: Keep the disposable MinIO execution as fresh runtime evidence
  for the real boto3-backed object-store adapter, while keeping the provider
  and availability claim bounded.
- **Verification**: Digest-pinned MinIO, normal and Object Lock buckets, five
  true invariants, cleanup, and report digest
  `5f4ef103abfe4b198bc64e348f554dc52e56d3ebb5d7f425faf1761ce6225c6a`.
- **Boundary**: Single-node synthetic runtime only; no replication, KMS,
  cross-site durability, provider interoperability, object-store HA/DR,
  malware scanning, authorized downloads, or production SLO.
- **Rollback**: Remove the dated report and focused test while retaining the
  provider-neutral contract and prior hosted evidence.

### D-343: Derive CI object-storage credentials at runtime

- **Date**: 2026-08-05
- **Decision**: Remove the literal synthetic MinIO password from workflow
  environment mappings and derive an identical disposable value within each
  step from a non-secret seed.
- **Verification**: Focused live-object-storage workflow tests, supply-chain
  policy validation, Ruff, and diff-check pass; the existing digest-pinned
  provider contract is unchanged.
- **Boundary**: This improves repository secret hygiene but does not replace
  hosted Gitleaks history/tree evidence, credential-vault integration, or
  production secret management.
- **Rollback**: Restore the prior environment wiring only if the disposable
  provider contract cannot authenticate; do not add a Gitleaks exception.

### D-344: Retain the current live Redis session/policy drill

- **Date**: 2026-08-05
- **Decision**: Keep the fresh digest-pinned Redis runtime report as bounded
  evidence for tenant-scoped sessions, revocation keys, and shared policy
  generation.
- **Verification**: Four invariants and cleanup pass; the report is
  schema-closed and digest-bound to
  `99fbd6b7aba969e0a41f4faa9e26d034e5e0f3b5a36e0e4e22bb2928ed9b44ca`.
- **Boundary**: Single-node synthetic runtime only; no replication,
  Sentinel/Cluster failover, cross-site durability, Redis HA, or SLO evidence.
- **Rollback**: Remove the dated verifier/report/test and retain existing
  provider-neutral Redis contracts and the CI server-boundary tests.

### D-345: Record the current full local regression

- **Date**: 2026-08-05
- **Decision**: Retain the complete local suite as compatibility evidence after
  the live Redis/object-storage slices.
- **Verification**: Pytest exits 0 in 356.1s with no collection or executed
  failure; external-service and capability skips plus existing warnings remain
  visible.
- **Boundary**: No hosted matrix, live vendor/write-back, statutory close,
  independent HA/DR, distributed IAM, scale/soak, or release approval follows.
- **Rollback**: Supersede E-434 with the next exact-environment regression; no
  runtime/data rollback is required.

### D-346: Add an export-based retail POS settlement slice

- **Date**: 2026-08-05
- **Decision**: Deliver the first retail breadth use case as an experimental,
  non-posting, local export control. Keep provider connectivity and accounting
  effects outside the slice until separately evidenced.
- **Verification**: Exact Money/tolerance arithmetic, refunds/fees/chargebacks,
  missing/duplicate/ambiguous records, permutation-stable decision digest,
  digest-bound report/tamper refusal, local CLI, synthetic JSON/CSV fixtures,
  module registry, and declarative pack tests pass.
- **Boundary**: No live processor/ERP interoperability, settlement finality,
  fraud assessment, journal posting, write-back, persistence/API/Studio,
  HA/DR, or complete retail breadth claim follows.
- **Rollback**: Remove the E-435 slice files and registry entry in one reviewed
  commit; existing reconciliation, connector, and inventory modules remain
  independent.

### D-347: Retain the post-retail local gate as bounded evidence

- **Date**: 2026-08-05
- **Decision**: Record the full local regression and static/package/security
  tools after E-435, while keeping hosted and external-service gates separate.
- **Verification**: Pytest exits 0 in 343.2s; Ruff, Mypy (456 files), Bandit,
  pip-audit, supply-chain validation, package build, and diff-check pass.
- **Boundary**: The local pip-audit project exclusion, declared service skips,
  existing warnings, hosted matrices, live providers, independent recovery,
  distributed IAM, scale/soak, and publication remain unresolved.
- **Rollback**: Supersede E-436 with the next exact-environment run; no runtime
  or data rollback is required.

### D-348: Add an export-based bank statement control slice

- **Date**: 2026-08-05
- **Decision**: Deliver the first banking/professional breadth use case as an
  experimental, non-posting local CAMT.053-to-ledger control. Keep bank/provider
  connectivity, payment initiation, accounting posting, and ERP write-back out
  of the slice until separately evidenced.
- **Verification**: Exact Money/tolerance arithmetic, normalized-reference
  matching, booking-date window, account/amount exceptions, duplicate and
  unmatched visibility, ambiguity refusal, permutation-stable digest,
  digest-bound report/tamper refusal, local CLI, synthetic fixtures, module and
  threat-model parity, and declarative pack tests are required.
- **Boundary**: No bank authenticity, live provider/ERP interoperability,
  payment initiation, statutory posting, write-back, persistence/API/Studio,
  HA/DR, or complete banking breadth claim follows.
- **Rollback**: Remove the E-437 slice files, CLI wiring, pack, fixtures, schema,
  docs, registry entry, and tests in one reviewed commit; existing CAMT.053
  ingestion remains independent.

### D-349: Retain the post-bank local gate as bounded evidence

- **Date**: 2026-08-05
- **Decision**: Record the complete local regression and static/security/package
  gates after E-437, while keeping hosted matrices and external banking/ERP
  evidence separate.
- **Verification**: Pytest exits 0 in 344.6s; Ruff, Mypy (459 files), Bandit,
  pip-audit with the unpublished-project exclusion, supply-chain validation,
  package build, and diff-check pass. Declared service skips and warnings remain
  visible.
- **Boundary**: This is local compatibility/package evidence only; it does not
  prove live providers/write-back, statutory close, independent HA/DR,
  distributed IAM, scale/soak, or release approval.
- **Rollback**: Supersede E-438 with the next exact-environment run; no runtime
  or data rollback is required.

### D-350: Add an export-based manufacturing production-cost control slice

- **Date**: 2026-08-05
- **Decision**: Deliver the first manufacturing breadth use case as an
  experimental, non-posting local production-order control. Keep statutory or
  standard-cost valuation, ERP/MRP connectivity, inventory/WIP/GL posting, and
  write-back out of the slice until separately evidenced.
- **Verification**: Exact Money/Quantity arithmetic, normalized record
  contracts, material and completion cost variance, planned/completed quantity,
  scrap limit, unknown-order visibility, permutation-stable digest,
  digest-bound report/tamper refusal, local CLI, synthetic fixtures, module and
  threat-model parity, and declarative pack tests are required.
- **Boundary**: No statutory valuation, live provider/ERP interoperability,
  inventory/WIP/GL posting, write-back, persistence/API/Studio, HA/DR, or
  complete manufacturing breadth claim follows.
- **Rollback**: Remove the E-439 slice files, CLI wiring, pack, fixtures, schema,
  docs, registry entry, and tests in one reviewed commit.

### D-351: Close the post-manufacturing dependency audit with OSV

- **Date**: 2026-08-05
- **Decision**: Close E-440 after the current dependency audit completed through
  the OSV service, while retaining the explicit local/hosted boundary.
- **Verification**: Full pytest, Ruff, Mypy (462 files), Bandit, supply-chain
  policy, package build, diff-check, and
  `uv run pip-audit -s osv --progress-spinner off --timeout 30` pass; OSV
  reports no known vulnerabilities.
- **Boundary**: OSV dependency evidence excludes the unpublished local
  distribution and does not replace hosted security/provenance or release
  approval; no GitHub publication occurs here.
- **Rollback**: Supersede E-440 with the next exact-environment audit if the
  locked dependency graph changes; no runtime/data rollback is needed.

### D-352: Preserve exact query strings for read-only connector destinations

- **Date**: 2026-08-06
- **Decision**: Permit fixed query strings in operator-declared HTTPS network
  connector destinations and send them verbatim through the pinned transport.
  Keep exact endpoint matching, public-DNS pinning, no redirects, secret
  references in headers, and visible-ASCII/credential/fragment rejection.
- **Rationale**: Public REST endpoints often require immutable filters or page
  parameters. Rejecting all queries made the generic read-only connector unable
  to represent those endpoints, while runtime query construction would weaken
  the allowlist and replay contract.
- **Verification**: Focused network, SDK, and database connector contracts pass
  35/35, including query registration, request-target preservation, public
  no-auth header isolation, redirect refusal, DNS checks, bounded retry, and
  response/credential/cursor limits.
- **Boundary**: This remains a read-only connector contract and does not prove
  live provider availability, authentication interoperability, write-back,
  production capacity, or deployment readiness. ADR: `0369-allowlisted-query-urls-in-readonly-network-connectors.md`.
- **Rollback**: Restore query rejection and the prior request-target behavior;
  no schema or data rollback is needed.

### D-353: Permit explicitly public no-auth network reads

- **Date**: 2026-08-06
- **Decision**: Allow `AuthenticationMethod.NONE` only for read-only network
  sources with an exact operator-declared HTTPS egress destination and rate
  limit. Such registrations must omit `credential_reference` and the executor
  must emit no authorization header. Database, SFTP, object-storage, payment,
  and write-back registrations remain credentialed.
- **Rationale**: Open public-data APIs do not require a secret, and fabricating
  a secret-reference requirement would make a truthful public connector
  contract impossible. Exact egress, DNS public-address pinning, TLS hostname
  validation, no redirects, bounded retries, and response limits remain in
  force.
- **Verification**: Public registration/execution/replay tests pass without a
  secret resolver; credentialed connector suites remain green and no-auth
  registrations carrying a credential are rejected.
- **Boundary**: This is a provider-neutral transport capability, not a live
  public-data connector, availability, freshness, or production operations
  claim. ADR: `0369-allowlisted-query-urls-in-readonly-network-connectors.md`.
- **Rollback**: Remove the no-auth branch and restore mandatory credential
  references; no migration or data rollback is needed.

### D-354: Record PostgreSQL grouped-matching scale without widening the claim

- **Date**: 2026-08-06
- **Decision**: Retain the local 500-partition and 10K-partition grouped-
  matching runs as bounded PostgreSQL correctness/concurrency evidence. Do not
  convert their wall time or single-host execution into production throughput,
  soak, HA, host-loss, cross-host fairness, RPO/RTO, or capacity claims.
- **Verification**: PostgreSQL 17.10 isolated databases under the
  non-privileged `reconforge_app` role passed the exact 500-partition profile in
  67.9s and 10K profile in 336.2s. The 10K run completed 1,000 runs and 10,000
  partitions across all five declared modes with 24,000 result rows, zero
  duplicate identities, zero failed runs, and zero active runs. Cleanup dropped
  both databases.
- **Boundary**: Synthetic single-host evidence only; production hardware,
  multi-host fairness, soak, queue HA, host-loss, and RPO/RTO remain open.
- **Rollback**: Supersede this evidence with a later exact-profile run; no
  runtime or data rollback is required.

### D-355: Re-run the complete local suite after connector and scale changes

- **Date**: 2026-08-06
- **Decision**: Require and record a complete local pytest run after the
  public no-auth/query-preserving connector and PostgreSQL grouped-matching
  evidence changes before any release-candidate discussion.
- **Verification**: `uv run --no-sync pytest -q --tb=short -ra` exits 0 in
  379.8s. No executed test failed; PostgreSQL/Redis capability skips and
  existing framework/legacy-input warnings remain explicit.
- **Boundary**: Local compatibility only; hosted Python/security/Docker/
  browser matrices, live provider availability, independent HA/DR, and
  publication approval remain external.
- **Rollback**: Supersede E-458 with the next exact-environment full run; no
  runtime or data rollback is required.

### D-356: Require the final local static and package gate

- **Date**: 2026-08-06
- **Decision**: Treat the current revision as locally regression-clean only
  after static analysis, dependency audit, supply-chain policy, package build,
  and diff checks pass after E-458.
- **Verification**: Ruff, Mypy over 465 source files, Bandit, OSV pip-audit
  after one retried TLS transport failure, supply-chain policy validation,
  package build, and `git diff --check` all pass.
- **Boundary**: This does not attest hosted CI/security/provenance, external
  providers, independent HA/DR, production operations, or publication approval.
- **Rollback**: Supersede E-459 with the next exact lock/source gate; no
  runtime or data rollback is required.

### D-357: Add a closed World Bank public REST reference connector

- **Date**: 2026-08-06
- **Decision**: Add a built-in no-auth World Bank REST reference connector with
  exact allowlisted page URLs, a closed finite-Decimal schema, bounded pages,
  and canonical response digests.
- **Verification**: Focused connector tests pass; the opt-in live transport
  test fetched the first 1,000-row page and validated the 2,890-row source
  count. The implementation is covered by ADR 0370.
- **Boundary**: This proves a bounded public reference path, not provider SLA,
  freshness, bank/ERP interoperability, write-back, or production readiness.
- **Rollback**: Remove the module/exports/tests/manifest entry; no migration
  or persistent-data rollback is needed.

### D-358: Bootstrap native PostgreSQL tools explicitly in the hosted gate

- **Date**: 2026-08-06
- **Decision**: Install the Ubuntu distribution PostgreSQL client package in
  `server-boundaries` before the live parity and backup tests, then assert the
  five required binaries resolve from `pg_config --bindir`.
- **Context**: The supplied hosted run exposed a native backup failure while
  local Windows cannot provide the PostgreSQL client-tool set. Making the
  dependency explicit removes an ambient-runner assumption; it does not hide
  a failing backup test.
- **Boundary**: A hosted rerun is still required to prove encrypted dump,
  restore, cleanup, and rollback; this workflow change is not runtime evidence.
- **Rollback**: Remove the bootstrap step and restore the prior runner
  dependency; no application migration or data rollback is involved.

### D-359: Record the World Bank connector in the closed JSON parser inventory

- **Date**: 2026-08-06
- **Decision**: Classify the connector's single direct `json.loads` call under
  FI-023, the existing bounded public-financial response surface, rather than
  bypassing the repository AST allowlist.
- **Verification**: `tests/test_file_ingestion_inventory.py::test_direct_json_parser_inventory_is_an_exact_ast_allowlist`
  passes after the exact path/call-count/rationale entry and connector test
  evidence are recorded.
- **Boundary**: Inventory closure covers parser-call governance; it does not
  authenticate the publisher, establish freshness, or make public data a
  production source.
- **Rollback**: Replace the direct parser with the central bounded reader or
  remove the connector and its allowlist entry; no data migration is needed.

### D-360: Require a clean full regression after parser-inventory repair

- **Date**: 2026-08-06
- **Decision**: Promote the current local suite result only after rerunning the
  complete pytest collection following the direct-parser inventory fix.
- **Verification**: `uv run --no-sync pytest -q --tb=short -ra` exits 0 in
  348.9s; all collected tests pass with only declared capability skips and
  existing warnings.
- **Boundary**: Local compatibility does not attest hosted CI, native
  PostgreSQL backup/restore, external providers, HA/DR, or publication.
- **Rollback**: Supersede E-463 with the next exact-environment full run; no
  runtime or data rollback is needed.

### D-361: Close the current static and package gate after connector lint repair

- **Date**: 2026-08-06
- **Decision**: Require the full static/security/dependency/package sequence on
  the current connector head after import ordering and Bandit suppression are
  corrected.
- **Verification**: Ruff, Mypy (466 files), Bandit, OSV pip-audit, closed
  supply-chain validation, package build, and diff-check all pass.
- **Boundary**: Local gates do not attest hosted security, provenance,
  external providers, HA/DR, or production publication.
- **Rollback**: Supersede E-464 with the next exact lock/source gate; no
  runtime or data rollback is needed.

### D-362: Keep hosted secret-scan failure separate from local reproduction

- **Date**: 2026-08-06
- **Decision**: Record the clean current Gitleaks history/tree scan as local
  evidence while retaining the hosted repository-security result as unresolved
  until the exact workflow is rerun.
- **Verification**: Gitleaks 8.30.1 scanned 508 commits and the current tree;
  both scans exited 0 with no leaks.
- **Boundary**: A local scan cannot attest GitHub checkout state, workflow
  environment, or hosted security approval.
- **Rollback**: Supersede E-465 with a fresh exact hosted/local paired scan;
  no runtime or data rollback is needed.

### D-363: Keep connector SDK documentation aligned with the reference portfolio

- **Date**: 2026-08-06
- **Decision**: Update the SDK foundation document to describe the governed
  read-only reference connectors and the concrete World Bank test path, while
  preserving the explicit no-live-vendor/no-write-back boundary.
- **Verification**: Documentation names exact endpoint/schema/digest behavior,
  opt-in live execution, and the non-production claim boundary; connector
  focused tests and package build remain green.
- **Boundary**: Documentation alignment is not provider interoperability or
  release approval.
- **Rollback**: Restore the prior generic SDK wording; no code/data rollback is
  required.

### D-364: Treat execution backlog serialization as a release gate

- **Date**: 2026-08-06
- **Decision**: Require the execution backlog to parse as YAML and contain
  unique task IDs after every evidence append; leading backticks are removed
  from plain scalar starts or quoted explicitly.
- **Verification**: PyYAML parses 133 tasks with unique IDs; targeted workflow,
  policy, and diff checks pass.
- **Boundary**: Serialization validity does not prove any runtime, hosted, or
  production gate.
- **Rollback**: Restore the prior scalar text only if it remains valid YAML;
  no runtime/data rollback is needed.

### D-365: Promote the latest bounded PostgreSQL HA/DR drill without widening claims

- **Date**: 2026-08-06
- **Decision**: Retain the latest three-run Docker primary/standby drill and
  report it as current single-host runtime evidence, including encrypted
  backup/restore and cleanup, while preserving all cross-domain limitations.
- **Verification**: Three runs pass with zero acknowledged loss, failover RTO
  11.055-11.137s, failback RTO 0.959-0.968s, fencing, partition refusal, and
  complete cleanup; the report and schema test are committed.
- **Boundary**: One host/failure domain, manual controller, synthetic data/key,
  no quorum/witness, no host-loss independence, and no production SLO claim.
- **Rollback**: Remove the dated report and evidence entry; no runtime/data
  rollback is needed.

### D-366: Retain the latest object-storage runtime report as bounded evidence

- **Date**: 2026-08-06
- **Decision**: Commit the latest disposable MinIO report and validate it beside
  the previous artifact, preserving the exact image digest, report digest, and
  synthetic/single-node limitations.
- **Verification**: The live boto3 drill passes scope isolation, immutable
  conflict, checksum tamper refusal, Object Lock deletion refusal, and cleanup;
  the schema/digest test validates both dated reports.
- **Boundary**: No replication, KMS, cross-site durability, provider
  interoperability, object-store HA, or production SLO claim follows.
- **Rollback**: Remove the dated report and latest assertion; no runtime/data
  rollback is needed.

### D-367: Retain the current Redis runtime report as bounded evidence

- **Date**: 2026-08-06
- **Decision**: Commit the current disposable Redis report and validate it beside
  the prior artifact, preserving the exact image digest, report digest, and
  synthetic/single-node limitations.
- **Verification**: The live adapter drill passes tenant-key isolation,
  non-persistence of raw session tokens, shared policy generation, and cleanup;
  the closed schema/digest test validates both dated reports.
- **Boundary**: No replication, Sentinel/Cluster failover, cross-site
  durability, Redis HA, or production SLO claim follows.
- **Rollback**: Remove the dated report and latest assertion; no runtime/data
  rollback is needed.

### D-368: Retain the current grouped-matching 1M rerun as bounded evidence

- **Date**: 2026-08-06
- **Decision**: Record two current-tree runs of the declared 1M grouped-matching
  profile with a canonical machine-readable report and digest-bound test.
- **Verification**: Both runs cover 250,000 partitions/1,000,000 records with
  zero ambiguous, unmatched, cross-engine, or permutation mismatches and equal
  effect/manifest digests.
- **Boundary**: One Windows host/process, exact-USD synthetic four-record
  partitions, bounded per-partition search; no distributed capacity, PostgreSQL
  parity, soak, provider I/O, SLO, or production claim follows.
- **Rollback**: Remove the current report, markdown section, and test assertion;
  no runtime/data rollback is required.

### D-369: Retain the current PostgreSQL backpressure rerun as bounded evidence

- **Date**: 2026-08-06
- **Decision**: Commit a digest-bound report for the current PostgreSQL
  durable-job queue-cap run beside the historical artifact.
- **Verification**: A non-privileged PostgreSQL 17.10 runtime completes all 64
  jobs and 256 effects, enforces the four-job lane cap, records rejected/retried
  submissions, and drains to zero queued/running residue with no duplicates.
- **Boundary**: One host and synthetic workload; no capacity, queue HA,
  automatic failover, host loss, cross-host fairness, soak, RPO/RTO, or
  production SLO claim follows.
- **Rollback**: Remove the dated report, markdown section, and test assertion;
  no runtime/data rollback is required.

### D-370: Record the current full local regression after scale evidence

- **Date**: 2026-08-06
- **Decision**: Promote the current full pytest run as a local compatibility
  gate while retaining all declared skips and warnings in the evidence.
- **Verification**: `uv run --no-sync pytest -q --tb=short -ra` exits 0 in
  364.3s with no collection or executed failure.
- **Boundary**: Local Windows evidence only; hosted matrix, live-provider,
  independent HA/DR, and release approval gates remain external.
- **Rollback**: Remove the evidence/backlog entry; no runtime/data rollback is
  required.

### D-371: Retain the final local static/package gate after scale evidence

- **Date**: 2026-08-06
- **Decision**: Record the final Ruff, Mypy, package-build, and diff-check pass
  for the current head after the benchmark/report additions.
- **Verification**: Ruff passes, Mypy reports no issues in 466 source files,
  `python -m build --no-isolation` succeeds, and `git diff --check` passes.
- **Boundary**: This does not replace hosted security, signed provenance,
  repository-security, or release approval.
- **Rollback**: Remove the evidence/backlog entry; no runtime/data rollback is
  required.

### D-372: Correct PostgreSQL close intercompany period binding

- **Date**: 2026-08-06
- **Decision**: Treat `run.period_id` as an internal row identity and bind
  source artifact periods to the verified worksheet business period instead.
- **Verification**: The isolated PostgreSQL 17.10 financial-close focus passes
  ownership, intercompany close, PPA, and deferred-tax contracts 18/18.
- **Boundary**: This is a local PostgreSQL correctness fix; statutory policy,
  hosted CI, providers, write-back, and HA/DR remain open.
- **Rollback**: Revert the comparison logic; no migration or data rollback is
  required.

### D-373: Promote the current PostgreSQL IAM contract focus

- **Date**: 2026-08-06
- **Decision**: Retain a fresh migration-head non-superuser runtime result for
  the selected IAM/RLS administration and privileged-session contracts.
- **Verification**: Access/identity/security governance, delegation,
  policy-analysis, service-account, and privileged-session focus passes 23/23
  in 19.1s on PostgreSQL 17.10.
- **Boundary**: Synthetic single-node evidence only; federation, UI/job/export
  adoption, distributed cache invalidation, HA/DR, and production IAM remain
  unverified.
- **Rollback**: Remove the evidence entry and ADR; no runtime/data rollback is
  required.

### D-374: Promote the current PostgreSQL database-reference focus

- **Date**: 2026-08-06
- **Decision**: Retain the fresh migration-head database-reference runtime
  result as bounded connector evidence.
- **Verification**: The non-privileged PostgreSQL 17.10 live suite passes 3/3
  for named read-only query, bounded row/digest, cursor/replay, and tenant
  isolation behavior; the disposable database is removed afterward.
- **Boundary**: Deployment-provided PostgreSQL views only; no live ERP/bank
  vendor, schema certification, write-back, hosted provider, or production
  interoperability claim follows.
- **Rollback**: Remove the evidence entry and ADR; no runtime/data rollback is
  required.
# ADR 0367 evidence note — professional invoice-to-payment control (2026-08-05)

Implemented and bounded the `professional.invoice-payment` module. It is local,
non-posting, and provider-neutral. Exact `Money`, normalized references, client
identity, due-date window, duplicate/ambiguity, unmatched-invoice, and
unapplied-payment behavior are explicit and digest-bound. The slice does not
claim revenue recognition, receivables allocation, live billing/payment
connectivity, ERP posting/write-back, HA/DR, or production readiness.
### D-306: Treat professional invoice/payment evidence as local bounded breadth
- **Date**: 2026-08-05
- **Context**: The professional-services vertical needed a real, testable control
  without pretending that exported files are a live billing or receivables
  system.
- **Decision**: Ship the `professional.invoice-payment` module as experimental,
  local-first, non-posting, provider-neutral code with exact Money arithmetic,
  explicit ambiguity/unapplied outcomes, and digest-bound reports.
- **Rationale**: This adds useful individual/professional breadth while keeping
  revenue recognition, allocation, posting, provider authentication, and ERP
  write-back behind separate evidence gates.
- **Reversibility**: Remove the module/pack/CLI and registry metadata; no
  migration or persistent data rollback is required.
- **Verification**: Focused tests, pack validation, full pytest, Ruff, Mypy,
  Bandit, OSV, supply-chain policy, build, and diff-check all pass locally.

### D-307: Record the current full regression after the PostgreSQL period fix
- **Date**: 2026-08-06
- **Context**: E-475 corrected an internal PostgreSQL period-row identity being
  compared with the close worksheet's business period. A fresh complete local
  regression is required before treating the correction as compatible with the
  rest of the tree.
- **Decision**: Record the full `pytest` run as a local compatibility checkpoint
  while retaining explicit external and hosted boundaries.
- **Verification**: `uv run --no-sync pytest -q --tb=short -ra` exits 0 in
  356.4 seconds; no collected or executed test failed, with only declared
  capability skips and existing warnings.
- **Boundary**: This does not close hosted CI, native backup-tool availability,
  live ERP/bank interoperability or write-back, statutory accounting,
  independent HA/DR, or production approval.
- **Reversibility**: Remove the evidence entry and ADR; no runtime/data
  rollback is required.

### D-310: Record the current PostgreSQL application-parity batch
- **Date**: 2026-08-06
- **Context**: After the API authorization correction, a broader live runtime
  pass is needed to detect regressions across the stateful application ports.
- **Decision**: Retain a fresh, disposable PostgreSQL 17.10 batch of 117
  selected application and scope tests as bounded parity evidence; remove the
  database after every run.
- **Verification**: All 117 selected tests pass under the non-privileged
  `reconforge_app` role; the Finance Core API live seam now injects both scope
  resolver modules and both exact/any-of authorization helpers correctly.
- **Boundary**: This does not close full parity, hosted backup tooling, live
  ERP/bank providers/write-back, HA/DR, scale, or production readiness.
- **Reversibility**: Remove the evidence entry and ADR; no runtime/data
  rollback is required.

### D-308: Preserve FinanceRead any-of semantics in server scope checks
- **Date**: 2026-08-06
- **Context**: Live PostgreSQL API execution showed that an authorized
  `finance_core.validate` emergency grant passed the route dependency but was
  denied by a second exact `finance_core.read` scope check. WebAuthn summary
  access exposed the same mismatch.
- **Decision**: Re-evaluate FinanceRead routes with the same any-of contract
  (`read`, `manage`, `validate`) while leaving manage/validate mutation routes
  exact. Keep the legacy identity live fixture explicitly on its ledger
  compatibility boundary.
- **Verification**: Fresh PostgreSQL 17.10 non-privileged live API suite
  passes 24/24 across emergency access, WebAuthn, identity, federation, SCIM,
  service accounts, and metrics; Ruff, Mypy, and diff-check pass.
- **Boundary**: This is route authorization consistency evidence, not complete
  enterprise IAM, federation, live provider/write-back, HA/DR, or production
  approval.
- **Reversibility**: Revert the helper/fixture change and remove the evidence
  entry and ADR; no migration or data rollback is required.

### D-309: Record the current regression after the API authorization fix
- **Date**: 2026-08-06
- **Context**: The FinanceRead any-of correction changed a central route helper
  and its unit contract; a complete local regression is required to validate
  compatibility.
- **Decision**: Record the fresh full pytest run as the current compatibility
  checkpoint while preserving external release boundaries.
- **Verification**: `uv run --no-sync pytest -q --tb=short -ra` exits 0 in
  354.3 seconds with no collection or executed failure; only declared
  capability skips and existing warnings remain.
- **Boundary**: This is not hosted release approval, live provider/write-back,
  statutory accounting, independent HA/DR, or production evidence.
- **Reversibility**: Remove the evidence entry and ADR; no runtime/data
  rollback is required.

### D-310: Separate write-back mutation from idempotency recovery
- **Date**: 2026-08-06
- **Context**: A provider may accept a write-back POST while the client loses
  the acknowledgement. Retrying the mutation is only safe when the provider's
  idempotency semantics are independently known; the generic transport had no
  explicit recovery boundary.
- **Decision**: Add an injected `WritebackRecoveryTransport` and an executor
  recovery method that queries provider status with the original idempotency
  key. Recovery never resolves the payload and never calls the mutation
  transport. A missing or misbound status fails closed.
- **Verification**: The focused network suite passes 18/18, including recovery
  with zero POST calls and 404/misbound acknowledgement refusal; Ruff and Mypy
  pass for the changed transport surface.
- **Boundary**: This does not prove any ERP, bank, or payment provider status
  API, distributed idempotency, accounting posting, HA/DR, or production
  write-back.
- **Reversibility**: Remove the protocol, executor method, tests, ADR, and
  evidence entry; no migration or persisted-data rollback is required.

### D-311: Expose provider-status recovery through the server boundary
- **Date**: 2026-08-06
- **Context**: The recovery primitive was safe but not callable through the
  authenticated server workflow. Operators need a scope-bound path that can
  recover a dispatched intent without posting again.
- **Decision**: Add `POST /api/v1/connectors/writeback/intents/{intent_id}/recover`
  behind `connectors.writeback.reconcile`. It is server-profile-only, requires
  the expected lifecycle version, rejects non-dispatched states, and persists
  only the verified recovery acknowledgement.
- **Verification**: API and authorization inventory tests pass 8/8; the closed
  inventory is 239 routes with digest
  `17c4bfc40da554070b4cf1589e49845f7a77a798654ac3dbb80eced0b567b388`; Ruff and
  Mypy pass.
- **Boundary**: No local network, provider status API, live ERP/bank mutation,
  accounting posting, distributed idempotency, HA/DR, or production claim is
  added.
- **Reversibility**: Remove the route/request model/inventory expectation/tests,
  ADR, and evidence entry; no migration or data rollback is required.

### D-312: Preserve write-back recovery replay idempotency
- **Date**: 2026-08-06
- **Context**: A successful recovery persists `DISPATCHED -> ACKNOWLEDGED` and
  increments the lifecycle version. A lost API response must be replayable with
  the original dispatched version without querying the provider again.
- **Decision**: Accept `expected_version` equal to either the current
  acknowledged version or its immediately preceding dispatched version when
  returning `already_acknowledged`; stale versions remain rejected.
- **Verification**: The API connector and authorization-inventory suite passes
  8/8; the replay assertion confirms one provider lookup and zero POST calls.
- **Boundary**: This is local optimistic-replay evidence only; it does not prove
  provider idempotency, distributed coordination, live write-back, or HA/DR.
- **Reversibility**: Remove the version condition, regression assertion, and
  evidence entry; no migration or data rollback is required.

### D-313: Bootstrap the PostgreSQL write-back runtime in its target database

- **Date**: 2026-08-06
- **Context**: The live write-back persistence test connected its privileged
  setup session to the configured database but did not install the shared RLS
  foundation before creating the write-back table. A disposable runtime could
  therefore not exercise the intended schema boundary.
- **Decision**: Install `install_postgres_rls_schema` on the privileged
  connection before `POSTGRES_WRITEBACK_SCHEMA_SQL`, then grant only the
  declared schema/table privileges to the non-privileged role. Keep the test
  database and role disposable and clean them in `finally`.
- **Verification**: PostgreSQL 16.14 runtime passes
  `tests/test_postgres_writeback.py` 2/2, including RLS, append-only,
  idempotency, version conflict, and tenant-isolation assertions.
- **Boundary**: This proves only a single-node synthetic persistence contract;
  it does not prove a live provider status API, accounting posting, distributed
  idempotency, HA/DR, or production write-back.
- **Reversibility**: Restore the prior fixture setup; no application migration
  or persisted-data change is involved.

### D-314: Keep dense grouped-matching ambiguity fail-closed

- **Date**: 2026-08-06
- **Context**: Fee-aware netting and FX conversion were covered by focused
  cases, but their combination with dense equal-cost candidates and exhausted
  search budgets needed an explicit adversarial contract.
- **Decision**: Add a bounded four-case suite without changing the public
  matcher API. Equal-cost alternatives must remain `GROUP_MATCH_AMBIGUOUS`,
  budget exhaustion must return no selected identities, and mixed partition or
  currency candidates must remain unmatched. FX/fee replay must preserve its
  digest under input permutation.
- **Verification**: `tests/test_grouped_matching_adversarial.py` passes 4/4;
  Ruff/Mypy and source-distribution membership pass under ADR 0381.
- **Boundary**: This is algorithm correctness evidence only. It does not
  establish fuzzing, mutation score, PostgreSQL parity, live-rate correctness,
  performance, posting, write-back, or production readiness.
- **Reversibility**: Remove the four tests, ADR, manifest entry, and evidence;
  no schema or persisted-data change is involved.

### D-315: Make provider-status recovery an explicit pinned HTTPS GET

- **Date**: 2026-08-06
- **Context**: Recovery was safe only through an injected lookup boundary. A
  production-shaped transport was needed without guessing vendor URL shapes or
  turning recovery into a second mutation.
- **Decision**: Add optional `recovery_endpoint` registration metadata, require
  exact HTTPS/no-query/no-fragment validation and egress declaration, and use a
  separate `PinnedHttpsRecoveryTransport` that performs a bounded GET with the
  original idempotency key. The executor falls back to the mutation endpoint
  only for backward-compatible injected transports.
- **Verification**: The focused network suite passes 19/19, including a real
  disposable TLS sandbox with three POST retries and one pinned GET recovery;
  Ruff and Mypy pass.
- **Boundary**: This proves a provider-neutral loopback transport only; vendor
  status semantics, accounting posting, distributed idempotency, HA/DR, and
  production write-back remain unverified.
- **Reversibility**: Remove the registration field, transport, tests, ADR,
  manifest entry, and evidence; no migration or persisted-data rollback is
  required.

### D-316: Cover every grouped-matching resume checkpoint

- **Date**: 2026-08-06
- **Context**: The replay harness injected only a first-partition fault, leaving
  later resumable checkpoints unexercised.
- **Decision**: Add a bounded fault matrix over fresh SQLite databases for every
  non-terminal partition checkpoint, reusing the public replay profile and
  verifier rather than adding a second matching implementation.
- **Verification**: The focused replay/adversarial suite passes 10/10; fault
  points 1, 2, and 3 all preserve the baseline digest, parity, mutation guard,
  zero duplicate effects, and terminal queue state.
- **Boundary**: This is synthetic SQLite failure-injection evidence only. It
  does not establish PostgreSQL parity, distributed queue failure, mutation
  tool score, throughput, or production reliability.
- **Reversibility**: Remove the harness, test, ADR, manifest entry, and
  evidence; no migration or persisted-data rollback is required.

### D-317: Repeat durable-job load in isolated SQLite soak iterations

- **Date**: 2026-08-06
- **Context**: Durable-job load, cancellation, retry, backpressure, and
  PostgreSQL correctness slices existed, but there was no retained repeated-run
  soak artifact checking digest stability and queue drain across iterations.
- **Decision**: Add a bounded `DurableJobSoakProfile` and manifest that reuses
  the public load harness against a fresh SQLite database per iteration. Require
  exact declared job/effect counts, one stable effect digest, zero duplicate
  effects, and zero queued/running residue; retain runtime and peak memory as
  observations without using them for capacity claims.
- **Verification**: Focused soak/load tests pass, including manifest replay and
  source-distribution membership.
- **Boundary**: One-host SQLite repetition only; PostgreSQL/distributed soak,
  queue HA, host-loss recovery, throughput/capacity/SLO, and production
  readiness remain unverified.
- **Reversibility**: Remove the profile, tests, ADR, manifest entry, and
  evidence; no migration or persisted-data rollback is required.

### D-318: Keep the live server-boundaries dependency profile complete

- **Date**: 2026-08-06
- **Context**: The server-boundaries job selects metrics, WebAuthn/MFA,
  federation, connector, backup, and PostgreSQL tests, but its install command
  named only a subset of extras. That allows hosted collection/runtime drift and
  can reproduce missing optional-module failures.
- **Decision**: Use the universal locked `--all-extras` resolution in that job,
  and add a workflow contract test so a partial install cannot return silently.
- **Verification**: The workflow contract test passes locally; the lock already
  contains the declared optional packages. A fresh hosted run remains required.
- **Boundary**: This fixes dependency-profile completeness only. It does not
  prove hosted PostgreSQL backup/restore, live providers, security provenance,
  or production readiness.
- **Reversibility**: Restore the prior command and remove the contract test,
  ADR, manifest entry, and evidence; no application migration is involved.

### D-321: Keep server identity close fixtures aligned with intercompany replay schemas

- **Date**: 2026-08-06
- **Context**: Consolidation-close replay verification queries the immutable
  intercompany artifact and close-link tables during every run transition. The
  server-identity PostgreSQL fixture installed only part of the migration
  dependency graph, so a fresh database exposed missing domain, approval,
  service-account, scope, intercompany, or audit-ledger relations as generic
  503 responses.
- **Decision**: Install the shared dependency schemas in migration order and
  grant the non-privileged application role every route table plus the domain
  audit ledger. Keep the runtime repository contract unchanged and fix fixture
  drift rather than weakening replay verification or treating absent evidence
  as empty evidence.
- **Verification**: A newly created disposable PostgreSQL 16.14 database passes
  the live server-identity API test with a non-superuser, non-BYPASSRLS role; the
  configured service passes metrics parity and Alembic upgrade tests. The
  missing-relation and permission failures were reproduced in PostgreSQL logs
  before the fixture correction.
- **Boundary**: Test-fixture/schema-contract closure only; statutory close,
  live providers/write-back, distributed scale, independent HA/DR, and production
  readiness remain open.

- **Reversibility**: Remove the two schema installs, grants, ADR, manifest entry,
  and evidence; no production migration or data rollback is required.

### D-322: Promote only bounded PostgreSQL grouped-matching runtime evidence

- **Date**: 2026-08-06
- **Context**: The PostgreSQL grouped worker, checkpoint path, and scale
  profiles existed, but their live cells were skipped when no DSN was present.
- **Decision**: Execute the existing runtime, 500-partition, and 10K-partition
  contracts against a local PostgreSQL service with a non-superuser,
  non-BYPASSRLS role. Record structural outcomes only and do not widen the
  P4-MAT-001 claim to production capacity or distributed reliability.
- **Verification**: Runtime 2/2, 500-partition 1/1, and 10K-partition 1/1
  passed; all declared work drained with zero duplicate result identities.
- **Consequence**: PostgreSQL runtime evidence is stronger and current for this
  bounded worker path. Cross-host capacity, soak/SLO behavior, provider I/O,
  and the full advanced-matching exit remain open.
- **Reversibility**: Documentation-only; remove ADR, manifest, backlog, state,
  and evidence entries without changing runtime or data.

### D-323: Keep unreachable public egress explicitly blocked

- **Date**: 2026-08-06
- **Context**: The opt-in World Bank public connector test reached the pinned
  HTTPS transport but the current host returned WinError 10051.
- **Decision**: Preserve the failure as a blocked gate. Do not bypass pinning,
  replace the live call with a fixture, or promote schema/digest assertions as
  public-network evidence.
- **Consequence**: The connector remains synthetic/read-only evidence until an
  authorized egress-enabled rerun succeeds; P4-CON-001 remains open.
- **Reversibility**: Re-run the unchanged test with explicit egress and replace
  only the blocked evidence after a successful real response.

### D-324: Preserve duplicate rows while publishing bounded canonical evidence

- **Date**: 2026-08-06
- **Context**: Duplicate occurrence lineage existed inside the legacy matcher,
  but callers could not request a standalone, versioned duplicate-evidence
  operation. Silent de-duplication would destroy auditability and malformed
  numeric values must not be normalized into a financial result.
- **Decision**: Add `bounded-duplicate-detection@1.0.0` as an experimental
  strategy. It groups each side by a canonical projection, normalizes exact
  Decimal amounts, assigns stable occurrence ordinals, exposes duplicate and
  unique groups, and refuses binary floats, repeated identities, and ceiling
  breaches. It never mutates, deletes, or merges records.
- **Verification**: Focused strategy/domain and matching-contract tests report
  27 passed; Ruff and Mypy pass for the new surface; architecture and source
  distribution manifest entries agree under ADR 0389.
- **Boundary**: Exact duplicate evidence only. Near-duplicate similarity,
  probabilistic matching, fraud detection, provider interoperability,
  PostgreSQL scale, and production readiness remain open.
- **Reversibility**: Remove the strategy, domain module, test, architecture
  entry, manifest entry, ADR, and execution evidence; no migration is needed.

### D-325: Make duplicate evidence selectable in Reconciliation-as-Code

- **Date**: 2026-08-06
- **Context**: The bounded duplicate strategy was executable through its direct
  adapter but not selectable by a versioned RAC document or its embedded golden
  tests. Treating duplicate groups as ordinary matches would make the evidence
  contract ambiguous.
- **Decision**: Add the explicit `duplicate_detection` strategy type,
  `duplicate-detection` mode, and bounded strategy identity to RAC v1. Dispatch
  through the existing strategy and add `duplicate_group_count` as an additive
  expected/actual field. Duplicate groups remain evidence, never matches or
  autonomous actions.
- **Verification**: The dedicated RAC golden/schema suite and Phase 2
  compatibility suite report 10 passed; Ruff and Mypy pass under ADR 0390.
- **Boundary**: Declaration and simulation only; no approval, merge, delete,
  fraud classification, provider interoperability, PostgreSQL execution, or
  production claim.
- **Reversibility**: Remove the additive contract/schema fields, dispatch
  branch, tests, ADR, manifest entry, and evidence without a migration.

### D-326: Prove Redis-backed policy-cache invalidation across independent clients

- **Date**: 2026-08-06
- **Context**: Unit tests covered the shared-generation protocol, while the
  existing live Redis drill only proved integer generation visibility and did
  not exercise the actual `PolicyDecisionCache` boundary.
- **Decision**: Extend the disposable live drill with two independent cache
  instances and synthetic evaluator call counters. A global invalidation in
  one instance must advance the Redis generation and force a fresh evaluation
  in the other instance; only the generation integer is stored in Redis.
- **Verification**: The current local Redis report records
  `policy_cache_cross_process_invalidation: true` alongside tenant isolation,
  hashed-token storage, shared generation, and cleanup. Historical reports
  remain readable under the v1 observation compatibility rule.
- **Boundary**: Single-node synthetic optimization evidence only; Redis
  replication/failover, federation, full route/job/export adoption, and
  production IAM assurance remain open.
- **Reversibility**: Remove the drill branch, optional report field/schema
  compatibility, tests, ADR, manifest entry, and execution evidence.

### D-327: Make pg_dump resolve the configured PostgreSQL service

- **Date**: 2026-08-06
- **Context**: The backup adapter supplied `service=<name>` as a positional
  `pg_dump` database argument. The PostgreSQL client then attempted the local
  socket instead of resolving the service file, leaving no dump artifact.
- **Decision**: Pass `service=<name>` via the explicit `--dbname` option for
  the primary and portable-file retry commands, preserving the validated
  service name and no-shell argv boundary.
- **Verification**: The focused backup suite reports 11 passed with its
  declared disposable-service skip. A PostgreSQL 16 Alpine client generated a
  non-empty 5,168,214-byte custom dump using the corrected service-file argv;
  the prior positional form failed against the local socket.
- **Boundary**: Command-construction evidence only; hosted encrypted
  backup/restore, native-tool availability, key custody, cross-site recovery,
  and production RPO/RTO remain open.
- **Reversibility**: Restore the two argv tuples and focused assertion; no
  migration or persisted data rollback is required.

### D-328: Keep the consolidation impairment bridge non-posting

- **Date**: 2026-08-06
- **Context**: The consolidation workstream needed a reproducible impairment
  calculation boundary without silently deciding valuation methodology,
  cash-generating-unit policy, tax, or statutory journal treatment.
- **Decision**: Add `consolidation-impairment-bridge-v1` as a pure exact
  Decimal/Money artifact. Operators provide approved carrying and recoverable
  amounts; the bridge exposes per-unit loss/headroom/status, aggregate totals,
  source digests, maker-checker attribution, canonical replay, and
  `posted: false`. The CLI accepts only the closed request contract and
  performs no database mutation or network call.
- **Verification**: `tests/test_consolidation_impairment.py` reports 5 passed;
  the JSON Schema, registry, Ruff, and package manifest are aligned.
- **Boundary**: This is not a statutory impairment engine, valuation opinion,
  tax calculation, journal posting, ERP write-back, or production assurance.
- **Reversibility**: Remove the domain/CLI/schema/test/registry/ADR/manifest
  and execution records; no migration or persisted-data rollback is required.

### D-329: Persist impairment evidence under a separate PostgreSQL append-only boundary

- **Date**: 2026-08-06
- **Context**: The deterministic impairment artifact needs the same tenant,
  maker-checker, audit, and replay guarantees as the other consolidation
  evidence without silently becoming a posting engine.
- **Decision**: Add migration `0066_pg_impairment`, a backend-neutral
  `ConsolidationImpairmentApplicationService`, and a forced-RLS,
  append-only `PostgresConsolidationImpairmentRepository`. Store canonical
  request/result JSONB, recompute both digests, make retries idempotent by
  tenant/result digest, and emit a creation audit event. Keep the live runtime
  test capability-gated and record a skip as a skip.
- **Verification**: Static schema/migration contracts pass; the runtime test is
  prepared for the disposable non-superuser PostgreSQL gate. The current local
  environment has no `RECONFORGE_TEST_POSTGRES_DSN`, so no live runtime pass is
  claimed.
- **Boundary**: The adapter refuses posted artifacts and update/delete paths;
  it does not decide valuation methodology, CGU scope, tax, statutory
  recognition, journal posting, ERP/bank write-back, restore, HA/DR, or
  production readiness.
- **Reversibility**: The migration downgrade refuses non-empty evidence before
  dropping the trigger/table; removing the adapter and migration is safe only
  after an explicit empty-table downgrade.

### D-330: Bind impairment evidence to the PostgreSQL close evidence bundle

- **Date**: 2026-08-06
- **Context**: A separately persisted impairment artifact must be attributable
  to the exact close worksheet that consumed it; a tenant-wide artifact lookup
  alone is not sufficient lineage.
- **Decision**: Add migration `0067_pg_close_impairment_links` with forced RLS,
  append-only triggers, run/artifact/entity uniqueness, and an immutable link
  digest. Validate the replay-verified artifact's business period, reporting
  currency, and entity against the worksheet; require a linker independent of
  the run preparer; and include sorted result digests in the close bundle.
  Expose the operation only through the PostgreSQL server API with strict IDs
  and `finance_core.manage` authorization.
- **Verification**: Static migration/schema contracts, close-bundle digest
  coverage, and injected server-scope route tests pass. The live PostgreSQL
  link runtime remains capability-gated and is not claimed without its DSN.
- **Boundary**: This is evidence provenance, not valuation methodology,
  statutory impairment recognition, journal posting, ERP write-back, HA/DR, or
  production readiness.
- **Reversibility**: The migration downgrade refuses non-empty links before
  dropping the trigger/function/index/table; the bundle reader preserves
  compatibility with older payloads that lack the additive digest field.

### D-331: Bind deferred-tax evidence to the PostgreSQL close evidence bundle

- **Date**: 2026-08-06
- **Context**: Deferred-tax evidence is a non-posting acquisition bridge, but
  a close run must identify the exact tax result reviewed for its worksheet.
- **Decision**: Add migration `0068_pg_close_deferred_tax_links` with forced
  RLS, append-only triggers, run/artifact/entity uniqueness, and an immutable
  link digest. Replay-verify the artifact, bind business period, currency, and
  subsidiary entity to the worksheet, require a linker independent of the run
  preparer, and include sorted result digests in the close bundle. Expose the
  link only through the PostgreSQL server API with strict IDs and
  `finance_core.manage` authorization.
- **Verification**: Static migration/schema contracts, close-bundle digest
  coverage, and injected server-scope route tests pass. The live PostgreSQL
  link runtime remains capability-gated and is not claimed without its DSN.
- **Boundary**: This is evidence provenance, not statutory tax recognition,
  valuation, journal posting, ERP write-back, HA/DR, or production readiness.
- **Reversibility**: The migration downgrade refuses non-empty links before
  dropping the trigger/function/index/table; old close bundles remain readable
  through the additive-field compatibility reader.

### D-332: Bind PPA evidence to the PostgreSQL close evidence bundle

- **Date**: 2026-08-06
- **Context**: A deterministic, non-posting acquisition PPA artifact must be
  attributable to the exact close worksheet that consumed it; a tenant-wide
  artifact lookup does not prove period, currency, or entity lineage.
- **Decision**: Add migration `0069_pg_close_ppa_links` with forced RLS,
  append-only triggers, run/artifact/entity uniqueness, and an immutable link
  digest. Replay-verify the PPA artifact, bind period/currency/subsidiary
  entity to the worksheet, require a linker independent of the run preparer,
  and include sorted result digests in the close bundle. Expose the link only
  through the PostgreSQL server API with strict IDs and
  `finance_core.manage` authorization.
- **Verification**: Static schema/migration contracts, close-bundle digest
  coverage, focused API/authorization contracts, and the package manifest
  alignment pass. The live PostgreSQL link runtime remains capability-gated
  without `RECONFORGE_TEST_POSTGRES_DSN`.
- **Boundary**: This is purchase-accounting evidence provenance, not valuation
  policy, statutory recognition, goodwill approval, journal posting, ERP
  write-back, HA/DR, or production readiness.
- **Reversibility**: The migration downgrade refuses non-empty links before
  dropping the trigger/function/index/table; old close bundles remain readable
  through the additive-field compatibility reader.

### D-333: Persist ownership-change proposals as non-posting PostgreSQL evidence

- **Date**: 2026-08-06
- **Context**: The ownership-change adjustment domain produces an exact,
  policy-neutral three-line proposal but had no tenant-RLS persistence or
  replay boundary.
- **Decision**: Add migration `0070_pg_ownership_change`, a backend-neutral
  application service, and a forced-RLS append-only PostgreSQL repository.
  Reconstruct the typed request from canonical JSONB, recompute both digests,
  require distinct identity actors, make result retries idempotent, emit an
  audit creation event, and refuse posted/update/delete paths.
- **Verification**: Static schema/migration contracts and deterministic
  repository verification pass. The live PostgreSQL runtime remains
  capability-gated without `RECONFORGE_TEST_POSTGRES_DSN`.
- **Boundary**: This does not determine statutory ownership-change treatment,
  goodwill/tax policy, legal-book entries, journal posting, provider
  write-back, or production readiness.
- **Reversibility**: The downgrade refuses non-empty artifacts before dropping
  the trigger/function/index/table.

### D-334: Bind ownership-change evidence to the PostgreSQL close bundle

- **Date**: 2026-08-06
- **Context**: A tenant-scoped ownership-change artifact must be attributable
  to the exact close worksheet that consumed it.
- **Decision**: Add migration `0071_pg_close_ownchg_links` with forced RLS,
  append-only triggers, run/artifact/entity uniqueness, and an immutable link
  digest. Replay-verify the artifact, bind period/currency/subsidiary entity
  to the worksheet, require a linker independent of the run preparer, and
  include sorted result digests in the close bundle. Expose strict
  `finance_core.manage`-protected server API linking while preserving old
  bundle readability through an additive field.
- **Verification**: Static migration/schema, bundle, focused API, and
  authorization contracts pass. The live PostgreSQL link runtime remains
  capability-gated without its DSN.
- **Boundary**: This is evidence provenance, not statutory accounting,
  journal posting, ERP/bank write-back, HA/DR, or production readiness.
- **Reversibility**: The downgrade refuses non-empty links before dropping the
  trigger/function/index/table.

### D-375: Expose ownership-change preparation through a local non-posting CLI

- **Date**: 2026-08-06
- **Context**: The deterministic ownership-change domain contract and its
  PostgreSQL evidence boundary were not available through one first-party
  local operator command.
- **Decision**: Add `reconforge consolidation ownership-change` with a closed
  JSON request contract, exact Decimal percentage parsing, canonical Money
  parsing, and a digest-bound `posted: false` JSON result. Reject unknown
  fields and invalid lineage/actor/currency inputs through the shared
  fail-closed CLI path. Do not persist, post, contact providers, or mutate
  inputs from this command.
- **Verification**: Focused CLI/domain tests cover balanced output, digest
  presence, output-file handling, and unknown-field rejection; ADR 0401 and
  the test are included in the source distribution.
- **Boundary**: Local synthetic operator evidence only; no statutory
  ownership-change treatment, journal posting, ERP/bank write-back, live
  PostgreSQL runtime, HA/DR, or production readiness claim.
- **Reversibility**: Remove the command, focused tests, manifest entries, and
  ADR; underlying domain and PostgreSQL contracts remain compatible.

### D-376: Exercise the ERP reference connector through the governed HTTPS sandbox

- **Date**: 2026-08-06
- **Context**: The ERP-shaped connector had injected transport/schema tests but
  no local proof that its real pinned HTTPS composition, retry, cursor, and
  secret-reference boundaries worked together.
- **Decision**: Add an optional `expected_entity_code` post-response guard and
  a disposable TLS sandbox test using the actual pinned GET transport and
  network executor. The test injects only a short-lived synthetic certificate,
  a public-address resolver seam, and a transient 503 before the valid page.
- **Verification**: ERP, REST, network, and SDK focused tests pass 39/39;
  canonical digest, idempotency/cursor headers, entity mismatch refusal,
  address pinning, retry bounds, and secret non-disclosure are asserted.
- **Boundary**: Loopback/provider-neutral evidence only; no live ERP vendor,
  vault/TLS operations, provider-version certification, posting, write-back,
  HA/DR, or production readiness claim follows.
- **Reversibility**: Remove the optional guard, sandbox test, ADR, docs, and
  manifest entry; existing callers that omit the guard remain compatible.

### D-377: Exercise the payment-statement reference connector through the governed HTTPS sandbox

- **Date**: 2026-08-06
- **Context**: The payment-statement connector had injected schema/transport
  tests but no local proof that its real pinned HTTPS composition, retry, cursor,
  and secret-reference boundaries worked together.
- **Decision**: Add an optional `expected_account_id` post-response guard and a
  disposable TLS sandbox test using the actual pinned GET transport and network
  executor.
- **Verification**: Focused payment-statement, ERP, REST, network, and SDK
  contracts require the account mismatch refusal, retry bound,
  cursor/idempotency propagation, address pinning, canonical digest, and secret
  non-disclosure.
- **Boundary**: Loopback/provider-neutral evidence only; no live bank vendor,
  licensed dialect, settlement, payment initiation, write-back, HA/DR, or
  production readiness claim follows.
- **Reversibility**: Remove the optional guard, sandbox test, ADR, docs, and
  manifest entry; existing callers that omit the guard remain compatible.

### D-378: Verify matching strategy envelopes before they cross a boundary

- **Date**: 2026-08-06
- **Context**: Strategy adapters calculate manifest, input, and output
  digests, but there was no shared fail-closed check before a result reached a
  worker, persistence boundary, or evidence consumer.
- **Decision**: Add `MatchingStrategyResult.verify_against` and invoke it from
  the indexed, grouped, carry-forward, duplicate-detection, and reversal
  adapters. The verifier recomputes the canonical input and result digests and
  rejects manifest, input, or output tampering.
- **Verification**: Focused strategy, grouped-worker, sequential-worker,
  carry-forward, reversal, and duplicate suites pass; adversarial tests cover
  all three mismatch classes; ADR 0404 and the strategy contract test are in
  the source-distribution manifest.
- **Boundary**: This is deterministic result-envelope integrity only. It does
  not establish PostgreSQL capacity, distributed consensus, live providers,
  independent algorithm validation, or production readiness.
- **Reversibility**: Remove the verifier calls, focused tests, ADR, and manifest
  entry without a data migration; the existing result shape remains unchanged.

### D-379: Expose scoped control-plane exports only through authenticated PostgreSQL server mode

- **Date**: 2026-08-06
- **Context**: The deterministic scoped-export repository already enforced
  PostgreSQL row-level hierarchy bounds, but no API surface exposed its
  snapshot. A route must not turn local SQLite or an unauthenticated request
  into export authority.
- **Decision**: Add `GET /api/v1/exports/scoped` as a read-only server-profile
  boundary. It requires `reports.read`, derives tenant/workspace/organization/
  legal-entity scope from the authenticated principal, re-evaluates the
  selected tenant/workspace/entity centrally, and delegates to the RLS-backed
  PostgreSQL repository. The response includes the canonical artifact, digest,
  byte size, and explicit server-mode source. No SQLite fallback, object-store
  publication, presigned URL, or provider network call is introduced.
- **Verification**: The focused authenticated route test proves bearer
  authentication, hierarchy propagation, central permission re-evaluation,
  deterministic digest, closed response shape, and server-only fail-closed
  behavior. The authorization inventory now contains 246 routes with digest
  `3c2691031c4fbf406b6426d0ef684d705337a1ee4910c49488092dca7a7e1745`.
- **Boundary**: This is bounded API composition only; it does not prove live
  PostgreSQL availability, distributed IAM invalidation, object-store
  durability, worker/UI adoption, HA/DR, or production readiness.
- **Reversibility**: Remove the route, helper, focused tests, ADR, docs, and
  manifest entries without a schema migration; existing repository and
  publication contracts remain unchanged.

### D-380: Carry workspace scope through PostgreSQL reconciliation workers

- **Date**: 2026-08-06
- **Context**: The reconciliation worker had an optional central service-account
  policy but claimed and persisted runs in tenant-only transactions. Workspace
  attribution and RLS existed, so processing a workspace run required an
  explicit, auditable scope contract rather than an implicit widening.
- **Decision**: Preserve the one-argument tenant supplier for unscoped legacy
  runs and add a three-argument `(tenant, workspace, entity)` supplier for
  scoped processing. Discovery reads persisted workspace attribution only after
  tenant authorization; claim SQL requires either the requested workspace or a
  NULL workspace. Every subsequent worker transaction carries the same
  workspace GUC. Entity is deliberately `None` because reconciliation runs do
  not yet have an authoritative entity column.
- **Verification**: The focused worker suite proves exact policy context,
  workspace GUC propagation, scoped completion, and fail-closed rejection of a
  legacy tenant-only supplier. The full regression and package gate passes
  after the change.
- **Boundary**: This is one worker lane, not universal IAM. Scheduler/outbox,
  export/UI, federation, distributed invalidation, entity attribution, live
  PostgreSQL, scale, HA/DR, and production readiness remain open.
- **Reversibility**: Remove the optional supplier, attribution lookup, claim
  predicate, transaction parameters, tests, and ADR without rewriting stored
  runs; existing tenant-only callers remain compatible.

### D-381: Carry organization and legal-entity scope through PostgreSQL reconciliation workers

- **Date**: 2026-08-06
- **Context**: The workspace-scoped worker lane still had no authoritative
  organization or legal-entity attribution. A workspace policy decision could
  therefore process multiple entities unless the persisted run and every
  transaction carried the same hierarchy.
- **Decision**: Migration `0072_pg_recon_entity_scope` adds nullable
  `organization_id` and `legal_entity_id` columns with tenant-safe foreign
  keys, composite lookup indexing, and RLS predicates. Discovery reads the
  immutable workspace/organization/entity tuple; claim SQL requires exact
  supplied values or NULL for legacy runs; and the worker passes the tuple to
  every transaction phase. Entity processing requires workspace and
  organization scope before database I/O; tenant-only and workspace-only
  callers remain compatible.
- **Verification**: The focused reconciliation, persisted-JSON, and Alembic
  suite passes 66 tests with two declared live-PostgreSQL skips. The entity
  contract asserts exact policy context, all three GUC values, claim SQL
  predicates/parameters, scoped completion, and missing-workspace rejection.
- **Boundary**: This closes one PostgreSQL reconciliation worker lane only.
  Universal worker/export/UI adoption, federation, distributed policy
  invalidation, live providers, scale, HA/DR, and production IAM assurance
  remain open.
- **Reversibility**: Downgrade removes only the organization/entity columns,
  index, foreign keys, and entity-aware policy; legacy tenant/workspace
  behavior remains available.

### D-382: Carry exact scope through PostgreSQL scheduler lanes

- **Date**: 2026-08-06
- **Context**: Scheduler rows already stored workspace and generic entity
  attribution, but the worker authorized and claimed due schedules at tenant
  scope. This left a widening path for a configured service identity.
- **Decision**: Add an optional deterministic lane supplier and scope-aware
  policy supplier. A scoped lane is authorized before connection access, then
  workspace/entity predicates are applied to the PostgreSQL `FOR UPDATE
  SKIP LOCKED` query and retained for all schedule dispatch side effects.
  Tenant-only callers remain compatible; entity lanes require workspace.
- **Verification**: Scoped worker tests pass exact policy, stable lane,
  pre-connection rejection, and application/repository propagation checks;
  the existing live PostgreSQL scheduler test remains capability-gated.
- **Boundary**: Scheduler only. The transactional outbox, universal worker
  surfaces, federation, distributed invalidation, live providers, scale,
  HA/DR, and production IAM assurance remain open.
- **Reversibility**: Remove the optional suppliers, filter parameters, tests,
  ADR, and manifest entry without changing stored schedules.

### D-383: Carry exact hierarchy scope through PostgreSQL transactional outbox delivery

- **Date**: 2026-08-06
- **Context**: The transactional outbox had tenant RLS and atomic leasing, but
  a hosted publisher could claim events from sibling workspaces or legal
  entities within the same tenant. Scheduler and reconciliation lanes already
  established the required hierarchy boundary.
- **Decision**: Migration `0073_pg_outbox_scope` adds nullable workspace,
  organization, and legal-entity attribution with transaction-local defaults,
  a pending lookup index, and explicit hierarchy RLS. Repository claims bind
  every supplied dimension and return attribution. The worker accepts a
  deterministic four-part lane, authorizes it before connection access, and
  restores the same scope for claim, publish, and failure transitions. Entity
  lanes require organization; an attributed event that does not match a
  supplied lane fails closed. Tenant-only callers remain compatible.
- **Verification**: Focused outbox/worker/migration/policy tests pass, including
  exact claim parameters, policy-before-connection, GUC propagation, and
  invalid hierarchy refusal. Full regression and package evidence is recorded
  separately as E-539 after the final gates.
- **Boundary**: This is a PostgreSQL outbox scope contract, not proof of live
  provider delivery, distributed queue fairness, HA/DR, throughput, or
  production readiness.
- **Reversibility**: Downgrade removes the scope index and columns and restores
  the tenant-only policy; optional worker/repository scope can be removed
  without rewriting legacy tenant-scoped events.

### D-384: Treat organization as a first-class policy scope

- **Date**: 2026-08-06
- **Context**: PostgreSQL outbox lanes now carry organization attribution, but
  the central policy context and allowed-only cache previously modeled only
  tenant/workspace/entity. A workspace/entity policy callback could therefore
  authorize an organization lane without evaluating that dimension.
- **Decision**: Add optional `organization_id` and
  `authorized_organization_ids` to `PolicyEvaluationContext` and central ABAC
  checks. Include organization in the policy-cache entry and provide targeted
  organization invalidation. Organization-scoped workers must use an explicit
  four-argument hierarchy policy supplier; legacy three-argument suppliers
  fail closed when an organization is requested.
- **Verification**: Policy, cache, and PostgreSQL outbox contracts prove
  organization deny-by-default, cache invalidation, exact hierarchy context,
  and pre-connection rejection of an incompatible supplier. Existing
  tenant/workspace callers remain compatible.
- **Boundary**: This closes a reusable policy primitive only; federation,
  route-wide adoption, distributed invalidation, live IAM providers, and
  production readiness remain open.
- **Reversibility**: Remove the optional context field, cache dimension,
  supplier, and tests without changing stored authorization records.

### D-385: Bind PostgreSQL outbox consumer receipts to event hierarchy

- **Date**: 2026-08-06
- **Context**: Publisher events now carry hierarchy attribution, while the
  exactly-once consumer receipt table and transaction remained tenant-only.
  A consumer could therefore recognize a receipt without proving the event
  belonged to its requested business lane.
- **Decision**: Migration `0074_pg_outbox_consumer_scope` adds nullable
  workspace/organization/legal-entity columns, transaction-local defaults,
  scope indexing, and explicit RLS. `PostgresOutboxConsumer.apply` accepts the
  optional hierarchy, restores it through the tenant boundary, verifies the
  source event attribution before invoking the effect, and writes immutable
  receipts with the same scope. Downgrade refuses to discard non-empty receipt
  rows.
- **Verification**: Consumer schema, migration, validation, and outbox
  contracts pass; legacy tenant-only events and calls remain compatible. The
  live PostgreSQL consumer drill is still capability-gated.
- **Boundary**: This is a database idempotency boundary only; it is not
  external broker exactly-once delivery, provider acknowledgement, throughput,
  HA/DR, or production readiness.
- **Reversibility**: With no receipt rows, downgrade removes only the additive
  scope columns/index and restores tenant-only RLS.

### D-386: Return persisted hierarchy on consumer receipt envelopes

- **Date**: 2026-08-06
- **Context**: The scoped consumer receipt stored hierarchy attribution, but
  the returned value exposed only tenant, event, digest, and status fields.
- **Decision**: Add optional workspace, organization, and legal-entity fields
  to `PostgresOutboxConsumerReceipt`; populate them for both initial apply and
  duplicate replay without changing existing positional field order.
- **Verification**: Focused consumer tests, full 2,638-test regression, Ruff,
  Mypy, Bandit, pip-audit, build, and diff-check pass. Live PostgreSQL remains
  capability-gated.
- **Boundary**: This improves provenance at the database idempotency boundary;
  it is not external broker exactly-once, provider acknowledgement, HA/DR, or
  production evidence.

### D-387: Bind server policy re-evaluation to organization scope

- **Date**: 2026-08-07
- **Context**: Central server policy re-evaluation carried tenant/workspace
  and optional entity dimensions but could omit the organization header.
- **Decision**: Add optional organization scope to the helper and context;
  derive it from `X-ReconForge-Organization` for workspace requests and fail
  closed on explicit/header mismatch before policy evaluation.
- **Verification**: Focused execution-scope tests pass 21/21; the full 2,638
  test regression, Ruff, Mypy, Bandit, pip-audit, build, and diff-check pass;
  ADR 0411 is packaged.
- **Boundary**: This is a central request-policy primitive only; universal
  route/job/export/UI adoption, federation, live IAM, HA/DR, and production
  readiness remain open.

### D-388: Keep hosted security findings separated from local policy evidence

- **Date**: 2026-08-07
- **Context**: The supplied hosted security run reported a Gitleaks finding and
  therefore failed its required context, while the current local tree needed
  an independently reproducible policy check.
- **Decision**: Record local supply-chain validator and clean Gitleaks results
  as local evidence only; do not downgrade the hosted failure or claim release
  approval until hosted history/tree, npm audit, provenance, and required-context
  jobs rerun successfully.
- **Verification**: The local validator returns `status=valid`, zero active
  exceptions, zero npm integrity gaps, and no pip/npm findings.
- **Boundary**: Local evidence cannot substitute for hosted security or release
  attestation.

### D-389: Carry organization scope through durable-job lanes

- **Date**: 2026-08-07
- **Context**: Durable jobs had tenant/workspace/entity lanes while central
  policy and other PostgreSQL workers also authorized organization scope.
- **Decision**: Add optional organization attribution to the aggregate,
  submission, scheduler lane, worker claim, SQLite migration 33, and
  PostgreSQL revision 0075. Queue bounds, idempotent replay, backup import /
  export, claim filters, transaction-local settings, and RLS use the same
  hierarchy; legacy tenant/workspace jobs remain compatible.
- **Verification**: Focused durable-job, backup/restore, scheduler, migration
  chain, and package tests pass. Full regression is tracked by E-550; live
  PostgreSQL remains capability-gated.
- **Boundary**: This is a durable-job isolation/provenance primitive, not
  distributed queue fairness, provider IAM, HA/DR, or production readiness.
- **Reversibility**: PostgreSQL downgrade removes the additive column/index and
  restores the prior policy. SQLite rollback requires a pre-migration backup
  rather than an implicit destructive downgrade.

### D-390: Preserve legacy durable-job backups across additive organization scope

- **Date**: 2026-08-07
- **Context**: SQLite durable jobs gained a non-null organization scope in
  migration 33, while existing schema-version-32 backup documents do not carry
  that field.
- **Decision**: Keep restore column selection additive and rely on the declared
  SQLite default for the missing legacy field; do not rewrite historical backup
  documents or invent an organization identity.
- **Verification**: A schema-version-32 backup regression restores, upgrades,
  and verifies an empty organization scope; the complete backup/export suite
  passes.
- **Boundary**: This covers local SQLite backup compatibility only, not native
  PostgreSQL restore, cross-site disaster recovery, or production RPO/RTO.

### D-391: Keep sequential RAC adapters bounded and non-posting

- **Date**: 2026-08-07
- **Context**: Tested carry-forward, sequence-window, and reversal-pairing
  strategies were available to the PostgreSQL worker but could not be declared
  by Reconciliation-as-Code.
- **Decision**: Add only explicit strategy-type/mode mappings to the existing
  bounded adapters. Reuse their exact Decimal, partition, date-window,
  candidate/search ceilings, ambiguity, and digest contracts; expose no new
  posting or provider path.
- **Verification**: The closed RAC schema and 45-test focused gate pass,
  including Golden allocation/residual and explicit reversal-link cases.
- **Boundary**: Declaration and local simulation only; PostgreSQL runtime,
  cross-engine parity, large-scale performance, settlement posting, and
  provider write-back remain unverified.

### D-392: Bind reconciliation reads to the same hierarchy as writes

- **Date**: 2026-08-07
- **Context**: Reconciliation read dependencies checked global permissions, but
  only mutations invoked central server-scope re-evaluation before PostgreSQL
  access.
- **Decision**: Add an any-of read guard to run listing, detail, and child reads;
  pass optional organization/legal-entity scope to both read and mutation
  guards. Preserve local SQLite compatibility and the existing transaction RLS
  boundary.
- **Verification**: The route fixture passes 14 tests and asserts exact
  hierarchy values for all eleven read/write calls; Ruff/Mypy pass.
- **Boundary**: This is one reconciliation route family, not complete API/job/
  export/UI IAM, federation, distributed revocation, HA/DR, or production IAM.

### D-393: Bind evidence policy checks to the full execution hierarchy

- **Date**: 2026-08-07
- **Context**: Evidence PostgreSQL transactions already restored organization and
  legal-entity scope, while route policy checks stopped at tenant/workspace.
- **Decision**: Forward optional organization and legal-entity identifiers to
  all evidence read, manage, and verify policy checks without changing local
  SQLite behavior or the sensitive drill-down permission.
- **Verification**: Evidence and server-scope contracts pass 10 tests with exact
  four-part scope assertions; Ruff/Mypy pass and ADR 0415 is packaged.
- **Boundary**: This is one route family, not complete API/job/export/UI IAM,
  federation, distributed invalidation, live providers, HA/DR, or production IAM.

### D-394: Bind intercompany policy checks to the full execution hierarchy

- **Date**: 2026-08-07
- **Context**: Intercompany PostgreSQL RLS restored organization/entity scope,
  but prepare/read ABAC calls supplied only tenant/workspace.
- **Decision**: Forward organization and legal-entity scope to both route policy
  checks while preserving workspace payload validation and non-posting behavior.
- **Verification**: Focused intercompany/reconciliation/evidence contracts pass
  5 tests with exact hierarchy assertions; Ruff/Mypy pass and ADR 0416 is packaged.
- **Boundary**: One route family only; posting, providers/write-back, distributed
  IAM, HA/DR, and production readiness remain open.

### D-395: Normalize optional hierarchy for tenant-scoped server policy calls

- **Date**: 2026-08-07
- **Context**: Tenant-only evidence routes passed `workspace_id=None`, and the
  central policy helper therefore skipped organization/legal-entity headers.
- **Decision**: Bind and validate optional organization/entity headers for every
  server policy call; reject explicit/header mismatches and entity scopes with
  no organization parent.
- **Verification**: Execution-scope plus PPA/impairment/deferred-tax contracts
  pass 23 focused tests; Ruff/Mypy pass and ADR 0417 is packaged.
- **Boundary**: Tenant-only persistence remains tenant-only; this is not
  multi-entity row isolation, complete IAM, federation, HA/DR, or production readiness.

### D-396: Persist hierarchy attribution for PostgreSQL PPA evidence

- **Date**: 2026-08-07
- **Context**: PPA central ABAC accepted organization/entity scope, but the
  immutable PostgreSQL table retained only tenant identity.
- **Decision**: Add nullable hierarchy columns, transaction defaults, foreign
  keys, RLS predicates, scoped digest uniqueness, and optional repository/API
  scope. Preserve tenant-only legacy identity and make scoped reads fail closed
  against NULL-attributed legacy rows.
- **Verification**: Static migration, repository, API, replay, and package
  contracts pass; live PostgreSQL hierarchy isolation is still required.
- **Boundary**: This closes PPA evidence storage only; impairment/deferred-tax
  tables, statutory posting, providers/write-back, HA/DR, and production IAM remain open.

### D-397: Persist hierarchy attribution for impairment and deferred-tax evidence

- **Date**: 2026-08-07
- **Context**: PPA hierarchy storage was closed, but the adjacent impairment and
  deferred-tax tables still exposed only tenant RLS.
- **Decision**: Add one additive migration for both tables with nullable scope,
  foreign keys, scoped digest uniqueness, hierarchy RLS, NULL-aware repository
  predicates, and server transaction propagation.
- **Verification**: Focused schema/API/repository contracts, the 2,651-test
  full regression, package build, Ruff, Mypy, and diff-check pass; declared
  external-service skips remain visible.
- **Boundary**: No live hierarchy PostgreSQL run, statutory judgment/posting,
  providers/write-back, HA/DR, or production readiness is claimed.

### D-398: Preserve hierarchy through PostgreSQL close scope resets

- **Date**: 2026-08-07
- **Context**: The authenticated close request carried four-part scope into the
  connection boundary, but repository and certification resets restored only
  the tenant GUCs.
- **Decision**: Make organization, workspace, and legal-entity constructor
  scope explicit and restore all five transaction-local settings in close and
  approval repositories; reject an entity without its organization parent.
- **Verification**: Scope-capture and invalid-parent focused contracts pass;
  the 2,653-test full regression, Ruff, Mypy, and diff-check pass; package
  build is rerun after this documentation update.
- **Boundary**: Close-table hierarchy persistence, live RLS isolation,
  statutory posting, providers/write-back, HA/DR, and production readiness
  remain open.

### D-399: Persist hierarchy attribution across PostgreSQL close tables

- **Date**: 2026-08-07
- **Context**: Close repositories restored the authenticated hierarchy, but
  close periods, runs, lifecycle rows, journal lines, and evidence links still
  stored only tenant identity at the database boundary.
- **Decision**: Add migration `0078_pg_close_scope` with nullable transactional
  organization/legal-entity attribution, tenant-safe foreign keys, hierarchy
  indexes, workspace-aware RLS for period/run rows, hierarchy RLS for all close
  records, and `UNIQUE NULLS NOT DISTINCT` scoped identities. Preserve legacy
  NULL rows and refuse rollback when attribution would be discarded.
- **Verification**: Focused close/migration contracts pass 39 tests with four
  declared live-service skips; Ruff, Mypy, and diff-check pass. Full regression
  and package evidence are tracked by E-571.
- **Boundary**: No live PostgreSQL hierarchy isolation, statutory posting,
  provider write-back, HA/DR, or production release approval is claimed.

### D-400: Refuse hierarchy-attribution loss during PostgreSQL downgrades

- **Date**: 2026-08-07
- **Context**: The downgrade paths for earlier hierarchy migrations could drop
  non-NULL scope attribution without an evidence-preserving check.
- **Decision**: Add database-side, pre-mutation guards to migrations 0072,
  0073, 0075, 0076, and 0077. A downgrade now fails closed when affected rows
  carry hierarchy attribution and retains legacy downgrade behavior only for
  empty/legacy-only tables.
- **Verification**: Static migration contracts and the full local gate must
  pass; a live PostgreSQL downgrade drill remains required before runtime
  promotion.
- **Boundary**: No live PostgreSQL downgrade, statutory accounting, provider
  write-back, HA/DR, or production readiness is claimed.

### D-401: Bound PostgreSQL server-profile connection reuse

- **Date**: 2026-08-07
- **Context**: Direct per-request connections can churn physical sockets under
  concurrent server-profile requests even when each transaction closes safely.
- **Decision**: Use the existing dependency-free pool behind a subtype-compatible
  `PostgresPooledConnectionFactory` in `create_api_app`, with default maximum
  eight connections, bounded acquisition, and registered shutdown cleanup.
- **Verification**: Focused foundation/API tests prove reuse, configuration,
  subtype compatibility, and cleanup; full regression and package gates remain
  required for closure.
- **Boundary**: This is not throughput, capacity, distributed scheduling,
  HA/DR, or production sizing evidence.

### D-402: Close the PostgreSQL metrics parity fixture dependency graph

- **Date**: 2026-08-07
- **Context**: The reported live metrics failure came from a parity fixture
  that installed metrics and domain tables but omitted tables queried by
  close, exceptions, evidence, controls, reconciliation, and matching metrics.
- **Decision**: Install those exact dependency schemas in the live parity test,
  preserving least-privilege grants and the SQLite comparison. Do not add
  production fallbacks or fabricated zero metrics.
- **Verification**: Focused/static contracts and the full local gate must pass;
  hosted PostgreSQL is the runtime verification surface.
- **Boundary**: No statutory metrics, provider, throughput, HA/DR, or
  production-readiness claim follows.

### D-403: Document fixed hierarchy SQL clauses for Bandit

- **Date**: 2026-08-07
- **Context**: Bandit B608 reported eight scoped-read compositions whose only
  dynamic fragment is a private fixed hierarchy predicate selector.
- **Decision**: Keep parameterized values and add line-level B608 rationale;
  do not disable the rule globally or accept user-controlled SQL.
- **Verification**: Full Bandit reports no failed findings; Ruff, Mypy, focused
  repository/security tests, and the current full regression remain green.
- **Boundary**: Scanner coverage only; no penetration-test or production-
  security-assurance claim follows.

### D-404: Pin the live migration-status contract to the current Alembic head

- **Date**: 2026-08-07
- **Context**: The PostgreSQL live migration test still expected status
  `0071_pg_close_ownchg_links`, while the supported linear registry and
  Alembic chain now end at `0078_pg_close_scope`.
- **Decision**: Update the live assertion to the current head. Do not weaken
  `PostgresMigrationStatusProvider` or add compatibility aliases for a stale
  test expectation.
- **Verification**: Static Alembic/operations contracts, the 2,655-test full
  local gate, Ruff, Mypy, package build, and diff-check pass; a fresh hosted
  PostgreSQL server-boundaries run is still required for runtime evidence.
- **Boundary**: This removes test drift only; it does not prove hosted
  migration, backup/restore, HA/DR, provider, or production readiness.

### D-405: Register Redis client shutdown cleanup in server profiles

- **Date**: 2026-08-07
- **Context**: PostgreSQL pool cleanup was registered on application shutdown,
  but the reusable optional Redis client was not.
- **Decision**: Register the existing lazy `RedisConnectionFactory.close`
  callback when `redis_url` is configured; keep local mode and lazy import
  behavior unchanged.
- **Verification**: The API foundation contract verifies the shutdown callback
  without opening Redis; full local gates remain required.
- **Boundary**: Lifecycle registration only; no Redis availability, HA/DR,
  throughput, or production SLO claim follows.

### D-406: Reuse reconciliation scheduler workers across cycles

- **Date**: 2026-08-07
- **Context**: The scheduler rebuilt a worker object for every polling cycle,
  creating avoidable churn when workers own bounded pools or other managed
  resources.
- **Decision**: Lazily cache one injected worker per validated stable
  `worker_id`; retain worker/factory ownership of resource cleanup and the
  existing bounded one-cycle-per-slot execution model.
- **Verification**: A two-cycle scheduler contract proves one factory call per
  slot and stable aggregate results; Ruff, Mypy, package build, diff-check, and
  full regression are required.
- **Boundary**: Resource reuse only; no throughput, fairness, capacity, soak,
  distributed scheduling, HA/DR, or production sizing claim follows.

### D-407: Add explicit reconciliation worker lifecycle close

- **Date**: 2026-08-07
- **Context**: Cached workers can retain pools or other managed resources after
  the scheduler loop stops.
- **Decision**: Add an idempotent scheduler `close()` that detaches workers and
  calls each optional worker hook once; add an idempotent worker `close()` that
  delegates to an optional connection-factory hook. Callers stop polling before
  close; concurrent-cycle coordination remains outside this boundary.
- **Verification**: Focused lifecycle tests prove cleanup, closed-cycle
  rejection, and repeated-close behavior; full static/package/regression gates
  are required.
- **Boundary**: Lifecycle correctness only; no provider, throughput, fairness,
  capacity, soak, distributed scheduling, HA/DR, or production claim follows.

### D-408: Serialize scheduler cycles with lifecycle close

- **Date**: 2026-08-07
- **Context**: A concurrent caller could otherwise close a cached worker while
  its bounded cycle callback was still running.
- **Decision**: Use a cycle lock for cycle execution and close, distinct from
  the worker-cache lock used by ThreadPool workers. A concurrent close waits
  for the active cycle without blocking worker lookup; the caller should still
  stop polling before shutdown.
- **Verification**: Focused lifecycle tests and full static/package/regression
  gates must pass.
- **Boundary**: Lifecycle serialization only; no throughput, fairness,
  capacity, soak, distributed scheduling, HA/DR, or production claim follows.

### D-409: Add safe telemetry to reconciliation scheduler cycles

- **Date**: 2026-08-07
- **Context**: Scheduler outcomes lacked per-cycle operational visibility while
  financial and tenant data must remain out of telemetry.
- **Decision**: Accept optional disabled-by-default `ObservabilityRuntime`
  instrumentation and emit only closed job/span attributes for operation,
  status, type, and result. Record failures before re-raising; never attach
  worker IDs, tenants, records, amounts, or connection details.
- **Verification**: Synthetic telemetry injection, full regression, Ruff,
  Mypy, package build, and diff-check must pass.
- **Boundary**: Instrumentation only; no collector, alerting, capacity, HA/DR,
  or production SLO claim follows.

### D-410: Bound durable-job telemetry to terminal transitions

- **Date**: 2026-08-07
- **Context**: Claim visibility did not cover worker terminal outcomes, while
  per-partition spans would impose unbounded telemetry volume.
- **Decision**: Instrument only terminal durable-job operations with the closed
  low-cardinality telemetry contract. Record persistence errors before
  re-raising; never attach job, tenant, worker, partition, or payload data.
- **Verification**: Focused observability, full regression, Ruff, Mypy, package
  build, and diff-check gates must pass.
- **Boundary**: Lifecycle instrumentation only; no collector, alerting,
  capacity, HA/DR, or production SLO claim follows.

### D-411: Keep migration status registry explicit and fail closed

- **Date**: 2026-08-07
- **Context**: Hosted diagnostics reported an unsupported PostgreSQL revision;
  local status must not silently widen the accepted migration chain.
- **Decision**: Validate against the explicit linear revision registry, reject
  unknown revisions, close resources on connected paths, and reject blank
  locators before attempting a connection.
- **Verification**: Synthetic current-head, unknown-revision, closure, and
  no-connect tests pass; hosted Alembic execution remains a separate gate.
- **Boundary**: Local provider contract only; no hosted migration or production
  readiness claim follows.

### D-412: Keep ERPNext reads provider-specific and mutation-free

- **Date**: 2026-08-07
- **Context**: The SDK had only a provider-neutral ERP example, while ERPNext
  uses token authorization and offset pagination on its GL Entry resource.
- **Decision**: Add a read-only ERPNext adapter over the governed HTTPS
  executor. Bind an operator-owned HTTPS endpoint with the exact resource path,
  send `token` credentials only at runtime, encode cursors through a fixed
  `limit_start` query parameter, and reject mixed-company or ambiguous
  debit/credit pages before producing evidence.
- **Verification**: Focused synthetic transport tests cover auth, pagination,
  schema, company scope, endpoint hardening, cursor refusal, and secret
  isolation; full gates and hosted provider operation remain separate.
- **Boundary**: No ERPNext tenant, posting, write-back, provider SLA, or
  production-readiness claim follows.

### D-413: Keep ERPNext Journal Entry write-back disabled and balanced

- **Date**: 2026-08-07
- **Context**: ERPNext uses token authorization and exposes a Journal Entry
  REST resource, but provider posting and account mapping are not verified in
  the current environment.
- **Decision**: Add a provider-specific draft payload builder with exact
  Decimal text, one-sided account lines, exact document balance, and fixed
  `docstatus=0`. Extend the write-back transport with a digest-bound optional
  `token` scheme while preserving legacy Bearer registration digests. Keep the
  ERPNext registration feature-disabled until an operator enables the existing
  maker-checker and server-profile controls.
- **Verification**: Synthetic payload, endpoint, gating, token-header,
  acknowledgement, digest, and secret-isolation tests pass; full local and
  static/package gates pass.
- **Boundary**: No live tenant, posting, account mapping, compensation
  endpoint, provider-version certification, or production write-back claim.

### D-414: Send ERPNext company scope to the provider and retain local guard

- **Date**: 2026-08-07
- **Context**: Local page validation prevented mixed-company evidence but did
  not prevent an unfiltered provider response from carrying out-of-scope rows.
- **Decision**: Add a closed query-parameter contract to the network executor.
  ERPNext sends Frappe's exact JSON company filter and optional bounded page
  length; fixed operator query text is preserved and all runtime query data is
  request-digest bound. Keep the response-level company guard as defense in
  depth.
- **Verification**: Focused synthetic tests cover canonical ordering, URL
  encoding, duplicate/control rejection, fixed-query preservation, page limits,
  and digest binding.
- **Boundary**: No claim of live provider filtering completeness or production
  tenant isolation follows without a real ERPNext runtime.

### D-415: Compose the bank-statement HTTPS source with the bounded CAMT parser

- **Date**: 2026-08-07
- **Context**: ReconForge had a deterministic local CAMT.053 boundary and a
  governed HTTPS executor, but no banking source adapter connecting those
  contracts.
- **Decision**: Add a read-only CAMT.053 HTTPS adapter with one exact endpoint
  path, runtime secret-reference credentials, the existing 8 MiB parser limit,
  optional expected-account isolation, and separate request/raw-response/
  normalized-source digests. Keep cursor and write capabilities disabled.
- **Verification**: Synthetic transport tests, malformed XML/XXE parser tests,
  account-scope tests, parser-inventory closure, packaging, full regression,
  and static/security/package gates pass locally.
- **Boundary**: Provider dialect, source authenticity, certificate or
  credential lifecycle, settlement, posting, write-back, and production
  availability remain unverified.

### D-416: Keep ERPNext Payment Entry reads closed and mutation-free

- **Date**: 2026-08-07
- **Context**: ERPNext GL Entry coverage did not expose the separate Payment
  Entry source shape needed for payment-control reconciliation.
- **Decision**: Add a read-only Payment Entry adapter with an exact resource
  path, token credentials, bounded offset pagination, provider-side and local
  company scope, exact paid/received Decimal text, duplicate/zero-page
  refusal, and deterministic response digests. No payment initiation or
  posting capability is added.
- **Verification**: Synthetic transport tests, parser-inventory closure,
  endpoint hardening, secret isolation, packaging, full regression, and
  static/security/package gates must pass.
- **Boundary**: Tenant/provider-version conformance, account mapping,
  settlement, posting, write-back, and production availability remain open.

### D-417: Require common replay conformance for provider read registrations

- **Date**: 2026-08-07
- **Context**: The CAMT.053 HTTPS and ERPNext read adapters each had direct
  tests, but the shared SDK portfolio did not prove that every provider
  registration obeyed the same manifest and replay boundary.
- **Decision**: Include the CAMT.053 HTTPS source and ERPNext GL Entry/Payment
  Entry sources in the reference manifest portfolio, and run each registration
  twice through the governed executor with a synthetic transport. Require
  read-only capability, exact HTTPS egress, secret-reference authentication,
  bounded retry/cursor declarations, identical request/response identity, and
  bounded recovery from synthetic 503/429 transient statuses.
- **Verification**: Focused provider/SDK tests pass; the 2,713-test local
  regression, Mypy, Ruff, Bandit, pip-audit, package/archive, and diff gates
  pass locally.
- **Boundary**: Synthetic SDK evidence does not establish live bank/ERP
  interoperability, source authenticity, settlement, posting, write-back, or
  production availability.

### D-418: Keep Gitleaks false-positive suppression exact and test-bound

- **Date**: 2026-08-07
- **Context**: The current checksum-verified Gitleaks history scan classified
  one literal observability redaction fixture as `generic-api-key`.
- **Decision**: Retain the fixture because it tests that tenant, job, actor,
  and worker identifiers do not reach telemetry. Add only the exact historical
  commit/path/rule/line and checked-tree fingerprints to `.gitleaksignore`.
  Do not add a broad rule, path, commit range, regex, or baseline.
- **Verification**: Gitleaks 8.30.1 scans 602 commits with zero findings and
  scans a clean 25.12 MB `git archive` checkout with zero findings. The local
  generated workspace scan is explicitly excluded from evidence after a
  6.30 GB/120-second timeout.
- **Boundary**: This is local scanner evidence; hosted security attestation,
  branch protection, and external credential safety remain unverified.

### D-419: Exercise provider adapters through a real local TLS transport

- **Date**: 2026-08-07
- **Context**: CAMT.053 and ERPNext adapters had provider-schema tests over an
  injected transport, but no runtime test crossed the actual pinned HTTPS
  connection boundary.
- **Decision**: Use a per-test localhost certificate and an injected public
  resolver with `PinnedHttpsGetTransport`. Exercise CAMT.053 and both ERPNext
  readers through a first-503/second-200 server, checking auth scheme,
  endpoint/query/cursor behavior, scope enforcement, and closed response
  parsing.
- **Verification**: Three focused TLS sandbox tests pass, and the full
  repository regression collected 2,716 tests and exited 0 in 366.5 seconds;
  the new ADR and test are required source-distribution members. The sandbox
  remains local synthetic evidence and does not call a provider.
- **Boundary**: Provider dialect/version, source authenticity, certificate or
  credential lifecycle, settlement, posting, write-back, and production
  availability remain open.

### D-420: Add a bounded grouped-matching property/fuzz campaign

- **Date**: 2026-08-07
- **Context**: Grouped matching had adversarial, mutation-sentinel, and
  checkpoint fault contracts, but the execution gap still listed broader
  generated fuzz/property coverage as open.
- **Decision**: Use deterministic Hypothesis generation at the public domain
  boundary with finite record counts and explicit search ceilings. Assert
  permutation-stable digests, closed selection invariants, budget refusal,
  portfolio non-overlap, and replay digest stability.
- **Verification**: Three new property/fuzz tests and the existing grouped
  correctness/adversarial/replay/mutation tests pass 20/20; the full
  repository regression collected 2,719 tests and exited 0 in 368.6 seconds;
  the ADR and test are source-distribution members.
- **Boundary**: This is synthetic bounded property/fuzz evidence, not a
  source-code mutation score, PostgreSQL parity, distributed fault campaign,
  live-rate validation, or production sizing claim.

### D-421: Add targeted source mutation for grouped matching

- **Date**: 2026-08-07
- **Context**: E-594 added generated property/fuzz checks, while the matching
  gap still distinguished request-level sentinels from source mutation.
- **Decision**: Use a dependency-free disposable child package and a closed
  subprocess pytest contract. Mutate only three named source expressions and
  require the baseline to pass and every mutant to fail.
- **Verification**: The campaign kills 3/3 mutants with zero survivors; the
  combined focused grouped suite passes 27 tests; the full repository
  regression collected 2,720 tests and exited 0 in 365.1 seconds; the
  ADR/source files are source-distribution members.
- **Boundary**: Targeted mutation only; no domain-wide mutation score,
  PostgreSQL parity, distributed fault campaign, live-rate validation, or
  production sizing claim follows.

### D-422: Persist durable-job scheduler cursor state

- **Date**: 2026-08-07
- **Context**: The process-scoped round-robin scheduler reset its cursor on
  restart and could not coordinate independent scheduler loops.
- **Decision**: Add tenant-scoped SQLite migration 34 and PostgreSQL migration
  `0079_pg_job_cursor`, bind each scheduler key to an ordered SHA-256 lane
  digest and count, reserve/advance the cursor atomically, and fail closed on
  lane drift. Restrict persistent scheduler lanes to one tenant for RLS-safe
  service operation; retain the process-scoped class for compatibility.
- **Verification**: Restart/drift SQLite contracts, migration chain,
  backup/export, PostgreSQL schema/RLS/Alembic/grant contracts, Ruff, Mypy,
  focused tests, and package checks pass.
- **Boundary**: This proves bounded shared-cursor coordination, not live
  cross-host fairness SLOs, throughput, queue HA/failover, soak, capacity, or
  production readiness.

### D-423: Treat two-connection SQLite cursor contention as bounded evidence

- **Date**: 2026-08-07
- **Context**: Restart continuity did not exercise concurrent transaction
  serialization for the persistent scheduler cursor.
- **Decision**: Use two independently created SQLite connections in separate
  executor threads, reserve twelve positions under one scheduler key, and
  require balanced lane counts and the exact final cursor version/index.
- **Verification**: The focused durable-job application suite passes; each
  connection is created and closed inside its owning thread to respect SQLite
  thread affinity.
- **Boundary**: This is local SQLite lock/serialization evidence only, not
  PostgreSQL, cross-host fairness, throughput, queue HA/failover, soak,
  capacity, or production SLO evidence.

### D-424: Verify nested retail-settlement replay integrity

- **Date**: 2026-08-07
- **Context**: The retail settlement report reader checked only its outer
  artifact digest, so a caller could alter serialized decision data and then
  recompute that envelope.
- **Decision**: Keep the existing report shape and add a shared canonical
  helper for the nested decision digest. Require canonical decision ordering
  and derived status counts before accepting a report.
- **Verification**: The focused retail suite passes 10/10, including a
  monetary-decision mutation whose recomputed outer digest is still refused.
- **Boundary**: This protects serialized artifact integrity only. It is not a
  signature, source-authenticity proof, live provider settlement, persistence,
  posting, write-back, or production retail evidence.

### D-425: Share nested decision integrity across industry controls

- **Date**: 2026-08-07
- **Context**: Bank, manufacturing, and professional invoice/payment reports
  each carried a decision digest but only checked their outer artifact hash.
- **Decision**: Use one small domain helper for canonical serialized decision
  ordering, sorted unique input fingerprints, status-count derivation, and
  nested digest verification; retain per-module schema, algorithm, status, and
  ordering contracts.
- **Verification**: Focused bank/manufacturing/professional suites pass 21/21,
  including an outer-rehash tamper regression for every module; the helper is
  included in the source distribution.
- **Boundary**: Serialized artifact integrity only; no source authenticity,
  live provider, persistence, posting, write-back, or production claim follows.

### D-426: Fail fast on repeated network-connector dependency failures

- **Date**: 2026-08-07
- **Context**: Bounded per-read retries did not stop later reads from
  repeating the same retry loop during a provider outage.
- **Decision**: Track an in-memory circuit per connector and exact endpoint.
  Open it after a bounded number of exhausted retryable transport/5xx failures,
  refuse reads during the window, and clear state after a successful recovery.
  Permanent HTTP and local response-policy errors do not open it.
- **Verification**: The network focused suite passes 24/24; the circuit test
  proves no transport call while open and one-attempt recovery after expiry.
- **Boundary**: Process-local synthetic resilience only; no distributed quota,
  live provider availability, vault, or production SLO claim follows.

### D-427: Keep network circuit state lane-scoped and bounded

- **Date**: 2026-08-07
- **Context**: A process-local circuit must not let one declared destination or
  credential lane suppress an independent connector lane, and unsafe operator
  bounds must not be accepted.
- **Decision**: Bind circuit state to connector, exact endpoint, and credential
  reference (or public lane); reject thresholds outside 1..100 and open windows
  outside 0..3600 seconds.
- **Verification**: Focused network tests pass 26/26, including endpoint and
  credential isolation plus invalid-bound refusal.
- **Boundary**: This is process-local synthetic isolation only; it does not
  establish distributed quota/circuit coordination, live provider behavior,
  vault operation, or production SLOs.

### D-428: Fail closed when hosted PostgreSQL native tools are absent

- **Date**: 2026-08-07
- **Context**: The backup gate previously depended on ambient runner tools, so
  a missing or wrapper-only PostgreSQL client could produce no dump without a
  repository-level workflow signal.
- **Decision**: Install the distribution `postgresql-client` package in
  `server-boundaries`, resolve the versioned client bindir through
  `pg_config --bindir`, and require all five native binaries before live tests.
  Protect the contract with a YAML workflow test.
- **Verification**: The phase-4 and connector focused suites pass 37/37, and
  Ruff plus diff-check pass.
- **Boundary**: Hosted execution, encrypted restore, HA/DR, RPO/RTO, and
  production release evidence remain unverified until a fresh runner completes
  the live gate.

### D-429: Persist retail settlement evidence in local SQLite

- **Date**: 2026-08-07
- **Context**: The experimental retail settlement report was deterministic and
  digest-bound but had no durable, workspace-scoped local evidence boundary or
  backup/restore coverage.
- **Decision**: Add SQLite migration 35 and an append-only
  `SQLiteRetailSettlementRepository`. Require `finance_core.manage`, derive a
  stable workspace-scoped identity, make repeated puts idempotent, verify the
  outer and nested decision digests plus persisted status/algorithm columns on
  every read, and include the table in local backup/restore maps.
- **Verification**: Retail persistence, tamper, migration, backup/restore,
  inventory, and focused regression tests pass; package/static gates remain
  release requirements.
- **Boundary**: Local SQLite persistence only; no retail API/Studio, live
  processor authenticity, settlement finality/fraud, posting, write-back,
  PostgreSQL parity, HA/DR, or production retail claim follows.

### D-430: Keep retail API exposure local until PostgreSQL parity exists

- **Date**: 2026-08-07
- **Context**: E-603 made retail settlement evidence durable in local SQLite,
  but exposing it through a server profile without a PostgreSQL adapter would
  create a misleading persistence fallback and an unbounded authorization
  surface.
- **Decision**: Add a migration-aware CLI `--persist` option and authenticated
  local `/api/v1/retail/settlements` POST/list/read routes. Writes require
  `finance_core.manage`; reads use the existing finance read/manage/validate
  any-of policy; report payloads are verified by the repository; server mode
  fails explicitly with no SQLite fallback.
- **Verification**: API/CLI tests prove authentication, workspace isolation,
  idempotency, tamper refusal, list/read behavior, and the 249-route digest
  inventory.
- **Boundary**: Local API/CLI composition only; no Studio, PostgreSQL parity,
  live processor authenticity, posting, write-back, HA/DR, or production
  retail claim follows.

### D-431: Use a forced-RLS PostgreSQL adapter for server retail evidence

- **Date**: 2026-08-07
- **Context**: E-604 intentionally refused server-mode retail persistence to
  avoid a silent SQLite fallback. A server deployment needs a real adapter
  before the route can be promoted beyond the local profile.
- **Decision**: Migration `0080_pg_retail_settlement` stores the bounded report
  as JSONB with scalar digest projections, forced tenant/workspace RLS, and an
  immutable trigger. `PostgresRetailSettlementRepository` validates the outer
  and nested digests on write/read, locks the decision key transaction-locally,
  and treats same-artifact replay as idempotent while refusing a conflicting
  artifact. The API binds body/query workspace to the authenticated request
  scope and selects PostgreSQL explicitly in server mode.
- **Boundary**: This is persistence and scope-parity evidence only. It does
  not establish hosted CI, HA/DR, live processor authenticity, posting,
  write-back, Studio/accessibility, or production retail operations.

### D-432: Keep the retail Studio view projection-only and read-only

- **Date**: 2026-08-07
- **Context**: E-605 completed local/API/PostgreSQL retail evidence paths, but
  the modern Studio had no review surface for that evidence.
- **Decision**: Add `/retail-settlement` as a lazy-loaded React route backed by
  one synthetic-only, versioned projection of the deterministic report. The
  browser validates exact decimal strings, bounded status values, digest
  shapes, unique batch IDs, and summary consistency. It displays English and
  Arabic labels, status filtering, variance reasons, algorithm/digest fields,
  and a visible non-posting/provider boundary.
- **Boundary**: The view does not calculate a second result, call a provider,
  call the authenticated retail API, post accounting entries, or write back.
  Live browser authentication, source authenticity, settlement finality,
  hosted deployment, HA/DR, and production retail operations remain open.
