# ADR 0569: Closed JSON envelope for matching strategy results

## Status

Accepted — 2026-08-23

## Context

Workers and persistence adapters need to move matching evidence across process
and backend boundaries. Ad-hoc projections can omit a digest or silently
coerce a tuple/Decimal representation, weakening replay verification.

## Decision

`MatchingStrategyResult` exposes `to_payload()` and `from_payload()` for one
closed JSON-safe envelope. The envelope contains exactly the strategy identity,
version, explanation schema, manifest/input/decision digests, results, and
exceptions. Reconstruction rejects unknown fields, non-array collections, and
non-object entries. The reconstructed result must pass identity/version and
digest verification before use.

## Consequences

- Transport is backend-neutral and deterministic.
- Consumers have one canonical replay boundary instead of hand-built maps.
- Existing worker projections remain compatible and can migrate incrementally.
- This does not prove a live PostgreSQL or cross-host runtime; those remain
  separate evidence gates.

## Rollback

Revert the envelope methods and their contract tests. No schema migration is
required because this is a process-boundary contract.
