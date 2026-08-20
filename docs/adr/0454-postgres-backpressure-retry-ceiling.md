# ADR 0454: Bound PostgreSQL backpressure submission retries

- Status: accepted
- Date: 2026-08-09
- Scope: `P4-SCL-001` PostgreSQL durable-job benchmark producer

## Decision

The bounded PostgreSQL backpressure profile uses a finite submission-attempt
budget and capped exponential delay when the atomic queue cap rejects a
producer. The default profile permits at most 1,000 attempts per job, starts
at 2 ms, and caps the delay at 250 ms. A producer raises the existing
`DurableJobBackpressureError` when the budget is exhausted; it never loops
forever and never mutates a rejected row.

The retry helper accepts an injected sleep function for deterministic unit and
failure-injection tests. The profile's structural manifest remains compatible;
observed retry counts and wall time remain observations rather than capacity
claims.

## Non-goals and rollback

This does not establish throughput, queue fairness, broker delivery semantics,
HA/DR, or production retry defaults. Rollback is a code-only revert of the
retry helper, profile validation fields, focused tests, and documentation; no
database migration or persisted-data change is required.

## Evidence boundary

Focused tests prove successful recovery within the budget, capped backoff, and
finite failure after repeated queue-cap refusal. The live PostgreSQL profile
remains capability-gated and retains its existing one-host synthetic limits.
