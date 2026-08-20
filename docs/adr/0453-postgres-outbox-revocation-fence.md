# ADR 0453: Re-evaluate worker policy before outbox publication

- Status: accepted
- Date: 2026-08-09
- Scope: PostgreSQL transactional-outbox worker authorization

## Decision

The PostgreSQL outbox worker must re-evaluate the configured central service-
account policy immediately before invoking the injected publisher for each
claimed event. The existing lane-level check remains the pre-connection and
pre-claim guard; the per-event check closes the revocation window between a
batch claim and the external publication side effect.

If the decision is denied, the worker fails closed before publisher I/O and
does not acknowledge the event. The database lease therefore remains subject
to the existing bounded lease-recovery path. After a successful publication,
the worker acknowledges the event without a second policy gate so a revocation
that arrives after the external side effect cannot create a duplicate on
replay.

The guard is still opt-in through `OutboxWorkerSettings` so Community/local
workers without a central policy supplier preserve their compatibility
contract. The publisher remains injected and provider-neutral.

## Non-goals and rollback

This does not provide distributed policy-cache invalidation, broker exactly-
once delivery, provider-level compensation, or HA/DR. Rollback is a code-only
revert of the per-event guard and its regression test; no migration or
persisted-data change is required.

## Evidence boundary

The focused PostgreSQL outbox contract proves a policy change between claim
and publication prevents publisher invocation and published acknowledgment.
It is synthetic/fake-connection evidence and does not establish external
provider behavior, cross-process revocation latency, or production SLOs.
