"""Generic CSV connector adapter."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from reconforge.connectors.manifest import (
    AuthenticationMethod,
    ConnectorCapability,
    ConnectorKind,
    ConnectorManifest,
    DataClassification,
    RetryPolicy,
    SupportLevel,
)
from reconforge.io.readers import normalize_columns, read_table


class GenericCSVConnector:
    """Connector for already-exported CSV folders."""

    name = "generic_csv"
    manifest = ConnectorManifest(
        schema_version="connector-manifest-v1",
        connector_id="generic_csv",
        display_name="Generic CSV local-file adapter",
        version="1.0.0",
        kind=ConnectorKind.LOCAL_FILE,
        capabilities=frozenset({ConnectorCapability.READ}),
        authentication=AuthenticationMethod.NONE,
        network_required=False,
        data_classification=DataClassification.RESTRICTED,
        incremental_cursor=False,
        idempotent_reads=True,
        retry_policy=RetryPolicy(maximum_attempts=1, initial_delay_seconds=0, maximum_delay_seconds=0),
        schema_versions=("unversioned-csv-v1",),
        synthetic_sandbox=True,
        threat_model=("hostile-local-file", "path-boundary", "spreadsheet-formula-content"),
        secret_handling="No credentials accepted or stored.",  # nosec B106
        egress_destinations=(),
        support_level=SupportLevel.EXPERIMENTAL,
    )

    def load_data(self, input_path: Path) -> dict[str, pd.DataFrame]:
        return {path.stem: normalize_columns(read_table(path)) for path in sorted(input_path.glob("*.csv"))}

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
