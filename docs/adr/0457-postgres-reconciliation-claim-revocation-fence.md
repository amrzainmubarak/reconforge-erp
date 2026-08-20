# ADR 0457: Recheck reconciliation policy before claiming a run

- **Status:** Accepted
- **Date:** 2026-08-09
- **Decision owners:** ReconForge maintainers

## Context

The PostgreSQL reconciliation worker checked its service-account policy before
opening the claim transaction. A permission could be revoked while the
connection was being opened or the run scope was being resolved, immediately
before the durable run claim.

## Decision

Retain the early policy check and add a second exact tenant/workspace/entity
check inside the fresh transaction immediately before `claim_run`. A denial is
raised as a dedicated no-effect policy error and does not mark the queued run
as a matcher failure. The connection is still closed by the transaction
boundary.

## Consequences

- Revocation in the claim window fails closed before the run lease or status is
  mutated.
- Matcher failures continue to use the existing retryable `Failed` transition;
  only the dedicated policy-denial path bypasses that transition.
- This is process-local supplier evidence. Distributed policy invalidation,
  live PostgreSQL multi-host behavior, queue HA/DR, and production IAM remain
  unproven.
