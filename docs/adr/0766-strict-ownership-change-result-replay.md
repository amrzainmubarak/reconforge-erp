# ADR 0766: Strict ownership-change result replay

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: Ownership-change result replay verified the result digest and
  summed serialized line amounts with `Decimal(text)`. A payload with a
  recomputed digest could therefore carry scientific, non-finite, or
  non-canonical financial text into the balance check.
- **Decision**: Validate result-level percentage and derived-effect fields with
  the strict exact parser and require their canonical decimal text. Restore
  every serialized line amount through `Money.from_canonical_dict()` before
  summing, which also enforces currency precision and embedded currency-policy
  and registry provenance. Require each line currency to match the result
  reporting currency.
- **Rationale**: Digest integrity does not replace semantic validation. A
  persisted financial artifact must remain safe even when an attacker or
  corrupted transport supplies a freshly recomputed digest.
- **Safety boundary**: This hardens non-posting ownership-change verification
  and PostgreSQL replay only. It does not add statutory accounting treatment,
  journal posting, external provider behavior, or autonomous approval.
- **Compatibility**: Existing typed results remain valid, including fixed
  currency-precision strings such as `100.00`; scalar result fields retain
  their existing canonical representation. Previously accepted re-signed
  payloads with invalid financial text now fail closed.
- **Verification**: Domain, PostgreSQL, and API ownership-change tests cover
  valid replay plus re-signed scientific, non-finite, and non-canonical values.
  Full regression, static/security gates, package build, and manifest
  membership are recorded in E-1106.
- **Rollback**: Revert E-1106, ADR 0766, the verifier/test changes, manifest
  entry, and execution records together. No persisted artifact is rewritten.
