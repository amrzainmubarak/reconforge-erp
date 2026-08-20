# Sequential matching 10K tier v1

The profile `sequential-matching/10k-record-partitioned-v1` executes **2,000
partitions × five records** for exactly 10,000 synthetic records. The partitions cycle exact-USD
carry-forward, contiguous sequence-window, and explicit reversal-pairing
cases. Every partition is executed by the public strategy; the PostgreSQL
worker projection is checked for every partition and reversed input samples
are compared for deterministic digests.

Run:

```text
python -c "from reconforge.benchmark.sequential_matching_scale import run_sequential_matching_10k, verify_sequential_matching_10k; r=run_sequential_matching_10k(); verify_sequential_matching_10k(r); print(r.to_manifest_text())"
```

The current JSON report records the measured host, runtime, peak memory,
effect/manifest digests, unmatched-record count, and explicit limitations.
This is a one-host synthetic algorithm observation—not distributed capacity,
live PostgreSQL, provider, soak, SLO, or production-posting evidence.
