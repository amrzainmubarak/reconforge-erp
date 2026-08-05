# ADR 0352: Witness acknowledgement does not satisfy voter quorum

- Status: accepted for the Phase 4 reliability-control slice
- Date: 2026-08-05

## Decision

The orchestration-neutral HA/DR state machine requires the configured voter
quorum from healthy voter nodes. A witness acknowledgement is a separate
fencing/election condition and is never counted as a substitute voter. A
topology also needs at least one witness in a failure domain not used by any
voter; a co-located witness cannot provide an independent failure domain.

## Rationale

Counting a witness as a voter could elect a leader with only one healthy voter
in a three-voter topology. Treating witness placement as an explicit invariant
prevents a configuration from claiming independent quorum when the witness
shares a voter failure domain.

## Evidence and boundary

- `tests/test_ha_dr_quorum_simulation.py` passes five tests, including rejection
  of co-located witnesses and one-voter-plus-witness failover attempts.
- The state machine remains `simulation_only`: no PostgreSQL, network,
  external fencing device, independent hosts, automatic failover, wall-clock
  RPO/RTO, or production SLO is proven.

## Rollback

Remove the two invariant checks, focused regressions, ADR, manifest entry, and
execution records. No schema, migration, or persisted data rollback is needed.
