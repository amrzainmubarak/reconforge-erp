# ADR 0098: Engine matrix lower-bound compatibility

- Status: Accepted
- Date: 2026-07-27

## Context

The supported engine manifest declares Python 3.11 and 3.12 with exact lower
and current-compatible NumPy, Pandas, and DuckDB versions. Its first real local
lower-bound execution exposed three independent compatibility defects: the CI
override suppressed transitive dependencies, Pandas 2.2 rejects
`fillna(value=None)`, and DuckDB 1.0 returns a blank CSV text field as `None`
where the Pandas reader returns an empty string.

The final difference affected canonical record identity because shared text
coercion converted the DuckDB null to the literal `"None"`. Golden counts and
financial values were unchanged, but accepting that digest drift would violate
the cross-engine contract.

## Decision

1. Preserve the four exact direct engine pins and binary-wheel requirement,
   while allowing their transitive dependencies to resolve.
2. Remove the redundant frame-wide `fillna(value=None)` from signature
   canonicalization; scalar canonicalizers already map missing values to null.
3. Normalize missing required non-date/non-numeric text to an empty string
   before trimming and identity calculation.
4. Do not rewrite golden outputs. Require all four cells to pass with zero
   skips locally, then require the separately stated identified hosted run
   before closing P0-009.

## Consequences

Pandas 2.2 obtains its required timezone dependency. Pandas 2/3 signature
canonicalization follows the same scalar path, and blank required text has one
representation across supported DuckDB readers. Existing signature-v1 digest
and strict signature-v3 tests remain unchanged. The reader change is limited
to missing required text; numeric/date parsing and data-quality behavior are
unchanged.

## Evidence and limitations

E-083 records exact interpreter/package versions, per-cell JUnit hashes, the
failed attempts, and the full regression. This ADR is not hosted execution,
performance, arbitrary-version compatibility, live PostgreSQL recovery, or a
production-readiness claim.

## Rollback

Revert this ADR, the dependency-aware CI override, scalar signature change, and
required-text null normalization together. Such a rollback reopens P0-009 and
must not retain any supported lower-bound parity claim.
