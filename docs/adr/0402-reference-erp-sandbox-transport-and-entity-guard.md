# ADR-0402: Exercise the ERP reference connector through the real governed HTTPS sandbox

## Status

Accepted — 2026-08-06.

## Context

`reference-erp-readonly` already validates a closed ledger-line page using an
injected transport, but that alone does not exercise TLS, retry, cursor, secret
header, public-address pinning, or the actual connector composition. The page
schema also needs a caller-side guard when a workflow expects one legal entity.

## Decision

Add an optional `expected_entity_code` argument to `ReferenceErpConnector.read_page`.
After schema validation, every returned line must match the expected code or
the read fails closed with a stable scope-mismatch error. This is a
post-response assertion and does not widen the endpoint or persist the
expectation in a financial result.

Add a disposable loopback HTTPS sandbox test using the real
`PinnedHttpsGetTransport` and `NetworkConnectorExecutor`. The sandbox uses a
short-lived synthetic certificate, a public-address resolver test seam, one
transient 503 followed by a 200 page, a cursor header, and a secret reference.
The test verifies retry bounds, idempotency/cursor propagation, TLS hostname
verification, address pinning, entity guard, canonical response digest, and
secret non-disclosure.

## Boundary

This is reproducible provider-neutral transport evidence. It is not a live ERP
vendor connection, provider-version certification, credential-vault proof,
accounting posting, write-back, HA/DR, or production-readiness claim.

## Rollback

Remove the optional guard, sandbox test, ADR, manifest entry, and evidence
record. Existing callers that omit `expected_entity_code` remain compatible.
