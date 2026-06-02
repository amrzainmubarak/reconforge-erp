"""Optional DuckDB reconciliation backend."""

from __future__ import annotations

from pathlib import Path

from reconforge.config import ReconForgeConfig
from reconforge.engines.base import EngineResult
from reconforge.engines.pandas_engine import PandasEngine


class DuckDBEngine:
    """DuckDB-aware backend that validates the optional dependency before execution."""

    name = "duckdb"

    def run(self, input_dir: Path, config: ReconForgeConfig) -> EngineResult:
        try:
            import duckdb  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB engine requires optional dependency. Install with pip install reconforge-erp[duckdb].",
            ) from exc
        result = PandasEngine().run(input_dir, config)
        return EngineResult(
            engine=self.name,
            matched_rows=result.matched_rows,
            exception_rows=result.exception_rows,
            stock_rows=result.stock_rows,
            gl_rows=result.gl_rows,
            summary=result.summary,
        )
