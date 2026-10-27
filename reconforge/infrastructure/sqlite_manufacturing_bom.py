"""SQLite persistence repository for Bill of Materials and MRP Explosion."""

from __future__ import annotations

import sqlite3

from reconforge.domain.manufacturing_bom_explosion import (
    BillOfMaterials,
    BOMComponentLine,
    BOMExplosionEngine,
)

CREATE_BOM_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS manufacturing_boms (
    bom_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    base_quantity INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (item_id, revision)
);

CREATE TABLE IF NOT EXISTS manufacturing_bom_components (
    bom_id TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    component_item_id TEXT NOT NULL,
    component_name TEXT NOT NULL,
    component_type TEXT NOT NULL,
    quantity_per_parent INTEGER NOT NULL,
    scrap_factor_bps INTEGER NOT NULL DEFAULT 0,
    substitute_item_id TEXT,
    substitute_ratio_bps INTEGER NOT NULL DEFAULT 10000,
    PRIMARY KEY (bom_id, line_number)
);

CREATE INDEX IF NOT EXISTS idx_bom_components_parent
ON manufacturing_bom_components (bom_id);
"""


class SqliteManufacturingBOMRepository:
    """Thread-safe SQLite storage for Bills of Materials."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript(CREATE_BOM_TABLES_SQL)
        self._conn.commit()

    def save_bom(self, bom: BillOfMaterials) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO manufacturing_boms (
                    bom_id, item_id, revision, status,
                    effective_from, effective_to, base_quantity
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id, revision) DO UPDATE SET
                    bom_id = excluded.bom_id,
                    status = excluded.status,
                    effective_from = excluded.effective_from,
                    effective_to = excluded.effective_to,
                    base_quantity = excluded.base_quantity
                """,
                (
                    bom.bom_id,
                    bom.item_id,
                    bom.revision,
                    bom.status,
                    bom.effective_from,
                    bom.effective_to,
                    bom.base_quantity,
                ),
            )
            # Remove existing components for this bom_id and re-insert
            self._conn.execute("DELETE FROM manufacturing_bom_components WHERE bom_id = ?", (bom.bom_id,))
            for comp in bom.components:
                self._conn.execute(
                    """
                    INSERT INTO manufacturing_bom_components (
                        bom_id, line_number, component_item_id, component_name,
                        component_type, quantity_per_parent, scrap_factor_bps,
                        substitute_item_id, substitute_ratio_bps
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        bom.bom_id,
                        comp.line_number,
                        comp.component_item_id,
                        comp.component_name,
                        comp.component_type,
                        comp.quantity_per_parent,
                        comp.scrap_factor_bps,
                        comp.substitute_item_id,
                        comp.substitute_ratio_bps,
                    ),
                )

    def get_bom(self, item_id: str, revision: str | None = None) -> BillOfMaterials | None:
        if revision:
            cursor = self._conn.execute(
                """
                SELECT bom_id, item_id, revision, status, effective_from, effective_to, base_quantity
                FROM manufacturing_boms
                WHERE item_id = ? AND revision = ?
                """,
                (item_id, revision),
            )
        else:
            cursor = self._conn.execute(
                """
                SELECT bom_id, item_id, revision, status, effective_from, effective_to, base_quantity
                FROM manufacturing_boms
                WHERE item_id = ? AND status = 'approved'
                ORDER BY effective_from DESC LIMIT 1
                """,
                (item_id,),
            )
        row = cursor.fetchone()
        if not row:
            return None

        bom_id = row[0]
        comp_cursor = self._conn.execute(
            """
            SELECT line_number, component_item_id, component_name, component_type,
                   quantity_per_parent, scrap_factor_bps, substitute_item_id, substitute_ratio_bps
            FROM manufacturing_bom_components
            WHERE bom_id = ?
            ORDER BY line_number ASC
            """,
            (bom_id,),
        )
        components: list[BOMComponentLine] = []
        for c in comp_cursor.fetchall():
            components.append(
                BOMComponentLine(
                    line_number=c[0],
                    component_item_id=c[1],
                    component_name=c[2],
                    component_type=c[3],
                    quantity_per_parent=c[4],
                    scrap_factor_bps=c[5],
                    substitute_item_id=c[6],
                    substitute_ratio_bps=c[7],
                )
            )

        return BillOfMaterials(
            bom_id=row[0],
            item_id=row[1],
            revision=row[2],
            status=row[3],
            effective_from=row[4],
            effective_to=row[5],
            base_quantity=row[6],
            components=tuple(components),
        )

    def list_all_boms(self) -> list[BillOfMaterials]:
        cursor = self._conn.execute("SELECT item_id, revision FROM manufacturing_boms")
        results: list[BillOfMaterials] = []
        for row in cursor.fetchall():
            bom = self.get_bom(row[0], row[1])
            if bom:
                results.append(bom)
        return results

    def build_engine(self) -> BOMExplosionEngine:
        return BOMExplosionEngine(self.list_all_boms())
