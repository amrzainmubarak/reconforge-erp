from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from reconforge.config import ReconForgeConfig
from reconforge.io.readers import read_required_datasets
from reconforge.schemas import DatasetName


@pytest.fixture()
def sample_dir() -> Path:
    return Path("examples/sample_data")


@pytest.fixture()
def config() -> ReconForgeConfig:
    return ReconForgeConfig()


@pytest.fixture()
def sample_datasets(sample_dir: Path) -> dict[DatasetName, pd.DataFrame]:
    return read_required_datasets(
        sample_dir,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.PRODUCTS,
            DatasetName.CUSTOMERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
