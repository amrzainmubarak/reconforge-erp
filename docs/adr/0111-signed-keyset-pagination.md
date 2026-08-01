# ADR 0111: Signed, context-bound keyset pagination

- Status: Accepted
- Date: 2026-07-27

## Context

Offset pagination is compatible and simple, but concurrent inserts and deletes
can repeat or skip records. Public cursors also cannot be trusted as query
parameters: a client may mutate their position, ordering, or filter context.

## Decision

Use a versioned canonical JSON position authenticated with HMAC-SHA-256 and an
operator-owned key of at least 32 bytes. Bind each cursor to an allowlisted sort
name, direction, stable record ID tie-breaker, and a digest of tenant/resource/
filter context. Decode with strict base64url, signature, shape, type, size,
depth, and collection checks before comparing any position.

The local evidence list exposes this contract through explicit
`pagination=cursor`; its existing offset mode remains the default. A signing
key must be configured explicitly and is never generated per process. The
token is authenticated and encoded, not encrypted; callers must not place
secret filter values in it. PostgreSQL evidence cursor mode fails explicitly
until a native keyset query exists rather than truncating an in-memory scan.

## Consequences

Duplicate sort values traverse without skips or repeats, and tokens fail when
the filter, tenant, sort, direction, payload, or signature changes. Inserts
before the boundary and deletions from earlier pages do not shift later pages.
Operators must provision and rotate a durable signing key; key rotation
invalidates outstanding cursors. Native PostgreSQL keyset execution remains a
separate enterprise-backend gate.
