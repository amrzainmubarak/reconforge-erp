# ADR 0221: Reference REST connector is read-only and schema-closed

- Status: accepted
- Date: 2026-08-02

## Decision

Ship one provider-neutral synthetic REST reference connector on top of the existing governed HTTPS executor. It accepts only exact allowlisted HTTPS egress, secret references, bounded cursor/idempotency reads, and a closed canonical record page. It rejects duplicate IDs, non-finite/non-exact amounts, unknown fields, and malformed dates. The connector has read capability only and no dynamic package loading or write-back.

## Consequences

ReconForge now has an executable reference integration and conformance surface without pretending to support SAP, Odoo, a bank, or a production provider. Credentials and customer data remain deployment-owned. Acknowledgement reconciliation, compensation, and write-back require a separate approved contract.

## Rollback

Remove the reference connector, tests, docs, ADR, and manifest entries. No external system or database state is mutated.
