# ADR 0694: Payables purchase-order API uses fail-closed field projection

- **Date**: 2026-08-26
- **Status**: Accepted for E-1034

## Context

Payables purchase-order create, submit, and approve routes returned mappings
from local SQLite and tenant-scoped PostgreSQL adapters. The response includes
nested purchase-order lines. Local table reads and future adapter columns could
therefore expand the financial lifecycle response without an intentional API
decision.

## Decision

Add central `PAYABLES_PURCHASE_ORDER_FIELDS` and
`PAYABLES_PURCHASE_ORDER_LINE_FIELDS` contracts plus a recursive
`project_payables_purchase_order` projector. Apply it to both local and
PostgreSQL branches for purchase-order create, submit, and approve. Retain the
existing direct response shape, exact quantity and minor-unit price fields,
permissions, lifecycle behavior, and local/server separation. Supplier
invoices, receipts, and three-way-match results remain separate response
families.

## Consequences

Known purchase-order and line fields remain available, while unknown
adapter/storage fields are excluded before serialization. Synthetic SQLite
future-column coverage and the central field-access contract provide bounded
evidence. This does not establish universal field-level authorization,
external IAM, distributed revocation, disclosure approval, source
authenticity, or production effectiveness.

## Compatibility and rollback

No route, schema, migration, permission, response-envelope, or lifecycle
change is introduced. Rollback is a code-and-metadata revert of E-1034, its
tests, this ADR, the manifest entry, and execution documentation. Do not
restore unbounded repository-row serialization as a compatibility fallback.
