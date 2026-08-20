# ADR 0474: Record the current-tree PostgreSQL HA/DR drill conservatively

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The repeated HA/DR verifier is a valuable regression gate for encrypted
backup/restore, synchronous standby fencing, failover, failback, transaction
sequence, and cleanup. Its disposable Docker topology intentionally runs on a
single physical host with a manual controller.

## Decision

Record the current run as bounded one-host evidence. Require three complete
runs, zero acknowledged transaction loss, cleanup success, final sequence 4,
and failover/failback RTO below the 60-second drill ceiling. Keep the topology
and limitations explicit.

## Verification

On 2026-08-09, Docker Engine 29.6.2 with PostgreSQL 17.10 passed all 3 runs:
failover RTO was 10.960–11.402 seconds and failback RTO was 1.109–1.170
seconds; all runs had zero acknowledged loss and cleanup success.

## Boundary

This does not establish independent failure domains, quorum/witness fencing,
automatic failover, cross-site recovery, production SLOs, or HA/DR readiness.

## Reversibility

Remove the generated local report and this dated evidence entry. No product
data or schema changes are required.
