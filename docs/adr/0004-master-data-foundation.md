# ADR 0004: Governed Local Master-Data Foundation

- Status: Accepted for the organization/fiscal reference slice
- Date: 2026-07-22
- Decision owners: ReconForge maintainers

## Context

ReconForge already stored workspaces, organizations, legal entities, and periods, but they were mostly reference tables and minimal repositories. Future finance, inventory, manufacturing, project, and reporting modules require shared company/branch/currency/period invariants. Building transaction modules on free-text entity and period fields would multiply ambiguity and migration cost.

At the same time, a reference layer must not be presented as a general ledger, legal entity authority, exchange-rate engine, consolidation system, or ERP posting lock.

## Decision

1. Add migration 7 rather than rewriting the initial schema or deleting legacy data.
2. Preserve existing rows and assign deterministic bounded legacy organization codes.
3. Add local currency and branch tables plus organization/entity/period activity and update metadata.
4. Require three-letter active currency references for new legal-entity writes while preserving legacy currency text.
5. Enforce organization/entity/branch scope and prevent branch-to-entity references across organizations.
6. Prevent overlapping fiscal-period dates per workspace under a SQLite immediate write transaction.
7. Allow only `Open -> Soft Closed -> Closed`, with controlled reopen transitions and mandatory reopen reasons.
8. Treat period status as workflow metadata only; it does not lock or post source-ERP transactions.
9. Add least-privilege `master_data.read` and `master_data.manage` permissions and append sanitized audit events for mutations.
10. Expose a versioned, path-free snapshot through CLI and authenticated API; do not implement import until conflict, merge, and authorization semantics are designed.

## Consequences

### Positive

- Future modules gain one governed reference boundary instead of duplicating codes and validation.
- Existing v6 databases can upgrade without destructive table replacement.
- Controller and read-only roles receive explicit least-privilege behavior.
- Snapshot consumers get a published JSON Schema without database or filesystem details.
- Period overlap and transition behavior is deterministic and testable.

### Costs and limits

- Existing workflow tables still contain some free-text entity and period fields; migration to foreign keys is future work.
- Currency references do not include exchange rates or localization.
- Period lifecycle does not enforce posting locks in source systems.
- Workspace isolation remains local-database application scope, not multi-tenant hosted isolation.
- Import/merge, deletion, archival policy, departments, dimensions, tax localization, and consolidation remain deferred.

## Rejected alternatives

### Add transaction modules first

Rejected because company, currency, branch, and fiscal-calendar ambiguity would be embedded in every downstream table.

### Replace existing tables

Rejected because it would create unnecessary migration and compatibility risk for local databases.

### Bundle exchange rates

Rejected because rate provenance, effective dates, providers, offline refresh, licensing, and accounting policy require a separate contract.
