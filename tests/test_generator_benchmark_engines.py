from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from reconforge.benchmark.runner import run_benchmark
from reconforge.config import ReconForgeConfig
from reconforge.engines.base import get_engine
from reconforge.engines.duckdb_engine import DuckDBEngine
from reconforge.engines.pandas_engine import PandasEngine
from reconforge.generator.synthetic import generate_synthetic_dataset
from reconforge.io.readers import read_required_datasets
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.schemas import REQUIRED_COLUMNS, DatasetName
from reconforge.validators import validate_input_directory


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


def test_generated_exception_rate_roughly_respected(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(200, target, exception_rate=0.2, seed=9)
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


def test_unsupported_engine_error() -> None:
    with pytest.raises(ValueError):
        get_engine("spark")


def test_pandas_engine_works(tmp_path: Path) -> None:
    target = tmp_path / "synthetic"
    generate_synthetic_dataset(40, target, seed=10)
    result = get_engine("pandas").run(target, ReconForgeConfig())
    assert result.stock_rows == 40


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
