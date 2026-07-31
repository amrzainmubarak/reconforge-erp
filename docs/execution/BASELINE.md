# ReconForge Baseline Audit

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
