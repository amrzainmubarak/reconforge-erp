# ADR 0034: Versioned Exact Synthetic Financial Generator

- Status: Accepted
- Date: 2026-07-24
- Scope: `reconforge generate synthetic` and its Python generator API

ADR 0056 supersedes only the current manifest-writer statement: schema v2 now
records financial-input policy while v1 remains an implicit-legacy reader. The
`exact-decimal-v1` algorithm, exact rate, currency, byte, and return-contract
decisions here remain unchanged.

## Context

The synthetic generator created monetary values with `random.uniform`, converted
the binary float to Decimal text, and then forced two fractional digits. This
made the generated finance fixtures depend on a binary-float boundary and
silently treated every currency like USD. Exception/critical-rate CLI values
were also parsed as floats before scenario selection. The output contained no
algorithm version, currency-policy provenance, or byte hashes.

Synthetic data is not customer financial data, but it is used as reconciliation,
benchmark, demo, and regression input. A generator that changes value semantics
without a version boundary undermines reproducibility and can create invalid
fixtures for JPY, KWD, or other non-two-minor-unit currencies.

## Decision

1. Use algorithm `exact-decimal-v1`. Monetary draws select one integer step on
   a six-decimal grid and construct Decimal directly, without float arithmetic.
2. Resolve the requested currency once from the versioned offline registry.
   Quantize all monetary fields with its minor units and `ROUND_HALF_UP` under a
   bounded local Decimal context. Write the explicit currency beside every
   generated monetary dataset.
3. Keep exception/critical rates as bounded exact decimal text at the CLI.
   Library floats remain a legacy ingress reader and convert immediately through
   the strict parser. Scenario draws use exact six-decimal integer steps.
4. Validate rows, rates, currency, and industry before creating the target
   directory. Unknown industries/currencies and invalid/scientific rates fail
   closed with a controlled CLI error.
5. Pin generated CSV line endings to LF and write schema-v1
   `synthetic_manifest.json`. The manifest carries algorithm/rate/seed/profile,
   currency policy and registry provenance, policy/manifest digests, and byte
   count/SHA-256 for the eight CSVs.
6. Keep the Python return value compatible: it remains the list of eight CSV
   paths. The manifest is an additive ninth artifact.

## Consequences

- The same seed, exact policies, algorithm version, and installed registry
  snapshot produce byte-identical tested CSV/manifest output independent of the
  ambient Decimal context.
- Existing seeds produce different values from the unversioned float algorithm.
  This is an intentional correctness change. Historical generated datasets
  remain readable; regenerate them only with an explicit review of expected
  output/digest changes.
- KWD values can retain three decimals and JPY values have zero fractional
  minor units. No currency is assigned an invented two-decimal policy.
- The rate draw has six-decimal resolution. Rates themselves remain exact in
  the manifest even when finer than that resolution.
- This manifest is provenance for generated fixtures, not a claim that the data
  models a real population, fraud distribution, or production performance.

## Security and privacy

The generator uses `random.Random` only for reproducible synthetic fixtures, not
secrets or cryptography. Inputs are bounded/validated before output creation.
The manifest contains no customer data or absolute paths. No network call,
telemetry, or external upload is introduced.

## Rollback

Historical CSVs can be retained with their existing checksums. Restoring the
unversioned float/two-decimal generator as the default is unsafe. Any future
algorithm change must use a new algorithm version and schema-compatible or
versioned manifest migration.
