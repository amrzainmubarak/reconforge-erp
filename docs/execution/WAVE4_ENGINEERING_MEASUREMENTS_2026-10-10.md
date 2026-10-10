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

Fresh10000-cycle capacity run is active, not accepted yet. A stable-AC three-pair retest follows it after the user confirmed fixed power.100000/1000000 are unrun; no equivalent competitor benchmark or global ranking is claimed.
