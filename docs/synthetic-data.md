# Synthetic Data Lab

The synthetic data generator creates local ERP-like datasets for demos, testing, benchmarking, and rule-pack development.

## Command

```bash
reconforge generate synthetic --rows 1000 --industry workshop --exception-rate 0.15 --critical-rate 0.05 --seed 42 --currency SAR --output benchmarks/small_1k
```

Supported industries:

- `workshop`
- `manufacturing`
- `fleet`
- `dealership`
- `service`

## Generated Files

- `stock_moves.csv`
- `gl_entries.csv`
- `work_orders.csv`
- `purchase_orders.csv`
- `products.csv`
- `customers.csv`
- `old_parts_returns.csv`
- `invoices.csv`
- `synthetic_manifest.json` (additive; not included in the eight-path Python return value)

## Exact generation policy

`exact-decimal-v1` draws monetary inputs on a six-decimal integer grid without
binary-float arithmetic, then applies the requested currency's registered minor
units and `ROUND_HALF_UP`. Monetary CSVs include an explicit currency column;
KWD is not forced to two decimals and JPY is emitted with zero minor units.

`--exception-rate` and `--critical-rate` are exact plain-decimal text in the
closed interval 0–1. Scientific/non-finite values are rejected before the
output directory is created. The CLI selects strict-financial-input-v2;
finite-float Python calls remain warning legacy readers and v2 records that
selection.

Current schema-v2 `synthetic_manifest.json` records financial-input policy,
algorithm version, exact rates, seed, profile, currency-policy and registry
provenance, policy/manifest digests, and each CSV's byte count/SHA-256. Schema
v1 remains an implicit-legacy compatibility reader. CSV line endings are pinned
to LF. Verify a manifest and its local bytes with:

```python
import json
from pathlib import Path

from reconforge.generator.synthetic import verify_synthetic_manifest

root = Path("benchmarks/small_1k")
payload = json.loads((root / "synthetic_manifest.json").read_text(encoding="utf-8"))
verify_synthetic_manifest(payload, output_dir=root)
```

The manifest proves deterministic fixture identity under its recorded policy;
it does not prove realism, privacy, benchmark scale, or production fitness.

## Scenario Patterns

The generator creates exact matches, fuzzy matches, unmatched stock, unmatched GL, amount mismatches, date mismatches, duplicate references, direct purchase fitting, missing old-part returns, WIP aging, closed jobs without invoices, cancelled PO linkage, and manual entries.
