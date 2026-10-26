"""Transaction-neutral SQLite persistence for quality workflow records."""

from __future__ import annotations

import sqlite3

from reconforge.domain.manufacturing_quality_rework import (
    NonConformanceReport,
    QualityInspectionPlan,
    QualityReworkError,
    ReworkOrder,
)
from reconforge.infrastructure.quality_records import (
    ncr_from_row,
    ncr_values,
    plan_from_row,
    plan_values,
    rework_from_row,
    rework_values,
)

SQLITE_QUALITY_SCHEMA = "\nCREATE TABLE IF NOT EXISTS quality_inspection_plans (\n    plan_id TEXT PRIMARY KEY,\n    workspace_id TEXT NOT NULL,\n    item_id TEXT NOT NULL,\n    revision TEXT NOT NULL,\n    name TEXT NOT NULL,\n    sample_size_units INTEGER NOT NULL,\n    specifications_json TEXT NOT NULL,\n    created_at TEXT NOT NULL,\n    UNIQUE (workspace_id, item_id, revision)\n);\n\nCREATE TABLE IF NOT EXISTS quality_ncrs (\n    ncr_id TEXT PRIMARY KEY,\n    workspace_id TEXT NOT NULL,\n    lot_id TEXT NOT NULL,\n    work_order_id TEXT NOT NULL,\n    defect_code TEXT NOT NULL,\n    defect_severity TEXT NOT NULL,\n    inspector_id TEXT NOT NULL,\n    quarantined_quantity_scaled INTEGER NOT NULL,\n    status TEXT NOT NULL,\n    disposition TEXT,\n    disposition_notes TEXT,\n    disposition_by TEXT,\n    disposition_at TEXT,\n    created_at TEXT NOT NULL\n);\n\nCREATE TABLE IF NOT EXISTS quality_rework_orders (\n    rework_order_id TEXT PRIMARY KEY,\n    workspace_id TEXT NOT NULL,\n    parent_work_order_id TEXT NOT NULL,\n    ncr_id TEXT NOT NULL,\n    item_id TEXT NOT NULL,\n    rework_quantity_scaled INTEGER NOT NULL,\n    rework_routing_steps_json TEXT NOT NULL,\n    rework_cost_center TEXT NOT NULL,\n    status TEXT NOT NULL,\n    accumulated_rework_cost_minor INTEGER NOT NULL DEFAULT 0,\n    created_at TEXT NOT NULL,\n    completed_at TEXT\n);\n"


class SqliteManufacturingQualityRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        connection.execute("SAVEPOINT quality_repository_init")
        try:
            # This owned schema contains only CREATE TABLE statements. Execute
            # each without executescript's implicit commit of the caller's UOW.
            for statement in SQLITE_QUALITY_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute("RELEASE quality_repository_init")
        except BaseException:
            connection.execute("ROLLBACK TO quality_repository_init")
            connection.execute("RELEASE quality_repository_init")
            raise

    def save_plan(self, workspace: str, plan: QualityInspectionPlan) -> None:
        self.connection.execute(
            """INSERT INTO quality_inspection_plans
            (workspace_id,plan_id,item_id,revision,name,sample_size_units,specifications_json,created_at)
            VALUES(?,?,?,?,?,?,?,datetime('now')) ON CONFLICT(workspace_id,item_id,revision) DO UPDATE SET
            name=excluded.name,sample_size_units=excluded.sample_size_units,specifications_json=excluded.specifications_json""",
            (workspace, *plan_values(plan)),
        )

    def get_plan(self, workspace: str, item_id: str, revision: str | None = None) -> QualityInspectionPlan | None:
        if revision is None:
            row = self.connection.execute(
                """SELECT plan_id,item_id,revision,name,sample_size_units,specifications_json
                FROM quality_inspection_plans WHERE workspace_id=? AND item_id=? ORDER BY created_at DESC,revision DESC LIMIT 1""",
                (workspace, item_id),
            ).fetchone()
        else:
            row = self.connection.execute(
                """SELECT plan_id,item_id,revision,name,sample_size_units,specifications_json
                FROM quality_inspection_plans WHERE workspace_id=? AND item_id=? AND revision=?""",
                (workspace, item_id, revision),
            ).fetchone()
        return plan_from_row(row) if row else None

    def create_ncr(self, workspace: str, ncr: NonConformanceReport) -> None:
        cursor = self.connection.execute(
            """INSERT INTO quality_ncrs(workspace_id,ncr_id,lot_id,work_order_id,defect_code,defect_severity,
            inspector_id,quarantined_quantity_scaled,status,disposition,disposition_notes,disposition_by,disposition_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ncr_id) DO NOTHING""",
            (workspace, *ncr_values(ncr)),
        )
        if cursor.rowcount != 1:
            raise QualityReworkError("quality_identifier_exists", "The NCR identifier already exists.")

    def get_ncr(self, workspace: str, identifier: str, *, for_update: bool = False) -> NonConformanceReport | None:
        row = self.connection.execute(
            """SELECT ncr_id,lot_id,work_order_id,defect_code,defect_severity,inspector_id,
            quarantined_quantity_scaled,status,disposition,disposition_notes,disposition_by,disposition_at,created_at
            FROM quality_ncrs WHERE workspace_id=? AND ncr_id=?""",
            (workspace, identifier),
        ).fetchone()
        return ncr_from_row(row) if row else None

    def update_ncr(self, workspace: str, ncr: NonConformanceReport) -> None:
        self.connection.execute(
            """UPDATE quality_ncrs SET status=?,disposition=?,disposition_notes=?,disposition_by=?,disposition_at=?
            WHERE workspace_id=? AND ncr_id=?""",
            (
                ncr.status,
                ncr.disposition,
                ncr.disposition_notes,
                ncr.disposition_by,
                ncr.disposition_at,
                workspace,
                ncr.ncr_id,
            ),
        )

    def ncr_rework_quantity(self, workspace: str, ncr_id: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COALESCE(SUM(rework_quantity_scaled),0) FROM quality_rework_orders WHERE workspace_id=? AND ncr_id=?",
                (workspace, ncr_id),
            ).fetchone()[0]
        )

    def create_rework(self, workspace: str, rework: ReworkOrder) -> None:
        cursor = self.connection.execute(
            """INSERT INTO quality_rework_orders(workspace_id,rework_order_id,parent_work_order_id,ncr_id,item_id,
            rework_quantity_scaled,rework_routing_steps_json,rework_cost_center,status,accumulated_rework_cost_minor,created_at,completed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(rework_order_id) DO NOTHING""",
            (workspace, *rework_values(rework)),
        )
        if cursor.rowcount != 1:
            raise QualityReworkError("quality_identifier_exists", "The rework identifier already exists.")

    def get_rework(self, workspace: str, identifier: str, *, for_update: bool = False) -> ReworkOrder | None:
        row = self.connection.execute(
            """SELECT rework_order_id,parent_work_order_id,ncr_id,item_id,rework_quantity_scaled,
            rework_routing_steps_json,rework_cost_center,status,accumulated_rework_cost_minor,created_at,completed_at
            FROM quality_rework_orders WHERE workspace_id=? AND rework_order_id=?""",
            (workspace, identifier),
        ).fetchone()
        return rework_from_row(row) if row else None

    def update_rework(self, workspace: str, rework: ReworkOrder) -> None:
        self.connection.execute(
            """UPDATE quality_rework_orders SET status=?,rework_routing_steps_json=?,accumulated_rework_cost_minor=?,completed_at=?
            WHERE workspace_id=? AND rework_order_id=?""",
            (
                rework.status,
                rework_values(rework)[5],
                rework.accumulated_rework_cost_minor,
                rework.completed_at,
                workspace,
                rework.rework_order_id,
            ),
        )
