"""SQLite adapter for governed inventory counts and reorder signals."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date
from typing import Any

from reconforge.application.inventory_planning import InventoryPlanningSummary
from reconforge.auth.rbac import same_actor
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.sqlite_inventory_planning_repository import (
    InventoryPlanningRepository,
    SQLiteInventoryPlanningRepository,
)
from reconforge.platform.common import (
    PlatformError,
    append_outbox_event,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)
from reconforge.platform.inventory_values import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    choice,
    clean_text,
    code,
    document_number,
    iso_date,
    page,
    quantity_to_scaled,
    scaled_to_text,
)

INVENTORY_READ_PERMISSION = "inventory.read"
COUNT_MANAGE_PERMISSION = "inventory.count.manage"
COUNT_APPROVE_PERMISSION = "inventory.count.approve"
REORDER_MANAGE_PERMISSION = "inventory.reorder.manage"
COUNT_STATUSES = ("Draft", "Counting", "Submitted", "Approved", "Cancelled")
MAX_COUNT_LINES = 100_000


class SQLiteInventoryPlanningRepositoryAdapter:
    """Coordinate count and reorder use cases without purchasing or ERP writeback."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        repository: InventoryPlanningRepository | None = None,
    ) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self.repository = repository or SQLiteInventoryPlanningRepository(connection)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        expected = {"inventory_count_sessions", "inventory_count_lines", "inventory_reorder_rules"}
        try:
            existing = {
                str(row["name"])
                for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to inspect the local inventory planning schema.") from exc
        if not existing >= expected:
            raise PlatformError("Inventory planning schema is unavailable. Run 'reconforge db migrate' first.")

    def summary(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> InventoryPlanningSummary:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        workspace_name = clean_text(workspace, "Workspace name")
        try:
            workspace_record = self.repository.workspace_by_name(workspace_name)
            counts = self.repository.summary_counts(str(workspace_record["id"])) if workspace_record else {}
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to summarize local inventory planning records.") from exc
        return InventoryPlanningSummary(
            workspace=workspace_name,
            count_sessions=counts.get("count_sessions", 0),
            counting_sessions=counts.get("counting_sessions", 0),
            submitted_sessions=counts.get("submitted_sessions", 0),
            approved_sessions=counts.get("approved_sessions", 0),
            reorder_rules=counts.get("reorder_rules", 0),
            active_reorder_rules=counts.get("active_reorder_rules", 0),
        )

    def create_count_session(
        self,
        *,
        count_number: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        warehouse_code: str,
        location_code: str,
        count_date: str,
        description: str = "Inventory count",
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=COUNT_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, clean_text(workspace, "Workspace name"))
        number = document_number(count_number, "Count number")
        if len(number) > 60:
            raise PlatformError("Count number must not exceed 60 characters.")
        actor = clean_text(actor_label or "local-cli", "Actor label")
        counted_on = self._required_date(count_date, "Count date")
        organization, entity, period, location = self._scoped_references(
            workspace_id,
            organization_code=organization_code,
            entity_code=entity_code,
            period_id=period_id,
            warehouse_code=warehouse_code,
            location_code=location_code,
        )
        self._require_open_period_date(period, counted_on)
        session_id = platform_id("ICNT", workspace_id, number)
        now = utc_now_text()
        record: dict[str, object] = {
            "id": session_id,
            "workspace_id": workspace_id,
            "organization_id": organization["id"],
            "legal_entity_id": entity["id"],
            "period_id": period["id"],
            "location_id": location["id"],
            "count_number": number,
            "count_date": counted_on.isoformat(),
            "description": clean_text(description, "Count description", maximum=500),
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.repository.transaction():
                self.repository.insert_count_session(record)
                _finalize_planning_event(
                    self.connection,
                    event_type="inventory.count.created",
                    aggregate_type="inventory_count_session",
                    aggregate_id=session_id,
                    payload={
                        "count_number": number,
                        "warehouse_code": location["warehouse_code"],
                        "location_code": location_code,
                    },
                    actor_label=actor_label,
                    action="inventory_count_created",
                    metadata={
                        "count_number": number,
                        "warehouse_code": location["warehouse_code"],
                        "location_code": location_code,
                    },
                )
        except sqlite3.IntegrityError as exc:
            raise PlatformError("Inventory count number already exists or references invalid local data.") from exc
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to create the local inventory count session.") from exc
        return self.get_count_session(session_id, actor_label=actor_label)

    def start_count_session(
        self,
        session_id: str,
        *,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=COUNT_MANAGE_PERMISSION)
        actor = clean_text(actor_label or "local-cli", "Actor label")
        now = utc_now_text()
        line_count = 0
        try:
            with self.repository.transaction():
                session = self._session(session_id)
                if session["status"] != "Draft":
                    raise PlatformError("Only Draft inventory count sessions can be started.")
                balances = self.repository.location_balances(str(session["location_id"]))
                if not balances:
                    raise PlatformError("The selected location has no non-zero Posted local balances to count.")
                if len(balances) > MAX_COUNT_LINES:
                    raise PlatformError(f"Inventory counts cannot exceed {MAX_COUNT_LINES} snapshot lines.")
                lines = [
                    {
                        "id": platform_id("ICNL", session_id, line_number),
                        "session_id": session_id,
                        "line_number": line_number,
                        "item_id": balance["item_id"],
                        "uom_id": balance["uom_id"],
                        "inventory_lot_id": balance["inventory_lot_id"],
                        "expected_quantity_scaled": int(balance["expected_quantity_scaled"]),
                        "quantity_precision": int(balance["quantity_precision"]),
                        "created_at": now,
                    }
                    for line_number, balance in enumerate(balances, start=1)
                ]
                self.repository.insert_count_lines(lines)
                if self.repository.start_count(session_id, actor, now) != 1:
                    raise PlatformError("Inventory count changed concurrently; reload and retry.")
                line_count = len(lines)
                _finalize_planning_event(
                    self.connection,
                    event_type="inventory.count.started",
                    aggregate_type="inventory_count_session",
                    aggregate_id=session_id,
                    payload={"snapshot_lines": line_count},
                    actor_label=actor_label,
                    action="inventory_count_started",
                    metadata={"snapshot_lines": line_count},
                )
        except PlatformError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to start the local inventory count session.") from exc
        return self.get_count_session(session_id, actor_label=actor_label)

    def record_counted_quantity(
        self,
        session_id: str,
        line_id: str,
        *,
        counted_quantity: object,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=COUNT_MANAGE_PERMISSION)
        actor = clean_text(actor_label or "local-cli", "Actor label")
        try:
            line = self.repository.count_line(session_id, line_id)
            if line is None:
                raise PlatformError("Inventory count line was not found.")
            if line["status"] != "Counting":
                raise PlatformError("Counted quantities can be recorded only while the session is Counting.")
            scaled = quantity_to_scaled(
                counted_quantity,
                int(line["quantity_precision"]),
                "Counted quantity",
                allow_zero=True,
            )
            now = utc_now_text()
            with self.repository.transaction():
                current = self.repository.count_line(session_id, line_id)
                if current is None or current["status"] != "Counting":
                    raise PlatformError("Inventory count changed concurrently; reload and retry.")
                if (
                    self.repository.record_count(
                        line_id,
                        scaled,
                        clean_text(note, "Count note", maximum=500, required=False),
                        actor,
                        now,
                    )
                    != 1
                ):
                    raise PlatformError("Inventory count line changed concurrently; reload and retry.")
                _finalize_planning_event(
                    self.connection,
                    event_type="inventory.count.quantity_recorded",
                    aggregate_type="inventory_count_line",
                    aggregate_id=line_id,
                    payload={"session_id": session_id, "item_code": line["item_code"]},
                    actor_label=actor_label,
                    action="inventory_count_quantity_recorded",
                    metadata={"session_id": session_id, "item_code": line["item_code"]},
                )
        except PlatformError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to record the local counted quantity.") from exc
        return self.get_count_session(session_id, actor_label=actor_label)

    def submit_count_session(
        self,
        session_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=COUNT_MANAGE_PERMISSION)
        actor = clean_text(actor_label or "local-cli", "Actor label")
        submit_reason = clean_text(reason, "Submission reason", maximum=500)
        now = utc_now_text()
        try:
            with self.repository.transaction():
                session = self._session(session_id)
                if session["status"] != "Counting":
                    raise PlatformError("Only Counting inventory sessions can be submitted.")
                lines = self.repository.count_lines(session_id)
                if not lines or any(line["counted_quantity_scaled"] is None for line in lines):
                    raise PlatformError("Every inventory count line requires a counted quantity before submission.")
                if self.repository.submit_count(session_id, actor, now, submit_reason) != 1:
                    raise PlatformError("Inventory count changed concurrently; reload and retry.")
                _finalize_planning_event(
                    self.connection,
                    event_type="inventory.count.submitted",
                    aggregate_type="inventory_count_session",
                    aggregate_id=session_id,
                    payload={"reason": submit_reason},
                    actor_label=actor_label,
                    action="inventory_count_submitted",
                    metadata={"reason": submit_reason},
                )
        except PlatformError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to submit the local inventory count session.") from exc
        return self.get_count_session(session_id, actor_label=actor_label)

    def approve_count_session(
        self,
        session_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(
            self.connection,
            actor_label=actor_label,
            permission=COUNT_APPROVE_PERMISSION,
        )
        actor = clean_text(actor_label or "local-cli", "Actor label")
        approval_reason = clean_text(reason, "Approval reason", maximum=500)
        now = utc_now_text()
        adjustment_id: str | None = None
        adjustment_number = ""
        variance_count = 0
        try:
            with self.repository.transaction():
                session = self._session(session_id)
                if session["status"] != "Submitted":
                    raise PlatformError("Only Submitted inventory count sessions can be approved.")
                if same_actor(session["created_by"], actor) or same_actor(session["submitted_by"], actor):
                    raise PlatformError("Segregation of duties prevents approving a count you created or submitted.")
                period = self._period(str(session["workspace_id"]), str(session["period_id"]))
                counted_on = self._required_date(session["count_date"], "Stored count date")
                self._require_open_period_date(period, counted_on)
                count_lines = self.repository.count_lines(session_id)
                if not count_lines or any(line["counted_quantity_scaled"] is None for line in count_lines):
                    raise PlatformError("Submitted inventory count lines are incomplete.")
                expected_balances = {
                    (str(line["item_id"]), str(line["inventory_lot_id"] or "")): int(line["expected_quantity_scaled"])
                    for line in count_lines
                }
                current_balances = {
                    (str(line["item_id"]), str(line["inventory_lot_id"] or "")): int(line["expected_quantity_scaled"])
                    for line in self.repository.location_balances(str(session["location_id"]))
                }
                if current_balances != expected_balances:
                    raise PlatformError(
                        "Posted inventory changed after this count started; cancel it and start a fresh snapshot."
                    )
                adjustment_lines: list[dict[str, object]] = []
                for source in count_lines:
                    variance = int(source["counted_quantity_scaled"]) - int(source["expected_quantity_scaled"])
                    if variance == 0:
                        continue
                    variance_count += 1
                    adjustment_lines.append(
                        {
                            "item_id": source["item_id"],
                            "uom_id": source["uom_id"],
                            "inventory_lot_id": source["inventory_lot_id"],
                            "from_location_id": session["location_id"] if variance < 0 else None,
                            "to_location_id": session["location_id"] if variance > 0 else None,
                            "quantity_scaled": abs(variance),
                            "quantity_precision": source["quantity_precision"],
                        }
                    )
                if adjustment_lines:
                    adjustment_number = f"ADJ/{session['count_number']}"
                    if self.repository.movement_number_exists(str(session["workspace_id"]), adjustment_number):
                        raise PlatformError("The generated count-adjustment movement number already exists.")
                    adjustment_id = platform_id("MOV", session["workspace_id"], adjustment_number)
                    movement: dict[str, object] = {
                        "id": adjustment_id,
                        "workspace_id": session["workspace_id"],
                        "organization_id": session["organization_id"],
                        "legal_entity_id": session["legal_entity_id"],
                        "period_id": session["period_id"],
                        "movement_number": adjustment_number,
                        "movement_date": counted_on.isoformat(),
                        "source_reference": session_id,
                        "description": f"Draft adjustment generated from approved count {session['count_number']}",
                        "created_by": "inventory-count-service",
                        "created_at": now,
                        "updated_at": now,
                    }
                    prepared_lines = [
                        {
                            **line,
                            "id": platform_id("MOVL", adjustment_id, line_number),
                            "movement_id": adjustment_id,
                            "line_number": line_number,
                            "description": f"Count variance from {session['count_number']}",
                            "created_at": now,
                        }
                        for line_number, line in enumerate(adjustment_lines, start=1)
                    ]
                    self.repository.insert_adjustment(movement, prepared_lines)
                if (
                    self.repository.approve_count(
                        session_id,
                        actor,
                        now,
                        approval_reason,
                        adjustment_id,
                    )
                    != 1
                ):
                    raise PlatformError("Inventory count changed concurrently; reload and retry.")
                _finalize_planning_event(
                    self.connection,
                    event_type="inventory.count.approved",
                    aggregate_type="inventory_count_session",
                    aggregate_id=session_id,
                    payload={
                        "reason": approval_reason,
                        "variance_lines": variance_count,
                        "adjustment_movement_id": adjustment_id,
                    },
                    actor_label=actor_label,
                    action="inventory_count_approved",
                    metadata={
                        "reason": approval_reason,
                        "variance_lines": variance_count,
                        "adjustment_movement_id": adjustment_id,
                    },
                )
                if adjustment_id is not None:
                    _finalize_planning_event(
                        self.connection,
                        event_type="inventory.count.adjustment_draft_created",
                        aggregate_type="inventory_movement",
                        aggregate_id=adjustment_id,
                        payload={"movement_number": adjustment_number, "count_session_id": session_id},
                        actor_label=actor_label,
                        action="inventory_count_adjustment_draft_created",
                        metadata={"movement_number": adjustment_number, "count_session_id": session_id},
                    )
        except PlatformError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to approve the local inventory count session.") from exc
        return self.get_count_session(session_id, actor_label=actor_label)

    def cancel_count_session(
        self,
        session_id: str,
        *,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        try:
            session = self._session(session_id)
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local inventory count session.") from exc
        permission = COUNT_APPROVE_PERMISSION if session["status"] == "Submitted" else COUNT_MANAGE_PERMISSION
        require_permission(self.connection, actor_label=actor_label, permission=permission)
        if session["status"] not in {"Draft", "Counting", "Submitted"}:
            raise PlatformError("Only Draft, Counting, or Submitted inventory counts can be cancelled.")
        actor = clean_text(actor_label or "local-cli", "Actor label")
        cancel_reason = clean_text(reason, "Cancellation reason", maximum=500)
        now = utc_now_text()
        try:
            with self.repository.transaction():
                current = self._session(session_id)
                if current["status"] not in {"Draft", "Counting", "Submitted"}:
                    raise PlatformError("Inventory count changed concurrently; reload and retry.")
                if self.repository.cancel_count(session_id, actor, now, cancel_reason) != 1:
                    raise PlatformError("Inventory count changed concurrently; reload and retry.")
                _finalize_planning_event(
                    self.connection,
                    event_type="inventory.count.cancelled",
                    aggregate_type="inventory_count_session",
                    aggregate_id=session_id,
                    payload={"reason": cancel_reason},
                    actor_label=actor_label,
                    action="inventory_count_cancelled",
                    metadata={"reason": cancel_reason},
                )
        except PlatformError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to cancel the local inventory count session.") from exc
        return self.get_count_session(session_id, actor_label=actor_label)

    def get_count_session(
        self,
        session_id: str,
        *,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        try:
            session = self._session(session_id)
            lines = self.repository.count_lines(session_id)
        except PlatformError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read the local inventory count session.") from exc
        public_lines = [self._public_count_line(line) for line in lines]
        session["lines"] = public_lines
        session["summary"] = {
            "lines": len(public_lines),
            "counted_lines": sum(line["counted_quantity"] is not None for line in public_lines),
            "variance_lines": sum(line["variance_quantity_scaled"] not in {None, 0} for line in public_lines),
        }
        return self._public_session(session)

    def list_count_sessions(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = page(limit, offset)
        selected_status = choice(status, "Count status", COUNT_STATUSES) if status else ""
        workspace_name = clean_text(workspace, "Workspace name")
        try:
            workspace_record = self.repository.workspace_by_name(workspace_name)
            if workspace_record is None:
                return []
            rows = self.repository.list_count_sessions(
                str(workspace_record["id"]),
                status=selected_status,
                limit=page_limit,
                offset=page_offset,
            )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local inventory count sessions.") from exc
        return [self._public_session(row) for row in rows]

    def upsert_reorder_rule(
        self,
        *,
        organization_code: str,
        entity_code: str,
        item_code: str,
        warehouse_code: str,
        location_code: str,
        minimum_quantity: object,
        target_quantity: object,
        lead_time_days: int = 0,
        active: bool = True,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission=REORDER_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, clean_text(workspace, "Workspace name"))
        organization = self._organization(workspace_id, organization_code)
        entity = self._entity(str(organization["id"]), entity_code)
        location = self._location(
            workspace_id,
            str(organization["id"]),
            str(entity["id"]),
            warehouse_code,
            location_code,
        )
        item = self._item(workspace_id, item_code)
        if item["item_type"] == "Service" or not bool(item["active"]):
            raise PlatformError("Reorder rules require an active stock or consumable item.")
        if item["organization_id"] is not None and str(item["organization_id"]) != str(organization["id"]):
            raise PlatformError("Reorder item belongs to a different organization.")
        if isinstance(lead_time_days, bool) or not 0 <= lead_time_days <= 3650:
            raise PlatformError("Lead time days must be an integer between 0 and 3650.")
        precision = int(item["decimal_places"])
        minimum_scaled = quantity_to_scaled(
            minimum_quantity,
            precision,
            "Minimum quantity",
            allow_zero=True,
        )
        target_scaled = quantity_to_scaled(target_quantity, precision, "Target quantity")
        if target_scaled <= minimum_scaled:
            raise PlatformError("Target quantity must be greater than minimum quantity.")
        rule_id = platform_id("IROR", workspace_id, organization["id"], entity["id"], item["id"], location["id"])
        now = utc_now_text()
        record: dict[str, object] = {
            "id": rule_id,
            "workspace_id": workspace_id,
            "organization_id": organization["id"],
            "legal_entity_id": entity["id"],
            "item_id": item["id"],
            "location_id": location["id"],
            "minimum_quantity_scaled": minimum_scaled,
            "target_quantity_scaled": target_scaled,
            "quantity_precision": precision,
            "lead_time_days": lead_time_days,
            "active": int(active),
            "created_by": clean_text(actor_label or "local-cli", "Actor label"),
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.repository.transaction():
                self.repository.upsert_reorder_rule(record)
                saved = self.repository.reorder_rule(rule_id)
                if saved is None:
                    raise PlatformError("Saved inventory reorder rule could not be reloaded.")
                _finalize_planning_event(
                    self.connection,
                    event_type="inventory.reorder_rule.upserted",
                    aggregate_type="inventory_reorder_rule",
                    aggregate_id=rule_id,
                    payload={
                        "item_code": item["item_code"],
                        "warehouse_code": location["warehouse_code"],
                        "location_code": location["location_code"],
                    },
                    actor_label=actor_label,
                    action="inventory_reorder_rule_upserted",
                    metadata={
                        "item_code": item["item_code"],
                        "warehouse_code": location["warehouse_code"],
                        "location_code": location["location_code"],
                    },
                )
        except PlatformError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save the local inventory reorder rule.") from exc
        return self._public_reorder_rule(saved)

    def list_reorder_rules(
        self,
        *,
        workspace: str = "default",
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = page(limit, offset)
        workspace_name = clean_text(workspace, "Workspace name")
        try:
            workspace_record = self.repository.workspace_by_name(workspace_name)
            if workspace_record is None:
                return []
            rows = self.repository.list_reorder_rules(
                str(workspace_record["id"]),
                active_only=active_only,
                limit=page_limit,
                offset=page_offset,
            )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local inventory reorder rules.") from exc
        return [self._public_reorder_rule(row) for row in rows]

    def reorder_signals(
        self,
        *,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        page_limit, page_offset = page(limit, offset)
        workspace_name = clean_text(workspace, "Workspace name")
        try:
            workspace_record = self.repository.workspace_by_name(workspace_name)
            if workspace_record is None:
                return self._empty_signal_payload(
                    workspace_name,
                    organization_code,
                    entity_code,
                    limit=page_limit,
                    offset=page_offset,
                )
            organization = self._organization(str(workspace_record["id"]), organization_code)
            entity = self._entity(str(organization["id"]), entity_code)
            rows = self.repository.reorder_signal_rows(
                str(workspace_record["id"]),
                str(organization["id"]),
                str(entity["id"]),
                active_only=True,
                limit=MAX_LIST_LIMIT,
                offset=0,
            )
        except PlatformError:
            raise
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to derive local inventory reorder signals.") from exc
        signals: list[dict[str, object]] = []
        for row in rows:
            on_hand_scaled = int(row["on_hand_quantity_scaled"])
            minimum_scaled = int(row["minimum_quantity_scaled"])
            if on_hand_scaled > minimum_scaled:
                continue
            target_scaled = int(row["target_quantity_scaled"])
            precision = int(row["quantity_precision"])
            signals.append(
                {
                    "signal_id": platform_id("IRS", row["id"], on_hand_scaled),
                    "rule_id": row["id"],
                    "risk_rating": "high" if on_hand_scaled < 0 else "medium",
                    "item_code": row["item_code"],
                    "item_name": row["item_name"],
                    "warehouse_code": row["warehouse_code"],
                    "location_code": row["location_code"],
                    "uom_code": row["uom_code"],
                    "quantity_precision": precision,
                    "on_hand_quantity_scaled": on_hand_scaled,
                    "on_hand_quantity": scaled_to_text(on_hand_scaled, precision),
                    "minimum_quantity_scaled": minimum_scaled,
                    "minimum_quantity": scaled_to_text(minimum_scaled, precision),
                    "target_quantity_scaled": target_scaled,
                    "target_quantity": scaled_to_text(target_scaled, precision),
                    "suggested_quantity_scaled": target_scaled - on_hand_scaled,
                    "suggested_quantity": scaled_to_text(target_scaled - on_hand_scaled, precision),
                    "lead_time_days": int(row["lead_time_days"]),
                    "description": "Local on-hand is at or below the configured reorder minimum.",
                }
            )
        severity_order = {"high": 0, "medium": 1}
        signals.sort(
            key=lambda signal: (
                severity_order[str(signal["risk_rating"])],
                str(signal["item_code"]),
                str(signal["signal_id"]),
            )
        )
        total = len(signals)
        selected = signals[page_offset : page_offset + page_limit]
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {"kind": "local-inventory-reorder-controls", "local_first": True, "external_calls": False},
            "workspace": workspace_name,
            "organization_code": organization["organization_code"],
            "entity_code": entity["entity_code"],
            "summary": {
                "total": total,
                "high": sum(signal["risk_rating"] == "high" for signal in signals),
                "medium": sum(signal["risk_rating"] == "medium" for signal in signals),
            },
            "pagination": {"limit": page_limit, "offset": page_offset, "returned": len(selected)},
            "signals": selected,
        }

    def snapshot(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        require_permission(self.connection, actor_label=actor_label, permission=INVENTORY_READ_PERMISSION)
        workspace_name = clean_text(workspace, "Workspace name")
        summary = self.summary(workspace=workspace_name, actor_label=actor_label)
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {"kind": "local-inventory-planning", "local_first": True, "external_calls": False},
            "workspace": workspace_name,
            "summary": summary.to_dict(),
            "count_sessions": self.list_count_sessions(
                workspace=workspace_name,
                limit=MAX_LIST_LIMIT,
                actor_label=actor_label,
            ),
            "reorder_rules": self.list_reorder_rules(
                workspace=workspace_name,
                active_only=False,
                limit=MAX_LIST_LIMIT,
                actor_label=actor_label,
            ),
        }

    def _scoped_references(
        self,
        workspace_id: str,
        *,
        organization_code: str,
        entity_code: str,
        period_id: str,
        warehouse_code: str,
        location_code: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        organization = self._organization(workspace_id, organization_code)
        entity = self._entity(str(organization["id"]), entity_code)
        period = self._period(workspace_id, period_id)
        location = self._location(
            workspace_id,
            str(organization["id"]),
            str(entity["id"]),
            warehouse_code,
            location_code,
        )
        return organization, entity, period, location

    def _organization(self, workspace_id: str, value: object) -> dict[str, Any]:
        record = self.repository.organization(workspace_id, code(value, "Organization code"))
        if record is None:
            raise PlatformError("Organization was not found in this workspace.")
        if not bool(record["active"]):
            raise PlatformError("Inventory planning requires an active organization.")
        return record

    def _entity(self, organization_id: str, value: object) -> dict[str, Any]:
        record = self.repository.entity(organization_id, code(value, "Entity code"))
        if record is None:
            raise PlatformError("Legal entity was not found in this organization.")
        if not bool(record["active"]):
            raise PlatformError("Inventory planning requires an active legal entity.")
        return record

    def _period(self, workspace_id: str, period_id: str) -> dict[str, Any]:
        record = self.repository.period(workspace_id, clean_text(period_id, "Period ID", maximum=160))
        if record is None:
            raise PlatformError("Fiscal period was not found in this workspace.")
        return record

    def _location(
        self,
        workspace_id: str,
        organization_id: str,
        entity_id: str,
        warehouse_code: object,
        location_code: object,
    ) -> dict[str, Any]:
        record = self.repository.location(
            workspace_id,
            organization_id,
            entity_id,
            code(warehouse_code, "Warehouse code"),
            code(location_code, "Location code"),
        )
        if record is None:
            raise PlatformError("Inventory location was not found in the selected entity and warehouse.")
        if not bool(record["warehouse_active"]) or not bool(record["active"]):
            raise PlatformError("Inventory planning requires an active warehouse and location.")
        if record["location_type"] != "Internal":
            raise PlatformError("Inventory counts and reorder rules require an Internal location.")
        return record

    def _item(self, workspace_id: str, value: object) -> dict[str, Any]:
        record = self.repository.item(workspace_id, code(value, "Item code"))
        if record is None:
            raise PlatformError("Inventory item was not found in this workspace.")
        return record

    def _session(self, session_id: str) -> dict[str, Any]:
        record = self.repository.count_session(clean_text(session_id, "Count session ID", maximum=160))
        if record is None:
            raise PlatformError("Inventory count session was not found.")
        return record

    @staticmethod
    def _required_date(value: object, label: str) -> date:
        parsed = iso_date(value, label)
        if parsed is None:
            raise PlatformError(f"{label} is required.")
        return parsed

    @staticmethod
    def _require_open_period_date(period: dict[str, Any], selected_date: date) -> None:
        if period["status"] != "Open":
            raise PlatformError("Inventory planning actions require an Open fiscal period.")
        start = iso_date(period["start_date"], "Stored period start date")
        end = iso_date(period["end_date"], "Stored period end date")
        if start is None or end is None:
            raise PlatformError("Stored fiscal period dates are invalid.")
        if not start <= selected_date <= end:
            raise PlatformError("Inventory planning date must fall inside the selected fiscal period.")

    @staticmethod
    def _public_count_line(line: dict[str, Any]) -> dict[str, Any]:
        precision = int(line["quantity_precision"])
        expected = int(line["expected_quantity_scaled"])
        counted_raw = line["counted_quantity_scaled"]
        counted = int(counted_raw) if counted_raw is not None else None
        public = dict(line)
        public["expected_quantity"] = scaled_to_text(expected, precision)
        public["counted_quantity"] = scaled_to_text(counted, precision) if counted is not None else None
        public["variance_quantity_scaled"] = counted - expected if counted is not None else None
        public["variance_quantity"] = scaled_to_text(counted - expected, precision) if counted is not None else None
        return public

    @staticmethod
    def _public_session(session: dict[str, Any]) -> dict[str, Any]:
        return dict(session)

    @staticmethod
    def _public_reorder_rule(row: dict[str, Any]) -> dict[str, Any]:
        precision = int(row["quantity_precision"])
        public = dict(row)
        public["active"] = bool(row["active"])
        public["minimum_quantity"] = scaled_to_text(int(row["minimum_quantity_scaled"]), precision)
        public["target_quantity"] = scaled_to_text(int(row["target_quantity_scaled"]), precision)
        public["on_hand_quantity"] = scaled_to_text(int(row["on_hand_quantity_scaled"]), precision)
        return public

    @staticmethod
    def _empty_signal_payload(
        workspace: str,
        organization_code: str,
        entity_code: str,
        *,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {"kind": "local-inventory-reorder-controls", "local_first": True, "external_calls": False},
            "workspace": workspace,
            "organization_code": code(organization_code, "Organization code"),
            "entity_code": code(entity_code, "Entity code"),
            "summary": {"total": 0, "high": 0, "medium": 0},
            "pagination": {"limit": limit, "offset": offset, "returned": 0},
            "signals": [],
        }


def _finalize_planning_event(
    connection: sqlite3.Connection,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    actor_label: str,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Commit planning business writes only after outbox and audit evidence exist."""

    try:
        append_outbox_event(
            connection,
            event_id=f"OBX-{uuid.uuid4().hex}",
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        commit_audited(
            connection,
            actor_label=actor_label,
            object_type=aggregate_type,
            object_id=aggregate_id,
            action=action,
            metadata=metadata,
        )
    except (PlatformError, sqlite3.DatabaseError):
        connection.rollback()
        raise
