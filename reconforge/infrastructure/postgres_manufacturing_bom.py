"""PostgreSQL enterprise persistence with FORCE RLS for Bills of Materials and MRP Explosion."""

from __future__ import annotations

from typing import Any

from reconforge.domain.manufacturing_bom_explosion import (
    BillOfMaterials,
    BOMComponentLine,
    BOMExplosionEngine,
)
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.platform.common import PlatformError

POSTGRES_BOM_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.manufacturing_boms (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    bom_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    base_quantity INTEGER NOT NULL DEFAULT 1,
    eco_number TEXT,
    change_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, item_id, revision),
    UNIQUE (tenant_id, workspace_id, bom_id)
);
ALTER TABLE reconforge.manufacturing_boms ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.manufacturing_boms FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.manufacturing_boms;
CREATE POLICY tenant_scope ON reconforge.manufacturing_boms
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE TABLE IF NOT EXISTS reconforge.manufacturing_bom_components (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    bom_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    component_item_id TEXT NOT NULL,
    component_name TEXT NOT NULL,
    component_type TEXT NOT NULL,
    quantity_per_parent INTEGER NOT NULL,
    scrap_factor_bps INTEGER NOT NULL DEFAULT 0,
    substitute_item_id TEXT,
    substitute_ratio_bps INTEGER NOT NULL DEFAULT 10000,
    uom_id TEXT NOT NULL DEFAULT 'EA',
    uom_conversion_factor_bps INTEGER NOT NULL DEFAULT 10000,
    eco_number TEXT,
    change_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workspace_id, bom_id, line_number)
);
ALTER TABLE reconforge.manufacturing_bom_components ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.manufacturing_bom_components FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON reconforge.manufacturing_bom_components;
CREATE POLICY tenant_scope ON reconforge.manufacturing_bom_components
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

CREATE INDEX IF NOT EXISTS idx_bom_components_lookup
ON reconforge.manufacturing_bom_components (tenant_id, workspace_id, bom_id);
"""


class PostgresManufacturingBOMRepository:
    """Enterprise PostgreSQL repository with FORCE RLS for Bills of Materials."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _scope(self) -> None:
        ensure_repository_tenant_scope(self.connection, self.tenant_id)

    def save_bom(
        self,
        *,
        workspace_id: str,
        bom: BillOfMaterials,
        created_by: str = "system",
    ) -> None:
        now = utc_now_text()
        try:
            with self.connection.transaction():
                self._scope()
                self.connection.execute(
                    """
                    INSERT INTO reconforge.manufacturing_boms (
                        tenant_id, workspace_id, bom_id, item_id, revision,
                        status, effective_from, effective_to, base_quantity,
                        eco_number, change_reason, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, workspace_id, item_id, revision) DO UPDATE SET
                        bom_id = excluded.bom_id,
                        status = excluded.status,
                        effective_from = excluded.effective_from,
                        effective_to = excluded.effective_to,
                        base_quantity = excluded.base_quantity,
                        eco_number = excluded.eco_number,
                        change_reason = excluded.change_reason,
                        updated_at = excluded.updated_at
                    """,
                    (
                        self.tenant_id,
                        workspace_id,
                        bom.bom_id,
                        bom.item_id,
                        bom.revision,
                        bom.status,
                        bom.effective_from,
                        bom.effective_to,
                        bom.base_quantity,
                        bom.eco_number,
                        bom.change_reason,
                        now,
                        now,
                    ),
                )
                self.connection.execute(
                    """
                    DELETE FROM reconforge.manufacturing_bom_components
                    WHERE tenant_id = %s AND workspace_id = %s AND bom_id = %s
                    """,
                    (self.tenant_id, workspace_id, bom.bom_id),
                )
                for comp in bom.components:
                    self.connection.execute(
                        """
                        INSERT INTO reconforge.manufacturing_bom_components (
                            tenant_id, workspace_id, bom_id, line_number,
                            component_item_id, component_name, component_type,
                            quantity_per_parent, scrap_factor_bps,
                            substitute_item_id, substitute_ratio_bps,
                            uom_id, uom_conversion_factor_bps,
                            eco_number, change_reason, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            self.tenant_id,
                            workspace_id,
                            bom.bom_id,
                            comp.line_number,
                            comp.component_item_id,
                            comp.component_name,
                            comp.component_type,
                            comp.quantity_per_parent,
                            comp.scrap_factor_bps,
                            comp.substitute_item_id,
                            comp.substitute_ratio_bps,
                            comp.uom_id,
                            comp.uom_conversion_factor_bps,
                            comp.eco_number,
                            comp.change_reason,
                            now,
                        ),
                    )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=created_by,
                    actor_user_id=created_by,
                    object_type="manufacturing_bom",
                    object_id=bom.bom_id,
                    action="bom_saved",
                    after_hash=f"{bom.item_id}:{bom.revision}:{len(bom.components)}",
                    metadata={
                        "workspace_id": workspace_id,
                        "item_id": bom.item_id,
                        "revision": bom.revision,
                        "components_count": len(bom.components),
                        "eco_number": bom.eco_number,
                    },
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL BOM save failed: {exc}") from exc

    def get_bom(
        self,
        *,
        workspace_id: str,
        item_id: str,
        revision: str | None = None,
    ) -> BillOfMaterials | None:
        try:
            with self.connection.transaction():
                self._scope()
                if revision:
                    cur = self.connection.execute(
                        """
                        SELECT bom_id, item_id, revision, status,
                               effective_from, effective_to, base_quantity,
                               eco_number, change_reason
                        FROM reconforge.manufacturing_boms
                        WHERE tenant_id = %s AND workspace_id = %s AND item_id = %s AND revision = %s
                        """,
                        (self.tenant_id, workspace_id, item_id, revision),
                    )
                else:
                    cur = self.connection.execute(
                        """
                        SELECT bom_id, item_id, revision, status,
                               effective_from, effective_to, base_quantity,
                               eco_number, change_reason
                        FROM reconforge.manufacturing_boms
                        WHERE tenant_id = %s AND workspace_id = %s AND item_id = %s AND status = 'approved'
                        ORDER BY effective_from DESC LIMIT 1
                        """,
                        (self.tenant_id, workspace_id, item_id),
                    )
                row = cur.fetchone()
                if not row:
                    return None

                bom_id = row[0]
                comp_cur = self.connection.execute(
                    """
                    SELECT line_number, component_item_id, component_name, component_type,
                           quantity_per_parent, scrap_factor_bps, substitute_item_id, substitute_ratio_bps,
                           uom_id, uom_conversion_factor_bps, eco_number, change_reason
                    FROM reconforge.manufacturing_bom_components
                    WHERE tenant_id = %s AND workspace_id = %s AND bom_id = %s
                    ORDER BY line_number ASC
                    """,
                    (self.tenant_id, workspace_id, bom_id),
                )
                components: list[BOMComponentLine] = []
                for c in comp_cur.fetchall():
                    components.append(
                        BOMComponentLine(
                            line_number=c[0],
                            component_item_id=c[1],
                            component_name=c[2],
                            component_type=c[3] if c[3] in ("raw_material", "subassembly", "finished_good") else "raw_material",
                            quantity_per_parent=c[4],
                            scrap_factor_bps=c[5],
                            substitute_item_id=c[6],
                            substitute_ratio_bps=c[7],
                            uom_id=c[8] or "EA",
                            uom_conversion_factor_bps=c[9] or 10000,
                            eco_number=c[10],
                            change_reason=c[11],
                        )
                    )

                return BillOfMaterials(
                    bom_id=row[0],
                    item_id=row[1],
                    revision=row[2],
                    status=row[3],
                    effective_from=str(row[4]),
                    effective_to=str(row[5]) if row[5] else None,
                    base_quantity=row[6],
                    components=tuple(components),
                    eco_number=row[7],
                    change_reason=row[8],
                )
        except Exception as exc:
            raise PlatformError(f"PostgreSQL BOM get failed: {exc}") from exc

    def list_all_boms(self, *, workspace_id: str) -> list[BillOfMaterials]:
        try:
            with self.connection.transaction():
                self._scope()
                cur = self.connection.execute(
                    """
                    SELECT item_id, revision FROM reconforge.manufacturing_boms
                    WHERE tenant_id = %s AND workspace_id = %s
                    ORDER BY item_id ASC, revision ASC
                    """,
                    (self.tenant_id, workspace_id),
                )
                rows = cur.fetchall()
            results: list[BillOfMaterials] = []
            for row in rows:
                bom = self.get_bom(workspace_id=workspace_id, item_id=row[0], revision=row[1])
                if bom:
                    results.append(bom)
            return results
        except Exception as exc:
            raise PlatformError(f"PostgreSQL BOM list failed: {exc}") from exc

    def build_engine(self, *, workspace_id: str) -> BOMExplosionEngine:
        return BOMExplosionEngine(self.list_all_boms(workspace_id=workspace_id))
