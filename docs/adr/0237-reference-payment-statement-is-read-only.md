# ADR 0237: Reference payment-statement connector is read-only

- Status: accepted
- Date: 2026-08-02

## Decision

Add a provider-neutral synthetic payment-statement connector on the governed
HTTPS executor. Its closed schema validates exact finite Decimal text, unique
line IDs, booking/value-date ordering, cursor/idempotency reads, canonical
digests, and an exact egress allowlist. The manifest exposes read capability
only; it performs no provider write-back.

## Boundary

This is a conformance reference, not a live bank or ERP integration. Provider
credentials, contracts, format licensing, reconciliation against a bank, and
governed write-back remain deployment-owned follow-up work.

## Rollback

Remove the connector, tests, documentation, ADR, and package entry. No
external system or database state is mutated.
