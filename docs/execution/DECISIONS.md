# ReconForge Execution Decisions Log

> This document records all decisions made during the ReconForge transformation execution.
> Each decision follows the format: ID, Date, Context, Decision, Rationale, Reversibility.

## Decisions

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
- **Reversibility**: Additive application class and tests; no schema change.

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
