# PostgreSQL grouped matching 10K domain-diverse local profile

## Environment

- Date: 2026-08-24
- PostgreSQL: 16.14 (`postgres:16-alpine`, local Docker service)
- Host: Windows 11, Python 3.14.6, AMD64, 16 logical CPUs
- Role: non-privileged `reconforge_app`; synthetic tenant data only
- Profile: `postgres-grouped-matching/10k-domain-diverse-v1`
- Shape: 16 workers, 250 runs, 10 partitions per run, batch size 32
- Workload: 2,500 independent hard-key partitions and exactly 10,000 synthetic
  source records
- Modes: one-to-many, many-to-one, true many-to-many, fee-aware portfolio
  netting, FX-aware many-to-many, and portfolio partial-settlement ambiguity

## Command

```powershell
$env:RECONFORGE_TEST_POSTGRES_DSN='postgresql://reconforge_app:***@127.0.0.1:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_ADMIN_DSN='postgresql://postgres:***@127.0.0.1:55433/reconforge'
$env:RECONFORGE_TEST_POSTGRES_APP_USER='reconforge_app'
python -m pytest -q tests/test_postgres_grouped_matching_scale.py -k '10k_domain_diverse' --tb=short -rs -s
```

The focused live selector passed. The public profile completed `250/250`
runs and `2,500/2,500` partitions, produced `9,160/9,160` expected result
rows, and finished with zero duplicate identities, failed runs, or active
runs. Per-mode completion counts were 42 for each of the four primary shapes,
41 for FX-aware many-to-many, and 41 for portfolio partial settlement.

- Observed runtime: `63.9503s`
- Effect-set digest:
  `78168229e37a78bb859e664a75098890e0671f9a502c8f6f04c30380ee9b3681`
- Manifest digest:
  `c4d3461885fd3626b66a787caf8b3800706d1505d84169375885cc001e4a133a`
- Machine-readable report:
  `postgres-grouped-matching-10k-domain-diverse-current-2026-08-24.json`

## Boundaries

This is one local Docker PostgreSQL service and synthetic data. It does not
prove throughput, capacity, SLO, soak, cross-host scheduling, queue HA,
automatic failover, HA/DR, provider interoperability, statutory posting,
write-back, or production readiness. The FX rate, fee treatment, and partial
settlement ambiguity are deterministic fixtures, not live market or provider
evidence.
