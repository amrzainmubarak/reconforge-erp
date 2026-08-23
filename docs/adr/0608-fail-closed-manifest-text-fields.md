# ADR 0608: Fail closed on non-text manifest declarations

## Status

Accepted — 2026-08-23

## Decision

Matching manifests reject non-text or blank deterministic tie-break and
explanation-schema values with the public contract error. They must never
surface an incidental attribute/type error or be coerced into a declaration.

## Boundary

This hardens manifest input handling. It does not establish that the declared
tie-break or explanation schema is semantically correct.

## Rollback

Relaxation requires a versioned contract update and negative tests; silent
coercion is not an acceptable rollback.
