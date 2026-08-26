# ADR 0654: Make write-back rate-limit reservations atomic and registration-scoped

- Date: 2026-08-26
- Status: accepted
- Scope: process-local `WritebackNetworkExecutor` sender throttling

## Context

The write-back executor used an in-memory next-allowed timestamp keyed only by
`connector_id`. There was no synchronization around the read/update sequence.
Concurrent workers could therefore observe one deadline and all dispatch
without honoring the configured interval. Registrations for different
tenant/workspace scopes or endpoints could also contend merely because they
shared a connector identifier.

## Decision

Reserve the next slot while holding a process-local `threading.Lock`, compute
the wait from the prior deadline, update the lane to the following deadline,
and sleep only after releasing the lock. Key the lane by the immutable
`WritebackNetworkRegistration.digest`, which already binds connector version,
endpoint, policy-relevant registration fields, and bound scope without storing
the credential value.

## Consequences

- Concurrent workers in one executor cannot reuse the same rate-limit slot.
- Distinct registration scopes and endpoints do not share a lane solely because
  they use the same connector ID.
- The guard remains process-local. Multiple worker processes, hosts, or provider
  quota domains still require a separately governed distributed limiter and
  provider-specific contract.
- No request payload, idempotency key, database schema, or public API changes.

## Verification and boundary

E-960 runs 35 focused write-back network tests, including concurrent slot
reservation and cross-scope lane isolation. This does not prove distributed
quota coordination, `Retry-After` semantics, live vendor interoperability,
HA/DR, or production readiness.

## Rollback

Revert the executor lock/key change and remove E-960 documentation. No data or
migration rollback is required.
