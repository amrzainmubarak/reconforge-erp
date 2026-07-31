"""SQLite persistence primitives for governed FIFO inventory valuation."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol


class InventoryValuationRepository(Protocol):
    """Persistence contract used by the valuation application service."""

    @contextmanager
    def transaction(self) -> Iterator[None]: ...

    def workspace_by_name(self, name: str) -> dict[str, Any] | None: ...

    def organization(self, workspace_id: str, code: str) -> dict[str, Any] | None: ...

    def entity(self, organization_id: str, code: str) -> dict[str, Any] | None: ...

    def period(self, workspace_id: str, period_id: str) -> dict[str, Any] | None: ...

    def currency(self, code: str) -> dict[str, Any] | None: ...

    def journal(self, workspace_id: str, organization_id: str, code: str) -> dict[str, Any] | None: ...

    def account(self, chart_id: str, code: str) -> dict[str, Any] | None: ...

    def policy(self, policy_id: str) -> dict[str, Any] | None: ...

    def policy_by_code(
        self, workspace_id: str, organization_id: str, legal_entity_id: str, code: str
    ) -> dict[str, Any] | None: ...

    def policy_has_approved_documents(self, policy_id: str) -> bool: ...

    def upsert_policy(self, record: Mapping[str, object]) -> None: ...

    def movement(self, movement_id: str) -> dict[str, Any] | None: ...

    def movement_lines(self, movement_id: str) -> list[dict[str, Any]]: ...

    def earlier_unvalued_movement(self, movement_id: str) -> dict[str, Any] | None: ...

    def later_approved_document(self, movement_id: str) -> dict[str, Any] | None: ...

    def required_dimensions_count(self, workspace_id: str, organization_id: str) -> int: ...

    def active_document_for_movement(self, movement_id: str) -> dict[str, Any] | None: ...

    def document(self, document_id: str) -> dict[str, Any] | None: ...

    def insert_document(self, record: Mapping[str, object]) -> None: ...

    def insert_input_costs(self, records: Sequence[Mapping[str, object]]) -> None: ...

    def input_costs(self, document_id: str) -> list[dict[str, Any]]: ...

    def insert_valuation_line(self, record: Mapping[str, object]) -> None: ...

    def insert_cost_layer(self, record: Mapping[str, object]) -> None: ...

    def open_cost_layers(
        self, legal_entity_id: str, item_id: str, inventory_lot_id: str | None
    ) -> list[dict[str, Any]]: ...

    def insert_layer_consumption(self, record: Mapping[str, object]) -> None: ...

    def update_cost_layer(self, layer_id: str, quantity_scaled: int, value_minor: int) -> int: ...

    def insert_finance_draft(self, entry: Mapping[str, object], lines: Sequence[Mapping[str, object]]) -> None: ...

    def approve_document(
        self,
        document_id: str,
        *,
        actor: str,
        timestamp: str,
        reason: str,
        total_value_minor: int,
        finance_entry_id: str,
    ) -> int: ...

    def cancel_document(self, document_id: str, *, actor: str, timestamp: str, reason: str) -> int: ...

    def valuation_lines(self, document_id: str) -> list[dict[str, Any]]: ...

    def layer_consumptions(self, document_id: str) -> list[dict[str, Any]]: ...

    def finance_entry(self, entry_id: str) -> dict[str, Any] | None: ...

    def finance_entry_by_number(self, workspace_id: str, entry_number: str) -> dict[str, Any] | None: ...

    def list_policies(self, workspace_id: str, *, limit: int, offset: int) -> list[dict[str, Any]]: ...

    def list_documents(self, workspace_id: str, *, status: str, limit: int, offset: int) -> list[dict[str, Any]]: ...

    def list_cost_layers(
        self, workspace_id: str, *, open_only: bool, limit: int, offset: int
    ) -> list[dict[str, Any]]: ...

    def summary_counts(self, workspace_id: str) -> dict[str, int]: ...


@dataclass
class SQLiteInventoryValuationRepository:
    """SQLite implementation with transaction ownership at the aggregate boundary."""

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

    def currency(self, code: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM currencies WHERE code = ?", (code,))

    def journal(self, workspace_id: str, organization_id: str, code: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT journals.*, charts.active AS chart_active
            FROM finance_journals journals
            JOIN charts_of_accounts charts ON charts.id = journals.chart_id
            WHERE journals.workspace_id = ? AND journals.organization_id = ?
              AND journals.journal_code = ?
            """,
            (workspace_id, organization_id, code),
        )

    def account(self, chart_id: str, code: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM accounts WHERE chart_id = ? AND account_code = ?",
            (chart_id, code),
        )

    def policy(self, policy_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT policies.*, organizations.organization_code, entities.entity_code,
                   journals.journal_code, journals.chart_id,
                   journals.active AS journal_active, journals.currency_code AS journal_currency_code,
                   receipt_accounts.active AS receipt_account_active,
                   receipt_accounts.allow_posting AS receipt_account_allow_posting,
                   cogs_accounts.active AS cogs_account_active,
                   cogs_accounts.allow_posting AS cogs_account_allow_posting,
                   adjustment_accounts.active AS adjustment_account_active,
                   adjustment_accounts.allow_posting AS adjustment_account_allow_posting,
                   receipt_accounts.account_code AS receipt_clearing_account_code,
                   cogs_accounts.account_code AS cogs_account_code,
                   adjustment_accounts.account_code AS adjustment_account_code
            FROM inventory_valuation_policies policies
            JOIN organizations ON organizations.id = policies.organization_id
            JOIN legal_entities entities ON entities.id = policies.legal_entity_id
            JOIN finance_journals journals ON journals.id = policies.finance_journal_id
            JOIN accounts receipt_accounts ON receipt_accounts.id = policies.receipt_clearing_account_id
            JOIN accounts cogs_accounts ON cogs_accounts.id = policies.cogs_account_id
            JOIN accounts adjustment_accounts ON adjustment_accounts.id = policies.adjustment_account_id
            WHERE policies.id = ?
            """,
            (policy_id,),
        )

    def policy_by_code(
        self, workspace_id: str, organization_id: str, legal_entity_id: str, code: str
    ) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT policies.*, organizations.organization_code, entities.entity_code,
                   journals.journal_code, journals.chart_id,
                   journals.active AS journal_active, journals.currency_code AS journal_currency_code,
                   receipt_accounts.active AS receipt_account_active,
                   receipt_accounts.allow_posting AS receipt_account_allow_posting,
                   cogs_accounts.active AS cogs_account_active,
                   cogs_accounts.allow_posting AS cogs_account_allow_posting,
                   adjustment_accounts.active AS adjustment_account_active,
                   adjustment_accounts.allow_posting AS adjustment_account_allow_posting,
                   receipt_accounts.account_code AS receipt_clearing_account_code,
                   cogs_accounts.account_code AS cogs_account_code,
                   adjustment_accounts.account_code AS adjustment_account_code
            FROM inventory_valuation_policies policies
            JOIN organizations ON organizations.id = policies.organization_id
            JOIN legal_entities entities ON entities.id = policies.legal_entity_id
            JOIN finance_journals journals ON journals.id = policies.finance_journal_id
            JOIN accounts receipt_accounts ON receipt_accounts.id = policies.receipt_clearing_account_id
            JOIN accounts cogs_accounts ON cogs_accounts.id = policies.cogs_account_id
            JOIN accounts adjustment_accounts ON adjustment_accounts.id = policies.adjustment_account_id
            WHERE policies.workspace_id = ? AND policies.organization_id = ?
              AND policies.legal_entity_id = ? AND policies.policy_code = ?
            """,
            (workspace_id, organization_id, legal_entity_id, code),
        )

    def policy_has_approved_documents(self, policy_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1 FROM inventory_valuation_documents
            WHERE policy_id = ? AND status = 'Approved' LIMIT 1
            """,
            (policy_id,),
        ).fetchone()
        return row is not None

    def upsert_policy(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_valuation_policies (
                id, workspace_id, organization_id, legal_entity_id, policy_code,
                costing_method, currency_code, finance_journal_id,
                receipt_clearing_account_id, cogs_account_id, adjustment_account_id,
                active, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'FIFO', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, organization_id, legal_entity_id, policy_code) DO UPDATE SET
                currency_code = excluded.currency_code,
                finance_journal_id = excluded.finance_journal_id,
                receipt_clearing_account_id = excluded.receipt_clearing_account_id,
                cogs_account_id = excluded.cogs_account_id,
                adjustment_account_id = excluded.adjustment_account_id,
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
                    "policy_code",
                    "currency_code",
                    "finance_journal_id",
                    "receipt_clearing_account_id",
                    "cogs_account_id",
                    "adjustment_account_id",
                    "active",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            ),
        )

    def movement(self, movement_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT movements.*, organizations.organization_code, entities.entity_code,
                   entities.currency AS entity_currency, periods.status AS period_status,
                   periods.start_date AS period_start_date, periods.end_date AS period_end_date
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
            SELECT lines.*, items.item_code, items.item_type, items.tracking_mode,
                   items.inventory_account_id, item_accounts.account_code AS inventory_account_code,
                   item_accounts.chart_id AS inventory_account_chart_id,
                   item_accounts.active AS inventory_account_active,
                   item_accounts.allow_posting AS inventory_account_allow_posting,
                   units.uom_code, units.decimal_places, lots.lot_serial_code
            FROM inventory_movement_lines lines
            JOIN inventory_items items ON items.id = lines.item_id
            JOIN units_of_measure units ON units.id = lines.uom_id
            LEFT JOIN accounts item_accounts ON item_accounts.id = items.inventory_account_id
            LEFT JOIN inventory_lots lots ON lots.id = lines.inventory_lot_id
            WHERE lines.movement_id = ?
            ORDER BY lines.line_number
            """,
            (movement_id,),
        )

    def earlier_unvalued_movement(self, movement_id: str) -> dict[str, Any] | None:
        if self._table_exists("inventory_valuation_reversals"):
            return self._one(
                """
                SELECT earlier.id, earlier.movement_number, earlier.movement_date
                FROM inventory_movements current
                JOIN inventory_movements earlier
                  ON earlier.workspace_id = current.workspace_id
                 AND earlier.organization_id = current.organization_id
                 AND earlier.legal_entity_id = current.legal_entity_id
                 AND earlier.status = 'Posted'
                 AND earlier.movement_type <> 'Transfer'
                 AND (
                    earlier.movement_date < current.movement_date OR
                    (earlier.movement_date = current.movement_date
                     AND earlier.movement_number < current.movement_number)
                 )
                WHERE current.id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM inventory_valuation_documents documents
                      WHERE documents.movement_id = earlier.id AND documents.status = 'Approved'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM inventory_valuation_reversals reversals
                      WHERE reversals.reversal_movement_id = earlier.id
                        AND reversals.status = 'Approved'
                  )
                ORDER BY earlier.movement_date, earlier.movement_number
                LIMIT 1
                """,
                (movement_id,),
            )
        return self._one(
            """
            SELECT earlier.id, earlier.movement_number, earlier.movement_date
            FROM inventory_movements current
            JOIN inventory_movements earlier
              ON earlier.workspace_id = current.workspace_id
             AND earlier.organization_id = current.organization_id
             AND earlier.legal_entity_id = current.legal_entity_id
             AND earlier.status = 'Posted'
             AND earlier.movement_type <> 'Transfer'
             AND (
                earlier.movement_date < current.movement_date OR
                (earlier.movement_date = current.movement_date
                 AND earlier.movement_number < current.movement_number)
             )
            WHERE current.id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM inventory_valuation_documents documents
                  WHERE documents.movement_id = earlier.id AND documents.status = 'Approved'
              )
            ORDER BY earlier.movement_date, earlier.movement_number
            LIMIT 1
            """,
            (movement_id,),
        )

    def later_approved_document(self, movement_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT documents.id, documents.valuation_number, later.movement_number, later.movement_date
            FROM inventory_movements current
            JOIN inventory_movements later
              ON later.workspace_id = current.workspace_id
             AND later.organization_id = current.organization_id
             AND later.legal_entity_id = current.legal_entity_id
             AND (
                later.movement_date > current.movement_date OR
                (later.movement_date = current.movement_date
                 AND later.movement_number > current.movement_number)
             )
            JOIN inventory_valuation_documents documents
              ON documents.movement_id = later.id AND documents.status = 'Approved'
            WHERE current.id = ?
            ORDER BY later.movement_date, later.movement_number
            LIMIT 1
            """,
            (movement_id,),
        )

    def required_dimensions_count(self, workspace_id: str, organization_id: str) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS total FROM accounting_dimensions
            WHERE workspace_id = ? AND required_on_entries = 1
              AND (organization_id IS NULL OR organization_id = ?)
            """,
            (workspace_id, organization_id),
        ).fetchone()
        return int(row["total"]) if row is not None else 0

    def active_document_for_movement(self, movement_id: str) -> dict[str, Any] | None:
        document = self._one(
            """
            SELECT * FROM inventory_valuation_documents
            WHERE movement_id = ? AND status <> 'Cancelled'
            """,
            (movement_id,),
        )
        if document is not None or not self._table_exists("inventory_valuation_reversals"):
            return document
        return self._one(
            """
            SELECT id, reversal_number AS valuation_number, status
            FROM inventory_valuation_reversals
            WHERE reversal_movement_id = ? AND status <> 'Cancelled'
            """,
            (movement_id,),
        )

    def document(self, document_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT documents.*, movements.movement_number, movements.movement_type,
                   movements.status AS movement_status, organizations.organization_code,
                   entities.entity_code, periods.name AS period_name,
                   policies.policy_code, policies.costing_method,
                   entries.entry_number AS finance_entry_number,
                   entries.status AS finance_entry_status
            FROM inventory_valuation_documents documents
            JOIN inventory_movements movements ON movements.id = documents.movement_id
            JOIN organizations ON organizations.id = documents.organization_id
            JOIN legal_entities entities ON entities.id = documents.legal_entity_id
            JOIN periods ON periods.id = documents.period_id
            JOIN inventory_valuation_policies policies ON policies.id = documents.policy_id
            LEFT JOIN ledger_entries entries ON entries.id = documents.finance_entry_id
            WHERE documents.id = ?
            """,
            (document_id,),
        )

    def insert_document(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_valuation_documents (
                id, workspace_id, organization_id, legal_entity_id, period_id,
                movement_id, policy_id, valuation_number, valuation_date,
                currency_code, status, created_by, created_at, updated_at
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
                    "movement_id",
                    "policy_id",
                    "valuation_number",
                    "valuation_date",
                    "currency_code",
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            ),
        )

    def insert_input_costs(self, records: Sequence[Mapping[str, object]]) -> None:
        self.connection.executemany(
            """
            INSERT INTO inventory_valuation_input_costs (
                id, valuation_document_id, movement_line_id, total_cost_minor, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                tuple(
                    record[key]
                    for key in ("id", "valuation_document_id", "movement_line_id", "total_cost_minor", "created_at")
                )
                for record in records
            ],
        )

    def input_costs(self, document_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT costs.*, movement_lines.line_number
            FROM inventory_valuation_input_costs costs
            JOIN inventory_movement_lines movement_lines ON movement_lines.id = costs.movement_line_id
            WHERE costs.valuation_document_id = ? ORDER BY movement_lines.line_number
            """,
            (document_id,),
        )

    def insert_valuation_line(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_valuation_lines (
                id, valuation_document_id, movement_line_id, line_number, flow_direction,
                item_id, uom_id, inventory_lot_id, quantity_scaled, quantity_precision,
                value_minor, inventory_account_id, offset_account_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(
                record[key]
                for key in (
                    "id",
                    "valuation_document_id",
                    "movement_line_id",
                    "line_number",
                    "flow_direction",
                    "item_id",
                    "uom_id",
                    "inventory_lot_id",
                    "quantity_scaled",
                    "quantity_precision",
                    "value_minor",
                    "inventory_account_id",
                    "offset_account_id",
                    "created_at",
                )
            ),
        )

    def insert_cost_layer(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_cost_layers (
                id, source_valuation_line_id, legal_entity_id, item_id, uom_id,
                inventory_lot_id, quantity_precision, original_quantity_scaled,
                remaining_quantity_scaled, original_value_minor, remaining_value_minor,
                currency_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tuple(
                record[key]
                for key in (
                    "id",
                    "source_valuation_line_id",
                    "legal_entity_id",
                    "item_id",
                    "uom_id",
                    "inventory_lot_id",
                    "quantity_precision",
                    "original_quantity_scaled",
                    "remaining_quantity_scaled",
                    "original_value_minor",
                    "remaining_value_minor",
                    "currency_code",
                    "created_at",
                )
            ),
        )

    def open_cost_layers(
        self, legal_entity_id: str, item_id: str, inventory_lot_id: str | None
    ) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT layers.*
            FROM inventory_cost_layers layers
            JOIN inventory_valuation_lines source_lines ON source_lines.id = layers.source_valuation_line_id
            JOIN inventory_valuation_documents source_documents
              ON source_documents.id = source_lines.valuation_document_id
            WHERE layers.legal_entity_id = ? AND layers.item_id = ?
              AND COALESCE(layers.inventory_lot_id, '') = COALESCE(?, '')
              AND layers.remaining_quantity_scaled > 0
              AND source_documents.status = 'Approved'
            ORDER BY source_documents.valuation_date, source_documents.valuation_number,
                     source_lines.line_number, layers.id
            """,
            (legal_entity_id, item_id, inventory_lot_id),
        )

    def insert_layer_consumption(self, record: Mapping[str, object]) -> None:
        self.connection.execute(
            """
            INSERT INTO inventory_layer_consumptions (
                id, valuation_line_id, cost_layer_id, quantity_scaled, value_minor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            tuple(
                record[key]
                for key in ("id", "valuation_line_id", "cost_layer_id", "quantity_scaled", "value_minor", "created_at")
            ),
        )

    def update_cost_layer(self, layer_id: str, quantity_scaled: int, value_minor: int) -> int:
        cursor = self.connection.execute(
            """
            UPDATE inventory_cost_layers
            SET remaining_quantity_scaled = ?, remaining_value_minor = ?
            WHERE id = ? AND remaining_quantity_scaled >= ? AND remaining_value_minor >= ?
            """,
            (quantity_scaled, value_minor, layer_id, quantity_scaled, value_minor),
        )
        return cursor.rowcount

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
        self.connection.executemany(
            """
            INSERT INTO ledger_lines (
                id, entry_id, line_number, account_id, description,
                debit_minor, credit_minor, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
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
                )
                for line in lines
            ],
        )

    def approve_document(
        self,
        document_id: str,
        *,
        actor: str,
        timestamp: str,
        reason: str,
        total_value_minor: int,
        finance_entry_id: str,
    ) -> int:
        cursor = self.connection.execute(
            """
            UPDATE inventory_valuation_documents
            SET status = 'Approved', approved_by = ?, approved_at = ?, approval_reason = ?,
                total_value_minor = ?, finance_entry_id = ?, updated_at = ?
            WHERE id = ? AND status = 'Draft'
            """,
            (actor, timestamp, reason, total_value_minor, finance_entry_id, timestamp, document_id),
        )
        return cursor.rowcount

    def cancel_document(self, document_id: str, *, actor: str, timestamp: str, reason: str) -> int:
        cursor = self.connection.execute(
            """
            UPDATE inventory_valuation_documents
            SET status = 'Cancelled', cancelled_by = ?, cancelled_at = ?,
                cancel_reason = ?, updated_at = ?
            WHERE id = ? AND status = 'Draft'
            """,
            (actor, timestamp, reason, timestamp, document_id),
        )
        return cursor.rowcount

    def valuation_lines(self, document_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT lines.*, items.item_code, units.uom_code, lots.lot_serial_code,
                   inventory_accounts.account_code AS inventory_account_code,
                   offset_accounts.account_code AS offset_account_code
            FROM inventory_valuation_lines lines
            JOIN inventory_items items ON items.id = lines.item_id
            JOIN units_of_measure units ON units.id = lines.uom_id
            LEFT JOIN inventory_lots lots ON lots.id = lines.inventory_lot_id
            JOIN accounts inventory_accounts ON inventory_accounts.id = lines.inventory_account_id
            JOIN accounts offset_accounts ON offset_accounts.id = lines.offset_account_id
            WHERE lines.valuation_document_id = ? ORDER BY lines.line_number
            """,
            (document_id,),
        )

    def layer_consumptions(self, document_id: str) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT consumptions.*, lines.line_number, layers.source_valuation_line_id
            FROM inventory_layer_consumptions consumptions
            JOIN inventory_valuation_lines lines ON lines.id = consumptions.valuation_line_id
            JOIN inventory_cost_layers layers ON layers.id = consumptions.cost_layer_id
            JOIN inventory_valuation_lines source_lines ON source_lines.id = layers.source_valuation_line_id
            JOIN inventory_valuation_documents source_documents
              ON source_documents.id = source_lines.valuation_document_id
            WHERE lines.valuation_document_id = ?
            ORDER BY lines.line_number, source_documents.valuation_date,
                     source_documents.valuation_number, source_lines.line_number, layers.id
            """,
            (document_id,),
        )

    def finance_entry(self, entry_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM ledger_entries WHERE id = ?", (entry_id,))

    def finance_entry_by_number(self, workspace_id: str, entry_number: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT * FROM ledger_entries WHERE workspace_id = ? AND entry_number = ?",
            (workspace_id, entry_number),
        )

    def list_policies(self, workspace_id: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
        return self._many(
            """
            SELECT policies.*, organizations.organization_code, entities.entity_code,
                   journals.journal_code, journals.chart_id,
                   journals.active AS journal_active, journals.currency_code AS journal_currency_code,
                   receipt_accounts.active AS receipt_account_active,
                   receipt_accounts.allow_posting AS receipt_account_allow_posting,
                   cogs_accounts.active AS cogs_account_active,
                   cogs_accounts.allow_posting AS cogs_account_allow_posting,
                   adjustment_accounts.active AS adjustment_account_active,
                   adjustment_accounts.allow_posting AS adjustment_account_allow_posting,
                   receipt_accounts.account_code AS receipt_clearing_account_code,
                   cogs_accounts.account_code AS cogs_account_code,
                   adjustment_accounts.account_code AS adjustment_account_code
            FROM inventory_valuation_policies policies
            JOIN organizations ON organizations.id = policies.organization_id
            JOIN legal_entities entities ON entities.id = policies.legal_entity_id
            JOIN finance_journals journals ON journals.id = policies.finance_journal_id
            JOIN accounts receipt_accounts ON receipt_accounts.id = policies.receipt_clearing_account_id
            JOIN accounts cogs_accounts ON cogs_accounts.id = policies.cogs_account_id
            JOIN accounts adjustment_accounts ON adjustment_accounts.id = policies.adjustment_account_id
            WHERE policies.workspace_id = ?
            ORDER BY organizations.organization_code, entities.entity_code, policies.policy_code
            LIMIT ? OFFSET ?
            """,
            (workspace_id, limit, offset),
        )

    def list_documents(self, workspace_id: str, *, status: str, limit: int, offset: int) -> list[dict[str, Any]]:
        query = """
            SELECT documents.*, movements.movement_number, movements.movement_type,
                   organizations.organization_code, entities.entity_code,
                   policies.policy_code, entries.entry_number AS finance_entry_number,
                   entries.status AS finance_entry_status
            FROM inventory_valuation_documents documents
            JOIN inventory_movements movements ON movements.id = documents.movement_id
            JOIN organizations ON organizations.id = documents.organization_id
            JOIN legal_entities entities ON entities.id = documents.legal_entity_id
            JOIN inventory_valuation_policies policies ON policies.id = documents.policy_id
            LEFT JOIN ledger_entries entries ON entries.id = documents.finance_entry_id
            WHERE documents.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if status:
            query += " AND documents.status = ?"
            parameters.append(status)
        query += " ORDER BY documents.valuation_date DESC, documents.valuation_number LIMIT ? OFFSET ?"
        parameters.extend((limit, offset))
        return self._many(query, tuple(parameters))

    def list_cost_layers(self, workspace_id: str, *, open_only: bool, limit: int, offset: int) -> list[dict[str, Any]]:
        query = """
            SELECT layers.*, items.item_code, units.uom_code, lots.lot_serial_code,
                   entities.entity_code, source_documents.valuation_number
            FROM inventory_cost_layers layers
            JOIN legal_entities entities ON entities.id = layers.legal_entity_id
            JOIN organizations ON organizations.id = entities.organization_id
            JOIN inventory_items items ON items.id = layers.item_id
            JOIN units_of_measure units ON units.id = layers.uom_id
            LEFT JOIN inventory_lots lots ON lots.id = layers.inventory_lot_id
            JOIN inventory_valuation_lines source_lines ON source_lines.id = layers.source_valuation_line_id
            JOIN inventory_valuation_documents source_documents
              ON source_documents.id = source_lines.valuation_document_id
            WHERE organizations.workspace_id = ? AND source_documents.status = 'Approved'
        """
        if open_only:
            query += " AND layers.remaining_quantity_scaled > 0"
        query += " ORDER BY layers.created_at, layers.id LIMIT ? OFFSET ?"
        return self._many(query, (workspace_id, limit, offset))

    def summary_counts(self, workspace_id: str) -> dict[str, int]:
        row = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM inventory_valuation_policies WHERE workspace_id = ?) AS policies,
                (SELECT COUNT(*) FROM inventory_valuation_documents
                 WHERE workspace_id = ? AND status = 'Draft') AS draft_documents,
                (SELECT COUNT(*) FROM inventory_valuation_documents
                 WHERE workspace_id = ? AND status = 'Approved') AS approved_documents,
                (SELECT COUNT(*) FROM inventory_cost_layers layers
                 JOIN legal_entities entities ON entities.id = layers.legal_entity_id
                 JOIN organizations organizations ON organizations.id = entities.organization_id
                 WHERE organizations.workspace_id = ? AND layers.remaining_quantity_scaled > 0) AS open_layers
            """,
            (workspace_id, workspace_id, workspace_id, workspace_id),
        ).fetchone()
        if row is None:
            return {}
        if self._table_exists("inventory_valuation_reversals"):
            unvalued_row = self.connection.execute(
                """
                SELECT COUNT(*) AS total FROM inventory_movements movements
                WHERE movements.workspace_id = ? AND movements.status = 'Posted'
                  AND movements.movement_type <> 'Transfer'
                  AND NOT EXISTS (
                      SELECT 1 FROM inventory_valuation_documents documents
                      WHERE documents.movement_id = movements.id AND documents.status = 'Approved'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM inventory_valuation_reversals reversals
                      WHERE reversals.reversal_movement_id = movements.id
                        AND reversals.status = 'Approved'
                  )
                """,
                (workspace_id,),
            ).fetchone()
        else:
            unvalued_row = self.connection.execute(
                """
                SELECT COUNT(*) AS total FROM inventory_movements movements
                WHERE movements.workspace_id = ? AND movements.status = 'Posted'
                  AND movements.movement_type <> 'Transfer'
                  AND NOT EXISTS (
                      SELECT 1 FROM inventory_valuation_documents documents
                      WHERE documents.movement_id = movements.id AND documents.status = 'Approved'
                  )
                """,
                (workspace_id,),
            ).fetchone()
        result = {str(key): int(value) for key, value in dict(row).items()}
        result["unvalued_posted_movements"] = int(unvalued_row["total"]) if unvalued_row is not None else 0
        return result

    def _table_exists(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        return row is not None

    def _one(self, query: str, parameters: tuple[object, ...]) -> dict[str, Any] | None:
        row = self.connection.execute(query, parameters).fetchone()
        return dict(row) if row is not None else None

    def _many(self, query: str, parameters: tuple[object, ...]) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(query, parameters).fetchall()]
