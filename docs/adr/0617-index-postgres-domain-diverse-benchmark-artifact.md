# ADR 0617: Index the PostgreSQL domain-diverse benchmark artifact

- Date: 2026-08-24
- Status: accepted
- Scope: benchmark provenance and claim wording only

## Context

The current PostgreSQL domain-diverse runtime artifact was already retained in
the source distribution and referenced by execution evidence, but it was not
present in `benchmark-evidence-index-v1`. That left the selected artifact
verifier unable to recompute its canonical file hash or enforce its digest
field and claim-boundary declaration.

## Decision

Add the exact current JSON artifact to
`docs/execution/benchmarks/INDEX.v1.json` with its canonical-LF SHA-256,
`effect_set_digest` and `manifest_digest` as the only evidence digest fields,
`postgresql_matching` as its workload family, and `partial` status. Extend the
verifier contract test from twelve to thirteen selected artifacts and add a
claims-matrix row that keeps the one-host synthetic and non-capacity limits
explicit.

## Consequences

- The benchmark verifier now detects tampering or path drift for the
  domain-diverse PostgreSQL artifact before test collection completes.
- The artifact is discoverable through the same provenance index as the
  homogeneous PostgreSQL profile and remains explicitly partial.
- No runtime, database schema, matching rule, provider, posting, HA/DR, or
  production-readiness claim is widened by this decision.

## Reversibility

If the artifact is superseded, remove its index entry and the focused count and
claims assertions together with the artifact/evidence record. Existing
homogeneous PostgreSQL entries and runtime behavior are unaffected.
