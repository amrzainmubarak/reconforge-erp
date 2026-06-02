"""Processing engine registry."""

from __future__ import annotations

from reconforge.engines.base import ReconciliationEngine


def get_engine(name: str) -> ReconciliationEngine:
    """Return a reconciliation engine by name."""

    normalized = name.lower()
    if normalized == "pandas":
        from reconforge.engines.pandas_engine import PandasEngine

        return PandasEngine()
    if normalized == "duckdb":
        from reconforge.engines.duckdb_engine import DuckDBEngine

        return DuckDBEngine()
    raise ValueError(f"Unsupported engine '{name}'. Supported engines: pandas, duckdb")


def list_engines() -> list[str]:
    """Return registered engine names."""

    return ["pandas", "duckdb"]
