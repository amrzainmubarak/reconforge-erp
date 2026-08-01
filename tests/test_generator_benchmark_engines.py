from __future__ import annotations

import hashlib
import importlib.util
import json
import random
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from reconforge.benchmark.reconciliation_execution import (
    ReconciliationExecutionBenchmarkProfile,
    _synthetic_records,
    assert_reconciliation_execution_regression,
    run_reconciliation_execution_benchmark,
    run_reconciliation_execution_benchmark_suite,
    run_reconciliation_execution_streaming_benchmark,
)
from reconforge.benchmark.runner import run_benchmark
from reconforge.config import ReconForgeConfig
from reconforge.engines.base import get_engine
from reconforge.engines.duckdb_engine import DuckDBEngine
from reconforge.engines.pandas_engine import PandasEngine
from reconforge.generator.synthetic import generate_synthetic_dataset, verify_synthetic_manifest
from reconforge.io.readers import read_required_datasets
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.schemas import REQUIRED_COLUMNS, DatasetName
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    LegacyFinancialInputWarning,
)
from reconforge.validators import validate_input_directory
from reconforge.workers.postgres_reconciliation import LocalDeterministicMatcherAdapter, ReconciliationExecutionContext


def _run_adapter_with_records(
    left_records: list[dict[str, object]],
    right_records: list[dict[str, object]],
    *,
    partition_max_records: int = 10_000,
) -> tuple[str, int, int, int, int]:
    adapter = LocalDeterministicMatcherAdapter()
    try:
        output = adapter(
            ReconciliationExecutionContext(
                run={
                    "rule_json": {
                        "partition_fields": ["entity_id"],
                        "partition_max_records": int(partition_max_records),
                        "amount_tolerance": "0",
                    }
                },
                left_inputs=tuple(left_records),
                right_inputs=tuple(right_records),
                heartbeat=lambda _: {},
                cancellation_requested=lambda: False,
            )
        )
    finally:
        adapter.close()
    payload = {"results": list(output.results), "exceptions": list(output.exceptions)}
    signature = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return (
        hashlib.sha256(signature.encode("utf-8")).hexdigest(),
        len(output.results),
        len(output.exceptions),
        len(left_records),
        len(right_records),
    )



def test_generated_files_exist(tmp_path: Path) -> None:
    paths = generate_synthetic_dataset(120, tmp_path / "synthetic", seed=7)
    assert len(paths) == 8
    assert (tmp_path / "synthetic" / "stock_moves.csv").exists()


def test_generated_schema_valid(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(100, target, seed=7)
    datasets = read_required_datasets(target, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    assert set(REQUIRED_COLUMNS[DatasetName.STOCK_MOVES]).issubset(datasets[DatasetName.STOCK_MOVES].columns)
    issues = validate_input_directory(target)
    assert not [issue for issue in issues if issue.severity == "error"]


def test_exact_synthetic_manifest_is_reproducible_and_currency_scoped_under_hostile_context(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    with localcontext() as context:
        context.prec = 4
        generate_synthetic_dataset(
            40,
            first,
            exception_rate="0.100000000000000005",
            critical_rate="0.025",
            currency="KWD",
            seed=712,
        )
    generate_synthetic_dataset(
        40,
        second,
        exception_rate="0.100000000000000005",
        critical_rate="0.025",
        currency="KWD",
        seed=712,
    )

    first_manifest = json.loads((first / "synthetic_manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "synthetic_manifest.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/synthetic_generator_manifest.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(first_manifest)
    verify_synthetic_manifest(first_manifest, output_dir=first)

    assert first_manifest == second_manifest
    assert first_manifest["schema_version"] == 2
    assert first_manifest["policy"]["algorithm_version"] == "exact-decimal-v1"
    assert first_manifest["policy"]["exception_rate"] == "0.100000000000000005"
    assert first_manifest["policy"]["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert first_manifest["policy"]["currency_policy"]["currency"] == "KWD"
    assert first_manifest["policy"]["currency_policy"]["minor_units"] == 3
    for item in first_manifest["output_files"]:
        assert (first / item["name"]).read_bytes() == (second / item["name"]).read_bytes()

    monetary_columns = {
        "products.csv": ["standard_cost"],
        "work_orders.csv": ["estimated_cost", "actual_cost"],
        "stock_moves.csv": ["unit_cost", "total_cost"],
        "gl_entries.csv": ["debit", "credit", "amount"],
        "purchase_orders.csv": ["unit_price", "total_price"],
        "invoices.csv": ["invoice_amount"],
    }
    for filename, columns in monetary_columns.items():
        frame = pd.read_csv(first / filename, dtype=str, keep_default_na=False)
        assert set(frame["currency"]) == {"KWD"}
        for column in columns:
            assert all(-int(Decimal(value).as_tuple().exponent) <= 3 for value in frame[column] if value)
    assert any(
        int(Decimal(value).as_tuple().exponent) == -3
        for value in pd.read_csv(first / "stock_moves.csv", dtype=str)["total_cost"]
    )


def test_exact_synthetic_generator_honors_zero_minor_unit_currency(tmp_path: Path) -> None:
    target = tmp_path / "jpy"
    generate_synthetic_dataset(12, target, currency="JPY", seed=713)

    for filename, column in (
        ("products.csv", "standard_cost"),
        ("work_orders.csv", "actual_cost"),
        ("stock_moves.csv", "total_cost"),
        ("gl_entries.csv", "amount"),
        ("purchase_orders.csv", "total_price"),
        ("invoices.csv", "invoice_amount"),
    ):
        frame = pd.read_csv(target / filename, dtype=str, keep_default_na=False)
        assert set(frame["currency"]) == {"JPY"}
        assert all(Decimal(value) == Decimal(value).to_integral_value() for value in frame[column] if value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exception_rate", "-0.01"),
        ("exception_rate", "1.01"),
        ("exception_rate", "1e-2"),
        ("exception_rate", "NaN"),
        ("exception_rate", True),
        ("critical_rate", "Infinity"),
    ],
)
def test_synthetic_generator_rejects_invalid_exact_policy_before_output(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    target = tmp_path / f"invalid-{field}"
    kwargs: dict[str, object] = {field: value}

    with pytest.raises(ValueError, match=field):
        generate_synthetic_dataset(10, target, **kwargs)  # type: ignore[arg-type]

    assert not target.exists()


def test_synthetic_manifest_detects_policy_and_output_tampering(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(20, target, seed=89)
    manifest = json.loads((target / "synthetic_manifest.json").read_text(encoding="utf-8"))

    tampered = deepcopy(manifest)
    tampered["policy"]["exception_rate"] = "0.9"
    with pytest.raises(ValueError, match="policy digest"):
        verify_synthetic_manifest(tampered)

    policy_tamper = deepcopy(manifest)
    policy_tamper["policy"]["financial_input_policy"] = LEGACY_FINANCIAL_INPUT_POLICY
    with pytest.raises(ValueError, match="policy digest"):
        verify_synthetic_manifest(policy_tamper)

    unsupported_policy = deepcopy(manifest)
    unsupported_policy["policy"]["financial_input_policy"] = "unknown-v9"
    with pytest.raises(ValueError, match="financial input policy is unsupported"):
        verify_synthetic_manifest(unsupported_policy)

    output_path = target / "stock_moves.csv"
    output_path.write_bytes(output_path.read_bytes() + b"tampered\n")
    with pytest.raises(ValueError, match="output file verification"):
        verify_synthetic_manifest(manifest, output_dir=target)


def test_synthetic_manifest_accepts_fixed_historical_v1_and_rejects_cross_version_policy() -> None:
    empty_digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    names = [
        "customers.csv",
        "gl_entries.csv",
        "invoices.csv",
        "old_parts_returns.csv",
        "products.csv",
        "purchase_orders.csv",
        "stock_moves.csv",
        "work_orders.csv",
    ]
    payload = {
        "schema_version": 1,
        "policy": {
            "algorithm_version": "exact-decimal-v1",
            "amount_random_scale": 6,
            "critical_rate": "0.05",
            "currency_policy": {
                "currency": "USD",
                "currency_policy_digest": "ec6c68cdfe753c874b177800cdb4e4d2ffa5492803436ddc6068a11f02b38b32",
                "currency_registry_digest": "d78f817456f78fa3dedf39dc3de2f8554f79e08c65d463ab1a60a36b3850b246",
                "currency_registry_version": "iso-4217-list-one-2026-01-01-rf1",
                "minor_units": 2,
                "rounding_policy": "ROUND_HALF_UP",
            },
            "exception_rate": "0.15",
            "industry": "workshop",
            "rows": 1,
            "seed": 42,
        },
        "policy_digest": "5200f2fff6d3ce11a09868c277d4d82ed64aa10e0672869a80dfad5cf5376118",
        "output_files": [{"bytes": 0, "name": name, "sha256": empty_digest} for name in names],
        "manifest_digest": "c00cd13fd2cced5d6f515cf2c95d0e7f65e20708ad427fd4b7db1a67b6c90a36",
    }
    schema = json.loads(Path("docs/schemas/synthetic_generator_manifest.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    validator.validate(payload)
    assert verify_synthetic_manifest(payload) == payload

    missing_current_policy = deepcopy(payload)
    missing_current_policy["schema_version"] = 2
    assert list(validator.iter_errors(missing_current_policy))
    with pytest.raises(ValueError, match="policy is unsupported"):
        verify_synthetic_manifest(missing_current_policy)

    legacy_with_future_policy = deepcopy(payload)
    legacy_with_future_policy["policy"]["financial_input_policy"] = LEGACY_FINANCIAL_INPUT_POLICY
    assert list(validator.iter_errors(legacy_with_future_policy))
    with pytest.raises(ValueError, match="policy is unsupported"):
        verify_synthetic_manifest(legacy_with_future_policy)


def test_synthetic_service_records_legacy_float_and_strict_rejects_before_output(tmp_path: Path) -> None:
    legacy_target = tmp_path / "legacy-float"
    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        generate_synthetic_dataset(
            20,
            legacy_target,
            exception_rate=0.2,
            seed=9,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )

    manifest = json.loads((legacy_target / "synthetic_manifest.json").read_text(encoding="utf-8"))
    assert manifest["policy"]["exception_rate"] == "0.2"
    assert manifest["policy"]["financial_input_policy"] == LEGACY_FINANCIAL_INPUT_POLICY

    strict_exact_target = tmp_path / "strict-exact"
    strict_paths = generate_synthetic_dataset(
        20,
        strict_exact_target,
        exception_rate="0.2",
        seed=9,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    strict_manifest = json.loads((strict_exact_target / "synthetic_manifest.json").read_text(encoding="utf-8"))
    assert strict_manifest["policy"]["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    for strict_path in strict_paths:
        assert strict_path.read_bytes() == (legacy_target / strict_path.name).read_bytes()

    strict_target = tmp_path / "strict-float"
    with pytest.raises(ValueError, match="plain decimal"):
        generate_synthetic_dataset(
            20,
            strict_target,
            exception_rate=0.2,
            seed=9,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    assert not strict_target.exists()


def test_generated_exception_rate_roughly_respected(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(200, target, exception_rate="0.2", seed=9)
    datasets = read_required_datasets(target, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    result = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], ReconForgeConfig())
    assert len(result.all_exceptions) / len(datasets[DatasetName.STOCK_MOVES]) >= 0.05


def test_generated_data_can_be_reconciled(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(80, target, seed=3)
    datasets = read_required_datasets(target, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    result = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], ReconForgeConfig())
    assert len(result.summary) == 6


def test_benchmark_runs_on_small_dataset(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(60, target, seed=5)
    metrics = run_benchmark(target, tmp_path / "benchmark", engine_name="pandas")
    assert metrics.engine_used == "pandas"
    assert metrics.number_of_stock_rows == 60


def test_benchmark_outputs_valid_json(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(50, target, seed=6)
    run_benchmark(target, tmp_path / "benchmark", engine_name="pandas")
    payload = json.loads((tmp_path / "benchmark" / "benchmark.json").read_text(encoding="utf-8"))
    assert payload["engine_used"] == "pandas"


def test_partitioned_reconciliation_execution_benchmark_is_reproducible(tmp_path: Path) -> None:
    first = run_reconciliation_execution_benchmark(100, partition_count=4, output_dir=tmp_path / "execution")
    second = run_reconciliation_execution_benchmark(100, partition_count=4)

    assert first.result_signature == second.result_signature
    assert first.left_rows == 50
    assert first.right_rows == 50
    assert first.matched_rows == 50
    assert first.exception_count == 0
    assert (tmp_path / "execution" / "reconciliation-execution.json").exists()
    assert (tmp_path / "execution" / "reconciliation-execution.md").exists()


def test_reconciliation_execution_benchmark_supports_unknown_currency_precision_and_reproducibility(tmp_path: Path) -> None:
    first = run_reconciliation_execution_benchmark(
        120,
        partition_count=4,
        amount_fractional_digits=4,
        output_dir=tmp_path / "execution_precision",
    )
    second = run_reconciliation_execution_benchmark(
        120,
        partition_count=4,
        amount_fractional_digits=4,
    )
    payload = json.loads((tmp_path / "execution_precision" / "reconciliation-execution.json").read_text(encoding="utf-8"))

    assert first.result_signature == second.result_signature
    assert first.left_rows == 60
    assert first.right_rows == 60
    assert first.matched_rows == 60
    assert first.exception_count == 0
    assert first.amount_fractional_digits == 4
    assert payload["amount_fractional_digits"] == 4
    assert (tmp_path / "execution_precision" / "reconciliation-execution.md").exists()


def test_streaming_reconciliation_execution_benchmark_is_reproducible(tmp_path: Path) -> None:
    first = run_reconciliation_execution_streaming_benchmark(200, partition_count=10, output_dir=tmp_path / "streaming")
    second = run_reconciliation_execution_streaming_benchmark(200, partition_count=10)
    different_seed = run_reconciliation_execution_streaming_benchmark(200, partition_count=10, seed=8)

    assert first.result_signature == second.result_signature
    assert first.result_signature != different_seed.result_signature
    assert first.engine_used == "local-deterministic-partitioned-streaming"
    assert first.matched_rows == 100
    assert first.exception_count == 0
    assert (tmp_path / "streaming" / "reconciliation-execution.json").exists()


def test_reconciliation_execution_benchmark_suite_writes_manifest_and_file_digests(tmp_path: Path) -> None:
    profiles = (
        ReconciliationExecutionBenchmarkProfile(
            profile_id="suite-single",
            total_records=220,
            partition_count=4,
            seed=7,
        ),
        ReconciliationExecutionBenchmarkProfile(
            profile_id="suite-single-stream",
            total_records=260,
            partition_count=5,
            streaming=True,
            seed=7,
        ),
    )
    suite = run_reconciliation_execution_benchmark_suite(profiles, output_dir=tmp_path / "execution-suite")

    assert suite.suite_signature
    assert suite.output_dir is not None
    manifest_path = tmp_path / "execution-suite" / "reconciliation-execution-benchmark-suite.json"
    manifest_bytes = manifest_path.read_bytes()
    assert manifest_bytes.endswith(b"}\n")
    assert b"\r\n" not in manifest_bytes
    manifest = json.loads(manifest_bytes)
    assert manifest["suite_signature"] == suite.suite_signature
    assert manifest["profile_count"] == 2
    assert len(manifest["profiles"]) == 2
    assert len(suite.profiles) == 2
    for profile in suite.profiles:
        assert "\\" not in profile.output_json
        output_path = Path(suite.output_dir) / profile.output_json
        assert output_path.exists()
        output_bytes = output_path.read_bytes()
        assert output_bytes.endswith(b"}\n")
        assert b"\r\n" not in output_bytes
        digest = hashlib.sha256(output_bytes).hexdigest()
        assert profile.output_json_sha256 == digest

    summary_lines = (
        tmp_path / "execution-suite" / "reconciliation-execution-benchmark-suite.md"
    ).read_text(encoding="utf-8").splitlines()
    assert summary_lines[:4] == [
        "# Reconciliation Execution Benchmark Suite",
        "",
        "| Profile | Signature | Runtime (s) | Peak MB | Candidate max | Candidate count total |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    assert len(summary_lines) == 6


def test_reconciliation_execution_regression_gate_detects_signature_and_runtime_delta() -> None:
    baseline = run_reconciliation_execution_benchmark(
        160,
        partition_count=4,
        output_dir=None,
    )
    assert_reconciliation_execution_regression(
        baseline={"single": baseline},
        candidate={"single": baseline},
    )

    signature_mutation = replace(
        baseline,
        result_signature="0" * 64,
    )
    with pytest.raises(AssertionError, match="result_signature changed"):
        assert_reconciliation_execution_regression(
            baseline={"single": baseline},
            candidate={"single": signature_mutation},
        )

    runtime_mutation = replace(
        baseline,
        runtime_seconds=baseline.runtime_seconds * 100.0,
    )
    with pytest.raises(AssertionError, match="runtime regression ratio"):
        assert_reconciliation_execution_regression(
            baseline={"single": baseline},
            candidate={"single": runtime_mutation},
            max_runtime_regression_ratio=1.1,
        )


def test_reconciliation_execution_benchmark_is_row_order_invariant() -> None:
    left_records, right_records = _synthetic_records(total_records=200, partition_count=10, seed=7)

    left_shuffled = left_records[:]
    right_shuffled = right_records[:]
    random.Random(7).shuffle(left_shuffled)
    random.Random(11).shuffle(right_shuffled)

    base_signature, base_result_count, base_exception_count, base_left, base_right = _run_adapter_with_records(
        left_records,
        right_records,
    )
    shuffled_signature, shuffled_result_count, shuffled_exception_count, shuffled_left, shuffled_right = _run_adapter_with_records(
        left_shuffled,
        right_shuffled,
    )

    assert base_signature == shuffled_signature
    assert base_result_count == shuffled_result_count
    assert base_exception_count == shuffled_exception_count
    assert base_left == shuffled_left == 100
    assert base_right == shuffled_right == 100


def test_unsupported_engine_error() -> None:
    with pytest.raises(ValueError):
        get_engine("spark")


def test_pandas_engine_works(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(40, target, seed=10)
    result = get_engine("pandas").run(target, ReconForgeConfig())
    assert result.stock_rows == 40
    assert result.financial_input_policy == "strict-financial-input-v2"


def test_duckdb_graceful_missing_dependency(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(40, target, seed=11)
    if importlib.util.find_spec("duckdb") is None:
        with pytest.raises(RuntimeError, match="DuckDB engine requires optional dependency"):
            DuckDBEngine().run(target, ReconForgeConfig())
    else:
        assert DuckDBEngine().run(target, ReconForgeConfig()).engine == "duckdb"


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="optional DuckDB dependency is not installed")
def test_duckdb_executes_without_delegating_to_pandas_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(40, target, seed=12)

    def fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("DuckDBEngine delegated execution to PandasEngine")

    monkeypatch.setattr(PandasEngine, "run", fail_if_called)

    result = DuckDBEngine().run(target, ReconForgeConfig())

    assert result.engine == "duckdb"
    assert result.stock_rows == 40


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="optional DuckDB dependency is not installed")
def test_duckdb_and_pandas_engines_make_equivalent_reconciliation_decisions(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(75, target, seed=14)

    pandas_result = PandasEngine().run(target, ReconForgeConfig())
    duckdb_result = DuckDBEngine().run(target, ReconForgeConfig())

    assert duckdb_result.matched_rows == pandas_result.matched_rows
    assert duckdb_result.exception_rows == pandas_result.exception_rows
    assert duckdb_result.summary.to_dict(orient="records") == pandas_result.summary.to_dict(orient="records")
    assert duckdb_result.reconciliation_signature
    assert pandas_result.reconciliation_signature
    assert duckdb_result.reconciliation_signature_version == "reconciliation-signature-v3"
    assert pandas_result.reconciliation_signature_version == "reconciliation-signature-v3"
    assert duckdb_result.financial_input_policy == "strict-financial-input-v2"
    assert pandas_result.financial_input_policy == "strict-financial-input-v2"
    assert duckdb_result.record_identity_policy == "canonical-multiset-occurrence-v1"
    assert pandas_result.record_identity_policy == "canonical-multiset-occurrence-v1"
    assert duckdb_result.reconciliation_signature == pandas_result.reconciliation_signature


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="optional DuckDB dependency is not installed")
def test_duckdb_partition_path_matches_pandas_for_large_scan_forced_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(500, target, seed=15)

    calls = {"partitions": 0}
    original_read_partition_records = DuckDBEngine._read_partition_records

    def read_partition_records_with_count(*args: object, **kwargs: object):
        calls["partitions"] += 1
        return original_read_partition_records(*args, **kwargs)  # type: ignore[misc]

    monkeypatch.setattr(DuckDBEngine, "_FULL_SCAN_ROW_LIMIT", 1)
    monkeypatch.setattr(
        DuckDBEngine,
        "_read_partition_records",
        staticmethod(read_partition_records_with_count),
    )

    pandas_result = PandasEngine().run(target, ReconForgeConfig())
    duckdb_result = DuckDBEngine().run(target, ReconForgeConfig())

    # Two-sided partitioned replay should read both inputs per partition.
    assert calls["partitions"] >= 4
    assert duckdb_result.reconciliation_signature == pandas_result.reconciliation_signature
    assert duckdb_result.stock_rows == pandas_result.stock_rows
    assert duckdb_result.gl_rows == pandas_result.gl_rows
    assert {
        metric["metric"]: int(metric["count"])
        for metric in duckdb_result.summary.to_dict(orient="records")
    } == {
        metric["metric"]: int(metric["count"])
        for metric in pandas_result.summary.to_dict(orient="records")
    }
    assert duckdb_result.exception_rows == pandas_result.exception_rows


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="optional DuckDB dependency is not installed")
def test_duckdb_partitioned_execution_is_row_order_invariant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "synthetic"
    shuffled = tmp_path / "synthetic_shuffled"
    generate_synthetic_dataset(500, target, seed=18)
    generate_synthetic_dataset(500, shuffled, seed=18)

    for filename in ("stock_moves.csv", "gl_entries.csv"):
        frame = pd.read_csv(shuffled / filename)
        frame.sample(frac=1, random_state=17).to_csv(shuffled / filename, index=False)

    monkeypatch.setattr(DuckDBEngine, "_FULL_SCAN_ROW_LIMIT", 1)
    result_original = DuckDBEngine().run(target, ReconForgeConfig())
    result_shuffled = DuckDBEngine().run(shuffled, ReconForgeConfig())

    assert result_original.reconciliation_signature == result_shuffled.reconciliation_signature
    assert result_original.stock_rows == result_shuffled.stock_rows
    assert result_original.gl_rows == result_shuffled.gl_rows
    assert {
        metric["metric"]: int(metric["count"])
        for metric in result_original.summary.to_dict(orient="records")
    } == {
        metric["metric"]: int(metric["count"])
        for metric in result_shuffled.summary.to_dict(orient="records")
    }
    assert result_original.exception_rows == result_shuffled.exception_rows
    assert result_original.matched_rows == result_shuffled.matched_rows


def test_duckdb_partition_size_uses_exact_integer_ceiling() -> None:
    assert DuckDBEngine._work_order_partition_size(total_records=3_000, work_order_count=6) == 1
    assert DuckDBEngine._work_order_partition_size(total_records=2_999, work_order_count=6) == 2

    work_order_count = 10**18 + 3
    total_records = (DuckDBEngine._WORK_ORDER_TARGET_PARTITION_ROWS * work_order_count) // 7
    assert DuckDBEngine._work_order_partition_size(total_records, work_order_count) == 8


@pytest.mark.skipif(importlib.util.find_spec("duckdb") is None, reason="optional DuckDB dependency is not installed")
def test_duckdb_relation_streaming_yields_bounded_canonical_batches(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(23, target, seed=15)

    batches = list(DuckDBEngine().iter_dataset_batches(target, DatasetName.STOCK_MOVES, batch_size=7))

    assert sum(len(batch) for batch in batches) == 23
    assert all(len(batch) <= 7 for batch in batches)
    assert all("total_cost" in batch.columns for batch in batches)
