# ADR 0599: Fail closed on incomplete matching strategy declarations

## Status

Accepted — 2026-08-23

## Decision

`MatchingStrategyManifest` rejects an unsupported maturity and rejects blank
deterministic tie-break or explanation-schema declarations at construction
time. A strategy cannot enter the registry or produce a digest unless its
reviewable determinism and explanation contract is explicitly declared.

## Boundary

This protects the strategy contract and registry admission. It does not claim
that a declared algorithm is financially correct, that every strategy family
required by the product target exists, or that a strategy has passed a domain
validation or performance gate.

## Rollback

Reverting this decision requires a versioned contract change and regenerated
strategy manifests/digests; silently accepting incomplete manifests is not an
allowed rollback.
