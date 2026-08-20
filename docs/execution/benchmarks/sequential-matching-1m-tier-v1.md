# Sequential matching 1M tier v1

The profile `sequential-matching/1m-record-partitioned-v1` executes 200,000
independent five-record partitions for exactly 1,000,000 synthetic records.
It cycles carry-forward, contiguous sequence-window, and reversal-pairing
cases, records deterministic effect/manifest digests, checks permutation
invariance, and samples the worker projection at the declared stride.

This is a one-host synthetic algorithm observation. It does not claim
distributed 1M capacity, live PostgreSQL parity, soak, SLO, provider behavior,
financial posting, or production sizing.
