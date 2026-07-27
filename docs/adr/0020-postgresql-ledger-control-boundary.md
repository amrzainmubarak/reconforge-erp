# ADR 0020: PostgreSQL Ledger-Control Boundary

- Status: Accepted as a bounded server slice
- Date: 2026-07-23
- Decision owners: ReconForge maintainers

## Context

The server migration chain had tenant/RLS and reference master-data tables, but
no server-side financial record boundary. A hosted finance-controls platform
must prove exact amounts, balanced postings, immutable approved records, and
atomic evidence before migrating broader reconciliation and workflow domains.

## Decision

Add Alembic revision `0003_postgres_ledger` and
`PostgresLedgerRepository`. The repository stores tenant-scoped account
references, draft-to-posted ledger entries, and debit/credit lines using
`NUMERIC(38,18)`. Inputs reject floats, missing values, malformed values,
negative values, and unsupported precision. The repository validates balance
before posting; a deferred PostgreSQL trigger rechecks line count, debit/credit
equality, and account organization scope at transaction commit.

Posted entries and their lines are immutable through database triggers. Posting
also appends a tenant-scoped hash-chained audit event and a transactional
outbox event in the caller-owned transaction. The repository also exposes
deterministic tenant-scoped audit listing and verification, including event
hash recomputation and previous-hash link checks. RLS is enabled and forced on
all ledger, audit, and outbox tables.

The default local Finance Core service remains unchanged. In the explicit
PostgreSQL server profile, the authenticated Finance Core API now routes the
bounded account, posted-entry, and organization/fiscal-period trial-balance
operations to this repository. The server adapter never silently falls back to
SQLite. Charts, analytic dimensions, finance journals, legal-entity-scoped
trial balance, draft validation, and voiding return an explicit `501`
capability response until their PostgreSQL schemas and workflows exist.

## Consequences

- The server path now has a real exact-amount financial bounded context with
  database-enforced invariants, exact organization/period aggregation, and an
  authenticated API route boundary.
- Audit and outbox evidence is committed with the ledger write when the caller
  commits the surrounding transaction.
- PostgreSQL domain coverage is still incomplete: reconciliation, the rest of
  Finance Core, AP/AR posting, workflow, evidence artifacts, workers, cache,
  object storage, and exports remain to be migrated or integrated.
- Tenant cleanup cascades are allowed only through database referential actions;
  direct mutation of posted records remains rejected.

## Rejected alternatives

- Storing amounts as floating point: this would undermine financial equality
  and reproducibility.
- Relying only on application-side balance checks: direct SQL or future code
  paths could create unbalanced posted entries.
- Making posted rows editable for convenience: corrections require new entries
  or a future explicit reversal workflow.
