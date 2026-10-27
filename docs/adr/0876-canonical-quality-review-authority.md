# ADR0876: Canonical quality review authority and truthful stock boundaries

Accepted — 2026-10-26. Scope: experimental legacy quality NCR records and native
ME2 evidence presentation. No native stock/quarantine integration is claimed.

The old NCR self-review check uses a mutable inspector username. Independent
reproduction renamed the creator and received a successful self-disposition.
That violates independent review even though the record has no financial effect.

Use a separately versioned append-only authority relation for canonical creator
and reviewer IDs. Retain labels as labels. Bind each authority row to its original
actor/object/action audit event and NCR scope; reviewer ID must differ from
creator ID. Insert/update the business record, append audit and insert authority
in one caller-owned transaction. Reject unverified historical creators without
inferring identity from a reused username. Preserve their records for reading.
SQLite60 owns atomic schema/version registration; PostgreSQL157 follows156 and
uses FORCE RLS with the same tenant/workspace boundary as the legacy quality
owner. This is not a new entity-isolation claim.

Canonical writes require a current persisted active human and permission.
The client inspector label cannot confer authority. Sensitive server writes
recheck current selected scope and permissions before mutation; legacy reads and
Community operation retain their storage boundaries. Document any stricter NCR
server hierarchy admission in the implementation evidence.

The separate native ME2 owner already binds original cost/production/inspection
sources and reviewed posting phases. A legacy NCR has arbitrary lot/work-order
strings, so connecting it to stock by string coincidence would create false
source ownership. Keep its recorded/not_posted response truthful; the old test
expecting quarantine remains a known unmet integration requirement.

ME2 UI must distinguish acknowledged child commands from verified parent totals.
Missing values are unavailable, never zero. Failed refresh keeps the child ACK
evidence but marks parent quantities/WIP unverified and blocks dependent writes
until successful refresh. Valid zero remains zero.

Rollback: keep new authority/audit evidence. PostgreSQL populated downgrade
refuses; use forward recovery or separately verified isolated restore. Empty
roundtrip is tested. Never delete authority to make rollback succeed. Existing
legacy rows receive no guessed identity. No API/CLI route is removed.

Acceptance requires independent rename/reused-alias/forged-actor cases, separate
reviewer, atomic rollback, database immutability/scope tests and migration tests.
Release and all five full enterprise cycles remain BLOCKED pending full gates.
