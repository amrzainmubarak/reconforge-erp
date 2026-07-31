# Engineering Audit

Baseline reviewed: 2026-07-23. The repository is ReconForge v0.7.0-alpha on the
`feature/p0-atomic-audit-outbox` branch. The full Python test suite passes under the
available Python 3.14 runtime when pytest is given a writable workspace temp directory.
The committed CI matrix remains Python 3.11/3.12.

## Critical

### C-001 — Hosted enterprise isolation is not implemented

- Evidence: persistence is still SQLite-first for the API and Studio domain routes, but PostgreSQL now has real bounded repositories for master data, ledger control, close control, tenant-scoped identity, audit reads, transactional outbox delivery, evidence metadata/coverage, reconciliation results, and reconciliation execution state. The explicit server-auth profile uses PostgreSQL for login, bearer validation, RBAC snapshots, revocation, and principal propagation while legacy domain routes remain on tenant-isolated SQLite; S3-backed evidence registration, PostgreSQL outbox delivery, authenticated reconciliation submission/read/cancellation/requeue, and a worker using the explicit schema-only `LocalDeterministicMatcherAdapter` are bounded and explicit, but production scheduling, external publishers, worker/API artifact delivery, large-dataset hosted execution, and full hosted domain persistence do not yet consume all boundaries.
- Affected files: `reconforge/db/`, `reconforge/platform/`, `reconforge/api/`.
- Technical risk: a hosted deployment would lack a proven tenant boundary and shared-service operational model.
- Financial/operational risk: cross-tenant disclosure or inconsistent isolation would be unacceptable for customer financial data.
- Recommended fix: retain the bounded database-per-tenant option, integrate the remaining domain repositories with the PostgreSQL boundary, add migration/upgrade tests, and verify API, worker, cache, search, object, and export paths under the same tenant context.
- Implementation status: Partially mitigated. PostgreSQL/RLS, master-data, ledger-control, identity, close, outbox, evidence, reconciliation-result, and reconciliation-execution repositories plus bounded server-auth/API/worker surfaces are implemented; the deterministic adapter is explicitly schema-only and has no hosted SQLite persistence side effects; bounded run submission/input registration is atomic and idempotent; Redis and object-storage boundary contracts plus migration-19 local and migration-0008 hosted evidence-registry integration are implemented; live/contract tests cover RLS, master-data, balanced posting, immutability, password authentication, hashed-session revocation, API principal authorization, reconciliation submission/reads and execution claims, object integrity, evidence metadata immutability, and tenant visibility when services are configured. Full hosted domain isolation remains open and is not advertised as implemented.
- Tests required: current API escape tests, PostgreSQL/Redis/object-storage boundary contracts, live RLS/master-data/ledger/identity/API/Redis/S3 tests, Alembic migration/upgrade tests, repository contract tests, and worker/cache/object-storage isolation tests.
- Migration impact: High; requires a versioned hosted schema and deployment migration plan.

### C-002 — The product is not yet a complete ERP

- Evidence: implemented workflows focus on reconciliation, controls, local finance/inventory foundations, close, evidence, and synthetic Studio surfaces. Migrations 15 and 20 add bounded AP and AR workflow slices, but complete accounting posting/payment, sales, procurement, manufacturing, tax, collections, projects, and fixed-asset transaction cycles are not present.
- Affected files: repository-wide; capability boundary is documented in `README.md`.
- Technical risk: users could mistake foundations or showcase screens for a complete posting ERP.
- Financial/operational risk: unsupported transaction cycles would require unsafe workarounds.
- Recommended fix: preserve the finance-controls positioning and add ERP modules as separately tested bounded contexts.
- Implementation status: Open by design; the bounded AP and AR slices are explicitly disclosed and do not post statutory accounting entries, calculate statutory tax, execute payments, or run collections.
- Tests required: end-to-end accounting-cycle tests for each future module before changing the capability claim.
- Migration impact: Module-specific and potentially high.

## High

### H-001 — Audit atomicity was inconsistent across mutation services

- Evidence: `append_audit_event()` previously always opened and committed its own transaction; multiple services committed business changes before calling `audit()`.
- Affected files: `reconforge/audit/events.py`, `reconforge/platform/common.py`, `reconforge/platform/matching.py`, `reconforge/platform/journals.py`, `reconforge/platform/finance_core.py`, `reconforge/platform/inventory_core.py`, `reconforge/platform/inventory_planning.py`, `reconforge/platform/inventory_valuation.py`, `reconforge/platform/inventory_valuation_reversal.py`, `reconforge/platform/exceptions.py`, `reconforge/platform/metrics.py`, `reconforge/platform/controls.py`, `reconforge/platform/approvals.py`, `reconforge/platform/intercompany.py`, `reconforge/platform/master_data.py`, `reconforge/platform/evidence.py`, `reconforge/platform/close.py`, and `reconforge/platform/accounts.py`.
- Technical risk: an audit failure could leave a committed business change without its audit event.
- Financial/operational risk: the result would not be fully traceable and could not satisfy evidence expectations.
- Recommended fix: keep audit appenders transaction-neutral when a caller transaction exists; append audit and outbox records before commit; migrate remaining legacy mutation paths.
- Implementation status: Audit atomicity is now enforced for matching, journal import, Finance Core entry lifecycle, Inventory Core movement lifecycle, account reconciliation, inventory planning/counts, FIFO valuation and reversal, the bounded AP and AR lifecycles, exception queue, metrics, controls, approvals, intercompany, master data, evidence, and close-period/task mutations. Transactional outbox coverage remains intentionally limited to selected reconciliation/journal/Finance Core/Inventory Core/AP/AR/account/inventory planning and valuation paths; other legacy services still require migration.
- Tests required: forced audit failure must roll back the business record, audit row, and outbox row.
- Migration impact: Low for local databases; behavior changes from partial commit to rollback on audit failure.

### H-002 — Monetary storage remains mixed outside the reconciliation core

- Evidence: reconciliation parsing, account reconciliation, journal imports, intercompany, AP slices, stock-to-GL assignment costs, risk magnitudes, control-rule comparisons, period fingerprints, review fallbacks, and client-pack amount buckets are Decimal-backed or Decimal-calculated and reject invalid values where they parse financial inputs, but several local platform tables still use SQLite `REAL` columns and legacy numeric call sites.
- Affected files: `reconforge/platform/common.py`, `reconforge/platform/journals.py`, `reconforge/platform/intercompany.py`, `reconforge/platform/matching.py`, `reconforge/platform/accounts.py`, related schema tables, and migrations 16-18.
- Technical risk: binary floating-point and invalid-value fallback can re-enter non-core finance workflows.
- Financial/operational risk: tolerance boundaries and imported journal values can drift or conceal data-quality errors.
- Recommended fix: migrate financial columns to integer minor units or canonical decimal text with currency metadata; remove financial uses of permissive converters.
- Implementation status: In progress; migrations 16-18 add canonical Decimal text and currency columns for account reconciliation, journals, intercompany, and persisted matching differences, while strict imports/tolerances reject invalid amounts, risk/rule/matching calculations avoid float arithmetic, and migrated mutations emit atomic audit/outbox evidence. Legacy compatibility columns and other platform REAL fields remain.
- Tests required: currency precision, locale parsing, invalid-value, round-trip, and ledger-invariant tests.
- Migration impact: High for existing local tables; requires expand-and-contract migration and export compatibility notes.

### H-003 — Reconciliation coverage is strongest for stock-to-GL, not all ERP domains

- Evidence: `reconforge/reconciliation/stock_gl.py` has two-sided result accounting, deterministic assignment, and data-quality exceptions; the bounded AP three-way-match and AR invoice/receipt services have their own exact-quantity/minor-unit contracts, while other control modules do not yet share the same invariant API.
- Affected files: `reconforge/reconciliation/`, `reconforge/platform/`.
- Technical risk: behavior and evidence fields can diverge across future reconciliation types.
- Financial/operational risk: unmatched or invalid records could be represented inconsistently.
- Recommended fix: define a shared reconciliation result contract with lineage, exception taxonomy, and cardinality invariants.
- Implementation status: Stock-to-GL, bounded AP, and bounded AR foundations implemented; shared cross-module contract remains open.
- Tests required: golden datasets and property-based invariants per reconciliation type.
- Migration impact: Moderate; report schemas need additive fields and versioning.

### H-004 — Unbound local actor labels are still permitted in local service mode

- Evidence: `reconforge/platform/common.py:require_permission()` preserves labels such as `local-cli` for trusted local operation, while `reconforge/api/app.py` scopes every API request to an explicit untrusted-server context that rejects unbound actors.
- Affected files: `reconforge/platform/common.py`, `reconforge/cli.py`, `reconforge/auth/`, and API/service call sites that pass actor labels.
- Technical risk: a production deployment that exposes local service entry points without an explicit trusted-local boundary could execute actions without a real identity or role assignment.
- Financial/operational risk: unauthorized financial changes may be attributed only to a shared label, weakening accountability and separation of duties.
- Recommended fix: make trusted-local mode an explicit local-only deployment setting; reject unbound actors in hosted/server mode and require authenticated tenant-scoped principals for all mutations.
- Implementation status: Partially mitigated; API/server request context rejects unbound actors and regression tests cover the guard. Enterprise identity, MFA, and deployment-level enforcement outside the API remain open.
- Tests required: authenticated actor propagation, tenant-scoped authorization, enterprise identity integration, and SoD bypass tests across all deployment surfaces.
- Migration impact: Moderate; automation and CLI users must create local users or explicitly select the local-only mode.

## Medium

### M-001 — DuckDB is genuine but intentionally not an end-to-end streaming engine

- Evidence: `reconforge/engines/duckdb_engine.py` registers local CSV/XLSX inputs as DuckDB relations, runs shared reconciliation directly for small workloads, and for larger local workloads partitions by `work_order` buckets with bounded relation-native reads before merging deterministic results.
- Affected files: `reconforge/engines/duckdb_engine.py`, `docs/performance/engine-parity.md`.
- Technical risk: large datasets can still require materialization and memory proportional to the input.
- Financial/operational risk: production-scale claims would be misleading without chunking and memory benchmarks.
- Recommended fix: add candidate pruning/partition-level cost-control, Parquet intermediates where useful, and reproducible 10k/100k/1m benchmarks.
- Implementation status: Real local backend implemented with relation-native `work_order` partitioning; hosted hard-key partitioning, tenant-scoped PostgreSQL-cursor input streaming, output checkpoints, and a multi-worker lease-based scheduler are bounded foundations. Global optimization over full streamed relation joins and published million-row evidence remain open.
- Tests required: row-level parity, memory ceilings, query-plan checks, cancellation/recovery tests, and completed 1m evidence before any scale claim.
- Migration impact: None for current local API; new execution modes require configuration compatibility.

### M-002 — The local authentication model is not an enterprise identity provider integration

- Evidence: local users/RBAC/session foundations, bounded PostgreSQL OIDC/SAML, authenticated SCIM, service principals, emergency review, and optional user-verified WebAuthn MFA are implemented and live-tested; hosted provider/authenticator interoperability, recovery, attestation governance, administration UI, workload federation, and Redis-backed multi-worker coordination are not implemented.
- Affected files: `reconforge/auth/`, `reconforge/api/security.py`.
- Technical risk: enterprise identity lifecycle and centralized session revocation are unavailable.
- Financial/operational risk: deployment teams may overestimate access-governance coverage.
- Recommended fix: implement provider adapters behind explicit feature flags and verify authorization at the backend.
- Implementation status: Local and bounded PostgreSQL identity surfaces, including WebAuthn MFA enforcement, are live-tested; enterprise lifecycle/interoperability and multi-worker Redis session coordination remain open.
- Tests required: hosted provider/authenticator interoperability, recovery, attestation policy, session revocation, SoD, workload federation, and tenant-scope tests.
- Migration impact: Moderate.

### M-003 — Developer environment reproducibility is degraded on this workspace

- Evidence: `.venv/Scripts/python.exe` points to a removed Python 3.11 installation; the system Python 3.14 runtime was required for validation.
- Affected files: local `.venv` only; repository setup is documented in `README.md`.
- Technical risk: contributors may receive an opaque launcher error before tests start.
- Financial/operational risk: missed validation or inconsistent local dependency resolution.
- Recommended fix: recreate local environments from `pyproject.toml`; add a setup diagnostic that reports interpreter mismatch.
- Implementation status: Environment issue observed, not a tracked repository artifact.
- Tests required: clean-install smoke tests on supported Python 3.11/3.12.
- Migration impact: None.

## Low / Enhancement

- The React Studio remains a read-only experimental client; mutation workflows are in the local Studio/CLI.
- The outbox is now formal schema migration 13. A compatibility guard may still create it for legacy version-12 databases opened before migration; hosted deployment must require the formal migration path.
- The current test suite is broad and green, but coverage and mutation-testing thresholds for critical financial branches are not yet enforced in CI.
- The transactional outbox now has formal migrations 13-14, bounded claim leases, retry/backoff, dead-letter state, explicit replay, and `reconforge/workers/outbox.py` provides fresh-connection bounded polling with graceful stop and injected publisher delivery. External transport, queue orchestration, tenant context, and delivery observability remain future work.
- Existing control packs are declarative YAML with schema validation; signing, dependency resolution, and safe upgrade migrations remain future work.

## Baseline commands

```powershell
python -m pytest --basetemp F:\reconforge-erp\.pytest_final -q
\.venv\Scripts\ruff.exe check .
```

The explicit `--basetemp` is needed in this environment because the default Windows
pytest temp root is not readable by the active process.
