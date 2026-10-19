import sqlite3
from contextlib import contextmanager
from typing import Any

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


def test_postgres_treasury_repository_lifecycle() -> None:
    from reconforge.infrastructure.postgres_treasury import (
        POSTGRES_TREASURY_SCHEMA_SQL,
        PostgresTreasuryRepository,
    )

    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_TREASURY_SCHEMA_SQL
    assert "reconforge.treasury_cash_positions" in POSTGRES_TREASURY_SCHEMA_SQL
    assert "reconforge.treasury_liquidity_flows" in POSTGRES_TREASURY_SCHEMA_SQL

    class FakeCursor:
        def __init__(self, rows: list[Any]) -> None:
            self._rows = rows

        def fetchone(self) -> Any:
            return self._rows[0] if self._rows else None

        def fetchall(self) -> list[Any]:
            return self._rows

    class FakeConnection:
        def __init__(self) -> None:
            self.executed: list[tuple[str, tuple[Any, ...]]] = []
            self.positions: dict[tuple[str, str, str, str], tuple[Any, ...]] = {}
            self.flows: list[tuple[Any, ...]] = []

        def transaction(self) -> Any:
            @contextmanager
            def _tx() -> Any:
                yield self

            return _tx()

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeCursor:
            self.executed.append((sql, params))
            clean = " ".join(sql.split())
            if "set_config('app.tenant_id'" in clean:
                return FakeCursor([])
            if "INSERT INTO reconforge.treasury_cash_positions" in clean:
                key = (params[0], params[1], params[3], params[4])
                self.positions[key] = params
                return FakeCursor([])
            if "SELECT workspace_id, organization_id, legal_entity_id" in clean and "reconforge.treasury_cash_positions" in clean:
                key = (params[0], params[1], params[2], params[3])
                if key in self.positions:
                    p = self.positions[key]
                    return FakeCursor([(p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9])])
                return FakeCursor([])
            if "INSERT INTO reconforge.treasury_liquidity_flows" in clean:
                self.flows.append(params)
                return FakeCursor([])
            if "SELECT flow_id, workspace_id, organization_id, legal_entity_id" in clean and "reconforge.treasury_liquidity_flows" in clean:
                rows = [
                    (f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[10], f[11], f[12])
                    for f in self.flows
                    if f[0] == params[0] and f[2] == params[1] and f[4] == params[2] and f[8] == params[3]
                ]
                return FakeCursor(rows)
            return FakeCursor([])

    conn = FakeConnection()
    repo = PostgresTreasuryRepository(conn, "00000000-0000-0000-0000-000000000001")
    pos = CashPosition(
        workspace_id="ws_pg",
        organization_id="org_pg",
        legal_entity_id="le_pg",
        bank_account_id="BA-PG-01",
        bank_name="Riyad Bank",
        currency="SAR",
        as_of_date="2026-11-01",
        cleared_balance_minor=1_000_000_00,
        minimum_covenant_minor=200_000_00,
    )
    repo.save_position(pos)
    retrieved = repo.get_position("ws_pg", "le_pg", "BA-PG-01")
    assert retrieved is not None
    assert retrieved.bank_name == "Riyad Bank"
    assert retrieved.cleared_balance_minor == 1_000_000_00

    flow = LiquidityFlow(
        flow_id="F-PG-01",
        workspace_id="ws_pg",
        organization_id="org_pg",
        legal_entity_id="le_pg",
        direction="inflow",
        source_type="receivable",
        source_reference="INV-PG-1",
        currency="SAR",
        due_date="2026-11-05",
        amount_minor=500_000_00,
    )
    repo.save_flow(flow)
    flows = repo.list_flows("ws_pg", "le_pg", "SAR", "2026-11-01", "2026-11-10")
    assert len(flows) == 1
    assert flows[0].amount_minor == 500_000_00
