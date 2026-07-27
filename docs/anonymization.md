# Anonymization

ReconForge includes a local risk-reduction tool for preparing candidate demo or
support data while preserving configured identifier relationships. It does not
prove that an output is anonymous, de-identified, or safe to publish.

## Command

```bash
reconforge anonymize --input examples/sample_data --output output/anonymized-consulting --profile consulting-safe
```

The output directory must be new or empty and outside the input directory. This
prevents legacy reversible maps or unrelated stale files from being included by
accident.

Public demo profile:

```bash
reconforge anonymize --input examples/sample_data --output output/anonymized-public --profile public-demo --seed 42 --amount-noise-percent 5
```

## What It Masks

Customer, supplier, user, engineer, equipment, invoice, work order, source document, journal, movement, purchase order, and return identifiers.

## Referential Integrity

If `WO-1001` appears in stock moves, GL entries, invoices, and old-part returns, the anonymizer maps it to the same masked value everywhere.

## Amounts and Dates

Use `--mask-amounts` and `--amount-noise-percent` to scale values
deterministically. The percentage is exact plain-decimal text between 0 and
100; scientific notation is rejected. Algorithm
`exact-global-decimal-noise-v1` uses one four-decimal Decimal factor across all
files/amount columns, preserving equalities where source scales agree. Masked
values use `ROUND_HALF_UP` at each value's source scale rather than assuming
every currency has two decimals.

Amount noise is deterministic and reversible. It is useful for changing demo
values, not as a confidentiality guarantee. Use `--preserve-dates` when date
sequence matters, or `--date-shift-days` to shift dates.

## Public and Private Artifacts

The shareable directory contains `anonymization_manifest.json`, which records
the exact transformation policy, algorithm version, privacy warning, and
verifiable SHA-256 policy/manifest and output-file digests without original
identifiers, the raw seed, or the amount factor.

The reversible original-to-mask CSV is no longer written there. If a controlled
workflow needs it, choose a separate protected location explicitly:

```bash
reconforge anonymize \
  --input live_exports \
  --output reviewed_anonymized_exports \
  --private-map-output private_evidence/anonymization_map.csv
```

The private path must be outside both input and shareable output directories
and must not already exist. Its `group,original,masked` format is compatible
with earlier releases. Never share it with the anonymized folder.

Python consumers can verify manifest and output-file digests with
`reconforge.anonymizer.verify_anonymization_manifest(payload,
output_dir=...)`.

## Security Note

Always review every file and field before sharing. Free text, unclassified
columns, rare record combinations, filenames, dates, and metadata may remain
sensitive. Deterministic aliases permit linkage and known-value inference. The
tool is not a substitute for organizational privacy review or qualified
disclosure-risk assessment.
