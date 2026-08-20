# ADR 0513: Prove ERPNext Payment Entry intent persistence under PostgreSQL RLS

## Context

The Payment Entry write-back contract had local API and pinned-TLS evidence,
but its provider-specific intent had not been exercised through the real
PostgreSQL append-only/RLS repository.

## Decision

Add an unskipped-when-configured server-boundary test that creates a disposable
tenant and non-privileged application role, persists the Payment Entry intent
through proposal, independent approval, dispatch, and acknowledgement, then
checks idempotent replay, digest binding, sibling-tenant denial, optimistic
version conflict, and database immutability. The payload remains a
`docstatus=0` synthetic draft; no provider network call is made.

## Consequences

- PostgreSQL persistence evidence now covers the provider-specific Payment
  Entry operation rather than only a generic write-back operation.
- The test is single-node, synthetic, and dependent on the disposable service
  configured by CI; it does not prove ERPNext interoperability, posting,
  compensation, or production availability.

## Rollback

Revert the test and E-702/D-507 records together. No migration or customer
data is changed.
