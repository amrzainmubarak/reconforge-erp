# ADR 0205: HA evidence requires fencing and named failure domains

- Status: Accepted
- Date: 2026-07-30

## Decision

Record topology, node count, independent failure-domain count, replication mode,
failure injection, fencing method, backup/restore integrity, RPO unit, RTO start
and stop events, ceilings, and limitations in a closed drill report. Promotion is
illegal until the old writer is positively fenced. Synchronous remote-apply may
support a zero-transaction RPO claim only for transactions committed after the
standby is confirmed streaming and synchronous policy is active. Control and
replication paths must be distinct in partition drills. A synchronous write without
client acknowledgement has an uncertain outcome and is excluded from the acknowledged-
transaction RPO claim. Rejoin requires a fresh physical base backup, read-only recovery
proof, and exact data digest before synchronous service resumes.

## Consequences

The first implementation is useful process/container-failure evidence but has one
Docker host failure domain. It cannot close the Enterprise HA/DR task or support a
host-loss, zone, region, automatic-failover, production SLO, or Enterprise-ready
claim. The next topology must use independent hosts plus a witness/quorum or an
equivalent external fencing authority. The single-host drill now exercises a bounded
replication-network partition, former-primary rejoin, and failback, but none of those
substitutes for independent-host failure evidence.

## Rollback

Remove the development drill and mark its matrix cell planned. Never promote an
unfenced standby; preserve backups and reports as operational evidence.
