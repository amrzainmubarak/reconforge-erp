# PostgreSQL HA/DR drill boundary

The reproducible development topology is two PostgreSQL 17.10 containers on one
Docker Engine host: one primary and one physical streaming standby. The primary
uses `synchronous_commit=remote_apply` and `synchronous_standby_names='*'` before
the measured sentinel transaction. Promotion is forbidden until the controller
proves the exact primary container ID is stopped, removes it, and proves no exact-
name container remains. This is the split-brain fence for this topology only.

Run `uv run --locked python .github/scripts/verify_postgres_ha_dr.py`. The drill:

1. creates separately labelled control and replication networks, volumes, and nodes;
2. migrates the primary through Alembic 0053;
3. creates the standby with `pg_basebackup` and a physical replication slot;
4. commits a synchronous sentinel and verifies it on the read-only standby;
5. creates an AES-256-GCM backup, restores into an isolated database, compares
   the sentinel digest, and drops the isolated database;
6. disconnects only the replication network, proves a synchronous write received no
   client acknowledgement, then starts the RTO clock, fences the exact primary,
   promotes through `pg_promote`, and commits a second sentinel;
7. re-seeds the former primary, verifies it is read-only and digest-identical, then
   commits a third synchronous sentinel;
8. fences the current writer, promotes the rejoined node, and commits sequence four;
9. reports failover/failback RPO and RTO and removes only exactly labelled resources.

Three complete clean-environment repetitions achieved zero missing acknowledged
sentinel transactions. Failover RTO was 11.075/11.094/11.117 seconds
(min/median/max), and failback RTO was 0.912/0.945/0.958 seconds under a 60-second
test ceiling. Run all three without selection using
`uv run --locked python .github/scripts/verify_postgres_ha_dr_repeated.py --output <report>`.
The non-acknowledged partition write is deliberately excluded
from the RPO promise because its client outcome is uncertain. It
does not establish a production SLO. Both nodes, volumes, Docker networking, and
the controller share one host/failure domain. Host loss, zone/region loss,
quorum/witness behavior, automatic failover, capacity under degradation,
production secrets/KMS, cross-host network partitions, and repeated soak results
remain mandatory before P3-ENT-010 can close.
