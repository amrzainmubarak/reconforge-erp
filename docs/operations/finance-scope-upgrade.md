# Finance hierarchy upgrade and restore

PostgreSQL migration `0095_pg_finance_scope` adds authority and relationship
checks to the existing Finance Core control records. It does not convert their
`Draft`, `Validated` or `Voided` lifecycle into an immutable operational GL.
[ADR0805](../adr/0805-finance-canonical-hierarchy-isolation.md) records the design.

## Prerequisites and changed behavior

Use separate migration credentials and the admitted nonowner application role.
The application role must not own the schema, bypass RLS, install triggers, or
acquire those powers through inherited roles. The application establishes the
authenticated tenant/workspace/organization/entity context for each transaction.
Possession of the shared database credential is not a sandbox against arbitrary
SQL that changes those settings.

Finance organization/entity codes resolve through canonical IDs and the exact
organization `application_workspace_id`. A workspace ID is unambiguous; duplicate
workspace names now fail rather than selecting the first row. Shared charts and
dimensions remain readable inside the authorized workspace. Organization-scoped
requests cannot mutate workspace-shared Finance references; entity-scoped
requests cannot mutate organization-wide Finance references.

Canonical identities and Finance reference identities cannot be relabeled after
creation. A Draft entry can change its scope only after removing its old lines
inside a read-committed transaction. Validated/Voided entry scope is fixed, and
neither can return to Draft. Entry lines cannot move to a different entry.
Normal descriptive changes remain possible at the appropriate authority level.
This migration does not establish all canonical master-data mutation permissions.

## Legacy inspection

The migration does not guess missing workspace attribution or change amounts.
Unresolved legacy organization attribution remains available for explicit
tenant-only inspection; narrowed Finance operations reject it. Do not clear
scope in an ordinary request to bypass this refusal or assign a guessed
workspace merely to make a write succeed. A governed attribution procedure and
its evidence are a separate migration decision.

The composite parent-account FK is installed `NOT VALID`. New or changed
references must share tenant, workspace and chart, but existing account-parent
affinity has not been certified by this migration. An administrative inspection
of a restored copy can identify legacy relationships that need resolution:

```sql
SELECT child.tenant_id, child.id, child.parent_account_id
FROM reconforge.finance_accounts AS child
LEFT JOIN reconforge.finance_accounts AS parent
  ON parent.tenant_id = child.tenant_id
 AND parent.id = child.parent_account_id
WHERE child.parent_account_id IS NOT NULL
  AND (parent.id IS NULL
       OR parent.workspace_id IS DISTINCT FROM child.workspace_id
       OR parent.chart_id IS DISTINCT FROM child.chart_id);
```

An empty result under a filtered application role does not establish complete
historical integrity. Run any complete administrative review through authorized
deployment procedures and retain its scope; do not expose its rows in public logs.

## Installed deletion guard

The installed parent-deletion trigger checks existence of Finance references
without returning their data. Its fixed `pg_catalog` search path and qualified
table names prevent search-path substitution. `row_security=off` prevents a
filtered history check from being mistaken for absence. The trigger owner must
have complete administrative visibility; a deployment where that owner remains
subject to FORCE RLS can refuse deletion, including an otherwise unused parent.
Do not solve such a refusal by granting the application role bypass powers.

Read-committed parent deletion and child insertion serialize through parent row
locks. Unsupported stale-snapshot deletion/reparenting fails explicitly. Tenant
cascade handling applies only once the tenant itself is absent; it does not
authorize deleting an individual referenced organization/entity/period.

## Verification and rollback

1. Retain the prior application/schema versions and a verified backup. Exercise
   the upgrade on an isolated restored copy before changing a live deployment.
2. Apply normal Alembic migrations through0095 with migration credentials.
   Inspect unresolved attribution and historical parent-account relationships.
3. Use the restricted application role to verify one permitted entity write,
   sibling-entity/organization denial, shared-reference read and denied mutation,
   and captured currency-policy interpretation. Verify concurrent operations
   using the actual supported transaction isolation level.
4. Restore a native populated backup into another database. Compare Finance,
   currency, canonical-master, audit and outbox values and policies before making
   new writes. Repeat the permitted/denied operations against the restored copy.

The repository's live native restore regression is
`tests/test_postgres_finance_scope_restore.py`; it requires matching PostgreSQL
`pg_dump`/`pg_restore` clients plus the test administrator/application DSNs.
The October03 observation additionally executed the same verification through
Docker's actual PostgreSQL16.14 client tools on synthetic disposable databases.
Separate write-back migration drills cover the migration chain on16.14/17.10;
those drills alone do not establish populated Finance restore behavior.

Downgrade to0094 removes these restrictions and preserves rows; it therefore
restores weaker authority. Stop affected writes and use an operator-controlled
security rollback procedure if rollback is necessary. No deletion, reassignment,
or invented historical metadata is part of rollback. The synthetic downgrade
test is evidence of the migration contract, not authorization to weaken a live
deployment.
