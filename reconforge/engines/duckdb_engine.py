"""Optional DuckDB reconciliation backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.engines.base import EngineResult
from reconforge.engines.signature import build_reconciliation_signature
from reconforge.io.readers import coerce_dataset_types, find_dataset_file, read_table
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.schemas import DatasetName


class DuckDBEngine:
    """DuckDB-backed local export reader with shared reconciliation semantics.

    CSV scans execute inside DuckDB. Canonical type coercion and deterministic
    global assignment are shared with the default engine so both backends
    produce the same financial decisions. The current implementation is
    intentionally in-memory and does not claim end-to-end streaming.
    """

    name = "duckdb"

    def run(self, input_dir: Path, config: ReconForgeConfig) -> EngineResult:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB engine requires optional dependency. Install with pip install reconforge-erp[duckdb].",
            ) from exc
        try:
            connection = duckdb.connect(database=":memory:")
            stock = self._read_dataset(connection, input_dir, DatasetName.STOCK_MOVES)
            gl = self._read_dataset(connection, input_dir, DatasetName.GL_ENTRIES)
        except (duckdb.Error, OSError, ValueError) as exc:
            raise RuntimeError("DuckDB could not read the required local reconciliation exports.") from exc
        finally:
            if "connection" in locals():
                connection.close()

        result = reconcile_stock_gl(stock, gl, config)
        return EngineResult(
            engine=self.name,
            matched_rows=len(result.matched_transactions),
            exception_rows=len(result.all_exceptions),
            stock_rows=len(stock),
            gl_rows=len(gl),
            summary=result.summary.copy(),
            reconciliation_signature=build_reconciliation_signature(
                matched_transactions=result.matched_transactions,
                all_exceptions=result.all_exceptions,
            ),
        )

    @staticmethod
    def _read_dataset(connection: Any, input_dir: Path, dataset: DatasetName) -> pd.DataFrame:
        path = find_dataset_file(input_dir, dataset)
        if path is None:
            raise ValueError(f"Missing required local export: {dataset.value}")
        if path.suffix.lower() == ".csv":
            raw = connection.execute(
                "SELECT * FROM read_csv_auto(?, header = true, all_varchar = true, sample_size = -1)",
                [str(path.resolve())],
            ).fetch_df()
        else:
            registered_name = f"input_{dataset.value}"
            connection.register(registered_name, read_table(path))
            raw = connection.execute(f'SELECT * FROM "{registered_name}"').fetch_df()
            connection.unregister(registered_name)
        return coerce_dataset_types(raw, dataset)
