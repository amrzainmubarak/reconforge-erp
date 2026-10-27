"""PostgreSQL tenant/workspace-scoped persistence for Master Production Scheduling (MPS) and sourcing with FORCE RLS."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from reconforge.domain.master_production_schedule import MPSPlanResult
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope as set_local_tenant_scope
from reconforge.platform.common import PlatformError

POSTGRES_MPS_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.mps_plans (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_name TEXT NOT NULL,
    revision TEXT NOT NULL,
    item_id TEXT NOT NULL,
    unit_of_measure TEXT NOT NULL,
    quantity_scale INTEGER NOT NULL,
    safety_stock_scaled BIGINT NOT NULL,
    lot_size_multiple_scaled BIGINT NOT NULL,
    opening_inventory_scaled BIGINT NOT NULL,
    plan_digest TEXT NOT NULL,
    plan_payload JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, plan_id, revision)
);
ALTER TABLE reconforge.mps_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.mps_plans FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.mps_plans;
CREATE POLICY tenant_scope ON reconforge.mps_plans
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.mps_sourcing_requisitions (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    requisition_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    plan_revision TEXT NOT NULL,
    item_id TEXT NOT NULL,
    bucket_index INTEGER NOT NULL,
    required_date DATE NOT NULL,
    shortage_quantity_scaled BIGINT NOT NULL,
    order_quantity_scaled BIGINT NOT NULL,
    preferred_supplier_id TEXT NOT NULL,
    unit_price_ceiling_minor BIGINT NOT NULL,
    currency TEXT NOT NULL,
    requisition_digest TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'APPROVED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, workspace_id, requisition_id),
    UNIQUE (tenant_id, workspace_id, plan_id, plan_revision, item_id, bucket_index)
);
ALTER TABLE reconforge.mps_sourcing_requisitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.mps_sourcing_requisitions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.mps_sourcing_requisitions;
CREATE POLICY tenant_scope ON reconforge.mps_sourcing_requisitions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresMPSRepository:
    """Enterprise PostgreSQL repository with FORCE RLS for Master Production Schedules and procurement requisitions."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def save_plan(
        self,
        *,
        workspace_id: str,
        plan_result: MPSPlanResult,
        created_by: str = "system",
    ) -> str:
        record_id = f"mps_{plan_result.plan_id}_{plan_result.revision}"
        now = utc_now_text()
        payload_str = json.dumps(asdict(plan_result), sort_keys=True)

        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.mps_plans (
                        tenant_id, id, workspace_id, plan_id, plan_name, revision,
                        item_id, unit_of_measure, quantity_scale, safety_stock_scaled,
                        lot_size_multiple_scaled, opening_inventory_scaled,
                        plan_digest, plan_payload, created_by, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, plan_id, revision) DO UPDATE SET
                        plan_name = excluded.plan_name,
                        plan_payload = excluded.plan_payload,
                        plan_digest = excluded.plan_digest
                    """,
                    (
                        self.tenant_id,
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
                        payload_str,
                        created_by,
                        now,
                    ),
                )

                for pr in plan_result.sourcing_requisitions:
                    pr_id = f"pr_{pr.requisition_id}"
                    self.connection.execute(
                        """
                        INSERT INTO reconforge.mps_sourcing_requisitions (
                            tenant_id, id, workspace_id, requisition_id, plan_id, plan_revision,
                            item_id, bucket_index, required_date, shortage_quantity_scaled,
                            order_quantity_scaled, preferred_supplier_id, unit_price_ceiling_minor,
                            currency, requisition_digest, status, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'APPROVED', %s)
                        ON CONFLICT (tenant_id, workspace_id, requisition_id) DO UPDATE SET
                            order_quantity_scaled = excluded.order_quantity_scaled
                        """,
                        (
                            self.tenant_id,
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

                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=created_by,
                    actor_user_id=created_by,
                    object_type="mps_plan",
                    object_id=plan_result.plan_id,
                    action="mps_plan_computed",
                    after_hash=plan_result.plan_digest,
                    metadata={
                        "revision": plan_result.revision,
                        "item_id": plan_result.item_id,
                        "rows_count": len(plan_result.schedule_rows),
                        "requisitions_count": len(plan_result.sourcing_requisitions),
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL MPS plan save failed: {exc}") from exc

        return record_id

    def get_plan(self, *, workspace_id: str, plan_id: str, revision: str) -> dict[str, Any] | None:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT id, workspace_id, plan_id, plan_name, revision,
                           item_id, unit_of_measure, quantity_scale, safety_stock_scaled,
                           lot_size_multiple_scaled, opening_inventory_scaled,
                           plan_digest, plan_payload, created_by, created_at
                    FROM reconforge.mps_plans
                    WHERE tenant_id = %s AND workspace_id = %s AND plan_id = %s AND revision = %s
                    """,
                    (self.tenant_id, workspace_id, plan_id, revision),
                )
                row = cur.fetchone()
                if not row:
                    return None
                payload = row[12]
                if isinstance(payload, str):
                    payload = json.loads(payload)
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
                    "plan": payload,
                    "created_by": row[13],
                    "created_at": str(row[14]),
                }
        except Exception as exc:
            raise PlatformError(f"PostgreSQL get MPS plan failed: {exc}") from exc

    def list_plans(self, *, workspace_id: str, item_id: str | None = None) -> list[dict[str, Any]]:
        try:
            with self.connection.transaction():
                self._scope()
                if item_id:
                    cur = self.connection.execute(
                        """
                        SELECT id, workspace_id, plan_id, plan_name, revision,
                               item_id, unit_of_measure, quantity_scale, safety_stock_scaled,
                               lot_size_multiple_scaled, opening_inventory_scaled,
                               plan_digest, plan_payload, created_by, created_at
                        FROM reconforge.mps_plans
                        WHERE tenant_id = %s AND workspace_id = %s AND item_id = %s
                        ORDER BY created_at DESC
                        """,
                        (self.tenant_id, workspace_id, item_id),
                    )
                else:
                    cur = self.connection.execute(
                        """
                        SELECT id, workspace_id, plan_id, plan_name, revision,
                               item_id, unit_of_measure, quantity_scale, safety_stock_scaled,
                               lot_size_multiple_scaled, opening_inventory_scaled,
                               plan_digest, plan_payload, created_by, created_at
                        FROM reconforge.mps_plans
                        WHERE tenant_id = %s AND workspace_id = %s
                        ORDER BY created_at DESC
                        """,
                        (self.tenant_id, workspace_id),
                    )
                rows = cur.fetchall()
                results = []
                for r in rows:
                    payload = r[12]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    results.append({
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
                        "plan": payload,
                        "created_by": r[13],
                        "created_at": str(r[14]),
                    })
                return results
        except Exception as exc:
            raise PlatformError(f"PostgreSQL list MPS plans failed: {exc}") from exc

    def list_requisitions(
        self,
        *,
        workspace_id: str,
        plan_id: str | None = None,
        item_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            with self.connection.transaction():
                self._scope()
                conditions = ["tenant_id = %s", "workspace_id = %s"]
                params: list[Any] = [self.tenant_id, workspace_id]
                if plan_id:
                    conditions.append("plan_id = %s")
                    params.append(plan_id)
                if item_id:
                    conditions.append("item_id = %s")
                    params.append(item_id)
                where_clause = " AND ".join(conditions)
                cur = self.connection.execute(
                    "".join(("""
                    SELECT id, workspace_id, requisition_id, plan_id, plan_revision,
                           item_id, bucket_index, required_date, shortage_quantity_scaled,
                           order_quantity_scaled, preferred_supplier_id, unit_price_ceiling_minor,
                           currency, requisition_digest, status, created_at
                    FROM reconforge.mps_sourcing_requisitions
                    WHERE """, (where_clause), """
                    ORDER BY bucket_index ASC
                    """)),
                    tuple(params),
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
                        "required_date": str(r[7]),
                        "shortage_quantity_scaled": r[8],
                        "order_quantity_scaled": r[9],
                        "preferred_supplier_id": r[10],
                        "unit_price_ceiling_minor": r[11],
                        "currency": r[12],
                        "requisition_digest": r[13],
                        "status": r[14],
                        "created_at": str(r[15]),
                    }
                    for r in rows
                ]
        except Exception as exc:
            raise PlatformError(f"PostgreSQL list requisitions failed: {exc}") from exc
