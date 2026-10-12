# 0810: Seal reconciliation child writes at the database boundary

Status: accepted for the bounded PostgreSQL0097 contract, 2026-10-03.

Restricted-role SQL reproduced three ways to invalidate retained reconciliation
evidence: append inputs/results/exceptions after completion, move a completed
child to an editable run, and mutate inputs while a worker has already claimed
the run. Ordinary same-run completed updates and parent terminal relabeling were
already guarded; those protections did not close these paths.

Migration0097 installs one invoker trigger on each of the three child tables.
INSERT/UPDATE/DELETE lock the exact visible parent run. Child tenant/run IDs
cannot change. Writes require READ COMMITTED without resetting isolation or
scope settings. Inputs are writable only before the first claim, in the initial
Queued/attempt0 state with no cancellation. Outputs remain writable during
active execution and the existing initial synchronous workflow. Terminal,
cancelled and unreclaimed retry states reject them. The explicit current schema
installer includes these guards; frozen historical base SQL is unchanged.

## Evidence

`POSTGRES_RECONCILIATION_SEAL_2026-10-03.json` binds before-fix raw SQL probes,
frozen source hashes and9 passing live tests. A Windows native-client skip was
covered separately by actual container `pg_dump`/`pg_restore`:12.962403s,
historical table digests and three guards retained, restricted-role append
denials repeated, exact read-only replay and a new initial input accepted.

The actual durable worker on0097 passes the pinned45-row independent scenario
with42 matched pairs, unchanged strict/legacy decision digests, exact replay,
lease recovery and real parent-lock races. The compatibility selection passes
257 tests with two explicit opt-in database skips. Root native migration-chain
drill and16.14/17.10 matrix pass in22.86s/36.139s. Source stability and owned
resource removal were checked for these actual executions.

## Compatibility and operation

Historical rows and manifests remain unchanged. A manifest damaged before this
migration is not repaired or silently resealed; verification must still surface
its mismatch. Owners remain a trusted administrative boundary. These synthetic
correctness/restore observations establish no capacity or customer ROI claim.

Upgrade through0097 and use the current installer for direct deployments.
Register inputs before claiming execution; retries replay existing inputs rather
than appending to a claimed set. Keep READ COMMITTED for mutations. Unsupported
caller isolation fails explicitly instead of changing caller state.

Downgrade removes only these guards and retains rows, thereby removing this
protection. Use the verified backup/restore path and a maintenance window for a
revert. Whole-package release verification and operational posting remain
separate gates.
