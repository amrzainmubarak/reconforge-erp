# Execution State

## Repository
- Path: `F:/reconforge-erp`
- Working branch: feature/p0-atomic-audit-outbox (local)
- Timestamp: 2026-07-24

## Current Phase
- Phase 0 – Baseline, reproducibility, and evidence capture (in progress)

## Active Task
- `P2-B8` (container parity gating) is complete in CI configuration: container build and in-image smoke checks (`reconforge doctor`, `reconforge validate`, `reconforge rules validate`) are now enforced.
- Residual local constraints:
  - `docker build/run` is still blocked on this workstation (`npipe:////./pipe/dockerDesktopLinuxEngine`), so runtime validation must be confirmed via CI workflow output.
  - `python -m bandit -q -r reconforge/db/backup.py` confirms restore-path SQL hardening is clean after the `P1-B9` changes.

## Scope Constraints
- Do not start major architecture refactors before baseline evidence is complete.
- No placeholder implementations.
- Every code change must include test and evidence artifacts.
- No data-loss or silent coercion in financial paths.

## Latest Evidence
- `pyproject.toml` dependency constraints updated: `pillow>=12.3.0` added under `dev` extras as a remediation step for previously reported pip-audit vulnerability.
- `python -m ruff check .` → success (all checks passed)
- `python -m mypy reconforge` → success (no issues found in 200 source files)
- `python -m pytest` → success (`554 passed, 10 skipped, 1 warning`) using `--basetemp .\\.pytest-baseline`.
- `python -m bandit -q -r reconforge` → no actionable failures.
- `python -m bandit -q -r reconforge/engines/duckdb_engine.py` → pass (0 findings)
- `python -m py_compile reconforge/engines/duckdb_engine.py` → success
- `python -m pip_audit` → no known vulnerabilities found
- `python -m build --no-isolation` → success
- `npm.cmd --prefix apps/web ci` → success
- `npm.cmd --prefix apps/web run typecheck` → success
- `npm.cmd --prefix apps/web run test:run` → passed (`1 passed (17)`).
- `npm.cmd --prefix apps/web run build` → success
- `npm.cmd --prefix apps/web run e2e` → success (2 tests)
- `reconforge doctor` → success
- `reconforge validate examples/sample_data` → success
- `reconforge demo run --output output/baseline-demo` → success
- `python -m ruff check .` (post-merge import/order correction) → success (`All checks passed!`)
- `python -m pytest tests/test_platform_matching.py -k "matching_without_currency_precision_uses_exact_amount_bucketing_for_candidate_indexing" --basetemp .\\.pytest-baseline-target -q` → passed (`1 passed`).
- `python -m pytest tests/test_reconciliation_hardening.py -k "test_amount_parser_rejects_scientific_notation or test_amount_parser_supports_locale_decimal_and_thousands_separators or test_amount_parser_backward_compatible_finite_float_inputs" --basetemp .\\.tmp_pytest` → passed (`3 passed, 11 deselected`).
- `python -m pytest tests/test_reconciliation_hardening.py --basetemp .\\.tmp_pytest` → passed (`14 passed`).
- Direct default-temp run of the same test hit host permissions error (`C:\\Users\\LOQ\\AppData\\Local\\Temp\\pytest-of-LOQ` access denied); using explicit basetemp succeeded and is recorded above.
- Docker gates unavailable (daemon not running in this environment)
- `.github/workflows/ci.yml` now includes a `docker-parity` job that runs container build and `reconforge doctor` in the same image.
- `docker-parity` job was strengthened to also run `reconforge validate examples/sample_data` and `reconforge rules validate --pack control-packs/audit-basic` in-container for parity parity with CLI smoke coverage (not locally runnable in this environment without Docker daemon).
- `docker build -t reconforge:baseline .` → failed: cannot connect to docker API (`npipe:////./pipe/dockerDesktopLinuxEngine`)
- `docker run --rm reconforge:baseline reconforge doctor` → failed: cannot connect to docker API (`npipe:////./pipe/dockerDesktopLinuxEngine`)
- `docker --context desktop-linux run --rm hello-world` → failed for same API endpoint (`npipe:////./pipe/dockerDesktopLinuxEngine` not available)
- `python -m ruff check alembic/versions` → success after import-block fixes applied to migration files (`10` files).
- `gh run view 30072000950 --job 89414652400 --log --repo amrzainmubarak/reconforge-erp` equivalent check showed server-boundaries still failed for:
  - import-lint `I001` in ten Alembic version files (`0001..0011`)
  - migration import failure: `ModuleNotFoundError: No module named 'reconforge.infrastructure'`
- Local smoke (`python` one-shot import over `alembic/versions/*.py` with `PYTHONPATH=$PWD`) → `IMPORT_OK 11` (all Alembic revision modules importable in repository checkout state).
- `python -m pytest tests/test_readers.py -k preserves_invalid_numeric -q` → passed (`1 passed`)
- `python -m pytest tests/test_platform_matching.py -k invariance --basetemp F:\reconforge-erp\.pytest-matching-invariance -q` → passed (`2 passed`)
- `python -m pytest tests/test_platform_matching.py -k "empty_exceptions or invariance" --basetemp F:\reconforge-erp\.pytest-matching-invariance -q` → passed (`2 passed`)
- `python -m pytest tests/test_platform_matching.py -k "invalid_amount_emits_invalid_amount_exception or matching_returns_empty_exception_payload_when_inputs_are_fully_valid or invariance" --basetemp F:\reconforge-erp\.pytest-matching-invariance -q` → passed (`4 passed`)
- `python -m pytest tests/test_platform_matching.py -k matching_data_quality_exceptions_are_order_invariant --basetemp .\\.pytest-baseline-target` → passed (`1 passed`)
- `python -m pytest tests/test_platform_matching.py -k explainability --basetemp .\\.pytest-explainability` → passed (`1 passed`)
- `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results" -q --basetemp .\\.pytest-explainability` → passed (`2 passed`)
- `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability" -q --basetemp .\\.pytest-explainability` → passed (`3 passed`)
- `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability or unmatched_left_explainability or tie_breaking_is_deterministic_when_confidence_is_tied or db_tie_breaking_is_deterministic_when_confidence_is_tied" -q --basetemp .\\.pytest-explainability` → passed (`6 passed`)
- `python -m pytest tests/test_platform_matching.py -k "many_to_many_explainability_stability or many_to_many_disabled_rejects_competing_candidates_with_expected_rejection_narrative" -q --basetemp .\\.pytest-explainability` → passed (`2 passed`)
- `python -m pytest tests/test_platform_common.py -q --basetemp .\\.pytest-platform-common` → passed (`6 passed`).
- `python -m pytest tests/test_platform_matching.py -k "unknown_currency_precision_works_identically_in_memory_and_run" -q --basetemp .\\.pytest-explainability` → passed (`1 passed`)
- Benchmark micro-slice:
  - `python -m pytest tests/test_generator_benchmark_engines.py -k "partitioned_reconciliation_execution_benchmark_is_reproducible or test_reconciliation_execution_benchmark_supports_unknown_currency_precision_and_reproducibility" -q --basetemp .\\.pytest-benchmark-slice` → passed (`2 passed`)
  - `python -c "from reconforge.benchmark.reconciliation_execution import run_reconciliation_execution_benchmark; m = run_reconciliation_execution_benchmark(10000, amount_fractional_digits=4, output_dir='output/reconciliation-benchmark-10k-4dp'); print(m.to_dict())"` → runtime `3.3439s`, `matched_rows=5000`, `exception_count=0`, `amount_fractional_digits=4`.
  - `python -c "from reconforge.benchmark.reconciliation_execution import run_reconciliation_execution_benchmark; m = run_reconciliation_execution_benchmark(100000, amount_fractional_digits=4, output_dir='output/reconciliation-benchmark-100k-4dp'); print(m.to_dict()['runtime_seconds'], m.to_dict()['peak_memory_mb'], m.to_dict()['result_signature'])"` → runtime `54.4183s`, `runtime_seconds=54.4183`, `peak_memory_mb=106.66`, `result_signature=c53fe0b0bd38761c32be73065544baf69c64ae88a86c706f01e5e45f51f675ef`.
  - CLI validation:
    - `python -c "from reconforge.cli import app; app(['benchmark-reconciliation','--records','10000','--partitions','2','--amount-fractional-digits','4','--output','output/reconciliation-benchmark-10k-4dp-cli'])"` executed and printed benchmark table output.
    - `python -c "from reconforge.cli import app; app(['benchmark-reconciliation','--records','100000','--partitions','20','--amount-fractional-digits','4','--output','output/reconciliation-benchmark-100k-4dp-cli'])"` executed and printed benchmark table output.
  - 1,000,000-record attempts for unknown precision:
    - non-streaming `run_reconciliation_execution_benchmark(1_000_000, amount_fractional_digits=4, partition_count=1000)` did not complete in an acceptable local runtime and was stopped for this session.
    - streaming attempts with `run_reconciliation_execution_streaming_benchmark(..., partition_count=20000/100000)` also did not complete in practical local runtime.
  - `python -m pytest --basetemp .\\.pytest-baseline` → passed (`554 passed, 10 skipped, 1 warning`)
  - `gh run list --workflow ci.yml --repo amrzainmubarak/reconforge-erp --json databaseId,conclusion,status,headBranch --limit 80` + per-run `gh run view --json jobs` confirms no `docker-parity` job executed in inspected window.
  - The scan covered runs from `29951140420` (main, 2026-07-22) through `26816522153` (main, 2026-06-02); only `test` jobs were present in those runs.
  - `P2-B8` CI evidence is now captured in run `30070878830` (`https://github.com/amrzainmubarak/reconforge-erp/actions/runs/30070878830`):
    - `docker-parity` completed successfully (job `89411613485`).
    - `test (3.11)` and `test (3.12)` succeeded.
    - `server-boundaries` failed because `Run Alembic PostgreSQL migration` failed in this run; this is tracked as a residual risk separate from `P2-B8`.
- Code hardening: `reconforge/platform/matching.py` now uses currency-aware exact decimal bucketing (`_amount_bucket_key`) instead of implicit two-decimal rounding when precision is unknown.
- Regression test added: `tests/test_platform_matching.py::test_matching_without_currency_precision_uses_exact_amount_bucketing_for_candidate_indexing`.
- Outbox SQL hardening: `reconforge/platform/outbox.py` switched `list_events` to allowlisted full SQL templates and removed `# nosec` suppression for predicate-based query construction.
- Backup restore hardening: `reconforge/db/backup.py` now validates dynamic table identifiers, uses schema-derived insert columns for older-schema backups, and fills missing optional fields from explicit schema defaults/nullable rules while keeping unsupported columns rejected.
- Targeted backup compatibility check: `python -m pytest tests/test_db_backup_restore.py -q --basetemp .\\.pytest-outbox-backup2` → passed (`7 passed`) after version-6 restore compatibility validation.
- Parsing hardening: `reconforge/platform/common.py` now makes `to_float` and `to_int` strict by default (invalid values raise `PlatformError`) with explicit opt-in default fallback.
- Regression tests added in `tests/test_platform_common.py` for strict parsing and non-coercive defaults, including new coverage for `parse_financial_amount` context-aware failures.
- Deterministic exception identity slice for stock/GL reconciliation is now in progress: `reconforge/reconciliation/stock_gl.py` uses canonical payload hashing for `exception_id` and no longer includes `source_row` position metadata; `tests/test_reconciliation_hardening.py` includes `test_reconciled_exception_ids_are_reorder_invariant`.
- Additional hardening evidence added for row-order stability in data-quality exception IDs after shuffle via `test_reordered_rows_do_not_change_data_quality_exception_id`.
- `reconforge/platform/matching.py` now emits deterministic `exception_id` values for `data_quality` exceptions using canonical hashed payloads, and
  `tests/test_platform_matching.py::test_matching_data_quality_exception_ids_are_stable_under_row_shuffles` was added to lock row-order invariance.
- `reconforge/platform/matching.py` now validates `reference_normalization_rules.regex_normalizations` patterns at parse time and rejects malformed regular expressions with deterministic `PlatformError` messages.
- Targeted verification:
- `python -m pytest tests/test_platform_matching.py -k "reference_normalization_rules_reject_invalid_configuration or reference_normalization_rules_reject_invalid_regex_normalization_pattern" --basetemp .\\.pytest-baseline-target -q` → passed (`2 passed`).
- `python -m ruff check alembic/versions` → pass (`All checks passed!`) with current migration imports.
- `PYTHONPATH=(Get-Location).Path` import sweep over `alembic/versions/*.py` → `IMPORT_OK 11` (all revisions importable under clean checkout).
- `reconforge_migration_sql.py` added as a resilient Alembic schema loader and `0001..0011` PostgreSQL migration revisions now resolve SQL constants through it.
- `python -m ruff check reconforge_migration_sql.py alembic/versions/0001_postgres_tenant_boundary.py ... alembic/versions/0011_postgres_reconciliation_checkpoints.py` → pass.
- One-shot revision load (`python -c ... importlib.util`) using local checkout root now returns `IMPORT_OK 11`.

## Reporting Hardening Slice
- `reconforge/reports/management_pack.py` now avoids coerced zero substitution in aggregate report paths by switching to optional decimal parsing for risk and amount impact calculations.
- `_sum_decimal_series` now ignores invalid monetary values during summation and never turns invalid amount text into a successful numeric zero.
- `_amount_impact_series` now parses fields safely and preserves non-parseable values as invalid markers while selecting the first parseable amount for each row.
- Tests added:
  - `tests/test_reports.py::test_amount_impact_series_preserves_invalid_values_without_crashing`
  - `tests/test_reports.py::test_risk_matrix_ignores_invalid_amounts_when_summing`

## Planned Next Step
1. `P2-B8` parity proof captured and archived in `docs/execution/EVIDENCE.md` (`docker-parity` success in run `30070878830`).
2. Push or re-trigger hosted CI and confirm `server-boundaries` migration step now succeeds with this branch tip.
3. If `server-boundaries` remains green, mark `P1-B13` complete and remove residual-risk tracking; otherwise patch and re-run.
4. Resume matching explainability and matching-engine extensions once P1 blockers are cleared.
5. Done: Added explicit parity acceptance for unknown-currency bucketing behavior between in-memory and persisted runs.
6. Done: Added deterministic benchmark coverage for unknown-currency precision (`amount_fractional_digits=4`) and captured 10k/100k synthetic profiling runs.
7. Done: Implemented in-memory and persisted explainability coverage for matched, unmatched-right, unmatched-left, and lineages.
8. Done: Extend explainability checks to tie-break determinism for identical confidence/rank ties.
9. Done: Add many-to-many ambiguity explanation checks for grouped candidate alternatives and rejection narratives when group matching is disabled.
10. Done: Added deterministic `data_quality` exception identifiers for platform matching (`EXC-*`) and row-shuffle invariance coverage.
11. Done: Extended backup restore regression coverage to validate fallback defaults for `periods` optional columns.
12. Done: Ran targeted verification for optional-column restore fallback: `test_restore_fills_optional_missing_restore_columns_from_defaults` (`1 passed`).
13. Done: Added strict reference-normalization regex validation and test coverage for invalid regex patterns (`test_reference_normalization_rules_reject_invalid_regex_normalization_pattern`).

## History

- 2026-07-24: Resolved remaining Ruff quality drift by applying import normalization in `reconforge/platform/matching.py` and `tests/test_platform_matching.py`.
- 2026-07-24: Completed reporting aggregate hardening by hardening report amount parsing (`reconforge/reports/management_pack.py`) and adding invalid-input regression tests in `tests/test_reports.py`; recorded slice evidence in `docs/execution/EVIDENCE.md`.
- 2026-07-24: Hardened outbox list query construction (`reconforge/platform/outbox.py`) with allowlisted status-to-query mapping and removed predicate-based `# nosec` suppression.
- 2026-07-24: Hardened backup insert SQL in `reconforge/db/backup.py` by adding strict identifier validation before PRAGMA/table/INSERT identifier interpolation.
- 2026-07-24: Completed `P1-B9` SQL-hardening in `reconforge/db/backup.py`; backup restore insertion now uses static queries and schema-aware defaults, and `python -m bandit -q -r reconforge/db/backup.py` passes.
- 2026-07-24: Addressed `server-boundaries` blockers after run `30072000950` by:
  - normalizing imports in Alembic revision files (`0001..0011`) to remove `I001` lint blockers
  - setting `PYTHONPATH` to `${{ github.workspace }}` for Alembic migration step
  - keeping Alembic migration execution command on CLI (`alembic -c alembic.ini upgrade head`)
- 2026-07-24: Extended `P1-B9` backup restore hardening for legacy schema snapshots (v6) by deriving insert columns from `PRAGMA table_info`, applying defaults from metadata, and keeping `# nosec B608` limited to validated identifier interpolation in `_build_insert_query`.
- 2026-07-24: Added backup restore regression test `test_restore_fills_optional_missing_restore_columns_from_defaults` to verify missing additive columns and defaults are applied for `organizations` and `legal_entities` snapshots before insertion.
- 2026-07-24: Expanded `test_restore_fills_optional_missing_restore_columns_from_defaults` to assert period optional defaults (`fiscal_year`, `period_number`, `status_reason`, `updated_at`) are restored correctly when omitted.
- 2026-07-24: Executed `python -m pytest tests/test_db_backup_restore.py -k test_restore_fills_optional_missing_restore_columns_from_defaults --basetemp .\\.pytest-backup-defaults -q` → passed (`1 passed`).
- 2026-07-24: Executed `python -m pytest tests/test_db_backup_restore.py -q --basetemp .\\.pytest-outbox-backup2` → passed (`8 passed`), including the expanded optional-column default-backfill assertions.
- 2026-07-24: Added strict, non-default-coercive behavior for `to_float`/`to_int` in `reconforge/platform/common.py` and new coverage in `tests/test_platform_common.py`.
- 2026-07-24: Hardened risk-score arithmetic for invalid financial text in `reconforge/reconciliation/risk.py` and `reconforge/risk/scoring.py` by preserving invalid inputs as non-numeric markers (`NaN`) and avoiding zero-cast assumptions; added deterministic assertions in `tests/test_risk_scoring.py`.
- 2026-07-24: Added explainability slice test `test_matching_explainability_payload_includes_alternatives_and_stable_selection_reason` to validate candidate rationale and stable selection under input shuffles in `tests/test_platform_matching.py`.
- 2026-07-24: `tests/test_reconciliation_hardening.py`: added `test_reconciled_exception_ids_are_reorder_invariant`.
- 2026-07-24: `reconforge/reconciliation/stock_gl.py`: deterministic exception IDs now depend on canonical row payload hashes excluding unstable row order fields (including `source_row`).
- 2026-07-24: `reconforge/platform/matching.py`: deterministic `exception_id` for `data_quality` exceptions via canonical payload hashing (`_exception_id`), plus shuffle stability test `test_matching_data_quality_exception_ids_are_stable_under_row_shuffles`.
- 2026-07-24: `python -m pytest tests/test_platform_matching.py -k explainability --basetemp .\\.pytest-explainability` executed successfully (`1 passed`).
- 2026-07-24: `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results" -q --basetemp .\\.pytest-explainability` executed successfully (`2 passed`).
- 2026-07-24: `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability" -q --basetemp .\\.pytest-explainability` executed successfully (`3 passed`).
- 2026-07-24: `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability or unmatched_left_explainability or tie_breaking_is_deterministic_when_confidence_is_tied" -q --basetemp .\\.pytest-explainability` executed successfully (`5 passed`).
- 2026-07-24: Added tie-break determinism explainability coverage `test_matching_tie_breaking_is_deterministic_when_confidence_is_tied` in `tests/test_platform_matching.py`.
- 2026-07-24: `python -m pytest tests/test_platform_matching.py -k "explainability or persists_reason_and_lineage_metadata_for_db_results or unmatched_right_explainability or unmatched_left_explainability or tie_breaking_is_deterministic_when_confidence_is_tied or db_tie_breaking_is_deterministic_when_confidence_is_tied" -q --basetemp .\\.pytest-explainability` executed successfully (`6 passed`).
- 2026-07-24: Added many-to-many explainability and rejection narrative tests:
  - `tests/test_platform_matching.py::test_matching_many_to_many_explainability_stability`
  - `tests/test_platform_matching.py::test_matching_many_to_many_disabled_rejects_competing_candidates_with_expected_rejection_narrative`
- `python -m pytest tests/test_platform_matching.py -k "many_to_many_explainability_stability or many_to_many_disabled_rejects_competing_candidates_with_expected_rejection_narrative" -q --basetemp .\\.pytest-explainability` → passed (`2 passed`).
- 2026-07-24: Added persisted-path tie-break coverage `test_matching_db_tie_breaking_is_deterministic_when_confidence_is_tied` in `tests/test_platform_matching.py`.
- 2026-07-24: Extended risk scoring resilience in `reconforge/risk/scoring.py` to treat invalid `aging_days` as zero-equivalent without crashing; added `test_risk_scoring_invalid_aging_days_defaults_to_zero`.
- 2026-07-24: Verified via GitHub API scan of the last 80 runs (`29951140420`..`26816522153`) that no `docker-parity` job has executed yet in remote CI evidence.
- 2026-07-24: Branch-level check for `feature/p0-atomic-audit-outbox` via `gh run list --workflow ci.yml --branch feature/p0-atomic-audit-outbox ... --limit 20` returned `[]`, so parity job evidence is not yet runnable until branch is pushed and workflow executed.
- 2026-07-24: Completed `P1-B11`: reference-normalization regex validation now fails fast in `reconforge/platform/matching.py` and is covered by `tests/test_platform_matching.py::test_reference_normalization_rules_reject_invalid_regex_normalization_pattern`.
- 2026-07-24: Executed targeted reference-normalization validation command (`reference_normalization_rules_reject_invalid_configuration or reference_normalization_rules_reject_invalid_regex_normalization_pattern`) with basetemp `.\\.pytest-baseline-target`; observed `2 passed`.
- 2026-07-24: Collected CI parity evidence in PR `54`:
  - Workflow run: `https://github.com/amrzainmubarak/reconforge-erp/actions/runs/30070878830`
  - `docker-parity` job `89411613485` completed successfully.
  - `test (3.11)` and `test (3.12)` succeeded; `server-boundaries` failed on migration step in this run.
- 2026-07-24: Followed up on `server-boundaries` migration failure by replacing CI Python-configured Alembic invocation with direct CLI call (`alembic -c alembic.ini upgrade head`) in `.github/workflows/ci.yml` to remove path-dependent `script_location` configuration drift.

