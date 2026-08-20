# ADR 0344: Verify the reference REST reader through disposable HTTPS

- **Date**: 2026-08-05
- **Status**: Accepted

## Context

The reference REST connector had strict schema, cursor, retry and digest tests
with an injected transport. The connector should also be exercised through the
actual TLS/HTTP GET path without contacting a vendor or treating a reference
manifest as a live ERP/bank integration.

## Decision

Add a local-only test that serves a bounded JSON page from a disposable HTTPS
server, returns one transient `429` and then a successful page, and drives the
normal `PinnedHttpsGetTransport`, `NetworkConnectorExecutor` and
`ReferenceRestConnector`. The test requires the same idempotency key and cursor
on both attempts, validates the secret-reference header, checks the next
cursor and canonical response digest, and shuts down the server deterministically.

The test clones the reference manifest only to replace its declared destination
with the ephemeral loopback endpoint; it does not weaken production allowlist
validation or change the packaged manifest.

## Consequences

- TLS negotiation, public-address resolution guard, retry, cursor propagation,
  schema projection and digest calculation are exercised together.
- The result is synthetic local transport evidence, not vendor schema
  compatibility, bank authentication, ERP semantics, or production capacity.
- Runtime defaults, migrations and external network behavior are unchanged.

## Verification and rollback

`tests/test_connector_rest_reference.py::test_local_https_rest_sandbox_exercises_real_tls_retry_cursor_and_digest`
is the gate. Rollback removes the test, this ADR, package membership and the
execution-log entry only.
