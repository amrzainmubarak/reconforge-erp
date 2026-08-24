# ADR 0618: PostgreSQL matching adapters preserve canonical zero values

- Date: 2026-08-24
- Status: accepted
- Scope: PostgreSQL grouped and sequential matching input adapters

## Context

The grouped and sequential PostgreSQL adapters selected canonical columns with
Python `or` expressions. A valid `Decimal("0")` is false-y, so a zero-valued
`amount_decimal` could be replaced by an amount from a less authoritative
field or from `attributes_json`. The same pattern made canonical identity,
date, and currency precedence depend on truthiness rather than on whether a
database value was present. That could alter a matching request without a
data-quality error and would weaken replay evidence.

## Decision

Use explicit `None` checks for database-owned values in both adapters. A
present canonical value, including numeric zero or an empty value that must be
validated downstream, is retained. Only `None` permits fallback to a legacy
column or JSON attribute. The adapters continue to validate required identity,
amount, and date fields and do not broaden any matching strategy or currency
policy.

## Consequences

- Valid zero amounts remain zero and cannot be shadowed by JSON attributes.
- Canonical source identity, date, and currency columns retain precedence over
  untrusted attribute payloads.
- Malformed present values now reach the existing fail-closed validation path
  instead of being silently replaced by a fallback.
- Existing non-null legacy compatibility inputs continue to use their defined
  fallback path; no schema or public API version changes.

## Reversibility

Revert the two adapter helper changes and their focused regression tests if a
versioned compatibility reader requires different precedence. Such a revert
would reintroduce the zero-value shadowing risk and therefore requires a new
ADR and explicit evidence.
