# ADR 0695: Payables goods-receipt API uses fail-closed field projection

- **Date**: 2026-08-26
- **Status**: Accepted for E-1035

## Context

The Payables receipt-posting route returned a local SQLite or tenant-scoped
PostgreSQL receipt mapping, including nested receipt-line rows. The adapters
have different physical schemas and local reads are broad; future columns
could otherwise become accidental financial response disclosure.

## Decision

Add central `PAYABLES_RECEIPT_FIELDS` and `PAYABLES_RECEIPT_LINE_FIELDS`
contracts plus a recursive `project_payables_receipt` projector. Apply it to
both local and PostgreSQL branches of `POST /api/v1/payables/receipts`.
Preserve the existing direct response shape, exact quantity fields,
permissions, lifecycle behavior, and local/server boundary. Supplier invoices
and three-way-match results remain separate response families.

## Consequences

Known receipt and line fields remain available while unknown adapter/storage
fields are excluded before serialization. Synthetic SQLite future-column
coverage and the central field-access contract provide bounded evidence. This
does not establish universal field-level authorization, external IAM,
distributed revocation, disclosure approval, source authenticity, or
production effectiveness.

## Compatibility and rollback

No route, schema, migration, permission, response-envelope, or lifecycle
change is introduced. Rollback is a code-and-metadata revert of E-1035, its
tests, this ADR, the manifest entry, and execution documentation. Do not
restore unbounded repository-row serialization as a compatibility fallback.
