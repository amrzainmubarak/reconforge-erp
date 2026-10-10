# Governed operational integrity: source-bound local acceptance

Publication snapshot, 2026-10-10. The final successor Draft PR's required checks
are the authoritative hosted status at its actual publication head. This local
packet precedes those checks and never infers acceptance from code existence.
PR12734b9 remains the accepted historical base; existing PR128699 is an
implementation dependency with retained failed gates, above PR126/125/124.

Three separately owned worktrees deliver existing-owner extensions:

Reconstruct the indexed raw bytes, independently recalculate seeded integer
totals and raw percentiles, and disclose adverse observations without application
imports or a database:

```text
python .github/scripts/verify_native_posting_pair.py --root . --report output/fresh-pair-proof.json
```

Inspect fresh built wheel/source artifacts with
`.github/scripts/verify_global_integrity_archive.py`; its safe extraction requires
Python3.11.4+ and also runs the standalone financial oracle from extracted source.

| Cycle | Complete tested behavior | Boundaries |
| --- | --- | --- |
| CA1 collections | Independent cancel of unposted claims releases invoice residual/plan receipt-name capacity; preparation/review/validated GL and original ACKs survive; partial collections continue to original AR/cash/GL. | Positive zero-tax functional currency;200 retained plans/invoice; no posted cancellation, customer credit/refund or external transfer. |
| LC1 receiving | Cancel unreceived charged claims; retain both-unit/two-warehouse exact allocations and drafts; replacement posts FIFO/GL/clearing/cash, then partial AP settlement. | Prepaid freight/duty,128 selected lines and200 bundles; no later actual-cost rewrite, supplier return or freight AP accrual. |
| FA1 evidence | Authorized source/plan/native-effect proof, three canonical seals, exact integer verification/download and original-cost/history-turnover ABAC. Supported reads/writes acquire asset before plan. | Cash-funded functional-currency cumulative straight-line; no FX/tax/impairment or universal arbitrary-SQL deadlock guarantee. |

## Financial and runtime evidence

At clean4bb4d1f9, complete owner gates execute19 commercial+49 supply+23 finance
cases, zero errors/failures/skips. At clean70dffef7, the19-case complete asset/
evidence/mixed-cycle gate also passes, including forced pg_blocking_pids overlap.
These execution counts overlap; they are not110 unique cases. The final asset
change is12 production lines plus its65-line regression, independently reviewed.
Studio typecheck/build and360 component tests in53 files pass at4bb; web source
is identical at70d. Ruff/Mypy/Bandit pass on70d. Original raw reports, exact JUnit
and source fingerprints are preserved in [the acceptance packet](GLOBAL_INTEGRITY_ACCEPTANCE_2026-10-10.json).

Actual HTTPS browser/restore succeeds for collections403.469s and landed
receiving238.985s at4bb, and fixed assets99.406s at70d. Each has one expected
browser scenario, zero skip/unexpected/flaky, a restricted nonowner/non-BYPASSRLS
role, unchanged source/built web and removed owned processes/container.
Each populated restore retains239 table fingerprints and238 function identities
plus schema/constraints/indexes/ACL/RLS/audit/evidence. The authenticated probe
updates identity_users; both identity fingerprints remain, every other238 table
and every captured object remains equal. Each rejects three direct SQL tamper attempts.

The independent funded normal and cancel/replacement oracles both yield18 posted
effects,184156 minor debit=credit, cash45898 and inventory11648. October assets
66147=capital50000+result16147; January57546=50000+7546. Rational allocation,
original FIFO consumption and cumulative depreciation/disposal equations are
computed outside the implementation, then compared with the immutable effect fold.
The separate asset wire proves cost10101,depreciation3033+6067,carrying1001,
proceeds1500,gain499 and zero final carrying amount.

Six unsuccessful attempts remain byte-reconstructible: early stale migration
diagnostics after a passing collections browser, incomplete replacement fields,
mobile proof button interception, asset/plan lock inversion,1800-second grouped
native budget exhaustion and900-second general Python budget exhaustion.
Timeouts contain no accepted case counts. Owner splitting executes the complete
selected files; no skip was added. Full Python3.11/3.12 and all configured native/
browser/security/package gates belong to the successor's exact hosted head.

## Same-workload measurements

Both fresh sequential sources perform1000 reviewed native USD cash/equity cycles
with four workers and three current independent humans, plus100/1000-effect reads
with three alternating repetitions. Same seed,pinned PostgreSQL17.10,host and
fsync/full_page_writes/synchronous_commit=on. All2000 effects complete without
failure/nonadmission; each independently proves493671004 minor debit=credit=cash=equity.
Each packet retains1000 raw cycle latencies,3333 read requests in12 samples,
resource vectors, versions, fingerprints and cleanup. Repetitions apply to reads,
not three independent posting populations. Fresh database effect IDs differ.

| Metric | Baseline806a05db | Candidate70dffef7 |
| --- | ---: | ---: |
| Posting seconds | 686.260674 | 642.665328 |
| Native cycles/s | 1.457172 | 1.556020 |
| p50 seconds | 2.700888 | 2.536519 |
| p95 seconds | 3.070491 | 2.982193 |
| p99 seconds | 3.492707 | 3.189220 |

Observed candidate posting change is+6.78% versus the fresh baseline,
and+4.30% versus historical PR127. One ordered run per source cannot
establish statistical significance or isolate every environmental/schema change.
The separately controlled warmed1000-line snapshot experiment alternates both
readers on one authenticated fixture: median10.7045965→0.1671239s,64.0519x,
1002→2 execute calls, identical500 minor debit/credit and668 dimension links.
Its result concerns one journal read, not posting or1000-line order settlement.

Sampling captures CPU/RAM/I/O/network/WAL/waits every10s; it does not measure
posting-only resource peaks or lock duration. Cost is null without a cost model.
The measured resource tradeoff is adverse for client CPU: sample-window process
CPU545.03125→743.703125s (+36.45%) and sampled client RSS121458688→123469824bytes
(+1.66%). Sampled database RAM204157747→196817715bytes (-3.60%); peak database
CPU286.28→282.12%. Windows differ72/67 observations and710.5/660.516s, spanning
posting, reads and observer work. These observations do not establish CPU or
overall resource efficiency. Both sampled deadlock and rollback counters stay0;
sampled lock-wait session maxima2→1 and WAL deltas20017436→19932614bytes.
Existing1000-effect bounded-batch read medians0.4677991→0.4806592s regress2.75%,
while per-effect medians7.5211534→6.9402772s improve7.72%. The existing within-run
batch advantage is separate from the new dimensional snapshot read optimization.
This slice establishes no HTTP TPS,mixed million-operation capacity,HA/RPO/RTO,
statutory statement,country compliance or equivalent competitor benchmark.

## Reproduction, compatibility and continuation

Native acceptance: `python .github/scripts/verify_commercial_collections.py`
followed by the complete owner file arguments retained in the packet. Real wire:
`python .github/scripts/verify_erp_expansion_browser.py --scenario collections`
and `landed-cost`/`fixed-assets`, each with `--verify-native-restore` and fresh output.
Matched load: `python .github/scripts/benchmark_enterprise_finance.py --counts 100 1000 --workers 4 --repetitions 3 --seed enterprise-native-v1 --max-seconds 1800 --output <fresh-directory>`.
Verify published raw content with `python .github/scripts/verify_benchmark_index.py --root .`
and `pytest tests/test_benchmark_evidence_index.py`. Inspect built artifacts with
`.github/scripts/verify_global_integrity_archive.py` and explicit root/sdist/wheel/report.

Additive0124/0125, the central125-revision registry and guarded populated
downgrades preserve source history. A rollback stops writes and restores a
verified compatible pre-upgrade backup into an isolated database; it cannot
delete cancellation/native history. MIT and dependency locks are unchanged.

Operator contracts: [collections](../operator/commercial-collections.md),
[landed receiving](../operator/landed-cost.md),[assets/evidence](../operator/fixed-assets.md).
[Coverage](GLOBAL_CAPABILITY_COVERAGE_WAVE3_2026-10-10.md) and the
[dependency-ordered next phase](GLOBAL_NEXT_PHASE_2026-10-10.md) retain actual
ceilings and missing returns,procurement sourcing,operational FX/tax/intercompany,
manufacturing and governed intelligence. No new ledger/currency/authorization engine.
