# Source-bound baseline refresh — 2026-10-08

The source checkpoint is `636786e8eeda82a8a74291c572deb8dd3bc3fe1c`
on `amr/global-platform-sprint`. The audit began with a clean checkout and runs
on `amr/baseline-refresh-20261008`; local and observed remote `main` remain
`b61ea56bb9c135fda12546e173795af3c243e4fb`. Inventory receipt work stays paused;
the cancellation-projection worktree is not included in this source.

[Machine-readable baseline](BASELINE_2026-10-08.json) retains exact commands,
exit codes, wall-clock durations, environment, lock identities where captured,
and SHA-256 references to raw logs under `output/baseline-2026-10-08/`.

## Baseline results before any repair

- Fresh locked all-extra CPython 3.12.13 environment; Windows 11, Node 26.3.0,
  npm 11.16.0 and Docker Engine 29.8.2. Host timings include concurrent audit
  work and are not throughput or capacity benchmarks.
- Full Python regression: **4,394 passed, 490 skipped, 2 failed, 25 warnings**
  in **1,575.27 seconds**. Both failures come from a parity-inventory `test`
  value containing two paths joined with a semicolon. CI passes that entire
  value as one filename, so its advertised general PostgreSQL gate cannot
  collect. The inventory file-existence contract also rejects it.
- Ruff, Mypy (610 runtime files), Bandit, installed Python dependency audit,
  hash-locked Python 3.12 audit (128 packages, no active exception), lock/policy
  checks, wheel/sdist build, CLI Doctor/validation/demo, and Docker build/Doctor
  pass. Sample validation retains ten intentional warnings and zero errors.
- Web typecheck, **219 tests in 26 files**, and production build pass.
  Chromium reports **18 passed, 9 skipped, 1 failed**: the screenshot journey
  expects the former synthetic exception queue after the route became
  authenticated exception review. No product fallback is warranted.
- npm audit reports one High finding in the development/build dependency
  `source-map-js` 1.2.1. Its upstream correction is 1.2.2; existing parent
  ranges accept it. See the [upstream correction](https://github.com/7rulnik/source-map-js/commit/cf7658058ceeaa8619d5ae0ec90be6905209d016)
  and [reviewed advisory](https://github.com/advisories/GHSA-68fv-2mgg-jv7q).
- A dedicated, digest-bound PostgreSQL 17.10 container upgrades from empty to
  `0106_pg_ap_link_reversal`. The role is neither SUPERUSER nor BYPASSRLS.
  Focused acceptance reports **20 passed, 2 failed, zero skipped**: Finance
  fixture grants omit the retained currency-policy binding/snapshot tables.
  The container was removed. This is separate from the 490 capability skips.

The scratch harness initially used an unsupported `python -m reconforge`
invocation and one incorrect test node ID. Those attempts are retained as
**harness invocation errors**; the corrected commands above were executed.
They are not attributed to product behavior.

## Five highest-priority findings in this checkout

| Priority | Finding and actual code/evidence | Required bounded response |
| --- | --- | --- |
| P0 correctness | `Money.to_minor_units`, `Money.from_minor_units` and Finance adapter text conversion inherit caller Decimal precision. At precision 3, 1234567.89 USD becomes 123000000 minor units instead of 123456789. The proposed regression fails 17/24 cases before repair. | Exact context-independent conversion, integer-oracle/property tests, retained policy/serialization compatibility, SQLite lifecycle and restricted-role PostgreSQL evidence. |
| P0 verification | The AP allocation/reversal parity row uses a semicolon-delimited filename. Both full-suite failures reproduce loss of CI collection. | Keep one primary path, declare additional paths as a typed list, and prove every advertised module and the reversal contract actually collect. |
| P0 supply chain | npm audit fails on the installed source-map-js 1.2.1 dependency. | Target only the compatible 1.2.2 lock entry; retain the original finding and rerun clean installation, audit and web gates. |
| P0 runtime evidence | Two live Finance tests fail before financial behavior because their nonowner fixture role lacks policy-store grants. | Add only SELECT/UPDATE on bindings for FOR SHARE and SELECT/INSERT on snapshots, retain the restricted role, and rerun on a fresh migrated database. |
| P1 evidence drift | Several baseline summaries still call the October 3 snapshot current, and the screenshot journey still assumes a synthetic queue. | Date historical records, publish this exact-source refresh, test the authentication boundary, and keep configured HTTPS/native restore prerequisites explicit. |

## Inspection coverage and interpretation

The tracked source inventory contains **610 runtime Python files, 558 Python
test modules, 106 PostgreSQL revisions, 55 SQLite migrations, 121 JSON schemas,
829 ADRs, eight CI workflows and 24 control packs**. Representative financial,
policy, authorization, audit, evidence, workflow, ingestion, migration, packaging,
web and CI boundaries were read; the full suite exercises the available local
contracts. This is not a claim of manual review of every source line or of live
execution of all PostgreSQL boundaries.

Security references verified from official sources on this date remain
[ASVS 5.0.0 stable](https://owasp.org/projects/asvs),
[SSDF 1.1 Final / 1.2 Draft](https://csrc.nist.gov/projects/ssdf/publications),
and [SLSA 1.2 Approved](https://slsa.dev/spec/v1.2/).
These are mapping references, not certification or independently assessed
compliance. Native PostgreSQL recovery, externally configured HTTPS journeys,
cross-host recovery, provider interoperability, signed release/provenance,
capacity and production acceptance remain separate gates.

One initial PostgreSQL focused log was overwritten by a scratch rerun before
archival was enabled. Its command/result/digest remain recorded with
`log_retained: false`; it is not presented as a retained raw artifact. Later
failed reproductions and passing PostgreSQL acceptance have separate logs.

## Post-repair acceptance

Latest bounded repair acceptance on clean `b8f5a772`: **4,422 Python passes, 490 explicit skips, zero failures**; **22 live PostgreSQL passes**, **219 web component passes**, **19 browser passes/nine prerequisites**, and zero-known-finding Python/npm audits. Static/build/CLI/Docker gates pass. [Acceptance and limits](ACCEPTANCE_2026-10-08.md) · [Command/source/hash evidence](ACCEPTANCE_2026-10-08.json).


## Final October8 bounded acceptance

Clean832ceeee full regression: 4429pass/490skip/0fail. [Final source-bound runtime/recovery/CI evidence and limits](ACCEPTANCE_FINAL_2026-10-08.md). This supersedes later-runtime whole-regression-pending notes only; full hosted CI and AMR-GFO-005 remain unaccepted.
