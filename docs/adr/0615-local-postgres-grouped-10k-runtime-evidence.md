# ADR 0615: Current local PostgreSQL grouped 10K runtime evidence

Status: Accepted

## Decision

Retain the 2026-08-24 local PostgreSQL 16.14 grouped 10K profile as bounded
runtime evidence. It uses 16 independent workers, 1,000 synthetic runs, ten
partitions per run, all five declared grouped modes, and the non-privileged
application role.

The run completed 1,000/1,000 runs, 10,000/10,000 partitions, and 24,000/24,000
expected result rows with zero duplicate identities, failed runs, or active
runs; each mode completed 200 runs. The observed 220.3637 seconds is retained
only as a hardware/environment observation. It is not a throughput, capacity,
SLO, soak, HA/DR, or production-sizing claim.
