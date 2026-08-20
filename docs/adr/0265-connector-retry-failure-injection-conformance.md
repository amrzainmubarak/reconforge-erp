# ADR 0265: Connector retry failure injection is a reusable synthetic gate

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Add a shared conformance helper that injects a bounded sequence of retryable
HTTP responses into a caller-supplied connector executor, requires eventual
success within the manifest retry ceiling, and checks that transient response
bodies do not leak into the successful result.

## Boundary

The helper is provider-neutral and entirely synthetic. It proves retry
contract behavior only; it does not prove vendor semantics, live credentials,
network availability, provider sandbox conformance, or write-back safety.

## Reversibility

The helper and tests are additive. Removing them changes no connector manifest,
database schema, network policy, or runtime default.
