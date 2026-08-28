# ADR 0606: Enforce the published strategy ID slug at runtime

## Status

Accepted — 2026-08-23

## Decision

`MatchingStrategyManifest` enforces the same lowercase slug pattern as the
published manifest schema: a lowercase alphanumeric start followed by
lowercase alphanumerics or hyphens, with bounded length. Runtime admission and
offline schema validation therefore reject the same identity forms.

## Boundary

This prevents identity drift and ambiguous registry keys. It does not prove
ownership, uniqueness across organizations, or semantic compatibility.

## Rollback

Any change requires a versioned schema/runtime migration and regenerated
manifest digests; accepting schema-invalid IDs is not an allowed rollback.
