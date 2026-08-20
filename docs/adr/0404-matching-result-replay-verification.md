# ADR 0404: Verify strategy results against their canonical request before exposure

- **Status:** Accepted
- **Date:** 2026-08-06

## Context

Matching strategy adapters produce digest-bound results that cross worker,
database, and evidence boundaries. Previously each adapter calculated the
digests but had no shared fail-closed verification step at the result
boundary. A corrupted or incorrectly re-bound result could therefore be
returned to a caller if an adapter implementation drifted.

## Decision

Add `MatchingStrategyResult.verify_against(request, manifest_digest)` as the
single replay verifier for strategy outputs. It recomputes the canonical input
digest and result digest, and rejects manifest, input, or output mismatches.
All current indexed, grouped, carry-forward, duplicate-detection, and reversal
strategy adapters invoke the verifier before returning a result.

## Boundary and rollback

This verifies deterministic strategy envelopes; it does not claim PostgreSQL
capacity, distributed consensus, live provider correctness, or independent
algorithm validation. The change is backward compatible for callers that
consume `MatchingStrategyResult`. Rollback removes the verifier calls and this
ADR without data migration.
