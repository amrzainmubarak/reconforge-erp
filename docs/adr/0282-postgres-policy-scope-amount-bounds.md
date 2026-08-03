# ADR 0282: PostgreSQL policy scopes preserve exact amount bounds

## Status

Accepted for the bounded Phase 4 IAM scope-projection slice.

## Context

The central policy contract already accepts finite `Decimal` minimum and
maximum amounts, but migration 0058 persisted only resource dimensions. A
PostgreSQL policy snapshot therefore could not distinguish two otherwise
identical grants whose authority applied to different amount ranges.

## Decision

Add migration `0059_pg_policy_amt_bounds` with nullable PostgreSQL `NUMERIC`
minimum and maximum bounds on `identity_role_permission_scopes`. Bounds are
accepted only when finite, ordered, and within the bounded Decimal contract;
the adapter converts them to exact `Decimal` values before constructing the
replayable `PolicyScope`. Scope overlap treats an unbounded side as open and
uses inclusive endpoints. Existing v1 scope payloads omit absent bounds and
retain their previous digest representation.

## Safety boundary

- The bounds are policy-analysis evidence, not proof that every API, job,
  export, or UI action enforces them. Route-wide authorization migration is a
  separate gate.
- A bound has no implicit currency. Callers must not use a scalar bound across
  currencies without an explicit currency policy; this slice does not add
  currency conversion or posting behavior.
- Scope identity, including amount bounds, remains immutable. Only one
  independent active-to-revoked transition is permitted, and tenant RLS is
  forced.
- Runtime evidence is limited to the synthetic single-node PostgreSQL CI
  service under the non-privileged application role; federation, distributed
  cache invalidation, and production SLO/HA evidence remain open.

## Rollback

Downgrade refuses if any amount-bound evidence exists. After a governed
retention decision and an empty amount-bound set, it removes only the new
columns and constraints and restores the migration-0058 uniqueness and
append-only trigger definition.
