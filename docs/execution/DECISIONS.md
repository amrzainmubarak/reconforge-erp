# ReconForge Execution Decisions Log

> This document records all decisions made during the ReconForge transformation execution.
> Each decision follows the format: ID, Date, Context, Decision, Rationale, Reversibility.

## Decisions

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
