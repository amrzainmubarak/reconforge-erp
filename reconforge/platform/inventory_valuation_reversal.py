"""Governed FIFO valuation reversal through exact compensating movements."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import PlatformError, audit, ensure_platform_schema, platform_id, require_permission
from reconforge.platform.inventory_valuation import INVENTORY_READ_PERMISSION
from reconforge.platform.inventory_valuation_reversal_repository import (
    InventoryValuationReversalRepository,
    SQLiteInventoryValuationReversalRepository,
)
from reconforge.platform.inventory_values import clean_text, document_number, minor_to_text, page, scaled_to_text

REVERSAL_STATUSES = ("Draft", "Approved", "Cancelled")
REVERSAL_MANAGE_PERMISSION = "inventory.valuation.reverse.manage"
REVERSAL_APPROVE_PERMISSION = "inventory.valuation.reverse.approve"


@dataclass(frozen=True)
class InventoryValuationReversalSummary:
    """Bounded reversal workflow counts for one local workspace."""

    workspace: str
    draft_reversals: int
    approved_reversals: int
    cancelled_reversals: int
    approved_effects: int
    finance_drafts: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class InventoryValuationReversalService:
    """Reverse Approved FIFO evidence without deleting its historical chain.

    A caller first posts an exact opposite inventory movement. Approval then
    restores or removes the original layer effects and prepares a balanced
    Finance Core Draft with the original entry's debit/credit sides swapped.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        repository: InventoryValuationReversalRepository | None = None,
    ) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self.repository = repository or SQLiteInventoryValuationReversalRepository(connection)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        expected = {
            "inventory_valuation_reversals",
            "inventory_valuation_reversal_effects",
        }
        try:
            existing = {
                str(row["name"])
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to inspect the valuation-reversal schema.") from exc
        if not expected <= existing:
            raise PlatformError("Valuation-reversal schema is unavailable. Run 'reconforge db migrate' first.")

    def create_reversal(
        self,
        *,
        reversal_number: str,
        original_valuation_document_id: str,
        reversal_movement_id: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Link an Approved valuation to an already-Posted exact opposite movement."""

        actor_user = require_permission(
            self.connection, actor_label=actor_label, permission=REVERSAL_MANAGE_PERMISSION
        )
        document_id = clean_text(
            original_valuation_document_id, "Original valuation document ID"
        )
        movement_id = clean_text(reversal_movement_id, "Reversal movement ID")
        original = self._required(
            self.repository.original_document(document_id), "Original inventory valuation was not found."
        )
        if str(original["status"]) != "Approved":
            raise PlatformError("Only an Approved inventory valuation can be reversed.")
        if not original.get("finance_entry_id"):
            raise PlatformError("Approved valuation is missing its protected Finance Core entry.")
        if self.repository.active_reversal_for_document(document_id) is not None:
            raise PlatformError("This valuation already has an active reversal workflow.")
        movement = self._required(
            self.repository.movement(movement_id), "Reversal inventory movement was not found."
        )
        self._validate_reversal_scope(original, movement)
        if self.repository.active_valuation_for_movement(movement_id) is not None:
            raise PlatformError("The reversal movement cannot also have a normal valuation document.")
        if self.repository.active_reversal_for_movement(movement_id) is not None:
            raise PlatformError("The reversal movement is already assigned to another reversal workflow.")
        self._validate_mirror_lines(original, movement)
        number = document_number(reversal_number, "Valuation reversal number")
        reversal_id = platform_id("IVR", original["workspace_id"], number)
        now = utc_now_text()
        actor = actor_user.username if actor_user is not None else clean_text(actor_label, "Actor label")
        record: dict[str, object] = {
            "id": reversal_id,
            "workspace_id": original["workspace_id"],
            "organization_id": original["organization_id"],
            "legal_entity_id": original["legal_entity_id"],
            "period_id": movement["period_id"],
            "original_valuation_document_id": original["id"],
            "reversal_movement_id": movement["id"],
            "reversal_number": number,
            "reversal_date": movement["movement_date"],
            "currency_code": original["currency_code"],
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.repository.transaction():
                self.repository.insert_reversal(record)
        except sqlite3.IntegrityError as exc:
            raise PlatformError("Reversal number, valuation, or movement is already assigned.") from exc
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save the local valuation reversal Draft.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_valuation_reversal",
            object_id=reversal_id,
            action="inventory_valuation_reversal_draft_created",
            metadata={
                "reversal_number": number,
                "original_valuation_document_id": original["id"],
                "reversal_movement_id": movement["id"],
            },
        )
        return self.get_reversal(reversal_id, actor_label=actor_label)

    def approve_reversal(
        self,
        reversal_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Approve exact layer effects and prepare a separate Finance Core Draft."""

        actor_user = require_permission(
            self.connection, actor_label=actor_label, permission=REVERSAL_APPROVE_PERMISSION
        )
        approval_reason = clean_text(reason, "Approval reason", maximum=500)
        actor = actor_user.username if actor_user is not None else clean_text(actor_label, "Actor label")
        selected_id = clean_text(reversal_id, "Valuation reversal ID")
        now = utc_now_text()
        reversal_number_value = ""
        finance_entry_id = ""
        total_value_minor = 0
        effect_count = 0
        try:
            with self.repository.transaction():
                reversal = self._required(
                    self.repository.reversal(selected_id), "Inventory valuation reversal was not found."
                )
                reversal_number_value = str(reversal["reversal_number"])
                if str(reversal["status"]) != "Draft":
                    raise PlatformError("Only Draft valuation reversals can be approved.")
                if actor_user is not None and str(reversal["created_by"]) == actor_user.username:
                    raise PlatformError("Segregation of duties prevents approving your own valuation reversal.")
                original = self._required(
                    self.repository.original_document(str(reversal["original_valuation_document_id"])),
                    "Original inventory valuation was not found.",
                )
                if str(original["status"]) != "Approved":
                    raise PlatformError("Reversal approval requires the original valuation to remain Approved.")
                movement = self._required(
                    self.repository.movement(str(reversal["reversal_movement_id"])),
                    "Reversal inventory movement was not found.",
                )
                self._validate_reversal_scope(original, movement)
                self._validate_mirror_lines(original, movement)
                effects, balances = self._prepare_effects(
                    reversal_id=selected_id,
                    original_document_id=str(original["id"]),
                    created_at=now,
                )
                effect_count = len(effects)
                total_value_minor = sum(int(str(effect["value_minor"])) for effect in effects)
                if total_value_minor != int(str(original["total_value_minor"])):
                    raise PlatformError("Valuation reversal layer effects do not equal the original total value.")
                finance_entry_id = self._insert_reversal_finance_draft(
                    reversal=reversal,
                    original=original,
                    created_at=now,
                )
                for effect in effects:
                    self.repository.insert_effect(effect)
                for layer_id, balance in sorted(balances.items()):
                    if self.repository.update_layer(
                        layer_id,
                        expected_quantity=balance["expected_quantity"],
                        expected_value=balance["expected_value"],
                        new_quantity=balance["new_quantity"],
                        new_value=balance["new_value"],
                    ) != 1:
                        raise PlatformError("FIFO layer changed concurrently; reload the reversal and retry.")
                if self.repository.approve_reversal(
                    selected_id,
                    actor=actor,
                    timestamp=now,
                    reason=approval_reason,
                    total_value_minor=total_value_minor,
                    finance_entry_id=finance_entry_id,
                ) != 1:
                    raise PlatformError("Valuation reversal changed concurrently; reload and retry.")
        except PlatformError:
            raise
        except sqlite3.IntegrityError as exc:
            raise PlatformError("Unable to approve reversal because protected local evidence conflicts.") from exc
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to approve the local valuation reversal.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_valuation_reversal",
            object_id=selected_id,
            action="inventory_valuation_reversal_approved",
            metadata={
                "reversal_number": reversal_number_value,
                "effect_count": effect_count,
                "total_value_minor": total_value_minor,
                "finance_entry_id": finance_entry_id,
                "finance_entry_status": "Draft",
            },
        )
        return self.get_reversal(selected_id, actor_label=actor_label)

    def cancel_reversal(
        self,
        reversal_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Cancel a Draft reversal without changing its independent movement."""

        require_permission(
            self.connection, actor_label=actor_label, permission=REVERSAL_MANAGE_PERMISSION
        )
        selected_id = clean_text(reversal_id, "Valuation reversal ID")
        cancel_reason = clean_text(reason, "Cancellation reason", maximum=500)
        actor = clean_text(actor_label, "Actor label")
        now = utc_now_text()
        try:
            with self.repository.transaction():
                reversal = self._required(
                    self.repository.reversal(selected_id), "Inventory valuation reversal was not found."
                )
                if str(reversal["status"]) != "Draft":
                    raise PlatformError("Only Draft valuation reversals can be cancelled.")
                if self.repository.cancel_reversal(
                    selected_id, actor=actor, timestamp=now, reason=cancel_reason
                ) != 1:
                    raise PlatformError("Valuation reversal changed concurrently; reload and retry.")
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to cancel the local valuation reversal.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_valuation_reversal",
            object_id=selected_id,
            action="inventory_valuation_reversal_cancelled",
            metadata={"reason": cancel_reason},
        )
        return self.get_reversal(selected_id, actor_label=actor_label)

    def get_reversal(self, reversal_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        try:
            record = self._required(
                self.repository.reversal(clean_text(reversal_id, "Valuation reversal ID")),
                "Inventory valuation reversal was not found.",
            )
            return self._public_reversal(record, include_effects=True)
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local valuation reversal.") from exc

    def list_reversals(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        selected_status = self._status(status) if status else ""
        page_limit, page_offset = page(limit, offset)
        workspace_record = self.repository.workspace_by_name(clean_text(workspace, "Workspace name"))
        if workspace_record is None:
            return []
        try:
            rows = self.repository.list_reversals(
                str(workspace_record["id"]),
                status=selected_status,
                limit=page_limit,
                offset=page_offset,
            )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local valuation reversals.") from exc
        return [self._public_reversal(row, include_effects=False) for row in rows]

    def summary(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> InventoryValuationReversalSummary:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        workspace_name = clean_text(workspace, "Workspace name")
        workspace_record = self.repository.workspace_by_name(workspace_name)
        try:
            counts = (
                self.repository.summary_counts(str(workspace_record["id"])) if workspace_record else {}
            )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to summarize local valuation reversals.") from exc
        return InventoryValuationReversalSummary(
            workspace=workspace_name,
            draft_reversals=counts.get("draft_reversals", 0),
            approved_reversals=counts.get("approved_reversals", 0),
            cancelled_reversals=counts.get("cancelled_reversals", 0),
            approved_effects=counts.get("approved_effects", 0),
            finance_drafts=counts.get("finance_drafts", 0),
        )

    def snapshot(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        """Return a bounded, path-free valuation-reversal contract."""

        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {
                "kind": "local-inventory-valuation-reversal",
                "local_first": True,
                "external_calls": False,
            },
            "workspace": clean_text(workspace, "Workspace name"),
            "summary": self.summary(workspace=workspace, actor_label=actor_label).to_dict(),
            "reversals": self.list_reversals(workspace=workspace, actor_label=actor_label),
            "boundary_note": (
                "Approval requires a separately Posted exact opposite movement and prepares a balanced "
                "Finance Core Draft. It deletes no history, validates no entry, and writes to no ERP."
            ),
        }

    def _validate_reversal_scope(
        self, original: Mapping[str, object], movement: Mapping[str, object]
    ) -> None:
        if str(movement["id"]) == str(original["movement_id"]):
            raise PlatformError("The original movement cannot serve as its own compensating movement.")
        if str(movement["status"]) != "Posted":
            raise PlatformError("Valuation reversal requires a separately Posted compensating movement.")
        if str(movement["period_status"]) != "Open":
            raise PlatformError("Valuation reversal requires the compensating movement period to remain Open.")
        if str(movement["movement_date"]) < str(original["original_movement_date"]):
            raise PlatformError("Compensating movement cannot predate the original valued movement.")
        for field, label in (
            ("workspace_id", "workspace"),
            ("organization_id", "organization"),
            ("legal_entity_id", "legal entity"),
        ):
            if str(movement[field]) != str(original[field]):
                raise PlatformError(f"Compensating movement must use the original valuation {label}.")
        if str(movement["entity_currency"]) != str(original["currency_code"]):
            raise PlatformError("Compensating movement entity currency must match the original valuation.")
        expected_type = self._expected_reversal_type(str(original["original_movement_type"]))
        if str(movement["movement_type"]) != expected_type:
            raise PlatformError(f"Compensating movement type must be {expected_type}.")

    def _validate_mirror_lines(
        self, original: Mapping[str, object], movement: Mapping[str, object]
    ) -> None:
        original_lines = self.repository.movement_lines(str(original["movement_id"]))
        reversal_lines = self.repository.movement_lines(str(movement["id"]))
        if not original_lines or len(original_lines) != len(reversal_lines):
            raise PlatformError("Compensating movement must mirror every original line exactly.")
        reversal_by_number = {int(line["line_number"]): line for line in reversal_lines}
        for original_line in original_lines:
            line_number = int(original_line["line_number"])
            reversal_line = reversal_by_number.get(line_number)
            if reversal_line is None or any(
                str(reversal_line.get(field) or "") != str(expected or "")
                for field, expected in (
                    ("item_id", original_line["item_id"]),
                    ("uom_id", original_line["uom_id"]),
                    ("inventory_lot_id", original_line.get("inventory_lot_id")),
                    ("from_location_id", original_line.get("to_location_id")),
                    ("to_location_id", original_line.get("from_location_id")),
                    ("quantity_scaled", original_line["quantity_scaled"]),
                    ("quantity_precision", original_line["quantity_precision"]),
                )
            ):
                raise PlatformError(
                    f"Compensating movement line {line_number} must exactly swap the original locations and quantity."
                )

    def _prepare_effects(
        self,
        *,
        reversal_id: str,
        original_document_id: str,
        created_at: str,
    ) -> tuple[list[dict[str, object]], dict[str, dict[str, int]]]:
        lines = self.repository.original_lines(original_document_id)
        consumptions_by_line: dict[str, list[dict[str, Any]]] = {}
        for consumption in self.repository.original_consumptions(original_document_id):
            consumptions_by_line.setdefault(str(consumption["valuation_line_id"]), []).append(consumption)
        effects: list[dict[str, object]] = []
        balances: dict[str, dict[str, int]] = {}
        for line in lines:
            line_id = str(line["id"])
            if str(line["flow_direction"]) == "Inbound":
                if not line.get("cost_layer_id"):
                    raise PlatformError("Original inbound valuation layer was not found.")
                layer = line
                current_quantity = int(layer["remaining_quantity_scaled"])
                current_value = int(layer["remaining_value_minor"])
                if (
                    current_quantity != int(layer["original_quantity_scaled"])
                    or current_value != int(layer["original_value_minor"])
                ):
                    raise PlatformError(
                        f"Inbound layer for original line {line['line_number']} is still consumed; "
                        "reverse dependent outbound valuations first."
                    )
                layer_id = str(layer["cost_layer_id"])
                effects.append(
                    {
                        "id": platform_id("IVE", reversal_id, line_id, "Remove"),
                        "reversal_id": reversal_id,
                        "original_valuation_line_id": line_id,
                        "original_consumption_id": None,
                        "cost_layer_id": layer_id,
                        "effect_type": "Remove",
                        "quantity_scaled": int(line["quantity_scaled"]),
                        "value_minor": int(line["value_minor"]),
                        "created_at": created_at,
                    }
                )
                balances[layer_id] = {
                    "expected_quantity": current_quantity,
                    "expected_value": current_value,
                    "new_quantity": 0,
                    "new_value": 0,
                }
                continue
            consumptions = consumptions_by_line.get(line_id, [])
            if not consumptions:
                raise PlatformError("Original outbound valuation consumption evidence is missing.")
            for consumption in consumptions:
                layer_id = str(consumption["cost_layer_id"])
                balance = balances.setdefault(
                    layer_id,
                    {
                        "expected_quantity": int(consumption["remaining_quantity_scaled"]),
                        "expected_value": int(consumption["remaining_value_minor"]),
                        "new_quantity": int(consumption["remaining_quantity_scaled"]),
                        "new_value": int(consumption["remaining_value_minor"]),
                    },
                )
                balance["new_quantity"] += int(consumption["quantity_scaled"])
                balance["new_value"] += int(consumption["value_minor"])
                if (
                    balance["new_quantity"] > int(consumption["original_quantity_scaled"])
                    or balance["new_value"] > int(consumption["original_value_minor"])
                ):
                    raise PlatformError("Restoring the outbound valuation would overstate its FIFO layer.")
                effects.append(
                    {
                        "id": platform_id("IVE", reversal_id, consumption["id"], "Restore"),
                        "reversal_id": reversal_id,
                        "original_valuation_line_id": line_id,
                        "original_consumption_id": consumption["id"],
                        "cost_layer_id": layer_id,
                        "effect_type": "Restore",
                        "quantity_scaled": int(consumption["quantity_scaled"]),
                        "value_minor": int(consumption["value_minor"]),
                        "created_at": created_at,
                    }
                )
        if not effects:
            raise PlatformError("Valuation reversal requires at least one exact layer effect.")
        return effects, balances

    def _insert_reversal_finance_draft(
        self,
        *,
        reversal: Mapping[str, object],
        original: Mapping[str, object],
        created_at: str,
    ) -> str:
        original_entry_id = clean_text(original.get("finance_entry_id"), "Original Finance Core entry ID")
        original_lines = self.repository.finance_lines(original_entry_id)
        if len(original_lines) < 2:
            raise PlatformError("Original Finance Core entry is missing balanced line evidence.")
        total_debit = sum(int(line["credit_minor"]) for line in original_lines)
        total_credit = sum(int(line["debit_minor"]) for line in original_lines)
        if total_debit <= 0 or total_debit != total_credit:
            raise PlatformError("Original Finance Core entry cannot produce a balanced reversal Draft.")
        number = f"IVR-{reversal['reversal_number']}"
        if len(number) > 64:
            digest = sha256(str(reversal["id"]).encode("utf-8")).hexdigest()[:16].upper()
            number = f"IVR-{digest}"
        if self.repository.finance_entry_by_number(str(reversal["workspace_id"]), number) is not None:
            raise PlatformError("Generated reversal Finance Core entry number already exists.")
        entry_id = platform_id("GLE", reversal["workspace_id"], number)
        entry: dict[str, object] = {
            "id": entry_id,
            "workspace_id": reversal["workspace_id"],
            "organization_id": reversal["organization_id"],
            "chart_id": original["chart_id"],
            "legal_entity_id": reversal["legal_entity_id"],
            "period_id": reversal["period_id"],
            "finance_journal_id": original["finance_journal_id"],
            "entry_number": number,
            "posting_date": reversal["reversal_date"],
            "currency_code": reversal["currency_code"],
            "description": f"FIFO valuation reversal {reversal['reversal_number']}",
            "external_reference": f"Reverses valuation {original['valuation_number']}",
            "created_by": reversal["created_by"],
            "created_at": created_at,
            "updated_at": created_at,
        }
        lines = [
            {
                "id": platform_id("GLL", entry_id, line_number),
                "entry_id": entry_id,
                "line_number": line_number,
                "account_id": line["account_id"],
                "description": f"Reverse FIFO valuation {original['valuation_number']}",
                "debit_minor": int(line["credit_minor"]),
                "credit_minor": int(line["debit_minor"]),
                "dimension_value_ids": self.repository.line_dimensions(str(line["id"])),
                "created_at": created_at,
            }
            for line_number, line in enumerate(original_lines, start=1)
        ]
        self.repository.insert_finance_draft(entry, lines)
        return entry_id

    def _public_reversal(
        self, reversal: Mapping[str, object], *, include_effects: bool
    ) -> dict[str, Any]:
        result = dict(reversal)
        currency = self._required(
            self.repository.currency(str(result["currency_code"])),
            "Valuation reversal currency is unavailable.",
        )
        minor_units = int(currency["minor_units"])
        result["total_value"] = minor_to_text(
            int(str(result.pop("total_value_minor"))), minor_units
        )
        if "original_total_value_minor" in result:
            result["original_total_value"] = minor_to_text(
                int(str(result.pop("original_total_value_minor"))), minor_units
            )
        if include_effects:
            effects = self.repository.effects(str(result["id"]))
            public_effects: list[dict[str, Any]] = []
            for effect in effects:
                item = dict(effect)
                precision = int(item["quantity_precision"])
                item["quantity"] = scaled_to_text(int(item.pop("quantity_scaled")), precision)
                item["value"] = minor_to_text(int(item.pop("value_minor")), minor_units)
                public_effects.append(item)
            result["effects"] = public_effects
        return result

    @staticmethod
    def _expected_reversal_type(original_type: str) -> str:
        mapping = {"Receipt": "Delivery", "Delivery": "Receipt", "Adjustment": "Adjustment"}
        try:
            return mapping[original_type]
        except KeyError as exc:
            raise PlatformError("Transfers and unsupported movements cannot be valuation-reversed.") from exc

    @staticmethod
    def _status(value: object) -> str:
        raw = clean_text(value, "Valuation reversal status", maximum=40)
        selected = {status.lower(): status for status in REVERSAL_STATUSES}.get(raw.lower())
        if selected is None:
            raise PlatformError(f"Valuation reversal status must be one of: {', '.join(REVERSAL_STATUSES)}.")
        return selected

    @staticmethod
    def _required(record: dict[str, Any] | None, message: str) -> dict[str, Any]:
        if record is None:
            raise PlatformError(message)
        return record
