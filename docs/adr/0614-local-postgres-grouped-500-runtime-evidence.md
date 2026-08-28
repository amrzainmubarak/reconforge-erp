# ADR 0614: Current local PostgreSQL grouped-matching runtime evidence

Status: Accepted

## Decision

Retain the 2026-08-23 disposable local PostgreSQL 16.14 run as current
runtime evidence for the bounded grouped-matching worker profile. The run
uses the non-privileged `reconforge_app` role, 16 workers, 250 runs, two
partitions per run, all five declared grouped modes, and synthetic data.

Observed invariants were 250/250 completed runs, 500/500 partitions,
1,200/1,200 expected result rows, zero duplicate identities, zero failed runs,
zero active runs, and 50 completed runs per mode. The observed 20.7293 seconds
is retained as an environment observation only, not a throughput, capacity,
SLO, soak, HA/DR, or production-sizing claim.
