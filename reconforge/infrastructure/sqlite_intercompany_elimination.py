"""SQLite persistence adapter for exact intercompany eliminations and profit-in-stock rules."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from reconforge.domain.intercompany_elimination import (
    IntercompanyEliminationResult,
    IntercompanyProfitInStockElimination,
    IntercompanyProfitInStockRule,
)
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import PlatformError

SQLITE_INTERCOMPANY_ELIMINATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS intercompany_elimination_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL,
    version TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    result_digest TEXT NOT NULL,
    result_payload TEXT NOT NULL,
    prepared_by TEXT NOT NULL,
    prepared_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, result_digest)
);

CREATE TABLE IF NOT EXISTS intercompany_profit_in_stock_rules (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    selling_entity TEXT NOT NULL,
    buying_entity TEXT NOT NULL,
    inventory_item_code TEXT NOT NULL,
    margin_basis_points INTEGER NOT NULL,
    ending_inventory_cost_minor INTEGER NOT NULL,
    nci_share_basis_points INTEGER NOT NULL,
    currency TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, rule_id)
);

CREATE TABLE IF NOT EXISTS intercompany_profit_in_stock_eliminations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    elimination_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    unrealized_profit_minor INTEGER NOT NULL,
    parent_share_minor INTEGER NOT NULL,
    nci_share_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    debit_account TEXT NOT NULL,
    credit_account TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, elimination_id)
);
"""


class SQLiteIntercompanyEliminationRepository:
    """Own SQLite-backed intercompany elimination artifacts and profit-in-stock persistence."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._init_tables()

    def _init_tables(self) -> None:
        self.connection.executescript(SQLITE_INTERCOMPANY_ELIMINATION_SCHEMA)
        self.connection.commit()

    def save_elimination_result(
        self,
        workspace: str,
        result: IntercompanyEliminationResult,
        *,
        actor_label: str = "local-cli",
    ) -> str:
        workspace_id = workspace.strip() or "default"
        now = utc_now_text()
        run_id = f"ICERUN-{workspace_id}-{result.result_digest[:16]}"
        payload_json = json.dumps(result.to_dict(), sort_keys=True)

        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO intercompany_elimination_runs (
                        id, workspace_id, reporting_currency, version,
                        request_digest, result_digest, result_payload,
                        prepared_by, prepared_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, result_digest) DO NOTHING
                    """,
                    (
                        run_id,
                        workspace_id,
                        result.reporting_currency,
                        result.version,
                        result.request_digest,
                        result.result_digest,
                        payload_json,
                        result.prepared_by,
                        result.prepared_at,
                        now,
                    ),
                )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to persist intercompany elimination run.") from exc

        return run_id

    def get_elimination_run(self, workspace: str, run_id: str) -> dict[str, Any] | None:
        workspace_id = workspace.strip() or "default"
        cursor = self.connection.execute(
            """
            SELECT id, workspace_id, reporting_currency, version,
                   request_digest, result_digest, result_payload,
                   prepared_by, prepared_at, created_at
            FROM intercompany_elimination_runs
            WHERE workspace_id = ? AND id = ?
            """,
            (workspace_id, run_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "workspace_id": row[1],
            "reporting_currency": row[2],
            "version": row[3],
            "request_digest": row[4],
            "result_digest": row[5],
            "result_payload": json.loads(row[6]),
            "prepared_by": row[7],
            "prepared_at": row[8],
            "created_at": row[9],
        }

    def list_elimination_runs(self, workspace: str, limit: int = 50) -> list[dict[str, Any]]:
        workspace_id = workspace.strip() or "default"
        cursor = self.connection.execute(
            """
            SELECT id, workspace_id, reporting_currency, version,
                   request_digest, result_digest,
                   prepared_by, prepared_at, created_at
            FROM intercompany_elimination_runs
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (workspace_id, max(1, min(limit, 200))),
        )
        return [
            {
                "id": row[0],
                "workspace_id": row[1],
                "reporting_currency": row[2],
                "version": row[3],
                "request_digest": row[4],
                "result_digest": row[5],
                "prepared_by": row[6],
                "prepared_at": row[7],
                "created_at": row[8],
            }
            for row in cursor.fetchall()
        ]

    def save_profit_in_stock_elimination(
        self,
        workspace: str,
        rule: IntercompanyProfitInStockRule,
        elimination: IntercompanyProfitInStockElimination,
        *,
        actor_label: str = "local-cli",
    ) -> str:
        workspace_id = workspace.strip() or "default"
        now = utc_now_text()
        db_rule_id = f"PISRULE-{workspace_id}-{rule.rule_id}"

        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO intercompany_profit_in_stock_rules (
                        id, workspace_id, rule_id, selling_entity, buying_entity,
                        inventory_item_code, margin_basis_points,
                        ending_inventory_cost_minor, nci_share_basis_points,
                        currency, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, rule_id) DO UPDATE SET
                        margin_basis_points=excluded.margin_basis_points,
                        ending_inventory_cost_minor=excluded.ending_inventory_cost_minor,
                        nci_share_basis_points=excluded.nci_share_basis_points
                    """,
                    (
                        db_rule_id,
                        workspace_id,
                        rule.rule_id,
                        rule.selling_entity,
                        rule.buying_entity,
                        rule.inventory_item_code,
                        rule.margin_basis_points,
                        rule.ending_inventory_cost_minor,
                        rule.nci_share_basis_points,
                        rule.currency,
                        now,
                    ),
                )
                self.connection.execute(
                    """
                    INSERT INTO intercompany_profit_in_stock_eliminations (
                        id, workspace_id, elimination_id, rule_id,
                        unrealized_profit_minor, parent_share_minor, nci_share_minor,
                        currency, debit_account, credit_account, rationale, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, elimination_id) DO NOTHING
                    """,
                    (
                        elimination.elimination_id,
                        workspace_id,
                        elimination.elimination_id,
                        elimination.rule_id,
                        elimination.unrealized_profit_minor,
                        elimination.parent_share_minor,
                        elimination.nci_share_minor,
                        elimination.currency,
                        elimination.debit_account,
                        elimination.credit_account,
                        elimination.rationale,
                        now,
                    ),
                )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to persist profit-in-stock elimination.") from exc

        return elimination.elimination_id

    def list_profit_in_stock_eliminations(self, workspace: str) -> list[dict[str, Any]]:
        workspace_id = workspace.strip() or "default"
        cursor = self.connection.execute(
            """
            SELECT elimination_id, rule_id, unrealized_profit_minor,
                   parent_share_minor, nci_share_minor, currency,
                   debit_account, credit_account, rationale, created_at
            FROM intercompany_profit_in_stock_eliminations
            WHERE workspace_id = ?
            ORDER BY created_at DESC
            """,
            (workspace_id,),
        )
        return [
            {
                "elimination_id": row[0],
                "rule_id": row[1],
                "unrealized_profit_minor": row[2],
                "parent_share_minor": row[3],
                "nci_share_minor": row[4],
                "currency": row[5],
                "debit_account": row[6],
                "credit_account": row[7],
                "rationale": row[8],
                "created_at": row[9],
            }
            for row in cursor.fetchall()
        ]
