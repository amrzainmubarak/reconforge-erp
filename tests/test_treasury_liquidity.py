"""Tests for deterministic treasury liquidity forecasting and stress scenarios."""

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.treasury_liquidity import (
    CashPosition,
    LiquidityFlow,
    StressScenario,
    TreasuryLiquidityEngine,
    scale_by_bps,
)


def test_scale_by_bps_rounding() -> None:
    # 1000 minor with 5000 bps (50%) -> 500
    assert scale_by_bps(1000, 5000) == 500
    # 100 minor with 3333 bps (33.33%) -> (100 * 3333 + 5000) // 10000 = (333300 + 5000) // 10000 = 338300 // 10000 = 33
    assert scale_by_bps(100, 3333) == 33
    # 100 minor with 3335 bps -> (333500 + 5000) // 10000 = 338500 // 10000 = 33
    assert scale_by_bps(100, 3335) == 33


def test_treasury_liquidity_baseline_projection() -> None:
    pos = CashPosition(
        workspace_id="ws_01",
        organization_id="org_01",
        legal_entity_id="le_01",
        bank_account_id="ba_01",
        bank_name="Saudi National Bank",
        currency="SAR",
        as_of_date="2026-11-01",
        cleared_balance_minor=1_000_000_00,  # 1,000,000.00 SAR
        minimum_covenant_minor=200_000_00,   # 200,000.00 SAR
    )

    engine = TreasuryLiquidityEngine(pos)

    # Inflow: Confirmed AR due Nov 05
    engine.add_flow(
        LiquidityFlow(
            flow_id="f_ar_01",
            workspace_id="ws_01",
            organization_id="org_01",
            legal_entity_id="le_01",
            direction="inflow",
            source_type="receivable",
            source_reference="INV-2026-001",
            currency="SAR",
            due_date="2026-11-05",
            amount_minor=500_000_00,
            confidence_bps=10_000,
        )
    )

    # Outflow: Supplier AP due Nov 10
    engine.add_flow(
        LiquidityFlow(
            flow_id="f_ap_01",
            workspace_id="ws_01",
            organization_id="org_01",
            legal_entity_id="le_01",
            direction="outflow",
            source_type="payable",
            source_reference="BILL-2026-88",
            currency="SAR",
            due_date="2026-11-10",
            amount_minor=300_000_00,
            confidence_bps=10_000,
        )
    )

    # Forecast for 15 days in 5-day buckets:
    # Bucket 0: Nov 01 - Nov 05 (includes AR +500,000)
    # Bucket 1: Nov 06 - Nov 10 (includes AP -300,000)
    # Bucket 2: Nov 11 - Nov 15 (no flows)
    results = engine.forecast(horizon_days=15, bucket_days=5)
    assert len(results) == 3

    # Bucket 0
    b0 = results[0]
    assert b0.opening_balance_minor == 1_000_000_00
    assert b0.weighted_inflow_minor == 500_000_00
    assert b0.weighted_outflow_minor == 0
    assert b0.closing_balance_minor == 1_500_000_00
    assert not b0.covenant_breached

    # Bucket 1
    b1 = results[1]
    assert b1.opening_balance_minor == 1_500_000_00
    assert b1.weighted_inflow_minor == 0
    assert b1.weighted_outflow_minor == 300_000_00
    assert b1.closing_balance_minor == 1_200_000_00
    assert not b1.covenant_breached

    # Bucket 2
    b2 = results[2]
    assert b2.opening_balance_minor == 1_200_000_00
    assert b2.closing_balance_minor == 1_200_000_00
    assert not b2.covenant_breached


def test_treasury_stress_scenario_delay_and_shock() -> None:
    pos = CashPosition(
        workspace_id="ws_01",
        organization_id="org_01",
        legal_entity_id="le_01",
        bank_account_id="ba_01",
        bank_name="Saudi National Bank",
        currency="SAR",
        as_of_date="2026-11-01",
        cleared_balance_minor=300_000_00,  # 300,000.00 SAR
        minimum_covenant_minor=250_000_00,  # 250,000.00 SAR
    )

    engine = TreasuryLiquidityEngine(pos)

    # AR due Nov 02 (+200,000)
    engine.add_flow(
        LiquidityFlow(
            flow_id="f_ar_01",
            workspace_id="ws_01",
            organization_id="org_01",
            legal_entity_id="le_01",
            direction="inflow",
            source_type="receivable",
            source_reference="INV-001",
            currency="SAR",
            due_date="2026-11-02",
            amount_minor=200_000_00,
            confidence_bps=10_000,
        )
    )

    # AP due Nov 08 (-150,000)
    engine.add_flow(
        LiquidityFlow(
            flow_id="f_ap_01",
            workspace_id="ws_01",
            organization_id="org_01",
            legal_entity_id="le_01",
            direction="outflow",
            source_type="payable",
            source_reference="BILL-001",
            currency="SAR",
            due_date="2026-11-08",
            amount_minor=150_000_00,
            confidence_bps=10_000,
        )
    )

    # Scenario: AR delayed by 10 days (moves from Nov 02 to Nov 12), and unplanned shock of 100,000 in bucket 0
    stress = StressScenario(
        scenario_name="Liquidity Squeeze",
        ar_delay_days=10,
        ar_haircut_bps=1000,  # 10% haircut on AR
        ap_acceleration_days=0,
        unplanned_outflow_minor=100_000_00,
    )

    results = engine.forecast(horizon_days=15, bucket_days=5, scenario=stress)

    # Bucket 0 (Nov 01-05): AR delayed to Nov 12, so no inflow! Shock of 100,000 outflow.
    # Opening 300,000 - 100,000 = 200,000 -> covenant breached! (covenant is 250,000)
    b0 = results[0]
    assert b0.weighted_inflow_minor == 0
    assert b0.weighted_outflow_minor == 100_000_00
    assert b0.closing_balance_minor == 200_000_00
    assert b0.covenant_breached is True

    # Bucket 1 (Nov 06-10): AP of 150,000 outflow.
    # Opening 200,000 - 150,000 = 50,000.
    b1 = results[1]
    assert b1.weighted_inflow_minor == 0
    assert b1.weighted_outflow_minor == 150_000_00
    assert b1.closing_balance_minor == 50_000_00
    assert b1.covenant_breached is True

    # Bucket 2 (Nov 11-15): AR now arrives on Nov 12 with 10% haircut: 200,000 * 90% = 180,000.
    # Opening 50,000 + 180,000 = 230,000.
    b2 = results[2]
    assert b2.weighted_inflow_minor == 180_000_00
    assert b2.closing_balance_minor == 230_000_00
    assert b2.covenant_breached is True  # still below 250,000


def test_treasury_currency_mismatch_rejected() -> None:
    pos = CashPosition(
        workspace_id="ws_01",
        organization_id="org_01",
        legal_entity_id="le_01",
        bank_account_id="ba_01",
        bank_name="SNB",
        currency="SAR",
        as_of_date="2026-11-01",
        cleared_balance_minor=100_000,
    )
    engine = TreasuryLiquidityEngine(pos)
    with pytest.raises(FinancePostingError, match="currency"):
        engine.add_flow(
            LiquidityFlow(
                flow_id="f_01",
                workspace_id="ws_01",
                organization_id="org_01",
                legal_entity_id="le_01",
                direction="inflow",
                source_type="receivable",
                source_reference="INV-USD",
                currency="USD",  # Mismatch!
                due_date="2026-11-05",
                amount_minor=10_000,
            )
        )
