"""SQLite persistence adapter for Shop Floor Execution and Lot Genealogy."""

from __future__ import annotations

import sqlite3

from reconforge.domain.shop_floor_dispatch import (
    LotTraceabilityRecord,
    ShopFloorOperationStep,
    WorkOrderDispatch,
)

CREATE_SHOP_FLOOR_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS shop_floor_lots (
    workspace_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    batch_number TEXT NOT NULL,
    quantity_scaled INTEGER NOT NULL,
    scale_factor INTEGER NOT NULL DEFAULT 1000,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (workspace_id, lot_id)
);

CREATE TABLE IF NOT EXISTS shop_floor_lot_genealogy (
    workspace_id TEXT NOT NULL,
    parent_lot_id TEXT NOT NULL,
    child_lot_id TEXT NOT NULL,
    quantity_consumed_scaled INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (workspace_id, parent_lot_id, child_lot_id)
);

CREATE TABLE IF NOT EXISTS shop_floor_dispatches (
    workspace_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    scheduled_quantity_scaled INTEGER NOT NULL,
    dispatched_lot_id TEXT NOT NULL,
    dispatched_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, dispatch_id)
);

CREATE TABLE IF NOT EXISTS shop_floor_steps (
    workspace_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL,
    work_center_id TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    status TEXT NOT NULL,
    actual_run_minutes INTEGER NOT NULL,
    quantity_completed_scaled INTEGER NOT NULL,
    quantity_scrapped_scaled INTEGER NOT NULL,
    scrap_reason_code TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (workspace_id, step_id)
);
"""


class SqliteShopFloorRepository:
    """Thread-safe SQLite storage for shop floor dispatches, execution steps, and lot genealogy."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(CREATE_SHOP_FLOOR_TABLES_SQL)
        self._conn.commit()

    def register_lot(
        self,
        lot: LotTraceabilityRecord,
        parent_lots: list[tuple[str, int]] | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO shop_floor_lots (
                    workspace_id, lot_id, item_id, batch_number,
                    quantity_scaled, scale_factor, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, lot_id) DO UPDATE SET
                    quantity_scaled = excluded.quantity_scaled,
                    status = excluded.status,
                    notes = excluded.notes
                """,
                (
                    lot.workspace_id,
                    lot.lot_id,
                    lot.item_id,
                    lot.batch_number,
                    lot.quantity_scaled,
                    lot.scale_factor,
                    lot.status,
                    lot.notes,
                ),
            )
            if parent_lots:
                for parent_id, qty in parent_lots:
                    self._conn.execute(
                        """
                        INSERT INTO shop_floor_lot_genealogy (
                            workspace_id, parent_lot_id, child_lot_id, quantity_consumed_scaled
                        ) VALUES (?, ?, ?, ?)
                        ON CONFLICT(workspace_id, parent_lot_id, child_lot_id) DO UPDATE SET
                            quantity_consumed_scaled = excluded.quantity_consumed_scaled
                        """,
                        (lot.workspace_id, parent_id, lot.lot_id, qty),
                    )

    def get_lot(self, workspace_id: str, lot_id: str) -> LotTraceabilityRecord | None:
        cursor = self._conn.execute(
            """
            SELECT workspace_id, lot_id, item_id, batch_number,
                   quantity_scaled, scale_factor, status, notes
            FROM shop_floor_lots
            WHERE workspace_id = ? AND lot_id = ?
            """,
            (workspace_id, lot_id),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return LotTraceabilityRecord(
            workspace_id=row[0],
            lot_id=row[1],
            item_id=row[2],
            batch_number=row[3],
            quantity_scaled=row[4],
            scale_factor=row[5],
            status=row[6],
            notes=row[7],
        )

    def save_dispatch(self, dispatch: WorkOrderDispatch) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO shop_floor_dispatches (
                    workspace_id, dispatch_id, work_order_id, item_id,
                    scheduled_quantity_scaled, dispatched_lot_id, dispatched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, dispatch_id) DO UPDATE SET
                    scheduled_quantity_scaled = excluded.scheduled_quantity_scaled,
                    dispatched_lot_id = excluded.dispatched_lot_id
                """,
                (
                    dispatch.workspace_id,
                    dispatch.dispatch_id,
                    dispatch.work_order_id,
                    dispatch.item_id,
                    dispatch.scheduled_quantity_scaled,
                    dispatch.dispatched_lot_id,
                    dispatch.dispatched_at,
                ),
            )
            for step in dispatch.steps:
                self.save_step(dispatch.workspace_id, step)

    def save_step(self, workspace_id: str, step: ShopFloorOperationStep) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO shop_floor_steps (
                    workspace_id, step_id, work_order_id, operation_sequence,
                    work_center_id, operator_id, status, actual_run_minutes,
                    quantity_completed_scaled, quantity_scrapped_scaled,
                    scrap_reason_code, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, step_id) DO UPDATE SET
                    status = excluded.status,
                    actual_run_minutes = excluded.actual_run_minutes,
                    quantity_completed_scaled = excluded.quantity_completed_scaled,
                    quantity_scrapped_scaled = excluded.quantity_scrapped_scaled,
                    scrap_reason_code = excluded.scrap_reason_code,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at
                """,
                (
                    workspace_id,
                    step.step_id,
                    step.work_order_id,
                    step.operation_sequence,
                    step.work_center_id,
                    step.operator_id,
                    step.status,
                    step.actual_run_minutes,
                    step.quantity_completed_scaled,
                    step.quantity_scrapped_scaled,
                    step.scrap_reason_code,
                    step.started_at,
                    step.completed_at,
                ),
            )

    def get_dispatch(self, workspace_id: str, dispatch_id: str) -> WorkOrderDispatch | None:
        cursor = self._conn.execute(
            """
            SELECT workspace_id, dispatch_id, work_order_id, item_id,
                   scheduled_quantity_scaled, dispatched_lot_id, dispatched_at
            FROM shop_floor_dispatches
            WHERE workspace_id = ? AND dispatch_id = ?
            """,
            (workspace_id, dispatch_id),
        )
        row = cursor.fetchone()
        if not row:
            return None

        # Fetch steps
        step_cursor = self._conn.execute(
            """
            SELECT step_id, work_order_id, operation_sequence,
                   work_center_id, operator_id, status, actual_run_minutes,
                   quantity_completed_scaled, quantity_scrapped_scaled,
                   scrap_reason_code, started_at, completed_at
            FROM shop_floor_steps
            WHERE workspace_id = ? AND work_order_id = ?
            ORDER BY operation_sequence ASC
            """,
            (workspace_id, row[2]),
        )
        steps = tuple(
            ShopFloorOperationStep(
                step_id=s[0],
                work_order_id=s[1],
                operation_sequence=s[2],
                work_center_id=s[3],
                operator_id=s[4],
                status=s[5],
                actual_run_minutes=s[6],
                quantity_completed_scaled=s[7],
                quantity_scrapped_scaled=s[8],
                scrap_reason_code=s[9],
                started_at=s[10],
                completed_at=s[11],
            )
            for s in step_cursor.fetchall()
        )

        return WorkOrderDispatch(
            workspace_id=row[0],
            dispatch_id=row[1],
            work_order_id=row[2],
            item_id=row[3],
            scheduled_quantity_scaled=row[4],
            dispatched_lot_id=row[5],
            dispatched_at=row[6],
            steps=steps,
        )

    def get_genealogy_edges(self, workspace_id: str) -> list[tuple[str, str, int]]:
        cursor = self._conn.execute(
            """
            SELECT parent_lot_id, child_lot_id, quantity_consumed_scaled
            FROM shop_floor_lot_genealogy
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        )
        return [(r[0], r[1], r[2]) for r in cursor.fetchall()]

    def get_lot_item_map(self, workspace_id: str) -> dict[str, str]:
        cursor = self._conn.execute(
            "SELECT lot_id, item_id FROM shop_floor_lots WHERE workspace_id = ?",
            (workspace_id,),
        )
        return {r[0]: r[1] for r in cursor.fetchall()}
