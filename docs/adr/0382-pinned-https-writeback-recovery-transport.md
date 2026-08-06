# ADR 0382: Pinned HTTPS write-back recovery transport

- **Status**: Accepted
- **Date**: 2026-08-06
- **Scope**: Experimental, provider-neutral transport boundary

## Context

The write-back executor could recover an uncertain mutation only through an
injected lookup object. That protected the no-second-POST invariant, but a
real HTTPS adapter was still missing. A generic transport must not guess a
vendor URL or encode an idempotency key into an unsafe query string.

## Decision

Add an optional, exact `recovery_endpoint` to the immutable network
registration. When present it must be HTTPS, contain no credentials/query/
fragment, and be explicitly listed in `egress_destinations`. Add
`PinnedHttpsRecoveryTransport`, which resolves and pins a public address,
performs a bounded GET with the original idempotency key header, never sends a
request body, never follows redirects, and returns the same bounded response
envelope used by the executor. The executor uses the declared recovery endpoint
and falls back to the mutation endpoint only for backward-compatible injected
transports.

## Consequences

- Operators can wire a provider-specific status URL without adding vendor code
  or permitting arbitrary endpoint construction.
- Recovery remains opt-in, authenticated through the existing short-lived
  secret resolution, and fail-closed on provider response binding.
- A declared URL is not evidence that a vendor implements idempotency status;
  vendor conformance and provider semantics remain deployment-owned.

## Verification and rollback

Focused transport tests pass, including a disposable local TLS sandbox that
performs three real POST retries followed by one real pinned GET recovery with
zero additional POSTs. Removing the field, transport, tests, ADR, and evidence
is reversible; no migration or persisted-data change is involved.
