from __future__ import annotations

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.schemas import DatasetName


def test_exact_match_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    exact = result.matched_transactions[result.matched_transactions["match_level"].eq("Level 1 Exact")]
    assert "STK-ISS-1001" in set(exact["source_document"])


def test_fuzzy_reference_match_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    fuzzy = result.matched_transactions[result.matched_transactions["match_level"].eq("Level 2 Fuzzy Reference")]
    assert "STK-ISS-1002" in set(fuzzy["source_document"])


def test_proximity_match_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    proximity = result.matched_transactions[result.matched_transactions["match_level"].eq("Level 3 Amount/Date Proximity")]
    assert "STK-ISS-1004" in set(proximity["source_document"])


def test_unmatched_stock_movement_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    assert "STK-ISS-1005" in set(result.stock_without_gl["source_document"])


def test_unmatched_gl_entry_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    assert "MANUAL-ADJ-778" in set(result.gl_without_stock["reference"])


def test_value_difference_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    assert "STK-ISS-1003" in set(result.value_differences["source_document"])
    row = result.value_differences[result.value_differences["source_document"].eq("STK-ISS-1003")].iloc[0]
    assert row["value_difference"] == 10.0


def test_reference_mismatch_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    assert "STK-ISS-1004" in set(result.reference_mismatches["source_document"])
