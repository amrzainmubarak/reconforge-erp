"""Compatibility interface for built-in local-file adapters and export profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd

from reconforge.connectors.manifest import ConnectorManifest


class ConnectorPlugin(Protocol):
    """Read-only source adapter plus local canonical-export compatibility interface."""

    name: str
    manifest: ConnectorManifest

    def load_data(self, input_path: Path) -> dict[str, pd.DataFrame]:
        """Load source data from a local path."""

    def validate_schema(self, datasets: dict[str, pd.DataFrame]) -> list[str]:
        """Return schema validation messages."""

    def normalize_columns(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Normalize source columns."""

    def map_accounts(self, datasets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
        """Map source accounts into ReconForge canonical fields."""

    def export_results(self, datasets: dict[str, pd.DataFrame], output_path: Path) -> list[Path]:
        """Export normalized canonical datasets."""
