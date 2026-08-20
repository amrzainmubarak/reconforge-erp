# ADR 0302: Keep quorum and fencing safety decisions orchestration-neutral

- Status: accepted
- Date: 2026-08-04
- Scope: `P4-REL-001`

## Decision

Add a deterministic `HaDrTopology`/`HaDrCluster` state machine that models
three voter nodes in independent failure domains plus a witness. Failover is
allowed only after a monotonic detection tick, witness acknowledgement, and
quorum. The old leader is fenced before election; its stale commit is rejected.
Rejoining nodes must catch up to the exact committed sequence and receive an
independent repromotion authorization before they can become candidates again.
Election tie-breaking is priority descending, then stable node ID.

The state machine emits canonical events and a digest-bound simulation report.
It is an orchestration-neutral safety contract: it does not connect to
PostgreSQL, Docker, a queue, an object store, a fencing device, or a network.

## Rationale

The existing Docker PostgreSQL drill proves synchronous replication, manual
promotion, fencing, backup/restore, and repeated integrity on one host. It
cannot prove host-loss independence, witness quorum, or automatic external
fencing. A separate decision contract lets deployment adapters be tested
against the same split-brain and replay invariants without widening the
single-host claim.

## Evidence boundary

`HA_DR_QUORUM_SIMULATION_2026-08-04.json` is `simulation_only`. It records two
logical failovers, zero acknowledged transaction loss, four ordered commits,
stale-leader rejection, and no split-brain in the model. Container domains are
not host failure domains; automatic failover, external fencing, PostgreSQL
execution, RPO/RTO wall-clock measurements, and production SLOs remain
unverified.

## Rollback

Remove the reliability module, script, schema, generated report, tests, ADR,
CI invocation, and execution records. The existing single-host HA/DR drill is
unchanged and no external state is modified.
