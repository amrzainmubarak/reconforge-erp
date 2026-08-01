# ADR 0116: Versioned matching strategy contract

- Status: Accepted
- Date: 2026-07-27

## Context

The current indexed matcher has deterministic behavior and explanations, but
callers bind directly to one service signature. Adding grouped, fee, netting,
or FX strategies without an explicit contract would mix capabilities, limits,
and evidence semantics and make replay dependent on implicit code state.

## Decision

Introduce a backend-neutral `MatchingStrategy` protocol with immutable request,
result, limit, and manifest types plus an immutable registry keyed by exact ID
and semantic version. Publish a schema-validated strategy manifest and bind
each execution to manifest, permutation-invariant normalized input, and complete
decision digests. Reject binary floats, non-finite Decimal values, colliding
field names, unsupported values, invalid tolerance, and declared limit excess.
Expose the current indexed composite one-to-one engine through a compatibility
adapter that fixes all many-side flags to false and preserves existing result,
exception, financial-input, record-identity, tie-break, and explanation behavior.

## Consequences

New strategies can be selected and replayed without changing the core caller
contract, while the first adapter remains compatible with current outputs.
The declared candidate-per-record ceiling is bounded by the right input ceiling;
it is deliberately conservative and is not performance evidence. Candidate
budget accounting, explicit inclusion/exclusion records, grouped matching,
ambiguity v2, and benchmark thresholds remain separate Phase 1 tasks.

## Reversibility

Existing `MatchingService.match_records` remains unchanged. Removing the adapter
does not change stored data, but published manifests and digests must remain
readable for any artifacts produced under this contract.
