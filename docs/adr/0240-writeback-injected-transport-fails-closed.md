# ADR 0240: Governed write-back uses an injected, acknowledgement-bound transport

- Status: accepted
- Date: 2026-08-02

## Decision

Add a transport-injected dispatch boundary for an already approved and
dispatched write-back intent. The adapter receives only intent identity,
operation, idempotency key, and payload digest; it must return an
acknowledgement bound to the original key. Provider exceptions and key
mismatches fail closed without changing the intent state.

## Boundary

The default application performs no network I/O. This is a synthetic
failure-injection and conformance boundary, not a live ERP/bank adapter,
credential provisioning flow, or payment-posting proof.

## Rollback

Remove the injected protocol, dispatch helper, tests, ADR, and execution
entries. No external provider state is touched.
