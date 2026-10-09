# Global capability coverage: inspected products and bounded ReconForge evidence

Research date: 2026-10-10. Implementation baseline: PR127 `34b9e7a5`, stacked on
PR126/125/124. This is a capability and dependency map, not a product ranking.
Vendor documentation establishes documented functionality, not equivalent
configuration, license entitlement, accounting guarantees or measured speed.
Release numbers below identify the inspected documentation; a readiness entry
for a newer release is not proof that a customer has deployed it. ReconForge
milestone results remain provisional until the final integrated source gate.

## Official reference register

| Product and inspected documentation | Documented scope used in this matrix | Qualification |
| --- | --- | --- |
| SAP S/4HANA Cloud [scope overview](https://help.sap.com/docs/SAP_S4HANA_CLOUD/9d794cbd48c648bc8a176e422772de7e/e237c247cc454f1b8307e52d0624d0f4.html), [manufacturing](https://help.sap.com/docs/SAP_S4HANA_CLOUD/a376cd9ea00d476b96f18dea1247e6a5/5c00965653691e5ee10000000a4450e5.html) | Finance, sales, procurement, production planning/execution and quality, projects | Public/private editions and release scope differ. Some Help Portal pages return no body to the browser tool; indexed official descriptions establish category scope only. |
| SAP [business-network integration 42K](https://help.sap.com/docs/SAP_S4HANA_CLOUD/0e602d466b99490187fcbb30d1dc897c/7a29e94495f64f3cb1bae215382b795e.html), [Employee Central scope](https://www.sap.com/docs/download/agreements/product-policy/css/service-specifications/feature-scope-description-for-sap-successfactors-employee-central-english-v5-2025.pdf) | RFQ/PO/receipt/invoice/payment messages; personnel and payroll integration | Separate integrations/services, not an assertion that every capability is bundled into one ERP license. |
| Oracle Fusion [Financials 26C](https://docs.oracle.com/en/cloud/saas/financials/26c/index.html), [partial AR 26B](https://docs.oracle.com/en/cloud/saas/financials/26b/fairp/how-can-i-use-partial-receipts.html), [assets 26C](https://docs.oracle.com/en/cloud/saas/financials/26c/faias/overview-of-asset-categories.html) | Financial accounting, individual partial receipt allocation, asset categories/books and depreciation policy | Partial-receipt reference actually inspected is 26B. No claim of identical country coverage or financial controls. |
| Oracle Fusion SCM 26C [manufacturing](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26c/faumf/index.html), [pricing](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26c/faupr/index.html), [SCM structures](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26c/faicf/index.html), [integration playbooks](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26c/faips/overview-of-the-scm-integration-playbooks.html), [projects 26C](https://docs.oracle.com/en/cloud/saas/project-management/26c/index.html) | Plant/process/production/genealogy; pricing lists/strategies/rounding; suppliers/UOM/legal entities/approvals/attachments/imports; projects and SCM integrations | Suite modules and integration options are distinct. The official readiness catalog also lists 26D; this map does not relabel inspected 26C behavior as a 26D assessment. |
| Microsoft Dynamics 365 [record-to-report, July 2026 catalog](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/record-to-report-overview), [plan-to-produce](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/plan-to-produce-areas), [fixed assets](https://learn.microsoft.com/en-us/dynamics365/finance/fixed-assets/fixed-assets), [consolidation](https://learn.microsoft.com/en-us/dynamics365/finance/general-ledger/financial-consolidations-currency-translation) | Budget/close/finance, BOM/routes/capacity/quality, asset acquisition/depreciation/disposal, group currency translation/eliminations | Product configuration matters; the process guide explicitly permits products with inventory ledger posting disabled. We do not infer an unconditional database invariant from a workflow diagram. |
| Dynamics [project operations](https://learn.microsoft.com/en-us/dynamics365/project-operations/), [hire-to-retire](https://learn.microsoft.com/en-us/dynamics365/guidance/business-processes/hire-to-retire-overview), [PO lines](https://learn.microsoft.com/en-us/dynamics365/supply-chain/procurement/tasks/create-purchase-order) | Projects, personnel/payroll interfaces, item/site/warehouse/price/discount lines | HR/payroll integration is not proof of every country payroll calculation in the ERP itself. |
| NetSuite [partial payments](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N1289458.html), [landed costs](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2418831.html), [per-line charges](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_3728979515.html), [projects](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_N1179876.html), [SuitePeople](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_1495573671.html) | Partial invoice payments/unapplied credit, weight/quantity/value receipt or bill charges, project cost/revenue, HR/workforce and U.S. payroll | Separate from Oracle Fusion. SuitePeople U.S. Payroll is not global payroll. Project management can require an add-on. |
| Odoo 19 [finance](https://www.odoo.com/documentation/19.0/applications/finance.html), [inventory/manufacturing](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp.html), [valuation operations](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/inventory_valuation/operations_valuation.html), [services](https://www.odoo.com/documentation/19.0/applications/services.html), [after-sales](https://www.odoo.com/documentation/19.0/applications/services/helpdesk/advanced/after_sales.html), [payroll](https://www.odoo.com/documentation/19.0/applications/hr/payroll.html) | Double-entry multi-company finance, stock/cost/BOM planning, freight/duties valuation, projects/helpdesk/field service, returns/credit notes, localized payroll | Apps depend on other apps and edition/localization. The specific 19.0 landed-cost page timed out; the inspected valuation page supports freight/duty capitalization. Country completeness was not assessed. |

## ReconForge coverage and execution dependencies

`N` = new native implementation in this sprint; `P` = preserved accepted scope;
`F` = existing foundation with narrower/nonposting semantics; `G` = gap.
Tests listed are executable evidence paths, not a statement that every test has
passed on the final head. Module manifests retain explicit experimental status.
Complexity is relative engineering effort, not an unsupported calendar estimate.

| Domain | Existing/new executable scope | Milestone evidence paths and bounded proof | Gap, dependency and complexity | Measurable differentiation opportunity |
| --- | --- | --- | --- | --- |
| Commercial orders and fulfillment | P: 1,000-line admission, locations/reservations, separately reviewed delivery and invoice tranches | `test_postgres_stock_commerce*.py`; actual two-item/two-warehouse/four-tranche wire. Admission does not prove a 1,000-line fully settled order. | G: configurable pricing/promotions/contracts/credit exposure/backorders. Depends on versioned price and exposure policy; high. | Price/exposure decision evidence plus conflicting reservation correctness under identical load. |
| Individual-invoice AR and cash | N: CA1 reviewed partial collections compose existing native receipt/allocation/cash GL | `test_postgres_commercial_collections.py`; `commercial-collections-cycles.spec.ts`; integer cash/AR/COGS oracle | Functional currency, positive zero-tax stock invoice, one active claim, at most 200 plans/invoice. Returns/refunds/reversals remain G; high dependency on original FIFO/recognition evidence. | Lost-ACK replay and SQL-enforced source/receipt/effect equivalence, measured with actual receipts. |
| Procurement and matching | P: mixed-unit multiline PO, partial receipts/invoices/payments and exact three-way closure | `test_postgres_procurement_multiline*.py`, procurement live wire; exact native AP/FIFO/GL | G: PR/RFQ/quote comparison, tolerances, commitments/budget integration, supplier scoring. Existing budget kernel is not integrated purchase control; high. | Explain every price/quantity variance without silently clearing mismatches. |
| Landed cost | N: LC1 prepaid freight/duties allocated by exact merchandise value before FIFO publication | `test_landed_cost.py` independent rational oracle; `test_postgres_landed_cost*.py`; `erp-landed-cost.spec.ts` | 128 selected lines/200 bundles per order. No published-layer rewrite; no freight AP accrual, weight/volume allocation or later revaluation. Depends on adjustment/reversal owner; high. | Immutable allocation evidence and source/FIFO/GL atomicity across heterogeneous units. Weight/value/quantity allocation already exists in other ERPs; novelty is not claimed. |
| Inventory and warehouses | P: exact quantities, physical reservations, movements, FIFO, source-bound native receipts/COGS | Native inventory/stock/procurement groups; multilateral SQL closure | G: complete transfer/count UI, warehouse-specific cost pools, serial/batch operational breadth. Entity/item/lot FIFO scope preserved; high. | Independent conservation oracle under reservation, transfer, issue and failure races. |
| Assets | N: FA1 cash acquisition, cumulative exact straight-line months, disposal gain/loss | `test_fixed_assets.py` independent Decimal oracle; `test_postgres_fixed_assets.py`; `fixed-assets-cycles.spec.ts` | Functional currency only; 1–1,200 months, no proration/tax books/impairment/AP capitalization/transfer. Depends on AP/FX/policy owners; high. | SQL-retained acquisition/depreciation/disposal proof, no cumulative rounding drift. Acquisition/depreciation/disposal itself is standard vendor functionality. |
| Statements and close | P: immutable MVCC membership capture, streaming verified trial balance/balance sheet/income statement/cash movements; close foundations | `test_postgres_financial_reporting*.py`, snapshot migration/recovery and wire; over 1,000 effects | Cash movements are not a statutory cash-flow statement. G: operational closing completeness, statutory presentations, group report integration; high. | Reproducible report membership/effect digests and drill-down without silently truncating. |
| FX, tax and treasury | F: currency registry, exact FX/reconciliation, bank statement/control foundations; native GL remains functional currency | Existing FX/bank/finance tests, preserved scope only | G: foreign-currency operational subledger, realized/unrealized journals, country-period tax owner, bank execution/controls. Historical exposure source first; very high. | Frozen rate/tax provenance and exact reversible journals; no standalone FX ledger. |
| Intercompany/consolidation | F: scoped ownership/PPA/close/elimination proposals and translation | Existing consolidation/intercompany groups retain nonposting limitations | G: paired operational intercompany posting, settlement, posting eliminations and unified group statements; requires FX/entity accounting; very high. | Both sides and elimination enforce a shared immutable source contract. |
| Manufacturing and supply planning | F: manufacturing cost-control/evidence and inventory planning | Existing manufacturing-cost-control and inventory-planning groups | G: full BOM/routing/work-order execution/MRP/production capitalization/quality/replenishment optimization; depends on supply valuation/issue/completion; very high. | Independent component/WIP/finished-goods conservation through actual production. |
| CRM and sales planning | F: customer master and transaction history | Existing master-data/receivable scope; no new CRM/forecast claim | G: leads/opportunities/contracts/campaigns/forecast pipeline; medium after commercial source completion. | Forecast inputs trace to authorized actual orders, with uncertainty and human review. |
| Expenses, projects and allocations | F: reviewed expense/operational finance, budget and control primitives | Existing native operational-finance/budget scope only | G: employee expense UI/reimbursement breadth, project/time/billing/cost-center allocation source owner; high. | Reusable reviewed allocation evidence linked to original expense/time sources. |
| HCM and payroll | G: identity users are not employees or payroll | No payroll/HCM acceptance evidence | Employee/employment/pay/calendar/country legislation/time inputs and payroll liability owner required; very high. | Country golden datasets and reproducible pay calculations; avoid superficial personnel screens. |
| Service and industry operations | F: exception workflows, retail/professional/banking integrity packs | Existing pack-specific tests; not field-service/retail/POS/AML products | G: tickets/SLA/contracts/dispatch/parts/billable time and full industry execution; high. | Authorized evidence connects service, parts, invoice and settlement. |
| Integrations, documents and workflow | P/F: native identity/policy/outbox/jobs/evidence, import/export/connectors and approvals | Existing route/native/job/evidence groups | Connector exports are not live vendor connectors. G: complete document lifecycle, provider conformance and multilevel operational approval policies; medium/high. | Durable idempotent integration with explicit egress and evidence per business effect. |
| Intelligence, observability and resources | P/F: governed AI assistance and existing telemetry; N: raw benchmark cycle/read vectors, sampled PostgreSQL/WAL/waits/container/process resources | `test_enterprise_financial_benchmark.py`; `.github/scripts/benchmark_enterprise_finance.py` | No new production forecasting/anomaly model accepted. Sampling can miss spikes; cost is null without a cost model. No multi-region failover proof; high. | Optimize only after source-bound profiling, same-workload retest and independent financial oracle. |

## Standards and comparison limits

[NIST SP800-218 SSDF 1.1](https://csrc.nist.gov/pubs/sp/800/218/final) remains the
inspected final publication. [SSDF 1.2](https://csrc.nist.gov/pubs/sp/800/218/r1/ipd)
is an initial public draft, not a replacement final standard. The inspected
[OWASP ASVS project](https://owasp.org/projects/asvs) identifies 5.0.0 as its
latest stable version. Pinned CI actions/dependencies, current authority checks,
RLS, immutable source closure, negative API/SQL tests, SBOM/image scanning and
isolated restore provide control evidence; they do not establish independent
ASVS certification or full SSDF conformance.

No reproducible competitor packet with equivalent hardware, durability, business
cycle, data, authority checks and independent financial oracle was available.
NetSuite's [5,000-line CSV transaction import limit](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N410731.html)
is an import constraint, not a latency/TPS benchmark. No vendor superiority,
global functional parity, statutory compliance or production-readiness claim is
permitted by this matrix. Evidence-native behavior, integrated finance and AI
assistance are not asserted to be globally unique merely because they are new
in ReconForge.

## Dependency-first next execution order

1. Original-source customer/supplier returns, credit/debit and cash reversal,
   preserving FIFO and settlement evidence; then concurrent restitution oracle.
2. Purchase sourcing/approval/commitment control and post-receipt landed-cost
   adjustment owner; then complete variance and supplier return workflows.
3. Foreign-currency source/subledger exposure, rate snapshots and realized/period
   revaluation journals; configured tax policy follows the same source contract.
4. Entity-paired intercompany, elimination posting and group close/reporting.
5. BOM/routing/issue/completion/WIP production cycle; planning uses proven stock
   and cost conservation instead of creating a parallel inventory engine.
6. Projects/service/expenses and governed forecasts over proven operational data;
   HCM/payroll requires independent country-specific validation.

Every stage requires UI/API/native source acceptance, negative authorization and
SQL tests, replay/failure tests, populated restore and measured resource limits.
