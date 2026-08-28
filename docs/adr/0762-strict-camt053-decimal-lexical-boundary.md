# ADR 0762: Strict CAMT.053 decimal lexical boundary

- **Status**: Accepted
- **Date**: 2026-08-28
- **Context**: The bounded CAMT.053 parser validated XML amount text with
  `Decimal(value)`. That accepted scientific notation and the shared parser's
  accounting separators even though an ISO 20022 decimal element is a source
  numeric value, not a locale-formatted display field.
- **Decision**: Require the CAMT.053 decimal lexical shape
  `[+-]?(digits with an optional decimal fraction, or a leading decimal point)`
  before passing the value to `parse_exact_amount()`. Serialize accepted
  values with `canonical_decimal_text()` and retain explicit non-finite versus
  invalid error categories.
- **Rationale**: The source boundary must reject representations that are not
  valid for this format, while the shared financial parser still supplies
  finite exact arithmetic and the canonical serializer supplies deterministic
  digests. This prevents a local display convention from being mistaken for
  an ISO source value.
- **Compatibility**: Ordinary signed decimal text, including `20`, `20.0`,
  `.5`, and `5.`, remains accepted and canonicalized. Scientific notation,
  comma separators, accounting parentheses, malformed text, and non-finite
  tokens fail closed. The parser remains offline, read-only, and bounded.
- **Verification**: CAMT.053 tests cover replay-equivalent formatting,
  scientific notation refusal, separator/parenthesis refusal, non-finite
  refusal, XML hardening, bounds, schema output, and payment-statement
  projection. Full regression and release gates are recorded in E-1102.
- **Rollback**: Revert E-1102, ADR 0762, CAMT.053 code/tests, the manifest
  entry, and execution records together.
