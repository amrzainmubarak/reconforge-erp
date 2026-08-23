# ADR 0601: Fail closed on malformed matching mode inputs

## Status

Accepted — 2026-08-23

## Decision

Matching manifests and coverage reports reject non-text or blank mode values at
their public boundaries. The contract does not coerce malformed mode metadata
or let a caller receive an accidental partial coverage report.

## Boundary

This is input-contract hardening only. It does not add a strategy family or
prove that a declared mode is financially correct.

## Rollback

Any relaxation requires a versioned contract update and explicit compatibility
tests; silent coercion is not permitted.
