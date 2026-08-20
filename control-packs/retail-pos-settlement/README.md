# Retail POS Settlement Controls

This pack is a local, read-only control surface for exported store POS batches
and processor settlement files. It identifies missing settlements, duplicate
provider identities, and net variances after explicit fees and chargebacks.

It is not a live card-processor connector, a payment authorization system, a
fraud product, a statutory ledger, or an automatic write-back path.

## Required input files

- `pos_batches.csv`
- `settlements.csv`

The `settlements.csv` export should include `expected_net`, calculated by the
operator from the POS card net less processor fees and chargebacks. The pack
does not infer missing provider detail silently.

## Run

```bash
reconforge rules run --input examples/retail_settlement/csv --pack control-packs/retail-pos-settlement --output output/retail-pack
reconforge retail settlement settlement-run --pos-input examples/retail_settlement/pos_batches.json --settlement-input examples/retail_settlement/settlements.json --output output/retail-settlement/report.json
```

The CLI artifact is digest-bound and includes unmatched, ambiguous, and
variance decisions. It is non-posting and requires human review before any
downstream accounting action.
