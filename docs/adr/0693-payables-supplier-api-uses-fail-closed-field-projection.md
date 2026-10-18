# ADR 0693: Payables supplier API uses fail-closed field projection

- **Date**: 2026-08-26
- **Status**: Accepted for E-1033

## Context

The Payables supplier save and list routes returned mappings from local SQLite
and tenant-scoped PostgreSQL adapters. The local supplier read path uses a
wide table projection, and either adapter can gain future columns. Returning
those mappings directly would turn storage evolution into an accidental
financial master-data disclosure change.

## Decision

Add `PAYABLES_SUPPLIER_FIELDS` and `project_payables_supplier` to the central
field-access module. Apply the projector to both local and PostgreSQL branches
of `POST /api/v1/payables/suppliers` and `GET /api/v1/payables/suppliers`.
Retain the existing direct supplier response and pagination envelope, reviewed
supplier fields, permissions, and local/server boundaries. Purchase orders,
receipts, supplier invoices, and three-way-match results remain separate
response families and are not implicitly covered by this decision.

## Consequences

Known supplier fields remain available and unknown adapter/storage fields are
excluded before serialization. A synthetic SQLite future-column test and the
field projector contract provide the bounded evidence. This does not establish
universal field-level authorization, external IAM, distributed revocation,
disclosure approval, source authenticity, or production effectiveness.

## Compatibility and rollback

No schema, migration, route, permission, response-envelope, or pagination
change is introduced. Rollback is a code-and-metadata revert of E-1033, its
tests, this ADR, the manifest entry, and execution documentation. Do not
restore unbounded repository-row serialization as an adapter compatibility
fallback.
