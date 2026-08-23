# ADR 0573: Current PostgreSQL receiver idempotency runtime evidence

## Status

Accepted — 2026-08-23

## Context

The write-back receiver had a PostgreSQL schema and persistence-free
conformance tests. Receiver-side idempotency and immutability need a live
database observation under the application role before they can be counted as
runtime evidence.

## Decision

Add an environment-gated live test that initializes the fixed receiver schema
with an admin connection, grants only schema/table usage needed by the
application role, and then verifies one atomic receipt/effect, exact replay,
canonical history digest stability, and deletion refusal through the app DSN.
The request payload remains digest-only.

## Limits

The evidence is one local PostgreSQL service and synthetic data. It does not
prove provider transport, secret handling, cross-host recovery, HA/DR, or
production receiver behavior. Without the explicit DSN the gate skips rather
than claiming success.
