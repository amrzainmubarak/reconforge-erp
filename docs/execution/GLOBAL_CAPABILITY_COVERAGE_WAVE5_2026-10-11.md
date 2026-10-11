# Wave5 capability and engineering gap matrix

Reviewed 2026-10-11. This matrix distinguishes implemented source from executed
acceptance. Final integration, HTTPS/restore and performance gates are pending.
The Wave4 matrix and its limitations remain authoritative for unchanged slices.
No global superiority or production readiness is established by this work.

| Capability and official competitor evidence | ReconForge implementation | Executed evidence at this checkpoint | Remaining dependencies and complexity | Measurable differentiation opportunity |
|---|---|---|---|---|
| Production actual cost/WIP: [SAP production accounting](https://help.sap.com/docs/SAP_S4HANA_CLOUD/4032610758dc437089f0c28320eec93f/e7f14152fe4eaa1ae10000000a445394.html), [Dynamics production lifecycle](https://learn.microsoft.com/en-us/dynamics365/supply-chain/production-control/production-process-overview), [NetSuite WIP](https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2337938.html) document material consumption, production and costing workflows. | ME1 versioned approved base-UOM BOM, whole component reservation, native FIFO issue into WIP, reviewed partial finished receipt and abnormal scrap through existing GL/FIFO. Canonical requirements can be referenced by sourcing. | Clean1880b215 four-case native owner gate passed without skips; independent integer/Fraction cost2900 = finished2610 + scrap290 + remainingWIP0. Subsequent reciprocal evidence-seal repair is pending retest. | Very high: labor/overhead/routing, normal-yield treatment, rework, quality, capacity planning and full MRP remain gaps. Bounded same-date receipt identity search is a documented throughput limitation. | Measure source-to-native cost conservation, retained ACK/evidence verification and complete production-cycle resource cost under SQL bypass and concurrency. Manufacturing functionality itself exists in competitors. |
| Paired company books and group elimination: [Oracle consolidation eliminations](https://docs.oracle.com/en/cloud/saas/financial-consolidation-cloud/agfcc/intercompany_eliminations.html), [Dynamics consolidation](https://learn.microsoft.com/en-us/dynamics365/finance/general-ledger/financial-consolidations-currency-translation) document consolidation, currency translation and eliminations. | IC1 same-functional-currency recognition and partial settlement in two original entities; native elimination GL in a distinct authorized group adjustment entity. Existing reviewed report maps generate three-book financial statements with original-effect drilldown. | Clean13bb4344 five-case nonowner PostgreSQL gate passed, zero skips: recognition10001 per company, cash3000 per company, elimination17002, five native effects; independent group balances/net income/net cash zero. Late second effect, competing settlements, native/public inverse denial and current three-scope ABAC passed. HTTPS/populated restore remains pending. | High: reporting-currency translation, ownership/noncontrolling interests, inventory-profit eliminations, dividends/investments, policy differences and subsequent corrections. Elimination seals this bounded source against further settlement. | Atomic cross-entity effect closure and independently reproducible elimination membership are testable; no claim that group reporting or drilldown is unique. |
| Requisition/RFQ/quotation/award: [Oracle26D supplier negotiations](https://docs.oracle.com/en/cloud/saas/procurement/26d/oaprc/oracle-supplier-negotiations.html), [Oracle26D award outcomes](https://docs.oracle.com/en/cloud/saas/readiness/scm/26d/proc26d/26D-procurement-wn-f51980.htm) document negotiation from requisition lines to purchasing documents and approval-dependent award finalization. | SRC5 immutable requisition, independently opened RFQ, retained offers, deterministic reviewed selection and third-human atomic native BPC1 budget-reserved PO. Existing partial receipt/AP/payment lifecycle reused. | Corrected owned26 native/API cases passed without skips. Independent golden reserve17000, consume7400, release9600; five native effects total debit=credit22200. Reciprocal full-quotation amount-authority repair needs new acceptance; final ME1 demand linkage/HTTPS/restore pending. | High: contracts, multi-level policy-driven approvals, split awards, foreign/taxed budget procurement, charges and supplier-return budget restitution. Up to128 lines/32 offers in this bounded slice. | Evidence of exact quote-to-PO-to-budget closure, source-owned SQL effects and permission revocation on replay; benchmark real multi-line workflows, not table inserts. |
| Customer/supplier partial and foreign/tax returns | Wave4 CR1/SR1/FX1/LC1/BPC1 retained. Original whole customer return/refund and eligible supplier receipt return remain available within original contracts. | Prior accepted130 evidence retained. New Wave5 sourcing/manufacturing does not automatically extend return eligibility. | Very high: cumulative partial original FIFO/COGS/tax/FX reversals, paid AP restitution, consumed layers, landed charge disposition and BPC budget conservation. No one-function guard relaxation is sufficient. | Independently verify cumulative original-cost residuals and source-native cash/AR/AP/GL consistency under racing returns and payments. |
| Treasury, close, fixed assets, FX and tax | Existing native FX revaluation/inverse, approved accounting periods, fixed assets and financial reporting reused. IC1 introduces original group-native effects without a parallel ledger. | Wave4 acceptance retained; new IC1 tested with reviewed report maps. | Country tax determination/local statutory rules, foreign AP, group translation, advanced treasury and broader financial dimensions require separate complete cycles. | Faster immutable report membership/drilldown with original precision and current authorization. |
| HCM/payroll, projects, service, CRM, planning and industry operations | Existing control foundations remain; this wave concentrates on production, sourcing and native group books. | No new operational completeness claim for these domains. | Statutory localization, domain lifecycle models and source-owned financial effects precede broad UI coverage. | Prioritize end-to-end operating value; module count is not evidence of superiority. |

## Engineering evaluation

The accepted6362724f baseline was freshly profiled with genuine three-human
posting, nonowner FORCE RLS, independent minor-unit oracle and unchanged source.
The single-worker100-cycle profile found authentication KDF CPU and repeated
native account reads/line writes and SQL planning costs. It is descriptive,
instrumented discovery, not a repeated fair improvement measurement. The KDF,
current authorization and financial triggers remain intact. Bounded account-read
and parameterized128-row insertion batches passed the actual1,000-line native
snapshot/independent legacy oracle and invalid-final-account atomicity tests.

The new external controller uses the same byte-fingerprinted harness for both
unchanged application checkouts, BC/CB/BC fresh populations,20 real warmups,
four workers, three repeated read measurements, independent financial/resource
verification, full active power parameter bookends and sampled AC/frequency.
Final CPU/RAM/latency/throughput acceptance remains pending. Monetary transaction
cost is unavailable without an actual resource price model. No equivalent vendor
hardware/durability/workload packet has been established, so no vendor speed ratio
is valid.

[PostgreSQL version policy](https://www.postgresql.org/support/versioning/) lists
17.11 as the current supported17 minor. [17.11 release notes](https://www.postgresql.org/docs/17/release-17-11.html)
include security fixes to role-dependent cached plans, SQL/server behavior and
backup clients; minor upgrades normally preserve the data directory but may need
configuration/reindex review. The frozen17.10 historical synthetic baseline is not
described as the latest secure server. An immutable17.11 image and separate
security/migration/restore acceptance are being verified. Comparisons must use
the same pinned server image on both application versions. PostgreSQL18 or19beta
adoption, partitioning, a new analytical engine and microservices are not justified
by the current profile.

[NIST publications](https://csrc.nist.gov/Projects/ssdf/publications) identify
SSDF1.1 as Final and1.2 as Draft; draft status must not be represented as final.
[OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
provides the security verification reference. Mapping controls and publishing
test evidence does not establish certification or universal tax/legal compliance.

## Next complete-cycle priorities

1. Close final135 migration/permissions, exact historical ACK/outbox scope seals,
   concurrency/revocation/late-failure and populated HTTPS/restore gates.
2. Measure final source on matched1K and bounded10K populations; reject unsupported
   resource improvements and retain adverse samples and execution boundaries.
3. Implement partial supplier/customer return accounting including original-cost
   cumulative residuals and BPC budget restitution before expanding return scope.
4. Add manufacturing labor/overhead, governed rework/quality and native monotonic
   same-date receipt sequencing; then net-shortage MRP with a complete supply cycle.
5. Add group reporting-currency translation and correction/reversal governance,
   then investment/ownership and profit-in-stock eliminations.
