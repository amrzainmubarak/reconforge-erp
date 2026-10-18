# ADR 0697: Receivables API uses fail-closed field projection

- Status: Accepted for E-1037
- Date: 2026-08-26
- Scope: ReconForge Receivables response serialization

## Context

The Receivables API returns customer, invoice, receipt, credit-exposure, and
aging data from local SQLite and tenant-scoped PostgreSQL adapters. Repository
and adapter mappings can gain storage-specific or future fields. Returning
those mappings directly would make financial response disclosure grow silently,
including through invoice lines, receipt allocations, and aging items.

## Decision

Use the central field-access projection contract for every reviewed
Receivables response family:

- customers use an explicit customer allowlist;
- invoices use an invoice allowlist and a recursive line allowlist;
- receipts use a receipt allowlist and a recursive allocation allowlist;
- credit exposure uses a dedicated exposure allowlist; and
- aging uses an explicit envelope and item allowlist.

Malformed nested collections or child records fail closed. The projection is
applied in both local and PostgreSQL route branches after existing scope,
permission, filtering, pagination, and lifecycle behavior. Direct response
shapes, exact minor units, and known fields remain compatible.

## Consequences

Unknown future adapter/storage fields do not enter the reviewed Receivables
responses by default. This is a disclosure boundary, not universal
field-level authorization: external IAM, distributed revocation, disclosure
approval, source authenticity, and production effectiveness remain separate
gates. No schema, migration, or persistence changes are introduced.

## Verification and rollback

`tests/test_field_access.py` covers all projector families and nested
structures. `tests/test_receivables_api.py` alters synthetic local tables with
future columns and proves they are absent from mutation and read responses.
Focused tests, full Python regression, Ruff, Mypy, Bandit, pip-audit, package
build, targeted YAML, and diff checks are the E-1037 evidence gates.

Rollback is a coordinated revert of the E-1037 route/projector code, tests,
this ADR, manifest entry, and execution metadata. It must not restore direct
unbounded repository-row serialization without a replacement disclosure
control.
