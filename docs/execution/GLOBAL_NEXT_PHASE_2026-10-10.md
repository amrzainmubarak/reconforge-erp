# ReconForge next phase: complete operating cycles and measured admission

Planning date: 2026-10-10. Proposed targets imply no acceptance, novelty or superiority.
Preserve PR127 and its PR126/125/124 ancestors, current native source owners,
Python/PostgreSQL/React, exact arithmetic, FORCE RLS and the modular monolith.
Bind new delivery claims to their actual commit, migrations and acceptance packet.

## Verified contract boundaries before expansion

- Legacy `StockOrder` is single-item; `CommercialOrder` admits 1–1,000 lines.
  The thousand-line test completes only the last tranche; 999 lines remain unfulfilled.
- Multiline procurement permits 128 PO/invoice-allocation lines and 1,024 retained
  receipts/invoices; legacy one-line orders retain their 32-part contract.
- Landed cost permits 128 selected lines and 200 retained bundles per order.
  Cancellation releases quantity capacity, retaining drafts and receipt budgets.
- Collections retain 200 plans/invoice, one active; assets retain 1–1,200 months.
- The 1,000-line journal snapshot fixture measures one journal's read parity,
  authorization and query calls, not 1,000 settled lines or mixed business TPS.

## 1. Original-source customer return, credit and refund

Start with one whole unpaid zero-tax invoice return in functional currency.
Reference immutable invoice lines and original FIFO issue consumptions; append
restitution and credit effects without rewriting published issues or journals.
Conserve returned quantities, original COGS, revenue, AR and remaining creditable
value. Two concurrent returns must not restore the same consumed stock twice.
Then support partial/multiline returns, original discount allocation, collected
invoice credits and cash refunds allocated to actual prior settlements.
Taxed returns require original components/policy provenance, without current-policy rerating.
Independent acceptance folds original sale, return, credit and refund effects and
checks inventory quantity/value, receivable residual and cash separately.

## 2. Purchase sourcing, commitments and actual charge liabilities

Deliver PR → RFQ → supplier quotations → deterministic reviewed comparison →
budget-backed PO → partial receipt/invoice/payment, using existing AP/FIFO/GL.
Reserve, consume and release commitments atomically with current budget authority;
concurrent approvals cannot spend one budget balance twice. Preserve rejected
quotes and approval evidence; price/quantity variances need explicit disposition.
Add supplier freight/duty AP liabilities and post-receipt actual-cost adjustments.
Allocate adjustments between remaining stock and already issued costs without
rewriting original FIFO consumptions; support period-lock refusal and retries.
Then complete supplier return/debit-note and payment-credit allocation cycles.

## 3. Operational FX, effective tax, intercompany and close

Attach transaction currency, functional amount and historical rate/source/time to
existing operational exposures. Deliver foreign invoice → partial settlement →
realized FX, then open-exposure revaluation and explicit reversal next period.
An independent rational oracle checks conversion, residuals and rounding using existing engines.
Version tax by country, effective period and transaction classification, retaining
taxable basis, exemption/rounding decision and original-policy credit inversion.
Next deliver paired intercompany source/settlement, elimination posting and group
close over proven entity/FX contracts. Check both entities and consolidation;
cash-movement reports do not become statutory cash-flow statements by renaming.

## 4. Production execution before MRP

Version BOM and routing; execute reviewed work order → component FIFO issue →
WIP → completion/scrap/variance → finished-goods receipt and quality disposition.
An independent component/WIP/output oracle conserves quantities and total cost
under partial completion, scrap, failure and concurrent material reservation.
MRP, replenishment and demand planning follow actual stock, open commitments,
lead-time evidence and completed production semantics; no parallel stock engine.

## 5. Commercial depth, projects, services and HCM

Add versioned pricing/contracts/promotions and credit exposure to proven sales;
CRM forecasts expose source coverage and backtesting before decision use.
Then connect project/service commitments, expenses, assets and revenue recognition
to the same native financial owners. HCM/payroll requires country-specific
employment/calendar/tax rules and independent gross-to-net golden datasets.
Governed AI proposes authorized decisions with provenance and human approval.

## Mandatory integration and quantitative gates

Every cycle reaches PostgreSQL, backend/API and actual populated Studio workflows.
Require direct-SQL bypass, tenant/entity RLS, current permission withdrawal, three
human duties, concurrent conflict, lost-response replay and worker-failure tests.
Verify migration, populated backup/restore and guarded rollback; refused commands preserve snapshots.
Use independent financial/quantity oracles, not implementation-derived expectations.
Complete 1/16/128-line orders first; fully settle 1,000 commercial lines only after
bounded evidence/resource admission. A 1,000-line PO requires a separately reviewed
contract increase; raising a constant does not establish safe processing.
Measure 1,000 → 10,000 → 100,000 → 1,000,000 completed mixed cycles only as resources
permit, with 2/4/8/16 submitting workers and distinct current posting identities.
Record successful business effects, refusals/retries, p50/p95/p99, CPU/RAM/I/O/WAL,
locks/deadlocks, raw timings, seed, versions, hashes and resource cost assumptions.
Compare baseline → profile → cause → optimization → identical-workload retest.

## Testable differentiation, without novelty claims

Evidence-native operations: measure lineage coverage, tamper detection and bounded
source-to-report verification latency against the retained financial digest.
Operational/financial closure: inject failures and SQL mutations at every owner
boundary; require zero accepted inventory/AR/AP/cash/GL divergence and exact replay.
Self-diagnosis: opt-in redacted profiling must identify injected waits or slow
stages with measured detection delay and false positives, without financial rows.
Efficient scale: publish capacity per CPU/RAM and cost per successful effect only
after matched measurements; unprofiled scale and absent cost models remain gaps.
