# ADR 0763: Shared strict connector amount validation

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: The read-only REST, ERP, payment-statement, and generic
  database-reference response models each implemented their own `Decimal`
  validation. The implementations accepted scientific notation and returned
  the original representation, allowing equivalent source values to produce
  different response fingerprints.
- **Decision**: Add `canonical_connector_amount()` as the shared connector
  response boundary. It uses `parse_exact_amount()` to reject binary floats,
  scientific notation, malformed values, and non-finite tokens, then returns
  `canonical_decimal_text()`. Existing connector-specific invalid and
  non-finite error wording remains explicit and compatible.
- **Rationale**: Financial connector boundaries need one auditable policy,
  not four subtly different validators. Canonical serialization must happen
  before response digest construction so replay identity is independent of
  harmless decimal formatting.
- **Compatibility**: Existing finite exact values remain accepted but are
  returned in canonical plain text. Response model field names, aliases,
  scopes, cursors, manifests, and read-only behavior remain unchanged.
- **Verification**: Connector model and response tests cover canonical output,
  scientific-notation refusal, non-finite refusal, tenant/entity/account
  boundaries, digest replay, TLS sandbox behavior, and SDK inventory. Full
  regression and release gates are recorded in E-1103.
- **Rollback**: Revert E-1103, ADR 0763, the shared helper, migrated
  connector/test changes, manifest entry, and execution records together.
