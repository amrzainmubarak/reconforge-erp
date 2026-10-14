# Required native sourcing partition recovery — 2026-10-14

This change separates the three complete native sourcing test files into required
CI owners. It changes no business runtime, migration, source effect, API,
financial arithmetic, permission, test filter, skip policy, or timeout.

The original M3 CI run `38508998306` on
`44e4a204a96f5fe117e9d2832a24226eabcf8a5d` ended with 58 successful jobs,
one cancelled sourcing shard and the failed aggregate. The cancelled job
`115673264550` completed container setup, locked dependency installation, normal
application-role creation and Alembic migration successfully. Its live native
step started at `2026-10-14T04:35:51Z`; GitHub recorded no completed live step.
The original check-run annotation states:

> The job has exceeded the maximum execution time of 30m0s

The native job-log endpoint returned HTTP 404, and the original complete run ZIP
contains no native sourcing log. These originals establish a native-step
cancellation after successful bootstrap. They do not identify a failing test,
query, lock, machine resource limit, or business-runtime root cause. The
aggregate correctly refused `SHARDS_RESULT=cancelled`; it was not a failure in
the new cash-flow or group-reporting contracts.

The contemporaneous M4 run `38509003717` on
`5a4c15ccddca836675c0a42478ba64dd1bd4e150` completed all 62 jobs successfully.
Its original sourcing command selected the same three files and recorded
34 collected, zero skipped, zero xfailed, zero xpassed and `stats_available=1`.
The native step ran from `04:37:44Z` to `04:43:19Z`, approximately 335 seconds.
The difference from the M3 cancellation remains unexplained; the original `-q`
log does not measure each file separately. This is evidence of the earlier M4
source only, not acceptance of the recovery source or a performance improvement.

| Complete existing file | Earlier required owner | Recovery required owner |
| --- | --- | --- |
| `tests/test_postgres_procurement_sourcing.py` | procurement-sourcing | procurement-sourcing |
| `tests/test_postgres_procurement_sourcing_api.py` | procurement-sourcing | procurement-sourcing-api |
| `tests/test_postgres_manufacturing_sourcing.py` | procurement-sourcing | manufacturing-sourcing |

Each file gets an independent provisioned PostgreSQL application-role fixture,
its entire test collection, and the mandatory native gate. The job limit remains
30 minutes; maximum parallelism remains four; sibling failures remain observable;
the aggregate still requires every shard to succeed. There is no `-k`, deselect,
retry-until-green, continue-on-error, or deadline increase. The inventory section
records only file ownership; service and historical parity counts do not change.

Targeted contracts prove exact file ownership and selection. The new frozen
source still requires complete CI, including all three required native shards.
Separating verification workloads is bounded risk reduction awaiting that
acceptance. It is not a claim to have diagnosed or accelerated the business
runtime, and it does not erase the negative M3 run.

Original custody was freshly downloaded from GitHub after local output folders
became unavailable. It does not recreate earlier missing local closures. All 71
M3/M4 artifact ZIPs matched both the API's byte count and SHA-256. The raw job logs
and artifact ZIPs are retained privately outside disposable worktrees; no secret
or raw financial row is reproduced in this note.

| Original | Bytes | SHA-256 |
| --- | ---: | --- |
| M3 complete run logs ZIP | 2099363 | `2ead479e5457ceb2d8484437b7e90212708fc3af675b2d1e1471960dc885ec92` |
| M3 failed aggregate log | 2403 | `152041971bb551c789cab569b370e6a0502bfe834d5e6b9dfd0ad0053246f834` |
| M4 complete run logs ZIP | 2293271 | `221f64ef818a7efc247cb24325ef4731a5ecf7fa44bbfdee3e2612fb809bbd77` |
| Exact original artifact custody packet | 18839 | `ca8fb7d0caa54d6cc47670ed73398d83030647f79cb44b9fbaccde6557355715` |

The historical M4 success remains immutable evidence. Any dependency follow-up
that incorporates this partition must be measured and accepted on its own head.
Benchmarks remain deferred at the user's direction; there is no new throughput,
CPU, memory, cost-per-operation, country-compliance, or production-readiness
claim.

Targeted pre-integration verification on this recovery checkout: the complete CI
boundary and selection contract files recorded 10 passed, zero failures, zero
errors and zero skipped in 45.861 seconds. Ruff passed for both changed Python
contracts and `git diff --check` passed. The original JUnit XML is 1735 bytes,
SHA-256 `6ab1abe711540e39378fc0b7c82378453b2f0283189a3bb0619d07c34941bcf6`.
Collection checks do not substitute for executing the new native shards.
