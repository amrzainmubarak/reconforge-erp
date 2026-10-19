from __future__ import annotations

import sqlite3

from reconforge.domain.treasury_liquidity import (
    CashPosition,
    LiquidityFlow,
    TreasuryLiquidityEngine,
)

CREATE_TREASURY_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS treasury_cash_positions (
    workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    bank_account_id TEXT NOT NULL,
    bank_name TEXT NOT NULL,
    currency TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    cleared_balance_minor INTEGER NOT NULL,
    minimum_covenant_minor INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (workspace_id, legal_entity_id, bank_account_id)
);

CREATE TABLE IF NOT EXISTS treasury_liquidity_flows (
    flow_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    legal_entity_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    currency TEXT NOT NULL,
    due_date TEXT NOT NULL,
    amount_minor INTEGER NOT NULL,
    confidence_bps INTEGER NOT NULL DEFAULT 10000,
    status TEXT NOT NULL DEFAULT 'projected',
    PRIMARY KEY (workspace_id, flow_id)
);

CREATE INDEX IF NOT EXISTS idx_treasury_flows_due
ON treasury_liquidity_flows (workspace_id, legal_entity_id, currency, due_date);
"""


class SqliteTreasuryRepository:
    """Thread-safe SQLite storage for treasury positions and forecast flows."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(CREATE_TREASURY_TABLES_SQL)
        self._conn.commit()

    def save_position(self, pos: CashPosition) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO treasury_cash_positions (
                    workspace_id, organization_id, legal_entity_id,
                    bank_account_id, bank_name, currency,
                    as_of_date, cleared_balance_minor, minimum_covenant_minor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, legal_entity_id, bank_account_id) DO UPDATE SET
                    bank_name = excluded.bank_name,
                    currency = excluded.currency,
                    as_of_date = excluded.as_of_date,
                    cleared_balance_minor = excluded.cleared_balance_minor,
                    minimum_covenant_minor = excluded.minimum_covenant_minor
                """,
                (
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

    def get_position(
        self, workspace_id: str, legal_entity_id: str, bank_account_id: str
    ) -> CashPosition | None:
        cursor = self._conn.execute(
            """
            SELECT workspace_id, organization_id, legal_entity_id,
                   bank_account_id, bank_name, currency,
                   as_of_date, cleared_balance_minor, minimum_covenant_minor
            FROM treasury_cash_positions
            WHERE workspace_id = ? AND legal_entity_id = ? AND bank_account_id = ?
            """,
            (workspace_id, legal_entity_id, bank_account_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return CashPosition(
            workspace_id=row[0],
            organization_id=row[1],
            legal_entity_id=row[2],
            bank_account_id=row[3],
            bank_name=row[4],
            currency=row[5],
            as_of_date=row[6],
            cleared_balance_minor=row[7],
            minimum_covenant_minor=row[8],
        )

    def save_flow(self, flow: LiquidityFlow) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO treasury_liquidity_flows (
                    flow_id, workspace_id, organization_id, legal_entity_id,
                    direction, source_type, source_reference, currency,
                    due_date, amount_minor, confidence_bps, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, flow_id) DO UPDATE SET
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

    def list_flows(
        self,
        workspace_id: str,
        legal_entity_id: str,
        currency: str,
        from_date: str,
        to_date: str,
    ) -> list[LiquidityFlow]:
        cursor = self._conn.execute(
            """
            SELECT flow_id, workspace_id, organization_id, legal_entity_id,
                   direction, source_type, source_reference, currency,
                   due_date, amount_minor, confidence_bps, status
            FROM treasury_liquidity_flows
            WHERE workspace_id = ? AND legal_entity_id = ? AND currency = ?
              AND due_date >= ? AND due_date <= ?
            ORDER BY due_date ASC
            """,
            (workspace_id, legal_entity_id, currency, from_date, to_date),
        )
        results: list[LiquidityFlow] = []
        for row in cursor.fetchall():
            results.append(
                LiquidityFlow(
                    flow_id=row[0],
                    workspace_id=row[1],
                    organization_id=row[2],
                    legal_entity_id=row[3],
                    direction=row[4],
                    source_type=row[5],
                    source_reference=row[6],
                    currency=row[7],
                    due_date=row[8],
                    amount_minor=row[9],
                    confidence_bps=row[10],
                    status=row[11],
                )
            )
        return results

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
