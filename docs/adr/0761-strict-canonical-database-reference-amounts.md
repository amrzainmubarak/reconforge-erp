# ADR 0761: Strict canonical database-reference amounts

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: The shared `DatabaseRecordRow` model validated amounts with
  `Decimal(value)` but returned the caller's original string. This admitted
  scientific-notation text and allowed equivalent forms such as `1,000.00`
  and `1000` to produce different response digests.
- **Decision**: Validate shared database-reference amounts with
  `parse_exact_amount()` and return `canonical_decimal_text()` from the field
  validator. Preserve the existing finite-value validation wording and allow
  the parser's supported exact accounting forms.
- **Rationale**: Every database-reference connector must expose a finite,
  exact, deterministic amount representation before scope, duplicate, and
  reconciliation processing. Canonicalization makes response fingerprints
  independent of harmless input formatting.
- **Compatibility**: Exact numeric values remain accepted; finite values may
  now be returned in canonical plain text rather than their input formatting.
  Scientific-notation strings and other malformed values now fail closed.
  Existing non-finite validation wording remains stable.
- **Verification**: Shared database-reference tests cover canonicalization,
  scientific-notation refusal, non-finite refusal, scope/duplicate behavior,
  and PostgreSQL transport integration. Full regression, static/security gates,
  package build, YAML, and diff checks are recorded in E-1101.
- **Rollback**: Revert E-1101, ADR 0761, shared connector/test changes,
  manifest entry, and execution records together.
