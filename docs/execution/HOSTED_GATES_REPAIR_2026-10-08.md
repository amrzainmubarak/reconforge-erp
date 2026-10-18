# Hosted gate repair evidence — 2026-10-08

Draft [PR123](https://github.com/amrzainmubarak/reconforge-erp/pull/123) revealed
inherited PostgreSQL and full-history secret-fixture gate failures. Original logs
and hashes remain separate from the bounded repairs in
[HOSTED_GATES_REPAIR_2026-10-08.json](HOSTED_GATES_REPAIR_2026-10-08.json).
The earlier b8f5a772 whole-suite acceptance remains historical; a fresh whole
regression is required after this runtime change. Main and migration heads are unchanged.

Pinned recovery verification now executes a private SQL file through psql with
its existing quoted revision binding. The Docker bridge supports service-only
source/maintenance commands and isolated target database commands. The writeback
drill verifies the retained0099 checkpoint's ancestry and records the actual0106
head. Owned fixture cleanup drains deferred constraints before restoring audit
triggers. Native invoice restore compares the captured source revision and
financial history. Exact synthetic-auth fingerprints retain all default Gitleaks
rules and full-history/tree scanning; there are no rule/path/commit wildcards.

| Gate | Result | Runner wall seconds |
| --- | --- | ---: |
| Focused recovery/runner/policy/report contracts | 119 passed / three live prerequisites | 11.214 |
| PostgreSQL17.10 analogous operations/consolidation/Receivables/native invoice | 97 passed / zero skipped | 59.847 |
| Writeback standalone17.10 migration/restore | actual0106 / retained valid history | 13.353 |
| Writeback16.14/17.10 matrix | both pass / equal history digests | 28.070 |
| Three-run single-host primary/standby sentinel drill | three pass / all owned cleanup | 474.306 |

The separate strict encrypted native backup/restore proves current0106, zero
PUBLIC SECURITY DEFINER execution, wrong-source revision refusal before output,
isolated-target removal, and source-container cleanup. The application role is
neither SUPERUSER nor BYPASSRLS. This uses actual PostgreSQL tools in an owned
container; Linux service-file hosted acceptance remains separately observable.
The HA drill observes synthetic sentinel RPO zero, failover11.985–12.076 seconds
and failback1.638–1.665 seconds on one host with manual control. It does not
establish cross-host recovery, automatic failover or a production SLO.

## Remaining acceptance gaps

- Shared PostgreSQL downgrade fixtures encounter the retained nondefault outbox
  generation guard. Isolate databases; do not weaken the migration or delete evidence.
- Identity/security role and permission assertions require current contract review.
- Three inherited Inventory receipt cases remain outside the paused feature scope.
- Configured HTTPS browser journeys, cancellation integration, default-branch
  dependency alerts and release signatures/provenance remain separate requirements.

AMR-GFO-005 remains in progress. Successful local recovery and fixture repairs
do not turn the whole hosted CI suite green or establish production acceptance.
Rollback reverts ADR0833's code/tests/reports together; no database migration is added.
