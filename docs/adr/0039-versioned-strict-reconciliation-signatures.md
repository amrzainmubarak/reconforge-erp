# ADR 0039: Version Strict Reconciliation Signatures

- Status: Accepted; current-writer selection superseded by ADR 0042
- Date: 2026-07-25
- Scope: Pandas/DuckDB reconciliation result identity and financial-input compatibility

## Context

The original reconciliation signature used one generic JSON serializer for
identifiers, dates, suggestion scores, and financial result columns. Upstream
matching normally emitted exact `Decimal` values, but the signature boundary
did not enforce that contract. A direct or future backend caller could therefore
place an IEEE-754 value, including `NaN`, in `stock_amount`, `gl_amount`, or
`value_difference` and have it serialized or treated as missing.

Changing the serializer in place would invalidate every historical digest
without identifying why. Separately, public financial helpers still accept
finite IEEE-754 values as compatibility inputs. Removing those inputs without a
versioned migration would break existing library callers.

## Decision

ADR 0042 later makes `reconciliation-signature-v3` the current writer so record
instance identity can be covered without changing either historical digest.
The v1/v2 contracts below remain accepted replay formats.

Define two explicit reconciliation signature policies:

- `reconciliation-signature-v1` reproduces the historical generic serializer,
  including its legacy financial-input behavior. It is available only when a
  caller requests it explicitly.
- `reconciliation-signature-v2` was the current writer for this decision. Its payload includes the
  policy identifier. It rejects binary floating-point and boolean values in the
  three financial result columns before missing-value handling, accepts only
  finite `Decimal`, integer, or exact plain-decimal text, and hashes one
  normalized plain-decimal representation.

Non-financial `confidence_score` and `reference_similarity` values retain their
existing representation because they are suggestions, not amounts or approval
authority. Both engines return the digest and its policy identifier together in
`EngineResult`.

For the wider financial ingress migration, retain legacy readers only behind an
explicitly named v1 compatibility policy while additive strict readers are
introduced. Migrate internal decision paths to strict readers and record the
remaining public compatibility surface. Default rejection/removal of v1 inputs
requires a documented breaking-release boundary; it must not happen through a
silent behavioral change.

## Consequences

- Equal exact amounts expressed as `1.2500`, `1.25`, integer zero, or canonical
  text have one v2 signature representation.
- Financial `NaN` cannot disappear into a null signature cell because type
  rejection runs first.
- V2 digests intentionally differ from v1 digests even for equal decisions. A
  digest without its policy identifier is insufficient evidence.
- The v1 golden regression preserves historical replay while new engine results
  fail closed at the financial signature boundary.
- The remaining legacy financial readers are not approved indefinitely; their
  strict/deprecation implementation remains part of P0-005.

## Rollback

An operator may explicitly reproduce a historical digest with v1. Do not make
v1 the implicit writer again. If a v2 integration must be rolled back, preserve
both the v2 digest and policy identifier and regenerate only with an explicitly
recorded v1 policy; never relabel one digest as the other.
