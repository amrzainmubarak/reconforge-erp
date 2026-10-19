"""PostgreSQL tenant/workspace-scoped persistence for manufacturing shop-floor execution and lot genealogy with FORCE RLS."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from reconforge.domain.shop_floor_dispatch import (
    GenealogyNode,
    LotTraceabilityRecord,
    ShopFloorOperationStep,
    WorkOrderDispatch,
    traverse_genealogy,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.platform.common import PlatformError

POSTGRES_SHOP_FLOOR_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.shop_floor_lots (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    batch_number TEXT NOT NULL,
    quantity_scaled BIGINT NOT NULL,
    scale_factor INTEGER NOT NULL DEFAULT 1000,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, lot_id)
);
ALTER TABLE reconforge.shop_floor_lots ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_lots FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_lots;
CREATE POLICY tenant_scope ON reconforge.shop_floor_lots
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.shop_floor_lot_genealogy (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    parent_lot_id TEXT NOT NULL,
    child_lot_id TEXT NOT NULL,
    quantity_consumed_scaled BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, parent_lot_id, child_lot_id)
);
ALTER TABLE reconforge.shop_floor_lot_genealogy ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_lot_genealogy FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_lot_genealogy;
CREATE POLICY tenant_scope ON reconforge.shop_floor_lot_genealogy
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.shop_floor_dispatches (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    scheduled_quantity_scaled BIGINT NOT NULL,
    dispatched_lot_id TEXT NOT NULL,
    dispatched_at TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, dispatch_id)
);
ALTER TABLE reconforge.shop_floor_dispatches ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_dispatches FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_dispatches;
CREATE POLICY tenant_scope ON reconforge.shop_floor_dispatches
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.shop_floor_steps (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    work_order_id TEXT NOT NULL,
    operation_sequence INTEGER NOT NULL,
    work_center_id TEXT NOT NULL,
    operator_id TEXT NOT NULL,
    status TEXT NOT NULL,
    actual_run_minutes INTEGER NOT NULL,
    quantity_completed_scaled BIGINT NOT NULL,
    quantity_scrapped_scaled BIGINT NOT NULL,
    scrap_reason_code TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, step_id)
);
ALTER TABLE reconforge.shop_floor_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.shop_floor_steps FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.shop_floor_steps;
CREATE POLICY tenant_scope ON reconforge.shop_floor_steps
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""


class PostgresShopFloorRepository:
    """Enterprise PostgreSQL repository with FORCE RLS for manufacturing execution and genealogy."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def register_lot(
        self,
        lot: LotTraceabilityRecord,
        parent_lots: list[tuple[str, int]] | None = None,
        *,
        actor_label: str = "system",
    ) -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.shop_floor_lots (
                        tenant_id, workspace_id, lot_id, item_id, batch_number,
                        quantity_scaled, scale_factor, status, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, lot_id) DO UPDATE SET
                        quantity_scaled = excluded.quantity_scaled,
                        status = excluded.status,
                        notes = excluded.notes
                    """,
                    (
                        self.tenant_id,
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
                        self.connection.execute(
                            """
                            INSERT INTO reconforge.shop_floor_lot_genealogy (
                                tenant_id, workspace_id, parent_lot_id, child_lot_id, quantity_consumed_scaled
                            ) VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (tenant_id, workspace_id, parent_lot_id, child_lot_id) DO UPDATE SET
                                quantity_consumed_scaled = excluded.quantity_consumed_scaled
                            """,
                            (self.tenant_id, lot.workspace_id, parent_id, lot.lot_id, qty),
                        )

                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="shop_floor_lot",
                    object_id=lot.lot_id,
                    action="lot_registered",
                    after_hash=hashlib.sha256(f"{lot.lot_id}:{lot.quantity_scaled}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": lot.workspace_id,
                        "item_id": lot.item_id,
                        "batch_number": lot.batch_number,
                        "status": lot.status,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL lot registration failed: {exc}") from exc

    def get_lot(self, workspace_id: str, lot_id: str) -> LotTraceabilityRecord | None:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT workspace_id, lot_id, item_id, batch_number,
                           quantity_scaled, scale_factor, status, notes
                    FROM reconforge.shop_floor_lots
                    WHERE tenant_id = %s AND workspace_id = %s AND lot_id = %s
                    """,
                    (self.tenant_id, workspace_id, lot_id),
                )
                row = cur.fetchone()
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
        except Exception as exc:
            raise PlatformError(f"PostgreSQL lot read failed: {exc}") from exc

    def save_dispatch(
        self,
        dispatch: WorkOrderDispatch,
        *,
        actor_label: str = "system",
    ) -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.shop_floor_dispatches (
                        tenant_id, workspace_id, dispatch_id, work_order_id,
                        item_id, scheduled_quantity_scaled, dispatched_lot_id, dispatched_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, dispatch_id) DO UPDATE SET
                        scheduled_quantity_scaled = excluded.scheduled_quantity_scaled,
                        dispatched_lot_id = excluded.dispatched_lot_id
                    """,
                    (
                        self.tenant_id,
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
                    self._save_step_in_tx(dispatch.workspace_id, step)

                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="shop_floor_dispatch",
                    object_id=dispatch.dispatch_id,
                    action="order_dispatched",
                    after_hash=hashlib.sha256(f"{dispatch.dispatch_id}:{dispatch.scheduled_quantity_scaled}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": dispatch.workspace_id,
                        "work_order_id": dispatch.work_order_id,
                        "item_id": dispatch.item_id,
                        "scheduled_quantity_scaled": dispatch.scheduled_quantity_scaled,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL dispatch failed: {exc}") from exc

    def _save_step_in_tx(self, workspace_id: str, step: ShopFloorOperationStep) -> None:
        self.connection.execute(
            """
            INSERT INTO reconforge.shop_floor_steps (
                tenant_id, workspace_id, step_id, work_order_id, operation_sequence,
                work_center_id, operator_id, status, actual_run_minutes,
                quantity_completed_scaled, quantity_scrapped_scaled,
                scrap_reason_code, started_at, completed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tenant_id, workspace_id, step_id) DO UPDATE SET
                status = excluded.status,
                actual_run_minutes = excluded.actual_run_minutes,
                quantity_completed_scaled = excluded.quantity_completed_scaled,
                quantity_scrapped_scaled = excluded.quantity_scrapped_scaled,
                scrap_reason_code = excluded.scrap_reason_code,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at
            """,
            (
                self.tenant_id,
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

    def save_step(
        self,
        workspace_id: str,
        step: ShopFloorOperationStep,
        *,
        actor_label: str = "system",
    ) -> None:
        try:
            with self.connection.transaction():
                self._scope()
                self._save_step_in_tx(workspace_id, step)
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor_label,
                    actor_user_id=actor_label,
                    object_type="shop_floor_step",
                    object_id=step.step_id,
                    action="step_progressed",
                    after_hash=hashlib.sha256(f"{step.step_id}:{step.quantity_completed_scaled}".encode()).hexdigest(),
                    metadata={
                        "workspace_id": workspace_id,
                        "work_order_id": step.work_order_id,
                        "operation_sequence": step.operation_sequence,
                        "status": step.status,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL step save failed: {exc}") from exc

    def get_dispatch(self, workspace_id: str, dispatch_id: str) -> WorkOrderDispatch | None:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT workspace_id, dispatch_id, work_order_id, item_id,
                           scheduled_quantity_scaled, dispatched_lot_id, dispatched_at
                    FROM reconforge.shop_floor_dispatches
                    WHERE tenant_id = %s AND workspace_id = %s AND dispatch_id = %s
                    """,
                    (self.tenant_id, workspace_id, dispatch_id),
                )
                row = cur.fetchone()
                if not row:
                    return None

                step_cur = self.connection.execute(
                    """
                    SELECT step_id, work_order_id, operation_sequence,
                           work_center_id, operator_id, status, actual_run_minutes,
                           quantity_completed_scaled, quantity_scrapped_scaled,
                           scrap_reason_code, started_at, completed_at
                    FROM reconforge.shop_floor_steps
                    WHERE tenant_id = %s AND workspace_id = %s AND work_order_id = %s
                    ORDER BY operation_sequence ASC
                    """,
                    (self.tenant_id, workspace_id, row[2]),
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
                    for s in step_cur.fetchall()
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
        except Exception as exc:
            raise PlatformError(f"PostgreSQL get dispatch failed: {exc}") from exc

    def get_genealogy_edges(self, workspace_id: str) -> list[tuple[str, str, int]]:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT parent_lot_id, child_lot_id, quantity_consumed_scaled
                    FROM reconforge.shop_floor_lot_genealogy
                    WHERE tenant_id = %s AND workspace_id = %s
                    """,
                    (self.tenant_id, workspace_id),
                )
                return [(r[0], r[1], int(r[2])) for r in cur.fetchall()]
        except Exception as exc:
            raise PlatformError(f"PostgreSQL get genealogy edges failed: {exc}") from exc

    def get_lot_item_map(self, workspace_id: str) -> dict[str, str]:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT lot_id, item_id
                    FROM reconforge.shop_floor_lots
                    WHERE tenant_id = %s AND workspace_id = %s
                    """,
                    (self.tenant_id, workspace_id),
                )
                return {r[0]: r[1] for r in cur.fetchall()}
        except Exception as exc:
            raise PlatformError(f"PostgreSQL get lot item map failed: {exc}") from exc

    def traverse(
        self,
        workspace_id: str,
        root_lot_id: str,
        direction: Literal["forward", "backward"],
        max_depth: int = 20,
    ) -> GenealogyNode:
        edges = self.get_genealogy_edges(workspace_id)
        lot_item_map = self.get_lot_item_map(workspace_id)
        return traverse_genealogy(
            root_lot_id=root_lot_id,
            edges=edges,
            lot_item_map=lot_item_map,
            direction=direction,
            max_depth=max_depth,
        )


__all__ = [
    "POSTGRES_SHOP_FLOOR_SCHEMA_SQL",
    "PostgresShopFloorRepository",
]
