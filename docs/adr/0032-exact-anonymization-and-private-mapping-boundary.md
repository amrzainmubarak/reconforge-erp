# ADR 0032: Exact anonymization and a private mapping boundary

## Status

Accepted — P0 correctness and privacy-hardening slice; current manifest writer
superseded by ADR 0054.

## Context

Amount noise entered through binary floats, used `Random.uniform()`, and then
forced every masked value to two decimal places. This could change results
under binary approximation, silently invent currency precision, and break
equalities because each amount column received a different factor.

More seriously, the default shareable output contained
`anonymization_map.csv` with every original identifier beside its masked value.
Copying that directory for a demo or support case therefore disclosed the
reversible mapping and contradicted the advertised sharing boundary. Reusing a
non-empty output directory could also leave that legacy file or other stale
sensitive files in place.

## Decision

- Parse `--amount-noise-percent` as exact text in the CLI and as a finite
  Decimal between 0 and 100 at the application boundary. Finite floats remain
  a legacy service-reader input and convert immediately through strict parsing.
- Generate one seeded integer-step Decimal factor at four-decimal resolution
  for all amount columns and files. Record algorithm version
  `exact-global-decimal-noise-v1`; do not use float arithmetic.
- Multiply with a bounded local Decimal context, then round `ROUND_HALF_UP` to
  each source value's explicit lexical scale. Do not infer a two-decimal
  currency policy where the schema does not provide one.
- Preserve invalid/non-finite/scientific amount values unchanged for visible
  review rather than replacing them with zero.
- Stop writing the reversible identifier map into the anonymized output by
  default. A caller that genuinely needs it must provide
  `--private-map-output` pointing outside both the input and shareable output
  directories; existing files are never overwritten.
- Require the shareable output directory to be new or empty and outside the
  input directory. This prevents stale raw maps or unrelated files from being
  mistaken for anonymized output.
- Add a shareable schema-v1 `anonymization_manifest.json` with algorithm,
  exact policy, source filenames, seed fingerprint, privacy boundary, and
  SHA-256 policy/manifest and shareable-output file digests. It contains no
  original identifier, raw seed, or amount factor. Provide a verifier for both
  the manifest and listed output bytes.

## Compatibility and migration

The old private mapping CSV shape (`group,original,masked`) is unchanged when
explicitly requested. The breaking default is intentional for secure-by-
default behavior: automation that consumed `output/anonymization_map.csv` must
choose a separate protected path with `--private-map-output`. The new public
manifest replaces that filename in the returned artifact list.

Existing non-empty output directories must be moved, reviewed, or emptied by
the operator before rerunning. ReconForge does not delete them automatically.
No database migration is required. A rollback may explicitly export the
private map outside the shareable directory; restoring the raw map to the
default output is not a safe rollback.

The exact integer-step algorithm intentionally changes seeded amount factors
from earlier float-based releases. Reproducibility claims must therefore bind
to the algorithm version. Identifier aliases remain deterministically assigned
in sorted-file/row order.

## Privacy boundary

This tool is a risk-reduction aid, not proof of anonymization, de-identification,
or safe publication. Deterministic aliases permit linkage and known-value
inference; deterministic amount noise is reversible; free text, unclassified
columns, rare combinations, filenames, and metadata may remain identifying.
Every output requires human review and the private map must be protected as
sensitive source data.

## Validation

- Boundary tests cover exact percentages, low ambient Decimal precision,
  factor bounds/scale, invalid policies, legacy finite-float input, huge values,
  source-scale rounding, and invalid-value preservation.
- Cross-file tests prove one factor preserves equal numeric relationships.
- Security tests prove default output omits original mappings, explicit private
  maps stay outside the shareable directory, stale/non-empty targets fail
  without deletion, and invalid CLI input creates no output.
- Manifest tests validate the JSON Schema and detect policy/manifest tampering.
