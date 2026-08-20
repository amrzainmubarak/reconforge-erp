# ADR 0403: Exercise the payment-statement reference connector through the governed HTTPS sandbox

- **Status:** Accepted
- **Date:** 2026-08-06

## Context

The provider-neutral payment-statement connector had closed schema and injected
transport tests, but no composition proof for its real pinned HTTPS GET path.
Its caller also could not bind a page to the expected bank-account scope after
schema validation.

## Decision

Add an optional `expected_account_id` guard to
`ReferencePaymentStatementConnector.read_page`. When supplied, every validated
record must carry the exact account identifier; empty or overlong scope values
and mismatches fail closed.

Add a disposable TLS sandbox test that uses the real `PinnedHttpsGetTransport`
and `NetworkConnectorExecutor`. The test injects only a short-lived synthetic
certificate, a public-address resolver seam, and one transient 503 response.
It verifies retry bounds, cursor/idempotency headers, address pinning, the
secret-reference header, canonical response digest, account scope, and secret
redaction.

## Boundary and rollback

This is provider-neutral loopback evidence only. It does not prove a live bank,
licensed statement dialect, vault operation, settlement, payment initiation,
write-back, HA/DR, or production readiness. Removing the guard, test, ADR,
documentation, and manifest membership is a data-free rollback; existing
callers that omit the guard remain compatible.
