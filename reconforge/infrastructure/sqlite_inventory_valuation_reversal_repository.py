"""SQLite persistence primitives for governed FIFO valuation reversals."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol


class InventoryValuationReversalRepository(Protocol):
    """Persistence contract used by the valuation-reversal service."""

    @contextmanager
    def transaction(self) -> Iterator[None]: ...

    def workspace_by_name(self, name: str) -> dict[str, Any] | None: ...

    def currency(self, code: str) -> dict[str, Any] | None: ...

    def original_document(self, document_id: str) -> dict[str, Any] | None: ...

    def original_lines(self, document_id: str) -> list[dict[str, Any]]: ...

    def original_consumptions(self, document_id: str) -> list[dict[str, Any]]: ...

    def movement(self, movement_id: str) -> dict[str, Any] | None: ...

    def movement_lines(self, movement_id: str) -> list[dict[str, Any]]: ...

    def active_reversal_for_document(self, document_id: str) -> dict[str, Any] | None: ...

    def active_reversal_for_movement(self, movement_id: str) -> dict[str, Any] | None: ...

    def active_valuation_for_movement(self, movement_id: str) -> dict[str, Any] | None: ...

    def reversal(self, reversal_id: str) -> dict[str, Any] | None: ...

    def insert_reversal(self, record: Mapping[str, object]) -> None: ...

    def insert_effect(self, record: Mapping[str, object]) -> None: ...

    def update_layer(
        self,
        layer_id: str,
        *,
        expected_quantity: int,
        expected_value: int,
        new_quantity: int,
        new_value: int,
    ) -> int: ...

    def finance_entry(self, entry_id: str) -> dict[str, Any] | None: ...

    def finance_lines(self, entry_id: str) -> list[dict[str, Any]]: ...

    def line_dimensions(self, line_id: str) -> list[str]: ...

    def finance_entry_by_number(self, workspace_id: str, entry_number: str) -> dict[str, Any] | None: ...

    def insert_finance_draft(self, entry: Mapping[str, object], lines: Sequence[Mapping[str, object]]) -> None: ...

    def approve_reversal(
        self,
        reversal_id: str,
        *,
        actor: str,
        timestamp: str,
        reason: str,
        total_value_minor: int,
        finance_entry_id: str,
    ) -> int: ...

    def cancel_reversal(self, reversal_id: str, *, actor: str, timestamp: str, reason: str) -> int: ...

    def effects(self, reversal_id: str) -> list[dict[str, Any]]: ...

    def list_reversals(self, workspace_id: str, *, status: str, limit: int, offset: int) -> list[dict[str, Any]]: ...

    def summary_counts(self, workspace_id: str) -> dict[str, int]: ...


@dataclass
class SQLiteInventoryValuationReversalRepository:
    """SQLite adapter with aggregate-level transaction ownership."""

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

    def currency(self, code: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM currencies WHERE code = ?", (code,))

    def original_document(self, document_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT documents.*, movements.movement_number AS original_movement_number,
                   movements.movement_type AS original_movement_type,
                   movements.status AS original_movement_status,
                   movements.movement_date AS original_movement_date,
                   organizations.organization_code, entities.entity_code,
                   entries.entry_number AS original_finance_entry_number,
                   entries.status AS original_finance_entry_status,
                   entries.chart_id, entries.finance_journal_id
            FROM inventory_valuation_documents documents
            JOIN inventory_movements movements ON movements.id = documents.movement_id
            JOIN organizations ON organizations.id = documents.organization_id
            JOIN legal_entities entities ON entities.id = documents.legal_entity_id
            LEFT JOIN ledger_entries entries ON entries.id = documents.finance_entry_id
            WHERE documents.id = ?
            """,
            (document_id,),
        )

    def original_lines(self, document_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT valuation_lines.*, movement_lines.from_location_id,
                   movement_lines.to_location_id, items.item_code, units.uom_code,
                   lots.lot_serial_code, layers.id AS cost_layer_id,
                   layers.original_quantity_scaled, layers.remaining_quantity_scaled,
                   layers.original_value_minor, layers.remaining_value_minor
            FROM inventory_valuation_lines valuation_lines
            JOIN inventory_movement_lines movement_lines
              ON movement_lines.id = valuation_lines.movement_line_id
            JOIN inventory_items items ON items.id = valuation_lines.item_id
            JOIN units_of_measure units ON units.id = valuation_lines.uom_id
            LEFT JOIN inventory_lots lots ON lots.id = valuation_lines.inventory_lot_id
            LEFT JOIN inventory_cost_layers layers
              ON layers.source_valuation_line_id = valuation_lines.id
            WHERE valuation_lines.valuation_document_id = ?
            ORDER BY valuation_lines.line_number
            """,
            (document_id,),
        )

    def original_consumptions(self, document_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT consumptions.*, lines.line_number, lines.quantity_precision,
                   lines.item_id, lines.uom_id, lines.inventory_lot_id,
                   layers.original_quantity_scaled, layers.remaining_quantity_scaled,
                   layers.original_value_minor, layers.remaining_value_minor,
                   layers.source_valuation_line_id
            FROM inventory_layer_consumptions consumptions
            JOIN inventory_valuation_lines lines ON lines.id = consumptions.valuation_line_id
            JOIN inventory_cost_layers layers ON layers.id = consumptions.cost_layer_id
            WHERE lines.valuation_document_id = ?
            ORDER BY lines.line_number, consumptions.created_at, consumptions.id
            """,
            (document_id,),
        )

    def movement(self, movement_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT movements.*, organizations.organization_code, entities.entity_code,
                   entities.currency AS entity_currency, periods.status AS period_status,
                   periods.start_date AS period_start_date,
                   periods.end_date AS period_end_date,
                   periods.name AS period_name
            FROM inventory_movements movements
            JOIN organizations ON organizations.id = movements.organization_id
            JOIN legal_entities entities ON entities.id = movements.legal_entity_id
            JOIN periods ON periods.id = movements.period_id
            WHERE movements.id = ?
            """,
            (movement_id,),
        )

    def movement_lines(self, movement_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT lines.*, items.item_code, units.uom_code, lots.lot_serial_code
            FROM inventory_movement_lines lines
            JOIN inventory_items items ON items.id = lines.item_id
            JOIN units_of_measure units ON units.id = lines.uom_id
            LEFT JOIN inventory_lots lots ON lots.id = lines.inventory_lot_id
            WHERE lines.movement_id = ? ORDER BY lines.line_number
            """,
            (movement_id,),
        )

    def active_reversal_for_document(self, document_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM inventory_valuation_reversals
            WHERE original_valuation_document_id = ? AND status <> 'Cancelled'
            """,
            (document_id,),
        )

    def active_reversal_for_movement(self, movement_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM inventory_valuation_reversals
            WHERE reversal_movement_id = ? AND status <> 'Cancelled'
            """,
            (movement_id,),
        )

    def active_valuation_for_movement(self, movement_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM inventory_valuation_documents
            WHERE movement_id = ? AND status <> 'Cancelled'
            """,
            (movement_id,),
        )

    def reversal(self, reversal_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT reversals.*, original.valuation_number AS original_valuation_number,
                   original.total_value_minor AS original_total_value_minor,
                   original.movement_id AS original_movement_id,
                   original.finance_entry_id AS original_finance_entry_id,
                   original_movements.movement_number AS original_movement_number,
                   original_movements.movement_type AS original_movement_type,
                   reversal_movements.movement_number AS reversal_movement_number,
                   reversal_movements.movement_type AS reversal_movement_type,
                   reversal_movements.status AS reversal_movement_status,
                   organizations.organization_code, entities.entity_code,
                   periods.name AS period_name,
                   entries.entry_number AS finance_entry_number,
                   entries.status AS finance_entry_status
            FROM inventory_valuation_reversals reversals
            JOIN inventory_valuation_documents original
              ON original.id = reversals.original_valuation_document_id
            JOIN inventory_movements original_movements ON original_movements.id = original.movement_id
            JOIN inventory_movements reversal_movements
              ON reversal_movements.id = reversals.reversal_movement_id
            JOIN organizations ON organizations.id = reversals.organization_id
            JOIN legal_entities entities ON entities.id = reversals.legal_entity_id
            JOIN periods ON periods.id = reversals.period_id
            LEFT JOIN ledger_entries entries ON entries.id = reversals.finance_entry_id
            WHERE reversals.id = ?
            """,
            (reversal_id,),
        )

    def insert_reversal(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_valuation_reversals (
                id, workspace_id, organization_id, legal_entity_id, period_id,
                original_valuation_document_id, reversal_movement_id,
                reversal_number, reversal_date, currency_code, status,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?)
            """,
            tuple(
                record[key]
                for key in (
                    "id",
                    "workspace_id",
                    "organization_id",
                    "legal_entity_id",
                    "period_id",
                    "original_valuation_document_id",
                    "reversal_movement_id",
                    "reversal_number",
                    "reversal_date",
                    "currency_code",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            ),
        )

    def insert_effect(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_valuation_reversal_effects (
                id, reversal_id, original_valuation_line_id, original_consumption_id,
                cost_layer_id, effect_type, quantity_scaled, value_minor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(
                record[key]
                for key in (
                    "id",
                    "reversal_id",
                    "original_valuation_line_id",
                    "original_consumption_id",
                    "cost_layer_id",
                    "effect_type",
                    "quantity_scaled",
                    "value_minor",
                    "created_at",
                )
            ),
        )

    def update_layer(
        self,
        layer_id: str,
        *,
        expected_quantity: int,
        expected_value: int,
        new_quantity: int,
        new_value: int,
    ) -> int:
        cursor = self.connection.execute(
            """
            UPDATE inventory_cost_layers
            SET remaining_quantity_scaled = ?, remaining_value_minor = ?
            WHERE id = ? AND remaining_quantity_scaled = ? AND remaining_value_minor = ?
            """,
            (new_quantity, new_value, layer_id, expected_quantity, expected_value),
        )
        return cursor.rowcount

    def finance_entry(self, entry_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM ledger_entries WHERE id = ?", (entry_id,))

    def finance_lines(self, entry_id: str) -> list[dict[str, Any]]:
        return self._many("SELECT * FROM ledger_lines WHERE entry_id = ? ORDER BY line_number", (entry_id,))

    def line_dimensions(self, line_id: str) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT dimension_value_id FROM ledger_line_dimensions
            WHERE line_id = ? ORDER BY dimension_value_id
            """,
            (line_id,),
        ).fetchall()
        return [str(row["dimension_value_id"]) for row in rows]

    def finance_entry_by_number(self, workspace_id: str, entry_number: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM ledger_entries WHERE workspace_id = ? AND entry_number = ?",
            (workspace_id, entry_number),
        )

    def insert_finance_draft(self, entry: Mapping[str, object], lines: Sequence[Mapping[str, object]]) -> None:
        self.connection.execute(
            """
            INSERT INTO ledger_entries (
                id, workspace_id, organization_id, chart_id, legal_entity_id, period_id,
                finance_journal_id, entry_number, posting_date, currency_code, description,
                external_reference, source_type, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Generated', 'Draft', ?, ?, ?)
            """,
            tuple(
                entry[key]
                for key in (
                    "id",
                    "workspace_id",
                    "organization_id",
                    "chart_id",
                    "legal_entity_id",
                    "period_id",
                    "finance_journal_id",
                    "entry_number",
                    "posting_date",
                    "currency_code",
                    "description",
                    "external_reference",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            ),
        )
        for line in lines:
            self.connection.execute(
                """
                INSERT INTO ledger_lines (
                    id, entry_id, line_number, account_id, description,
                    debit_minor, credit_minor, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(
                    line[key]
                    for key in (
                        "id",
                        "entry_id",
                        "line_number",
                        "account_id",
                        "description",
                        "debit_minor",
                        "credit_minor",
                        "created_at",
                    )
                ),
            )
            dimension_value_ids = line.get("dimension_value_ids", ())
            if isinstance(dimension_value_ids, str | bytes) or not isinstance(dimension_value_ids, Sequence):
                raise TypeError("Finance line dimension IDs must be a sequence.")
            for dimension_value_id in dimension_value_ids:
                self.connection.execute(
                    """
                    INSERT INTO ledger_line_dimensions (line_id, dimension_value_id)
                    VALUES (?, ?)
                    """,
                    (line["id"], dimension_value_id),
                )

    def approve_reversal(
        self,
        reversal_id: str,
        *,
        actor: str,
        timestamp: str,
        reason: str,
        total_value_minor: int,
        finance_entry_id: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            UPDATE inventory_valuation_reversals
            SET status = 'Approved', approved_by = ?, approved_at = ?, approval_reason = ?,
                total_value_minor = ?, finance_entry_id = ?, updated_at = ?
            WHERE id = ? AND status = 'Draft'
            """,
            (
                actor,
                timestamp,
                reason,
                total_value_minor,
                finance_entry_id,
                timestamp,
                reversal_id,
            ),
        )
        return cursor.rowcount

    def cancel_reversal(self, reversal_id: str, *, actor: str, timestamp: str, reason: str) -> int:
        cursor = self.connection.execute(
            """
            UPDATE inventory_valuation_reversals
            SET status = 'Cancelled', cancelled_by = ?, cancelled_at = ?,
                cancel_reason = ?, updated_at = ?
            WHERE id = ? AND status = 'Draft'
            """,
            (actor, timestamp, reason, timestamp, reversal_id),
        )
        return cursor.rowcount

    def effects(self, reversal_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT effects.*, lines.line_number, lines.flow_direction,
                   lines.quantity_precision, items.item_code, units.uom_code,
                   lots.lot_serial_code, source_documents.valuation_number AS layer_valuation_number
            FROM inventory_valuation_reversal_effects effects
            JOIN inventory_valuation_lines lines ON lines.id = effects.original_valuation_line_id
            JOIN inventory_items items ON items.id = lines.item_id
            JOIN units_of_measure units ON units.id = lines.uom_id
            LEFT JOIN inventory_lots lots ON lots.id = lines.inventory_lot_id
            JOIN inventory_cost_layers layers ON layers.id = effects.cost_layer_id
            JOIN inventory_valuation_lines source_lines ON source_lines.id = layers.source_valuation_line_id
            JOIN inventory_valuation_documents source_documents
              ON source_documents.id = source_lines.valuation_document_id
            WHERE effects.reversal_id = ?
            ORDER BY lines.line_number, effects.effect_type, effects.created_at, effects.id
            """,
            (reversal_id,),
        )

    def list_reversals(self, workspace_id: str, *, status: str, limit: int, offset: int) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT reversals.*, original.valuation_number AS original_valuation_number,
                   original.total_value_minor AS original_total_value_minor,
                   original.movement_id AS original_movement_id,
                   original.finance_entry_id AS original_finance_entry_id,
                   original_movements.movement_number AS original_movement_number,
                   original_movements.movement_type AS original_movement_type,
                   reversal_movements.movement_number AS reversal_movement_number,
                   reversal_movements.movement_type AS reversal_movement_type,
                   reversal_movements.status AS reversal_movement_status,
                   organizations.organization_code, entities.entity_code,
                   periods.name AS period_name,
                   entries.entry_number AS finance_entry_number,
                   entries.status AS finance_entry_status
            FROM inventory_valuation_reversals reversals
            JOIN inventory_valuation_documents original
              ON original.id = reversals.original_valuation_document_id
            JOIN inventory_movements original_movements ON original_movements.id = original.movement_id
            JOIN inventory_movements reversal_movements
              ON reversal_movements.id = reversals.reversal_movement_id
            JOIN organizations ON organizations.id = reversals.organization_id
            JOIN legal_entities entities ON entities.id = reversals.legal_entity_id
            JOIN periods ON periods.id = reversals.period_id
            LEFT JOIN ledger_entries entries ON entries.id = reversals.finance_entry_id
            WHERE reversals.workspace_id = ?
              AND (? = '' OR reversals.status = ?)
            ORDER BY reversals.reversal_date DESC, reversals.reversal_number DESC
            LIMIT ? OFFSET ?
            """,
            (workspace_id, status, status, limit, offset),
        )

    def summary_counts(self, workspace_id: str) -> dict[str, int]:
        row = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM inventory_valuation_reversals
                 WHERE workspace_id = ? AND status = 'Draft') AS draft_reversals,
                (SELECT COUNT(*) FROM inventory_valuation_reversals
                 WHERE workspace_id = ? AND status = 'Approved') AS approved_reversals,
                (SELECT COUNT(*) FROM inventory_valuation_reversals
                 WHERE workspace_id = ? AND status = 'Cancelled') AS cancelled_reversals,
                (SELECT COUNT(*) FROM inventory_valuation_reversal_effects effects
                 JOIN inventory_valuation_reversals reversals ON reversals.id = effects.reversal_id
                 WHERE reversals.workspace_id = ? AND reversals.status = 'Approved') AS approved_effects,
                (SELECT COUNT(*) FROM inventory_valuation_reversals reversals
                 JOIN ledger_entries entries ON entries.id = reversals.finance_entry_id
                 WHERE reversals.workspace_id = ? AND reversals.status = 'Approved'
                   AND entries.status = 'Draft') AS finance_drafts
            """,
            (workspace_id, workspace_id, workspace_id, workspace_id, workspace_id),
        ).fetchone()
        return {str(key): int(value) for key, value in dict(row).items()} if row is not None else {}

    def _one(self, sql: str, parameters: tuple[object, ...]) -> dict[str, Any] | None:
        row = self.connection.execute(sql, parameters).fetchone()
        return dict(row) if row is not None else None

    def _many(self, sql: str, parameters: tuple[object, ...]) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(sql, parameters).fetchall()]
