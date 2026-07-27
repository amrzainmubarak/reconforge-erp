"""Generic CSV connector adapter."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from reconforge.io.readers import normalize_columns, read_table


class GenericCSVConnector:
    """Connector for already-exported CSV folders."""

    name = "generic_csv"

    def load_data(self, input_path: Path) -> dict[str, pd.DataFrame]:
        return {
            path.stem: normalize_columns(read_table(path))
            for path in sorted(input_path.glob("*.csv"))
        }

    def validate_schema(self, datasets: dict[str, pd.DataFrame]) -> list[str]:
        return [] if datasets else ["No CSV datasets found."]

    def normalize_columns(self, frame: pd.DataFrame) -> pd.DataFrame:
        return normalize_columns(frame)

    def map_accounts(self, datasets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        return datasets

    def export_results(self, datasets: dict[str, pd.DataFrame], output_path: Path) -> list[Path]:
        output_path.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for name, frame in datasets.items():
            path = output_path / f"{name}.csv"
            frame.to_csv(path, index=False)
            paths.append(path)
        return paths
