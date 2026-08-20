# ADR 0503: Retain the current PostgreSQL HA/DR drill conservatively

- Status: accepted
- Date: 2026-08-10
- Decision owner: ReconForge execution owner

## Context

The repeated PostgreSQL HA/DR verifier is a bounded operational regression
gate for encrypted backup/restore, synchronous-standby fencing, manual
promotion/failback, transaction continuity, and labelled-resource cleanup.
The topology uses two disposable containers on one Docker host and therefore
cannot establish host, zone, or region independence.

## Decision

Retain the 2026-08-10 report as the current local evidence artifact. Require
three complete runs, zero acknowledged transaction loss, final sequence 4,
cleanup success, and failover/failback RTO below the 60-second drill ceiling.
Keep the single-host and manual-controller limitations explicit.

## Verification

Docker Engine 29.6.2 with `postgres:17.10-alpine` passed all three runs. The
report SHA-256 is
`b756fc0883b62bda597376b8c4d7d516f089181be55439714855bbcd7d9a6b90`.
Failover RTO was 11.117–11.321 seconds and failback RTO was 0.931–1.082
seconds; all runs recorded zero acknowledged loss and cleanup success.

## Boundary

This does not establish independent failure domains, quorum/witness fencing,
automatic failover, cross-site recovery, production SLOs, or HA/DR readiness.
It does not close the hosted native PostgreSQL backup gate E-461.

## Reversibility

Remove the dated report, manifest entry, test expectation, and this ADR. No
product data or schema changes are required.
