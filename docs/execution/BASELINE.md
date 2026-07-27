# Baseline Run Report

Snapshot date: 2026-07-24 (Africa/Cairo)

## Scope and reproducibility boundary

- Current branch: `feature/p0-atomic-audit-outbox` at `bdf63de48051a0ef5c694442208f5207f4dd5e1c`.
- Base: `origin/main` at `6a785c0b42f57aee80e3082c0226e6f99742f80b`; the current branch contains that base plus 11 commits.
- The local `main` pointer was fast-forwarded to `origin/main` without checking it out or changing the worktree.
- The measured worktree is not a release candidate: 112 tracked files differ from `HEAD`, 99 untracked files exist, and `git status --porcelain=v1` emits 208 entries because untracked directories may be collapsed.
- Baseline commands were run against that exact dirty worktree. Results must not be attributed to `HEAD`, `main`, or a published release.

## Environment

| Item | Measured value |
| --- | --- |
| OS | Microsoft Windows 11 Pro 10.0.26200, build 26200 |
| CPU | AMD Ryzen 7 7435HS, 16 logical processors |
| RAM | 21,144,231,936 bytes reported by Windows |
| Python | 3.14.6 (newer than the declared/tested 3.11/3.12 classifiers) |
| pandas / Pydantic / FastAPI / DuckDB | 3.0.3 / 2.13.4 / 0.139.2 / 1.5.5 |
| Node / npm | Node 26.3.0; `npm.ps1` blocked by PowerShell policy, so gates used `npm.cmd` |
| Git | 2.54.0.windows.1 |
| Docker | Client 29.6.1; `desktop-linux` daemon unavailable |

## Backend and repository gates

| Command | Exit | Result | Duration | Evidence |
| --- | ---: | --- | ---: | --- |
| `python -m ruff check .` | 1 | Fail | 0.181s | 7 findings: import order/placement and two unused imports |
| `python -m mypy reconforge` | 1 | Fail | 21.406s | 2 argument-type errors in matching and validation |
| `python -m pytest --basetemp=.pytest-baseline-current -q` | 1 | Fail | ~150s | 637 collected; 626 passed, 10 skipped, 1 deterministic failure |
| `python -m bandit -q -r reconforge` | 0 | Pass | 4.367s | No findings; three `nosec B608` notices point to the same validated dynamic-SQL line |
| `python -m pip_audit` | 0 | Pass with scope limit | 12.376s | No known vulnerabilities; the local `reconforge-erp` package is not on PyPI and was skipped |
| `python -m build --no-isolation` | 0 | Pass | 14.404s | Built `reconforge_erp-0.7.0.tar.gz` and wheel; emitted setuptools metadata-overwrite warnings |
| `git diff --check` | 2 | Fail | 0.089s | Two trailing-whitespace lines in `EVIDENCE.md` and one blank line at EOF in `money.py` |

The failing test is `tests/test_generator_benchmark_engines.py::test_duckdb_partitioned_execution_is_row_order_invariant`. Two focused replays failed with the same digest pair, so it is not classified as flaky.

## Web gates

| Command | Exit | Result | Duration | Evidence |
| --- | ---: | --- | ---: | --- |
| `npm.cmd --prefix apps/web ci` | 0 | Pass | 23.866s | 158 packages installed; npm reported 0 vulnerabilities |
| `npm.cmd --prefix apps/web run typecheck` | 0 | Pass | 1.225s | TypeScript build check passed |
| `npm.cmd --prefix apps/web run test:run` | 0 | Pass | 7.288s | 17 tests passed in 1 file |
| `npm.cmd --prefix apps/web run build` | 0 | Pass | 1.751s | Vite production build completed |
| `npm.cmd --prefix apps/web run e2e` | 0 | Pass | 7.127s | 2 Playwright tests passed |

## Runtime gates

| Command | Exit | Result | Duration | Evidence |
| --- | ---: | --- | ---: | --- |
| `reconforge doctor` | 0 | Pass | 2.582s | Package/config/sample/output OK; validation reports 0 errors and 10 warnings |
| `reconforge validate examples/sample_data` | 0 | Pass | 2.360s | 0 errors, 10 visible data-quality warnings |
| `reconforge demo run --output output/baseline-demo-current` | 0 | Pass | 5.541s | 13 stock/GL exceptions, 16 work-order exceptions, 14 evidence cases |
| `docker build -t reconforge:baseline .` | n/a | Environment unavailable | n/a | Docker daemon pipe `dockerDesktopLinuxEngine` does not exist |
| `docker run --rm reconforge:baseline reconforge doctor` | n/a | Not run | n/a | Requires a successful image build and running daemon |

`output/baseline-demo` already existed and was preserved; the new runtime evidence uses `output/baseline-demo-current`.

## Baseline verdict

The package build, local CLI, security scans, and web gates execute successfully in this environment. The baseline is not green because lint, typing, whitespace, and a critical order-invariance test fail. Docker parity and live PostgreSQL/Redis/object-storage tests remain unverified locally. No stable, enterprise-ready, scale, compliance, or cross-engine determinism claim is allowed from this snapshot.

## Post-baseline remediation in the same worktree

The initial failures above remain the reproducible audit result. After documenting them, the first Money/Currency and stable-decimal-identity slices produced this newer gate state:

| Command | Exit | Result | Duration |
| --- | ---: | --- | ---: |
| `python -m ruff check .` | 0 | All checks passed | 0.126s |
| `python -m mypy reconforge` | 0 | No issues in 205 source files | 0.988s |
| Money/validation/reconciliation targeted suite | 0 | 52 passed | 2.770s |
| DuckDB parity/partition/permutation targeted suite | 0 | 3 passed | 5.250s |
| Documentation/claim targeted suite | 0 | 15 passed | <2s |
| `python -m pytest --basetemp=.pytest-full-final -q` | 0 | 627 passed, 10 skipped, 0 failed | 132.040s |
| `python -m bandit -q -r reconforge` | 0 | No findings | 4.335s |

### Later P0 Money/Currency registry and CLI-boundary evidence

The subsequent P0-004 completion and first P0-005 slice do not change the
initial baseline result above. They establish a newer dirty-worktree state:

| Command | Exit | Result | Duration |
| --- | ---: | --- | ---: |
| Currency/reconciliation/financial-CLI targeted suite | 0 | 73 passed | 8.480s |
| `python -m pytest --basetemp=.pytest-full-final-authoritative -q` | 0 | 648 collected; 638 passed, 10 skipped | 99.235s |
| `python -m ruff check .` | 0 | All checks passed | 0.204s |
| `python -m mypy reconforge` | 0 | No issues in 206 source files | 2.882s |
| `python -m bandit -q -r reconforge` | 0 | No findings | 4.829s |
| `python -m pip_audit` | 0 | No known vulnerabilities in audited installed packages; local package skipped | 12.185s |
| `python -m build --no-isolation` | 0 | sdist/wheel built; currency snapshot included in both | 12.824s |
| `python -m pip_audit` | 0 | No known vulnerabilities in audited installed packages | 13.113s |
| `python -m build --no-isolation` | 0 | sdist and wheel built | 13.927s |
| `git diff --check` | 0 | Clean | 0.082s |

Later slices do not change the dirty-worktree boundary. E-054 adds a locally validated universal Python/server lock and dependency/secret policy definitions, but Docker/live-service/hosted supported-version execution, the npm SRI gap, broad financial-float migration, and all supported engine cases remain unresolved.
