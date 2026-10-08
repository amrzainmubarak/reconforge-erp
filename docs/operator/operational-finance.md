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
