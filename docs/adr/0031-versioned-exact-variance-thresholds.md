# ADR 0031: Versioned exact variance thresholds

## Status

Accepted — P0 financial-correctness slice.

ADR 0055 supersedes only the current writer/version statement: schema v3 and
threshold-policy v2 now add financial-input policy provenance. The exact
comparison, v1/v2 compatibility, and historical digest decisions here remain.

## Context

The `analyze variance` CLI converted amount and percentage thresholds to binary
floats before comparison. Two distinct values such as
`0.100000000000000003` and `0.100000000000000005` could therefore become the
same threshold. The unversioned `variance_analysis.json` contract also exposed
only numeric threshold fields, so changing those fields to strings would break
existing consumers even though strings are the safest portable exact-decimal
encoding.

Summary JSON and CSV readers had the same early-conversion risk: Python's JSON
decoder and Pandas type inference could create a float before strict Decimal
validation.

## Decision

- Accept CLI threshold values as text and parse them once at the variance
  application boundary. Library callers may continue supplying finite floats
  as a legacy reader input; they are converted immediately through the strict
  parser and never used in float arithmetic.
- Reject negative, malformed, non-finite, and scientific-notation threshold
  text before creating an output directory.
- Preserve JSON and CSV numeric lexemes as text until strict Decimal parsing.
- Compare amount thresholds against the unrounded exact variance. Compare
  percentage thresholds without division by cross-multiplying exact Decimals.
  Equality remains inclusive. An amount threshold of zero retains its legacy
  meaning of disabling the amount test; a percentage threshold of zero remains
  inclusive.
- Make two-decimal report display rounding explicit as `ROUND_HALF_EVEN`.
  Display rounding never feeds the threshold decision.
- Emit variance report schema version 2. Retain the legacy `thresholds` object
  and its numeric JSON types, but encode its Decimal values directly as JSON
  number lexemes without a float conversion.
- Add `threshold_policy` with canonical decimal strings, comparison/display
  semantics, and a SHA-256 policy digest. New readers use this object and verify
  its digest.
- Keep an explicit compatibility reader for unversioned/v1 artifacts, whose
  legacy threshold values may be JSON numbers or strings.

## Compatibility and migration

Existing readers can continue reading
`thresholds.amount_threshold` and `thresholds.percent_threshold` as JSON
numbers. Version-aware readers should call `read_variance_thresholds()` and use
the canonical v2 policy. The documented JSON Schema accepts legacy unversioned
or explicit-v1 artifacts and requires `threshold_policy` for v2.

No database migration is required. Rollback can restore the earlier writer;
v2 artifacts remain readable by the compatibility reader, while legacy
artifacts remain readable indefinitely. Restoring float CLI parsing or using
rounded display values for decisions is not a safe rollback because it
reintroduces the demonstrated decision-changing defect.

## Security and operational consequences

All processing remains local. Exact serialization uses the standard JSON
encoder for structure and escaping, with collision-checked private markers
replaced only by validated finite canonical Decimal number lexemes. NaN and
infinite JSON output are rejected. Decimal arithmetic costs are proportional
to the small set of summary metrics and configured numeric precision; no large
candidate scan or network dependency is added.

## Validation

- CLI regression tests preserve values beyond binary-float precision and prove
  the resulting decision.
- JSON and CSV numeric-lexeme tests prove exact ingestion and rejection of
  scientific numeric text.
- An ambient low-precision/alternate-rounding Decimal context does not change
  threshold decisions or display output.
- Schema tests validate both current v2 and legacy unversioned/v1 artifacts.
- Reader tests cover legacy compatibility, unknown versions, and digest
  tampering.
