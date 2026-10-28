# ADR 0881: Bind direct PostgreSQL NCR updates to reviewed evidence

Status: proposed. Date: 2026-10-28.

## Context

The existing PostgreSQL `update_ncr` repository method accepts an arbitrary
disposition object without checking the independent reviewer or audit record.
The authenticated API uses `disposition_ncr`, which checks those conditions,
but a direct caller of the repository could bypass them. This concerns the
advisory legacy quality workflow; it does not post stock or finance effects.

## Decision

Within the existing caller-owned transaction, the normal disposition path
validates the actor and creator separation, stages its immutable audit event
and reviewer authority, and then updates the NCR. The update method requires
an independent reviewer authority bound to that same event and a digest of the
complete requested decision. An update failure rolls back the staged event,
authority and state together. A replay of an already persisted disposition is
a read-only no-op after locking and comparing every field; aware timestamp
offsets are compared as instants. The original event and its hash are never
rewritten or reinterpreted. This no-op does not independently validate an old
record's provenance. Any non-identical update requires the locked current row
to be open or under review and the requested transition to be dispositioned;
all non-decision fields must remain unchanged. A historical decision cannot
roll a later persisted state backwards.

This deliberately refuses previously unchecked direct updates with no
independent reviewed evidence. No production caller of the method other than
`disposition_ncr` was found in this repository; external direct repository
callers must move to `disposition_ncr` with a current authorized reviewer.
Public API request/response shapes, persisted rows, history and SQLite behavior
remain unchanged. No database migration is needed for this repository-level
boundary. No historical identity or entity ownership is inferred.

This is not a database-level defense against arbitrary SQL or invocation of
private helpers with application database credentials. The repository's
`actor_user_id` is supplied by its caller; `_actor` checks that identity's
current grants, but cannot prove it is the authenticated caller. The API must
bind it to the authenticated principal. Direct trusted Python callers must
perform their own caller binding; this change does not prevent impersonation by
such a caller. NCRs, inspection plans,
rework and actor authorities remain workspace-scoped; entity isolation,
legacy migration/reader, direct SQL authorization, stock linkage and complete
quality workflows are separate unresolved gates. Do not interpret this change
as their qualification.

## Evidence and rollback

The restricted PostgreSQL regression first demonstrated a direct forged
disposition without reviewer authority. It then tests refusal, normal
independent API disposition, exact replay, post-review tampering and rollback
on an injected update failure. Source-bound run receipts and prerequisites are
tracked in execution evidence. Retain all previously created decisions and
audit records. If the guard causes operational incompatibility, disable direct
repository mutation at the caller and use the supported disposition command;
reverting the guard reopens the bypass and requires explicit risk acceptance.
