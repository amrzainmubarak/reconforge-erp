# Durable job operations

This experimental module exposes the existing durable-job lifecycle through an
authenticated operator API and Studio `/jobs`. It adds no scheduling engine,
financial posting effect, output store, or worker bypass.

Select a tenant, workspace, organization and entity lane. In the server profile,
the selected hierarchy must match current granted scope and request headers.
`ops.read` permits bounded metadata and retained transitions. `jobs.manage` is a
separate permission, initially assigned only to admin; server mutation requires a
human session and recent reauthentication. A read role cannot cancel or requeue.

The only operator transitions are unleased **queued → cancelled** and
**paused/failed → queued**. A worker owns running/retrying transitions through its
generation-fenced lease. A running or leased job returns a conflict; inspect its
worker evidence and recovery state. Cooperative running-job cancellation remains
a separate capability and is not introduced here.

Every mutation supplies the version that the operator inspected. The lifecycle
persists the changed projection and its append-only transition atomically. If a
response is lost, the same actor can repeat the same action against the original
version while that immediately following transition is still current. Any later
worker progression, different actor or different action returns a conflict.
Refresh and review before issuing a new command. Studio blocks further commands
after an uncertain transport outcome until refreshed metadata is inspected.

List pages use an opaque-to-the-operator job ID keyset, ordered identically by
binary identifier on SQLite and PostgreSQL. Each page contains at most 50 records;
Studio requests 25. Concurrent status changes can alter membership between pages.
Details return the latest 200 transitions and flag truncation. Original history,
partition effects and lease events remain in storage. Operator responses exclude
idempotency keys, input/configuration digests, manifest paths and source rows.

SQLite migration56 and PostgreSQL0107 add the permission and lane indexes.
PostgreSQL also seeds future tenants/admin roles. Downgrade removes these additions
while retaining jobs and transition evidence, and refuses to discard nondefault
permission grants. Removing API/Studio exposure is a reversible rollback that
does not require downgrading the lifecycle database.

The native gate is reproducible with
`python .github/scripts/verify_postgres_job_operations.py --output <report.json>`.
It owns a pinned PostgreSQL17.10 Docker container and a nonowner application role,
then exercises scoped pagination, RLS, six concurrent cancellations, exact replay,
lease refusal, guarded downgrade/upgrade and native dump/restore. Its JSON binds
the actual migration head, source commit/file hashes, runtimes and container cleanup.
It uses a loopback address and bounded connection timeout. This gate is synthetic,
single-host evidence and does not establish availability or capacity guarantees.

The optional real browser acceptance lives outside default E2E under
`apps/web/live/job-operations.acceptance.ts`, requires `RECONFORGE_GFO_LIVE_URL`,
and uses migrated persisted fixtures from `tests/job_operations_runtime_fixture.py`.
No request interception or synthetic in-browser queue is used in that acceptance.
Source registration, central authorization inventories, full migration acceptance
and the integrated browser/build/regression gates remain integration responsibilities.
