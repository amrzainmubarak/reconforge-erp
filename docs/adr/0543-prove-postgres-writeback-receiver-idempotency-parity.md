# ADR 0543: Prove PostgreSQL receiver idempotency parity before distributed claims

- Status: Accepted
- Date: 2026-08-22
- Scope: E-829 server-backed receiver idempotency conformance

## Context

ADR 0542 defines a digest-only receiver contract and proves atomic replay on a
same-host SQLite reference store. That is a useful adapter contract, but it
does not prove that the same immutable request and response identity survives
server-backed concurrency, a native database backup, or the PostgreSQL
versions declared by the repository.

Neither a PostgreSQL result nor a database lock establishes a live provider's
contract, distributed consensus, settlement finality, or cross-host failover.
Those claims require separate identified external and failure-domain evidence.

## Decision

Add an optional PostgreSQL reference store implementing the unchanged receiver
contract. It loads psycopg only when the backend is used, preserving the local
Community import path. A transaction-scoped advisory lock over the canonical
receiver/key digest serializes contenders before the immutable receipt is
read or inserted. The receipt and synthetic effect are committed by one
database transaction and retain identifiers and digests only.

Install database triggers that reject receipt/effect UPDATE or DELETE, digest
format checks, and the same receiver/key primary and foreign-key identity.
Initialization remains an explicit administrator action; runtime operations
use a non-superuser, non-role-creating, non-database-creating,
non-replicating, non-BYPASSRLS role.

Retain one closed matrix runner and report that execute the identical cases on
the exact digest-pinned PostgreSQL 16.14 and 17.10 images, create a native
custom-format dump, restore it to an independent database, and compare both
canonical histories with the SQLite reference history.

## Verification

Each PostgreSQL cell must prove:

- exact sequential replay and refusal of same-key payload retargeting;
- one apply and seven identical replays from eight spawned processes;
- replay after a child exits immediately following commit;
- database refusal of receipt/effect mutation and malformed direct input;
- three immutable receipts for exactly three synthetic effects;
- native dump listing and an independent restore with identical canonical
  history and no additional effect on replay;
- the declared non-privileged role flags; and
- exact disposable-container cleanup.

The matrix fails closed on a version/image mismatch, false check, source or
SQLite-report digest drift, extra report field, or history disagreement.

## Security and financial integrity

The store has no listener, credential persistence, payload-body persistence,
numeric amount, ledger posting, or autonomous approval path. Generated
credentials exist only for disposable local containers. SQL data values are
parameterized; identifiers are immutable module constants or psycopg quoted
identifiers. Statement and connection timeouts are bounded.

This is one Docker Desktop host running two sequential single-node PostgreSQL
versions with synthetic digest-only effects. It is not live-provider
interoperability, cross-host consensus/failover, accounting posting,
settlement, HA/DR, or production exactly-once assurance.

## Compatibility

The change is additive. The SQLite reference behavior, sender lifecycle,
connector manifests, application database migrations, write-back policy, and
disabled-by-default network behavior are unchanged. Importing the connector
package does not require psycopg until a PostgreSQL operation is requested.

## Rollback

Remove the additive PostgreSQL store, matrix runner/report/schema/tests,
exports, workflow step, and documentation. No product database migration or
user data is changed. Preserve retained failure evidence and never reinterpret
an idempotency conflict as a successful replay.
