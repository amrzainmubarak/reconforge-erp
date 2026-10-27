"""SQLite persistence adapter for multi-entity consolidated financial statements."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from reconforge.domain.consolidated_financial_statements import ConsolidatedFinancialStatements
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import PlatformError

SQLITE_CONSOLIDATED_STATEMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS consolidated_statement_runs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    reporting_currency TEXT NOT NULL,
    period_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    report_digest TEXT NOT NULL,
    statements_payload TEXT NOT NULL,
    prepared_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, report_digest)
);

CREATE INDEX IF NOT EXISTS idx_consolidated_statements_lookup
ON consolidated_statement_runs (workspace_id, group_id, period_id);
"""


class SQLiteConsolidatedStatementsRepository:
    """Thread-safe SQLite storage for consolidated financial statement runs."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._init_tables()

    def _init_tables(self) -> None:
        with self._conn:
            self._conn.executescript(SQLITE_CONSOLIDATED_STATEMENTS_SCHEMA)

    def save_run(
        self,
        *,
        workspace_id: str,
        statements: ConsolidatedFinancialStatements,
        prepared_by: str = "system",
    ) -> str:
        run_id = f"csr_{statements.group_id}_{statements.period_id}_{statements.report_digest[:12]}"
        now = utc_now_text()
        payload = json.dumps(asdict(statements), sort_keys=True)

        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO consolidated_statement_runs (
                        id, workspace_id, group_id, organization_id, reporting_currency,
                        period_id, period_start, period_end, as_of_date,
                        report_digest, statements_payload, prepared_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, report_digest) DO UPDATE SET
                        statements_payload = excluded.statements_payload,
                        prepared_by = excluded.prepared_by
                    """,
                    (
                        run_id,
                        workspace_id,
                        statements.group_id,
                        statements.organization_id,
                        statements.reporting_currency,
                        statements.period_id,
                        statements.period_start,
                        statements.period_end,
                        statements.as_of_date,
                        statements.report_digest,
                        payload,
                        prepared_by,
                        now,
                    ),
                )
        except sqlite3.Error as exc:
            raise PlatformError(f"Failed to persist consolidated statement run: {exc}") from exc

        return run_id

    def get_run(self, *, workspace_id: str, run_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, workspace_id, group_id, organization_id, reporting_currency,
                   period_id, period_start, period_end, as_of_date,
                   report_digest, statements_payload, prepared_by, created_at
            FROM consolidated_statement_runs
            WHERE workspace_id = ? AND id = ?
            """,
            (workspace_id, run_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "workspace_id": row[1],
            "group_id": row[2],
            "organization_id": row[3],
            "reporting_currency": row[4],
            "period_id": row[5],
            "period_start": row[6],
            "period_end": row[7],
            "as_of_date": row[8],
            "report_digest": row[9],
            "statements": json.loads(row[10]),
            "prepared_by": row[11],
            "created_at": row[12],
        }

    def list_runs(self, *, workspace_id: str, group_id: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        if group_id:
            cur.execute(
                """
                SELECT id, workspace_id, group_id, organization_id, reporting_currency,
                       period_id, period_start, period_end, as_of_date,
                       report_digest, statements_payload, prepared_by, created_at
                FROM consolidated_statement_runs
                WHERE workspace_id = ? AND group_id = ?
                ORDER BY created_at DESC
                """,
                (workspace_id, group_id),
            )
        else:
            cur.execute(
                """
                SELECT id, workspace_id, group_id, organization_id, reporting_currency,
                       period_id, period_start, period_end, as_of_date,
                       report_digest, statements_payload, prepared_by, created_at
                FROM consolidated_statement_runs
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                """,
                (workspace_id,),
            )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "workspace_id": r[1],
                "group_id": r[2],
                "organization_id": r[3],
                "reporting_currency": r[4],
                "period_id": r[5],
                "period_start": r[6],
                "period_end": r[7],
                "as_of_date": r[8],
                "report_digest": r[9],
                "statements": json.loads(r[10]),
                "prepared_by": r[11],
                "created_at": r[12],
            }
            for r in rows
        ]
