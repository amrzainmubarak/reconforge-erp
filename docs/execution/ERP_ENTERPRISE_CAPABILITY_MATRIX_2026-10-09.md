# Enterprise ERP capability comparison: bounded evidence, October 9, 2026

This program starts from PR126 `21b4b8a2`, preserving PR125 and PR124. This
matrix compares identifiable business capabilities, not product quality, market
rank, certification, operating cost or performance. Vendor documentation proves
documented product behavior; it does not prove ReconForge implements the same
configuration breadth. No equivalent vendor workload was available for a
controlled performance comparison. Final source-bound acceptance is separate
from the implementation and milestone evidence below.

## Operating scope

| Capability | ReconForge implementation in this program | Evidence and explicit limit | SAP / Oracle / Dynamics reference scope |
| --- | --- | --- | --- |
| Multi-line sales and partial deliveries | New immutable commercial parent with up to 1,000 item/UOM/location lines; separately reviewed native fulfillment, invoice and cash tranches | Native 1,000-line admission/approval and one last-line complete cycle; actual two-item/two-warehouse/four-paid-tranche Studio milestone. This does not prove 1,000 fully settled lines per order. | SAP S/4HANA documents [partial and subsequent deliveries](https://help.sap.com/docs/SAP_S4HANA_ONPREMISE/7b24a64d9d0941bda1afa753263d9e39/5721bf53d25ab64ce10000000a174cb4.html). Other vendors' equivalent sales configurations were not assessed in this matrix. |
| Multi-line procurement | One authoritative native AP purchase order and one native multi-line supplier invoice; line-specific partial receipts and exact allocations | Native mixed EA/KG, two warehouses, four receipts, two invoices and four installment payments; 128-line admission. No sum of heterogeneous units. | Dynamics documents [line-level items, units, warehouses, prices and discounts](https://learn.microsoft.com/en-us/dynamics365/supply-chain/procurement/tasks/create-purchase-order). |
| Receipt/invoice matching | Immutable per-line order/receipt/invoice quantity and exact price closure; native FIFO, inventory GL and AP accrual | Exact three-way matching only; configurable price/tax tolerances, landed charges and two-way approval policy are remaining capabilities. | SAP documents [PO invoices and GR/IR clearing](https://help.sap.com/docs/SAP_S4HANA_ON-PREMI-SE/af9ef57f504840d2b81be8667206d485/be5eb6531de6b64ce10000000a174cb4.html). Oracle documents [PO/receipt matching, partial shipments and receipt charges](https://docs.oracle.com/en/cloud/saas/financials/25d/fappp/matching-invoice-lines.html). Dynamics' line-level purchasing reference is linked above. |
| Partial cash settlement | New commercial parent tracks separately invoiced/paid tranches; procurement reuses actual reviewed FI1 AP installments | A paid sales tranche fully collects its own invoice. Partial collection of an individual AR invoice is still a gap; AP installments are genuine cumulative payments. | Oracle documents [individual partial receipts](https://docs.oracle.com/en/cloud/saas/financials/26b/fairp/how-can-i-use-partial-receipts.html), which is broader than the new sales tranche implementation. SAP/Dynamics receipt allocation configurations were not assessed here. |
| Warehouse stock and FIFO | Reuses reservation, physical location balances, native issue/receipt, cost layers and balanced postings | Competing orders cannot reserve beyond available physical stock; cancellation releases capacity. FIFO cost pools remain entity/item/lot across locations. Warehouse-specific costing and new transfer/count workflows are not claimed. | The Dynamics purchasing reference documents site/warehouse defaults and overrides; it is not a comparable FIFO benchmark. |
| Financial statements and drill-down | New immutable MVCC birth-sealed native-effect capture, streaming verified aggregation, trial balance, balance sheet, income statement and cash movements; bounded keyset evidence pages | Actual 1,005 native-effect reporting milestone beyond legacy 1,000-effect limit. Cash movements are not a jurisdiction-approved statutory cash-flow statement. Legacy bounded endpoint retains its refusal. | Statement standards and statutory configurations across vendors are not assessed by this program. |
| Multi-company / FX consolidation | Existing reviewed close, budget, FX and consolidation foundations are preserved; this program reuses their permission and native posting boundaries | New operational multi-currency settlement, FX valuation journals, intercompany elimination and unified multi-company statements remain incomplete. | Dynamics documents [multi-company consolidation, elimination and currency translation](https://learn.microsoft.com/en-us/dynamics365/finance/general-ledger/financial-consolidations-currency-translation). No parity claim is made. |
| Global tax, assets, treasury, sourcing and returns | Existing kernels remain available where already implemented; no superficial replacement modules added | Country/period tax configuration and posting, fixed-asset depreciation cycles, banking settlement integrations, credit limits, price-list governance, multi-level commercial approvals, PR/RFQ and customer/supplier return-credit cycles remain outside accepted new scope. | Oracle's matching reference explicitly describes receipt charges and supplier credits. Broader vendor modules require their own source and configuration assessment. |

## Engineering scope

New owners reuse current human identity, existing permissions and ABAC,
FORCE RLS, exact integer/Decimal amounts, native double-entry posting,
append-only commands and audit/outbox linkage. Financial publication requires
three distinct current humans. No extra financial engine or mandatory vendor
service was introduced; no dependency or MIT license change was necessary.

Native integration gates cover direct SQL source/owner/phase tampering,
lost acknowledgement and exact replay, late-effect rollback, row conflicts,
cross-parent stock capacity and cross-workspace/tenant refusal. The report
membership seal closes the previously untested nested-trigger admission path
without removing legitimate temporary-table privileges. The global FIFO
chronology guard now compares the actual same item/lot cost pool rather than
blocking unrelated item receipts; same-pool date/order constraints remain.

Actual HTTPS Studio and populated `pg_dump`/`pg_restore` gates are required for
all three new owners in CI. They verify restored rows, routines, finite ACLs,
FORCE RLS, unbound/foreign scope invisibility and three financial tamper
refusals. Their passing state belongs to the exact captured source, not to the
presence of these tests or this document.

## Measurement and next acceptance

The executable `.github/scripts/benchmark_enterprise_finance.py` generates
deterministic independent integer account totals, prepares/reviews/posts every
entry through three persisted humans, and alternates warmed legacy/public
reads against bounded verified batches on the same immutable history. It
records exact source, PostgreSQL image/version/configuration, concurrency,
latency percentiles, client execute calls, Python heap peaks and engine resource
metadata. A client execute count is not a server-internal SQL statement count.

The first clean 100-entry milestone at `61bf6d7b` measured 1.311 completed
three-human native cycles/second with four workers, including authentication;
public verified-read median 0.750258s versus 0.051644s for batches, 14.528x,
300 versus 2 client execute calls. It is not HTTP TPS, a general ERP throughput
limit or acceptance of the later integrated source. The separately measured
1,005-entry reporting-owner benchmark uses a different legacy internal reader
and must retain its own baseline and digest. Final measurements require a
clean fixed integrated commit and a fresh evidence directory.

The clean `347d3714` 100/1,000-entry run completed in716.203s. Its1,000
genuine cycles produced independently expected493,671,004minor units with
zero errors,1.475595cycles/s and2.621/3.236/4.186s p50/p95/p99 cycle latency.
On that same immutable1,000-effect history, three alternating warmed read
repetitions measured median6.867102s→0.464948s,14.769607x, with3,000→20
client execute calls. The indexed raw packet records the larger bounded-page
Python heap, database settings and final resource sample; no peak-memory,
million-effect, equivalent-vendor or production sizing claim follows.

Next work is ordered by a measurable complete cycle: individual AR partial
receipts and return-credit/refund closure; configurable procurement variance
and landed-cost approval; same-day high-volume FIFO scalability with stable
cost order; operational FX valuation/settlement and tax posting; multi-entity
intercompany/elimination; then treasury/bank adapters and asset depreciation.
Each must reach real Studio-to-native-GL execution, restore and concurrency
acceptance before being marked implemented and proven.
