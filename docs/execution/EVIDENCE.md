# Evidence Register

## Evidence Collected

### Baseline Gate Commands
- `python -m ruff check .`
- `python -m mypy reconforge`
- `python -m pytest`
- `python -m bandit -q -r reconforge`
- `python -m pip_audit`
- `python -m build --no-isolation`
- `git diff --check`

#### Session Outcomes
- `python -m ruff check .` → pass (`All checks passed!`)
- `python -m mypy reconforge` → pass (`Success: no issues found in 200 source files`)
- `python -m pytest --basetemp .\\.pytest-baseline` → pass (`554 passed, 10 skipped, 1 warning`)
- `python -m bandit -q -r reconforge` → pass with intentional `# nosec B608` warning on validated identifier interpolation in `reconforge/db/backup.py`.
- `python -m pip_audit` → `No known vulnerabilities found` (package `reconforge-erp` not audited on PyPI in this workspace).
- `python -m build --no-isolation` → pass (sdist and wheel generated successfully).
- `git diff --check` → pass (no conflict markers, no whitespace issues from this session).

### Frontend / UI Commands
- `npm.cmd --prefix apps/web ci`
- `npm.cmd --prefix apps/web run typecheck`
- `npm.cmd --prefix apps/web run test:run`
- `npm.cmd --prefix apps/web run build`
- `npm.cmd --prefix apps/web run e2e`

### App / Domain Commands
- `reconforge doctor`
- `reconforge validate examples/sample_data`
- `reconforge demo run --output output/baseline-demo`
- `docker build -t reconforge:baseline .`
- `docker run --rm reconforge:baseline reconforge doctor`
- CI-only parity checks (now defined in `.github/workflows/ci.yml`):
  - `docker build -t reconforge:ci-baseline .`
  - `docker run --rm reconforge:ci-baseline reconforge doctor`

### Security Slice Verification (P0-B2)
- `python -m bandit -q -r reconforge/engines/duckdb_engine.py` → pass (0 findings).
- `python -m bandit -q -r reconforge` → pass on currently enforced scope; backup restore path now uses a single documented `# nosec B608` only on validated identifier-only SQL string construction in `_build_insert_query`.
- `python -m py_compile reconforge/engines/duckdb_engine.py` → success.
- `python -m pip_audit` → no known vulnerabilities found.
- `python -m bandit -q -r reconforge/db/backup.py` → pass with one intentional `# nosec B608` on `_build_insert_query`; warnings confirm no actionable SQL injection patterns remain beyond that validated path.

## Evidence Files
- [BASELINE.md](BASELINE.md)
- [QUALITY_BASELINE.md](QUALITY_BASELINE.md)
- [SECURITY_BASELINE.md](SECURITY_BASELINE.md)
- [PERFORMANCE_BASELINE.md](PERFORMANCE_BASELINE.md)
- [DEPENDENCY_RISK.md](DEPENDENCY_RISK.md)
- [DOCUMENTATION_DRIFT.md](DOCUMENTATION_DRIFT.md)
- [CLAIMS_EVIDENCE_MATRIX.md](CLAIMS_EVIDENCE_MATRIX.md)
- [GAP_MATRIX.md](GAP_MATRIX.md)
- [BACKLOG.yaml](BACKLOG.yaml)
- [REPOSITORY_INVENTORY.md](REPOSITORY_INVENTORY.md)

## Traceability Notes
- Evidence commands are rerun for targeted commands when corresponding fixes are implemented.
- Open failures (environment gates) are paired with blockers and next remediation step.

## Targeted Slice Evidence
- `apps/web`: `npm.cmd --prefix apps/web run test:run` now passes (`1 passed (17)`).
- `P2-B8 container parity slice`: `docker build -t reconforge:baseline .` and `docker run --rm reconforge:baseline reconforge doctor` failed in this environment because docker API socket is unavailable (`npipe:////./pipe/dockerDesktopLinuxEngine`).
- `P2-B8 container parity slice`: `docker --context desktop-linux run --rm hello-world` also failed for the same API endpoint (`npipe:////./pipe/dockerDesktopLinuxEngine`).
- `P2-B8 container parity slice (CI)`: `.github/workflows/ci.yml` now includes a `docker-parity` job that runs container build + `reconforge doctor`, plus `reconforge validate examples/sample_data` and `reconforge rules validate --pack control-packs/audit-basic` in an isolated image tag to validate parity in Docker-capable runners.
- `P2-B8 container parity slice (CI evidence)`: PR `54` triggered workflow run `30070878830` with job list containing `docker-parity`.
  - Evidence:
    - https://github.com/amrzainmubarak/reconforge-erp/actions/runs/30070878830
  - `docker-parity` job `89411613485` → success.
  - `docker-parity` steps completed: image build, `reconforge doctor`, `reconforge validate examples/sample_data`, and `reconforge rules validate --pack control-packs/audit-basic`.
  - `test (3.11)` and `test (3.12)` also succeeded.
  - Note: run `30070878830` overall failed due unrelated `server-boundaries` failure in `Run Alembic PostgreSQL migration`; this does not invalidate `P2-B8` parity completion.
  - Fix implemented for follow-up: `server-boundaries` now runs Alembic via CLI (`alembic -c alembic.ini upgrade head`) in `.github/workflows/ci.yml` to avoid config-bootstrap script-location drift in runner execution.
  - Follow-up run `30072000950` confirmed additional `server-boundaries` blockers:
    - `ruff check .` now fails due import-block formatting (`I001`) in 10 Alembic revision files (`0001..0011`) importing `reconforge.infrastructure.*`.
    - Runtime migration fails with `ModuleNotFoundError: No module named 'reconforge.infrastructure'` at `alembic/versions/0001_postgres_tenant_boundary.py` during revision script import.
  - Corrections committed in this branch to unblock these blockers:
    - Added `reconforge_migration_sql.py` to provide resilient fallback extraction of Postgres schema SQL constants from checked-in source files when `reconforge.infrastructure` imports fail during revision loading.
    - Updated `alembic/versions/0001_postgres_tenant_boundary.py` .. `0011_postgres_reconciliation_checkpoints.py` to load SQL from the helper module at top-level revision import-time.
    - `python -m ruff check alembic/versions/0001_postgres_tenant_boundary.py ... alembic/versions/0011_postgres_reconciliation_checkpoints.py` now passes.
    - `PYTHONPATH=(Get-Location).Path` one-shot import script over `alembic/versions/*.py` now returns `IMPORT_OK 11`.
    - `PYTHONPATH: ${{ github.workspace }}` remains set in `Run Alembic PostgreSQL migration` step.
  - Historical context retained:
    - `gh run list --workflow ci.yml --repo amrzainmubarak/reconforge-erp --json databaseId,conclusion,status,headBranch --limit 80` + per-run `gh run view <id> --json jobs` previously confirmed no `docker-parity`; superseded by run `30070878830`.
    - `gh run list --workflow ci.yml --repo amrzainmubarak/reconforge-erp --branch feature/p0-atomic-audit-outbox --json databaseId,conclusion,status,createdAt --limit 20` returned `[]` before branch/PR run creation.
- `Alembic migration hardening verification (local, current branch):`
  - `python -m ruff check alembic/versions` → pass (`All checks passed!`).
  - `PYTHONPATH=(Get-Location).Path python` one-shot import over `alembic/versions/*.py` → `IMPORT_OK 11`.
  - `gh run view 30072000950 --job 89414652400 --log` remains a historical failure reference (inline bootstrap step), while `server-boundaries` migration command in the current workflow file is now CLI-based.
- `Static quality slice`: `python -m ruff check .` and `python -m ruff check --fix reconforge/platform/matching.py tests/test_platform_matching.py` → pass (2 issues auto-fixed).
- `docs/execution/BACKLOG.yaml`: `P1-B3` completed and execution tracker metadata synchronized (claims matrix + baseline/gap metrics).
  - `reconforge/io/readers.py`: invalid numeric values now remain explicit missing values (`None`) and preserve raw source text in `_reconforge_raw_<column>`.
  - `tests/test_readers.py`:
    - Added `test_coerce_dataset_types_preserves_invalid_numeric_original_and_marks_missing`.
- `reconforge/db/backup.py`: removed dynamic insert query concatenation and added identifier validation for backup restore table/pragma lookups.
  - `P1-B9`: restore inserts now derive insert-column sets from `PRAGMA table_info` for legacy snapshots, while still enforcing allowlisted query templates and schema metadata for defaults/nullability.
  - `python -m pytest tests/test_db_backup_restore.py -q --basetemp .\\.pytest-outbox-backup2` → passed (`8 passed`) including `test_version_six_backup_restores_then_upgrades_to_latest`.
  - Added `tests/test_db_backup_restore.py::test_restore_fills_optional_missing_restore_columns_from_defaults` to validate optional-column and default-backed restoration for `organizations` and `legal_entities`.
  - Extended the same test to assert `periods` fallback defaults when optional columns are intentionally omitted.
  - Targeted command to execute in next verification cycle:
    - `python -m pytest tests/test_db_backup_restore.py -k test_restore_fills_optional_missing_restore_columns_from_defaults --basetemp .\\.pytest-backup-defaults -q`
  - `python -m pytest tests/test_db_backup_restore.py -k test_restore_fills_optional_missing_restore_columns_from_defaults --basetemp .\\.pytest-backup-defaults -q` → passed (`1 passed`).
  - `python -m pytest tests/test_db_backup_restore.py -q --basetemp .\\.pytest-outbox-backup2` → passed (`8 passed`) including optional-column fallback coverage.
- `python -m ruff check reconforge/db/backup.py tests/test_db_backup_restore.py` → passed (all checks).
- `python -m bandit -q -r reconforge/db/backup.py tests/test_db_backup_restore.py` → warning-only output from test asserts/hardcoded fixture password; no restore-path regressions found.
- Money/Currency deterministic parsing slice:
  - `reconforge/utils/money.py`:
    - `parse_amount` now supports explicit locale separator normalization.
    - Precision helpers (`parse_amount_for_currency_precision`, `round_money`, `money_difference`, `within_tolerance`) preserve strict decimal validation.
  - `tests/test_reconciliation_hardening.py`:
    - Added `test_amount_parser_supports_locale_decimal_and_thousands_separators`.
    - Existing precision/invalid-value tests were used to validate backward compatibility and strict rejection paths.
- `python -m pytest tests/test_reconciliation_hardening.py -k "test_amount_parser_rejects_scientific_notation or test_amount_parser_supports_locale_decimal_and_thousands_separators or test_amount_parser_backward_compatible_finite_float_inputs" --basetemp .\\.tmp_pytest` → passed (`3 passed, 11 deselected`).
- `python -m pytest tests/test_reconciliation_hardening.py --basetemp .\\.tmp_pytest` → passed (`14 passed`).
- `tests/test_platform_common.py`: added for strict `to_float`/`to_int` regression coverage (invalid values no longer coerce to zero by default).
- `python -m pytest tests/test_platform_common.py -q --basetemp .\\.pytest-platform-common` executed successfully (`6 passed`).
- Deterministic risk-score robustness (`2026-07-24`):
  - `reconforge/risk/scoring.py`: invalid financial values in risk factors now remain non-numeric (`NaN`) through scoring helpers.
  - `reconforge/reconciliation/risk.py`: amount components skip invalid/non-numeric magnitudes instead of numeric zero casting.
  - `tests/test_risk_scoring.py`: added invalid-factor regression checks to ensure deterministic score behavior without silent coercion.
  - `reconforge/risk/scoring.py`: hardened `aging_days` parsing via fallback-safe integer coercion, and added `test_risk_scoring_invalid_aging_days_defaults_to_zero`.
- `docs/execution/BACKLOG.yaml`: `P0-B4` marked complete.
- `docs/execution/BACKLOG.yaml`: `P0-B2` marked complete.
- Dependency remediation:
  - `pyproject.toml`: added `pillow>=12.3.0` under `[project.optional-dependencies.dev]` to address baseline pip-audit vulnerability findings.
  - Runtime dependency refresh: `python -m pip install --upgrade "pillow>=12.3.0"` executed in the working environment.
- Targeted verification:
  - `python -m pytest tests/test_readers.py -k preserves_invalid_numeric -q` → passed (`1 passed`).
- Matching determinism (P1-B6):
  - `tests/test_platform_matching.py`:
    - Added deterministic signature-based invariance tests for randomized permutations and in-memory `match_records` execution.
- Targeted verification:
  - `python -m pytest tests/test_platform_matching.py -k invariance --basetemp F:\\reconforge-erp\\.pytest-matching-invariance -q` → passed (`2 passed`).
- Empty-exception behavior (P1-B5):
  - `tests/test_platform_matching.py`:
    - Added `test_matching_returns_empty_exception_payload_when_inputs_are_fully_valid`.
    - Added `test_matching_invalid_amount_emits_invalid_amount_exception`.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "empty_exceptions or invariance" --basetemp F:\\reconforge-erp\\.pytest-matching-invariance -q` → passed (`2 passed`).
    - `python -m pytest tests/test_platform_matching.py -k "invalid_amount_emits_invalid_amount_exception or matching_returns_empty_exception_payload_when_inputs_are_fully_valid or invariance" --basetemp F:\\reconforge-erp\\.pytest-matching-invariance -q` → passed (`4 passed`).
  - `python -m pytest tests/test_platform_matching.py -k matching_data_quality_exceptions_are_order_invariant --basetemp .\\.pytest-baseline-target` → passed (`1 passed`).
- Matching explainability slice (in-memory):
  - `tests/test_platform_matching.py`:
    - Added `test_matching_explainability_payload_includes_alternatives_and_stable_selection_reason` to validate candidate alternatives and stable selected rationale in lineage.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k explainability --basetemp .\\.pytest-explainability` → passed (`1 passed`).
- Matching explainability slice (full persisted-path parity check):
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results" -q --basetemp .\\.pytest-explainability` → passed (`2 passed`).
- Matching explainability slice (unmatched right coverage):
  - `tests/test_platform_matching.py`:
    - Added `test_matching_in_memory_unmatched_right_explainability_includes_rejection_reason` to assert non-matched right-side payload includes rejection reason and stable diagnostics.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability" -q --basetemp .\\.pytest-explainability` → passed (`3 passed`).
- Matching explainability slice (unmatched left coverage):
  - `tests/test_platform_matching.py`:
    - Added `test_matching_in_memory_unmatched_left_explainability_includes_rejection_reason` to assert left-side non-match diagnostics remain explicit and stable.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability or unmatched_left_explainability" -q --basetemp .\\.pytest-explainability` → passed (`4 passed`).
- Matching explainability slice (tie-break determinism):
  - `tests/test_platform_matching.py`:
    - Added `test_matching_tie_breaking_is_deterministic_when_confidence_is_tied` to validate deterministic selection and stable rationale when candidates share equal score.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability or unmatched_left_explainability or tie_breaking_is_deterministic_when_confidence_is_tied" -q --basetemp .\\.pytest-explainability` → passed (`5 passed`).
- Matching explainability slice (DB-path tie-break determinism):
  - `tests/test_platform_matching.py`:
    - Added `test_matching_db_tie_breaking_is_deterministic_when_confidence_is_tied` to validate persisted result determinism and identical lineage under equal-score collisions.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability or unmatched_left_explainability or tie_breaking_is_deterministic_when_confidence_is_tied or db_tie_breaking_is_deterministic_when_confidence_is_tied" -q --basetemp .\\.pytest-explainability` → passed (`6 passed`).
- Matching explainability slice (many-to-many + disabled-flow rejection):
  - `tests/test_platform_matching.py`:
    - Added `test_matching_many_to_many_explainability_stability` to verify grouped candidate explanations remain stable under shuffled input.
    - Added `test_matching_many_to_many_disabled_rejects_competing_candidates_with_expected_rejection_narrative` to verify deterministic rejection narratives when grouped matching is disabled.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "many_to_many_explainability_stability or many_to_many_disabled_rejects_competing_candidates_with_expected_rejection_narrative" -q --basetemp .\\.pytest-explainability` → passed (`2 passed`).
- Reference-normalization config validation slice:
  - `tests/test_platform_matching.py`:
    - Added `test_reference_normalization_rules_reject_invalid_configuration` to assert malformed `reference_normalization_rules` fail fast with deterministic `PlatformError` messages.
    - Added `test_reference_normalization_rules_reject_invalid_regex_normalization_pattern` to assert invalid regex patterns fail fast with deterministic `PlatformError` messages.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "reference_normalization_rules_reject_invalid_configuration or reference_normalization_rules_reject_invalid_regex_normalization_pattern" --basetemp .\\.pytest-baseline-target -q` → passed (`2 passed`).
- Unknown-currency precision parity slice:
  - `tests/test_platform_matching.py`:
    - Added `test_matching_unknown_currency_precision_works_identically_in_memory_and_run` to validate exact bucketing and row-order invariance for unknown-currency matching candidates.
  - Targeted verification:
    - `python -m pytest tests/test_platform_matching.py -k "unknown_currency_precision_works_identically_in_memory_and_run" -q --basetemp .\\.pytest-explainability` → passed (`1 passed`).
- Unknown-currency precision performance slice:
  - `tests/test_generator_benchmark_engines.py`:
    - Added `test_reconciliation_execution_benchmark_supports_unknown_currency_precision_and_reproducibility` to verify synthetic benchmark reproducibility with high-decimal amounts (`amount_fractional_digits=4`).
  - Targeted verification:
    - `python -m pytest tests/test_generator_benchmark_engines.py -k "partitioned_reconciliation_execution_benchmark_is_reproducible or test_reconciliation_execution_benchmark_supports_unknown_currency_precision_and_reproducibility" -q --basetemp .\\.pytest-benchmark-slice` → passed (`2 passed`).
    - `python -c "from reconforge.benchmark.reconciliation_execution import run_reconciliation_execution_benchmark; m = run_reconciliation_execution_benchmark(10000, amount_fractional_digits=4, output_dir='output/reconciliation-benchmark-10k-4dp'); print(m.to_dict())"` → runtime `3.3439`, `matched_rows=5000`, `exception_count=0`.
    - `python -c "from reconforge.benchmark.reconciliation_execution import run_reconciliation_execution_benchmark; m = run_reconciliation_execution_benchmark(100000, amount_fractional_digits=4, output_dir='output/reconciliation-benchmark-100k-4dp'); print(m.to_dict()['runtime_seconds'], m.to_dict()['peak_memory_mb'], m.to_dict()['result_signature'])"` → runtime `54.4183`, `runtime_seconds=54.4183`, `peak_memory_mb=106.66`, `result_signature=c53fe0b0bd38761c32be73065544baf69c64ae88a86c706f01e5e45f51f675ef`.
  - CLI path verification (`reconforge.cli` app):
    - `python -c "from reconforge.cli import app; app(['benchmark-reconciliation','--records','10000','--partitions','2','--amount-fractional-digits','4','--output','output/reconciliation-benchmark-10k-4dp-cli'])"` executed successfully and produced reconciliation benchmark output table.
    - `python -c "from reconforge.cli import app; app(['benchmark-reconciliation','--records','100000','--partitions','20','--amount-fractional-digits','4','--output','output/reconciliation-benchmark-100k-4dp-cli'])"` executed successfully and produced reconciliation benchmark output table.
    - `python -c "from reconforge.cli import app; app(['benchmark-reconciliation','--records','100000','--partitions','20','--streaming','--amount-fractional-digits','4','--output','output/reconciliation-benchmark-100k-4dp-stream'])"` executed successfully and wrote `output/reconciliation-benchmark-100k-4dp-stream/reconciliation-execution.json`.
  - `output/reconciliation-benchmark-100k-4dp-stream/reconciliation-execution.json`:
    - `engine_used`: `local-deterministic-partitioned-streaming`
    - `runtime_seconds`: `57.0513`
    - `peak_memory_mb`: `15.52`
    - `matched_rows`: `50000`
    - `result_signature`: `330314ec4d12400b72338906402070d368643f65d63732659d5ec2e8145c9b08`
  - 1,000,000-record unknown-precision attempts:
    - non-streaming benchmark with `records=1_000_000`, `amount_fractional_digits=4`, `partition_count=1000` did not return within practical local runtime.
    - streaming benchmark attempts with large partition counts similarly did not complete within practical local runtime in this environment.
- Baseline command set closure:
  - `python -m ruff check .` → pass (`All checks passed!`).
  - `python -m mypy reconforge` → success (`Success: no issues found in 200 source files`).
  - `python -m pytest --basetemp .\\.pytest-baseline` → pass (`554 passed, 10 skipped, 1 warning`).
  - `python -m pytest tests/test_platform_matching.py -k "matching_without_currency_precision_uses_exact_amount_bucketing_for_candidate_indexing" --basetemp .\\.pytest-baseline-target -q` → pass (`1 passed`).


### Reporting aggregate hardening (2026-07-24)
- `reconforge/reports/management_pack.py`:
  - _sum_decimal_series now uses optional parsing for aggregate rows, ensuring malformed amounts do not become successful zeros.
  - _amount_impact_series now uses staged optional parsing and null-safe `copy_abs` flow for missing/invalid values.
- `tests/test_reports.py`:
  - Added `test_amount_impact_series_preserves_invalid_values_without_crashing`.
  - Added `test_risk_matrix_ignores_invalid_amounts_when_summing`.

#### Targeted verification (reports)
- `python -m pytest tests/test_reports.py -k "amount_impact_series_preserves_invalid_values_without_crashing or risk_matrix_ignores_invalid_amounts_when_summing or management_pack_executive_summary_preserves_decimal_precision or high_risk_exceptions_respects_invalid_risk_score_values or to_decimal_rejects_invalid_amount_text" --basetemp .\.pytest-report-slice2 -q` → passed (`5 passed`).

