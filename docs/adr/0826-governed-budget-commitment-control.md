# Govern operational budget envelopes as an immutable commitment control

Status: accepted; SQLite 52, PostgreSQL 0102, authenticated API registration, and SQLite backup/restore admission are integrated and tested.
Date: 2026-10-03
Scope: operational appropriation envelopes, human review, and retained commitment evidence.

Operational spending controls need a durable budget authority before downstream
purchase, payable, cash, or general-ledger effects may rely on an amount as
available. A caller-provided total, a cached login permission, or a mutable
reservation balance cannot establish that authority. This slice introduces one
bounded envelope with explicit lifecycle and immutable commitment evidence. It
does not post a journal, create a purchase order, settle a payable, or change a
cash balance.

Use positive exact integer minor units and a captured currency registry policy.
An envelope begins as `Draft`, its creator submits it, and a different current
human identity approves it. Only an `Approved` envelope accepts `Reserve`,
`Release`, or `Consume`. The stored aggregate obeys
`available = limit - reserved - consumed`; every event carries the exact next
row version, source reference, actor, audit ID, Outbox ID, and request digest.
Definitions, policy metadata, lifecycle provenance, event evidence, and command
receipts are immutable. Correction happens through a new event rather than an
update or delete.

Every read and mutation starts with the authenticated request principal, then
re-reads the enabled persisted identity, active role assignments, active role
permissions, and non-revoked workspace/organization/legal-entity grants inside
the same transaction that reads or changes budget state. The request snapshot is
only an upper bound: it can narrow a request but cannot re-grant a revoked live
permission or scope. PostgreSQL reads those authority rows with `FOR SHARE` and
uses transaction-local RLS scope; SQLite re-reads local RBAC under `BEGIN
IMMEDIATE`. Human writes require recent stronger authentication in server mode.
The PostgreSQL repository rechecks the exact persisted session and an unexpired
step-up assertion inside the budget write transaction, using the database clock,
and holds a shared lock on that session until the business effect commits. A
middleware snapshot therefore cannot carry a revoked session or expired
assertion into a later financial write.
The local authenticated route converts the real password-authenticated local
session into a fresh server principal for that one call, then the repository
performs the durable identity/RBAC check again.

The required permissions are `budget_control.read`, `budget_control.manage`,
and `budget_control.approve`. `manage` creates, submits, reserves, releases,
and consumes; `approve` is required for independent approval; `read` retrieves
the scoped envelope and event history. The database guard rejects an approval
by the creator or submitter even if an application path regresses.

PostgreSQL revision 0102 seeds those permissions and their `admin`/`controller`
default-role grants for tenants and roles that already exist at upgrade time. Its
versioned tenant and role triggers repeat the seed for a tenant or either
default role created later. A revoked operator grant remains revoked: the seed
uses conflict-safe inserts and never reactivates an existing row.

Command IDs are scoped to tenant/workspace in PostgreSQL and workspace in local
mode. They bind actor, canonical scope, and exact request digest. A matching
retry returns the original acknowledgement only after current authority passes
and the currently retained immutable ledger independently verifies. A changed
request with the same command ID fails closed. PostgreSQL serializes the command
key with an advisory transaction lock and locks the envelope before capacity
checks; SQLite uses `BEGIN IMMEDIATE`. The declared PostgreSQL write profile is
`READ COMMITTED`; callers at another isolation are refused rather than silently
changed.

Storage is defined by the frozen `SQLITE_BUDGET_CONTROL_UPGRADE_SQL` artifact
owned by SQLite migration 52 and by the frozen `UPGRADE_SQL` literal owned by
Alembic revision 0102. Neither migration imports mutable runtime schema text.
The tables are:

- `budget_envelopes`: canonical scope, fixed budget definition and captured
  currency policy, lifecycle identities, cached conserved balances, and version.
- `budget_commitment_events`: append-only reserve/release/consume evidence,
  exact remaining amount, immutable audit and Outbox references, and version.
- `budget_commands`: scoped idempotency request/response receipts and digests.

The PostgreSQL schema uses `reconforge.budget_envelopes`,
`reconforge.budget_commitment_events`, and
`reconforge.budget_commands`, with forced RLS policies and trigger guards.
SQLite defines equivalent tables and immutable/lifecycle/event guards. Both
adapters emit budget audit and Outbox records in the same transaction as the
business effect and receipt.

The shared PostgreSQL runtime database credential and trusted server
application are part of this slice's trusted computing base. RLS binds tenant
and selected hierarchy, while the server rechecks user authority and stronger
authentication before every budget mutation. The database trigger layer enforces
structural lifecycle, conservation, and immutable evidence invariants; it does
not prove an individual human actor's permission or stronger-authentication
state against arbitrary SQL issued with that shared runtime credential. A valid
direct DML sequence can therefore satisfy structural guards without being an
authorized product workflow. Deployments that need a database-enforced human
actor boundary require separate DB identities or a constrained database
interface; this slice does not claim that boundary.

SQLite migration **52** and PostgreSQL Alembic revision **0102** install the
reviewed schema. `create_api_app` registers the secured
PostgreSQL repository factory from the identity factory, exposes the authenticated
router under `/api/v1`, and includes all mutation routes in the central
permission-contract scan. The module descriptor is registered centrally. The
PostgreSQL migration acceptance begins at revision 0101, applies 0102 through
Alembic, proves all three tables have forced RLS, proves an empty downgrade, and
proves that a downgrade with retained evidence fails without changing the
revision or row. A deployment still needs an operator-provisioned application
role with the narrow table privileges it requires; no migration guesses a tenant
role name or grants financial access automatically.

Restore has a strict dependency order. Apply base platform migrations and the
budget migration first; restore tenant, workspace, organization, legal entity,
fiscal period, currency, captured currency-registry snapshot, and identity
parents before `budget_envelopes`; retain associated audit and Outbox records
before `budget_commitment_events`; load `budget_commands` only after their
envelopes and referenced evidence exist. The SQLite native backup profile carries
all three budget tables. Its restore runs only in an unpublished temporary
database, removes the closed set of three lifecycle admission triggers required
to load retained final state, reinstalls them, and calls
`verify_sqlite_budget_storage` before the database can replace the target.
Tampered budget evidence fails that verification. PostgreSQL native
backup/restore orchestration remains separate; its migration downgrade refuses
to discard any retained budget evidence.

Acceptance evidence covers the full lifecycle, exact textual minor values,
capacity conservation, command replay and conflicting reuse, audit/Outbox
atomicity, SQLite raw trigger tamper refusal and PostgreSQL structural trigger
admission, independent maker/checker review,
parallel self-approval and oversubscription races, current-role revocation
before retry, stale-session and expired-step-up refusal inside the PostgreSQL
write transaction, a session lock that blocks concurrent revocation until the
financial transaction completes, frozen SQLite/Alembic migration identity tests,
SQLite authenticated HTTP, SQLite migration rollback and
backup/restore tamper refusal, and PostgreSQL authenticated HTTP with step-up,
selected-scope binding, nonowner RLS, and live-role revocation. The PostgreSQL
migration test separately applies the registered 0102 revision from 0101 and
tests safe downgrade behavior. The PostgreSQL acceptance uses disposable
isolated databases and a non-superuser, non-BYPASSRLS application role; it is
synthetic test evidence rather than a production capacity, availability,
regulatory, or customer-outcome claim.

There is no standalone web screen in this slice. The authenticated API is the
current operating surface and is centrally registered. The local and PostgreSQL
HTTP acceptance tests exercise the real router with real authentication, scope,
version, digest, status, and authorization/error responses. A future UI may be
added only after it consumes this centrally registered API and preserves those
authority and error semantics.

Rollback preserves a verified pre-upgrade backup and all immutable budget,
audit, Outbox, and command evidence. A reader that does not understand the new
tables must refuse their interpretation; it must not delete commitments, alter
captured money policy, or synthesize a balance from incomplete rows.
