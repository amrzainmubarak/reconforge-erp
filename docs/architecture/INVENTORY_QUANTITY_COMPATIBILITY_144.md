# Existing native inventory contracts and quantity custody

Revision `0144_pg_inventory_contracts` follows `0143_pg_project_billing`.
The ordered source contains 143 revisions; rejected revision 137 is absent.

The existing Inventory Core contract permits tenant-unbound operations whose
organization uses the authoritative workspace-organization association rather
than the convenience `application_workspace_id` field. The new generic quantity
coordinator must preserve that contract. Its invoker predicate checks the actual
organization/entity parent, workspace association, tenant and existing inventory
scope, including entity aliases. A raw gate INSERT is subject to the same
predicate; ordinary role table privileges remain required.

Only the generic pool/version functions and gate RLS policy change. The original
142 source owner directory, source birth, release, immutable history and master
interpretation foreign keys remain unchanged. A legacy organization cannot
therefore become a manufacturing supply owner through this compatibility path.
No grants, security-definer function, alternative ledger or inventory balance
is introduced.

Downgrade restores the original functions/policy when compatible. Retained
legacy coordination refuses downgrade; restore the backup or retain revision144.
Accepted historical graphs in the scope fixture are created at revision136 and
then actually upgraded through every later revision, without disabling guards.

Actual isolated native evidence before commit: two original Core/Planning
cycles, seven scope cases, and four new direct-SQL/ACL/inverse cases, all without
skip/xfail/xpass. Original packets remain under `output/m2-core-legacy-quantity144-candidate-v4`,
`output/m2-scope-history144-candidate-v1`, and `output/m2-quantity144-direct-sql-v2`.
Earlier prerequisite and diagnostic setup failures remain retained separately.
These source-qualified gates do not replace final frozen-source CI and recovery.

Empty customer/supplier return downgrade/upgrades recreate coordination
metadata. Their test operator restores explicit table rights; the customer gate
versions reset while every original financial/source population stays byte-exact.
Attack and populated-refusal snapshots continue to include coordination rows.
