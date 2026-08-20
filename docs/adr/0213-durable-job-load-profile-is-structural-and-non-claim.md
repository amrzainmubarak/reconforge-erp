# ADR 0213: Durable-job load profile is a structural, non-claim manifest

- Status: Accepted
- Date: 2026-08-01
- Owners: Platform Reliability / Operations

## Context

P4-SCL-001 requires reproducible multi-worker load, contention, queue,
retry, checkpoint, no-duplicate-effect, memory, backpressure, cancellation,
and soak profiles on named hardware at each published scale tier. The
existing durable-job contract (E-092 through E-096, E-181, E-188) already
proves the closed state machine, generation-fenced leases, atomic
checkpoint/resume, no-duplicate-effect for a single two-partition workload,
idempotent two-worker submission, and SQLite/PostgreSQL semantic parity.
What is missing is a *reproducible multi-worker load harness* that proves
no-duplicate-effect under multi-worker contention and emits a closed
manifest.

Two risks had to be avoided: (1) emitting a wall-clock or memory number that
could be read as a scale, SLO, or sizing claim before named-hardware
10K/100K/1M/10M evidence exists; (2) introducing a new persistence
primitive or changing the durable-job domain, which would risk regressing
the already-proved contract.

## Decision

1. Add `reconforge/benchmark/durable_job_load.py` as the first P4-SCL-001
   slice. It drives the *existing* durable-job worker loop
   (claim/commit_partition/complete_partition) under real multi-worker
   contention on a shared SQLite database using one ThreadPoolExecutor.
2. The harness reuses the existing `SQLiteDurableJobRepository`,
   `DurableJobApplicationService`, and `DurableJobWorkerService` exactly as
   callers already use them. No new domain type, schema, migration, or
   repository method is introduced.
3. Each worker is statically pinned to one tenant so per-tenant contention
   is fair (workers-per-tenant must be an exact multiple). Workers per
   tenant share queued work within that tenant; a worker that has handled
   its fair share exits.
4. The manifest is closed schema-v1 over the *structural* outcome only:
   declared shape, completed jobs, committed partition effects, duplicate
   count, final queue/running depth, per-tenant completions, deterministic
   effect-set digest, environment, and explicit limitations. Observed
   runtime, peak memory, and throughput are recorded as separate
   non-deterministic counters and are explicitly excluded from the manifest
   digest, so the digest is reproducible across runs and hardware.
5. `verify_load_manifest` asserts the structural invariants: completed jobs
   equal the declared count, duplicate partition effects are zero, queue
   drains to zero, committed effects equal completed * partitions_per_job,
   per-tenant completions sum to the declared count, and limitations retain
   honest non-claim wording.
6. The default tier is deliberately small (8 workers, 64 jobs, 4 partitions
   per job, 4 tenants = 256 declared partition effects). Backpressure, soak,
   retry/backoff coupling, cancellation-under-load, PostgreSQL load parity,
   and 10K/100K/1M/10M tier publication are explicitly deferred to later
   P4-SCL-001 slices.

## Consequences

- P4-SCL-001 gains the first reproducible multi-worker load profile with
  no-duplicate-effect proof under contention. The manifest digest is stable
  across runs while observed timing/memory vary honestly.
- The slice does not claim a scale tier, SLO, backpressure behaviour, soak
  result, distributed capacity, or publication of 10K/100K/1M/10M evidence.
  SQLite serializes writes under `BEGIN IMMEDIATE`, so measured contention
  bounds multi-worker coordination, not database partition parallelism.
- Cancellation-under-load is not exercised by this slice. The durable-job
  domain already permits `QUEUED/RUNNING -> CANCELLED` and proves the
  transitions; a future slice will exercise cancellation under contention
  with clean lease release.
- No API, CLI, UI, PostgreSQL, tag, release, deployment, or production
  mutation is part of this slice.

## Rollback

Remove `reconforge/benchmark/durable_job_load.py`,
`tests/test_durable_job_load_profile.py`, ADR 0213, the execution-state
entries, and the MANIFEST.in/test-membership lines. No database migration,
domain change, repository change, API, CLI, UI, tag, release, or deployed
service rollback is required.
