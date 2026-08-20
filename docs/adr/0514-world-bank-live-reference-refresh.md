# ADR 0514: Record a bounded live World Bank reference refresh

## Context

ReconForge includes a public, no-auth World Bank reference connector. Its live
endpoint is intentionally opt-in because public data can change and the
connector is not a financial-provider integration.

## Decision

Record one successful bounded HTTPS refresh on 2026-08-11 using the pinned
transport and the declared first 1,000-row page. Preserve request/response
digests, row count, attempt count, and the observed source count as runtime
evidence. Keep the test opt-in and retain synthetic fixtures as the deterministic
regression source.

## Consequences

This refresh demonstrates current endpoint reachability and schema acceptance
for the public reference source. It does not establish freshness guarantees,
provider SLA, source authenticity beyond the transport/shape checks, ERP or
bank interoperability, credentials, write-back, or production availability.

## Rollback

Remove the refresh evidence and ADR entry; no code, secret, or external state
is changed.
