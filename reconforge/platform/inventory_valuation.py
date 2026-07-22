"""Governed FIFO valuation and an explicit Inventory-to-Finance Draft bridge."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from hashlib import sha256
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    audit,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)
from reconforge.platform.inventory_valuation_repository import (
    InventoryValuationRepository,
    SQLiteInventoryValuationRepository,
)
from reconforge.platform.inventory_values import (
    MAX_AMOUNT_MINOR,
    amount_to_minor,
    choice,
    clean_text,
    code,
    document_number,
    iso_date,
    minor_to_text,
    page,
    scaled_to_text,
)

INVENTORY_READ_PERMISSION = "inventory.read"
VALUATION_MANAGE_PERMISSION = "inventory.valuation.manage"
VALUATION_APPROVE_PERMISSION = "inventory.valuation.approve"
VALUATION_STATUSES = ("Draft", "Approved", "Cancelled")
MAX_VALUATION_LINES = 1_000


@dataclass(frozen=True)
class InventoryValuationSummary:
    """Bounded control counts for the local valuation foundation."""

    workspace: str
    policies: int
    draft_documents: int
    approved_documents: int
    open_layers: int
    unvalued_posted_movements: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class InventoryValuationService:
    """Prepare and independently approve exact FIFO valuations.

    Approval creates a balanced Finance Core entry in ``Draft`` only. It never
    validates that entry and never writes back to an ERP.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        repository: InventoryValuationRepository | None = None,
    ) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self.repository = repository or SQLiteInventoryValuationRepository(connection)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        expected = {
            "inventory_valuation_policies",
            "inventory_valuation_documents",
            "inventory_valuation_input_costs",
            "inventory_valuation_lines",
            "inventory_cost_layers",
            "inventory_layer_consumptions",
        }
        try:
            existing = {
                str(row["name"])
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to inspect the local inventory valuation schema.") from exc
        if not expected <= existing:
            raise PlatformError("Inventory valuation schema is unavailable. Run 'reconforge db migrate' first.")

    def upsert_policy(
        self,
        *,
        policy_code: str,
        organization_code: str,
        entity_code: str,
        journal_code: str,
        receipt_clearing_account_code: str,
        cogs_account_code: str,
        adjustment_account_code: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update one entity-scoped FIFO policy."""

        actor_user = require_permission(
            self.connection, actor_label=actor_label, permission=VALUATION_MANAGE_PERMISSION
        )
        workspace_name = clean_text(workspace, "Workspace name")
        workspace_id = ensure_workspace(self.connection, workspace_name)
        organization = self._required(
            self.repository.organization(workspace_id, code(organization_code, "Organization code")),
            "Inventory valuation requires an existing organization.",
        )
        entity = self._required(
            self.repository.entity(str(organization["id"]), code(entity_code, "Entity code")),
            "Inventory valuation requires an existing legal entity.",
        )
        if not bool(organization["active"]) or not bool(entity["active"]):
            raise PlatformError("Inventory valuation requires an active organization and legal entity.")
        journal = self._required(
            self.repository.journal(
                workspace_id, str(organization["id"]), code(journal_code, "Journal code")
            ),
            "Inventory valuation requires an existing Finance Core journal.",
        )
        if not bool(journal["active"]) or not bool(journal["chart_active"]):
            raise PlatformError("Inventory valuation requires an active journal and chart of accounts.")
        if str(journal["currency_code"]) != str(entity["currency"]):
            raise PlatformError("Valuation journal and legal-entity currencies must match.")
        if self.repository.required_dimensions_count(workspace_id, str(organization["id"])):
            raise PlatformError(
                "Inventory valuation does not yet support required Finance Core dimensions; "
                "use a journal scope without required dimensions."
            )
        chart_id = str(journal["chart_id"])
        accounts = {
            "receipt_clearing_account_id": self._posting_account(
                chart_id, receipt_clearing_account_code, "Receipt clearing account"
            ),
            "cogs_account_id": self._posting_account(chart_id, cogs_account_code, "COGS account"),
            "adjustment_account_id": self._posting_account(
                chart_id, adjustment_account_code, "Adjustment account"
            ),
        }
        selected_code = code(policy_code, "Valuation policy code")
        policy_id = platform_id("IVP", workspace_id, organization["id"], entity["id"], selected_code)
        now = utc_now_text()
        actor = actor_user.username if actor_user is not None else clean_text(actor_label, "Actor label")
        existing = self.repository.policy_by_code(
            workspace_id, str(organization["id"]), str(entity["id"]), selected_code
        )
        protected_values = {
            "currency_code": str(entity["currency"]),
            "finance_journal_id": str(journal["id"]),
            **accounts,
        }
        if (
            existing is not None
            and self.repository.policy_has_approved_documents(str(existing["id"]))
            and any(str(existing[key]) != str(value) for key, value in protected_values.items())
        ):
            raise PlatformError(
                "A valuation policy referenced by Approved documents cannot change its financial setup."
            )
        record: dict[str, object] = {
            "id": policy_id,
            "workspace_id": workspace_id,
            "organization_id": organization["id"],
            "legal_entity_id": entity["id"],
            "policy_code": selected_code,
            **protected_values,
            "active": int(active),
            "created_by": str(existing["created_by"]) if existing is not None else actor,
            "created_at": str(existing["created_at"]) if existing is not None else now,
            "updated_at": now,
        }
        try:
            with self.repository.transaction():
                self.repository.upsert_policy(record)
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save the local FIFO valuation policy.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_valuation_policy",
            object_id=policy_id,
            action="inventory_valuation_policy_upserted",
            metadata={"policy_code": selected_code, "costing_method": "FIFO", "active": active},
        )
        return self.get_policy(policy_id, actor_label=actor_label)

    def create_document(
        self,
        *,
        valuation_number: str,
        movement_id: str,
        policy_code: str,
        input_costs: Sequence[Mapping[str, object]] = (),
        valuation_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Prepare a Draft valuation with exact inbound line costs."""

        actor_user = require_permission(
            self.connection, actor_label=actor_label, permission=VALUATION_MANAGE_PERMISSION
        )
        movement = self._required(
            self.repository.movement(clean_text(movement_id, "Movement ID")),
            "Inventory movement not found.",
        )
        if str(movement["status"]) != "Posted":
            raise PlatformError("Only Posted inventory movements can be prepared for valuation.")
        if str(movement["movement_type"]) == "Transfer":
            raise PlatformError("Transfers do not create valuation documents because entity cost ownership is unchanged.")
        if str(movement["period_status"]) != "Open":
            raise PlatformError("Inventory valuations can be prepared only while the movement period is Open.")
        workspace_id = str(movement["workspace_id"])
        policy = self._required(
            self.repository.policy_by_code(
                workspace_id,
                str(movement["organization_id"]),
                str(movement["legal_entity_id"]),
                code(policy_code, "Valuation policy code"),
            ),
            "Entity-scoped valuation policy not found.",
        )
        self._validate_policy_state(policy, movement)
        existing = self.repository.active_document_for_movement(str(movement["id"]))
        if existing is not None:
            raise PlatformError("This movement already has an active valuation document.")
        selected_date = str(movement["movement_date"])
        if valuation_date:
            parsed = iso_date(valuation_date, "Valuation date")
            if parsed is None:
                raise PlatformError("Valuation date is required when supplied.")
            if parsed.isoformat() != selected_date:
                raise PlatformError("Valuation date must equal the immutable inventory movement date.")
        number = document_number(valuation_number, "Valuation number")
        lines = self.repository.movement_lines(str(movement["id"]))
        if not 1 <= len(lines) <= MAX_VALUATION_LINES:
            raise PlatformError(f"Valuation documents require between 1 and {MAX_VALUATION_LINES} movement lines.")
        for line in lines:
            self._validate_inventory_line_account(line, policy)
        currency = self._required(
            self.repository.currency(str(policy["currency_code"])),
            "Valuation currency is unavailable.",
        )
        costs_by_line = self._prepare_input_costs(
            input_costs,
            movement_type=str(movement["movement_type"]),
            movement_lines=lines,
            minor_units=int(currency["minor_units"]),
        )
        document_id = platform_id("IVD", workspace_id, number)
        now = utc_now_text()
        actor = actor_user.username if actor_user is not None else clean_text(actor_label, "Actor label")
        document: dict[str, object] = {
            "id": document_id,
            "workspace_id": workspace_id,
            "organization_id": movement["organization_id"],
            "legal_entity_id": movement["legal_entity_id"],
            "period_id": movement["period_id"],
            "movement_id": movement["id"],
            "policy_id": policy["id"],
            "valuation_number": number,
            "valuation_date": selected_date,
            "currency_code": policy["currency_code"],
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
        }
        cost_records = [
            {
                "id": platform_id("IVC", document_id, movement_line_id),
                "valuation_document_id": document_id,
                "movement_line_id": movement_line_id,
                "total_cost_minor": total_minor,
                "created_at": now,
            }
            for movement_line_id, total_minor in sorted(costs_by_line.items())
        ]
        try:
            with self.repository.transaction():
                self.repository.insert_document(document)
                self.repository.insert_input_costs(cost_records)
        except sqlite3.IntegrityError as exc:
            raise PlatformError("Valuation number or movement is already assigned to an active document.") from exc
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save the local valuation Draft.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_valuation_document",
            object_id=document_id,
            action="inventory_valuation_draft_created",
            metadata={
                "valuation_number": number,
                "movement_id": movement["id"],
                "input_cost_lines": len(cost_records),
            },
        )
        return self.get_document(document_id, actor_label=actor_label)

    def approve_document(
        self,
        document_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Approve FIFO valuation atomically and create a balanced Finance Draft."""

        actor_user = require_permission(
            self.connection, actor_label=actor_label, permission=VALUATION_APPROVE_PERMISSION
        )
        approval_reason = clean_text(reason, "Approval reason", maximum=500)
        actor = actor_user.username if actor_user is not None else clean_text(actor_label, "Actor label")
        now = utc_now_text()
        finance_entry_id = ""
        total_value_minor = 0
        document_number_value = ""
        try:
            with self.repository.transaction():
                document = self._required(
                    self.repository.document(clean_text(document_id, "Valuation document ID")),
                    "Inventory valuation document not found.",
                )
                document_number_value = str(document["valuation_number"])
                if str(document["status"]) != "Draft":
                    raise PlatformError("Only Draft inventory valuations can be approved.")
                if actor_user is not None and str(document["created_by"]) == actor_user.username:
                    raise PlatformError("Segregation of duties prevents approving your own inventory valuation.")
                movement = self._required(
                    self.repository.movement(str(document["movement_id"])),
                    "Inventory movement not found.",
                )
                if str(movement["status"]) != "Posted" or str(movement["period_status"]) != "Open":
                    raise PlatformError("Valuation approval requires a Posted movement in an Open period.")
                policy = self._required(
                    self.repository.policy(str(document["policy_id"])),
                    "Inventory valuation policy not found.",
                )
                self._validate_policy_state(policy, movement)
                earlier = self.repository.earlier_unvalued_movement(str(movement["id"]))
                if earlier is not None:
                    raise PlatformError(
                        "FIFO approval requires earlier Posted movement "
                        f"{earlier['movement_number']} to be valued first."
                    )
                later = self.repository.later_approved_document(str(movement["id"]))
                if later is not None:
                    raise PlatformError(
                        "Backdated FIFO approval is blocked because later valuation "
                        f"{later['valuation_number']} is already Approved."
                    )
                if self.repository.required_dimensions_count(
                    str(document["workspace_id"]), str(document["organization_id"])
                ):
                    raise PlatformError(
                        "Valuation approval cannot generate a Finance Draft while required dimensions are configured."
                    )
                movement_lines = self.repository.movement_lines(str(movement["id"]))
                input_costs = {
                    str(record["movement_line_id"]): int(record["total_cost_minor"])
                    for record in self.repository.input_costs(str(document["id"]))
                }
                journal_postings: list[tuple[str, int, int, str]] = []
                for line in movement_lines:
                    self._validate_inventory_line_account(line, policy)
                    flow = self._line_flow(str(movement["movement_type"]), line)
                    offset_account_id = self._offset_account_id(str(movement["movement_type"]), policy)
                    valuation_line_id = platform_id("IVL", document["id"], line["id"])
                    quantity_scaled = int(line["quantity_scaled"])
                    if flow == "Inbound":
                        value_minor = input_costs.get(str(line["id"]), 0)
                        if value_minor <= 0:
                            raise PlatformError("Every inbound movement line requires an exact positive input cost.")
                    else:
                        allocations = self._fifo_allocations(
                            legal_entity_id=str(document["legal_entity_id"]),
                            line=line,
                        )
                        value_minor = sum(self._as_int(item["value_minor"]) for item in allocations)
                    if value_minor <= 0:
                        raise PlatformError("Every valuation line must carry a positive currency value.")
                    total_value_minor += value_minor
                    if total_value_minor > MAX_AMOUNT_MINOR:
                        raise PlatformError("Valuation total exceeds the supported local amount range.")
                    valuation_line: dict[str, object] = {
                        "id": valuation_line_id,
                        "valuation_document_id": document["id"],
                        "movement_line_id": line["id"],
                        "line_number": line["line_number"],
                        "flow_direction": flow,
                        "item_id": line["item_id"],
                        "uom_id": line["uom_id"],
                        "inventory_lot_id": line["inventory_lot_id"],
                        "quantity_scaled": quantity_scaled,
                        "quantity_precision": line["quantity_precision"],
                        "value_minor": value_minor,
                        "inventory_account_id": line["inventory_account_id"],
                        "offset_account_id": offset_account_id,
                        "created_at": now,
                    }
                    self.repository.insert_valuation_line(valuation_line)
                    if flow == "Inbound":
                        self.repository.insert_cost_layer(
                            {
                                "id": platform_id("IVR", valuation_line_id),
                                "source_valuation_line_id": valuation_line_id,
                                "legal_entity_id": document["legal_entity_id"],
                                "item_id": line["item_id"],
                                "uom_id": line["uom_id"],
                                "inventory_lot_id": line["inventory_lot_id"],
                                "quantity_precision": line["quantity_precision"],
                                "original_quantity_scaled": quantity_scaled,
                                "remaining_quantity_scaled": quantity_scaled,
                                "original_value_minor": value_minor,
                                "remaining_value_minor": value_minor,
                                "currency_code": document["currency_code"],
                                "created_at": now,
                            }
                        )
                    else:
                        for allocation in allocations:
                            consumption_id = platform_id(
                                "IVX", valuation_line_id, allocation["layer_id"]
                            )
                            self.repository.insert_layer_consumption(
                                {
                                    "id": consumption_id,
                                    "valuation_line_id": valuation_line_id,
                                    "cost_layer_id": allocation["layer_id"],
                                    "quantity_scaled": allocation["quantity_scaled"],
                                    "value_minor": allocation["value_minor"],
                                    "created_at": now,
                                }
                            )
                            if self.repository.update_cost_layer(
                                str(allocation["layer_id"]),
                                int(allocation["remaining_quantity_scaled"]),
                                int(allocation["remaining_value_minor"]),
                            ) != 1:
                                raise PlatformError("FIFO cost layer changed concurrently; reload and retry.")
                    inventory_account_id = str(line["inventory_account_id"])
                    description = f"{document['valuation_number']} line {line['line_number']}"
                    if flow == "Inbound":
                        journal_postings.extend(
                            (
                                (inventory_account_id, value_minor, 0, description),
                                (offset_account_id, 0, value_minor, description),
                            )
                        )
                    else:
                        journal_postings.extend(
                            (
                                (offset_account_id, value_minor, 0, description),
                                (inventory_account_id, 0, value_minor, description),
                            )
                        )
                finance_entry_id = self._insert_finance_draft(
                    document=document,
                    policy=policy,
                    movement=movement,
                    postings=journal_postings,
                    created_at=now,
                )
                if self.repository.approve_document(
                    str(document["id"]),
                    actor=actor,
                    timestamp=now,
                    reason=approval_reason,
                    total_value_minor=total_value_minor,
                    finance_entry_id=finance_entry_id,
                ) != 1:
                    raise PlatformError("Inventory valuation changed concurrently; reload and retry.")
        except PlatformError:
            raise
        except sqlite3.IntegrityError as exc:
            raise PlatformError("Unable to approve valuation because a protected local record conflicts.") from exc
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to approve the local inventory valuation.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_valuation_document",
            object_id=document_id,
            action="inventory_valuation_approved",
            metadata={
                "valuation_number": document_number_value,
                "total_value_minor": total_value_minor,
                "finance_entry_id": finance_entry_id,
                "finance_entry_status": "Draft",
            },
        )
        return self.get_document(document_id, actor_label=actor_label)

    def cancel_document(
        self,
        document_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Cancel an unapproved valuation Draft while preserving its evidence."""

        require_permission(self.connection, actor_label=actor_label, permission=VALUATION_MANAGE_PERMISSION)
        cancel_reason = clean_text(reason, "Cancellation reason", maximum=500)
        actor = clean_text(actor_label, "Actor label")
        now = utc_now_text()
        try:
            with self.repository.transaction():
                document = self._required(
                    self.repository.document(clean_text(document_id, "Valuation document ID")),
                    "Inventory valuation document not found.",
                )
                if str(document["status"]) != "Draft":
                    raise PlatformError("Only Draft inventory valuations can be cancelled.")
                if self.repository.cancel_document(
                    str(document["id"]), actor=actor, timestamp=now, reason=cancel_reason
                ) != 1:
                    raise PlatformError("Inventory valuation changed concurrently; reload and retry.")
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to cancel the local inventory valuation.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="inventory_valuation_document",
            object_id=document_id,
            action="inventory_valuation_cancelled",
            metadata={"reason": cancel_reason},
        )
        return self.get_document(document_id, actor_label=actor_label)

    def get_policy(self, policy_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        policy = self._required(
            self.repository.policy(clean_text(policy_id, "Valuation policy ID")),
            "Inventory valuation policy not found.",
        )
        return self._public_policy(policy)

    def list_policies(
        self,
        *,
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = page(limit, offset)
        workspace_record = self.repository.workspace_by_name(clean_text(workspace, "Workspace name"))
        if workspace_record is None:
            return []
        try:
            records = self.repository.list_policies(
                str(workspace_record["id"]), limit=page_limit, offset=page_offset
            )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local valuation policies.") from exc
        return [self._public_policy(record) for record in records]

    def get_document(self, document_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        try:
            document = self._required(
                self.repository.document(clean_text(document_id, "Valuation document ID")),
                "Inventory valuation document not found.",
            )
            return self._public_document(document, include_details=True)
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local inventory valuation.") from exc

    def list_documents(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        selected_status = choice(status, "Valuation status", VALUATION_STATUSES) if status else ""
        page_limit, page_offset = page(limit, offset)
        workspace_record = self.repository.workspace_by_name(clean_text(workspace, "Workspace name"))
        if workspace_record is None:
            return []
        try:
            rows = self.repository.list_documents(
                str(workspace_record["id"]), status=selected_status, limit=page_limit, offset=page_offset
            )
            return [self._public_document(record, include_details=False) for record in rows]
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local inventory valuations.") from exc

    def list_cost_layers(
        self,
        *,
        workspace: str = "default",
        open_only: bool = False,
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = page(limit, offset)
        workspace_record = self.repository.workspace_by_name(clean_text(workspace, "Workspace name"))
        if workspace_record is None:
            return []
        try:
            rows = self.repository.list_cost_layers(
                str(workspace_record["id"]), open_only=open_only, limit=page_limit, offset=page_offset
            )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local FIFO cost layers.") from exc
        return [self._public_layer(row) for row in rows]

    def summary(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> InventoryValuationSummary:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        workspace_name = clean_text(workspace, "Workspace name")
        workspace_record = self.repository.workspace_by_name(workspace_name)
        try:
            counts = (
                self.repository.summary_counts(str(workspace_record["id"])) if workspace_record else {}
            )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to summarize local inventory valuations.") from exc
        return InventoryValuationSummary(
            workspace=workspace_name,
            policies=counts.get("policies", 0),
            draft_documents=counts.get("draft_documents", 0),
            approved_documents=counts.get("approved_documents", 0),
            open_layers=counts.get("open_layers", 0),
            unvalued_posted_movements=counts.get("unvalued_posted_movements", 0),
        )

    def snapshot(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        """Return a bounded, path-free valuation control snapshot."""

        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {
                "kind": "local-inventory-valuation",
                "local_first": True,
                "external_calls": False,
            },
            "workspace": clean_text(workspace, "Workspace name"),
            "summary": self.summary(workspace=workspace, actor_label=actor_label).to_dict(),
            "policies": self.list_policies(workspace=workspace, actor_label=actor_label),
            "documents": self.list_documents(workspace=workspace, actor_label=actor_label),
            "open_cost_layers": self.list_cost_layers(
                workspace=workspace, open_only=True, actor_label=actor_label
            ),
            "boundary_note": (
                "FIFO foundation only. Approval creates a balanced local Finance Core Draft; "
                "it does not validate that entry or write to a source ERP."
            ),
        }

    def _posting_account(self, chart_id: str, raw_code: str, label: str) -> str:
        account = self._required(
            self.repository.account(chart_id, code(raw_code, label)),
            f"{label} was not found in the journal chart.",
        )
        if not bool(account["active"]) or not bool(account["allow_posting"]):
            raise PlatformError(f"{label} must be active and posting-enabled.")
        return str(account["id"])

    def _validate_policy_state(
        self, policy: Mapping[str, object], movement: Mapping[str, object]
    ) -> None:
        if not bool(policy["active"]) or not bool(policy["journal_active"]):
            raise PlatformError("Inventory valuation requires an active policy and Finance Core journal.")
        if str(policy["costing_method"]) != "FIFO":
            raise PlatformError("This version supports FIFO valuation only.")
        if str(policy["currency_code"]) != str(movement["entity_currency"]):
            raise PlatformError("Valuation policy and legal-entity currencies must match.")
        if str(policy["journal_currency_code"]) != str(policy["currency_code"]):
            raise PlatformError("Valuation policy and Finance Core journal currencies must match.")
        account_flags = (
            ("receipt_account_active", "receipt_account_allow_posting"),
            ("cogs_account_active", "cogs_account_allow_posting"),
            ("adjustment_account_active", "adjustment_account_allow_posting"),
        )
        if any(not bool(policy[active]) or not bool(policy[posting]) for active, posting in account_flags):
            raise PlatformError("Valuation offset accounts must remain active and posting-enabled.")

    @staticmethod
    def _validate_inventory_line_account(
        line: Mapping[str, object], policy: Mapping[str, object]
    ) -> None:
        if str(line["item_type"]) == "Service":
            raise PlatformError("Service items cannot participate in inventory valuation.")
        if not line.get("inventory_account_id"):
            raise PlatformError(f"Item {line['item_code']} requires an inventory account before valuation.")
        if not bool(line["inventory_account_active"]) or not bool(line["inventory_account_allow_posting"]):
            raise PlatformError(f"Item {line['item_code']} requires an active posting-enabled inventory account.")
        if str(line["inventory_account_chart_id"]) != str(policy["chart_id"]):
            raise PlatformError(f"Item {line['item_code']} inventory account must use the valuation journal chart.")

    def _prepare_input_costs(
        self,
        input_costs: Sequence[Mapping[str, object]],
        *,
        movement_type: str,
        movement_lines: Sequence[Mapping[str, object]],
        minor_units: int,
    ) -> dict[str, int]:
        lines_by_number = {self._as_int(line["line_number"]): line for line in movement_lines}
        inbound_numbers = {
            number
            for number, line in lines_by_number.items()
            if self._line_flow(movement_type, line) == "Inbound"
        }
        prepared: dict[str, int] = {}
        seen_numbers: set[int] = set()
        for value in input_costs:
            if not isinstance(value, Mapping):
                raise PlatformError("Each valuation input cost must be an object.")
            raw_number = value.get("line_number")
            if isinstance(raw_number, bool):
                raise PlatformError("Input cost line number must be a positive integer.")
            try:
                line_number = int(str(raw_number))
            except (TypeError, ValueError) as exc:
                raise PlatformError("Input cost line number must be a positive integer.") from exc
            if line_number not in lines_by_number or line_number in seen_numbers:
                raise PlatformError("Input cost line numbers must be unique movement line numbers.")
            if line_number not in inbound_numbers:
                raise PlatformError("Input costs are accepted only for inbound movement lines.")
            total_minor = amount_to_minor(value.get("total_cost"), minor_units, "Input total cost")
            if total_minor <= 0:
                raise PlatformError("Input total cost must be greater than zero.")
            seen_numbers.add(line_number)
            prepared[str(lines_by_number[line_number]["id"])] = total_minor
        if seen_numbers != inbound_numbers:
            raise PlatformError("Every inbound movement line requires exactly one input total cost.")
        return prepared

    @staticmethod
    def _line_flow(movement_type: str, line: Mapping[str, object]) -> str:
        if movement_type == "Receipt":
            return "Inbound"
        if movement_type == "Delivery":
            return "Outbound"
        if movement_type == "Adjustment":
            return "Inbound" if line.get("to_location_id") is not None else "Outbound"
        raise PlatformError("Transfers do not require valuation documents.")

    @staticmethod
    def _offset_account_id(movement_type: str, policy: Mapping[str, object]) -> str:
        if movement_type == "Receipt":
            return str(policy["receipt_clearing_account_id"])
        if movement_type == "Delivery":
            return str(policy["cogs_account_id"])
        return str(policy["adjustment_account_id"])

    def _fifo_allocations(
        self, *, legal_entity_id: str, line: Mapping[str, object]
    ) -> list[dict[str, int | str]]:
        needed = self._as_int(line["quantity_scaled"])
        precision = self._as_int(line["quantity_precision"])
        allocations: list[dict[str, int | str]] = []
        layers = self.repository.open_cost_layers(
            legal_entity_id, str(line["item_id"]), self._optional_text(line.get("inventory_lot_id"))
        )
        for layer in layers:
            if self._as_int(layer["quantity_precision"]) != precision or str(layer["uom_id"]) != str(line["uom_id"]):
                raise PlatformError("FIFO layer unit precision does not match the outbound movement line.")
            if needed <= 0:
                break
            remaining_quantity = self._as_int(layer["remaining_quantity_scaled"])
            remaining_value = self._as_int(layer["remaining_value_minor"])
            take = min(needed, remaining_quantity)
            value = self._allocate_layer_value(
                remaining_value=remaining_value,
                remaining_quantity=remaining_quantity,
                consumed_quantity=take,
            )
            allocations.append(
                {
                    "layer_id": str(layer["id"]),
                    "quantity_scaled": take,
                    "value_minor": value,
                    "remaining_quantity_scaled": remaining_quantity - take,
                    "remaining_value_minor": remaining_value - value,
                }
            )
            needed -= take
        if needed:
            available = self._as_int(line["quantity_scaled"]) - needed
            raise PlatformError(
                "Insufficient Approved FIFO quantity for outbound line "
                f"{line['line_number']}: required {scaled_to_text(self._as_int(line['quantity_scaled']), precision)}, "
                f"available {scaled_to_text(available, precision)}."
            )
        return allocations

    @staticmethod
    def _allocate_layer_value(
        *, remaining_value: int, remaining_quantity: int, consumed_quantity: int
    ) -> int:
        if consumed_quantity == remaining_quantity:
            return remaining_value
        exact = (Decimal(remaining_value) * Decimal(consumed_quantity)) / Decimal(remaining_quantity)
        allocated = int(exact.to_integral_value(rounding=ROUND_HALF_EVEN))
        if allocated <= 0 or allocated >= remaining_value:
            raise PlatformError(
                "A partial FIFO issue cannot be represented exactly enough in currency minor units; "
                "consume the layer fully or use a more granular receipt quantity."
            )
        return allocated

    def _insert_finance_draft(
        self,
        *,
        document: Mapping[str, object],
        policy: Mapping[str, object],
        movement: Mapping[str, object],
        postings: Sequence[tuple[str, int, int, str]],
        created_at: str,
    ) -> str:
        grouped: dict[tuple[str, str], int] = defaultdict(int)
        for account_id, debit_minor, credit_minor, _description in postings:
            if debit_minor:
                grouped[(account_id, "debit")] += debit_minor
            if credit_minor:
                grouped[(account_id, "credit")] += credit_minor
        total_debit = sum(value for (_account, side), value in grouped.items() if side == "debit")
        total_credit = sum(value for (_account, side), value in grouped.items() if side == "credit")
        if total_debit <= 0 or total_debit != total_credit:
            raise PlatformError("Generated Inventory-to-Finance postings must balance to a positive amount.")
        valuation_number = str(document["valuation_number"])
        entry_number = f"IV-{valuation_number}"
        if len(entry_number) > 64:
            digest = sha256(str(document["id"]).encode("utf-8")).hexdigest()[:16].upper()
            entry_number = f"IV-{digest}"
        existing = self.repository.finance_entry_by_number(str(document["workspace_id"]), entry_number)
        if existing is not None:
            raise PlatformError("Generated Finance Core entry number already exists.")
        entry_id = platform_id("GLE", document["workspace_id"], entry_number)
        entry: dict[str, object] = {
            "id": entry_id,
            "workspace_id": document["workspace_id"],
            "organization_id": document["organization_id"],
            "chart_id": policy["chart_id"],
            "legal_entity_id": document["legal_entity_id"],
            "period_id": document["period_id"],
            "finance_journal_id": policy["finance_journal_id"],
            "entry_number": entry_number,
            "posting_date": movement["movement_date"],
            "currency_code": document["currency_code"],
            "description": f"FIFO inventory valuation {valuation_number}",
            "external_reference": f"Inventory movement {movement['movement_number']}",
            "created_by": document["created_by"],
            "created_at": created_at,
            "updated_at": created_at,
        }
        ledger_lines: list[dict[str, object]] = []
        ordered = sorted(grouped.items(), key=lambda item: (item[0][1] != "debit", item[0][0]))
        for line_number, ((account_id, side), value) in enumerate(ordered, start=1):
            ledger_lines.append(
                {
                    "id": platform_id("GLL", entry_id, line_number),
                    "entry_id": entry_id,
                    "line_number": line_number,
                    "account_id": account_id,
                    "description": f"FIFO valuation {valuation_number}",
                    "debit_minor": value if side == "debit" else 0,
                    "credit_minor": value if side == "credit" else 0,
                    "created_at": created_at,
                }
            )
        self.repository.insert_finance_draft(entry, ledger_lines)
        return entry_id

    def _public_policy(self, policy: Mapping[str, object]) -> dict[str, Any]:
        result = dict(policy)
        result["active"] = bool(result["active"])
        for field in (
            "chart_id",
            "journal_active",
            "journal_currency_code",
            "receipt_account_active",
            "receipt_account_allow_posting",
            "cogs_account_active",
            "cogs_account_allow_posting",
            "adjustment_account_active",
            "adjustment_account_allow_posting",
        ):
            result.pop(field, None)
        return result

    def _public_document(
        self, document: Mapping[str, object], *, include_details: bool
    ) -> dict[str, Any]:
        result: dict[str, Any] = dict(document)
        currency = self._required(
            self.repository.currency(str(document["currency_code"])),
            "Valuation currency is unavailable.",
        )
        minor_units = int(currency["minor_units"])
        result["total_value"] = minor_to_text(self._as_int(result.pop("total_value_minor")), minor_units)
        if not include_details:
            return result
        input_costs = self.repository.input_costs(str(document["id"]))
        result["input_costs"] = [
            {
                **record,
                "total_cost": minor_to_text(self._as_int(record["total_cost_minor"]), minor_units),
            }
            for record in input_costs
        ]
        for record in result["input_costs"]:
            record.pop("total_cost_minor", None)
        lines = self.repository.valuation_lines(str(document["id"]))
        result["lines"] = []
        for line in lines:
            line_result = dict(line)
            line_result["quantity"] = scaled_to_text(
                self._as_int(line_result.pop("quantity_scaled")), self._as_int(line_result["quantity_precision"])
            )
            line_result["value"] = minor_to_text(self._as_int(line_result.pop("value_minor")), minor_units)
            result["lines"].append(line_result)
        consumptions = self.repository.layer_consumptions(str(document["id"]))
        result["layer_consumptions"] = []
        precision_by_line = {
            self._as_int(line["line_number"]): self._as_int(line["quantity_precision"])
            for line in lines
        }
        for consumption in consumptions:
            consumption_result = dict(consumption)
            precision = precision_by_line[self._as_int(consumption_result["line_number"])]
            consumption_result["quantity"] = scaled_to_text(
                self._as_int(consumption_result.pop("quantity_scaled")), precision
            )
            consumption_result["value"] = minor_to_text(
                self._as_int(consumption_result.pop("value_minor")), minor_units
            )
            result["layer_consumptions"].append(consumption_result)
        return result

    def _public_layer(self, layer: Mapping[str, object]) -> dict[str, Any]:
        result: dict[str, Any] = dict(layer)
        currency = self._required(
            self.repository.currency(str(layer["currency_code"])),
            "Valuation currency is unavailable.",
        )
        precision = self._as_int(result["quantity_precision"])
        minor_units = int(currency["minor_units"])
        result["original_quantity"] = scaled_to_text(
            self._as_int(result.pop("original_quantity_scaled")), precision
        )
        result["remaining_quantity"] = scaled_to_text(
            self._as_int(result.pop("remaining_quantity_scaled")), precision
        )
        result["original_value"] = minor_to_text(
            self._as_int(result.pop("original_value_minor")), minor_units
        )
        result["remaining_value"] = minor_to_text(
            self._as_int(result.pop("remaining_value_minor")), minor_units
        )
        result["layer_status"] = "Open" if result["remaining_quantity"] != scaled_to_text(0, precision) else "Closed"
        return result

    @staticmethod
    def _required(value: dict[str, Any] | None, message: str) -> dict[str, Any]:
        if value is None:
            raise PlatformError(message)
        return value

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return str(value) if value is not None and str(value) else None

    @staticmethod
    def _as_int(value: object) -> int:
        return int(str(value))
