"""Tests for the matching engine's unified Money/Currency behavior."""

from decimal import Decimal

import pandas as pd
import pytest

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.matching import match_stock_to_gl


@pytest.fixture
def base_config() -> ReconForgeConfig:
    return ReconForgeConfig(amount_tolerance=Decimal("0.05"), date_tolerance_days=3)


def test_matching_backward_compatibility_without_currency(base_config: ReconForgeConfig) -> None:
    """Test that rows without currency fall back to USD and match correctly."""
    stock = pd.DataFrame(
        [
            {
                "move_id": "SM1",
                "date": "2026-07-24",
                "total_cost": "100.50",
                "source_document": "INV-01",
                "work_order": "WO-1",
            }
        ]
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL1",
                "date": "2026-07-24",
                "amount": "100.50",
                "reference": "INV-01",
                "work_order": "WO-1",
            }
        ]
    )
    matches = match_stock_to_gl(stock, gl, base_config)
    assert len(matches) == 1
    assert matches[0].match_level == "Level 1 Exact"
    assert matches[0].stock_move_id == "SM1"
    assert matches[0].gl_entry_id == "GL1"


def test_matching_currency_isolation(base_config: ReconForgeConfig) -> None:
    """Test that equivalent amounts in different currencies do NOT match."""
    stock = pd.DataFrame(
        [
            {
                "move_id": "SM1",
                "date": "2026-07-24",
                "total_cost": "100.50",
                "currency": "USD",
                "source_document": "INV-01",
                "work_order": "WO-1",
            },
            {
                "move_id": "SM2",
                "date": "2026-07-24",
                "total_cost": "100.50",
                "currency": "EGP",
                "source_document": "INV-02",
                "work_order": "WO-2",
            }
        ]
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL1",
                "date": "2026-07-24",
                "amount": "100.50",
                "currency": "EGP",
                "reference": "INV-01",
                "work_order": "WO-1",
            },
            {
                "entry_id": "GL2",
                "date": "2026-07-24",
                "amount": "100.50",
                "currency": "USD",
                "reference": "INV-02",
                "work_order": "WO-2",
            }
        ]
    )
    # SM1 (USD) shouldn't match GL1 (EGP), SM2 (EGP) shouldn't match GL2 (USD)
    matches = match_stock_to_gl(stock, gl, base_config)
    assert len(matches) == 0


def test_matching_precision_and_invalid_data(base_config: ReconForgeConfig) -> None:
    """Test that invalid strings, NaNs, or incorrect precisions prevent matches instead of crashing."""
    stock = pd.DataFrame(
        [
            {
                "move_id": "SM1",
                "date": "2026-07-24",
                "total_cost": "INVALID",
                "currency": "USD",
                "source_document": "INV-01",
                "work_order": "WO-1",
            },
            {
                "move_id": "SM2",
                "date": "2026-07-24",
                "total_cost": float("nan"),
                "currency": "USD",
                "source_document": "INV-02",
                "work_order": "WO-2",
            }
        ]
    )
    gl = pd.DataFrame(
        [
            {
                "entry_id": "GL1",
                "date": "2026-07-24",
                "amount": "100.50",
                "currency": "USD",
                "reference": "INV-01",
                "work_order": "WO-1",
            },
            {
                "entry_id": "GL2",
                "date": "2026-07-24",
                "amount": "100.50",
                "currency": "USD",
                "reference": "INV-02",
                "work_order": "WO-2",
            }
        ]
    )
    matches = match_stock_to_gl(stock, gl, base_config)
    assert len(matches) == 0
