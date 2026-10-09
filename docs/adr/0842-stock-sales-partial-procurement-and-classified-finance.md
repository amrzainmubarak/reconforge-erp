# ADR 0842: Compose stock sales, partial procurement and classified financial reporting

Date: 2026-10-09
Status: Accepted; bounded local runtime acceptance on6ec9; hosted and independent release assurance remain separate

Start at PR125 source f24d4836 and retain its dependency on PR124. Main is
unchanged. The expansion branch is amr/global-erp-expansion-20261009.

Reuse InventoryCore, native FIFO layers and exact allocation, reviewed inventory
receipt, AR, AP, FinanceCore, FinancePosting, posted balances, identity and RLS.
Add source ownership around these engines, never another posting kernel.

Build complete bounded cycles in dependency order: classified reporting and
governed opening (0112); stock reservation, reviewed delivery/COGS and revenue
(0113); repeated reviewed stock receipt and exact supplier invoice tranches
(0114); reviewed AP installments composed with existing partial payment-link
allocation (0115). Preserve OPS1's full-source contract. New FI1 installment
plans retain exact amount, original invoice/version, residual and accounts.

Finance owns financial_reporting files and 0112; Sales owns stock_sales and
0113; Procurement owns procurement_partial and 0114, with separate Studio
components and tests. The lead owns financial_installments/0115, shared native
admission, routing, authorization, Studio navigation, recovery/packaging/CI
inventories and integration. All three worktrees start at exact F24.

Every monetary effect shares one scoped READ COMMITTED owner transaction with
the native document, immutable command, audit and outbox. Maker/checker/poster
are independent current humans. Deferred guards close source and financial
phases in both directions, including direct SQL and generic native routes.
Exact minor units, bounded quantities, deterministic frozen retry and current
scope/amount policy are mandatory. Claims remain experimental and bounded.

Local native68/zero-skip, domain/contracts47, React295, normal HTTPS cycles,
214-table/197-function populated restore, current package/image/security and
bounded synthetic recovery pass on source6ec9. See the source-bound acceptance
packet in docs/execution/ERP_EXPANSION_ACCEPTANCE_2026-10-09.json. Current-source
hosted checks belong to DraftPR126; they are not inferred from local results.

Build in batches; verify actual cycles at integration gates. Freeze the source
before full Python/PostgreSQL/React/browser/security/concurrency/recovery/build
and hosted verification. Preserve failures and environmental prerequisites.
Add no skips or security bypasses. Populated destructive downgrade is refused;
application rollback retains additive schemas and immutable financial evidence.
