# ADR 0696: Payables supplier-invoice API uses fail-closed field projection

- **Date**: 2026-08-26
- **Status**: Accepted for E-1036

## Context

Payables supplier-invoice routes returned mappings from local SQLite and
tenant-scoped PostgreSQL adapters. Invoice create/read mappings contain nested
invoice lines and an optional three-way-match record; list and lifecycle paths
return related shapes. Local broad reads or future adapter fields could make
storage evolution an accidental financial disclosure change.

## Decision

Add central invoice, invoice-line, and three-way-match allowlists plus the
recursive `project_payables_supplier_invoice` projector. Apply it to invoice
create, list, submit, match, and approve branches for both local and
PostgreSQL. Preserve existing direct response shapes, exact quantity and
minor-unit values, permissions, lifecycle behavior, and local/server
separation. Supplier, purchase-order, and goods-receipt response families
remain separately governed.

## Consequences

Known invoice, line, and match fields remain available while unknown
adapter/storage fields are excluded before serialization. Synthetic SQLite
future-column coverage and the field-access contracts provide bounded
evidence. This does not establish universal field-level authorization,
external IAM, distributed revocation, disclosure approval, source
authenticity, or production effectiveness.

## Compatibility and rollback

No route, schema, migration, permission, response-envelope, or lifecycle
change is introduced. Rollback is a code-and-metadata revert of E-1036, its
tests, this ADR, the manifest entry, and execution documentation. Do not
restore unbounded repository-row serialization as a compatibility fallback.
