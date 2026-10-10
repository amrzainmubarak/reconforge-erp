# Global capability and engineering gap matrix — Wave4

Research date2026-10-10. This is an evidence update above accepted PR129e07bff2a,
not a replacement for the17-domain [coverage matrix](GLOBAL_CAPABILITY_COVERAGE_2026-10-10.md)
and [Wave3 evidence](GLOBAL_CAPABILITY_COVERAGE_WAVE3_2026-10-10.md). Documentation
availability describes a vendor feature; it does not establish our implementation
parity, their measured limits or a superiority result. Current Wave4 code is a
candidate until its integrated native/browser/restore and exact-head CI gates pass.

| Capability / official vendor evidence | ReconForge retained base and implemented candidate | Proven evidence / remaining gap | Complexity and next dependencies | Measurable opportunity |
|---|---|---|---|---|
| Original customer returns / credits: [SAP S/4 customer returns](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/1dad2180e6f34b75ac77afce5cb5eda1/13ec4980b29311da2b24000f20dac9ef.html); [Oracle26D credit memos](https://docs.oracle.com/en/cloud/saas/financials/26d/farfa/op-receivablescreditmemos-post.html) | Native stock-commerce/FIFO/AR/CA1 retained. CR1/CRF1 candidate returns a whole delivered source, restores original FIFO/COGS, credits revenue/AR and recognizes/refunds the collected entitlement. | Pure/API16 tests pass; initial native failures retained; final original-return gate and actual HTTPS/restore pending. Functional-currency zero-tax original source only. No arbitrary partial quantity, FX/tax return or shipment-dependent disposition claim. | High: source-specific tax/FX reversals, consumed/restored layers, landed-cost history, period and cash governance. Partial line return requires cumulative original-cost apportionment and independent residual oracle. | Measure immutable source→inverse GL→FIFO evidence verification, race/retry atomicity, query/CPU costs. Vendor credits already exist; concept is not globally unique. |
| Purchase commitments: [Dynamics Finance budget control](https://learn.microsoft.com/en-us/dynamics365/finance/budgeting/budget-control-overview-configuration) documents requisition/PO commitment controls. | Existing native procurement/budget/AP/LC1 reused. BPC1 binds approved appropriation to a multi-line PO, consumes only posted receipt/AP value and releases the unreceived residual. | Frozen7f72c770 native/API24 pass/0skip. Studio master-only seed and actual HTTPS/populated restore still pending. No PR/RFQ or multi-level budget approval claim. | High: one fiscal envelope, retained precision/version, serialized competing appropriation; supplier-return budget reinstatement must conserve original reserve/consume/release history. | Direct SQL bidirectional source/budget closure and observed blockers are testable advantages within our implementation; no vendor parity score without comparable adversarial tests. |
| Supplier return: [NetSuite vendor return management](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2386202.html) covers authorization, shipment and credit/refund workflows. | Existing native receipt reversal/AP foundation. SR1 is next: whole original unissued receipt and exact unpaid AP debit, preserving original cost/cash history. | Planned/in progress; no completed supplier-return claim yet. Paid supplier refund, partial returns, BPC1 budget reinstatement remain unimplemented. | High: original FIFO eligibility, original AP accrual inverse, landed-cost expense disposition, payment-vs-return lock ordering and authoritative credited projection. | Explicit GL/FIFO/AP conservation under SQL bypass, late failure and response loss. |
| Foreign AR, partial collection and realized FX: [Oracle26D receipt application](https://docs.oracle.com/en/cloud/saas/financials/26d/faofc/guidelines-for-applying-receipts-and-on-account-credit-memos.html); [Odoo19 multi-currency](https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html) | Existing currency registry/GL/AR reused. FX1 recognizes a taxed foreign invoice into functional GL, partially collects at retained dated rates and posts realized gain/loss using cumulative historical release. | Pure24 pass; first native cycle/API2 pass at9cea6a86; expanded native/current-grant/browser/restore candidate pending. Retained0/2/3 currency precision is tested. | High: foreign AP, inclusive/withholding taxes, national determination rules, credit reversals, historic policy migration. Manual versioned effective tax components are not a complete country tax product. | Independent minor-unit oracle and browser cryptographic seals for every original/settlement effect, current authority on replay, no duplicated FX/ledger. |
| Unrealized FX/revaluation: [Dynamics AR/AP revaluation](https://learn.microsoft.com/en-us/dynamics365/finance/cash-bank-management/foreign-currency-revaluation-accounts-payable-accounts-receivable); [Oracle26B revaluation](https://docs.oracle.com/en/cloud/saas/financials/26b/faiac/overview-of-revaluations.html) | Historical rate metadata and realized settlement candidate exist; governed native revaluation over open exposure is not completed. | Missing independent unrealized balances, source-owned reversals before settlement, consolidation effects. | High: outstanding exposure capture→three-human revaluation→exact corrective reversal→settlement, closed-period evidence and account classification. | A retained exposure snapshot, deterministic delta and independently verified reversal can be measured; do not relabel realized settlement as revaluation. |
| Group finance and close | Retained native GL/report snapshots/classifications, period controls and consolidation control foundations. | Wave4 does not complete operational intercompany settlement, group elimination ledger, global tax or complete IFRS/GAAP statements. | High: FX translation vs transaction FX, legal entities, investment ownership, elimination rules and drill-down source capture. | Source-native immutable report membership with independently reproduced balances. |
| Manufacturing, MRP and planning | Inventory valuation/reversal and manufacturing cost control packs retained. | BOM→work order→WIP→completion/variance/QC and native MRP remain missing. No superficial manufacturing APIs added. | Very high: issue/reservation semantics, routing/UOM, partial completion/scrap, actual cost accumulation and finished-goods/FIFO/GL closure. | Consistent WIP/inventory/GL and resource cost per fully completed production cycle. |
| HCM/payroll/CRM/projects/service/industry operations | Existing limited operational/control foundations only, as separately described in the17-domain matrix. | Broad operational suites remain gaps; no new worldwide ERP completeness claim. | Domain engines, statutory localization, permissions and lifecycle depth precede broad UI coverage. | Prioritize genuine business-cycle evidence over count of modules/routes. |

## Engineering comparison and decision record

Published competitor results exist, but none found supplies equivalent hardware,
durability, current-human permission checks and this exact fully posted workload.
[SAP sizing](https://www.sap.com/about/benchmark/sizing/decision-tree.html) defines
SAPS using fully processed sales order lines/hour. The [Oracle/Cisco EBS R12.1.3
batch benchmark](https://www.oracle.com/a/ocom/docs/applications/ebusiness/cisco-o-to-c-ora-lrg-b200-16-c-9-14-12.pdf)
actually dates to September2012:100,000 lines,16 cores/128GB,29.20-minute wall
clock,205,479 lines/hour extrapolation. Its multi-stage order-to-cash process and
storage differ from this four-worker two-line journal benchmark. No speed ratio
or ranking is valid. [Dynamics posting guidance](https://learn.microsoft.com/en-us/dynamics365/finance/general-ledger/posting-performance)
describes posting strategies, not an equivalent published resource-cost packet.

Our benchmark uses fresh actual three-human journals, exact independent integer
oracles, retained raw failure evidence, alternating order and kernel CPU counters.
The earlier Wave3 single-population +6.78% throughput and +36.45% sample-window CPU
are historical observations. The new posting-window CPU measurement separates
client and PostgreSQL cgroup CPU; those windows must not be mixed to imply a gain.
The current9-case read-policy correctness gate passes; same-workload repeated
performance acceptance remains pending. Monetary cost requires an explicit cost
model; it stays null rather than inventing a currency figure.

Evidence-native operation, source closure, governed AI and observability already
have global alternatives. ReconForge's opportunity is an open, inspectable,
local-first implementation with verifiable database enforcement and measured cost.
There is no independent cross-vendor security, accuracy or production audit here.
AI forecasting/automation is not newly completed by this wave.

## Stable technology / security references

- Preserve Python/PostgreSQL/React modular monolith and pinned PostgreSQL17.10
  test image. PostgreSQL18 documentation is available; upgrading engines requires
  a separate migration, parity and measured resource benefit, not novelty.
- [PostgreSQL17 RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html),
  [statement snapshot semantics](https://www.postgresql.org/docs/17/xfunc-volatility.html)
  and [planning counters](https://www.postgresql.org/docs/17/pgstatstatements.html)
  guide ADR0850. No SECURITY DEFINER cache, durability relaxation or session-level
  permission memoization. Experimental join-collapse settings were rejected.
- [NIST SSDF publications](https://csrc.nist.gov/projects/ssdf/publications):
  SSDF1.1 remains final;1.2 revision is draft. SP800-218A is a final AI profile.
- [OWASP ASVS releases](https://github.com/OWASP/ASVS/releases): use stable5.0.0;
  bleeding-edge snapshots are not a stable release or certification.
- No new library/service is required for the candidate optimization. Existing
  locked dependencies, action SHAs, MIT project license, provenance/SBOM and
  security/restore gates remain authoritative; PR checks do not attest a signed
  production release or standards compliance.

Next order: accepted original customer/foreign-AR cycles→supplier-return/AP
closure→budget reinstatement/paid and partial returns→FX revaluation→native
production/WIP cycle→group intercompany/eliminations, expanding every lifecycle
through native storage, API authority, audit and an actual Studio journey.
