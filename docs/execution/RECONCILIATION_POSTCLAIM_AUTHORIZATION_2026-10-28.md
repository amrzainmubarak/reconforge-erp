# Reconciliation worker authorization after claim — 2026-10-28

**Status: reproduced with an in-memory boundary; repair, live PostgreSQL and
release verification remain open.** This document does not claim a real user,
customer, deployed grant revocation, PostgreSQL connection-pool deadlock, or
financial posting was observed. The read-only investigation used HEAD
`43d8d051ea14046e78f86c2723f4c5aaec0afa02` in a checkout with unrelated
concurrent changes. The investigated worker file had SHA-256
`4eeec1a59c044b373bf5fdb5a2ca6592139017b8a0ce43a4b214cea284c18ce0`;
the probes verified that the imported module came from this checkout.

## Observed authorization boundary

[`process_run`](../../reconforge/workers/postgres_reconciliation.py) checks
tenant policy, selected scope before the claim connection, and the full scope
again inside the claim transaction. After that transaction commits, the worker
does not reevaluate the supplied context before reading checkpoints or streaming
more inputs, extending a heartbeat, persisting a partition and checkpoint, or
persisting the final result and completing the run. Cancellation and failure
handling can also write status, audit and outbox records. The scope supplied to
PostgreSQL is not itself proof that the service principal still holds that
scope. A non-partitioned matcher may already have received source records in
memory at claim time; later revocation cannot make previously disclosed data
unseen. This investigation does not show any GL posting.

The shared [`require_service_worker_policy`](../../reconforge/workers/policy.py)
calls an injected supplier and central evaluator. A supplier can itself cache
or otherwise return stale grants; invoking it more frequently alone does not
prove revocation freshness. The check does not establish the authoritative
amount or bind the policy limit to a currency. The existing explicit
`allow_unbound_hosted_policy=True` path has no supplier-based authorization.
Those remain separate blockers.

## Synthetic reproduction

On Windows with Python 3.12, run from the repository root:

```text
output/release-blocker-20261025/venv312/Scripts/python.exe output/postclaim-20261028/postclaim_policy_probe.py
```

The probe uses the real `process_run`, policy guard and central policy engine,
with an in-memory repository and transaction boundary. A synthetic supplier
initially grants organization `org_a`. After the fake claim transaction
commits, the injected matcher removes that grant and calls heartbeat. The
recorded events then include `heartbeat_after_revoke`, `result_after_revoke`
and `complete_after_revoke`; the worker returns `Complete`. Policy was called
three times before the change and not again during the run. A subsequent
explicit check against the same supplier denies `organization_scope_denied`.
This demonstrates the control-flow gap, not live PostgreSQL persistence or a
production authorization bypass.

Script SHA-256:
`e3258edc66609988d50489c4920ffe2d37e0b0d47ebecf34fca086243c8412b3`.
Captured log `output/postclaim-20261028/postclaim_policy_probe.log` SHA-256:
`fb505195f483ce3b1de2ff0e4cd8d938ea6c3490cc32ed31da0b9f5de9e9bdfd`.

### Follow-up with synthetic PostgreSQL

Two further cases ran on a freshly created, task-owned PostgreSQL 16.15
container on 2026-10-28 UTC / 2026-10-29 Cairo time. The tests used separate
random databases upgraded to Alembic head and a synthetic application role
without superuser, BYPASSRLS, CREATEDB or CREATEROLE; FORCE RLS on the run
table was checked by the shared fixture. The matcher and PostgreSQL repository
were real, while identity, grants and their revocation remained synthetic.

In the first case the matcher withdrew the synthetic `org_a` grant after claim
commit, then called heartbeat and the deterministic matcher. The real database
state changed, one match was persisted and the run reached `Complete`. The
supplier's three checks all occurred before withdrawal; an explicit later check
returned `organization_scope_denied`. This demonstrates the missing recheck
with actual PostgreSQL writes, but not a real IAM provider or deployed user's
grant revocation.

The second case used an actual `PostgresPooledConnectionFactory` with one
connection and a 0.25-second acquisition timeout. A partitioned run returned
`Failed` with `PostgreSQL runtime connection unavailable` while the streaming
path required another connection. This is an observed bounded timeout on the
synthetic fixture, not an indefinite deadlock or a general throughput result.

The command in `output/postclaim-20261028/run_postclaim_live.py` ran both cases
with the mandatory native gate: **2 passed, 0 skipped, 0 xfailed** in 21.78 s
of pytest time. The owned, labeled container was removed after the run; no
other service was stopped. `live-probe.log` SHA-256 is
`c9fedcddbff1dd828a7d89f78644f1886d539e3ccef873ffdda14eebe8efd369`;
`live-probe.json` records environment and cleanup. At the run's beginning and
end the worker SHA-256 was
`f3b47b1ded1200bbbcda9a4924bde271b6bed7b5f874564e0e09a2fc403045c5`,
repository SHA-256 was
`50fc754b4825ee26cb52488030dee96b8abadb554348c06233e35b02ae488735`,
and test SHA-256 was
`079795dcfc59b06f8090d184e32a4f1ffd56b8cc87ab8db324b1cad584dbb131`.
HEAD was `f4686c4a209337c60e1f6ed4be35da2efeb4180a`, but other files in the
checkout were modified; these file-bound observations are not a full frozen
source or hosted CI result.

## Connection and streaming constraint

`_stream_input_supplier` holds its PostgreSQL transaction and cursor across
`yield`. While that generator remains active, the deterministic matcher asks
for cancellation and heartbeat using separate transactions, and the outer
worker writes each partition using another transaction. The bounded
[`PostgresConnectionPool`](../../reconforge/infrastructure/postgres.py)
allows `max_size=1` and has an acquisition timeout.

The separate synthetic `output/postclaim-20261028/stream_one_slot_probe.py`
uses the real worker and local matcher with a fake one-slot transactional
boundary. The simulated cursor yielded a partition while its slot was occupied;
the nested cancellation check hit a synthetic timeout, the slot was released,
and the run returned `Failed`. The log records the sequence, rather than a
real wait, actual PostgreSQL pool exhaustion or a measured production outage.
Script SHA-256:
`c9a1b840ccb9c4b7187cfed768ff42260cd7083203567c3139ebed1fb78e409b`.
Log SHA-256:
`9b683383389660ba9024ab508586e3a8a03ff6b85b8fd370d316af98c9829241`.

This is relevant to remediation: calling a policy supplier that itself leases
from the same bounded pool while a transaction or streaming cursor is held can
consume an additional slot. The current in-claim check already invokes such a
callback inside a transaction. Neither a callback's implementation nor a
minimum pool size is guaranteed by this investigation.

## Candidate design, semantics and prerequisites

No fix is implemented here. A check immediately before every sensitive read,
heartbeat, partition write and final completion would narrow the window, but
an independently fetched context can become stale between the check and the
write. It must not be described as atomic revocation. The design needs an
explicit authority source, freshness and concurrency semantics, not just more
calls to the existing callback.

For authorization backed by the same PostgreSQL database, investigate a
transaction-aware policy reader using the *existing* transaction connection,
plus a policy/grant version or lock that is checked before the effect and is
also coordinated with grant revocation. Define one lock order for the authority
record and run row, and test the actual isolation level and pool of size one.
If a revocation transaction commits first, the following effect must deny; if
the worker locks and commits first, document that linearization order. Merely
reading a version without coupling the revocation and effect is insufficient.
For an external identity source, a local version cannot guarantee immediate
revocation unless propagation and trust are part of a tested contract; an
expiring capability or bounded freshness changes the guarantee and needs its
own threat model. A cache hit alone is not proof of current authority.

Streaming input requires a separate solution for connection ownership and
consistent cursor semantics. Options include bounded materialization or
resumable keyset reads with explicitly versioned input snapshots, or a
documented minimum resource profile. These have different memory, ordering,
and replay tradeoffs. Do not release a cursor between pages without proving
input immutability, no skipped/duplicated rows, checkpoint compatibility and
failure recovery.

Once a claim has committed, a revocation must not be reported as a pre-claim
`denied`/`skipped` item while leaving a running lease unexplained. The current
exception handler intentionally routes post-claim exceptions through `_fail`,
which marks the owning run `Failed`, records an audit/outbox event and requires
explicit requeue; pre-claim typed denials are re-raised for the worker summary.
A replacement must define a least-privileged, auditable cleanup authority for
this state transition even when the normal execution grant is revoked, sanitize
error content, and handle loss of lease or inability to record the transition.
Earlier committed partitions remain durable: rollback of a later transaction
must not be described as rollback of the whole run. Existing checkpoints are
not thereby revalidated. Requeue, replay and idempotency need their own proofs.

Minimum validation: a restricted non-superuser/NOBYPASSRLS PostgreSQL role;
grant revoked before claim, between claim and first output, between partitions,
and immediately before completion; explicit pause hooks to test commit order
and concurrent revocation; no unauthorized post-revocation write; rollback and
correct failure/audit/outbox behavior; lease expiry, crash and requeue; matched
and conflicting checkpoint replay; source reads and cancellation paths; and
pool size one plus concurrent workers with bounded acquisition timeouts. Check
supplier failure, stale grant versions, external identity unavailability,
`allow_unbound_hosted_policy`, unscoped legacy runs and known/unknown amount
independently. Tests should compare actual database state and must not claim
coverage of arbitrary SQL by privileged roles.

## Recommended next implementation slice

First define a trusted, transaction-aware authorization port and its linearized
revocation semantics. For a database-backed provider, have the provider read
the exact principal, tenant, workspace, organization, entity and effective
grant version using the existing write transaction's connection. Coordinate
revocation through the same authoritative version/lock and document a uniform
lock order. An injectable callback that merely accepts a connection is not by
itself evidence that the data are current or that revocation takes the same
lock. At each partition/complete boundary, check authority before creating
results or a checkpoint; preserve the explicit difference between a refusal
before claim and a post-claim stop with auditable recovery. Treat missing,
expired, invalid or unavailable authority as an explicit fail-closed outcome.
Bind amounts only after their separate authoritative-exposure problem is
solved. A live external provider must either offer equivalent ordering or
declare and test a bounded freshness window; do not promise immediate
revocation from a local cached snapshot.

In parallel, address cursor ownership: either prove a bounded, versioned
pagination design over immutable inputs with each read connection released
before the next write, or use explicitly separated resource pools with
admission control that reserves enough writer and policy capacity for all
concurrent streaming readers. A pool size of two alone is not a concurrency
proof: multiple active readers can occupy all slots. Run the same live
regressions with one permitted connection, concurrent workers, timeout and
cancellation, and recovery after an already committed partition. Until both
the provider and resource contract are implemented and tested, repeated
callback checks provide a narrower best-effort guard only; no atomic
revocation or deadlock-free claim follows from this investigation.
