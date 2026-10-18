# Final bounded baseline and recovery acceptance — 2026-10-08

The exact whole-suite runtime/test source is **832ceeee075330931a494215c68c350867e93600** on
`amr/baseline-refresh-20261008`. The full locked Windows/Python3.12.13
regression passes **4,429 tests, 490 explicit skips, zero failures**
and 27 warnings in 952.19 pytest seconds
(955.613 runner seconds). No new skip or deselection is added.
[Machine evidence](ACCEPTANCE_FINAL_2026-10-08.json) retains commands, duration,
source/diff identities, log hashes and every skip reason.

The later live-only fixture follow-up at **98e3b0a34ed3f7339392263acef6af61e9408ede** changes no runtime,
CI or web source and passes34 actual HTTP/metrics/industry/provenance cases.
Its separate [fixture evidence](HTTP_FIXTURE_CLEANUP_2026-10-08.json) records
the exact changed test hashes and retained diff. The earlier whole regression
is not relabeled as a full run of that later fixture commit.

Initial failing source636786e8 remains in [BASELINE_2026-10-08.json](BASELINE_2026-10-08.json).
The earlier b8f5a772 acceptance remains in [ACCEPTANCE_2026-10-08.md](ACCEPTANCE_2026-10-08.md).
The later runtime recovery repairs have fresh
[hosted-gate evidence and remaining gaps](HOSTED_GATES_REPAIR_2026-10-08.md).
This final result supersedes the whole-regression-pending status of that earlier
repair snapshot only; it does not accept the remaining hosted integration gates.

| Gate | Result | Runner wall seconds |
| --- | --- | ---: |
| Full Python regression | 4,429 passed / 490 explicit skips / zero failures | 955.613 |
| Ruff / Mypy / Bandit | Pass; 610 runtime sources | 15.731 |
| Recovery/runner/report/supply-chain/documentation focused | 126 passed / two live prerequisites | 11.540 |
| Live PostgreSQL17.10 operations/consolidation/Receivables/native invoice | 97 passed / zero skipped | 59.847 |
| Live PostgreSQL17.10 HTTP/metrics/industry/provenance cleanup | 34 passed / zero skipped | 37.852 |
| Writeback16.14/17.10 matrix | Both pass / actual0106 / equal financial-history digests | 28.070 |
| Three repeated single-host HA sentinel drills | All pass / owned cleanup | 474.306 |
| Gitleaks full history and current tree | Zero findings after exact synthetic-fixture review | 5.184 |
| wheel / sdist at tested runtime | Pass; final evidence packaging is recorded separately | 25.077 |
| CLI doctor / validate / demo | Pass; sample zero errors / ten deliberate warnings | 12.954 |
| Docker build / doctor | Pass; exact image digest in machine record | 302.697 |

Money and both Finance adapters preserve exact integer units and recorded
currency scale under caller Decimal precision and traps (ADR0832). The pinned
recovery query now executes via a private psql script with its quoted variable
binding (ADR0833). The current0106 encrypted native restore proves exact revision,
zero PUBLIC SECURITY DEFINER execution, wrong-source refusal before output,
target removal and container cleanup with a nonowner/no-BYPASSRLS application role.
No PostgreSQL or SQLite migration, public Money signature, CLI/API schema,
policy digest or automatic financial history repair changes.

The unchanged web source retains219 component passes,19 Chromium passes and
nine explicit configured HTTPS prerequisites. The lockfiles retain the recorded
128-package zero-finding Python audit and zero-finding npm audit after the single
source-map-js1.2.2 lock-entry correction. Reviewed synthetic Gitleaks fingerprints
do not disable any default rule or source/test/history coverage.

Hosted Ubuntu whole regressions at832ceeee independently pass4431 with488
explicit skips on each Python version:3.11 in879.37 seconds and3.12 in777.23
seconds. Platform-dependent prerequisites explain the difference from Windows.
The Linux PostgreSQL16.14 strict encrypted native test passes before its shard's
later scoped-export cleanup failure; whole native shard acceptance remains
separate from that executed component. The wheel is installed to a separate
target and doctor runs from that package, reusing the locked dependencies.

## Hosted CI and scope

[Draft PR123](https://github.com/amrzainmubarak/reconforge-erp/pull/123) is stacked
on unchanged sprint636786e8. The live hosted job snapshot is retained in the
machine evidence; successful individual gates do not imply whole CI acceptance.
Shared PostgreSQL downgrade fixtures encounter retained newer outbox guards;
identity/security assertions require current role/permission contract review;
three inherited Inventory receipt failures remain outside the paused feature
scope. AUD-20261008-007/-008 remain planned and -009 deferred. AMR-GFO-005 stays
in progress. Main staysb61ea56b and cancellation0107 stays outside this source.
The native scoped-export and industry metrics cleanup failures at832ceeee are
repaired and pass locally in the later34-case follow-up; fresh final-head hosted
CI is pending. No successful component turns the whole historical run green.

The three-run manual single-host sentinel drill observes synthetic RPO zero,
failover11.985–12.076 seconds and failback1.638–1.665 seconds. These observations
do not establish host-loss recovery, automatic failover or production RPO/RTO.
Default-branch Dependabot alerts, configured network/provider acceptance,
signed release/provenance, independent compliance and production acceptance
remain separate requirements. The wheel/sdist/ZIP are review artifacts only.

Rollback reverts the Money and bounded gate-repair commits with their tests,
reports and lock change. No migration rollback is required; reverting restores
the documented original rounding/advisory/recovery failures.
