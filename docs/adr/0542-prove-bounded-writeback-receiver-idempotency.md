# ADR 0542: Prove bounded write-back receiver idempotency before vendor claims

- Status: Accepted
- Date: 2026-08-22
- Scope: E-828 receiver-side write-back idempotency conformance

## Context

ReconForge already keeps the original idempotency key across retries and can
recover an uncertain dispatch through a separate status lookup. Those sender
controls do not prove that a receiving provider commits one business effect
when several clients or processes submit the same mutation, nor that reuse of a
key with a different payload is rejected.

A real vendor claim requires an identified external sandbox and its documented
semantics. Before that evidence exists, the connector SDK still needs an
executable receiver contract that adapters can be tested against.

## Decision

Add a provider-neutral, digest-only receiver request and a local SQLite
reference store. The receiver identity and idempotency key form the unique
business-effect identity. Operation and payload digest are immutable bindings;
reusing the key with either changed value fails closed.

The reference store commits an immutable receipt and a synthetic effect in one
`BEGIN IMMEDIATE` transaction. An exact replay returns the original canonical
provider response. Payload bytes and credentials are never persisted.

Retain a closed drill that proves:

- sequential apply/replay produces one effect and an identical response;
- eight spawned processes converge to one apply and seven replays;
- a process exit after commit but before returning a response is recovered by
  replay without another effect;
- same-key payload retargeting, receipt update, and effect deletion are refused;
- an independent SQLite backup retains counts, canonical history, and replay
  identity; and
- the temporary store is removed.

## Security and financial integrity

The store persists only bounded identifiers, SHA-256 digests, a provider
reference, and UTC evidence time. It never receives a currency amount as a
numeric value, changes a posted ledger, or handles production secrets. Direct
receipt/effect mutation is blocked by database triggers, while canonical
history excludes non-deterministic timestamps.

This establishes a reusable receiver conformance contract and same-host
database coordination. It does not establish a live vendor, cross-host
consensus, database failover, settlement finality, accounting posting, or
production exactly-once delivery.

## Compatibility

The feature is additive. Existing sender APIs, write-back lifecycle schemas,
SQLite/PostgreSQL product migrations, connector manifests, and retry behavior
do not change. Adapters may adopt the conformance contract without changing
the default disabled write-back policy.

## Rollback

Remove the additive receiver module, runner, report, schema, tests, exports, and
documentation. No application database migration or user data requires
rollback. Preserve any collected failure evidence; do not reinterpret a
receiver conflict as a successful replay.
