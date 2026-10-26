"""Transaction-neutral SQLite persistence for quality workflow records."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

from reconforge.audit import append_audit_event
from reconforge.auth import LocalAuthService
from reconforge.domain.finance_posting import digest_payload
from reconforge.domain.manufacturing_quality_rework import (
    NCRDisposition,
    NonConformanceReport,
    QualityInspectionPlan,
    QualityReworkError,
    ReworkOrder,
    require_independent_quality_actor,
)
from reconforge.infrastructure.quality_actor_authority_schema import execute_quality_actor_schema
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
            execute_quality_actor_schema(connection)
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

    @contextmanager
    def _actor_mutation(self) -> Iterator[None]:
        owns = not self.connection.in_transaction
        if owns:
            self.connection.execute("BEGIN IMMEDIATE")
        self.connection.execute("SAVEPOINT quality_actor_mutation")
        try:
            yield
            self.connection.execute("RELEASE quality_actor_mutation")
            if owns:
                self.connection.commit()
        except BaseException:
            self.connection.execute("ROLLBACK TO quality_actor_mutation")
            self.connection.execute("RELEASE quality_actor_mutation")
            if owns:
                self.connection.rollback()
            raise

    def _actor(self, user_id: str, actor_label: str) -> None:
        if self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone() is None:
            raise QualityReworkError("quality_actor_identity_denied", "A persisted active quality actor is required.")
        original_factory = self.connection.row_factory
        try:
            self.connection.row_factory = sqlite3.Row
            service = LocalAuthService(self.connection)
            user = service.users.get_by_id(user_id)
            if (user is None or user.disabled or user.username != actor_label
                    or "manufacturing_execution.manage" not in service.roles.user_permissions(user.username)):
                raise QualityReworkError("quality_actor_identity_denied", "Current quality actor authority is required.")
        finally:
            self.connection.row_factory = original_factory

    def ncr_actor_id(self, workspace: str, ncr_id: str, authority_kind: str) -> str | None:
        row = self.connection.execute(
            "SELECT user_id FROM quality_ncr_actor_authorities WHERE workspace_id=? AND ncr_id=? "
            "AND authority_kind=? AND identity_contract='canonical-user-v1'",
            (workspace, ncr_id, authority_kind),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def _append_authority(self, workspace: str, ncr: NonConformanceReport, kind: str, user_id: str, label: str) -> None:
        original_factory = self.connection.row_factory
        try:
            self.connection.row_factory = sqlite3.Row
            event = append_audit_event(
                self.connection, actor_user_id=user_id, actor_label=label, object_type="quality.ncr",
                object_id=ncr.ncr_id, action="quality_ncr_recorded" if kind == "creator" else "quality_ncr_dispositioned",
                after_hash=digest_payload(asdict(ncr)),
                metadata={"workspace_id": workspace, "identity_contract": "canonical-user-v1", "scope_level": "workspace-ncr"},
            )
        finally:
            self.connection.row_factory = original_factory
        self.connection.execute(
            "INSERT INTO quality_ncr_actor_authorities(workspace_id,ncr_id,authority_kind,user_id,actor_label,identity_contract,audit_event_id) "
            "VALUES(?,?,?,?,?,'canonical-user-v1',?)", (workspace, ncr.ncr_id, kind, user_id, label, event.id),
        )

    def create_ncr(
        self, workspace: str, ncr: NonConformanceReport, *, creator_user_id: str | None = None, actor_label: str | None = None,
    ) -> None:
        if creator_user_id is None:
            self._insert_ncr(workspace, ncr)
            return
        with self._actor_mutation():
            self._actor(creator_user_id, actor_label or "")
            self._insert_ncr(workspace, ncr)
            self._append_authority(workspace, ncr, "creator", creator_user_id, actor_label or "")

    def _insert_ncr(self, workspace: str, ncr: NonConformanceReport) -> None:
        cursor = self.connection.execute(
            """INSERT INTO quality_ncrs(workspace_id,ncr_id,lot_id,work_order_id,defect_code,defect_severity,
            inspector_id,quarantined_quantity_scaled,status,disposition,disposition_notes,disposition_by,disposition_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ncr_id) DO NOTHING""",
            (workspace, *ncr_values(ncr)),
        )
        if cursor.rowcount != 1:
            raise QualityReworkError("quality_identifier_exists", "The NCR identifier already exists.")

    def disposition_ncr(
        self, workspace: str, ncr_id: str, *, disposition: NCRDisposition, notes: str,
        actor_user_id: str, actor_label: str,
    ) -> NonConformanceReport:
        with self._actor_mutation():
            self._actor(actor_user_id, actor_label)
            ncr = self.get_ncr(workspace, ncr_id, for_update=True)
            if ncr is None:
                raise QualityReworkError("quality_ncr_not_found", "NCR not found in the selected workspace.")
            require_independent_quality_actor(self.ncr_actor_id(workspace, ncr_id, "creator"), actor_user_id)
            updated = ncr.disposition_ncr(disposition=disposition, notes=notes, actor=actor_label)
            self.update_ncr(workspace, updated)
            self._append_authority(workspace, updated, "reviewer", actor_user_id, actor_label)
            return updated

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
