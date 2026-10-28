# Quality entity-scope design investigation — 2026-10-28

**Status: proposed, not implemented or verified. Release remains blocked.** This
is a design investigation, not evidence that entity isolation or a legacy-data
recovery interface exists. The reviewed repository HEAD was
`24d8862eb172eb7621a6749af1ea48efe163b727`; the checkout also contained local
changes outside this investigation. No source or test was modified for this
document and no new runtime test was run here.

## Observed boundary

The current PostgreSQL NCR, inspection-plan, rework, and NCR-actor-authority
policies filter by tenant and workspace, not legal entity. See
[quality repository and schema](../../reconforge/infrastructure/postgres_manufacturing_quality.py),
[enterprise module schema](../../reconforge/infrastructure/postgres_enterprise_modules_schema.py),
and [NCR actor authority schema](../../reconforge/infrastructure/quality_actor_authority_schema.py).
The API requires a selected hierarchy for NCR creation and disposition, and
checks the actor, but the NCR record has no durable entity binding against which
to compare that selection. Plans and rework have their own workspace-scoped
routes; see [quality routes](../../reconforge/api/routes/manufacturing_quality.py).

Earlier synthetic restricted-role PostgreSQL probes observed an actor authorized
for entity B disposing an NCR created in the same workspace under entity A, and
also observed cross-entity inspection-plan access and rework creation. The
probes, their precise source versions, and limitations are recorded in
[security continuation](SECURITY_CONTINUATION_2026-10-28.md) and
[state](STATE.md). This investigation did not independently repeat them.
An actor's selected entity, including one recorded in an audit event, does not
prove the ownership of an older NCR or of its lot or work order. Current quality
records are advisory; these observations do not prove a quality-to-stock or GL
posting relationship.

The repository's current direct-disposition guard checks independent reviewer
authority and an audit digest, but its actor argument is caller-supplied. The
API binds the actor to the authenticated principal; direct repository use does
not establish that identity. See [direct-authority evidence](QUALITY_DIRECT_AUTHORITY_2026-10-28.md).
Entity work must not claim this separate identity gap is closed without its own
proof.

## Options and compatibility

1. **Keep workspace behavior.** Preserves existing access but leaves the
   observed cross-entity exposure open. It is not a security repair.
2. **Disable all PostgreSQL quality operations.** A restrictive deny policy on
   the quality and authority tables plus explicit API unavailability would
   contain ordinary non-bypass application-role access. It would also interrupt
   all enterprise inspection, NCR and rework use and ordinary historical-data
   access. This broad breaking containment has not been adopted.
3. **Proposed bounded NCR record scope.** Bind only newly created NCR records to
   an explicitly authorized tenant/workspace/organization/entity tuple. Leave
   every pre-migration record's new scope fields `NULL` and deny their ordinary
   entity-scoped access until a separate, reviewed access process exists. This
   preserves a working path for newly scoped NCRs but changes accessibility of
   historical records and some direct PostgreSQL callers. It does not isolate
   inspection plans or prove source-object ownership. This is the preferred
   candidate for further design, not an implemented fix.

SQLite's local quality semantics remain unchanged in this candidate; therefore
cross-backend equivalence for entity scope must not be claimed. Existing API
response fields should remain stable for supported new NCR operations, while
the changed PostgreSQL access behavior and error semantics need release notes
and explicit regression tests. Unknown historical records must never be
silently assigned from timestamps, actor grants, display names, audit metadata,
or the currently selected entity.

## Candidate implementation boundary

- An Alembic migration after
  [0157](../../alembic/versions/0157_postgres_quality_actor_authority.py)
  adds nullable organization and entity fields to NCRs, with a constraint that
  both are present or both absent. It does not backfill. Validate the complete
  hierarchy against the authoritative workspace/organization/entity relations
  for newly created rows; use existing scoped authorization contracts, including
  `irp_scope` and `hc_actor`, only after verifying their precise behavior and
  concurrency boundaries. The stored tuple denotes **record scope**, not
  ownership of any claimed source object.
- Creation uses the authenticated, admitted request hierarchy explicitly and
  persists it in the same transaction as the NCR, creator authority, and audit
  event. Require an explicit valid hierarchy for direct PostgreSQL creation;
  neither a missing actor nor an empty hierarchy may silently create an
  entity-bound record. Prevent ordinary updates to a record's scope, including
  attempts to convert old NULL rows to a guessed entity. Repository identity
  binding remains a separate requirement unless independently implemented.
- Add restrictive PostgreSQL row policies with exact nonempty tenant,
  workspace, organization and entity equality for new NCRs; NULL and missing
  context fail closed. PostgreSQL permissive policies can combine with OR, so
  a replacement or extra policy must be checked against *all* policies and
  installation paths; a suitably tested `AS RESTRICTIVE` policy can preserve
  the existing permissive tenant/workspace condition. Apply both `USING` and
  `WITH CHECK` as appropriate and keep ENABLE/FORCE RLS. Ensure older schema
  installers do not remove the restriction on reinstall.
- Protect NCR actor-authority rows through the same accessible parent NCR and
  make rework access and creation depend on the scoped parent. Protect parent
  links from unauthorized reassignment; test that a foreign or unbound NCR
  cannot be reached through rework. Review policy dependencies and privileges
  for recursion, foreign-key visibility and information leakage. These rules
  cover restricted application roles; they do not constrain superusers,
  BYPASSRLS, table-owner administrative operations, or PostgreSQL `TRUNCATE`.
  Test actual grants rather than treating RLS as an identity protocol.
- Inspection plans need a separate entity-scope design: their existing unique
  identity is workspace/item/revision, so simply adding entity columns or a
  filter can create collisions, hidden-row conflicts, or altered semantics.
  Until that work is designed and tested, quality entity isolation as a whole
  remains an open blocker.

This candidate cannot safely be deployed as a schema-only change while older
writers still create unbound records. Coordinate application and migration
ordering, fail closed when the expected contract is absent, and test mixed
versions. Examine every install/reinstall path and PostgreSQL adapter caller;
do not change the original baseline schema without a versioned migration.

## Historical access, migration, and recovery

Keeping rows physically intact is not the same as keeping them accessible.
Before implementation, specify an authorized, auditable legacy export or review
workflow with explicit role/permission, scope, approval, field handling, and
tests. Until then, ordinary entity-scoped APIs must not claim to expose legacy
NCRs; a database administrator's privileged backup is not a product interface.
Any later attribution must be an explicit, evidence-backed, separately
authorized decision with provenance and immutable audit history. Unknown stays
unknown when evidence is insufficient.

Source inspection found that the existing [scoped export](../../reconforge/infrastructure/postgres_scoped_exports.py)
does not include quality NCRs or rework. Its policy decision currently logs
without providing an audit repository or sink; it is not evidence of durable
audit. The [emergency access](../../reconforge/infrastructure/postgres_emergency_access.py)
domains do not include quality, and a grant alone would not bypass restrictive
RLS. A possible separately authorized read service would need a trustworthy
database identity, narrow record grants, expiration and revocation, durable
access audit, child-record controls, and tests covering direct SQL and pooled
connections. This is an unimplemented candidate, not a verified recovery path.

The migration must be tested from a populated 0157 database containing both
legacy NCRs and dependent authority/rework rows; compare their content and
counts before and after, including an independently restored backup. A downgrade
that merely removes the restriction could restore the observed exposure or
discard new ownership data. Define and test refusal/forward recovery and a
controlled rollback runbook before use; do not silently downgrade or delete
records. A new migration head also affects the explicit registry and current
restore/browser contracts in [PostgreSQL operations](../../reconforge/infrastructure/postgres_operations.py),
[browser verification](../../.github/scripts/verify_erp_expansion_browser.py),
[archive verification](../../.github/scripts/verify_global_integrity_archive.py),
and their tests. Update those only together with real migration and restore
evidence, not by weakening the gates.

## Required verification before activation

Write failing tests against the existing behavior first, then verify the final
source using an explicitly owned, freshly created PostgreSQL database migrated
from a populated predecessor and a non-superuser, non-BYPASSRLS application
role. The minimum test matrix must cover:

- Authenticated API and direct restricted-role SQL/repository access for entity
  A versus B in one workspace and for different tenants/workspaces. Test
  SELECT, INSERT, UPDATE, DELETE, missing context, spoofed or mismatched scope,
  and the actual grants; distinguish RLS protection from authentication.
- New scoped NCR creation, independent disposition, valid replay and denial of
  self-approval, actor spoofing, scope reassignment, cross-entity rework and
  changed parent links. Inject failure between NCR, authority and audit writes
  and verify rollback without partial effects.
- Legacy NULL rows and children are preserved byte-for-byte and are not exposed
  to ordinary entity contexts; check the separately designed authorized legacy
  access path when one exists. Exercise uniqueness conflicts without leaking
  protected record details.
- Populated upgrade, restart, backup/restore, migration-policy persistence
  through supported installers, and safe downgrade refusal or controlled
  recovery. Verify old/new application compatibility explicitly.
- Existing SQLite and PostgreSQL API contracts, status codes, error disclosure,
  privilege revocation and concurrent mutation tests; plans remain explicitly
  out of scope until separately repaired. Do not claim inventory quarantine,
  financial posting, performance, or full quality entity isolation from these
  tests.
