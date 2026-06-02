# Configuration

The default config lives at `config/reconforge.yml`.

## Tolerances

```yaml
amount_tolerance: 2.0
date_tolerance_days: 3
```

Use tighter tolerances for strict accounting close workflows and wider tolerances when ERP exports include rounding or posting-date lag.

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

Account mappings document the intended control scope and can be extended when future connectors filter ERP exports automatically.

## Risk Weights

Risk weights are configurable. Increase a weight when your organization treats that control gap as more severe. For example, a regulated workshop may increase `missing_old_part_return` or `direct_purchase_fit`.
