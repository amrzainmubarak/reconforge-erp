# ADR 0780: Enforce strict quantity inputs in Payables adapters

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Payables

## Context

The Payables contract stores purchase-order, receipt, and supplier-invoice
quantities as exact decimal values plus canonical text. The SQLite and
PostgreSQL adapters validated these values with direct `Decimal` conversion.
That allowed a direct programmatic caller to provide binary floating-point or
scientific-notation text even though both forms are outside the repository's
strict exact-input policy.

## Decision

Route Payables quantity ingress in both SQLite and PostgreSQL through
`parse_exact_amount()`, while retaining the existing positive-quantity and
canonical-text behavior. Validate text length and printable-character rules
before parsing in the PostgreSQL adapter, but preserve the original Python
value for the strict parser so a float cannot be converted into an apparently
safe string first.

This is an exact quantity-input boundary for the bounded Payables workflow. It
does not claim full inventory-unit semantics, statutory accounting, provider
authenticity, settlement, posting, or production assurance.

## Consequences and rollback

Both local and tenant-scoped Payables adapters now share the same rejection of
binary floating-point, non-finite, malformed, missing, and scientific-notation
quantity inputs. Existing exact decimal strings retain their arbitrary-scale
canonical representation. No schema or migration changes are required.
Rollback is a source/test/ADR/execution-record revert with no external-state
mutation.
