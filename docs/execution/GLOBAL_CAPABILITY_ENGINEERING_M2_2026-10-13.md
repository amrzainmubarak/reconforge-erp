# Source-qualified global capability and engineering gaps

Observed on2026-10-13. This is a functional gap matrix, not a competitive
performance result. Product edition, optional application and documentation
version matter. Competitor documentation describes available scope; it does
not independently prove ReconForge scope or a comparative resource advantage.

| Official reference and observed scope | ReconForge existing evidence | Missing / partial cycle | Owner, dependencies and acceptance | Engineering opportunity and limit |
| --- | --- | --- | --- | --- |
| [SAP S/4HANA Cloud manufacturing,2608](https://help.sap.com/docs/SAP_S4HANA_CLOUD/a376cd9ea00d476b96f18dea1247e6a5/5c00965653691e5ee10000000a4450e5.html): official indexed text covers engineering, planning, production execution and quality. [Production versions](https://help.sap.com/docs/SAP_S4HANA_CLOUD/2bba750d1e124e1ea2a039bb1cd9b6c5/c234b8535c39b44ce10000000a174cb4.html) bind validity/lot ranges, BOM alternatives and task lists | Accepted M1 original BOM/routing, FIFO material issue, WIP, actual posted labor/overhead claims, partial quality hold, inspection, FG/scrap. New M2 native demand/onhand custody/shortage purchasing/handoff original cost3600=FG3240+scrap360 | No full MPS/MRP/capacity/scheduling/multi-plant/lot genealogy/by-product cycle | Agent1; Root quantity ownership, approved engineering and source-owned PO/AP/budget are prerequisites. Actual complete Studio cycle plus native recovery/current authority must pass on frozen head | Original source arithmetic and bounded exclusive quantity custody can be measured. They are not proof that SAP lacks traceability. SAP page retrieval here is indexed official text, not an exhaustive detailed implementation audit |
| [Oracle SCM26D use index](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26d/use.html) lists inventory, costing, receipt/landed-cost and supply-chain financial orchestration. [Work-order cost review26D](https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26d/fapma/review-work-order-costs.html) documents cost review for manufacturing work orders | Actual approved sourcing/RFQ/quotes/third-human award, budget-bound PO/partial receiving/AP; M2 purchases original shortage1EA+2.5KG, budget/AP1450, then existing production owner takes custody | Foreign/tax-aware procurement contracts and adjustments, broader landed-cost variances, paid partial supplier restitution and replenishment planning | Agent1 operations; exact quote/receipt/FIFO/budget/GL membership, idempotency and source-held concurrency are mandatory | Reduce overhead only after profiling actual mixed source workloads. Index coverage is not a full26D costing comparison; no Oracle TPS result is inferred |
| [Dynamics365 Finance consolidation and translation](https://learn.microsoft.com/en-us/dynamics365/finance/general-ledger/financial-consolidations-currency-translation), updated2026-05-04: multi-company aggregation, eliminations, currencies/calendars/charts, minority-interest scenarios and original-transaction drill-back; date-batch parallelism is documented | Accepted M1 two-party IC2 foreign trade, partial settlement, revaluation/inverse, historical translation and actual adjustment GL. M3 development source cashflow and Project reconciliation passed actual TLS with isolated original-file oracles | Whole-group balance population, ownership/NCI/investment/profit-in-stock, complete close/statutory reporting; M3 bounded selected-source diagnostic is not these capabilities | Agent2/Root; original source membership, captured reporting policy, current read caps, explicit opening basis and period authority. Group cycle requires independent balances and whole-source restore | Dynamics already documents source-company ownership and drill-back; those features are not claimed globally unique. Opportunity is reproducible original-population verification at measured resource cost |
| [NetSuite Advanced Manufacturing overview](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_1506368304.html): optional SuiteApp extends routing, work instructions, material usage, resource demand, labor/downtime and mobile/shop-floor reporting | Original BOM/routing/material/WIP/quality cost cycle, approved Project time and gross wage source claims exist in M1 | Work centers/capacity, live shop-floor labor attribution, downtime/OEE, maintenance and integrated production scheduling | Agent1/Agent3; approved public time and private wage boundaries, actual production source allocation, asset/maintenance ownership and native cycle | Automatic payroll-to-production costing is not yet implemented. Optional SuiteApp capability must not be attributed to every NetSuite base deployment |
| [Odoo20 manufacturing index](https://www.odoo.com/documentation/20.0/applications/inventory_and_mrp/manufacturing.html): official indexed navigation lists BOM/work centers, WIP, MPS, by-products, lots/serials, shop-floor time and subcontracting | Single bounded original order supply and manufacturing cycle; accepted inventory/FIFO, gross payroll/time and Project billing foundations | Full planning, subcontracting, lot/serial genealogy, by-products, capacity and complete employee workflows | Agent1/Agent3; build connected cycles before claiming module completion, with original inventory/GL and employee permission evidence | This retrieval is index-level official coverage; full page retrieval timed out. Master-branch documentation is not silently treated as stable20. No unmatched Odoo benchmark is used |

## Enterprise scope beyond manufacturing and finance

| Capability | Existing / proven scope | Missing / partial | Acceptance and independent evidence | Owner / complexity |
| --- | --- | --- | --- | --- |
| CRM, contracts and service | Original customers/stock sales/AR/collections and eligible returns; no full CRM/service assertion | Leads/opportunities/renewals/subscriptions, entitlements/dispatch/SLAs and service billing | Authorized daily Studio lifecycle linked to original sales/AR/cash/GL; immutable amendments and independent contractual calculations | Agent3; high, depends on commercial pricing, workflow and source ownership |
| HCM and statutory payroll | Private personnel, approved public Project time, budget-backed gross2501, original wage1268/1233 and partial payments1000+1501; ordinary private-row count0 | Attendance/leave/shifts/benefits/deductions/self-service and statutory payroll | Effective rules, three humans, independent gross-to-net/payable/cash/GL, country-qualified sources and privacy/recovery | Agent3; high. All countries target, proven statutory packs0 |
| Projects, resources and billing | Independent public time76min×2001/hour +74min×3001/hour=6236; actual native AR/cash1000+5236 and separate wage claims | WBS/resource planning, contract amendments, full Project statements; source-close diagnostic in development | Preserve original price/time/wage claims and current read caps. Original Project margin is distinguishable from whole-document cash/payables | Agent3; high, depends on source-owned HCM/PB/GL |
| Tax, banking and treasury | Captured currencies/rates and generic tax/FX, bank reconciliation and payment-control foundations | Bank execution, complete liquidity forecast, country reporting/rules and statutory interpretation | Authorized synthetic bank sandbox/statement/payment lifecycle and independent tax/FX/cash equations per declared country | Agent2; high. Currency/country codes do not establish legal support |
| Controlled AI | Existing governed assistance surfaces, human-owned sensitive actions | Full evaluation-backed enterprise forecasting, anomaly detection and bounded automation | Same-tenant authorized evidence, prompt/model/evaluation versions, injection/adversarial tests; financial posting/permission changes remain governed | Agent3/Root; high. No autonomous sensitive posting added by this cohort |

## Five engineering guarantees and current comparison boundary

1. Exact operational/financial consistency: reuse original GL/FIFO/source owners,
   ACID and exact arithmetic. Original costing/claim/receipt proofs are retained;
   legacy raw inventory movement before valuation remains an explicit gap.
2. Isolation/current authorization: FORCE RLS, source-scope pins, independent
   human phases and current persisted permission/cap checks. The supported
   fractional unit-price authorization red is retained and53 native correction
   cases pass; integrated final acceptance is pending.
3. Immutable evidence/replay: original SQL populations, deterministic bytes,
   receipt digests and isolated Fraction-based arithmetic. In-project independent
   computation is not external audit attestation.
4. Recovery/lifecycle: accepted M1 actual native/HTTPS/restore/package/security
   gates; M2/M3 full frozen source gates remain pending. Same-host recovery does
   not demonstrate multi-region HA/DR.
5. Resource efficiency: no accepted new TPS/latency/CPU/RAM or cost claim. Native
   source-report transport now coalesces original JSON tokens into at most64KiB
   chunks without changing bytes/digest; mechanism verification is not throughput
   evidence. Owner deferred benchmarks; per-operation cost remains null.

[NIST SSDF official publications](https://csrc.nist.gov/projects/ssdf/publications)
lists SSDF1.1 as Final and1.2 as Draft, with the AI profile800-218A Final. Draft1.2
is not treated as a stable compliance requirement. Existing ASVS/SBOM/locked
dependency/source-image controls remain engineering references, not certification.
No equal-workload competitor performance evidence was established. Competitive
claims remain functional scope and proposed experiments, never invented TPS.

Priority: close current Studio/read-authority gates; publish source-qualified
M2; complete M3 original multi-source and Project diagnostics; then extend real
partial return restitution and production planning/work-center capacity before
country-qualified employee/treasury cycles. Preserve earlier negative and
interrupted performance evidence until a new fair comparison is authorized.
