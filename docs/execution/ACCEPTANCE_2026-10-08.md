# Bounded baseline repair acceptance — 2026-10-08

The initial failing audit is retained in [BASELINE_2026-10-08.json](BASELINE_2026-10-08.json).
Acceptance records exact commands, source/diff identities, wall-clock durations,
SHA-256 log references, skip reasons and declared limits in
[ACCEPTANCE_2026-10-08.json](ACCEPTANCE_2026-10-08.json).
The full regression runs on clean **b8f5a772**, with locked CPython 3.12.13 on
Windows 11; Node 26.3.0/npm 11.16.0 and Docker 29.8.2 provide the other gates.
Timings include concurrent local work and do not establish capacity.

| Gate | Result | Runner wall seconds |
| --- | --- | ---: |
| Python full regression | 4,422 passed / 490 skipped / zero failures | 1017.062 |
| Money / Finance / CI focused | 134 passed / two live prerequisites | 41.077 |
| Python 3.11 Money / currency / input | 61 passed; focused scope only | 64.897 |
| PostgreSQL 17.10 selected acceptance | 22 passed / zero skipped; migrated to 0106 | 9.400 |
| Ruff / Mypy / Bandit | Pass; Mypy checks 610 source files | 23.086 |
| Python lock / installed / hash-locked audit | Pass; canonical audit 128 packages / zero findings | 94.992 |
| npm clean install / audit | Pass; zero known findings | 13.513 |
| Web typecheck / component tests / build | Pass; 219 component tests in 26 files | 13.689 |
| Chromium E2E | 19 passed / nine explicit prerequisites | 48.052 |
| wheel / sdist build at b8f5a772 | Pass; runtime matches source and slice evidence is included | 39.679 |
| CLI doctor / validate / demo | Pass; validate zero errors / ten deliberate sample warnings | 15.835 |
| Docker build / doctor | Pass; image digest retained | 318.599 |

Pytest itself reports 1013.92 seconds and 24 warnings;
runner duration includes process startup and result writing. The 26 new regression
cases and the two repaired inventory failures explain the change from 4,394 to
4,422 passes. Capability skips remain explicit in the machine record.

## What this iteration establishes

- Money preserves the exact integer coefficient and recorded 0–8 currency scale
  across low Decimal precision, alternative rounding and rounding traps. The
  independent integer-text/property oracle, persisted SQLite review/reconnect
  and live restricted-role KWD Finance lifecycle pass.
- The actual CI producer collects the primary and additional AP parity modules,
  including reversal, instead of treating semicolon-separated paths as one file.
- Finance test roles have SELECT/UPDATE on policy bindings for FOR SHARE and
  SELECT/INSERT on snapshots; they remain nonowner, NOSUPERUSER and NOBYPASSRLS.
  The fresh digest-pinned PostgreSQL container was removed after acceptance.
- The compatible source-map-js 1.2.2 lock entry resolves the recorded
  [upstream advisory](https://github.com/advisories/GHSA-68fv-2mgg-jv7q).
  The screenshot journey follows authenticated Exception review without
  restoring synthetic queue data.
- Public Money signatures, CLI/API schemas, retained policy digests, SQLite55
  and PostgreSQL0106 remain unchanged. Boolean minor units now fail explicitly.

## Boundaries and next gate

AUD-20261008-001 through -005 are complete for this bounded repair.
AMR-GFO-005 remains in progress. Main stays b61ea56b, Inventory receipt work
stays paused, and cancellation revision0107 is not part of this source.
No merge, stable release, hosted CI success, native recovery, configured HTTPS,
full Python3.11 regression, signed release/provenance, capacity, HA/DR,
independent compliance assessment or production acceptance follows from these
results. Historical amounts already rounded by callers are not repaired.

Next execute the native encrypted backup/isolated restore test with owned
source/maintenance services and native PostgreSQL client tools, and the nine
browser journeys with provisioned HTTPS/API/session/synthetic targets. Preserve
those results separately; a PostgreSQL scoped route test is not an authenticated
network/browser journey. Draft review targets the unchanged sprint checkpoint
and keeps the 308 inherited main-to-sprint commits outside this repair's diff.

Rollback reverts the Money/Finance conversion and gate-repair commits with
their tests and lock change; no database migration is required. This restores
the known original exactness and dependency findings, which require an explicit
disposition if rollback is selected.

## Later source-bound acceptance

[Final runtime recovery and regression acceptance](ACCEPTANCE_FINAL_2026-10-08.md) supersedes the pending native/whole-regression status only for its exact later source. The original table and limitations above remain historical b8f5a772 evidence.
