# Engineering Roadmap

This roadmap is implementation-oriented. “Planned” means design work or a foundation,
not a shipped capability.

## P0 — financial correctness and atomic evidence

Completed in the current working phase:

- Decimal parsing rejects missing, malformed, non-finite, and boolean amounts.
- Invalid and missing stock/GL dates are data-quality exceptions and are excluded from matching.
- Stock-to-GL assignment is deterministic and globally optimized.
- Stable match/exception IDs do not use DataFrame row numbers.
- Candidate generation combines reference, exact-field, and amount indexes before scoring.
- Both left and right unmatched platform results are persisted.
- Match retries can use an idempotency key.
- Audit append respects caller transactions; matching, journal, Finance Core, Inventory Core, exception, metrics, controls, approvals, intercompany, master data, evidence, and close mutations append audit before commit.
- Match completion and journal import write a local transactional outbox event before commit.
- Accounts Payable foundation added in migration 15: supplier master, purchase orders, posted receipts, supplier invoices, deterministic three-way matching, exception visibility, idempotency, optimistic row versions, RBAC/SoD checks, and backup/restore coverage. It is not a statutory AP subledger or payment engine.
- Accounts Receivable foundation added in migration 20: customer credit profiles, exact sales invoices, approval-time credit-hold/limit controls, permissioned override reasons, posted receipts, accumulating allocations, deterministic exposure/aging reads, RBAC/SoD, audit/outbox evidence, CLI/API surfaces, and backup/restore coverage. It is not a statutory AR subledger, tax, collections, payment, or ERP-writeback engine.
- Account reconciliation migrated in migration 16 to canonical Decimal text and currency metadata, strict invalid-value handling, atomic workflow/audit/outbox finalization, and Decimal-preserving backup/restore coverage.
- Journal and intercompany amounts migrated in migration 17 to canonical Decimal text with strict invalid-value handling, Decimal precision tests, and atomic outbox/audit finalization.
- Persisted matching differences migrated in migration 18 to canonical Decimal text with strict non-negative tolerance validation, exact tolerance metadata, and backup/restore coverage.
- Stock-to-GL assignment penalties, risk magnitudes, and declarative control-rule monetary comparisons now use Decimal arithmetic; invalid control amount impact remains explicit.
- Period comparison identity, review amount fallback, client-pack redaction buckets, and WIP risk inputs now use strict Decimal parsing.
- Workflow repositories now support caller-owned transactions so compound financial mutations can roll back business, workflow, audit, and outbox writes together.
- Inventory planning/counts, FIFO valuation, and valuation reversal now append transactional outbox and audit evidence before their repository transactions commit, with forced-failure rollback coverage.
- New invariant/regression tests cover row order, invalid values/dates, cardinality, idempotency, and rollback.

## P0 remaining

- Migrate the remaining legacy platform mutation services to the same atomic audit/outbox pattern.
- Standardize duplicate, ambiguous, partial, reversal, and manual-override exception contracts across all reconciliation modules.
- Extend the canonical monetary storage contract from account reconciliation, journals, intercompany, and AP to SQLite tables still using floating-point affinity.

## P1 — production platform foundation

- Connect the versioned transactional outbox delivery state machine (SQLite migrations 13-14 and PostgreSQL migration 0007) to a managed publisher/worker runtime and external transport. Tenant-scoped PostgreSQL claim/retry/dead-letter/replay semantics and a fresh-connection worker adapter are implemented; managed scheduling, tenant enumeration, transport idempotency, and observability remain open.
- Add the optional PostgreSQL connection, transaction-local tenant scope, and RLS schema foundation while preserving SQLite local mode. Alembic now manages the tenant/RLS foundation, master-data, bounded exact-amount ledger-control, tenant-scoped identity, close-control, outbox delivery, evidence-registry, reconciliation-result, reconciliation-execution, and partition-checkpoint contexts; authenticated server routes now atomically accept bounded canonical reconciliation submissions, and a durable worker using the explicit schema-only `LocalDeterministicMatcherAdapter` exposes the persisted output contract. Hard-key partitioning, atomic checkpoint resume, tenant-scoped PostgreSQL-cursor partition streaming, a multi-worker scheduler, and bounded DuckDB CSV relation batches are implemented foundations; streamed global execution, million-row evidence, and each remaining domain schema still require integration before calling server persistence complete.
- Add tenant context enforcement at repository, API, worker, cache, object, and export boundaries.
- PostgreSQL server API authentication, tenant-scoped RBAC snapshots, hashed sessions, revocation, principal propagation, bounded master-data collection APIs including fiscal periods, a bounded Finance Core account/posted-entry/trial-balance API, audit-chain reads/verification, and a bounded close-control period/task API are implemented as a transition profile; remaining domain schemas are still local-only; add MFA/enterprise-provider adapters, Redis-backed multi-worker sessions, user lifecycle administration, remaining Finance Core schemas, and deployment-wide worker/UI propagation before calling server persistence or enterprise identity complete.
- Add the optional Redis boundary for tenant-scoped sessions, revocation, atomic rate limiting, and distributed locks (foundation implemented); wire it into API authentication, workers, and failure recovery before calling multi-worker coordination implemented.
- Add the optional S3-compatible object-storage adapter with tenant keys, checksum verification, retention metadata/object-lock support, bounded signed URLs, and deletion safeguards (foundation implemented); migrations 19 and 0008 now support explicit object-backed local registration plus tenant-scoped PostgreSQL evidence metadata, links, requirements, coverage, and verification. Wire it into workers, scanning, authorized downloads, and restore workflows before calling the artifact pipeline complete.
- Add OpenTelemetry traces/metrics and structured security events.
- Add clean-install and supported-Python smoke validation.

## P2 — finance and close depth

- Extend the bounded AP and AR slices with payment proposals, tax/withholding, credit/debit notes, invoice/revenue accounting, period controls, collections, and source-system integration; build treasury, tax, multi-currency, budgets, consolidation, and close controls as separate domain slices.
- Add immutable posting snapshots, reversal workflows, fiscal calendars, period locks, and evidence binders per cycle.
- Add golden datasets and invariant/property tests before broad capability claims.

## P3 — operational ERP domains

- Procurement, sales, inventory/warehouse operations, returns, landed cost, planning, and replenishment.
- Manufacturing/MRP, fixed assets, projects, quality, and maintenance only after inventory/finance foundations are stable.

## P4 — enterprise integrations and scale

- Connector SDK with tested local connectors and separately tested vendor adapters.
- Chunked/Parquet execution, resumable jobs, cancellation, worker recovery, and 10k/100k/1m reproducible benchmarks.
- Hosted deployment profiles, read replicas/warehouse reporting, SSO/SCIM interoperability, WebAuthn recovery/attestation governance, workload federation, and production DR exercises.

## Release gates

Every phase requires passing unit/integration/security/migration tests, updated evidence-
backed documentation, no unresolved Critical findings, and an explicit capability-boundary
review. No phase changes the product positioning to “complete ERP” or “enterprise-ready”
without the corresponding implementation and operational evidence.
