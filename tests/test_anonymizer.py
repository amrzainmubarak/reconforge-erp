from __future__ import annotations

from pathlib import Path

import pandas as pd

from reconforge.anonymizer.engine import anonymize_directory
from reconforge.config import ReconForgeConfig
from reconforge.io.readers import read_required_datasets
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.schemas import DatasetName


def test_same_original_value_maps_to_same_masked_value(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, seed=42)
    stock = pd.read_csv(output / "stock_moves.csv")
    invoices = pd.read_csv(output / "invoices.csv")
    masked = stock.loc[stock["move_id"].eq("SM-0001"), "work_order"].iloc[0]
    assert masked in set(invoices["work_order"])


def test_different_values_map_to_different_masked_values(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, seed=42)
    customers = pd.read_csv(output / "customers.csv")
    assert customers["customer_code"].nunique() == len(customers)


def test_matching_still_works_after_anonymization(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, seed=42)
    datasets = read_required_datasets(output, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    result = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], ReconForgeConfig())
    assert len(result.matched_transactions) > 0


def test_optional_amount_masking_works(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, mask_amounts=True, seed=42)
    original = pd.read_csv("examples/sample_data/stock_moves.csv")
    masked = pd.read_csv(output / "stock_moves.csv")
    assert not original["total_cost"].equals(masked["total_cost"])


def test_date_shifting_works(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, seed=42, date_shift_days=30)
    original = pd.to_datetime(pd.read_csv("examples/sample_data/stock_moves.csv")["date"]).iloc[0]
    shifted = pd.to_datetime(pd.read_csv(output / "stock_moves.csv")["date"]).iloc[0]
    assert (shifted - original).days == 30
