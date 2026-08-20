# ADR 0439: Exercise provider adapters through the pinned HTTPS runtime

- Status: accepted
- Date: 2026-08-07
- Scope: `P4-CON-001`, `connectors.boundary`

## Decision

Add a local HTTPS sandbox contract for the CAMT.053 bank-statement source and
the ERPNext GL Entry and Payment Entry readers. The sandbox uses a temporary
localhost certificate, an injected public-address resolver, and the real
`PinnedHttpsGetTransport`. Each source must survive a synthetic 503 retry,
validate its provider response, preserve token/bearer isolation, and retain
its exact endpoint, company/account scope, query, and cursor contract.

## Evidence boundary

The server, certificate, credentials, and payloads are generated per test and
never leave the process. This proves the adapter-to-transport runtime boundary
and failure handling only; it does not prove a bank or ERPNext tenant,
provider-version/dialect compatibility, source authenticity, certificate or
credential lifecycle, settlement, posting, write-back, or production
availability.

## Rollback

Remove `tests/test_connector_provider_tls_sandbox.py`, this ADR, its manifest
entry, and the E-593 execution records. The provider-specific synthetic
transport tests remain unchanged.
