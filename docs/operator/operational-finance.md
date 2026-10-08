# Reviewed operational finance

Use the PostgreSQL server identity and Finance Core profile. Select the tenant,
workspace, organization and legal entity explicitly. Create journal and account
masters with the existing Finance Core controls before the operational command.

Prepare captures a real submitted/approved AR invoice or approved AP invoice,
its immutable monetary lines, a fixed debit/credit map, business date, open
period and the verified currency policy. The plan has no caller supplied amount.
AR revenue requires Asset/Income accounts. Collections require Asset/Asset;
AP accrual requires Liability/Liability and AP payment requires Liability/Asset.
The Sales/Procurement owners additionally validate their operational mappings.

An independent human reviews the source digest and existing GL snapshot. A
nonpreparer posts the accrual. Full collections and payments use their owning
Sales/Procurement commands; the owner must create the real AR receipt/allocation
or AP payment link on the same transaction and connection as the posted GL.
Deferred guards reject an incomplete financial effect at commit.

Studio exposes source preparation, independent review, accrual posting, exact
readback, and a posted-only trial balance with contributing effect references
and JSON export. The report is net activity in the selected period; it does not
include opening balances. Money crosses the browser API as decimal strings.

If an acknowledgement is lost, resend the retained command with the same actor,
identifier, expected digest, source, reason and scope. Changed content or another
actor is rejected. The browser keeps pending financial bodies only in memory.
If the page was closed, inspect the source using the native invoice ID before
attempting a fresh command. Each source operation has one retained plan/effect.

Do not reverse an OPS1 journal through generic Manual posting. A native reviewed
inverse contract is required; this slice does not yet implement operational AR/AP
credit notes or settlement reversal. Existing generic Manual and reviewed
Inventory receipts retain their established contracts.

Schema installation requires a migration identity that bypasses forced RLS.
An existing unbound OPS1 ID or number aborts installation. A populated downgrade
refuses evidence loss. Recover using a verified backup and a forward migration.
Keep native source rows, finance snapshots, immutable links, commands, audit,
outbox, functions/triggers and forced RLS together in backup/restore verification.

After installing migration 0109, an existing runtime role that can write ordinary
Finance entries also needs `SELECT` on `reconforge.operational_finance_plans`.
The additive integrity trigger reads that forced-RLS source index even when a
Manual entry has no operational owner. Grant this read dependency to the existing
runtime role before resuming writes; it does not require INSERT, UPDATE, DELETE,
table ownership, BYPASSRLS or SECURITY DEFINER execution. Preserve and verify this
ACL during native backup/restore along with the existing Finance grants.

Native AR invoice, receipt and allocation writers and native AP invoice/payment
writers additionally need `SELECT` on both `reconforge.operational_finance_plans`
and `reconforge.operational_finance_links` after migration 0109. Their invoker
closure query references both relations, so PostgreSQL checks both read ACLs even
for a source with no operational owner. Grant each read explicitly and preserve
its forced RLS; these dependencies require no additional DML privileges. Verify
them on a fresh restricted role rather than a role with pre-existing broad grants.

After installing migration 0111, existing runtime roles that write native AP
purchase orders, receiving, supplier invoices, matching or payment links also
need `SELECT` on `reconforge.procurement_cycles`. The additive AP integrity
trigger checks that forced-RLS ownership index for each native mutation,
including payments outside a Procurement cycle. Grant only this read dependency
to a legacy AP runtime role; this dependency does not require INSERT, UPDATE,
DELETE, table ownership, BYPASSRLS or SECURITY DEFINER execution. Verify that the
runtime role can read the index and cannot mutate it, and retain its ACL in
backup/restore. Profiles before migration 0111 have no such table or dependency.

Prepare, review and post Sales- or Procurement-owned source plans from the owning
operational workspace. The public Financial workspace keeps evidence readable,
but returns `operational_owner_required` for detached phase commands. The owner
must commit its business phase and the financial phase in one scoped transaction;
deferred PostgreSQL reverse closure rejects direct repository or SQL advances
without that matching owner phase. Standalone unowned accrual plans retain their
reviewed Financial workflow.

Runtime roles using the public operational-finance routes need `SELECT` on
`reconforge.sales_revenue_documents` after migration 0110 and on
`reconforge.procurement_cycles` after migration 0111 for the forced-RLS ownership
lookup. The reverse integrity hooks use those same finite read dependencies for
ordinary Finance and AR/AP writes. Preserve SELECT while withholding INSERT,
UPDATE and DELETE for a legacy role that does not manage the corresponding owner
module. Profiles before each module migration have no corresponding dependency;
do not grant absent tables or broaden RLS, ownership or execution privileges.
