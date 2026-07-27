# Configuration

The default config lives at `config/reconforge.yml`.

## Tolerances

```yaml
amount_tolerance: "2.0"
date_tolerance_days: 3
matching_ambiguity_policy: stable-tie-break-v1
```

Use tighter tolerances for strict accounting close workflows and wider tolerances when ERP exports include rounding or posting-date lag.

Keep financial tolerances as quoted decimal text. Current CLI, benchmark, and
Studio readers select `strict-financial-input-v2` and preserve an older
unquoted YAML decimal lexeme before validation, so existing `2.0` files remain
compatible without first converting the value to binary floating point. Direct
Python `load_config` and `ReconForgeConfig` construction now also default to
strict v2. Use exact text, `Decimal`, or integers; historical replay can select
legacy v1 only through an explicit policy argument. See
`financial-input-v2-migration.md`.

`stable-tie-break-v1` preserves the established deterministic assignment for
compatibility. Use `unresolved-equal-cost-v1` when equal-cost candidate graphs
must remain explicit review exceptions. The conservative policy stops at 64
candidates or 32 alternative-assignment checks per connected component and
records `search_budget_exceeded` instead of continuing an unbounded search.

## Aging Buckets

```yaml
aging_buckets:
  - label: "0-30"
    min_days: 0
    max_days: 30
  - label: "90+"
    min_days: 91
    max_days:
```

Buckets are applied to open WIP work orders.

## Old-Part Categories

```yaml
required_old_part_categories:
  - Batteries
  - Brakes
  - Electrical
  - Engine
  - Transmission
```

Use this list to reflect local policy for returned cores, replaced parts, or repairable items.

## Account Mapping

```yaml
account_mapping:
  stock_account: "1400"
  spare_parts_expense: "5100"
  work_in_progress: "1500"
  inventory_variance: "5200"
```

Account mappings document the intended control scope and can be extended when future export adapters normalize ERP exports automatically.

## Risk Weights

Risk weights are configurable. Increase a weight when your organization treats that control gap as more severe. For example, a regulated workshop may increase `missing_old_part_return` or `direct_purchase_fit`.
