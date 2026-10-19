"""PostgreSQL persistence adapter for treasury positions and forecast flows with FORCE RLS."""

from __future__ import annotations

from typing import Any, Literal, cast

from reconforge.domain.treasury_liquidity import (
    CashPosition,
    LiquidityFlow,
    TreasuryLiquidityEngine,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.platform.common import PlatformError

POSTGRES_TREASURY_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.treasury_cash_positions (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    bank_account_id TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    currency TEXT NOT NULL,
    as_of_date DATE NOT NULL,
    cleared_balance_minor BIGINT NOT NULL,
    minimum_covenant_minor BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, legal_entity_id, bank_account_id)
);

CREATE TABLE IF NOT EXISTS reconforge.treasury_liquidity_flows (
    tenant_id TEXT NOT NULL,
    flow_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    currency TEXT NOT NULL,
    due_date DATE NOT NULL,
    amount_minor BIGINT NOT NULL,
    confidence_bps INTEGER NOT NULL DEFAULT 10000,
    status TEXT NOT NULL DEFAULT 'projected',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, flow_id)
);

CREATE INDEX IF NOT EXISTS idx_postgres_treasury_flows_due
    ON reconforge.treasury_liquidity_flows (tenant_id, workspace_id, legal_entity_id, currency, due_date);

ALTER TABLE reconforge.treasury_cash_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.treasury_cash_positions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope ON reconforge.treasury_cash_positions;
CREATE POLICY tenant_scope ON reconforge.treasury_cash_positions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE reconforge.treasury_liquidity_flows ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.treasury_liquidity_flows FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope ON reconforge.treasury_liquidity_flows;
CREATE POLICY tenant_scope ON reconforge.treasury_liquidity_flows
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresTreasuryRepository:
    """Thread-safe PostgreSQL storage for treasury positions and forecast flows with FORCE RLS."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def save_position(self, pos: CashPosition) -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.treasury_cash_positions (
                        tenant_id, workspace_id, organization_id, legal_entity_id,
                        bank_account_id, bank_name, currency,
                        as_of_date, cleared_balance_minor, minimum_covenant_minor
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, legal_entity_id, bank_account_id) DO UPDATE SET
                        bank_name = excluded.bank_name,
                        currency = excluded.currency,
                        as_of_date = excluded.as_of_date,
                        cleared_balance_minor = excluded.cleared_balance_minor,
                        minimum_covenant_minor = excluded.minimum_covenant_minor
                    """,
                    (
                        self.tenant_id,
                        pos.workspace_id,
                        pos.organization_id,
                        pos.legal_entity_id,
                        pos.bank_account_id,
                        pos.bank_name,
                        pos.currency,
                        pos.as_of_date,
                        pos.cleared_balance_minor,
                        pos.minimum_covenant_minor,
                    ),
                )
        except Exception as exc:
            raise PlatformError("Unable to persist treasury cash position.") from exc

    def get_position(
        self, workspace_id: str, legal_entity_id: str, bank_account_id: str
    ) -> CashPosition | None:
        try:
            with self.connection.transaction():
                self._scope()
                cursor = self.connection.execute(
                    """
                    SELECT workspace_id, organization_id, legal_entity_id,
                           bank_account_id, bank_name, currency,
                           as_of_date::text, cleared_balance_minor, minimum_covenant_minor
                    FROM reconforge.treasury_cash_positions
                    WHERE tenant_id = %s AND workspace_id = %s AND legal_entity_id = %s AND bank_account_id = %s
                    """,
                    (self.tenant_id, workspace_id, legal_entity_id, bank_account_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return CashPosition(
                    workspace_id=str(row[0]),
                    organization_id=str(row[1]),
                    legal_entity_id=str(row[2]),
                    bank_account_id=str(row[3]),
                    bank_name=str(row[4]),
                    currency=str(row[5]),
                    as_of_date=str(row[6]),
                    cleared_balance_minor=int(row[7]),
                    minimum_covenant_minor=int(row[8]),
                )
        except Exception as exc:
            raise PlatformError("Unable to retrieve treasury cash position.") from exc

    def save_flow(self, flow: LiquidityFlow) -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.treasury_liquidity_flows (
                        tenant_id, flow_id, workspace_id, organization_id, legal_entity_id,
                        direction, source_type, source_reference, currency,
                        due_date, amount_minor, confidence_bps, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, flow_id) DO UPDATE SET
                        direction = excluded.direction,
                        source_type = excluded.source_type,
                        source_reference = excluded.source_reference,
                        currency = excluded.currency,
                        due_date = excluded.due_date,
                        amount_minor = excluded.amount_minor,
                        confidence_bps = excluded.confidence_bps,
                        status = excluded.status
                    """,
                    (
                        self.tenant_id,
                        flow.flow_id,
                        flow.workspace_id,
                        flow.organization_id,
                        flow.legal_entity_id,
                        flow.direction,
                        flow.source_type,
                        flow.source_reference,
                        flow.currency,
                        flow.due_date,
                        flow.amount_minor,
                        flow.confidence_bps,
                        flow.status,
                    ),
                )
        except Exception as exc:
            raise PlatformError("Unable to persist treasury liquidity flow.") from exc

    def list_flows(
        self,
        workspace_id: str,
        legal_entity_id: str,
        currency: str,
        from_date: str,
        to_date: str,
    ) -> list[LiquidityFlow]:
        try:
            with self.connection.transaction():
                self._scope()
                cursor = self.connection.execute(
                    """
                    SELECT flow_id, workspace_id, organization_id, legal_entity_id,
                           direction, source_type, source_reference, currency,
                           due_date::text, amount_minor, confidence_bps, status
                    FROM reconforge.treasury_liquidity_flows
                    WHERE tenant_id = %s AND workspace_id = %s AND legal_entity_id = %s AND currency = %s
                      AND due_date >= %s::date AND due_date <= %s::date
                    ORDER BY due_date ASC
                    """,
                    (self.tenant_id, workspace_id, legal_entity_id, currency, from_date, to_date),
                )
                rows = cursor.fetchall()
                results: list[LiquidityFlow] = []
                for row in rows:
                    results.append(
                        LiquidityFlow(
                            flow_id=str(row[0]),
                            workspace_id=str(row[1]),
                            organization_id=str(row[2]),
                            legal_entity_id=str(row[3]),
                            direction=cast(Literal["inflow", "outflow"], str(row[4])),
                            source_type=cast(
                                Literal["receivable", "payable", "payroll", "tax", "debt_service", "manual"],
                                str(row[5]),
                            ),
                            source_reference=str(row[6]),
                            currency=str(row[7]),
                            due_date=str(row[8]),
                            amount_minor=int(row[9]),
                            confidence_bps=int(row[10]),
                            status=cast(Literal["projected", "confirmed", "disputed", "settled"], str(row[11])),
                        )
                    )
                return results
        except Exception as exc:
            raise PlatformError("Unable to list treasury liquidity flows.") from exc

    def build_engine(
        self, workspace_id: str, legal_entity_id: str, bank_account_id: str
    ) -> TreasuryLiquidityEngine:
        pos = self.get_position(workspace_id, legal_entity_id, bank_account_id)
        if not pos:
            raise ValueError(f"Position not found for bank account {bank_account_id}")
        engine = TreasuryLiquidityEngine(pos)
        flows = self.list_flows(
            workspace_id, legal_entity_id, pos.currency, "2000-01-01", "2099-12-31"
        )
        for f in flows:
            engine.add_flow(f)
        return engine
