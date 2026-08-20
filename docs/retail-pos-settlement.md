# Retail POS settlement control

ReconForge now includes one bounded retail vertical slice: reconciling local
POS batch exports against local processor settlement exports. The algorithm is
`retail-pos-settlement-v1` and uses the installed `Money` currency/rounding
policy for every amount.

The slice keeps card refunds, processor fees, chargebacks, unmatched batches,
duplicate provider identities, scope mismatches, and net variances visible. It
produces a JSON report whose decision and artifact digests can be replayed and
verified. Input files are fingerprinted before the run and the control never
posts a journal or performs network I/O.

## Inputs

The CLI accepts two bounded JSON record files (a `records` array):

- POS records: `batch_id`, `store_id`, `business_date`, `currency`, six exact
  sales/refund amounts, `transaction_count`, and `source_reference`.
- Processor records: `settlement_id`, `batch_id`, `store_id`,
  `settlement_date`, `currency`, `card_gross`, `refunds`, `fees`,
  `chargebacks`, `net_settlement`, and `provider_reference`.

```bash
reconforge retail settlement settlement-run \
  --pos-input examples/retail_settlement/pos_batches.json \
  --settlement-input examples/retail_settlement/settlements.json \
  --currency USD \
  --tolerance 0.01 \
  --output output/retail-settlement/report.json
```

The declarative pack at `control-packs/retail-pos-settlement` provides CSV
controls for missing batches, duplicate settlement IDs, and operator-supplied
`expected_net` variance. It is a control pack, not a live processor connector.

## Boundary

This is an experimental, local, non-posting artifact workflow. It does not
prove provider authenticity, settlement finality, card-network semantics,
fraud prevention, statutory posting, ERP write-back, production availability,
or a complete retail module. A future stateful/API/Studio slice must add
approved persistence, policy coverage, operational evidence, and domain review
before those claims are considered.
