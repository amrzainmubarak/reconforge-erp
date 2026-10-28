"""Scoped PostgreSQL persistence for inspection, NCR and rework records.

The repository records the quality workflow. Inventory and ledger effects remain
owned by the corresponding native posting contracts, never direct SQL here.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from typing import Any

from reconforge.domain.finance_posting import digest_payload
from reconforge.domain.manufacturing_quality_rework import (
    NCRDisposition,
    NonConformanceReport,
    QualityInspectionPlan,
    QualityReworkError,
    ReworkOrder,
    require_independent_quality_actor,
)
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
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


def _same_persisted_decision(left: NonConformanceReport, right: NonConformanceReport) -> bool:
    """Compare every field, interpreting timestamp offsets as the same instant."""
    left_values, right_values = asdict(left), asdict(right)
    for field in ("created_at", "disposition_at"):
        first, second = left_values.pop(field), right_values.pop(field)
        if first is None or second is None:
            if first != second:
                return False
            continue
        try:
            a, b = datetime.fromisoformat(first), datetime.fromisoformat(second)
            if a.utcoffset() is None or b.utcoffset() is None or a != b:
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return left_values == right_values


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

    def _actor(self, workspace: str, user_id: str, label: str) -> None:
        identity = self._scoped_execute(
            "SELECT username FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND NOT disabled FOR SHARE",
            (self.tenant_id, user_id),
        ).fetchone()
        if identity is None or identity[0] != label:
            raise QualityReworkError("quality_actor_identity_denied", "A persisted active quality actor is required.")
        scope = self.connection.execute(
            "SELECT current_setting('app.organization_id',true) AS organization_id, "
            "current_setting('app.legal_entity_id',true) AS legal_entity_id",
        ).fetchone()
        if scope is None or not scope[0] or not scope[1]:
            raise QualityReworkError("quality_actor_identity_denied", "An explicit quality actor hierarchy is required.")
        try:
            self.connection.execute(
                "SELECT reconforge.hc_actor(%s,%s,%s,%s,%s,%s)",
                (self.tenant_id, workspace, scope[0], scope[1], user_id, "manufacturing_execution.manage"),
            )
        except Exception as exc:
            if getattr(exc, "sqlstate", None) != "23514":
                raise
            raise QualityReworkError("quality_actor_identity_denied", "Current quality actor authority is required.") from None

    def ncr_actor_id(self, workspace: str, ncr_id: str, authority_kind: str) -> str | None:
        row = self._scoped_execute(
            "SELECT user_id FROM reconforge.quality_ncr_actor_authorities WHERE tenant_id=%s AND workspace_id=%s "
            "AND ncr_id=%s AND authority_kind=%s AND identity_contract='canonical-user-v1'",
            (self.tenant_id, workspace, ncr_id, authority_kind),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def _append_authority(self, workspace: str, ncr: NonConformanceReport, kind: str, user_id: str, label: str) -> None:
        scope = self.connection.execute(
            "SELECT current_setting('app.organization_id',true) AS organization_id, "
            "current_setting('app.legal_entity_id',true) AS legal_entity_id",
        ).fetchone()
        event = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_user_id=user_id, actor_label=label, object_type="quality.ncr", object_id=ncr.ncr_id,
            action="quality_ncr_recorded" if kind == "creator" else "quality_ncr_dispositioned",
            after_hash=digest_payload(asdict(ncr)), metadata={
                "workspace_id": workspace, "identity_contract": "canonical-user-v1", "scope_level": "workspace-ncr",
                "actor_organization_id": scope[0], "actor_legal_entity_id": scope[1],
            },
        )
        self._scoped_execute(
            "INSERT INTO reconforge.quality_ncr_actor_authorities"
            "(tenant_id,workspace_id,ncr_id,authority_kind,user_id,actor_label,identity_contract,audit_event_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,'canonical-user-v1',%s)",
            (self.tenant_id, workspace, ncr.ncr_id, kind, user_id, label, event.id),
        )

    def create_ncr(
        self, workspace: str, ncr: NonConformanceReport, *, creator_user_id: str | None = None, actor_label: str | None = None,
    ) -> None:
        if creator_user_id is None:
            self._insert_ncr(workspace, ncr)
            return
        with self.connection.transaction():
            self._actor(workspace, creator_user_id, actor_label or "")
            self._insert_ncr(workspace, ncr)
            self._append_authority(workspace, ncr, "creator", creator_user_id, actor_label or "")

    def _insert_ncr(self, workspace: str, ncr: NonConformanceReport) -> None:
        cursor = self._scoped_execute(
            """INSERT INTO reconforge.quality_ncrs(tenant_id,workspace_id,ncr_id,lot_id,work_order_id,defect_code,defect_severity,
            inspector_id,quarantined_quantity_scaled,status,disposition,disposition_notes,disposition_by,disposition_at,created_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,workspace_id,ncr_id) DO NOTHING""",
            (self.tenant_id, workspace, *ncr_values(ncr)),
        )
        if cursor.rowcount != 1:
            raise QualityReworkError("quality_identifier_exists", "The NCR identifier already exists.")

    def disposition_ncr(
        self, workspace: str, ncr_id: str, *, disposition: NCRDisposition, notes: str,
        actor_user_id: str, actor_label: str,
    ) -> NonConformanceReport:
        with self.connection.transaction():
            self._actor(workspace, actor_user_id, actor_label)
            ncr = self.get_ncr(workspace, ncr_id, for_update=True)
            if ncr is None:
                raise QualityReworkError("quality_ncr_not_found", "NCR not found in the selected workspace.")
            require_independent_quality_actor(self.ncr_actor_id(workspace, ncr_id, "creator"), actor_user_id)
            updated = ncr.disposition_ncr(disposition=disposition, notes=notes, actor=actor_label)
            self._append_authority(workspace, updated, "reviewer", actor_user_id, actor_label)
            self.update_ncr(workspace, updated)
            return updated

    def get_ncr(self, workspace: str, identifier: str, *, for_update: bool = False) -> NonConformanceReport | None:
        query = """SELECT ncr_id,lot_id,work_order_id,defect_code,defect_severity,inspector_id,
            quarantined_quantity_scaled,status,disposition,disposition_notes,disposition_by,disposition_at,created_at
            FROM reconforge.quality_ncrs WHERE workspace_id=%s AND ncr_id=%s"""
        row = self._scoped_execute(
            "".join((query, " FOR UPDATE" if for_update else "")), (workspace, identifier)
        ).fetchone()
        return ncr_from_row(row) if row else None

    def update_ncr(self, workspace: str, ncr: NonConformanceReport) -> None:
        # A committed identical decision is a read-only replay. Lock the row
        # first, and do not recompute or replace its historical audit hash.
        current = self.get_ncr(workspace, ncr.ncr_id, for_update=True)
        if current is not None and current.status == "dispositioned" and _same_persisted_decision(current, ncr):
            return
        if current is None:
            raise QualityReworkError("quality_ncr_not_found", "NCR not found in the selected workspace.")
        candidate = replace(
            current, status=ncr.status, disposition=ncr.disposition,
            disposition_notes=ncr.disposition_notes, disposition_by=ncr.disposition_by,
            disposition_at=ncr.disposition_at,
        )
        if (
            current.status not in ("open", "under_review")
            or ncr.status != "dispositioned"
            or not _same_persisted_decision(candidate, ncr)
        ):
            raise QualityReworkError("quality_ncr_transition_invalid", "The NCR decision is not a valid current transition.")
        # An NCR decision must be backed by its immutable independent reviewer
        # and the audit hash of this exact decision. The normal disposition
        # path stages both in the same transaction before reaching this method.
        payload = asdict(ncr)
        hashes = {digest_payload(payload)}
        if ncr.disposition_at and ncr.disposition_at.endswith("+00:00"):
            hashes.add(digest_payload({**payload, "disposition_at": ncr.disposition_at[:-6] + "Z"}))
        authority = self._scoped_execute(
            """SELECT 1 FROM reconforge.quality_ncr_actor_authorities reviewer
            JOIN reconforge.quality_ncr_actor_authorities creator
              ON creator.tenant_id=reviewer.tenant_id AND creator.workspace_id=reviewer.workspace_id
             AND creator.ncr_id=reviewer.ncr_id AND creator.authority_kind='creator'
            JOIN reconforge.domain_audit_events event
              ON event.tenant_id=reviewer.tenant_id AND event.id=reviewer.audit_event_id
            WHERE reviewer.tenant_id=%s AND reviewer.workspace_id=%s AND reviewer.ncr_id=%s
              AND reviewer.authority_kind='reviewer' AND reviewer.user_id<>creator.user_id
              AND reviewer.actor_label=%s AND event.actor_user_id=reviewer.user_id
              AND event.actor_label=reviewer.actor_label AND event.object_type='quality.ncr'
              AND event.object_id=reviewer.ncr_id AND event.action='quality_ncr_dispositioned'
              AND event.metadata_json->>'workspace_id'=reviewer.workspace_id
              AND event.after_hash=ANY(%s)""",
            (self.tenant_id, workspace, ncr.ncr_id, ncr.disposition_by, list(hashes)),
        ).fetchone()
        if authority is None:
            raise QualityReworkError("quality_actor_authority_missing", "An independently audited NCR decision is required.")
        cursor = self._scoped_execute(
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
        if cursor.rowcount != 1:
            raise QualityReworkError("quality_ncr_not_found", "NCR not found in the selected workspace.")

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
