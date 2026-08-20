# ADR 0343: Verify the write-back transport against a disposable local HTTPS sandbox

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

The provider-neutral write-back transport already had injected failure tests,
but those tests did not exercise a real TLS socket and HTTP server. A stronger
local experiment is useful as long as it cannot be mistaken for an ERP or bank
provider certification.

## Decision

Add a focused test that creates a short-lived localhost certificate, serves a
disposable HTTPS provider endpoint, injects the normal pinned transport with a
loopback-only test connection factory, and returns two transient `503`
responses followed by a digest-valid acknowledgement. The test requires the
same idempotency key and payload on all attempts, validates the bearer secret
is sent only to the transport, and verifies that the receipt does not contain
the secret.

The resolver still returns a public test address so the production public-DNS
guard remains active; the test factory deliberately maps that address to the
disposable listener and never contacts the internet.

## Consequences

- TLS negotiation, HTTP request shape, retry behavior, acknowledgement binding
  and secret isolation are exercised together in one reproducible sandbox.
- This is stronger than a pure fake transport but remains synthetic. It does
  not prove a vendor API contract, vault interoperability, accounting posting,
  external network behavior, or production write-back.
- No runtime defaults, credentials, migrations or provider activation change.

## Verification and rollback

`tests/test_connector_writeback_network.py::test_local_https_writeback_sandbox_exercises_real_tls_retry_and_idempotency`
is the gate. Rollback removes the test, this ADR, package membership and the
execution-log entry without changing application state.
