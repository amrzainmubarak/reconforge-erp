# Global capability coverage: governed abandonment and verifiable asset evidence

Research date: 2026-10-10. This successor adds to the seventeen-domain
[coverage matrix](GLOBAL_CAPABILITY_COVERAGE_2026-10-10.md); its unchanged rows
and precise scope limits remain applicable. PR127 `34b9e7a5` and its
PR126/125/124 ancestors remain the accepted historical baseline. Actual PR128
head `69951414` supplies the existing CA1/LC1/FA1 owners, with failed hosted
security, ordinary-AR and draft-scope checks that this slice addresses. Their
acceptance is not inferred from feature existence or from an older green run.

## Updated official sources and competing functionality

| Product / inspected official source | Documented capability | Consequence for this slice |
| --- | --- | --- |
| Oracle Fusion [Financials26D](https://docs.oracle.com/en/cloud/saas/financials/26d/index.html), [SCM26D](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26d/index.html) | Current documentation catalogs include finance, assets, receivables and SCM books. The earlier matrix's detailed26B/26C references retain their actual inspected versions. | Publication of26D does not establish identical deployed editions, nor does a catalog prove financial or concurrency invariants. |
| Microsoft Dynamics365 [landed-cost overview](https://learn.microsoft.com/en-us/dynamics365/supply-chain/landed-cost/landed-cost-overview), [voyage management](https://learn.microsoft.com/en-us/dynamics365/supply-chain/landed-cost/manage-voyages) | Freight/duty allocation supports multiple bases, estimated/actual cost accounting and goods in transit. Voyage deletion is constrained by lifecycle state. | ReconForge's prepaid value allocation is narrower. Governed abandonment is useful workflow completion; it is not claimed as a globally new capability. Post-receipt actual-cost adjustment remains a gap. |
| NetSuite [item return costing](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2199328.html), [customer credit memos](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N1311306.html) | Calculated or fixed returned-item cost and AR credit-memo/return workflows are documented. | Original FIFO-consumption restitution, customer credits and refunds are material ReconForge gaps. Generic GL reversal cannot safely substitute for these contracts. |
| SAP [customer returns](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/7b24a64d9d0941bda1afa753263d9e39/ef17554b70b946e588cf4fb378fa4622.html) | The official indexed description covers logistics and financial customer returns. Body extraction was unavailable. | Establishes category availability only; no claim about uninspected configuration or database enforcement. |
| Odoo [19.0 returns](https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/returns.html), [after-sales](https://www.odoo.com/documentation/19.0/applications/services/helpdesk/advanced/after_sales.html), [20.0 credit-note documentation](https://www.odoo.com/documentation/20.0/applications/finance/accounting/customer_invoices/credit_notes.html) | Inspected19.0 guidance covers warehouse reverse transfers and credit notes;20.0 documentation is officially indexed. Subsequent body fetches timed out. | Preserve19.0 inspected behavior and retrieval limitations. No inference of20.0 stable deployment or full country coverage. |

No directly comparable competitor benchmark packet was found for the same
hardware, durability, synthetic dataset, three-person authority, complete
business effect and independent financial oracle. No cross-vendor performance
ranking follows from this feature map.

## Executable coverage delta

| Capability | Existing owner and new implementation | Test / runtime evidence contract | Missing scope; complexity and dependencies | Differentiation to measure |
| --- | --- | --- | --- | --- |
| Abandon an unposted invoice installment | CA1 cancel action releases the residual claim and reusable receipt name, retains original preparation/review/validated GL and immutable cancellation evidence. Three distinct humans after review; posted receipts cannot be cancelled. | `test_postgres_commercial_collection_cancellation.py`; actual collections Studio wire, lost-response replay and restored cancellation table. | Refunds, credits, source inverses, tax and FX remain absent. High: requires original invoice/FIFO/settlement conservation. | Equal financial state before/after cancellation; no SQL bypass, stale approval or duplicate business effect. |
| Abandon charged receiving before publication | LC1 immutable cancellation releases selected PO receiving capacity while preserving allocations, native receipt plans, reviews and unposted GL. Ordinary receiving keeps its narrower grants. | `test_postgres_landed_cost_cancellation.py`; Studio cancel/replacement; populated native restore; mixed two-UOM/two-warehouse oracle. | No posted-layer rewrite, supplier return or freight AP accrual. High: adjustment owner must account for issued stock, remaining stock and clearing. | Procurement capacity and physical/FIFO/AP/GL conservation across cancellation/post races. |
| Asset-to-ledger evidence drill-down | FA1 source definition, lifecycle plan, native effect/snapshot, actors and audit/outbox references compose the existing ledger. Authorized source-cost/history-turnover reads and client-side canonical digest verification. | `test_postgres_fixed_assets_evidence.py`; real acquisition/depreciation/disposal wire with proof verification and restored evidence. | No tax books, foreign-currency assets, proration or impairment. High: policy/rate/AP source owners first. | Verifiable exact integer evidence and safe drill-down without a parallel ledger or broader read authority. |
| One operational/financial truth after abandonment | Opening capital, cancelled/replaced landed receiving, partial AP, FIFO sale, cancelled/replaced AR collection and asset lifecycle feed the original classified reports. | Both branches of `test_postgres_global_operating_cycles.py` must yield18 effects,184156 minor debit=credit, cash45898 and inventory11648; independent rational allocation and direct posted-effect fold. | Single tenant/entity/functional currency. No large mixed ERP throughput or global consolidation proof. | Same financial oracle despite abandoned reviewed work; retained evidence cannot enter posted statements. |
| Efficient native snapshot verification | One scoped aggregate replaces per-line dimension SELECTs; existing canonical snapshot and validation digest remain authoritative. Opt-in profiler records template digests/timings, without SQL parameters or rows. | `test_postgres_posting_snapshot_profile.py`:1000-line parity and RLS; alternating same-fixture measurements and matched native-posting retest. | One measured host, sampled resources; no unmeasured throughput, cost, HA or million-operation claim. | Reduced query count and measured latency with byte-equivalent financial digest and unchanged authorization. |

Test names establish reproducible verification entry points. Source-bound
acceptance and actual measurements are recorded separately; this matrix never
substitutes for a successful final gate. All three existing owners remain
experimental and retain their manifest ceilings.

## Dependency-first continuation

1. **Source-bound returns and credits:** immutable invoice credit residual,
   original FIFO issue-consumption restitution, original revenue/tax inverse,
   cash refund allocation and every existing owner closure. Start with a bounded
   whole unpaid zero-tax return; expand only after its full SQL/API/Studio oracle.
2. **Procurement commitments and adjustments:** PR/RFQ/quotation comparison,
   budget-backed approvals, actual freight liabilities and received/issued stock
   adjustment conservation; then supplier debit/return and variance resolution.
3. **Multi-currency operational exposure:** historical rate snapshots, realized
   settlement difference and period revaluation; then country/period tax policy.
4. **Intercompany and group close:** paired source posting and settlement,
   elimination journals and classified group statements over proven FX owners.
5. **Production execution:** BOM/routing, component issue, WIP/completion/scrap,
   independent quantity/cost oracle, then MRP and replenishment over actual stock.
6. **Projects, services and intelligence:** authorized source data and reviewed
   forecasts; HCM/payroll follows country-specific independent golden validation.

The security references remain [SSDF1.1 final](https://csrc.nist.gov/pubs/sp/800/218/final),
[SSDF1.2 initial public draft](https://csrc.nist.gov/pubs/sp/800/218/r1/ipd) and
[ASVS5.0.0 stable](https://owasp.org/projects/asvs). No certification or complete
conformance claim is made. Python/PostgreSQL/React and the modular monolith are
preserved; profiling rather than technology substitution drives optimization.
