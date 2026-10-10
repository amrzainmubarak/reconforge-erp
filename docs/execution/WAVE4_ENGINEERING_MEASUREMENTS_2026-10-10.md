# Wave4 engineering measurements — 2026-10-10

Financial byte/arithmetic verification passed. Performance comparison acceptance is **false**.
The six fresh populations below used identical benchmark/observer bytes and static configuration, but dynamic host power changed: 248 AC and 263 battery samples. These descriptive observations do not establish a controlled causal speedup.

| Run | Posting s | ops/s | p50 / p95 / p99 s | Client CPU s | DB CPU s | CPU s/success | Batch1000 s |
|---|---:|---:|---|---:|---:|---:|---:|
| 1-baseline | 1140.814 | 0.8766 | 4.525 / 4.854 / 5.321 | 1196.656 | 2920.017 | 4.1167 | 1.153795 |
| 1-candidate | 823.901 | 1.2137 | 3.262 / 3.516 / 3.661 | 1245.219 | 1774.253 | 3.0195 | 1.417025 |
| 2-candidate | 548.612 | 1.8228 | 2.076 / 3.091 / 3.362 | 785.266 | 1144.629 | 1.9299 | 0.626310 |
| 2-baseline | 746.237 | 1.3401 | 2.961 / 3.138 / 3.370 | 641.219 | 1882.998 | 2.5242 | 0.540545 |
| 3-baseline | 743.355 | 1.3453 | 2.958 / 3.087 / 3.208 | 634.672 | 1884.830 | 2.5195 | 0.567914 |
| 3-candidate | 507.865 | 1.9690 | 2.015 / 2.140 / 2.295 | 625.734 | 1132.981 | 1.7587 | 0.563998 |

The medians report throughput +36.02%, combined client/DB CPU per success -23.54%, client CPU +22.46%, batch-read elapsed +10.28%. Neither adverse outcome is accepted or hidden. Individual ratios and changing clocks/power prevent selecting these medians as a validated universal gain.

Each measured cycle performs prepare → independent review → separate posting through native current-authority repositories, with 390000-iteration authentication for each duty. Four workers; twenty genuine warmup effects outside the thousand measured effects; fresh PostgreSQL17.10 server/population per run; durability on; nonowner/NOBYPASSRLS. This is one synthetic USD cash/equity entity, not HTTP/mixed ERP throughput.
Independent SHA256/integer oracle: 493671004 minor units for1000,46669102 for100. Six runs retained6120 distinct native effects including warmup, zero financial failures and sampled deadlocks.

The serial20 profile reduces retained top-level SQL planning29.212→13.325s; candidate capture reaches200query rows, so these are truncated diagnostic aggregates. In the later parallel100 diagnosis, identity workerCPU rises79.421875→106.953125s, while businessCPU7.140625→7.234375s. Identity increase accounts for99.8866% of processCPU delta; exact KDF implementation/iterations remain unchanged. This locates cost; scheduler/thermal causation and phase-specific frequency remain unproved.
Memory peaks include startup/migrations/warmup; sparse RSS samples can miss spikes. Cgroup postingCPU boundaries include observerexec overhead; sample-window IO/network/WAL include other stages. track_io_timing is off in quiet runs, so zero timing counters are unavailable IO timing, not zero diskwork. No supplied monetary costmodel: cost remainsnull.

## Retained raw evidence

[Six original reports, manifest, oracles and source binding](wave4-evidence/posting-1k/) use trusted manifest SHA256 `c5dfa70b980a9532e14e7e93e65e24f6c9fbf0f9c56524d63985fbcbaed31acc`. Normal and optimized independent outputs: `df871dd80208db49e592ce586c1784a5cb669c2457ed6d76a070da4bdf30cd3c`.
[CPU/SQL profiles](wave4-evidence/profiling/) retain raw phases, cProfile, query capture and dynamic power observations. [The earlier regressed pair and interrupted attempt](wave4-evidence/unaccepted-first-pair/) remain unaccepted. [Published fixed business-source CI](wave4-evidence/ci-b6e9dcf6/) records all38successful jobs and eleven populated HTTPSrestores. The historical22-entry benchmark index remains unchanged.

## Reproduction

Baseline `b7df92711d52bde1adb735e3d1ab538eb2f4e5cc` is accepted129businesssource plus identical instrumentation. Candidate `07452da8742406d2223ce522c87aee0fcd223a90`; later delivery changes are documented and do not rewrite these measurements.

```text
python .github/scripts/benchmark_global_engineering_pair.py --baseline <baseline-checkout> --candidate <candidate-checkout> --count 1000 --pairs 3 --max-seconds 1800 --output <fresh-evidence-directory>
python -I .github/scripts/verify_wave4_posting_pair.py --manifest docs/execution/wave4-evidence/posting-1k/manifest.json --manifest-sha256 c5dfa70b980a9532e14e7e93e65e24f6c9fbf0f9c56524d63985fbcbaed31acc --report <fresh-proof.json>
```

The fresh10000-cycle capacity run completed successfully at16:33UTC. The independent SHA256/integer oracle is5028151631minor units; all10000measured effects and20disjoint warmups were retained, both100/10000read populations have three verified repetitions per read mode, and the owned lab was removed. [Original3.55MBreport and independent result](wave4-evidence/scale-10k/) are pinned by report SHA256 `c09be0d222823c915f93efdbd0824e33715024b2106064805d85dc4e8f405313`.

| 10K candidate capacity metric | Observed value |
|---|---:|
| Posting elapsed | 4376.855s |
| Successful native cycles/sec | 2.284745 |
| p50 / p95 / p99 | 1.678126 / 2.082625 / 2.582500s |
| Posting client / database CPU | 5378.296875 / 9874.770547s |
| Combined CPU per successful cycle | 1.525307s |
| Container / client lifetime memory peak | 427376640 / 126705664bytes |
| 10000-effect bounded-read median | 4.905057s |
| Financial errors / sampled deadlocks | 0 / 0 |

This is one candidate population with changing power during the run; there is no matched10Kbaseline or causal improvement claim. Sparse IO/network/WAL observations and memory scopes retain the limitations above. Three stable-AC pairs started afterward with the unchanged frozen child populations and Balanced scheme GUID `381b4222-f694-41f0-9685-ff5bb260df2e`; their before/after scheme readings and exact sampled AC/saver state are hash-bound separately. The active scheme does not measure Windows overlay power mode or continuous stability.100000/1000000remain unrun: linear extrapolation of this actual10Kposting alone is about12.2hours for100K, beyond the individual7200s resource budget; this extrapolation is not a measured scale result. No equivalent competitor benchmark or global ranking is claimed.


## Completed stable-AC comparison

All six fresh populations completed with financial and observed-environment verification passed. These are the entire BC, CB, BC repetitions, including adverse outcomes. The original mixed-power packet above remains historical and unaccepted.

| Run | Posting s | cycles/s | p50 s | p95 s | p99 s | Client CPU s | DB CPU s | CPU s/success | Batch1000 s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-baseline | 704.663929 | 1.419116 | 2.761310 | 3.307787 | 4.265476 | 713.187500 | 1729.263766 | 2.442451 | 0.494244 |
| 1-candidate | 473.354024 | 2.112584 | 1.763702 | 2.406500 | 2.640858 | 640.312500 | 1011.369457 | 1.651682 | 0.453179 |
| 2-candidate | 436.603822 | 2.290406 | 1.671297 | 2.114964 | 2.540505 | 531.187500 | 995.488110 | 1.526676 | 0.469902 |
| 2-baseline | 622.531817 | 1.606344 | 2.441582 | 2.753406 | 3.431160 | 516.593750 | 1578.474764 | 2.095069 | 0.470626 |
| 3-baseline | 615.556683 | 1.624546 | 2.434087 | 2.618511 | 2.858823 | 514.406250 | 1563.865217 | 2.078271 | 0.457262 |
| 3-candidate | 417.134435 | 2.397309 | 1.641767 | 1.848359 | 1.990338 | 512.828125 | 944.521768 | 1.457350 | 0.464334 |

| Metric | Baseline median | Candidate median | Change % |
|---|---:|---:|---:|
| posting_seconds | 622.531817 | 436.603822 | -29.8664% |
| throughput | 1.606344 | 2.290406 | +42.5851% |
| p50 | 2.441582 | 1.671297 | -31.5486% |
| p95 | 2.753406 | 2.114964 | -23.1873% |
| p99 | 3.431160 | 2.540505 | -25.9578% |
| client_cpu_seconds | 516.593750 | 531.187500 | +2.8250% |
| container_cpu_seconds | 1578.474764 | 995.488110 | -36.9335% |
| total_cpu_seconds_per_success | 2.095069 | 1.526676 | -27.1300% |
| bounded_batch_read_seconds | 0.470626 | 0.464334 | -1.3370% |

The independently recomputed medians show +42.5851% throughput, -27.1300% combined CPU per successful cycle, and -1.3370% bounded-read elapsed. Client posting CPU still rises +2.8250%; client lifetime peak median rises +0.2254% (129007616 to129298432bytes), while database lifetime peak median falls -32.1299% (318361600 to216072192bytes). Overall resource/performance acceptance remains **false**; no threshold was changed after observing the measurements. Phase-specific KDF CPU attribution and controlled sustained-run thermal/frequency/resource acceptance remain work in BACKLOG004. These figures support an observed scoped improvement, not universal or competitor superiority.

Each source has3000measured cycles and60warmups:6120distinct native effects, six distinct fresh PostgreSQL servers, zero financial errors and sampled deadlocks, sampled waiting-session maximum3. All371power samples are AC with saver off, with12matching before/after Balanced GUID readings. User confirmation covers fixed power mode; samples/endpoints do not prove continuous power/overlay/thermal equivalence. Sample-window IO/network/WAL include warmup/reads; monetary cost remainsnull. Full1000-line sales/procurement cycles, failover RPO/RTO and100K/1M remain unmeasured.

Portable original [stable packet](wave4-evidence/posting-1k-stable-ac/) keeps absolute original Windows references byte-for-byte; the offline verifier rebases only six validated identities to portable paths. Trusted pair SHA256 `cd8c404d2baf129001930ce220846b89e4e06dbf59c02bc342be1935c26c09b1`; trusted manifest SHA256 `1e67d483a994e68392fd7d5a35413e7c535d8d2b78a25d1ae975cf587b3f2a7c`. Outside-checkout normal/optimized environment proofs are byte-identical SHA256 `ac3abc9e6ebd8176fcd637f9343e2e050db2a83f45a9093eb3ad43e95d61523c`. Financial integer/SHA256 oracle is independent of application code; this is internal reproducible verification, not third-party attestation or a new inspection of the original databases.

Measured whole-source commits remain baseline b7df9271 and candidate07452da8. Later delivery changes include a Studio initialization-race repair and portable Windows-observer loading; the financial backend/migration code is unchanged after07452da8. The whole final delivery tree is not retrospectively presented as benchmarked.

```text
python .github/scripts/benchmark_stable_power_pair.py --baseline <clean-b7df-checkout> --candidate <clean-0745-checkout> --output <fresh-directory> --expected-scheme-guid 381b4222-f694-41f0-9685-ff5bb260df2e
python -I .github/scripts/verify_stable_power_environment.py --packet docs/execution/wave4-evidence/posting-1k-stable-ac --pair-sha256 cd8c404d2baf129001930ce220846b89e4e06dbf59c02bc342be1935c26c09b1 --manifest-sha256 1e67d483a994e68392fd7d5a35413e7c535d8d2b78a25d1ae975cf587b3f2a7c --expected-scheme-guid 381b4222-f694-41f0-9685-ff5bb260df2e --report <fresh-proof.json>
```

Use `-I -O` for the optimized-mode proof. Seventy-three targeted cases passed with zero failures/errors/skips (14environment,38posting,21controller); full hosted acceptance must run on the commit containing this packet.
