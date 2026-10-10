# Wave4 incremental acceptance — 2026-10-10

This packet records accepted bounded native operations at their actual frozen source commits. **Final Wave4 acceptance remains pending.** It does not combine historical sources into a final-head regression or claim production readiness, certification or global superiority. PR129 `e07bff2a2e8197b052d53454ea85c727f7c7518e` is the starting source; earlier PR history and the benchmark index remain intact.

The companion JSON embeds exact original report serialization and SHA256, commands, source fingerprints, independently parsed JUnit counts and diagnostic sidecar hashes. It preserves failed and interrupted attempts. Raw sidecars stay in the recorded owner output paths; this document does not claim they have been copied into the source distribution.

## Actual HTTPS and populated restore

| Bounded cycle | Frozen source | Duration | Restored head / table count | Raw report SHA256 |
|---|---|---:|---|---|
| customer_returns | `9c4bea54` | 165.156s | 0129_pg_financial_read_plans / 249 tables | `b5be76a4e655c0ecfb11a7cc42cf008947d6df08fd158d260cd28f16fc214f44` |
| procurement_commitments | `9c4bea54` | 138.141s | 0129_pg_financial_read_plans / 249 tables | `cee18c7d6e20830068c6659a77047ff02989885da387301aacaf3032d8867cbb` |
| fx_five_stage | `1e73267e` | 104.546s | 0131_pg_fx_revaluation / 253 tables | `594b41ada0420a647b1c0b99aa083c0d631635276e7a7aa133352706c65ae027` |
| supplier_returns | `92230f4a` | 161.672s | 0131_pg_fx_revaluation / 253 tables | `f2682341253a49275d894f1de6190115fac5adc60ebf5dbef7db6d0e46310503` |

Each accepted browser packet has one expected scenario, zero skipped/unexpected/flaky scenarios, an application role with `[false,false]` superuser/bypass-RLS flags, unchanged clean source and built web bytes, three SQL tamper refusals, identical persisted/restored financial results and owned HTTPS/container cleanup. These are actual synthetic local workflows and real native backup/restore proofs; they do not establish general HA/RPO/RTO or enterprise load capacity.

Customer return at `9c4bea54` credits the original **45,000 minor units**, releases **35,000** unpaid AR and establishes/refunds the original **10,000** collected amount in two installments. It restores the original **10 units /12,000 minor units** of FIFO cost, retains the original receipt and consumption, keeps reviewed cancellation history and finishes with zero refund due. Nine native effects have **156,000** debit and credit turnover. The contract covers whole zero-tax functional-currency delivered tranches; partial quantities, taxed and foreign stock sources remain gaps.

Procurement commitment at `9c4bea54` retains the original **17,000** multi-line PO reservation, consumes **7,400** with native AP accrual and releases **9,600**, leaving budget availability **12,600**. Two receipts, one supplier invoice and two payments produce five native effects, **22,200** balanced turnover and **7,400** remaining inventory value. PR/RFQ/quotation/contracts and budget-backed supplier-return appropriation reinstatement remain gaps.

The five-stage FX journey at `1e73267e` retains **11,401 EUR minor units /14,251 USD functional minor units**. Foreign receipts **4,000/7,401** release historical AR **5,000/9,251**; closing unrealized FX **+740** is reversed by **−740** before the final settlement. Realized gain/loss are **200/370**, cash ends at **14,081**, native AR ends Paid with zero balance, and unrealized gain ends zero. Effective configured tax, currency precision and original source/rate evidence remain retained. Broader AP/stock FX, group translation and arbitrary tax jurisdictions are outside this slice.

Supplier return at `92230f4a` passed actual HTTPS and populated restore in **161.672s**. Ten native effects have **66,414** debit and credit turnover: the original AP credit is **12,000**, original FIFO removal is **12,706**, paid landed charges are disposed to approved expense of **706**, and final inventory/cash are **5,295/−6,001** minor units. The journey cancels a reviewed claim, prepares a fresh same-source replacement and posts through three humans, with two receipts, two invoices and two installments. Restore retains **253 tables, 80 populated tables and 2,076 rows**, exact catalog/ACL/FORCE RLS and three SQL tamper refusals. English/Arabic, 390-pixel layouts and accessibility checks passed. The failed `1e73267e` duplicate-panel and `5512f01c` populated-select attempts remain retained. The bounded supplier contract accepts a whole unissued original receipt and exact accrued unpaid AP source, including expense disposition of original paid landed charges. It excludes partial/consumed/adjusted receipts, paid merchandise AP and BPC1 sources. The complete latest 28-case native file set still requires final hosted acceptance.

## Native correctness and authority

The complete customer-return file passed **15 tests** on clean `9c4bea54` in **639.415s**. It includes independent integer/Fraction expectations, unpaid/partially/fully collected sources, direct SQL barriers, late rollback, return/refund races, exact lost-response replay, current original-precision parent authority, restricted legacy roles, charged FIFO restitution and actual lock blockers against a new sale.

The BPC1 native/API packet passed **24 tests** on clean `7f72c770` in **498.809s**. Original FX packets contain **19 unique executed case IDs**, with overlap between the full 16-case, account 2-case and restore 3-case runs retained explicitly. Closing valuation/inverse passed a separate complete **6-test** file set at `5ac359c1` in **205.020s**; the retained-position authorization follow-up passed at `dcdbe8c7` in **41.096s**. These source-bound packets remain separate; their counts are not a substitute for final unified CI.

Native posted effects and original policies remain immutable. The slices reuse existing inventory/AR/AP/cash/GL engines and enforce current scoped authority and independent human preparation/review/posting. Corrections use native exact inverse/restoration effects and protected source closure. No duplicated ledger, currency registry or permission engine is introduced.

## Static, packaging and integration evidence

The committed integration contract at `2f40d28c` verifies **459 routes** with digest `f41b3007bbcc9cc1285cc836be0cb2e81d2e2c4e03713f83f6d245db27fccc9a` and preserves the accepted 429/432 route digests. It retains complete-file mandatory native coverage, unique CI ownership, two new native shards and a ten-scenario actual browser/restore matrix.

On clean `1e73267e`, seven completed gates passed: full Ruff; Mypy over 707 source files; Bandit; pip-audit; React 404/404 with zero pending/todo; Python sdist/wheel build; and isolated archive verification. The archive has a complete **131-revision** chain at `0131_pg_fx_revaluation`, retains the 125 checkpoint, checks exact required source/wheel members and MIT, imports helpers from extracted source and removes temporary extraction. pip-audit audited 126 installed dependencies with zero known findings; it skipped the local ReconForge 0.7.1 package because it is not on PyPI. This is the scanner's bounded result, not a vulnerability-free claim.

The local general Python partition was **explicitly interrupted after 355.721s for the UI repair**, with `accepted=false`, no completed JUnit and verified owned-process cleanup. Final complete general acceptance will come from the exact final hosted CI head. Completed `1e73267e` gates remain evidence for that source; the final archive and CI must bind later publication changes separately.

## Pending gates and development order

1. Exact-final-head hosted CI and complete mandatory native/general/security/package gates, preserving the four completed actual HTTPS/restore packets at their recorded source commits.
2. Three equivalent baseline/candidate benchmark pairs, retaining raw timings, CPU/RAM/I/O, warmup, hardware, durability, failures and independent oracle checks. No performance improvement is claimed in this packet.
3. Mixed 10,000/100,000/1,000,000 operations and 1,000-line business documents under declared resource ceilings; these packet fixtures do not prove those loads.
4. Taxed/partial/foreign customer corrections and partial supplier corrections, with native source/tax/FX ownership and budget appropriation reinstatement.
5. PR/RFQ/quotations/contracts through governed PO/accrual/payments, then BOM/routing/work orders/material issue/completion/costing/quality and MRP after demand/source contracts.
6. Remaining group/treasury, HCM/payroll, project/service and governed intelligence functions, prioritized by the official-source capability matrix and engine dependencies. AI remains advisory for sensitive financial actions.

Reproduction requires each recorded source commit, locked dependencies, that source's built Studio/Chromium and the raw report's pinned PostgreSQL image. Use a new output directory for every run. Compare exact monetary results and source fingerprints; randomized IDs and aggregate digests across fresh databases are not parity targets. See the companion JSON and operator runbooks for the complete original commands, retained failures and bounded contracts.
