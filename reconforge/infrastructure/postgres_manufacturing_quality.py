"""Scoped PostgreSQL persistence for inspection, NCR and rework records.

The repository records the quality workflow. Inventory and ledger effects remain
owned by the corresponding native posting contracts, never direct SQL here.
"""

from __future__ import annotations

from typing import Any

from reconforge.domain.manufacturing_quality_rework import (
    NonConformanceReport,
    QualityInspectionPlan,
    QualityReworkError,
    ReworkOrder,
)
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.infrastructure.quality_records import (
    ncr_from_row,
    ncr_values,
    plan_from_row,
    plan_values,
    rework_from_row,
    rework_values,
)

POSTGRES_MANUFACTURING_QUALITY_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.quality_inspection_plans (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    name TEXT NOT NULL,
    sample_size_units INTEGER NOT NULL CHECK (sample_size_units > 0),
    specifications_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, plan_id),
    UNIQUE (tenant_id, workspace_id, item_id, revision)
);
CREATE TABLE IF NOT EXISTS reconforge.quality_ncrs (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    ncr_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    defect_code TEXT NOT NULL,
    defect_severity TEXT NOT NULL,
    inspector_id TEXT NOT NULL,
    quarantined_quantity_scaled BIGINT NOT NULL CHECK (quarantined_quantity_scaled > 0),
    status TEXT NOT NULL,
    disposition TEXT,
    disposition_notes TEXT,
    disposition_by TEXT,
    disposition_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, ncr_id)
);
CREATE TABLE IF NOT EXISTS reconforge.quality_rework_orders (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    rework_order_id TEXT NOT NULL,
    parent_work_order_id TEXT NOT NULL,
    ncr_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    rework_quantity_scaled BIGINT NOT NULL CHECK (rework_quantity_scaled > 0),
    rework_routing_steps_json TEXT NOT NULL,
    rework_cost_center TEXT NOT NULL,
    status TEXT NOT NULL,
    accumulated_rework_cost_minor BIGINT NOT NULL DEFAULT 0 CHECK (accumulated_rework_cost_minor >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, workspace_id, rework_order_id),
    FOREIGN KEY (tenant_id, workspace_id, ncr_id)
        REFERENCES reconforge.quality_ncrs(tenant_id, workspace_id, ncr_id)
);
ALTER TABLE reconforge.quality_inspection_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_inspection_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_inspection_plans;
CREATE POLICY tenant_scope ON reconforge.quality_inspection_plans
    USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));
ALTER TABLE reconforge.quality_ncrs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_ncrs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_ncrs;
CREATE POLICY tenant_scope ON reconforge.quality_ncrs
    USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));
ALTER TABLE reconforge.quality_rework_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.quality_rework_orders FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.quality_rework_orders;
CREATE POLICY tenant_scope ON reconforge.quality_rework_orders
    USING (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id',true) AND workspace_id = current_setting('app.workspace_id',true));
CREATE INDEX IF NOT EXISTS idx_quality_plan_scope_item
    ON reconforge.quality_inspection_plans(tenant_id,workspace_id,item_id,created_at);
CREATE INDEX IF NOT EXISTS idx_quality_ncr_scope_lot
    ON reconforge.quality_ncrs(tenant_id,workspace_id,lot_id,status);
CREATE INDEX IF NOT EXISTS idx_quality_rework_scope_ncr
    ON reconforge.quality_rework_orders(tenant_id,workspace_id,ncr_id,status);
"""


class PostgresManufacturingQualityRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scoped_execute(self, query: str, values: tuple[object, ...]) -> Any:
        ensure_repository_tenant_scope(self.connection, self.tenant_id)
        return self.connection.execute(query, values)

    def save_plan(self, workspace: str, plan: QualityInspectionPlan) -> None:
        self._scoped_execute(
            """INSERT INTO reconforge.quality_inspection_plans
            (tenant_id,workspace_id,plan_id,item_id,revision,name,sample_size_units,specifications_json,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT(tenant_id,workspace_id,item_id,revision) DO UPDATE SET
            name=excluded.name,sample_size_units=excluded.sample_size_units,specifications_json=excluded.specifications_json""",
            (self.tenant_id, workspace, *plan_values(plan)),
        )

    def get_plan(self, workspace: str, item_id: str, revision: str | None = None) -> QualityInspectionPlan | None:
        if revision is None:
            row = self._scoped_execute(
                """SELECT plan_id,item_id,revision,name,sample_size_units,specifications_json
                FROM reconforge.quality_inspection_plans WHERE workspace_id=%s AND item_id=%s ORDER BY created_at DESC,revision DESC LIMIT 1""",
                (workspace, item_id),
            ).fetchone()
        else:
            row = self._scoped_execute(
                """SELECT plan_id,item_id,revision,name,sample_size_units,specifications_json
                FROM reconforge.quality_inspection_plans WHERE workspace_id=%s AND item_id=%s AND revision=%s""",
                (workspace, item_id, revision),
            ).fetchone()
        return plan_from_row(row) if row else None

    def create_ncr(self, workspace: str, ncr: NonConformanceReport) -> None:
        cursor = self._scoped_execute(
            """INSERT INTO reconforge.quality_ncrs(tenant_id,workspace_id,ncr_id,lot_id,work_order_id,defect_code,defect_severity,
            inspector_id,quarantined_quantity_scaled,status,disposition,disposition_notes,disposition_by,disposition_at,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,workspace_id,ncr_id) DO NOTHING""",
            (self.tenant_id, workspace, *ncr_values(ncr)),
        )
        if cursor.rowcount != 1:
            raise QualityReworkError("quality_identifier_exists", "The NCR identifier already exists.")

    def get_ncr(self, workspace: str, identifier: str, *, for_update: bool = False) -> NonConformanceReport | None:
        query = """SELECT ncr_id,lot_id,work_order_id,defect_code,defect_severity,inspector_id,
            quarantined_quantity_scaled,status,disposition,disposition_notes,disposition_by,disposition_at,created_at
            FROM reconforge.quality_ncrs WHERE workspace_id=%s AND ncr_id=%s"""
        row = self._scoped_execute(
            "".join((query, " FOR UPDATE" if for_update else "")), (workspace, identifier)
        ).fetchone()
        return ncr_from_row(row) if row else None

    def update_ncr(self, workspace: str, ncr: NonConformanceReport) -> None:
        self._scoped_execute(
            """UPDATE reconforge.quality_ncrs SET status=%s,disposition=%s,disposition_notes=%s,disposition_by=%s,disposition_at=%s
            WHERE workspace_id=%s AND ncr_id=%s""",
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
            self._scoped_execute(
                "SELECT COALESCE(SUM(rework_quantity_scaled),0) FROM reconforge.quality_rework_orders WHERE workspace_id=%s AND ncr_id=%s",
                (workspace, ncr_id),
            ).fetchone()[0]
        )

    def create_rework(self, workspace: str, rework: ReworkOrder) -> None:
        cursor = self._scoped_execute(
            """INSERT INTO reconforge.quality_rework_orders(tenant_id,workspace_id,rework_order_id,parent_work_order_id,ncr_id,item_id,
            rework_quantity_scaled,rework_routing_steps_json,rework_cost_center,status,accumulated_rework_cost_minor,created_at,completed_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,workspace_id,rework_order_id) DO NOTHING""",
            (self.tenant_id, workspace, *rework_values(rework)),
        )
        if cursor.rowcount != 1:
            raise QualityReworkError("quality_identifier_exists", "The rework identifier already exists.")

    def get_rework(self, workspace: str, identifier: str, *, for_update: bool = False) -> ReworkOrder | None:
        query = """SELECT rework_order_id,parent_work_order_id,ncr_id,item_id,rework_quantity_scaled,
            rework_routing_steps_json,rework_cost_center,status,accumulated_rework_cost_minor,created_at,completed_at
            FROM reconforge.quality_rework_orders WHERE workspace_id=%s AND rework_order_id=%s"""
        row = self._scoped_execute(
            "".join((query, " FOR UPDATE" if for_update else "")), (workspace, identifier)
        ).fetchone()
        return rework_from_row(row) if row else None

    def update_rework(self, workspace: str, rework: ReworkOrder) -> None:
        self._scoped_execute(
            """UPDATE reconforge.quality_rework_orders SET status=%s,rework_routing_steps_json=%s,accumulated_rework_cost_minor=%s,completed_at=%s
            WHERE workspace_id=%s AND rework_order_id=%s""",
            (
                rework.status,
                rework_values(rework)[5],
                rework.accumulated_rework_cost_minor,
                rework.completed_at,
                workspace,
                rework.rework_order_id,
            ),
        )
