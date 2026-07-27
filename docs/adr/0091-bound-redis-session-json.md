# ADR 0091: Bound tenant-scoped Redis session JSON

- Status: Accepted
- Date: 2026-07-26
- Decision owners: Identity, Platform Architecture, Security, Reliability
- Scope: FI-013 `TenantRedisStore.put_session` and `get_session`

## Context

The optional Redis coordination adapter stores compact session metadata and
loads it through a direct `json.loads`. The value contains a user identifier,
session identifier, bearer-token SHA-256 digest, and expiry timestamp, but had
no byte, graph, duplicate-key, finite-value, closed-field, or timestamp-zone
contract. Malformed values failed generically, while very large or ambiguous
values were parsed before rejection. Redis keys and TTLs were already
tenant-scoped and raw bearer tokens were not accepted.

## Decision

Publish the closed `redis-session-object-v1` schema and named
`redis-session-json-v1` profile:

- allow at most 16,384 UTF-8 bytes, 16 nodes, depth two, exactly no more than
  four object properties, and 256 characters per scalar;
- require exactly `session_id`, `user_id`, `token_hash`, and `expires_at`, all
  as strings; identifiers are non-empty, at most 256 characters, and contain
  no control characters;
- require a lowercase 64-character SHA-256 token digest and an explicit UTC
  ISO timestamp ending in `Z` or `+00:00`; no raw token or implicit timezone is
  accepted;
- retain the established sorted compact ASCII producer text. Producer
  validation and encoding occur before Redis client access;
- decode through the same bounded contract. Corrupt values fail visibly and
  are neither replaced, deleted, nor converted into sentinel sessions;
- preserve tenant-key hashing, TTL units/values, missing-key behavior,
  session-ID/key equality checks, and public dataclass shape;
- extend the existing service-backed Redis test to cover session isolation,
  exact TTL presence, and cleanup without adding a second service skip;
- remove the Redis session direct parser from the exact AST allowlist.

## Consequences

One FI-013 direct call remains: generic database export. One central bounded
parser and one packaged currency-registry parser account for the other two
direct calls.

This slice bounds an optional primitive; it does not claim that Redis sessions
are integrated into the production login/session lifecycle. Live Redis
behavior remains unproved unless `RECONFORGE_TEST_REDIS_URL` is supplied.

## Compatibility and migration

No Redis key format, namespace, hash algorithm, TTL, API/CLI route, dataclass,
or missing-key behavior changes. Values produced by the prior implementation
already contain exactly the four required strings in the same canonical text
and remain readable. Explicit zero-offset timestamps using either `Z` or
`+00:00` remain valid. Undocumented extra/missing fields, non-string coercions,
invalid digests, implicit/non-UTC timestamps, ambiguous JSON, and over-budget
values now fail closed.

## Rollback

Revert the profile, schema, Redis routing, tests, inventory, and governance as
one unit. Existing valid values remain ordinary compact JSON readable by the
prior implementation. Do not scan, rewrite, delete, or extend the TTL of live
session or revocation keys during rollback.
