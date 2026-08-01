"""SQLite persistence primitives for inventory count and reorder planning."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol


class InventoryPlanningRepository(Protocol):
    """Storage contract used by the inventory planning application service."""

    @contextmanager
    def transaction(self) -> Iterator[None]: ...

    def workspace_by_name(self, name: str) -> dict[str, Any] | None: ...

    def organization(self, workspace_id: str, code: str) -> dict[str, Any] | None: ...

    def entity(self, organization_id: str, code: str) -> dict[str, Any] | None: ...

    def period(self, workspace_id: str, period_id: str) -> dict[str, Any] | None: ...

    def location(
        self,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        warehouse_code: str,
        location_code: str,
    ) -> dict[str, Any] | None: ...

    def item(self, workspace_id: str, item_code: str) -> dict[str, Any] | None: ...

    def count_session(self, session_id: str) -> dict[str, Any] | None: ...

    def count_lines(self, session_id: str) -> list[dict[str, Any]]: ...

    def count_line(self, session_id: str, line_id: str) -> dict[str, Any] | None: ...

    def location_balances(self, location_id: str) -> list[dict[str, Any]]: ...

    def insert_count_session(self, record: Mapping[str, object]) -> None: ...

    def insert_count_lines(self, records: Sequence[Mapping[str, object]]) -> None: ...

    def start_count(self, session_id: str, actor: str, timestamp: str) -> int: ...

    def record_count(
        self,
        line_id: str,
        quantity_scaled: int,
        note: str,
        actor: str,
        timestamp: str,
    ) -> int: ...

    def submit_count(self, session_id: str, actor: str, timestamp: str, reason: str) -> int: ...

    def cancel_count(self, session_id: str, actor: str, timestamp: str, reason: str) -> int: ...

    def approve_count(
        self,
        session_id: str,
        actor: str,
        timestamp: str,
        reason: str,
        adjustment_movement_id: str | None,
    ) -> int: ...

    def insert_adjustment(
        self,
        movement: Mapping[str, object],
        lines: Sequence[Mapping[str, object]],
    ) -> None: ...

    def movement_number_exists(self, workspace_id: str, movement_number: str) -> bool: ...

    def list_count_sessions(
        self,
        workspace_id: str,
        *,
        status: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    def upsert_reorder_rule(self, record: Mapping[str, object]) -> None: ...

    def reorder_rule(self, rule_id: str) -> dict[str, Any] | None: ...

    def list_reorder_rules(
        self,
        workspace_id: str,
        *,
        active_only: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    def reorder_signal_rows(
        self,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        *,
        active_only: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]: ...

    def summary_counts(self, workspace_id: str) -> dict[str, int]: ...


@dataclass
class SQLiteInventoryPlanningRepository:
    """SQLite implementation with explicit aggregate-level operations."""

    connection: sqlite3.Connection

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def workspace_by_name(self, name: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM workspaces WHERE name = ?", (name,))

    def organization(self, workspace_id: str, code: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM organizations WHERE workspace_id = ? AND organization_code = ?",
            (workspace_id, code),
        )

    def entity(self, organization_id: str, code: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM legal_entities WHERE organization_id = ? AND entity_code = ?",
            (organization_id, code),
        )

    def period(self, workspace_id: str, period_id: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM periods WHERE workspace_id = ? AND id = ?",
            (workspace_id, period_id),
        )

    def location(
        self,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        warehouse_code: str,
        location_code: str,
    ) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT locations.*, warehouses.warehouse_code, warehouses.organization_id,
                   warehouses.legal_entity_id, warehouses.active AS warehouse_active
            FROM inventory_locations locations
            JOIN warehouses ON warehouses.id = locations.warehouse_id
            WHERE warehouses.workspace_id = ? AND warehouses.organization_id = ?
              AND warehouses.legal_entity_id = ? AND warehouses.warehouse_code = ?
              AND locations.location_code = ?
            """,
            (workspace_id, organization_id, entity_id, warehouse_code, location_code),
        )

    def item(self, workspace_id: str, item_code: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT items.*, units.uom_code, units.decimal_places
            FROM inventory_items items
            JOIN units_of_measure units ON units.id = items.uom_id
            WHERE items.workspace_id = ? AND items.item_code = ?
            """,
            (workspace_id, item_code),
        )

    def count_session(self, session_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT sessions.*, organizations.organization_code, entities.entity_code,
                   periods.name AS period_name, warehouses.warehouse_code,
                   locations.location_code, locations.name AS location_name,
                   movements.movement_number AS adjustment_movement_number
            FROM inventory_count_sessions sessions
            JOIN organizations ON organizations.id = sessions.organization_id
            JOIN legal_entities entities ON entities.id = sessions.legal_entity_id
            JOIN periods ON periods.id = sessions.period_id
            JOIN inventory_locations locations ON locations.id = sessions.location_id
            JOIN warehouses ON warehouses.id = locations.warehouse_id
            LEFT JOIN inventory_movements movements ON movements.id = sessions.adjustment_movement_id
            WHERE sessions.id = ?
            """,
            (session_id,),
        )

    def count_lines(self, session_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT lines.*, items.item_code, items.name AS item_name, units.uom_code,
                   lots.lot_serial_code
            FROM inventory_count_lines lines
            JOIN inventory_items items ON items.id = lines.item_id
            JOIN units_of_measure units ON units.id = lines.uom_id
            LEFT JOIN inventory_lots lots ON lots.id = lines.inventory_lot_id
            WHERE lines.session_id = ?
            ORDER BY lines.line_number
            """,
            (session_id,),
        )

    def count_line(self, session_id: str, line_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT lines.*, sessions.status, items.item_code, units.uom_code
            FROM inventory_count_lines lines
            JOIN inventory_count_sessions sessions ON sessions.id = lines.session_id
            JOIN inventory_items items ON items.id = lines.item_id
            JOIN units_of_measure units ON units.id = lines.uom_id
            WHERE lines.session_id = ? AND lines.id = ?
            """,
            (session_id, line_id),
        )

    def location_balances(self, location_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT lines.item_id, lines.uom_id, lines.inventory_lot_id,
                   lines.quantity_precision, items.item_code, items.name AS item_name,
                   units.uom_code, lots.lot_serial_code,
                   SUM(
                       CASE
                           WHEN lines.to_location_id = ? THEN lines.quantity_scaled
                           WHEN lines.from_location_id = ? THEN -lines.quantity_scaled
                           ELSE 0
                       END
                   ) AS expected_quantity_scaled
            FROM inventory_movement_lines lines
            JOIN inventory_movements movements ON movements.id = lines.movement_id
            JOIN inventory_items items ON items.id = lines.item_id
            JOIN units_of_measure units ON units.id = lines.uom_id
            LEFT JOIN inventory_lots lots ON lots.id = lines.inventory_lot_id
            WHERE movements.status = 'Posted'
              AND (lines.from_location_id = ? OR lines.to_location_id = ?)
            GROUP BY lines.item_id, lines.uom_id, lines.inventory_lot_id,
                     lines.quantity_precision, items.item_code, items.name,
                     units.uom_code, lots.lot_serial_code
            HAVING expected_quantity_scaled <> 0
            ORDER BY items.item_code, lots.lot_serial_code
            """,
            (location_id, location_id, location_id, location_id),
        )

    def insert_count_session(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_count_sessions (
                id, workspace_id, organization_id, legal_entity_id, period_id,
                location_id, count_number, count_date, description, status,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?)
            """,
            tuple(
                record[key]
                for key in (
                    "id",
                    "workspace_id",
                    "organization_id",
                    "legal_entity_id",
                    "period_id",
                    "location_id",
                    "count_number",
                    "count_date",
                    "description",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            ),
        )

    def insert_count_lines(self, records: Sequence[Mapping[str, object]]) -> None:
        self.connection.executemany(
            """
            INSERT INTO inventory_count_lines (
                id, session_id, line_number, item_id, uom_id, inventory_lot_id,
                expected_quantity_scaled, quantity_precision, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                tuple(
                    record[key]
                    for key in (
                        "id",
                        "session_id",
                        "line_number",
                        "item_id",
                        "uom_id",
                        "inventory_lot_id",
                        "expected_quantity_scaled",
                        "quantity_precision",
                        "created_at",
                    )
                )
                for record in records
            ],
        )

    def start_count(self, session_id: str, actor: str, timestamp: str) -> int:
        return self._update(
            """
            UPDATE inventory_count_sessions
            SET status = 'Counting', started_by = ?, started_at = ?, updated_at = ?
            WHERE id = ? AND status = 'Draft'
            """,
            (actor, timestamp, timestamp, session_id),
        )

    def record_count(
        self,
        line_id: str,
        quantity_scaled: int,
        note: str,
        actor: str,
        timestamp: str,
    ) -> int:
        return self._update(
            """
            UPDATE inventory_count_lines
            SET counted_quantity_scaled = ?, count_note = ?, counted_by = ?, counted_at = ?
            WHERE id = ?
            """,
            (quantity_scaled, note, actor, timestamp, line_id),
        )

    def submit_count(self, session_id: str, actor: str, timestamp: str, reason: str) -> int:
        return self._update(
            """
            UPDATE inventory_count_sessions
            SET status = 'Submitted', submitted_by = ?, submitted_at = ?,
                submit_reason = ?, updated_at = ?
            WHERE id = ? AND status = 'Counting'
            """,
            (actor, timestamp, reason, timestamp, session_id),
        )

    def cancel_count(self, session_id: str, actor: str, timestamp: str, reason: str) -> int:
        return self._update(
            """
            UPDATE inventory_count_sessions
            SET status = 'Cancelled', cancelled_by = ?, cancelled_at = ?,
                cancel_reason = ?, updated_at = ?
            WHERE id = ? AND status IN ('Draft', 'Counting', 'Submitted')
            """,
            (actor, timestamp, reason, timestamp, session_id),
        )

    def approve_count(
        self,
        session_id: str,
        actor: str,
        timestamp: str,
        reason: str,
        adjustment_movement_id: str | None,
    ) -> int:
        return self._update(
            """
            UPDATE inventory_count_sessions
            SET status = 'Approved', approved_by = ?, approved_at = ?,
                approval_reason = ?, adjustment_movement_id = ?, updated_at = ?
            WHERE id = ? AND status = 'Submitted'
            """,
            (actor, timestamp, reason, adjustment_movement_id, timestamp, session_id),
        )

    def insert_adjustment(
        self,
        movement: Mapping[str, object],
        lines: Sequence[Mapping[str, object]],
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_movements (
                id, workspace_id, organization_id, legal_entity_id, period_id,
                movement_number, movement_type, movement_date, source_reference,
                description, source_type, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'Adjustment', ?, ?, ?, 'Generated', 'Draft', ?, ?, ?)
            """,
            tuple(
                movement[key]
                for key in (
                    "id",
                    "workspace_id",
                    "organization_id",
                    "legal_entity_id",
                    "period_id",
                    "movement_number",
                    "movement_date",
                    "source_reference",
                    "description",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            ),
        )
        self.connection.executemany(
            """
            INSERT INTO inventory_movement_lines (
                id, movement_id, line_number, item_id, uom_id, inventory_lot_id,
                from_location_id, to_location_id, quantity_scaled,
                quantity_precision, description, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                tuple(
                    line[key]
                    for key in (
                        "id",
                        "movement_id",
                        "line_number",
                        "item_id",
                        "uom_id",
                        "inventory_lot_id",
                        "from_location_id",
                        "to_location_id",
                        "quantity_scaled",
                        "quantity_precision",
                        "description",
                        "created_at",
                    )
                )
                for line in lines
            ],
        )

    def movement_number_exists(self, workspace_id: str, movement_number: str) -> bool:
        return (
            self._one(
                "SELECT id FROM inventory_movements WHERE workspace_id = ? AND movement_number = ?",
                (workspace_id, movement_number),
            )
            is not None
        )

    def list_count_sessions(
        self,
        workspace_id: str,
        *,
        status: str,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT sessions.*, organizations.organization_code, entities.entity_code,
                   periods.name AS period_name, warehouses.warehouse_code,
                   locations.location_code, locations.name AS location_name,
                   movements.movement_number AS adjustment_movement_number,
                   (SELECT COUNT(*) FROM inventory_count_lines lines WHERE lines.session_id = sessions.id) AS line_count,
                   (SELECT COUNT(*) FROM inventory_count_lines lines WHERE lines.session_id = sessions.id AND lines.counted_quantity_scaled IS NOT NULL) AS counted_line_count
            FROM inventory_count_sessions sessions
            JOIN organizations ON organizations.id = sessions.organization_id
            JOIN legal_entities entities ON entities.id = sessions.legal_entity_id
            JOIN periods ON periods.id = sessions.period_id
            JOIN inventory_locations locations ON locations.id = sessions.location_id
            JOIN warehouses ON warehouses.id = locations.warehouse_id
            LEFT JOIN inventory_movements movements ON movements.id = sessions.adjustment_movement_id
            WHERE sessions.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if status:
            query += " AND sessions.status = ?"
            parameters.append(status)
        query += " ORDER BY sessions.count_date DESC, sessions.count_number LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
        return self._many(query, parameters)

    def upsert_reorder_rule(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_reorder_rules (
                id, workspace_id, organization_id, legal_entity_id, item_id, location_id,
                minimum_quantity_scaled, target_quantity_scaled, quantity_precision,
                lead_time_days, active, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, organization_id, legal_entity_id, item_id, location_id)
            DO UPDATE SET
                minimum_quantity_scaled = excluded.minimum_quantity_scaled,
                target_quantity_scaled = excluded.target_quantity_scaled,
                quantity_precision = excluded.quantity_precision,
                lead_time_days = excluded.lead_time_days,
                active = excluded.active,
                updated_at = excluded.updated_at
            """,
            tuple(
                record[key]
                for key in (
                    "id",
                    "workspace_id",
                    "organization_id",
                    "legal_entity_id",
                    "item_id",
                    "location_id",
                    "minimum_quantity_scaled",
                    "target_quantity_scaled",
                    "quantity_precision",
                    "lead_time_days",
                    "active",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            ),
        )

    def reorder_rule(self, rule_id: str) -> dict[str, Any] | None:
        return self._one(self._reorder_base_query() + " WHERE rules.id = ?", (rule_id,))

    def list_reorder_rules(
        self,
        workspace_id: str,
        *,
        active_only: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        query = self._reorder_base_query() + " WHERE rules.workspace_id = ?"
        parameters: list[object] = [workspace_id]
        if active_only:
            query += " AND rules.active = 1"
        query += " ORDER BY items.item_code, warehouses.warehouse_code, locations.location_code LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
        return self._many(query, parameters)

    def reorder_signal_rows(
        self,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        *,
        active_only: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        query = (
            self._reorder_base_query()
            + """
            WHERE rules.workspace_id = ? AND rules.organization_id = ?
              AND rules.legal_entity_id = ?
            """
        )
        parameters: list[object] = [workspace_id, organization_id, entity_id]
        if active_only:
            query += " AND rules.active = 1"
        query += " ORDER BY items.item_code, warehouses.warehouse_code, locations.location_code LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
        return self._many(query, parameters)

    def summary_counts(self, workspace_id: str) -> dict[str, int]:
        row = self._one(
            """
            SELECT
                (SELECT COUNT(*) FROM inventory_count_sessions WHERE workspace_id = ?) AS count_sessions,
                (SELECT COUNT(*) FROM inventory_count_sessions WHERE workspace_id = ? AND status = 'Counting') AS counting_sessions,
                (SELECT COUNT(*) FROM inventory_count_sessions WHERE workspace_id = ? AND status = 'Submitted') AS submitted_sessions,
                (SELECT COUNT(*) FROM inventory_count_sessions WHERE workspace_id = ? AND status = 'Approved') AS approved_sessions,
                (SELECT COUNT(*) FROM inventory_reorder_rules WHERE workspace_id = ?) AS reorder_rules,
                (SELECT COUNT(*) FROM inventory_reorder_rules WHERE workspace_id = ? AND active = 1) AS active_reorder_rules
            """,
            (workspace_id, workspace_id, workspace_id, workspace_id, workspace_id, workspace_id),
        )
        if row is None:
            return {}
        return {key: int(value) for key, value in row.items()}

    @staticmethod
    def _reorder_base_query() -> str:
        return """
            SELECT rules.*, organizations.organization_code, entities.entity_code,
                   items.item_code, items.name AS item_name, units.uom_code,
                   warehouses.warehouse_code, locations.location_code,
                   COALESCE((
                       SELECT SUM(
                           CASE
                               WHEN lines.to_location_id = rules.location_id THEN lines.quantity_scaled
                               WHEN lines.from_location_id = rules.location_id THEN -lines.quantity_scaled
                               ELSE 0
                           END
                       )
                       FROM inventory_movement_lines lines
                       JOIN inventory_movements movements ON movements.id = lines.movement_id
                       WHERE movements.status = 'Posted'
                         AND lines.item_id = rules.item_id
                         AND (lines.from_location_id = rules.location_id OR lines.to_location_id = rules.location_id)
                   ), 0) AS on_hand_quantity_scaled
            FROM inventory_reorder_rules rules
            JOIN organizations ON organizations.id = rules.organization_id
            JOIN legal_entities entities ON entities.id = rules.legal_entity_id
            JOIN inventory_items items ON items.id = rules.item_id
            JOIN units_of_measure units ON units.id = items.uom_id
            JOIN inventory_locations locations ON locations.id = rules.location_id
            JOIN warehouses ON warehouses.id = locations.warehouse_id
        """

    def _one(self, query: str, parameters: Sequence[object]) -> dict[str, Any] | None:
        row = self.connection.execute(query, parameters).fetchone()
        return dict(row) if row is not None else None

    def _many(self, query: str, parameters: Sequence[object]) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(query, parameters).fetchall()]

    def _update(self, query: str, parameters: Sequence[object]) -> int:
        return int(self.connection.execute(query, parameters).rowcount)
