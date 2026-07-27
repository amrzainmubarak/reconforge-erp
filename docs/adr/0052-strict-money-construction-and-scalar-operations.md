# ADR 0052: Add Strict Money Construction and Scalar Operations

- Status: Accepted
- Date: 2026-07-25
- Scope: `Money` construction and scalar multiplication/division compatibility

## Context

`Money` already accepted an explicit financial-input policy, and current
reconciliation writers passed that policy. Its default must remain legacy-v1
until a breaking-release boundary, but direct legacy construction suppressed
the deprecation warning emitted by the canonical parser. The scalar `*` and `/`
operators likewise retain historical finite-float compatibility and cannot take
a policy keyword.

This left strict behavior available only through a low-level constructor
argument and left no clearly named current operation for scalar arithmetic.
Changing the constructor default or dunder operators in place would be a public
behavior break.

## Decision

1. Add `Money.from_exact`, `Money.multiply_exact`, and `Money.divide_exact`.
   Each uses strict-financial-input-v2 and rejects Python/NumPy floating scalars
   before financial arithmetic.
2. Keep the constructor default and `*`/`/` behavior as legacy-v1 compatibility
   until an approved breaking release. A successful legacy construction from a
   binary floating scalar now emits the same call-site-deduplicated deprecation
   warning as the public parser; strict rejection and invalid inputs do not emit
   a misleading compatibility warning.
3. Require every production `Money(...)` constructor call outside
   `utils/money.py` to spell `input_policy=` explicitly. Extend the AST
   compatibility-perimeter test to enforce this rule.
4. Keep P0-005 open. The compatibility constructor/default operators and other
   classified financial ingress readers remain supported migration boundaries.

## Consequences

- New code has discoverable strict construction and scalar-operation APIs.
- Existing exact integer/text/Decimal operator results and finite-float
  compatibility results remain unchanged.
- Legacy binary-float construction is no longer silent, so test/runtime warning
  counts can increase at distinct compatibility call sites.
- No database schema, serialized Money schema, currency policy, digest, API
  route, or persisted reconciliation contract changes.

## Rollback

Do not remove the warning or route current production constructors back to an
implicit policy. The exact methods may be replaced only with an equivalent
strict-v2 boundary and rejection tests. Changing the public constructor or
dunder defaults requires a breaking-release ADR, migration guidance, release
notes, and an explicit legacy reader for the supported compatibility window.
