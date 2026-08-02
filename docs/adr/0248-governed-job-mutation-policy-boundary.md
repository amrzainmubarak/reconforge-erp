# ADR 0248: Durable-job mutations use an explicit policy boundary

- **Status:** Accepted
- **Date:** 2026-08-02

## Decision

Add `GovernedDurableJobApplicationService` as an opt-in policy boundary around
job submit and cancel mutations. It requires the caller's identity to match
the policy context, evaluates the central permission/tenant/workspace/SoD
rules, and only then invokes the existing durable lifecycle service. The
legacy service remains compatible for internal callers that have their own
authorization boundary.

## Boundary

This closes the typed application boundary and deny-before-repository tests.
It does not claim every API, export, scheduler, or worker route is migrated,
nor does it close federation or cache invalidation. A later live PostgreSQL
durable-job gate may promote this wrapper independently of those surface gaps.
