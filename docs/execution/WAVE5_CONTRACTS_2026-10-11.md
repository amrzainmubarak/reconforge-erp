# Wave5 source and integration contracts

Checkpoint updated 2026-10-12. Evidence below retains its original source identity;
this document does not replace pending final-head gates with prior success.

Start: accepted Draft PR130 at `6362724f2337a79c3d7569574f7bf9591a018524`, above PR129 through PR124. Local and remote main remain `b61ea56bb9c135fda12546e173795af3c243e4fb`. Primary checkout remains on `69951414` with its two original uncommitted schema edits protected by SHA256.

Baseline: live authenticated PR130, main-ref and original successful CI run38081451376 responses retained separately under output/wave5-baseline-6362724f. Individual bounded API refresh attempts timed out; successfully retrieved responses were individually inspected. Exact-source hosted 38-job acceptance is reused as the full baseline, not presented as a new regression run. Fresh Python3.12.13 Ruff passed; eight relevant pure/domain suites passed61 cases with zero skips in26.53s. One inherited Starlette/httpx deprecation warning remains. Agent operations also passed21 sourcing-adjacent cases in1.94s. This is no performance result.

## Ownership

| Owner | Independent worktree | Owned slice | Shared dependencies |
|---|---|---|---|
| Manufacturing | reconforge-manufacturing-wave5 | New manufacturing_execution domain/application/adapter/schema/module/UI/tests/oracle | Migration133, native movement relevance marker, shared reservation/FIFO protection and exact private posting admission |
| Corporate finance | reconforge-finance-wave5 | New intercompany_operations source/paired plans/settlement/group elimination/report/UI/tests/oracle | Migration134, all-entity current authority, exact private native posting admission and protected source dispatch |
| Operations | reconforge-operations-wave5 | New procurement_sourcing PR/RFQ/quotes/reviewed award into existing BPC1; source-linked manufacturing requirements | Migration135, budget and original-source return/capacity contracts when proven |
| Root | reconforge-integration-wave5 | Shared architecture, permissions, API/nav, native source hooks, Alembic, CI/restore/package integration, profiling and benchmark evidence | All owner artifacts; reviews rotate manufacturing→finance→operations→manufacturing |

No owner edits the primary checkout or another worktree. All new authors and committers are Amr. Shared-file changes require coordination; no full regressions after small edits.

## Financial contracts

ME1 uses original FIFO components and native issue movements, then native WIP journals and existing IRP1 finished-goods receipts. Issued cost equals remaining WIP plus finished-goods cost plus scrap expense. BOM revisions and original base-unit quantity precision are retained; cross-UOM BOM conversion remains excluded. Partial cumulative allocations conserve the final residual. Manufacturing reservations share stock lock keys with sales; native relevance guards must exit before protected-table access for unrelated ordinary roles. No independent inventory/GL engine or MRP completion assertion.

The bounded manufacturing contract allows at most 100 components and 200 retained
output attempts, whole material issue and one finished item in the original
functional currency. Lot/serial handling, labor, overhead, routing, rework, normal
yield, cross-UOM conversion and full MRP are not delivered by this slice. Same-date
receipt identity search is capped at 4,096 candidates, with atomic refusal when
exhausted; that ceiling is not a high-volume throughput acceptance.

IC1 uses two explicitly authorized trading entities and an explicit existing group-adjustment scope, all on an identical retained functional/reporting currency policy. Recognition and settlement post both parties atomically in Finance Core. Reviewed elimination journals post to the explicit group-adjustment scope, preserving original trading books. Consolidated management reports reuse reviewed mappings and native effect drill-down from all three scopes. No automatic FX/tax/legal-company/statutory inference. A request bound to one entity never clears its established scope to reach another.

IC1 covers native service charges and at most 32 posted installments before final
elimination. No group currency translation, ownership/NCI calculation, investment
or profit-in-stock elimination, external bank transfer or source inverse is implied.

Sourcing preserves approved requisitions, frozen supplier quotes, deterministic selection and three-person award into existing BPC1 multiline PO/budget/AP. Source-linked manufacturing requirements validate canonical scope, item/UOM/quantity precision, retained digest and current authority. Demand provenance alone is not MRP. Supplier-return budget reinstatement needs an original-owned reversed-consumption event and net receiving capacity closure; the accepted exclusion remains until this complete contract is implemented and verified.

SRC5 permits at most 128 original demand lines and 32 complete immutable supplier
offers, in one appropriation/period and original functional currency with zero tax.
Split awards, negotiated amendments, weighted ranking and multi-level approval
policies remain outside this contract. Partial foreign/tax-aware customer or supplier
returns are not established by Wave5. A 1,000-line GL snapshot is not evidence for
1,000-line commercial orders or a larger manufacturing/sourcing limit.

All slices preserve exact arithmetic, double entry, ACID, FORCE RLS, current grants after locks, immutable source/audit/outbox, versioned idempotency and public source-inverse refusal. Direct SQL, concurrent conflicting commands, permission withdrawal, lost responses, failure rollback and populated restore are mandatory acceptance gates.

Migration136 adds restrictive FORCE RLS hierarchy checks to nine native inventory
transaction relations. Helpers are STABLE SECURITY INVOKER, retain caller ACLs,
never reset scope, and follow an acyclic child-to-original-parent graph. Scoped
movement lines require exact item/UOM/location/optional-lot custody. Existing
unbound tenant and metadata contracts remain intact; malformed legacy hierarchy
rows become invisible under explicit business scope without being rewritten.

## Executed source-bound financial evidence

The three actual HTTPS/populated restore reports at
`output/wave5-final-wire-8513a9e2/{manufacturing-execution,intercompany-operations,procurement-sourcing}/report.json`
passed on `8513a9e2fd1a061c02fb31d5444304809c8af92e`, source SHA256
`f95d7114d6644bdf5c10a05acede40e016bff0079924b103a384cba23937d204`,
PostgreSQL17.11/head`0136_pg_inventory_scope`, with ordinary nonowner/non-bypass
roles. Each restored a populated 270-table native database, retaining respectively
51/42/78 nonempty tables. These local raw artifacts are not a new HEAD run or external attestation.

| Cycle | Independent exact minor-unit equation | Original raw report SHA256 |
|---|---|---|
| ME1 | 2,900 materials = 2,610 FG + 290 abnormal scrap + 0 WIP; 9 good/1 scrap quantity; six effects; debit=credit turnover 21,133 | `d344a4db07e6e322396834f37bcb531966992a2fae6f8c9571ad905f2dfda64e` |
| IC1 | 10,001 original and 3,000 cash per party; 7,001 residual; 17,002 elimination; five effects; group income/expense/net cash and balance-sheet net positions zero | `c9418e110bb83bced524b587fd366d9ea43ba8fe544fb38de4f0a698b9ad4305` |
| SRC5 | 17,000 award/reserve = 7,400 consumed + 9,600 released; source reserve0; paid7,400; budget available12,600; five effects; debit=credit turnover22,200 | `797e8c5e087feb48440cdeb4489015a6f5508dd596026e4c8de68ffc53e3ce01` |

The separate stdlib ME/IC review first checked separately retained raw report SHA
and duplicate JSON members, then bound extraction JSON pointers and proof/output
hashes. Both `-I` and `-I -O` outputs were byte-identical. Original/restored ME
proofs were identical; IC original downloaded proof membership matched complete
restored-effect equality and native snapshot, with no second restored HTTP export.
Binding report SHA256 is
`c75cb557b5795a4e0af2aacc3285bb6e18aed8ffb24e841e70637cc05bebd2c1`.
SRC's separately invoked stdlib oracle retained identical input SHA before/after restore.

The independently inspected e8e native packet is
`output/global-operating-platform-20261009/commercial/native-1791771040926527000/native-gate.json`:
source `e8e2de24bf6311d67b46a9bfd3b025c1792c3474`, unchanged clean-source SHA256
`676611870ab9695b0226f28553ed15b0ce4343266964f44aeecf96c880156cd6`,
**73 tests/0 failures/0 errors/0 skips**, 882.8294731 seconds, PostgreSQL17.11.
Its JSON SHA is `75af21b3f7cfbb08481b75588fccc3dea6510045a43e46a82253504af99eb1f3`;
log SHA is `dac187db865e3c085e8259cf0196cf7ea66ab1842a5760888fc61f5d952a6f6b`;
JUnit SHA is `8808c664976ecabcde466d0c2147cb7b793c895ad292fb4263947dd0bb95ba82`.
JUnit confirms migration2, inventory scope7, ME15, IC8+API3, SRC20+API8, posting
snapshot/profile8 and two original finance scope races. This is native functional,
atomicity, isolation and concurrency evidence; its elapsed time is not benchmark throughput.

Before the later FX UI repair, `git diff8513a9e2...e8e2de24...` was empty for
`reconforge`, `apps/web/src` and `alembic`. This records inspected application
equivalence; it does not rebind the raw reports to e8e or any later HEAD.

FX proof lifecycle repair `34c92761dd7f55044bf14d9387df602e07b4b24b` fixes a
reproduced same-plan passive-effect epoch race. Exact committed subject identity
is synchronized before visible actions; current context, original epoch and
same subject remain required to publish a result or error. Nine actual-WebCrypto
React cases, TypeScript and reciprocal review passed. Current hosted and affected
FX HTTPS acceptance are pending; no earlier whole-web packet covers this new code.
Root's integrated `b6fcf71d` checkpoint reports all68 React files/452 tests with
zero skips and TypeScript/build success. Those later UI checks preserve their
own source identity; affected FX HTTPS/restore is still running, and complete
current hosted CI acceptance has not been declared here.

## Measurement admission

The root's first opt-in CPU/SQL/memory discovery run is on immutable accepted636. It is profiling evidence, not a quiet speed comparison. Final baseline/candidate measurements use equal workloads, fresh populations, at least three alternating trials where resources permit, warmup, raw power/frequency/resources and independent financial oracles. New mixed API/manufacturing/intercompany runs retain their own scope. Runtime changes after measurement require final-head retest. No old Wave4 percentage becomes a Wave5 result. 100K/1M and monetary cost remain unproven until actually admitted and measured.

The attempted six-run pair was interrupted after the user confirmed heavy external
load. No current Wave5 speed/resource improvement is admitted from that attempt.
An isolated fresh retest is required, with successful genuine financial effects
counted; API seeding/export/oracle windows must remain explicit.

Official competitor references were refreshed 2026-10-12 in the
[capability matrix](GLOBAL_CAPABILITY_COVERAGE_WAVE5_2026-10-11.md).
[SAP's archive](https://www.sap.com/about/benchmark/appbm/archive.html) identifies
SD retirement in December2025; historical SAPS and current
[Q2C/aSAPS](https://www.sap.com/about/benchmark/appbm/q2c.html) measure commercial
and analytical work distinct from our authenticated three-human GL cycle.
[Dynamics batch guidance](https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/sysadmin/priority-based-batch-scheduling)
is scheduler/concurrency/retry advice, not matched financial throughput evidence.
No competitor speed ratio or global superiority claim follows from these sources.
