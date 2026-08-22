# ReconForge Baseline Audit

> Historical command snapshot. Its external-gate closure failure was superseded
> by the owner/team release policy in E-251/D236; recorded command outcomes
> remain historical evidence rather than current release state.

> Updated local refresh snapshot below reflects the latest local run in this
> machine/session. "Passed/blocked" entries are environment-scoped and should not
> be interpreted as cross-platform production evidence.

## Latest refresh (2026-08-11)

- Date: 2026-08-11
- Host: Windows 11 / PowerShell
- Working directory: `F:\reconforge-erp`
- Python environment: `python 3.14.x` (local environment)

### Python & Backend Checks
- `python -m ruff check .` : Passed (Exit 0).
- `python -m mypy reconforge` : Passed (Exit 0).
- `python -m pytest` : Passed (Exit 0) after full suite.
  - Result: **2775 passed, 110 skipped** (23 warnings, `LegacyFinancialInputWarning`) in **557.82 s** (9m 17s).
- `python -m bandit -q -r reconforge` : Passed (Exit 0), no blocking issues.
- `python -m pip_audit` : Passed (Exit 0).
  - No known vulnerabilities found.
- `python -m build --no-isolation` : Passed.
  - Built artifacts include `reconforge_erp-0.7.1.tar.gz` and `reconforge_erp-0.7.1-py3-none-any.whl`.
- `git diff --check` : Passed (Exit 0), CRLF normalization note only.

### Web Frontend Checks (apps/web)
- `npm --prefix apps/web ci` : Passed (Exit 0).
- `npm --prefix apps/web run typecheck` : Passed (Exit 0).
- `npm --prefix apps/web run test:run` : Passed.
  - Result: **13 files, 70 tests**.
- `npm --prefix apps/web run build` : Passed (Exit 0).
- `npm --prefix apps/web run e2e` : Passed (Exit 0).
  - Result: **21 tests, 16 passed, 5 skipped**.

### Platform CLI & Demo
- `reconforge doctor` : Passed.
- `reconforge validate examples/sample_data` : Passed with warnings only (0 errors).
- `reconforge demo run --output output/baseline-demo` : Passed.
  - Produced dashboard/executive/pack/artifact outputs in `output/baseline-demo`.

### Docker
- `docker build -t reconforge:baseline .` : Passed (Exit 0, 2.748 s).
- `docker run --rm reconforge:baseline reconforge doctor` : Passed (Exit 0).
  - Health snapshot: Package/config/output/validation all OK with 10 warnings, 0 errors.

#### E-822 hardened runtime refresh (2026-08-22)

- Host: Docker Desktop 4.87.0, Linux engine 29.7.2/API 1.55 on Windows.
- Baseline context/image/user: 53.82 MB; 149,556,826 bytes; UID/GID 0.
- Final context/image/user: 216.25 KB; 58,773,988 bytes; fixed UID/GID 10001.
  The accepted Python 3.11 Alpine runtime excludes uv, global pip/build
  packages, source, project build manifests, and repository documentation.
- Doctor, sample validation, audit-basic rules, and the complete demo pass with
  `--network none --read-only` and bounded UID/GID-owned tmpfs mounts for
  `/tmp` and `/app/output`.
- This refresh is current local runtime evidence only. It does not supersede
  hosted/reproducibility/scanning/signature/provenance requirements.
- Docker Scout 1.24.0 exact-image scan: exit 0 after indexing 82 packages;
  zero findings at all severities. The result is time-bounded and is not the
  current release gate because the later pinned Grype database disagrees.

#### E-823/E-824 exact-image security result (2026-08-22)

- Syft 1.51.0 inventories 68 package artifacts with 94.11% usable license
  metadata. Grype 0.117.0 database v6.1.9 reports five High matches.
- Exact CPython source/tag evidence establishes CVE-2026-3644,
  CVE-2026-4224, and CVE-2026-7210 as fixed in Python 3.11.16. The closed
  fixed-only OpenVEX path records those decisions while retaining them in the
  total count.
- CVE-2026-14456 remains unexcepted for libcrypto3 and libssl3 3.5.7-r0.
  The gate exits 1 and blocks registry authentication. No supported current
  Alpine candidate offered upstream-fixed OpenSSL 3.5.8 at review time.

#### E-825 write-back lifecycle identity refresh (2026-08-22)

- The SQLite schema head advances from 41 to 42 and the PostgreSQL source
  Alembic head advances from `0088_pg_currency_snapshot` to
  `0089_pg_writeback_identity`.
- Focused local SQLite execution proves proposal-drift/state-jump refusal and
  fail-closed upgrade behavior. A digest-pinned PostgreSQL 17.10 Alpine runtime
  passes both write-back histories under a non-superuser/NOBYPASSRLS role and
  an isolated three-upgrade/two-deep-downgrade Alembic drill through head 0089.
- The API exposes an additive stable proposal digest. This is bounded intent
  governance only, not provider connectivity, accounting posting, autonomous
  approval, or production write-back assurance.

### Disposable PostgreSQL boundary checks
- `uv run --no-sync pytest -q -ra tests/test_application_metrics.py::test_live_postgres_metrics_and_sqlite_parity tests/test_alembic_postgres.py::test_alembic_upgrade_command_is_available_when_server_extra_is_installed` : **Passed (2/2)**.
  - Historical E-706 environment: Docker `postgres:16-alpine` 16.14, isolated database, Alembic head `0086_pg_close_reopened`, and a non-privileged `reconforge_app` role. The current source migration head is `0088_pg_currency_snapshot`; no live rerun of the new `0087`/`0088` migrations is implied here.
- `uv run --no-sync pytest -q -rs tests/test_postgres_backup.py::test_live_postgres_native_adapter_encrypted_backup_isolated_restore_and_cleanup` : **Skipped (capability)**.
  - Reason: Windows host has no native `pg_config`/`pg_dump`/`pg_restore` toolchain; hosted Linux bootstrap remains required for E-461.

### Supply-chain and release-freeze checks
- `uv run --isolated --python 3.11 --all-extras --locked --no-editable python -c "import cbor2, cryptography, opentelemetry.sdk.metrics"` : Passed.
- `uv run --isolated --python 3.12 --all-extras --locked --no-editable pytest ...` (historical CI import-error modules) : Passed (48 passed, 1 declared live-PostgreSQL skip).
- Gitleaks 8.30.1 full-history and working-tree scans : Passed (684 commits; 30.65 MB tree; zero findings).
- `uv run --no-sync pytest -q tests/test_signed_release_pipeline.py` : Passed (17 tests), including the active D-485 freeze and explicit-closure guard.

## Environment & Commands Execution Log

- Date: 2026-07-31
- Host: Windows 11 / PowerShell
- Working directory: `F:\reconforge-erp`
- Python environment: `python 3.14.x` (locked local virtual environment in this session)

### Python & Backend Checks
- `python -m ruff check .` : Passed (Exit 0, 224 ms).
- `python -m mypy reconforge` : Passed (Exit 0, 760 ms).
- `python -m pytest` : Failed only by design on phase-closure guard.
  - Result: **2005 passed, 64 skipped, 1 failed** (runtime 259.62 s / 259,620 ms).
  - Failed test: `tests/test_phase_1_3_execution_contract.py::test_phase_three_has_no_unsupported_completion_shortcut`.
  - Failure reason: `docs/execution/PHASE_1_3_EXECUTION_MATRIX.yaml` currently sets `all_tasks_completed=false` and `all_required_gates_verified=false` by design while `P3-EXT-001`, `P3-EXT-002`, and some Phase-3 internal tasks remain open.
- `python -m bandit -q -r reconforge` : Passed (Exit 0, 8.5 s). No findings.
- `python -m pip_audit` : Passed (Exit 0, 13.7 s).
  - Non-blocking skip detail: reconforge-erp package not found on PyPI for local package-audit continuity.
- `python -m build --no-isolation` : Passed. Built artifacts include `reconforge_erp-0.7.1.tar.gz` and `reconforge_erp-0.7.1-py3-none-any.whl`.
  - Exit 0, 8.5 s.
- `git diff --check` : Passed (Exit 0, ~8.5 s).
  - Only CRLF normalization notices on tracked files.

### Web Frontend Checks (apps/web)
- `npm --prefix apps/web ci` : Passed. Exit 0, 7.6 s.
  - Installed 160 packages; no vulnerabilities.
- `npm --prefix apps/web run typecheck` : Passed. Exit 0, 1.306 s.
- `npm --prefix apps/web run test:run` : Passed. Exit 0, 55 tests in 8 test files.
  - Duration 7.04 s.
- `npm --prefix apps/web run build` : Passed. Exit 0, 1.825 s.
- `npm --prefix apps/web run e2e` : Passed. Exit 0, 11 passed / 5 skipped.
  - Duration 27.2 s.

### Platform CLI & Demo
- `reconforge doctor` : Passed. Exit 0, ~1.3 s.
- `reconforge validate examples/sample_data` : Passed. Exit 0, 2.897 s.
  - 10 warnings, 0 errors.
- `reconforge demo run --output output/baseline-demo` : Passed. Exit 0, 7.196 s.
  - Generated artifacts including:
    - `output/baseline-demo/dashboard.html`
    - `output/baseline-demo/executive_report.html`
    - `output/baseline-demo/management_pack.xlsx`
    - `output/baseline-demo/review_state.json`
    - `output/baseline-demo/review_register.xlsx`
    - `output/baseline-demo/evidence/index.html`
    - `output/baseline-demo/client_pack/*`

### Docker
- `docker build -t reconforge:baseline .` : Passed. Exit 0, 2.748 s.
- `docker run --rm reconforge:baseline reconforge doctor` : Passed. Exit 0, 5.124 s.
  - Health snapshot: Package/config/output/validation all OK with 0 errors and 10 warnings.

## Latest refresh (2026-08-15)

- Date: 2026-08-15
- Host: Windows 11 + WSL2 Ubuntu for native-tool checks
- Working directory: `F:\reconforge-erp`
- Python environment: `python 3.14.x` (local session)

### Python & Backend Checks
- `python -m ruff check .` : Passed (latest local static run logged in recent baseline updates).
- `python -m mypy reconforge` : Passed (no issues in 520 source files).
- `python -m pytest` : Passed (local full-regression result logged as 100% in the local evidence set).
- `python -m bandit -q -r reconforge` : Passed (informational warnings only).
- `python -m pip_audit` : Passed (no vulnerabilities reported in the same snapshot window).
- `python -m build --no-isolation` : Passed.
- `git diff --check` : Passed.

### Web Frontend Checks (apps/web)
- `npm --prefix apps/web ci` : Passed.
- `npm --prefix apps/web run typecheck` : Passed.
- `npm --prefix apps/web run test:run` : Passed.
- `npm --prefix apps/web run build` : Passed.
- `npm --prefix apps/web run e2e` : Passed.

### Platform CLI & Demo
- `reconforge doctor` / `reconforge validate examples/sample_data` / `reconforge demo run --output output/baseline-demo` : Passed with documented local bounded warnings.

### PostgreSQL Boundaries
- `uv run --no-sync pytest tests/test_postgres_backup.py::test_live_postgres_native_adapter_encrypted_backup_isolated_restore_and_cleanup` :
  Passed in WSL2 local boundary using disposable PostgreSQL 16 and local `pg_wrapper` shim. Hosted Linux native-tool gate (`E-461`) still open.
- `postgres_durable_job` scale profiles: local one-host 1M synthetic durable-job evidence recorded for
  `postgres-durable-job-load/1m-effects-v1` with documented manifest effect digests and boundary limits in `E-806`.

### Boundary notes
- This section reflects local, environment-scoped evidence and does not constitute hosted production assurance, capacity/SLO claims, or release-closure substitution for open gates.
