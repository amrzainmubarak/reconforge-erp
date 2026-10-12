"""One SQLite owner for a reviewed physical receipt, its valuation and sealed GL."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Never, cast
from uuid import uuid4

from reconforge.audit import append_audit_event
from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import PostingActor, digest_payload, text
from reconforge.domain.inventory_receipt_posting import (
    COMMIT_PERMISSIONS,
    PREPARE_PERMISSIONS,
    READ_PERMISSIONS,
    REVIEW_PERMISSIONS,
    InventoryReceiptPostingError,
    ReceiptEffect,
    ReceiptPlan,
    ReceiptPlanView,
    ReceiptPreparation,
    ReceiptReversalPreparation,
    ReceiptReview,
    exact_date,
    exact_int,
    make_effect,
    make_plan,
    make_review,
    source_plan_id,
    verify_effect,
    verify_inverse,
    verify_plan,
    verify_review,
)
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.sqlite_inventory_unit_of_work import SQLiteInventoryUnitOfWork
from reconforge.infrastructure.sqlite_inventory_valuation_repository import SQLiteInventoryValuationRepository
from reconforge.io.inventory_receipt_posting import decode_receipt_json, encode_receipt_json
from reconforge.platform.common import append_outbox_event, current_server_principal
from reconforge.platform.inventory_values import code, movement_number, quantity_to_scaled, scaled_to_text

_SOURCE_TABLES = {
    "inventory_receipt_plans",
    "inventory_receipt_reviews",
    "inventory_receipt_links",
    "inventory_receipt_commands",
}


def _fail(message: str, code: str = "inventory_receipt_evidence_invalid") -> Never:
    raise InventoryReceiptPostingError(code, message)


def _insert(connection: sqlite3.Connection, table: str, values: Mapping[str, Any]) -> None:
    """Only private, module-owned table/column dictionaries reach this writer."""
    columns = ",".join(values)
    markers = ",".join("?" for _ in values)
    connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({markers})", tuple(values.values()))  # nosec B608


class SQLiteInventoryReceiptPostingRepository:
    def __init__(
        self, connection: sqlite3.Connection, *, unit_of_work: SQLiteInventoryUnitOfWork | None = None,
        strict_command_actor: bool = False
    ) -> None:
        self.connection = connection
        self.unit_of_work = unit_of_work
        self.strict_command_actor = strict_command_actor
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables >= _SOURCE_TABLES:
            _fail(
                "Reviewed Inventory receipt schema requires SQLite migration 50.", "inventory_receipt_schema_required"
            )
        if unit_of_work is not None:
            unit_of_work.require_active(connection)

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[SQLiteInventoryUnitOfWork | None]:
        if write and self.connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            _fail(
                "Reviewed Inventory writes require foreign_keys=ON; caller settings were not changed.",
                "inventory_receipt_foreign_keys_required",
            )
        if self.unit_of_work is not None:
            with self.unit_of_work.operation(self.connection):
                yield self.unit_of_work
        elif write:
            with SQLiteInventoryUnitOfWork(self.connection) as owner, owner.operation(self.connection):
                yield owner
        else:
            owns = not self.connection.in_transaction
            if owns:
                self.connection.execute("BEGIN")
            try:
                yield None
            finally:
                if owns:
                    self.connection.rollback()

    def _authority(self, actor: PostingActor, permissions: frozenset[str], *, mutation: bool) -> None:
        principal = current_server_principal()
        if (
            principal is None
            or principal.principal_type != "user"
            or (principal.user.id, principal.user.username) != (actor.user_id, actor.username)
        ):
            _fail("A verified, bound human identity is required.", "inventory_receipt_human_required")
        user = self.connection.execute("SELECT username,disabled FROM users WHERE id=?", (actor.user_id,)).fetchone()
        if user is None or user["username"] != actor.username or user["disabled"]:
            _fail("The authenticated human is no longer enabled.", "inventory_receipt_human_required")
        if mutation and not principal.step_up_active:
            _fail("Recent human reauthentication is required.", "inventory_receipt_step_up_required")
        for permission in sorted(permissions):
            actor.require(permission, mutation=mutation)
            if permission not in principal.permissions:
                _fail("Current authenticated permission is required.", "inventory_receipt_permission_denied")
            if not evaluate_principal_access(principal, required_permission=permission).allowed:
                _fail(
                    "Central authorization denied this Inventory receipt action.", "inventory_receipt_permission_denied"
                )

    @staticmethod
    def _scope_authority(scope: Mapping[str, str]) -> None:
        principal = current_server_principal()
        if principal is None:
            _fail("A bound human is required.", "inventory_receipt_human_required")
        for field, allowed in (
            ("workspace_id", principal.authorized_workspace_ids),
            ("organization_id", principal.authorized_organization_ids),
            ("legal_entity_id", principal.authorized_legal_entity_ids),
        ):
            if allowed and scope[field] not in allowed:
                _fail("Receipt is outside the authenticated scope.", "inventory_receipt_scope_denied")

    def _one(self, sql: str, parameters: tuple[object, ...]) -> dict[str, Any]:
        row = self.connection.execute(sql, parameters).fetchone()
        if row is None:
            _fail("A required scoped Inventory reference was not found.", "inventory_receipt_not_found")
        return dict(row)

    def _scope(self, workspace: str, organization: str, entity: str) -> dict[str, str]:
        row = self._one(
            "SELECT w.id AS workspace_id,o.id AS organization_id,e.id AS legal_entity_id,"
            "o.organization_code,e.entity_code FROM workspaces w JOIN organizations o ON o.workspace_id=w.id "
            "JOIN legal_entities e ON e.organization_id=o.id WHERE w.name=? AND o.organization_code=? AND e.entity_code=?",
            (workspace, organization, entity),
        )
        self._scope_authority(row)
        return cast(dict[str, str], row)

    def _event(self, plan_id: str, action: str, actor: PostingActor, metadata: dict[str, Any]) -> tuple[str, str]:
        event = append_audit_event(
            self.connection,
            actor_user_id=actor.user_id,
            actor_label=actor.username,
            object_type="inventory_receipt_posting",
            object_id=plan_id,
            action=action,
            metadata=metadata,
        )
        outbox = "OBX-" + uuid4().hex
        append_outbox_event(
            self.connection,
            event_id=outbox,
            event_type=action,
            aggregate_type="inventory_receipt_posting",
            aggregate_id=plan_id,
            payload={**metadata, "audit_event_id": event.id},
        )
        return event.id, outbox

    def _verify_event(
        self, audit_id: str, outbox_id: str, actor_id: str, plan_id: str, action: str, metadata: dict[str, Any]
    ) -> None:
        audit = self._one("SELECT * FROM audit_events WHERE id=?", (audit_id,))
        outbox = self._one("SELECT * FROM outbox_events WHERE id=?", (outbox_id,))
        if (
            (audit["actor_user_id"], audit["object_type"], audit["object_id"], audit["action"])
            != (actor_id, "inventory_receipt_posting", plan_id, action)
            or decode_receipt_json(audit["metadata_json"]) != metadata
            or (outbox["aggregate_type"], outbox["aggregate_id"], outbox["event_type"])
            != ("inventory_receipt_posting", plan_id, action)
            or decode_receipt_json(outbox["payload_json"]) != {**metadata, "audit_event_id": audit_id}
        ):
            _fail("Retained Inventory source evidence does not match its source.")

    @staticmethod
    def _plan_columns(plan: ReceiptPlan) -> dict[str, Any]:
        source, mapping, scope = plan["source"], plan["mapping"], plan["scope"]
        return {
            "id": plan["plan_id"],
            **{key: scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
            "source_number": source["number"],
            "operation": plan["operation"],
            "plan_version": 1,
            **{
                key: source[key]
                for key in (
                    "period_id",
                    "posting_date",
                    "item_id",
                    "uom_id",
                    "location_id",
                    "quantity_scaled",
                    "quantity_precision",
                    "total_value_minor",
                )
            },
            "preparer_actor_id": plan["preparer"]["user_id"],
            "preparer_username": plan["preparer"]["username"],
            "prepared_at": plan["prepared_at"],
            "reason": plan["reason"],
            **plan["currency_policy"],
            **{
                key: mapping[key]
                for key in ("policy_id", "journal_id", "inventory_account_id", "receipt_clearing_account_id")
            },
            "mapping_digest": plan["mapping_digest"],
            "original_plan_id": plan["original"]["plan_id"] if plan["original"] else None,
            "original_posting_effect_id": plan["original"]["posting_effect_id"] if plan["original"] else None,
            **plan["artifacts"],
            "finance_validation_digest": plan["finance_validation_digest"],
            "plan_digest": plan["plan_digest"],
            "plan_json": encode_receipt_json(plan),
            "preparation_audit_event_id": plan["preparation_audit_event_id"],
            "preparation_outbox_event_id": plan["preparation_outbox_event_id"],
        }

    def _plan(self, plan_id: str, *, authorize: bool = True) -> ReceiptPlan:
        row = self._one("SELECT * FROM inventory_receipt_plans WHERE id=?", (plan_id,))
        if authorize:
            self._scope_authority(row)
        plan = verify_plan(decode_receipt_json(row["plan_json"]))
        expected = self._plan_columns(plan)
        if row != expected:
            _fail("Stored Inventory plan columns contradict its closed source.")
        FinancePolicyStore(self.connection).entry(plan["currency_policy"])
        self._verify_event(
            plan["preparation_audit_event_id"],
            plan["preparation_outbox_event_id"],
            plan["preparer"]["user_id"],
            plan_id,
            "inventory_receipt_prepared",
            {"plan_digest": plan["plan_digest"], "finance_validation_digest": plan["finance_validation_digest"]},
        )
        if plan["original"]:
            original = self._one(
                "SELECT operation FROM inventory_receipt_plans WHERE id=?", (plan["original"]["plan_id"],)
            )
            if original["operation"] != "Receipt":
                _fail("A retained full inverse must reference an original receipt.")
            verify_inverse(plan, self._plan(plan["original"]["plan_id"], authorize=False))
        return plan

    @staticmethod
    def _review_columns(plan: ReceiptPlan, review: ReceiptReview) -> dict[str, Any]:
        return {
            "id": review["review_id"],
            **{key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
            **{
                key: review[key]
                for key in (
                    "plan_id",
                    "plan_version",
                    "plan_digest",
                    "finance_validation_digest",
                    "reviewed_at",
                    "reason",
                    "review_digest",
                    "audit_event_id",
                    "outbox_event_id",
                )
            },
            "reviewer_actor_id": review["reviewer"]["user_id"],
            "reviewer_username": review["reviewer"]["username"],
            "review_json": encode_receipt_json(review),
        }

    def _review(self, plan: ReceiptPlan) -> ReceiptReview:
        row = self._one("SELECT * FROM inventory_receipt_reviews WHERE plan_id=?", (plan["plan_id"],))
        review = verify_review(decode_receipt_json(row["review_json"]), plan)
        if row != self._review_columns(plan, review):
            _fail("Stored Inventory review columns contradict its evidence.")
        self._verify_event(
            review["audit_event_id"],
            review["outbox_event_id"],
            review["reviewer"]["user_id"],
            plan["plan_id"],
            "inventory_receipt_reviewed",
            {
                "plan_digest": plan["plan_digest"],
                "review_digest": review["review_digest"],
                "finance_validation_digest": plan["finance_validation_digest"],
            },
        )
        return review

    def _cached(
        self, *, scope: Mapping[str, str], command_id: str, operation: str, request: Mapping[str, Any]
    ) -> tuple[str, dict[str, Any] | None]:
        digest = digest_payload(request)
        row = self.connection.execute(
            "SELECT * FROM inventory_receipt_commands WHERE workspace_id=? AND operation=? AND command_id=?",
            (scope["workspace_id"], operation, text(command_id, "command_id")),
        ).fetchone()
        if row is None:
            return digest, None
        self._scope_authority(row)
        if (
            any(row[key] != scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))
            or row["request_digest"] != digest
        ):
            _fail("Command identity was already used for different content.", "inventory_receipt_command_conflict")
        if self.strict_command_actor:
            principal = current_server_principal()
            if principal is None or row["actor_user_id"] != principal.user.id:
                _fail("Receipt command belongs to another authenticated human.", "inventory_receipt_command_actor_denied")
        plan = self._plan(row["plan_id"])
        expected: Mapping[str, Any]
        if operation in {"prepare_receipt", "prepare_reversal"}:
            expected, actor_id = plan, plan["preparer"]["user_id"]
        elif operation == "review":
            review = self._review(plan)
            expected, actor_id = review, review["reviewer"]["user_id"]
        else:
            effect = self._effect(plan)
            expected, actor_id = effect, effect["posted_actor_id"]
        result = decode_receipt_json(row["result_json"])
        if (
            result != expected
            or row["actor_user_id"] != actor_id
            or digest != digest_payload(_retained_intent(operation, plan, expected))
        ):
            _fail("Stored command receipt contradicts its immutable source.")
        return digest, dict(result)

    def _command(
        self,
        plan: ReceiptPlan,
        command_id: str,
        operation: str,
        digest: str,
        actor: PostingActor,
        result: Mapping[str, Any],
    ) -> None:
        _insert(
            self.connection,
            "inventory_receipt_commands",
            {
                **{key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                "command_id": text(command_id, "command_id"),
                "operation": operation,
                "request_digest": digest,
                "plan_id": plan["plan_id"],
                "actor_user_id": actor.user_id,
                "created_at": utc_now_text(),
                "result_json": encode_receipt_json(result),
            },
        )

    def _masters(
        self,
        scope: Mapping[str, str],
        *,
        item_id: str,
        location_id: str,
        policy_id: str,
        period_id: str,
        posting_date: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        organization = self._one("SELECT * FROM organizations WHERE id=?", (scope["organization_id"],))
        entity = self._one("SELECT * FROM legal_entities WHERE id=?", (scope["legal_entity_id"],))
        item = self._one(
            "SELECT i.*,u.decimal_places,u.active AS uom_active,a.active AS account_active,a.allow_posting,a.chart_id "
            "FROM inventory_items i JOIN units_of_measure u ON u.id=i.uom_id JOIN accounts a ON a.id=i.inventory_account_id WHERE i.id=?",
            (item_id,),
        )
        location = self._one(
            "SELECT l.*,w.active AS warehouse_active,w.organization_id,w.workspace_id,w.legal_entity_id FROM inventory_locations l "
            "JOIN warehouses w ON w.id=l.warehouse_id WHERE l.id=?",
            (location_id,),
        )
        period = self._one("SELECT * FROM periods WHERE id=?", (period_id,))
        persistence = SQLiteInventoryValuationRepository(self.connection)
        policy = persistence.policy(policy_id)
        if policy is None:
            _fail("Valuation mapping not found.", "inventory_receipt_not_found")
        if (
            any(row.get("active") != 1 for row in (organization, entity, item, location, policy))
            or not all(item[key] == 1 for key in ("uom_active", "account_active", "allow_posting"))
            or location["warehouse_active"] != 1
            or location["allow_negative"] != 0
            or item["item_type"] not in {"Stock", "Consumable"}
            or item["tracking_mode"] != "None"
            or location["location_type"] != "Internal"
        ):
            _fail(
                "Receipt requires active untracked stock, base UOM, Internal location and posting accounts.",
                "inventory_receipt_master_invalid",
            )
        if (
            any(
                row[key] != scope[key]
                for row in (location, policy)
                for key in ("workspace_id", "organization_id", "legal_entity_id")
            )
            or any(item[key] != scope[key] for key in ("workspace_id", "organization_id"))
            or organization["workspace_id"] != scope["workspace_id"]
            or entity["organization_id"] != scope["organization_id"]
        ):
            _fail("Canonical Inventory master scope does not match the receipt.", "inventory_receipt_scope_denied")
        if (
            period["workspace_id"] != scope["workspace_id"]
            or period["status"] != "Open"
            or not period["start_date"] <= posting_date <= period["end_date"]
        ):
            _fail("Receipt requires its Open fiscal period.", "inventory_receipt_period_closed")
        if (
            policy["costing_method"] != "FIFO"
            or policy["currency_code"] != entity["currency"]
            or policy["journal_currency_code"] != policy["currency_code"]
            or item["chart_id"] != policy["chart_id"]
        ):
            _fail(
                "Receipt requires one coherent functional-currency FIFO mapping.", "inventory_receipt_mapping_invalid"
            )
        if not all(
            policy[key] == 1
            for key in (
                "journal_active",
                "receipt_account_active",
                "receipt_account_allow_posting",
                "cogs_account_active",
                "cogs_account_allow_posting",
                "adjustment_account_active",
                "adjustment_account_allow_posting",
            )
        ):
            _fail("Receipt valuation accounts and journal must remain active.", "inventory_receipt_mapping_invalid")
        if persistence.required_dimensions_count(scope["workspace_id"], scope["organization_id"]):
            _fail("This receipt contract does not support required dimensions.", "inventory_receipt_scope_unsupported")
        mapping = {
            "policy_id": policy["id"],
            "costing_method": "FIFO",
            "currency_code": policy["currency_code"],
            "journal_id": policy["finance_journal_id"],
            "inventory_account_id": item["inventory_account_id"],
            **{key: policy[key] for key in ("receipt_clearing_account_id", "cogs_account_id", "adjustment_account_id")},
        }
        return item, policy, mapping

    def _admission(self, plan: ReceiptPlan, actor: PostingActor) -> None:
        source = plan["source"]
        item, policy, mapping = self._masters(
            plan["scope"],
            item_id=source["item_id"],
            location_id=source["location_id"],
            policy_id=plan["mapping"]["policy_id"],
            period_id=source["period_id"],
            posting_date=source["posting_date"],
        )
        currency = self._one("SELECT * FROM currencies WHERE code=?", (policy["currency_code"],))
        captured, _ = FinancePolicyStore(self.connection).capture(
            workspace_id=plan["scope"]["workspace_id"],
            currency_code=policy["currency_code"],
            minor_units=currency["minor_units"],
            actor_label=actor.username,
        )
        if (
            mapping != plan["mapping"]
            or {"currency_code": captured.currency_code, **captured.metadata()} != plan["currency_policy"]
            or item["uom_id"] != source["uom_id"]
            or item["decimal_places"] != source["quantity_precision"]
        ):
            _fail(
                "Reviewed source mapping or monetary policy changed; prepare a new source.",
                "inventory_receipt_review_changed",
            )
        if plan["operation"] == "FullReceiptReversal":
            self._unused(plan)

    def prepare_receipt(self, request: ReceiptPreparation, *, command_id: str, actor: PostingActor) -> ReceiptPlan:
        with self._transaction(write=True):
            self._authority(actor, PREPARE_PERMISSIONS, mutation=True)
            normalized = asdict(request)
            for key in ("organization_code", "entity_code", "item_code", "policy_code"):
                normalized[key] = code(normalized[key], key)
            normalized["receipt_number"] = movement_number(request.receipt_number)
            normalized["posting_date"] = exact_date(request.posting_date)
            normalized["reason"] = text(request.reason, "reason", maximum=500)
            normalized["workspace"] = text(request.workspace, "workspace")
            exact_int(request.total_value_minor)
            scope = self._scope(normalized["workspace"], normalized["organization_code"], normalized["entity_code"])
            item = self._one(
                "SELECT i.id,i.uom_id,u.decimal_places FROM inventory_items i JOIN units_of_measure u ON u.id=i.uom_id WHERE i.workspace_id=? AND i.organization_id=? AND i.item_code=?",
                (scope["workspace_id"], scope["organization_id"], normalized["item_code"]),
            )
            location_parts = request.location_code.strip().upper().split("/")
            if len(location_parts) != 2:
                _fail("Location must identify WAREHOUSE/LOCATION.", "inventory_receipt_request_invalid")
            location = self._one(
                "SELECT l.id FROM inventory_locations l JOIN warehouses w ON w.id=l.warehouse_id "
                "WHERE w.workspace_id=? AND w.organization_id=? AND w.legal_entity_id=? AND w.warehouse_code=? AND l.location_code=?",
                (scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], *location_parts),
            )
            policy = self._one(
                "SELECT id FROM inventory_valuation_policies WHERE workspace_id=? AND organization_id=? AND legal_entity_id=? AND policy_code=?",
                (scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], normalized["policy_code"]),
            )
            quantity = quantity_to_scaled(request.quantity, item["decimal_places"], "Receipt quantity")
            source = {
                "number": normalized["receipt_number"],
                "posting_date": normalized["posting_date"],
                "period_id": request.period_id,
                "item_id": item["id"],
                "uom_id": item["uom_id"],
                "location_id": location["id"],
                "quantity_scaled": quantity,
                "quantity_precision": item["decimal_places"],
                "quantity_text": scaled_to_text(quantity, item["decimal_places"]),
                "total_value_minor": request.total_value_minor,
            }
            intent = {"scope": scope, "source": source, "policy_id": policy["id"], "reason": normalized["reason"]}
            digest, replay = self._cached(
                scope=scope, command_id=command_id, operation="prepare_receipt", request=intent
            )
            if replay is not None:
                retained = verify_plan(replay)
                if intent != {
                    "scope": retained["scope"],
                    "source": retained["source"],
                    "policy_id": retained["mapping"]["policy_id"],
                    "reason": retained["reason"],
                }:
                    _fail("Receipt command input does not match its retained source.")
                return retained
            item, policy, mapping = self._masters(
                scope,
                item_id=item["id"],
                location_id=location["id"],
                policy_id=policy["id"],
                period_id=request.period_id,
                posting_date=normalized["posting_date"],
            )
            currency = self._one("SELECT minor_units FROM currencies WHERE code=?", (policy["currency_code"],))
            monetary, _ = FinancePolicyStore(self.connection).capture(
                workspace_id=scope["workspace_id"],
                currency_code=policy["currency_code"],
                minor_units=currency["minor_units"],
                actor_label=actor.username,
            )
            plan = make_plan(
                operation="Receipt",
                scope=scope,
                source=source,
                mapping=mapping,
                currency_policy={"currency_code": monetary.currency_code, **monetary.metadata()},
                actor=actor,
                prepared_at=utc_now_text(),
                reason=normalized["reason"],
                audit_event_id="pending",
                outbox_event_id="pending",
            )
            self._store_plan(plan, actor)
            self._command(plan, command_id, "prepare_receipt", digest, actor, plan)
            return self._plan(source_plan_id(scope, source["number"]))

    def _store_plan(self, plan: ReceiptPlan, actor: PostingActor) -> None:
        if self.connection.execute("SELECT 1 FROM inventory_receipt_plans WHERE id=?", (plan["plan_id"],)).fetchone():
            _fail("The source number already owns a prepared Inventory plan.", "inventory_receipt_source_conflict")
        audit, outbox = self._event(
            plan["plan_id"],
            "inventory_receipt_prepared",
            actor,
            {"plan_digest": plan["plan_digest"], "finance_validation_digest": plan["finance_validation_digest"]},
        )
        plan["preparation_audit_event_id"], plan["preparation_outbox_event_id"] = audit, outbox
        verify_plan(plan)
        _insert(self.connection, "inventory_receipt_plans", self._plan_columns(plan))

    def review(
        self, plan_id: str, *, command_id: str, expected_plan_digest: str, reason: str, actor: PostingActor
    ) -> ReceiptReview:
        with self._transaction(write=True):
            plan = self._plan(text(plan_id, "plan_id"))
            permissions = REVIEW_PERMISSIONS | (
                {"inventory.valuation.reverse.approve", "finance_core.reverse"} if plan["original"] else set()
            )
            self._authority(actor, frozenset(permissions), mutation=True)
            self._checker(plan, actor)
            reason = text(reason, "reason", maximum=500)
            digest, replay = self._cached(
                scope=plan["scope"],
                command_id=command_id,
                operation="review",
                request={"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": reason},
            )
            if replay is not None:
                return verify_review(replay, plan)
            if plan["plan_digest"] != expected_plan_digest:
                _fail("Expected plan digest differs from the retained source.", "inventory_receipt_review_changed")
            self._admission(plan, actor)
            review = make_review(
                plan,
                actor=actor,
                reviewed_at=utc_now_text(),
                reason=reason,
                audit_event_id="pending",
                outbox_event_id="pending",
            )
            audit, outbox = self._event(
                plan_id,
                "inventory_receipt_reviewed",
                actor,
                {
                    "plan_digest": plan["plan_digest"],
                    "review_digest": review["review_digest"],
                    "finance_validation_digest": plan["finance_validation_digest"],
                },
            )
            review["audit_event_id"], review["outbox_event_id"] = audit, outbox
            _insert(self.connection, "inventory_receipt_reviews", self._review_columns(plan, review))
            self._command(plan, command_id, "review", digest, actor, review)
            return self._review(plan)

    @staticmethod
    def _checker(plan: ReceiptPlan, actor: PostingActor) -> None:
        if actor.user_id == plan["preparer"]["user_id"]:
            _fail("The stable preparer identity cannot review or post its own receipt.", "inventory_receipt_sod_denied")

    def _unused(self, plan: ReceiptPlan) -> None:
        original_ref = plan["original"]
        if original_ref is None:
            _fail("A full inverse requires its original reviewed receipt.")
        original = self._plan(original_ref["plan_id"])
        verify_inverse(plan, original)
        self._effect(original)
        layer = self._one("SELECT * FROM inventory_cost_layers WHERE id=?", (original_ref["cost_layer_id"],))
        used = self.connection.execute(
            "SELECT 1 FROM inventory_layer_consumptions WHERE cost_layer_id=? UNION ALL "
            "SELECT 1 FROM inventory_valuation_reversal_effects WHERE cost_layer_id=? LIMIT 1",
            (layer["id"], layer["id"]),
        ).fetchone()
        outbound = self.connection.execute(
            "SELECT 1 FROM inventory_movement_lines l JOIN inventory_movements m ON m.id=l.movement_id "
            "WHERE l.item_id=? AND m.workspace_id=? AND m.organization_id=? AND m.legal_entity_id=? "
            "AND m.status IN ('Posted','Voided') AND l.from_location_id IS NOT NULL LIMIT 1",
            (
                plan["source"]["item_id"],
                plan["scope"]["workspace_id"],
                plan["scope"]["organization_id"],
                plan["scope"]["legal_entity_id"],
            ),
        ).fetchone()
        if (
            used
            or outbound
            or layer["remaining_quantity_scaled"] != layer["original_quantity_scaled"]
            or layer["remaining_value_minor"] != layer["original_value_minor"]
        ):
            _fail(
                "Full inverse requires an unused original layer and no historical outbound dependency for this item.",
                "inventory_receipt_inverse_used",
            )
        if self.connection.execute(
            "SELECT 1 FROM inventory_receipt_links WHERE original_plan_id=?", (original["plan_id"],)
        ).fetchone():
            _fail("The original receipt already has a committed inverse.", "inventory_receipt_source_conflict")

    def prepare_reversal(
        self, request: ReceiptReversalPreparation, *, command_id: str, actor: PostingActor
    ) -> ReceiptPlan:
        with self._transaction(write=True):
            self._authority(
                actor,
                PREPARE_PERMISSIONS | {"inventory.valuation.reverse.manage", "finance_core.reverse"},
                mutation=True,
            )
            original = self._plan(text(request.original_plan_id, "original_plan_id"))
            self._effect(original)
            source = {
                **original["source"],
                "number": movement_number(request.reversal_number),
                "posting_date": exact_date(request.posting_date),
                "period_id": text(request.period_id, "period_id"),
            }
            reason = text(request.reason, "reason", maximum=500)
            intent = {"original_plan_id": original["plan_id"], "source": source, "reason": reason}
            digest, replay = self._cached(
                scope=original["scope"], command_id=command_id, operation="prepare_reversal", request=intent
            )
            if replay is not None:
                retained = verify_plan(replay)
                verify_inverse(retained, original)
                if retained["source"] != source or retained["reason"] != reason:
                    _fail("Inverse command input does not match its retained source.")
                return retained
            original_ref = {
                "plan_id": original["plan_id"],
                **{
                    key: str(original["artifacts"][key])
                    for key in ("posting_effect_id", "valuation_document_id", "valuation_line_id", "cost_layer_id")
                },
            }
            plan = make_plan(
                operation="FullReceiptReversal",
                scope=original["scope"],
                source=source,
                mapping=original["mapping"],
                currency_policy=original["currency_policy"],
                actor=actor,
                prepared_at=utc_now_text(),
                reason=reason,
                audit_event_id="pending",
                outbox_event_id="pending",
                original=original_ref,
            )
            self._admission(plan, actor)
            self._store_plan(plan, actor)
            self._command(plan, command_id, "prepare_reversal", digest, actor, plan)
            return self._plan(plan["plan_id"])

    def commit(
        self, plan_id: str, *, command_id: str, expected_review_digest: str, reason: str, actor: PostingActor
    ) -> ReceiptEffect:
        with self._transaction(write=True) as owner:
            if owner is None:
                _fail("An active Inventory transaction owner is required.")
            plan = self._plan(text(plan_id, "plan_id"))
            permissions = COMMIT_PERMISSIONS | (
                {"inventory.valuation.reverse.approve", "finance_core.reverse"} if plan["original"] else set()
            )
            self._authority(actor, frozenset(permissions), mutation=True)
            self._checker(plan, actor)
            reason = text(reason, "reason", maximum=500)
            digest, replay = self._cached(
                scope=plan["scope"],
                command_id=command_id,
                operation="commit",
                request={"plan_id": plan_id, "expected_review_digest": expected_review_digest, "reason": reason},
            )
            review = self._review(plan)
            if replay is not None:
                return verify_effect(replay, plan, review)
            if review["review_digest"] != expected_review_digest:
                _fail("Expected review digest differs from its retained review.", "inventory_receipt_review_changed")
            if self.connection.execute("SELECT 1 FROM inventory_receipt_links WHERE plan_id=?", (plan_id,)).fetchone():
                _fail("This source already has a committed operational effect.", "inventory_receipt_source_conflict")
            self._admission(plan, actor)
            link = {
                "id": plan_id,
                **{key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                "plan_id": plan_id,
                "review_id": review["review_id"],
                "plan_digest": plan["plan_digest"],
                "review_digest": review["review_digest"],
                **{key: value for key, value in plan["artifacts"].items() if not key.endswith("_number")},
                "original_plan_id": plan["original"]["plan_id"] if plan["original"] else None,
                "original_posting_effect_id": plan["original"]["posting_effect_id"] if plan["original"] else None,
                "posted_actor_id": actor.user_id,
                "posted_at": utc_now_text(),
                "reason": reason,
                "audit_event_id": "AE-" + uuid4().hex,
                "outbox_event_id": "OBX-" + uuid4().hex,
            }
            # append_audit_event allocates its own identity. Reserve the real event
            # before the link; the deferred effect reference still prevents any
            # evidence-only commit if a later participant fails.
            audit, outbox = self._event(
                plan_id,
                "inventory_receipt_committed",
                actor,
                {
                    "plan_digest": plan["plan_digest"],
                    "review_digest": review["review_digest"],
                    "finance_validation_digest": plan["finance_validation_digest"],
                    "effect_id": plan["artifacts"]["posting_effect_id"],
                },
            )
            link["audit_event_id"], link["outbox_event_id"] = audit, outbox
            _insert(self.connection, "inventory_receipt_links", link)
            self._materialize_inventory(plan, review, link, actor, owner)
            participant = owner.receipt_finance()
            entry_id = participant.materialize_draft(
                plan_id, expected_review_digest=expected_review_digest, actor=actor
            )
            table, identifier = (
                ("inventory_valuation_documents", plan["artifacts"]["valuation_document_id"])
                if plan["operation"] == "Receipt"
                else ("inventory_valuation_reversals", plan["artifacts"]["valuation_reversal_id"])
            )
            self.connection.execute(
                f"UPDATE {table} SET status='Approved',total_value_minor=?,finance_entry_id=?,approved_by=?,approved_at=?,approval_reason=? WHERE id=?",  # nosec B608
                (plan["source"]["total_value_minor"], entry_id, actor.username, link["posted_at"], reason, identifier),
            )
            participant.seal_and_post(plan_id, expected_review_digest=expected_review_digest, actor=actor)
            effect = self._effect(plan)
            self._command(plan, command_id, "commit", digest, actor, effect)
            return effect

    def _materialize_inventory(
        self,
        plan: ReceiptPlan,
        review: ReceiptReview,
        link: Mapping[str, Any],
        actor: PostingActor,
        owner: SQLiteInventoryUnitOfWork,
    ) -> None:
        owner.require_active(self.connection)
        records = expected_inventory_records(plan, link, actor.username)
        movement = dict(records["inventory_movements"])
        movement.update(status="Draft", posted_by="", posted_at=None, post_reason="")
        _insert(self.connection, "inventory_movements", movement)
        _insert(self.connection, "inventory_movement_lines", records["inventory_movement_lines"])
        core = owner.core()
        core._validate_movement_integrity(movement, check_stock=True)
        self.connection.execute(
            "UPDATE inventory_movements SET status='Posted',posted_by=?,posted_at=?,post_reason=? WHERE id=?",
            (actor.username, link["posted_at"], link["reason"], movement["id"]),
        )
        persistence = SQLiteInventoryValuationRepository(self.connection, unit_of_work=owner)
        if plan["operation"] == "Receipt" and (
            persistence.earlier_unvalued_movement(str(movement["id"]))
            or persistence.later_approved_document(str(movement["id"]))
        ):
            _fail("Receipt has unresolved valuation chronology dependencies.", "inventory_receipt_valuation_order")
        header_table = (
            "inventory_valuation_documents" if plan["operation"] == "Receipt" else "inventory_valuation_reversals"
        )
        header = dict(records[header_table])
        header.update(
            status="Draft",
            total_value_minor=0,
            finance_entry_id=None,
            approved_by="",
            approved_at=None,
            approval_reason="",
        )
        _insert(self.connection, header_table, header)
        if plan["operation"] == "Receipt":
            for table in ("inventory_valuation_input_costs", "inventory_valuation_lines", "inventory_cost_layers"):
                _insert(self.connection, table, records[table])
        else:
            _insert(
                self.connection, "inventory_valuation_reversal_effects", records["inventory_valuation_reversal_effects"]
            )
            self.connection.execute(
                "UPDATE inventory_cost_layers SET remaining_quantity_scaled=0,remaining_value_minor=0 WHERE id=?",
                (plan["artifacts"]["cost_layer_id"],),
            )

    def _effect(self, plan: ReceiptPlan) -> ReceiptEffect:
        from reconforge.infrastructure.sqlite_finance_posting import SQLiteFinancePostingRepository

        review = self._review(plan)
        link = self._one("SELECT * FROM inventory_receipt_links WHERE plan_id=?", (plan["plan_id"],))
        verify_inventory_backing(self, plan, review, link)
        finance = SQLiteFinancePostingRepository(self.connection)._get_effect(
            str(plan["artifacts"]["posting_effect_id"])
        )
        effect = make_effect(
            plan, review, finance, audit_event_id=link["audit_event_id"], outbox_event_id=link["outbox_event_id"]
        )
        return verify_effect(effect, plan, review)

    def get_effect(self, plan_id: str, *, actor: PostingActor) -> ReceiptEffect:
        with self._transaction():
            self._authority(actor, READ_PERMISSIONS, mutation=False)
            return self._effect(self._plan(text(plan_id, "plan_id")))

    def get_plan(self, plan_id: str, *, actor: PostingActor) -> ReceiptPlanView:
        with self._transaction():
            self._authority(actor, READ_PERMISSIONS, mutation=False)
            plan = self._plan(text(plan_id, "plan_id"))
            review = (
                self._review(plan)
                if self.connection.execute(
                    "SELECT 1 FROM inventory_receipt_reviews WHERE plan_id=?", (plan_id,)
                ).fetchone()
                else None
            )
            effect = (
                self._effect(plan)
                if self.connection.execute(
                    "SELECT 1 FROM inventory_receipt_links WHERE plan_id=?", (plan_id,)
                ).fetchone()
                else None
            )
            return {"plan": plan, "review": review, "effect": effect}


def expected_inventory_records(
    plan: ReceiptPlan, link: Mapping[str, Any], poster_username: str
) -> dict[str, dict[str, Any]]:
    """Retained physical fields; mutable layer balances are checked separately."""
    source, artifacts = plan["source"], plan["artifacts"]
    inverse = plan["operation"] == "FullReceiptReversal"
    scope = {key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
    common = {
        **scope,
        "period_id": source["period_id"],
        "created_by": plan["preparer"]["username"],
        "created_at": link["posted_at"],
        "updated_at": link["posted_at"],
    }
    approval = {
        "status": "Approved",
        "total_value_minor": source["total_value_minor"],
        "finance_entry_id": artifacts["finance_entry_id"],
        "approved_by": poster_username,
        "approved_at": link["posted_at"],
        "approval_reason": link["reason"],
        "cancelled_by": "",
        "cancelled_at": None,
        "cancel_reason": "",
    }
    result = {
        "inventory_movements": {
            **common,
            "id": artifacts["movement_id"],
            "movement_number": artifacts["movement_number"],
            "movement_type": "Delivery" if inverse else "Receipt",
            "movement_date": source["posting_date"],
            "source_reference": plan["plan_id"],
            "description": plan["reason"],
            "source_type": "Generated",
            "status": "Posted",
            "posted_by": poster_username,
            "posted_at": link["posted_at"],
            "post_reason": link["reason"],
            "voided_by": "",
            "voided_at": None,
            "void_reason": "",
        },
        "inventory_movement_lines": {
            "id": artifacts["movement_line_id"],
            "movement_id": artifacts["movement_id"],
            "line_number": 1,
            "item_id": source["item_id"],
            "uom_id": source["uom_id"],
            "inventory_lot_id": None,
            "from_location_id": source["location_id"] if inverse else None,
            "to_location_id": None if inverse else source["location_id"],
            "quantity_scaled": source["quantity_scaled"],
            "quantity_precision": source["quantity_precision"],
            "description": plan["reason"],
            "created_at": link["posted_at"],
        },
    }
    if inverse:
        if plan["original"] is None:
            _fail("A full inverse requires its retained original source.")
        result["inventory_valuation_reversals"] = {
            **common,
            **approval,
            "id": artifacts["valuation_reversal_id"],
            "original_valuation_document_id": plan["original"]["valuation_document_id"],
            "reversal_movement_id": artifacts["movement_id"],
            "reversal_number": artifacts["valuation_number"],
            "reversal_date": source["posting_date"],
            "currency_code": plan["currency_policy"]["currency_code"],
        }
        result["inventory_valuation_reversal_effects"] = {
            "id": artifacts["reversal_effect_id"],
            "reversal_id": artifacts["valuation_reversal_id"],
            "original_valuation_line_id": plan["original"]["valuation_line_id"],
            "original_consumption_id": None,
            "cost_layer_id": artifacts["cost_layer_id"],
            "effect_type": "Remove",
            "quantity_scaled": source["quantity_scaled"],
            "value_minor": source["total_value_minor"],
            "created_at": link["posted_at"],
        }
    else:
        result["inventory_valuation_documents"] = {
            **common,
            **approval,
            **plan["currency_policy"],
            "id": artifacts["valuation_document_id"],
            "movement_id": artifacts["movement_id"],
            "policy_id": plan["mapping"]["policy_id"],
            "valuation_number": artifacts["valuation_number"],
            "valuation_date": source["posting_date"],
        }
        result["inventory_valuation_input_costs"] = {
            "id": artifacts["input_cost_id"],
            "valuation_document_id": artifacts["valuation_document_id"],
            "movement_line_id": artifacts["movement_line_id"],
            "total_cost_minor": source["total_value_minor"],
            "created_at": link["posted_at"],
        }
        result["inventory_valuation_lines"] = {
            "id": artifacts["valuation_line_id"],
            "valuation_document_id": artifacts["valuation_document_id"],
            "movement_line_id": artifacts["movement_line_id"],
            "line_number": 1,
            "flow_direction": "Inbound",
            "item_id": source["item_id"],
            "uom_id": source["uom_id"],
            "inventory_lot_id": None,
            "quantity_scaled": source["quantity_scaled"],
            "quantity_precision": source["quantity_precision"],
            "value_minor": source["total_value_minor"],
            "inventory_account_id": plan["mapping"]["inventory_account_id"],
            "offset_account_id": plan["mapping"]["receipt_clearing_account_id"],
            "created_at": link["posted_at"],
        }
        result["inventory_cost_layers"] = {
            "id": artifacts["cost_layer_id"],
            "source_valuation_line_id": artifacts["valuation_line_id"],
            "legal_entity_id": scope["legal_entity_id"],
            "item_id": source["item_id"],
            "uom_id": source["uom_id"],
            "inventory_lot_id": None,
            "quantity_precision": source["quantity_precision"],
            "original_quantity_scaled": source["quantity_scaled"],
            "remaining_quantity_scaled": source["quantity_scaled"],
            "original_value_minor": source["total_value_minor"],
            "remaining_value_minor": source["total_value_minor"],
            "currency_code": plan["currency_policy"]["currency_code"],
            "created_at": link["posted_at"],
        }
    return result


def verify_inventory_backing(
    repository: SQLiteInventoryReceiptPostingRepository,
    plan: ReceiptPlan,
    review: ReceiptReview,
    link: Mapping[str, Any],
) -> None:
    expected = {
        "id": plan["plan_id"],
        "plan_id": plan["plan_id"],
        "review_id": review["review_id"],
        **{key: plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
        "plan_digest": plan["plan_digest"],
        "review_digest": review["review_digest"],
        **{key: value for key, value in plan["artifacts"].items() if not key.endswith("_number")},
        "original_plan_id": plan["original"]["plan_id"] if plan["original"] else None,
        "original_posting_effect_id": plan["original"]["posting_effect_id"] if plan["original"] else None,
    }
    if (
        any(link[key] != value for key, value in expected.items())
        or link["posted_actor_id"] == plan["preparer"]["user_id"]
    ):
        _fail("Inventory link contradicts its retained source and review.")
    repository._verify_event(
        link["audit_event_id"],
        link["outbox_event_id"],
        link["posted_actor_id"],
        plan["plan_id"],
        "inventory_receipt_committed",
        {
            "plan_digest": plan["plan_digest"],
            "review_digest": review["review_digest"],
            "finance_validation_digest": plan["finance_validation_digest"],
            "effect_id": plan["artifacts"]["posting_effect_id"],
        },
    )
    audit = repository._one("SELECT actor_label FROM audit_events WHERE id=?", (link["audit_event_id"],))
    records = expected_inventory_records(plan, link, audit["actor_label"])
    for table, expected_row in records.items():
        actual = repository._one(f"SELECT * FROM {table} WHERE id=?", (expected_row["id"],))  # nosec B608
        excluded = {"remaining_quantity_scaled", "remaining_value_minor"} if table == "inventory_cost_layers" else set()
        if any(actual[key] != value for key, value in expected_row.items() if key not in excluded):
            _fail("Materialized Inventory rows contradict the retained receipt.")
    connection = repository.connection
    for table, parent, identifier in (
        ("inventory_movement_lines", "movement_id", plan["artifacts"]["movement_id"]),
        ("inventory_valuation_lines", "valuation_document_id", plan["artifacts"]["valuation_document_id"]),
        ("inventory_valuation_input_costs", "valuation_document_id", plan["artifacts"]["valuation_document_id"]),
        ("inventory_valuation_reversal_effects", "reversal_id", plan["artifacts"]["valuation_reversal_id"]),
    ):
        if (
            identifier
            and connection.execute(f"SELECT count(*) FROM {table} WHERE {parent}=?", (identifier,)).fetchone()[0] != 1  # nosec B608
        ):  # nosec B608
            _fail("Reviewed receipt requires exactly its retained source line.")
    layer = repository._one("SELECT * FROM inventory_cost_layers WHERE id=?", (plan["artifacts"]["cost_layer_id"],))
    quantity, value = layer["original_quantity_scaled"], layer["original_value_minor"]
    for row in connection.execute(
        "SELECT quantity_scaled,value_minor FROM inventory_layer_consumptions WHERE cost_layer_id=?", (layer["id"],)
    ):
        quantity -= row["quantity_scaled"]
        value -= row["value_minor"]
    for row in connection.execute(
        "SELECT effect_type,quantity_scaled,value_minor FROM inventory_valuation_reversal_effects WHERE cost_layer_id=?",
        (layer["id"],),
    ):
        sign = 1 if row["effect_type"] == "Restore" else -1
        quantity += sign * row["quantity_scaled"]
        value += sign * row["value_minor"]
    if (quantity, value) != (layer["remaining_quantity_scaled"], layer["remaining_value_minor"]):
        _fail("Retained FIFO balance is not explained by its immutable history.")


def _retained_intent(operation: str, plan: ReceiptPlan, result: Mapping[str, Any]) -> dict[str, Any]:
    if operation == "prepare_receipt":
        return {
            "scope": plan["scope"],
            "source": plan["source"],
            "policy_id": plan["mapping"]["policy_id"],
            "reason": plan["reason"],
        }
    if operation == "prepare_reversal":
        if plan["original"] is None:
            _fail("Inverse receipt command references an original operation.")
        return {"original_plan_id": plan["original"]["plan_id"], "source": plan["source"], "reason": plan["reason"]}
    if operation == "review":
        return {"plan_id": plan["plan_id"], "expected_plan_digest": plan["plan_digest"], "reason": result["reason"]}
    if operation == "commit":
        return {
            "plan_id": plan["plan_id"],
            "expected_review_digest": result["review_digest"],
            "reason": result["finance_effect"]["reason"],
        }
    _fail("Unknown retained receipt operation.")


def verify_receipt_storage(connection: sqlite3.Connection) -> None:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventory_receipt_plans'"
    ).fetchone():
        return
    repository = SQLiteInventoryReceiptPostingRepository(connection)
    from reconforge.infrastructure.sqlite_inventory_receipt_posting_schema import RESERVED_COLUMNS

    owners = {
        "inventory_movements": "movement_id",
        "inventory_movement_lines": "movement_line_id",
        "inventory_valuation_documents": "valuation_document_id",
        "inventory_valuation_input_costs": "input_cost_id",
        "inventory_valuation_lines": "valuation_line_id",
        "inventory_cost_layers": "cost_layer_id",
        "inventory_valuation_reversals": "valuation_reversal_id",
        "inventory_valuation_reversal_effects": "reversal_effect_id",
        "ledger_entries": "finance_entry_id",
        "ledger_lines": "finance_line_1_id",
        "finance_posting_effects": "posting_effect_id",
    }
    for table, column in owners.items():
        reserved = " OR ".join(f"upper(substr(record.{name},1,5))='IRP1-'" for name in RESERVED_COLUMNS[table])
        linkage = f"k.{column}=record.id"
        if table == "ledger_lines":
            linkage += " OR k.finance_line_2_id=record.id"
        if connection.execute(
            f"SELECT 1 FROM {table} record WHERE ({reserved}) AND NOT EXISTS(SELECT 1 FROM inventory_receipt_links k WHERE {linkage}) LIMIT 1"  # nosec B608
        ).fetchone():
            _fail("Reserved Inventory artifact has no complete reviewed source owner.")
    for row in connection.execute("SELECT id FROM inventory_receipt_plans ORDER BY id"):
        plan = repository._plan(row["id"], authorize=False)
        if connection.execute("SELECT 1 FROM inventory_receipt_reviews WHERE plan_id=?", (row["id"],)).fetchone():
            repository._review(plan)
        if connection.execute("SELECT 1 FROM inventory_receipt_links WHERE plan_id=?", (row["id"],)).fetchone():
            repository._effect(plan)
    for row in connection.execute("SELECT * FROM inventory_receipt_commands"):
        plan = repository._plan(row["plan_id"], authorize=False)
        result = decode_receipt_json(row["result_json"])
        expected: Mapping[str, Any]
        if row["operation"] in {"prepare_receipt", "prepare_reversal"}:
            expected = plan
            actor_id = plan["preparer"]["user_id"]
        elif row["operation"] == "review":
            expected = repository._review(plan)
            actor_id = expected["reviewer"]["user_id"]
        else:
            expected = repository._effect(plan)
            actor_id = expected["posted_actor_id"]
        if (
            result != expected
            or row["request_digest"] != digest_payload(_retained_intent(row["operation"], plan, expected))
            or row["actor_user_id"] != actor_id
            or any(row[key] != plan["scope"][key] for key in ("workspace_id", "organization_id", "legal_entity_id"))
        ):
            _fail("Stored Inventory command response does not match its authoritative source.")
