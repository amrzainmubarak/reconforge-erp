# Partition independent live gates and preserve a failing aggregate

Status: accepted for local workflow contracts; hosted execution remains pending.
Date: 2026-10-03

PR113 at8ba6772d exceeded the server-boundaries job's30-minute limit. GitHub's
check annotation confirms cancellation by that limit, not an assertion failure.
Earlier groups completed, while later groups have no accepted completed result.
The exact failed/cancelled heads remain in retained evidence.

The existing job ID now runs nine independent service-backed shards, each with
the original30-minute ceiling, max-parallel4 and fail-fast disabled. Existing
native tools, migration setup, PostgreSQL/Redis images, environment variables,
test filters and report uploads remain. Thirty-nine original verification
commands are preserved exactly once; one new command adds the two AR policy API
modules. Existing intentional test-module duplication is retained and inventoried.

An aggregate retains the public check name server-boundaries. It runs after the
matrix and succeeds only when its result is success. Failed, cancelled, skipped,
empty and unknown outcomes cannot become a successful required gate. An unknown
dispatch branch is an error. Reports are produced by their owning shard only.

Local acceptance:109 focused CI/consumer tests pass without skips; four new tests
pass again after strengthening the fallback assertion. Ruff/diff pass. Actual
Bash dispatch with captured commands verifies all nine branches and rejects an
unknown branch. Command multiset and independent source review show no lost
verification. See SERVER_BOUNDARY_SHARDING_2026-10-03.json. These are workflow
and dispatch tests, not a claim that all hosted database tests already passed.

Current-head migration proof separately moves from0098 to0099 and reruns actual
PostgreSQL16.14/17.10 native history/restore drills. Both schemas admit the new
revision while retaining old report validation. No historical migration/report
is rewritten. A reviewed empty-array SHA256 false positive receives two exact
Gitleaks fingerprints; scanner configuration and broad exclusions are unchanged.
POSTGRES_0099_GATE_REPAIR_2026-10-03.json retains the original full8054 failure,
the intermediate schema omission, native runs and repaired78-test gate.

Rollback: revert the workflow partition to the previous file if hosted evidence
shows an orchestration defect, preserving reports and accepting the old timeout
limitation explicitly. Do not delete commands, turn failures into warnings or
raise the timeout as a substitute for measured partitioning. If the preserved
parity command alone approaches the limit, partition its measured test inventory
under a separately reviewed compatibility contract.
