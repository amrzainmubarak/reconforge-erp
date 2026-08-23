# ADR 0612: Registry-wide deterministic matching replay profile

Status: Accepted

## Context

Individual strategy tests proved local behavior, but a registry could still
silently omit a family or allow one adapter to drift from the shared JSON
result-envelope verifier.  E-1003 requires explicit strategy identity,
permutation determinism, and replay evidence across the published family set.

## Decision

Maintain `matching-strategy-registry-replay-v1` as a bounded synthetic profile.
It obtains the immutable registry, requires an exact fixture for every
published manifest, executes each strategy twice with reversed records/rates,
round-trips both outputs through the closed result envelope, and compares the
canonical payloads and digests. Any missing fixture, envelope drift, or
permutation difference fails the profile.

The profile is a correctness and evidence contract only. It does not claim
PostgreSQL runtime parity, live provider behavior, production throughput, or
capacity beyond the declared small fixtures.
