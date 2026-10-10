# Global operating platform: bounded engineering measurements

## Successor quiet retest and dimensional read optimization

The current22-entry index preserves all20 prior entries and adds raw806a05db
and70dffef7 paired reports, with1000 cycles/3333 read observations each. Both
complete without financial failure. Candidate observed posting change+6.78%
versus the fresh baseline and+4.30% versus historical accepted PR127.
The snapshot64.0519x read result is a distinct alternating same-fixture experiment.
See [source-bound acceptance](GLOBAL_INTEGRITY_ACCEPTANCE_2026-10-10.md) for the
raw metric table, configurations, sample limits and failures. The prior posting
regressions below remain historical measured outcomes; none is rewritten.
The fresh pair also retains adverse client CPU545.03125→743.703125s (+36.45%)
and bounded-batch read0.4677991→0.4806592s (+2.75%). Resource windows cover reads
and observer work as well as posting; the throughput gain does not establish
CPU efficiency or across-the-board reporting improvement.

Publication date: 2026-10-10. Initial runs occurred on 2026-10-09 UTC; the corrective-source run occurred on 2026-10-10 UTC. Native posting throughput regressed against accepted PR127 in both expansion observations. Financial correctness passed. Within-run bounded-batch reads exercise an existing pathway; the new measured optimization is commercial projection allocation lookup reuse.

## Corrective-source retest

[Full post-repair observations](benchmarks/enterprise-native-finance-post-repair-cfd30de7-2026-10-10.json)
retain source `cfd30de7a5ae1958b17e81f4988cbe9fa461457a`, migration0123,
unchanged whole-source SHA256 `4eb38a271b4b49b9d420c79b11513fb36b3d199697adfc31af26aa7fd9e05231`
and original report SHA256 `306ab7117fca913ab81a367eba551634ae99b40a5bb62f18342a95a8be6994a4`.
Same pinned PostgreSQL17.10, seed, hardware profile, four workers,1000 three-human
native cash/equity cycles and100/1000-effect reads each with three repetitions.
All1000 cycles complete, zero failures/nonadmissions, independent493671004minor
debit=credit=cash=equity. Source remains unchanged and owned container removed.

| Metric | Accepted PR12734b9 | Pre-repair6272889d | Correctivecfd30de7 |
| --- | ---: | ---: | ---: |
| Posting seconds | 670.269043 | 759.610646 | 873.143320 |
| Native cycles/s | 1.491938 | 1.316464 | 1.145287 |
| p50 seconds | 2.562645 | 3.115654 | 3.417656 |
| p95 seconds | 3.352172 | 3.296120 | 4.423447 |
| p99 seconds | 4.595277 | 3.581297 | 4.747318 |
|1000-effect per-effect read median seconds | 6.957988 | 7.669656 | 13.696350 |
|1000-effect batch read median seconds | 0.474097 | 0.569061 | 1.121742 |

Corrective posting throughput is23.23% below accepted PR127 and13.00% below the
pre-repair observation. The within-run existing batch path is12.2099x faster
than per-effect reads; both absolute read durations regress between sources.
This result rejects a broad performance-improvement claim. Namespace dispatch
fixes are required correctness/compatibility work; these measurements do not
establish them as a speed optimization or identify the regression's cause.
Docker Desktop restarted before this run; thirteen pre-existing containers were
preserved. Resource availability, cache/host contention and sampling differ:
one observation per source cannot isolate causality or statistical confidence.
One operator count-only query observed1000 BENCH effects late in the run; it
adds an observation query to cumulative database counters, not business throughput.

The new packet retains1000 cycle latencies,3333 timed read request observations
and93 ten-second resource samples. Sampled client RSS max124747776bytes;
database container memory max180.3MiB, aggregate CPU max295.0%, lock-wait sessions
max2. First-to-last counters record0 deadlocks/rollbacks/conflicts and19911960
WAL bytes; counters include reads and sampler work and omit earlier seeding.
These are samples, not peak-resource/lock-duration evidence. I/O timing remains
off; cost, RPO/RTO and competitor measurements remain unavailable in this profile.
Native1000 operations are the highest completed posting tier here; no10000,
100000 or million-posting claim follows. Instrumenting authentication, posting
SQL and wait spans on repeated equal workloads is the next performance priority.

The historical corrective publication contained19 entries and preserves every accepted old entry.
Earlier source-specific packets below remain unchanged. Later evidence-only
publication does not reattribute the benchmark to a different runtime source.

## Retained evidence and source binding

The [evidence index](benchmarks/INDEX.v1.json) preserves all 15 original accepted entries and seven later artifacts, including this successor pair. Its verifier checks paths, canonical-LF artifact hashes, profile identity and declared digest fields. It does not execute the workload or independently certify acceptance.

| Artifact | Measured source | Original report SHA-256 |
| --- | --- | --- |
| [Accepted PR127 native profile](benchmarks/enterprise-native-finance-pr127-34b9-2026-10-10.json) | `34b9e7a5b2a7c4d8ae49b641a36de030a878d507` | `b051654acdae6c9878ca355a26b681519e37cd3ec59994583f317e514c71079f` |
| [Current native profile](benchmarks/enterprise-native-finance-current-6272889d-2026-10-10.json) | `6272889d6ded2e20d4a52a79df234dd832ca6504` | `5ec2b6adfd87a207bd7b55f557f391897cbfe0799616b63e8548b442453cebaf` |
| [Both commercial projection observations](benchmarks/commercial-collection-projection-two-runs-2026-10-10.json), first run | `fdb0db48d2bc6271544dab3149a146f5699d5d64` | `a49d43553dfb7a6432350cadbf43a2bf784fb4b54bbe47408a16ecdd59a622ed` |
| Same artifact, second run | `1dff47125ef78724bd48fc352d210339925e6f55` | `42c2e8fadcd9bcd906e5011f985c24a58b9f677f85a3e55bc7f21a07b935f4bc` |

Every new wrapper retains the full parsed original report, including its available raw vectors, query plans, counters, command and source bindings. Serialization metadata preserves the original report's key order, UTF-8 encoding, indentation and line endings. Focused tests reconstruct the exact original bytes and check their retained SHA-256 independently of the index's canonical-LF hash. Original report locations are recorded for operator navigation; verification uses the checked-in content and does not depend on ignored output directories.

The accepted PR127 schema-v1 report retained percentiles and aggregate timings, but did not retain individual posting/read latency vectors or periodic resource samples. Those missing observations cannot be reconstructed from percentiles. The current schema-v2 report retains all 1,000 posting latencies, ordered effect IDs and completion indices, 3,333 timed read-request latencies across both counts and six samples per count, and 79 resource samples. No missing baseline measurements are invented.

The preexisting `enterprise-native-finance-1000-2026-10-09.json` remains unchanged. It measures the earlier `347d3714` source, whereas the comparison here uses the requested final accepted PR127 source `34b9e7a5`.

## Workload and environment

Both native runs use the same `native-three-human-cash-equity-v1` profile and `enterprise-native-v1` seed. Each executes 1,000 governed native prepare/review/post cycles with four workers, then reads 100 and 1,000 effects through two authenticated verification paths, three repetitions each. Both read paths warm their caches before measurements and alternate execution order. Each posting uses three distinct human identities and the normal native financial engine. Money is integer USD minor units; this is one entity and one currency.

Native repository latency includes synthetic identity authentication, transaction control, posting validation and source/evidence checks. This profile does not measure HTTP latency, order processing, financial statement generation, mixed ERP throughput, or 1,000-line order throughput. The 100-effect tier measures reads over the first 100 effects of the 1,000-posting history, rather than a separate 100-posting load run.

| Environment | Recorded value |
| --- | --- |
| Host | Windows 11 build 26200, AMD64 Family 25 Model 68 Stepping 1, 16 logical CPUs |
| Python | 3.12.13, MSC v.1944, AMD64 |
| Docker | 29.8.2, Linux x86_64, overlayfs |
| Docker kernel | `6.18.40.1-microsoft-standard-WSL2` |
| Docker available resources | 16 CPUs, 10,266,177,536 bytes RAM; no dedicated per-benchmark CPU/RAM cap recorded |
| PostgreSQL | 17.10 |
| Pinned image | `postgres:17.10-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193` |
| Migrations | Baseline `0119_pg_receipt_fifo_chronology`; current `0122_pg_fixed_assets` |
| Runtime role flags | Superuser false; BYPASSRLS false on both runs |
| Durability | `fsync=on`, `full_page_writes=on`, `synchronous_commit=on`, `wal_level=replica` |
| Other PostgreSQL settings | `max_connections=100`, `shared_buffers=16384` 8-KiB blocks, `work_mem=4096` KiB |
| I/O timing | Current explicitly records `track_io_timing=off`; baseline did not record this setting |
| Admission | 4 workers, counts 100/1,000, 3 repetitions, maximum 1,800 seconds |
| Final database size | Baseline 34,297,523 bytes; current 35,133,107 bytes |

The two runs report unchanged tracked source before/after execution and owned container removal. The current run records imported module paths in the isolated verification worktree. The benchmark report provides those bindings; publication on a later documentation commit does not relabel the measured source.

## Native posting: regression retained

| Metric | PR127 `34b9e7a5` | Current `6272889d` |
| --- | ---: | ---: |
| Completed native cycles | 1,000 | 1,000 |
| Posting errors | 0 | 0 |
| Posting elapsed seconds | 670.269043 | 759.610646 |
| Native postings/second | 1.491938 | 1.316464 |
| Cycle p50 seconds | 2.562645 | 3.115654 |
| Cycle p95 seconds | 3.352172 | 3.296120 |
| Cycle p99 seconds | 4.595277 | 3.581297 |
| Whole-driver wall seconds | 709.281 | 801.641 |

Observed posting throughput decreased **11.76%**, and posting elapsed time increased **13.33%**. The lower p95/p99 measurements do not cancel the throughput regression. This is a comparison of one run per source, with additional source-owner controls, newer migrations and richer measurement instrumentation on the current source. It identifies a regression for investigation; it does not establish its cause or statistical confidence.

The next measured work is profiling authentication, posting validation, owner admission and transaction waits separately on this exact profile. No optimization is accepted merely by attributing the cost to stronger controls, and no financial constraint is relaxed to improve throughput.

## Native verified reads: existing pathway measured within each run

| Count | Run | Per-effect median seconds | Bounded-batch median seconds | Within-run ratio | Effects/second at batch median |
| --- | --- | ---: | ---: | ---: | ---: |
| 100 | PR127 | 0.715664 | 0.058498 | 12.2340x | 1,709.454 |
| 100 | Current | 0.713685 | 0.067012 | 10.6501x | 1,492.270 |
| 1,000 | PR127 | 6.957988 | 0.474097 | 14.6763x | 2,109.273 |
| 1,000 | Current | 7.669656 | 0.569061 | 13.4777x | 1,757.279 |

The current 1,000-effect comparison observes **13.4777x** lower whole-profile duration through the existing bounded-batch pathway. This pathway was already present in PR127. Between runs, bounded-batch median duration increased **20.03%** and per-effect median duration increased **10.23%**; neither is presented as a new improvement.

The paths verify identical effect IDs and financial digests inside each run. At 1,000 effects, per-effect reads issue 3,000 client execute calls and batch reads issue 20. This counter is client calls, not PostgreSQL internal query count. Request percentile units differ: one effect versus up to 100 effects. The wrappers retain each repetition's p50/p95/p99 and current raw request latencies; comparing those percentiles as equivalent request units would be misleading.

The independent retained monetary oracle is **493,671,004 minor units** for the 1,000-effect history: debit = credit = cash increment = equity credit magnitude. The first 100 effects total **46,669,102 minor units**. Both modes and all three repetitions agree with each expected total and their run's effect digest. The publication tests use those fixed golden totals without invoking the benchmark's amount generator or verifier to derive their expectation. Native effect IDs and source evidence IDs differ between runs, so their financial history digests are intentionally not equated across runs.

## Commercial projection: measured allocation lookup optimization

Both observations operate on one real native invoice and one reviewed partial receipt: one order line, one tranche, one collection plan, invoice 45,000 and collection 10,000 minor units. Twenty-five alternating `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` executions per path retain execution/planning vectors and the first complete query plan. The synthetic projection digest and unchanged source are checked inside each observation.

The baseline repeated receipt-allocation aggregation three times while forming collected and outstanding amounts. The candidate computes that scoped allocation once through a lateral relation and reuses it. The retained first plans show **3 → 1 allocation scans**, with identical result projection. Both baseline and candidate SQL strings remain available for inspection and rerun.

| Observation | Baseline execution median ms | Candidate execution median ms | Duration reduction |
| --- | ---: | ---: | ---: |
| `fdb0db48` | 6.223 | 6.133 | 1.45% |
| `1dff4712` | 6.243 | 5.941 | 4.84% |

These are small local query-execution improvements with scheduling variation, not a claim about large-order throughput or posting speed. Projection hashes differ between observations because each uses distinct synthetic native history. Hash equality is required between pathways within an observation. The projection reports record PostgreSQL/Python/host identifiers, but do not record full resource sampling, the database configuration, all 25 full plans, or whole-source fingerprints; the missing fields remain limitations of these packets.

## Current resource observations and limits

The sampler retained **79** read-only samples at a nominal 10-second interval, from elapsed 0.0 to 780.484 seconds. Sampling completed without recorded errors or a live remaining thread. It covers the posting and read phases; every sample and its collection duration remains in the wrapper. Sampling can miss short spikes and is not a benchmark phase boundary.

| Observation | Value and interpretation |
| --- | --- |
| Maximum sampled client RSS | 125,726,720 bytes; observed working set, not benchmark peak |
| Maximum observed process lifetime peak RSS | 126,783,488 bytes; Windows lifetime counter begins before benchmark admission |
| Maximum sampled database-container memory | 215.2 MiB; rounded Docker display, not peak |
| Maximum sampled database-container CPU | 287.62%; Docker aggregate CPU percentage, may exceed 100% across CPUs |
| Maximum simultaneously sampled lock-wait sessions | 2; duration and wait-free operation not established |
| Maximum simultaneously sampled I/O-wait sessions | 1 |
| First-to-last WAL delta | 19,880,776 bytes, 113,367 records, 550 full-page images |
| First-to-last database commits | 12,661; includes posting, reads and sampler activity, not business transactions |
| First-to-last database rollbacks/deadlocks/conflicts | 0 / 0 / 0 within the sampled counter window |
| First-to-last temporary files/bytes | 0 / 0 within the sampled counter window |
| First-to-last blocks read/hit | 82 / 23,609,922; database cumulative counter deltas |
| Final Docker network totals | 108 MB / 277 MB; rounded cumulative container totals, not per-transaction cost |
| Final Docker block-I/O totals | 55.7 MB / 211 MB; rounded cumulative totals including fixture activity |

The initial sample already contains fixture work: one rollback and 20,314,736 WAL bytes. First-to-last deltas exclude that earlier work and can omit activity after the last sample. They are therefore not exact full-driver WAL or per-successful-business-transaction costs. Database size and counter scope remain distinct from throughput and peak-resource measurements.

`track_io_timing=off` means recorded zero block-read/write milliseconds **do not prove zero I/O latency**. No setting was enabled to improve the reported evidence. Python `tracemalloc` allocation peaks in read samples are a separate measurement from process RSS and container memory; those original values remain intact.

Cost per successful transaction remains unavailable without a supplied resource cost model. This suite measures no failover, regional recovery, RPO or RTO. Isolated populated backup/restore acceptance belongs to its separate operating gate. No equivalent SAP/Oracle/Dynamics/NetSuite/Odoo benchmark was run on matched resources, so no comparative performance ranking follows.

## Reproduction and publication checks

Use the exact measured source in a clean isolated checkout with the pinned environment. The native driver creates its own synthetic fixture and owned loopback PostgreSQL container; it does not connect to production.

```powershell
& F:/reconforge-erp/.venv-baseline-20261008/Scripts/python.exe .github/scripts/benchmark_enterprise_finance.py --counts 100 1000 --workers 4 --repetitions 3 --max-seconds 1800 --output output/reproduced-native-finance
```

Run that command once at `34b9e7a5` and once at `6272889d` with matched available resources; each source uses its own checked-in driver and schema. Record host contention and cache/resource configuration when repeating. The current report retains the actual launch command, runtime root and module origins. Individual failures and partial measurements remain failure evidence, never financial acceptance.

The commercial profile is a pytest target run through its owned fixture launcher:

```powershell
& F:/reconforge-erp/.venv-baseline-20261008/Scripts/python.exe .github/scripts/verify_commercial_collections.py .github/scripts/profile_commercial_projection.py
```

Use the exact source recorded in each packet. The launcher creates the pinned owned loopback container and nonowner role, supplies ephemeral fixture DSNs to the child environment, and removes the container afterward. The original packets intentionally omit credentials and do not pretend the fixture DSNs are portable.

The publication gate passed **23 targeted tests** across `test_benchmark_evidence_index.py` and `test_enterprise_financial_benchmark.py`, with no failures or skips. Ruff on the changed test file, verification of all **18** index entries, and `git diff --check` passed. Those checks establish retained artifact integrity, the fixed financial oracle and measurement completeness. Heavy runtime acceptance remains a separate gate on the integrated source.

## Next measurements

1. Profile the native posting regression, then rerun the same 1,000-effect profile with unchanged financial and isolation constraints. Separate authentication, owner admission, SQL execution and lock waits before choosing an optimization.
2. Extend the commercial projection profile to populated multi-line/multi-tranche histories while preserving exact projection equivalence; retain configuration and full source fingerprints as well as raw timings.
3. Measure the actual governed LC1 → FIFO sale → CA1 → FA1 business cycle independently of the cash/equity microprofile. Scale through 1,000 and 10,000 completed cycles only after bounded runtime/resource admission and an independent inventory/GL oracle.
4. Add phase-specific resource and wait-duration evidence, then resource-cost and failover models when their infrastructure is available. Do not extrapolate this run to 100,000 or 1,000,000 operations.
