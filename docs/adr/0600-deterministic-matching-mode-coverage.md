# ADR 0600: Expose deterministic matching mode coverage

## Status

Accepted — 2026-08-23

## Decision

`MatchingStrategyRegistry.coverage_report()` provides a sorted, immutable
report of caller-required modes, registered modes, missing modes, and the
strategy identities that declare each mode. Duplicate required modes and
caller ordering do not change the report.

## Boundary

Mode coverage is an inventory control, not proof of strategy-family
correctness, financial suitability, engine parity, performance, or production
readiness. A mode may still require additional domain and evidence gates.

## Rollback

Removing the report requires replacing its CI contract with an equivalent
machine-readable coverage gate; silently relying on a hand-maintained list is
not an acceptable rollback.
