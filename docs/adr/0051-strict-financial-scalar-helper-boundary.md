# ADR 0051: Keep Current Scalar Arithmetic off Legacy Financial Readers

- Status: Accepted
- Date: 2026-07-25
- Scope: Public money rounding, difference, and tolerance helper compatibility

## Context

ADR 0040 introduced strict and legacy amount parsers, but the public
`round_money`, `money_difference`, and `within_tolerance` helpers still have
legacy-v1 signatures and behavior. Changing those names in place would break
programmatic callers before a declared breaking-release boundary. Leaving
internal callers on them, however, would make it easy for a new production path
to accept a Python or NumPy floating scalar through the compatibility reader
without selecting that policy consciously.

The remaining callers had two distinct boundaries. Platform amount bucketing
already receives a validated `Decimal`. Rule evaluation and period-artifact
comparison still accept historical YAML/CSV/Python values, so their legacy
conversion cannot be removed safely in this slice.

## Decision

1. Add `round_exact_money`, `exact_money_difference`, and
   `within_exact_tolerance`. They call the strict-v2 parser and reject binary
   floating-point before conversion.
2. Keep the three historical helper names and results unchanged as external
   legacy-v1 compatibility readers. Their existing deprecation warning remains
   the migration signal.
3. Move every production scalar operation to the exact helper names. Platform
   bucketing passes its existing `Decimal` directly. Rules and period comparison
   isolate their still-compatible parsing first and pass only the resulting
   `Decimal` into exact arithmetic.
4. Add a source-AST regression that fails if production code outside
   `utils/money.py` calls any of the three legacy helper names.
5. Keep P0-005 open. The `Money` constructor/scalar operators and named
   variance, anonymizer, generator, Studio, configuration, rule, and period
   compatibility readers still require staged migration or an approved
   breaking-release boundary.

## Consequences

- New internal rounding/tolerance work has a fail-closed current entry point.
- Compatibility is localized and visible rather than silently mixed into
  current scalar arithmetic.
- The lexical float count does not fall merely because the old type signatures
  must remain. This slice proves call-site isolation, not removal of every
  compatibility reader.
- Existing callers of the historical names keep their return values and warning
  behavior; no API, schema, persisted artifact, or digest changes.

## Rollback

The exact helpers may be replaced only by another strict-v2 path with the same
binary-float rejection tests. Do not route production code back through the
legacy helper names or remove the AST guard. If an artifact/rule compatibility
reader is later made strict, version its ingress contract and retain an explicit
reader for historical inputs until the documented compatibility window closes.
