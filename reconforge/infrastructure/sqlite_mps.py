"""SQLite persistence adapter for Master Production Scheduling (MPS) and sourcing requisitions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from reconforge.domain.master_production_schedule import MPSPlanResult
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import PlatformError

SQLITE_MPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS mps_plans (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    revision TEXT NOT NULL,
    item_id TEXT NOT NULL,
    unit_of_measure TEXT NOT NULL,
    quantity_scale INTEGER NOT NULL,
    safety_stock_scaled INTEGER NOT NULL,
    lot_size_multiple_scaled INTEGER NOT NULL,
    opening_inventory_scaled INTEGER NOT NULL,
    plan_digest TEXT NOT NULL,
    plan_payload TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, plan_id, revision)
);

CREATE TABLE IF NOT EXISTS mps_sourcing_requisitions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    requisition_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_revision TEXT NOT NULL,
    item_id TEXT NOT NULL,
    bucket_index INTEGER NOT NULL,
    required_date TEXT NOT NULL,
    shortage_quantity_scaled INTEGER NOT NULL,
    order_quantity_scaled INTEGER NOT NULL,
    preferred_supplier_id TEXT NOT NULL,
    unit_price_ceiling_minor INTEGER NOT NULL,
    currency TEXT NOT NULL,
    requisition_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'APPROVED',
    created_at TEXT NOT NULL,
    UNIQUE (workspace_id, requisition_id),
    UNIQUE (workspace_id, plan_id, plan_revision, item_id, bucket_index)
);

CREATE INDEX IF NOT EXISTS idx_mps_plans_lookup
ON mps_plans (workspace_id, item_id);
"""


class SQLiteMPSRepository:
    """Thread-safe SQLite storage for Master Production Schedules and procurement requisitions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._init_tables()

    def _init_tables(self) -> None:
        with self._conn:
            self._conn.executescript(SQLITE_MPS_SCHEMA)

    def save_plan(
        self,
        *,
        workspace_id: str,
        plan_result: MPSPlanResult,
        created_by: str = "system",
    ) -> str:
        record_id = f"mps_{plan_result.plan_id}_{plan_result.revision}"
        now = utc_now_text()
        payload = json.dumps(asdict(plan_result), sort_keys=True)

        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO mps_plans (
                        id, workspace_id, plan_id, plan_name, revision,
                        item_id, unit_of_measure, quantity_scale, safety_stock_scaled,
                        lot_size_multiple_scaled, opening_inventory_scaled,
                        plan_digest, plan_payload, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, plan_id, revision) DO UPDATE SET
                        plan_name = excluded.plan_name,
                        plan_payload = excluded.plan_payload,
                        plan_digest = excluded.plan_digest
                    """,
                    (
                        record_id,
                        workspace_id,
                        plan_result.plan_id,
                        plan_result.plan_name,
                        plan_result.revision,
                        plan_result.item_id,
                        plan_result.unit_of_measure,
                        plan_result.quantity_scale,
                        plan_result.safety_stock_scaled,
                        plan_result.lot_size_multiple_scaled,
                        plan_result.opening_inventory_scaled,
                        plan_result.plan_digest,
                        payload,
                        created_by,
                        now,
                    ),
                )

                for pr in plan_result.sourcing_requisitions:
                    pr_id = f"pr_{pr.requisition_id}"
                    self._conn.execute(
                        """
                        INSERT INTO mps_sourcing_requisitions (
                            id, workspace_id, requisition_id, plan_id, plan_revision,
                            item_id, bucket_index, required_date, shortage_quantity_scaled,
                            order_quantity_scaled, preferred_supplier_id, unit_price_ceiling_minor,
                            currency, requisition_digest, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'APPROVED', ?)
                        ON CONFLICT(workspace_id, requisition_id) DO UPDATE SET
                            order_quantity_scaled = excluded.order_quantity_scaled
                        """,
                        (
                            pr_id,
                            workspace_id,
                            pr.requisition_id,
                            pr.plan_id,
                            pr.plan_revision,
                            pr.item_id,
                            pr.bucket_index,
                            pr.required_date,
                            pr.shortage_quantity_scaled,
                            pr.order_quantity_scaled,
                            pr.preferred_supplier_id,
                            pr.unit_price_ceiling_minor,
                            pr.currency,
                            pr.requisition_digest,
                            now,
                        ),
                    )
        except sqlite3.Error as exc:
            raise PlatformError(f"Failed to persist MPS plan and requisitions: {exc}") from exc

        return record_id

    def get_plan(self, *, workspace_id: str, plan_id: str, revision: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT id, workspace_id, plan_id, plan_name, revision,
                   item_id, unit_of_measure, quantity_scale, safety_stock_scaled,
                   lot_size_multiple_scaled, opening_inventory_scaled,
                   plan_digest, plan_payload, created_by, created_at
            FROM mps_plans
            WHERE workspace_id = ? AND plan_id = ? AND revision = ?
            """,
            (workspace_id, plan_id, revision),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "workspace_id": row[1],
            "plan_id": row[2],
            "plan_name": row[3],
            "revision": row[4],
            "item_id": row[5],
            "unit_of_measure": row[6],
            "quantity_scale": row[7],
            "safety_stock_scaled": row[8],
            "lot_size_multiple_scaled": row[9],
            "opening_inventory_scaled": row[10],
            "plan_digest": row[11],
            "plan": json.loads(row[12]),
            "created_by": row[13],
            "created_at": row[14],
        }

    def list_plans(self, *, workspace_id: str, item_id: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        if item_id:
            cur.execute(
                """
                SELECT id, workspace_id, plan_id, plan_name, revision,
                       item_id, unit_of_measure, quantity_scale, safety_stock_scaled,
                       lot_size_multiple_scaled, opening_inventory_scaled,
                       plan_digest, plan_payload, created_by, created_at
                FROM mps_plans
                WHERE workspace_id = ? AND item_id = ?
                ORDER BY created_at DESC
                """,
                (workspace_id, item_id),
            )
        else:
            cur.execute(
                """
                SELECT id, workspace_id, plan_id, plan_name, revision,
                       item_id, unit_of_measure, quantity_scale, safety_stock_scaled,
                       lot_size_multiple_scaled, opening_inventory_scaled,
                       plan_digest, plan_payload, created_by, created_at
                FROM mps_plans
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
                "plan_id": r[2],
                "plan_name": r[3],
                "revision": r[4],
                "item_id": r[5],
                "unit_of_measure": r[6],
                "quantity_scale": r[7],
                "safety_stock_scaled": r[8],
                "lot_size_multiple_scaled": r[9],
                "opening_inventory_scaled": r[10],
                "plan_digest": r[11],
                "plan": json.loads(r[12]),
                "created_by": r[13],
                "created_at": r[14],
            }
            for r in rows
        ]

    def list_requisitions(self, *, workspace_id: str, plan_id: str | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        if plan_id:
            cur.execute(
                """
                SELECT id, workspace_id, requisition_id, plan_id, plan_revision,
                       item_id, bucket_index, required_date, shortage_quantity_scaled,
                       order_quantity_scaled, preferred_supplier_id, unit_price_ceiling_minor,
                       currency, requisition_digest, status, created_at
                FROM mps_sourcing_requisitions
                WHERE workspace_id = ? AND plan_id = ?
                ORDER BY bucket_index ASC
                """,
                (workspace_id, plan_id),
            )
        else:
            cur.execute(
                """
                SELECT id, workspace_id, requisition_id, plan_id, plan_revision,
                       item_id, bucket_index, required_date, shortage_quantity_scaled,
                       order_quantity_scaled, preferred_supplier_id, unit_price_ceiling_minor,
                       currency, requisition_digest, status, created_at
                FROM mps_sourcing_requisitions
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
                "requisition_id": r[2],
                "plan_id": r[3],
                "plan_revision": r[4],
                "item_id": r[5],
                "bucket_index": r[6],
                "required_date": r[7],
                "shortage_quantity_scaled": r[8],
                "order_quantity_scaled": r[9],
                "preferred_supplier_id": r[10],
                "unit_price_ceiling_minor": r[11],
                "currency": r[12],
                "requisition_digest": r[13],
                "status": r[14],
                "created_at": r[15],
            }
            for r in rows
        ]
