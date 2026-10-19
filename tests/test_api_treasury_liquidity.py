import sqlite3

import pytest
from pydantic import ValidationError

from reconforge.api.routes.treasury_liquidity import (
    FlowRequest,
    PositionRequest,
)
from reconforge.domain.treasury_liquidity import CashPosition, LiquidityFlow
from reconforge.infrastructure.sqlite_treasury import SqliteTreasuryRepository


def test_position_request_schema_strictness() -> None:
    valid = {
        "bank_account_id": "BA-100",
        "bank_name": "Saudi National Bank",
        "currency": "SAR",
        "as_of_date": "2026-11-01",
        "cleared_balance_minor": "100000000",
        "minimum_covenant_minor": "20000000",
    }
    pos = PositionRequest.model_validate(valid)
    assert pos.currency == "SAR"
    assert pos.cleared_balance_minor == "100000000"

    # Reject float or invalid minor units
    for bad in ["1000.50", "abc", "-500", ""]:
        with pytest.raises(ValidationError):
            PositionRequest.model_validate({**valid, "cleared_balance_minor": bad})


def test_flow_request_schema_strictness() -> None:
    valid = {
        "flow_id": "F-01",
        "direction": "inflow",
        "source_type": "receivable",
        "source_reference": "INV-1001",
        "currency": "SAR",
        "due_date": "2026-11-05",
        "amount_minor": "50000000",
        "confidence_bps": 9500,
        "status": "projected",
    }
    flow = FlowRequest.model_validate(valid)
    assert flow.confidence_bps == 9500

    # Reject confidence out of bounds
    with pytest.raises(ValidationError):
        FlowRequest.model_validate({**valid, "confidence_bps": 15000})


def test_sqlite_treasury_repository_lifecycle() -> None:
    conn = sqlite3.connect(":memory:")
    repo = SqliteTreasuryRepository(conn)

    pos = CashPosition(
        workspace_id="ws_main",
        organization_id="org_01",
        legal_entity_id="le_01",
        bank_account_id="BA-SAR-01",
        bank_name="Al Rajhi Bank",
        currency="SAR",
        as_of_date="2026-11-01",
        cleared_balance_minor=500_000_00,
        minimum_covenant_minor=100_000_00,
    )
    repo.save_position(pos)

    retrieved = repo.get_position("ws_main", "le_01", "BA-SAR-01")
    assert retrieved is not None
    assert retrieved.bank_name == "Al Rajhi Bank"
    assert retrieved.cleared_balance_minor == 500_000_00

    # Save flows
    f1 = LiquidityFlow(
        flow_id="F-AR-01",
        workspace_id="ws_main",
        organization_id="org_01",
        legal_entity_id="le_01",
        direction="inflow",
        source_type="receivable",
        source_reference="INV-99",
        currency="SAR",
        due_date="2026-11-03",
        amount_minor=200_000_00,
    )
    f2 = LiquidityFlow(
        flow_id="F-AP-01",
        workspace_id="ws_main",
        organization_id="org_01",
        legal_entity_id="le_01",
        direction="outflow",
        source_type="payable",
        source_reference="BILL-55",
        currency="SAR",
        due_date="2026-11-08",
        amount_minor=150_000_00,
    )
    repo.save_flow(f1)
    repo.save_flow(f2)

    flows = repo.list_flows("ws_main", "le_01", "SAR", "2026-11-01", "2026-11-10")
    assert len(flows) == 2

    # Build forecast engine from repository
    engine = repo.build_engine("ws_main", "le_01", "BA-SAR-01")
    forecast = engine.forecast(horizon_days=10, bucket_days=5)
    assert len(forecast) == 2

    # Bucket 0: Opening 500k + 200k = 700k
    assert forecast[0].opening_balance_minor == 500_000_00
    assert forecast[0].closing_balance_minor == 700_000_00
    assert not forecast[0].covenant_breached

    # Bucket 1: Opening 700k - 150k = 550k
    assert forecast[1].opening_balance_minor == 700_000_00
    assert forecast[1].closing_balance_minor == 550_000_00
    assert not forecast[1].covenant_breached
