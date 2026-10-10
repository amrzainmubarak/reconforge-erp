# Global capability and engineering gap matrix — Wave4

Research date2026-10-10. This is an evidence update above accepted PR129e07bff2a,
not a replacement for the17-domain [coverage matrix](GLOBAL_CAPABILITY_COVERAGE_2026-10-10.md)
and [Wave3 evidence](GLOBAL_CAPABILITY_COVERAGE_WAVE3_2026-10-10.md). Documentation
availability describes a vendor feature; it does not establish our implementation
parity, their measured limits or a superiority result. Four bounded native business
cycles have actual source-bound HTTPS/populated restore acceptance. All38 jobs in
[hosted run38059696904](https://github.com/amrzainmubarak/reconforge-erp/actions/runs/38059696904)
passed at b6e9dcf6, including complete native/API owner gates, actual HTTPS/restore
and ordered0132/package/security checks. The
[incremental packet](WAVE4_ACCEPTANCE_2026-10-10.md) retains their separate commits,
failures and limits. Three fresh matched1K pairs are financially valid, but resource
acceptance is false; the amended documentation/evidence-head archive and checks
remain pending. No full platform or vendor superiority is claimed.

| Capability / official vendor evidence | ReconForge retained base and implemented candidate | Proven evidence / remaining gap | Complexity and next dependencies | Measurable opportunity |
|---|---|---|---|---|
| Original customer returns / credits: [SAP S/4 customer returns](https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/1dad2180e6f34b75ac77afce5cb5eda1/13ec4980b29311da2b24000f20dac9ef.html); [Oracle26D credit memos](https://docs.oracle.com/en/cloud/saas/financials/26d/farfa/op-receivablescreditmemos-post.html) | Native stock-commerce/FIFO/AR/CA1 retained. CR1/CRF1 returns a whole delivered source, restores original FIFO/COGS, credits revenue/AR and recognizes/refunds the retained collected entitlement in installments. | Complete native15 and actual HTTPS/populated249-table restore pass at9c4bea54: credit45000, AR release35000, original cash10000 refunded, FIFO10 units/12000 restored. Original charged cost, source history, current whole-turnover authority, actual lock blockers and SQL/race/rollback/retry covered. Complete native15 and actual HTTPS/populated253-table restore also pass at b6e9dcf6;0132 preserves exact original inverse closure and ordinary-role compatibility. Functional-currency zero-tax original source only; partial quantity, FX/tax return and arbitrary credits remain gaps. | High: source-specific tax/FX reversals, consumed/restored layers, landed-cost history, period and cash governance. Partial line return requires cumulative original-cost apportionment and independent residual oracle. | Measure immutable source→inverse GL→FIFO evidence verification, race/retry atomicity, query/CPU costs. Vendor credits already exist; concept is not globally unique. |
| Purchase commitments: [Dynamics Finance budget control](https://learn.microsoft.com/en-us/dynamics365/finance/budgeting/budget-control-overview-configuration) documents requisition/PO commitment controls. | Existing native procurement/budget/AP/LC1 reused. BPC1 binds approved appropriation to a multi-line PO, consumes only posted receipt/AP value and releases the unreceived residual. | Frozen7f72c770 native/API24 pass/0skip. Actual master-only seeded Studio cycle and populated249-table restore pass at9c4bea54: reserve17000, consume7400, release9600, two receipts and two installments. Complete24 native/API cases and actual HTTPS/populated253-table restore pass at b6e9dcf6. PR/RFQ/contracts, charge appropriation, return reinstatement and multi-level budget approvals remain gaps. | High: one fiscal envelope, retained precision/version, serialized competing appropriation; supplier-return budget reinstatement must conserve original reserve/consume/release history. | Direct SQL bidirectional source/budget closure and observed blockers are testable advantages within our implementation; no vendor parity score without comparable adversarial tests. |
| Supplier return: [NetSuite vendor return management](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2386202.html) covers authorization, shipment and credit/refund workflows. | Existing native receipt reversal/AP reused. SR1 returns a whole original unissued receipt and exact accrued unpaid AP source, preserves original history and disposes paid capitalized landed charges to approved expense. | Actual HTTPS/populated253-table restore pass at92230f4a, including reviewed cancel/reprepare, three humans, two receipts/invoices/installments and EN/AR accessibility. AP credit12000/FIFO removal12706/charge expense706, ten effects balanced66414. Complete28 native/API cases and actual HTTPS/populated restore pass at b6e9dcf6. Partial/issued/adjusted receipts, paid merchandise AP/refund, taxed/foreign sources and BPC1 budget reinstatement remain unsupported. | High: original FIFO eligibility, original AP accrual inverse, landed-cost expense disposition, payment-vs-return lock ordering and authoritative credited projection. | Explicit GL/FIFO/AP conservation under SQL bypass, late failure and response loss; paid charge disposition is explicit and does not fabricate a cash refund. |
| Foreign AR, partial collection and realized FX: [Oracle26D receipt application](https://docs.oracle.com/en/cloud/saas/financials/26d/faofc/guidelines-for-applying-receipts-and-on-account-credit-memos.html); [Odoo19 multi-currency](https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html) | Existing currency registry/GL/AR reused. FX1 recognizes a configured taxed foreign invoice into functional GL, partially collects at retained dated rates and posts realized gain/loss using cumulative historical release. | Original source-bound native packets contain19 unique executed cases, including retained0/2/3 precision. Five-stage actual HTTPS/populated253-table restore passes at1e73267e: EUR gross11401, USD gross14251, two settlements, realized gain200/loss370 and cash14081. Portable stdlib Fraction oracle pins all original proof/report bytes and native effect membership to a separately trusted manifest. Full native/API and five-stage HTTPS/populated restore gates also pass at b6e9dcf6; historical overlapping packets are not summed. | High: foreign AP, inclusive/withholding taxes, national determination rules, credit reversals, historic policy migration. Manual versioned effective tax components are not a complete country tax product. | Independent minor-unit oracle and browser cryptographic seals for every original/settlement effect, current authority on replay, no duplicated FX/ledger. |
| Unrealized FX/revaluation: [Dynamics AR/AP revaluation](https://learn.microsoft.com/en-us/dynamics365/finance/cash-bank-management/foreign-currency-revaluation-accounts-payable-accounts-receivable); [Oracle26B revaluation](https://docs.oracle.com/en/cloud/saas/financials/26b/faiac/overview-of-revaluations.html) | Governed native closing valuation captures original outstanding foreign/historical/closing values and dated rate, posts unrealized FX and requires an exact original native inverse before settlement. Current authority covers the full emitted position at original precision. | Complete closing/inverse6-case gate at5ac359c1 and retained-position1 atdcdbe8c7 pass. Actual five-stage1e732 cycle values foreign7401/historical9251 at closing9991, posts +740 and original inverse−740, then final AR/unrealized zero; independent portable oracle verifies these equations and native linkage. Complete closing/inverse and five-stage HTTPS/populated restore pass at b6e9dcf6; AP/stock exposure, group translation and consolidation revaluation remain gaps. | High: broader source-owned exposures, corrective period governance, functional account classification and consolidation/translation policies. | Retained exposure, deterministic delta, exact inverse and current original-position ABAC can be independently measured; transaction FX is distinct from group translation. |
| Group finance and close | Retained native GL/report snapshots/classifications, period controls and consolidation control foundations. | Wave4 does not complete operational intercompany settlement, group elimination ledger, global tax or complete IFRS/GAAP statements. | High: FX translation vs transaction FX, legal entities, investment ownership, elimination rules and drill-down source capture. | Source-native immutable report membership with independently reproduced balances. |
| Manufacturing, MRP and planning | Inventory valuation/reversal and manufacturing cost controls retain evidence persistence/API/Studio. The manufacturing repository exports control results and does not post inventory, WIP or GL. | Operational BOM/work order→component FIFO issue→WIP→completion/scrap/variance/QC→finished-goods/GL and native MRP remain missing. | Very high: issue/reservation semantics, routing/UOM, partial completion/scrap, actual cost accumulation and finished-goods/FIFO/GL closure. | Consistent WIP/inventory/GL and resource cost per fully completed production cycle. |
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
Six fresh1K runs compare b7df9271 with07452da8 in BC/CB/BC order. Normal and
optimized-Python financial oracles pass under trusted manifest
c5dfa70b980a9532e14e7e93e65e24f6c9fbf0f9c56524d63985fbcbaed31acc.
Median throughput improves36.02% and combined client/database CPU per success
falls23.54%, but client CPU rises22.46% and bounded batch read rises10.28%.
Resource acceptance is false. These four-worker two-line cash/equity journal
measurements do not establish mixed operational or complete1,000-line sales/PO
capacity; the1,000-line report fixture proves read parity only. Six raw reports
and oracles are staged under wave4-evidence/posting-1k; the new evidence-head
archive is pending. Fresh10K scale and HA/DR RPO/RTO are unaccepted. Monetary cost
requires an explicit cost model and stays null.

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

Next order: amended-head archive/CI closure and client CPU/batch-read remediation
→budget reinstatement/paid, partial and taxed/foreign returns→PR/RFQ and funded
charges→broader FX/tax and intercompany close→production/WIP→native MRP. Each
cycle must close SQL/API/Studio with current authority, independent financial
oracles, concurrency/lost-response and populated restore evidence.
