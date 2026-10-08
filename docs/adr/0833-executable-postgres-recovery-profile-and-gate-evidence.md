# ADR 0833: executable PostgreSQL recovery profiles and exact gate evidence

Date: 2026-10-08
Status: Accepted for the bounded baseline gate repair

## Problem

Draft PR123 exposed inherited gates unavailable in the initial Windows baseline.
psql does not expand its quoted variables in SQL supplied through --command,
so strict source/restore revision verification fails before backup. The Docker
test runner also assumes every service specification contains dbname. The
writeback restore drill compares a moving head with its historical0099 constant,
and one operations API fixture changes trigger state while deferred events remain.
Gitleaks flags twelve historical and twelve current synthetic auth fixture lines.

## Decision

Keep the recovery profile/revision header and fail-closed revision predicate.
For pinned profiles, put the static verification query in a private temporary
ASCII SQL script and invoke psql --file with the existing quoted --set binding.
Remove that script on success and failure. Keep legacy coarse verification on
its original --command path. Do not interpolate a revision into SQL ourselves.
The disposable Docker runner copies the script into its owned container and
forwards the bindings; service-only source/maintenance commands address postgres,
while isolated target specifications retain their explicit database.

Resolve the current Alembic head while proving the retained0099 checkpoint is
an ancestor. Upgrade and record the actual head. Preserve historical reports,
publish fresh source-hashed October8 drill/matrix reports, and extend their
closed revision enums only through0106. Drain the owned operations fixture's
deferred constraints before restoring its audit trigger within the transaction.

Review Synthetic-123 occurrences in temporary database and mocked browser
auth tests. Add only exact commit/path/rule/line and current-tree fingerprints.
Default rules, full-history scanning and source/test scope remain unchanged.

## Evidence and limits

Retain original hosted failure logs separately. Six real-adapter argv contracts
cover service-only and isolated targets with legacy/pinned profiles. Existing
negative source/restore-profile, ACL hardening and target-rollback tests remain
required. A disposable PostgreSQL17.10 current0106 backup/restore verifies the
restored revision, zero PUBLIC SECURITY DEFINER execution, wrong-source refusal
before output, target removal and container cleanup. PostgreSQL16.14/17.10
writeback migration/restore evidence reaches0106 with equal history digests.
The three-run single-host HA/DR sentinel drill retains its own narrower0053
profile and does not establish host-loss HA or a production RPO/RTO.

No API/schema/database migration or automatic historical data repair is added.
These results are synthetic development acceptance, not provider interoperability,
independent security assurance, compliance, production or cross-host recovery.
Revert this bounded gate repair with its tests and reports to roll back; the
original failures return and the affected acceptance gates must remain blocked.

## Follow-up: shared HTTP audit fixture cleanup

On source832ceeee, Linux native encrypted current0106 restore passes, but the
native shard then fails scoped-export audit teardown; industry-close fails the
same deferred-event boundary in its shared audit helper. Drain deferred
constraints before restoring the trigger in that helper and the remaining
scoped-export/consolidation/policy-provenance owned cleanup transactions.
34 fresh PostgreSQL17.10 HTTP/metrics/industry/close/provenance regressions pass
with the same CI bootstrap predecessors, followed by strict current0106 native
restore, revision/ACL refusal checks and cleanup. No runtime or permission
change follows; earlier whole-suite source832ceeee stays separately bound.
HTTP_FIXTURE_CLEANUP_2026-10-08.json records original failures and exact fixture
hashes. Hosted final-head acceptance remains separate.
