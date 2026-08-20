# Sequential matching 100K tier v1

The profile `sequential-matching/100k-record-partitioned-v1` executes 20,000
independent five-record partitions for exactly 100,000 synthetic records. It
cycles carry-forward, contiguous sequence-window, and reversal-pairing cases,
records deterministic effect/manifest digests, checks permutation invariance,
and samples the worker projection at the declared stride.

This is a single-host synthetic algorithm observation. It does not claim live
PostgreSQL parity, distributed throughput, soak, SLO, provider behavior,
financial posting, or production sizing.
