"""One transaction composes native FIFO Remove, original AP inverse and credit."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from reconforge.domain.budget_control import BudgetScope
from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    validation_digest,
)
from reconforge.domain.inventory_receipt_posting import ReceiptReversalPreparation, exact_text
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.supplier_returns import SupplierReturnPreparation, return_values
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from reconforge.platform.common import current_server_principal, platform_id
from reconforge.utils.time import utc_now_text

READ = frozenset({"payables.read", "inventory.read", "finance_core.read"})
PERMISSIONS = {
    "prepare": READ | {"payables.manage", "inventory.manage", "inventory.valuation.manage", "inventory.valuation.reverse.manage", "finance_core.manage", "finance_core.reverse"},
    "review": READ | {"payables.approve", "inventory.post", "inventory.valuation.approve", "inventory.valuation.reverse.approve", "finance_core.validate", "finance_core.reverse"},
    "post": READ | {"payables.manage", "inventory.post", "inventory.valuation.approve", "inventory.valuation.reverse.approve", "finance_core.post", "finance_core.reverse"},
    "cancel": READ | {"payables.approve", "inventory.valuation.reverse.approve", "finance_core.validate"},
}


class _SupplierReturnPostingParticipant:
    def __init__(self, owner: PostgresSupplierReturnsRepository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class PostgresSupplierReturnsRepository:
    def __init__(self, connection: Any, tenant_id: str, *, require_live_session_assurance: bool = False) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.purchase = PostgresProcurementPartialRepository(connection, tenant_id)
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self.receipts = self.purchase.receipts
        self.authority = PostgresBudgetControlRepository(connection, tenant_id,
            require_live_session_assurance=require_live_session_assurance)
        self._participant: _SupplierReturnPostingParticipant | None = None

    def _one(self, query: str, parameters: tuple[Any, ...]) -> dict[str, Any]:
        return self.purchase._one(query, parameters)

    def _actor(self, actor: PostingActor, operation: str, plan: Mapping[str, Any]) -> None:
        permissions = PERMISSIONS.get(operation, READ)
        for permission in sorted(permissions):
            self.owner._actor(actor, permission, plan, mutation=operation != "read")
        scope = BudgetScope(*(str(plan[key]) for key in ("workspace_id", "organization_id", "legal_entity_id")))
        live = self.authority._authority(scope, actor.user_id, actor.username)
        if (live is None or not permissions <= live.permissions or scope.workspace_id not in live.workspace_ids
                or scope.organization_id not in live.organization_ids or scope.legal_entity_id not in live.legal_entity_ids):
            raise FinancePostingError("supplier_return_authority_denied", "Current persisted permission and hierarchy grants are required.")
        if operation != "read":
            self.authority._assert_write_session(current_server_principal())
            self.connection.execute("SELECT set_config('app.supplier_return_actor_id',%s,true)", (actor.user_id,))

    def _row(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        query = ("SELECT payload,phase FROM reconforge.supplier_return_plans WHERE tenant_id=%s AND id=%s FOR UPDATE" if lock
                 else "SELECT payload,phase FROM reconforge.supplier_return_plans WHERE tenant_id=%s AND id=%s")
        row = self._one(query, (self.tenant_id, exact_text(identifier)))
        return {**row["payload"], "phase": row["phase"]}

    def _source(self, order_id: str, receipt_id: str, invoice_id: str, *, lock: bool = False) -> dict[str, Any]:
        order = self.purchase._order(order_id, lock=lock)
        if lock:
            self.connection.execute("SELECT s.id FROM reconforge.ap_suppliers s JOIN reconforge.ap_purchase_orders p ON p.tenant_id=s.tenant_id AND p.supplier_id=s.id WHERE p.tenant_id=%s AND p.id=%s FOR UPDATE OF s",
                                    (self.tenant_id, order["purchase_order_id"]))
            self.connection.execute("SELECT h.id FROM reconforge.ap_supplier_invoices h JOIN reconforge.procurement_partial_invoices i ON i.tenant_id=h.tenant_id AND i.native_invoice_id=h.id WHERE i.tenant_id=%s AND i.order_id=%s AND i.id=%s FOR UPDATE OF h",
                                    (self.tenant_id, order_id, invoice_id))
        source = self._one("SELECT reconforge.sr_source(%s,%s,%s,%s) value", (self.tenant_id, order_id, receipt_id, invoice_id))["value"]
        if source is None:
            raise FinancePostingError("supplier_return_source_invalid", "Select a complete native receipt and matching accrued single-line AP invoice.")
        return source

    def _locks(self, plan: Mapping[str, Any]) -> None:
        # Native receipt family: corrective period -> purchase -> supplier/AP -> metadata -> inverse/FIFO/GL.
        self.owner.posting._period(plan["period_id"], plan["workspace_id"], plan["posting_date"])
        self._source(plan["order_id"], plan["receipt_id"], plan["invoice_id"], lock=True)
        self._row(plan["id"], lock=True)

    def _command(self, plan: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        exact_text(command_id, maximum=140)
        digest = digest_payload({"operation": operation, "actor_id": actor.user_id, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, plan["workspace_id"], "supplier-return", command_id]),))
        retained = self.connection.execute("SELECT * FROM reconforge.supplier_return_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                           (self.tenant_id, plan["workspace_id"], command_id)).fetchone()
        if retained is None:
            return digest, None
        if (retained["operation"], retained["actor_id"], retained["request_digest"]) != (operation, actor.user_id, digest):
            raise FinancePostingError("supplier_return_command_conflict", "Command identifies another exact source request or current human.")
        self._actor(actor, operation, self._row(retained["plan_id"]))
        self.connection.execute("SELECT reconforge.sr_close(%s,%s)", (self.tenant_id, retained["plan_id"]))
        return digest, dict(retained["response_json"])

    def _view(self, plan_id: str) -> dict[str, Any]:
        return self._one("SELECT reconforge.sr_public(%s,%s) value", (self.tenant_id, plan_id))["value"]

    def _remember(self, plan: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                  digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self._view(plan["id"])
        self.connection.execute("""INSERT INTO reconforge.supplier_return_commands(tenant_id,workspace_id,plan_id,operation,
            command_id,actor_id,request_digest,request_json,response_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, plan["workspace_id"], plan["id"], operation, command_id, actor.user_id, digest,
             canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        self.connection.execute("SELECT reconforge.sr_close(%s,%s)", (self.tenant_id, plan["id"]))
        return result

    def _inverse(self, effect: Mapping[str, Any], args: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        original = effect["snapshot_json"]["entry"]
        entry_id, number, now = platform_id("GLE", args["workspace_id"], args["id"].upper() + "-AP"), args["id"].upper() + "-AP", utc_now_text()
        total = sum(line["credit_minor"] for line in effect["snapshot_json"]["lines"])
        self.connection.execute("""INSERT INTO reconforge.finance_entries(tenant_id,id,workspace_id,journal_id,organization_code,
            entity_code,period_id,entry_number,posting_date,description,external_reference,source_type,status,currency_code,
            total_debit_minor,total_credit_minor,created_by,currency_precision,currency_rounding_policy,currency_registry_version,
            currency_registry_digest,preparer_actor_id,reverses_posting_id,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Generated','Draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.tenant_id, entry_id, args["workspace_id"], original["journal_id"], args["organization_code"], args["entity_code"],
             args["period_id"], number, args["posting_date"], args["reason"], args["id"], original["currency_code"], total, total,
             actor.username, original["currency_precision"], original["currency_rounding_policy"], original["currency_registry_version"],
             original["currency_registry_digest"], actor.user_id, effect["id"], now, now))
        for line in effect["snapshot_json"]["lines"]:
            line_id = platform_id("GLL", entry_id, line["line_number"])
            self.connection.execute("""INSERT INTO reconforge.finance_entry_lines(tenant_id,id,entry_id,line_number,account_id,
                description,debit_minor,credit_minor,currency_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, line_id, entry_id, line["line_number"], line["account_id"], line["description"],
                 line["credit_minor"], line["debit_minor"], original["currency_code"]))
            for dimension, value in line["dimensions"].items():
                self.connection.execute("INSERT INTO reconforge.finance_entry_line_dimensions(tenant_id,entry_line_id,dimension_id,dimension_value_id) VALUES(%s,%s,%s,%s)",
                                        (self.tenant_id, line_id, dimension, value))
        snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry_id))
        return {"entry_id": entry_id, "snapshot": snapshot, "validation_digest": validation_digest(snapshot), "original_effect_id": effect["id"]}

    def prepare(self, request: SupplierReturnPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            source = self._source(request.order_id, request.receipt_id, request.invoice_id)
            original = source["original_plan"]
            payload = {**original["scope"], **args, **return_values(source["receipt"]["total_minor"], original["source"]["total_value_minor"]),
                       "currency_code": original["currency_policy"]["currency_code"], "currency_precision": original["currency_policy"]["currency_precision"]}
            self._actor(actor, "prepare", payload)
            digest, replay = self._command(payload, "prepare", command_id, actor, args)
            if replay is not None:
                return replay
            self.owner.posting._period(request.period_id, payload["workspace_id"], request.posting_date)
            source = self._source(request.order_id, request.receipt_id, request.invoice_id, lock=True)
            self._actor(actor, "prepare", payload)
            self.connection.execute("SELECT reconforge.sr_available(%s,%s,%s,%s)", (self.tenant_id, request.order_id, request.receipt_id, request.invoice_id))
            if request.posting_date < max(source["receipt"]["posting_date"], source["invoice"]["posting_date"]):
                raise FinancePostingError("supplier_return_date_invalid", "Return cannot precede its original receipt or AP accrual.")
            payload.update(schema_version="supplier-return-v1", id="SR1-" + uuid4().hex, request=args, source_snapshot=source,
                           native_invoice_id=source["native_invoice"]["id"], preparer_actor_id=actor.user_id)
            inverse = self.receipts.prepare_reversal(ReceiptReversalPreparation(original_plan_id=source["receipt"]["receipt_plan_id"],
                reversal_number=payload["id"].upper(), posting_date=request.posting_date, period_id=request.period_id, reason=request.reason),
                command_id=platform_id("SRIRP", payload["id"], "prepare"), actor=actor)
            payload["inverse_plan"] = dict(inverse)
            payload["entries"] = [self._inverse(source["accrual_effect"], payload, actor)]
            if payload["charge_expense_minor"]:
                amount = exact_minor_text(payload["charge_expense_minor"], payload["currency_precision"])
                clearing = self._one("SELECT account_code FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s",
                                     (self.tenant_id, original["mapping"]["receipt_clearing_account_id"]))["account_code"]
                journal = self._one("SELECT journal_code FROM reconforge.finance_journals WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, original["mapping"]["journal_id"]))["journal_code"]
                entry = self.owner.finance.create_entry(entry_number=payload["id"].upper() + "-CH", workspace=payload["workspace_id"],
                    organization_code=payload["organization_code"], entity_code=payload["entity_code"], period_id=request.period_id,
                    journal_code=journal, posting_date=request.posting_date, description=request.reason, external_reference=payload["id"],
                    actor_label=actor.username, lines=[{"account_code": request.expense_account_code, "debit": amount}, {"account_code": clearing, "credit": amount}])
                snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
                payload["entries"].append({"entry_id": entry["id"], "snapshot": snapshot, "validation_digest": validation_digest(snapshot), "original_effect_id": None})
            payload["plan_digest"] = digest_payload(payload)
            audit, outbox = self.owner._event(payload, "supplier_return_prepared", actor, {"plan_digest": payload["plan_digest"]})
            self.connection.execute("""INSERT INTO reconforge.supplier_return_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id,
                order_id,receipt_id,invoice_id,native_invoice_id,number,amount_minor,payload,audit_event_id,outbox_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                (self.tenant_id, payload["id"], payload["workspace_id"], payload["organization_id"], payload["legal_entity_id"], request.order_id,
                 request.receipt_id, request.invoice_id, payload["native_invoice_id"], request.number, payload["amount_minor"], canonical_json(payload), audit, outbox))
            self.connection.execute("UPDATE reconforge.procurement_partial_receipts SET supplier_return_owner_id=%s WHERE tenant_id=%s AND id=%s",
                                    (payload["id"], self.tenant_id, request.receipt_id))
            self.connection.execute("UPDATE reconforge.ap_supplier_invoices SET supplier_return_owner_id=%s WHERE tenant_id=%s AND id=%s",
                                    (payload["id"], self.tenant_id, payload["native_invoice_id"]))
            return self._remember(payload, "prepare", command_id, actor, digest, args)

    def _current(self, plan: Mapping[str, Any]) -> None:
        if self._source(plan["order_id"], plan["receipt_id"], plan["invoice_id"]) != plan["source_snapshot"]:
            raise FinancePostingError("supplier_return_source_changed", "Original receiving, AP accrual or invoice version changed.")

    def _request(self, plan: Mapping[str, Any], digest: str, reason: str) -> dict[str, Any]:
        if digest != plan["plan_digest"]:
            raise FinancePostingError("supplier_return_state_conflict", "Expected exact original source digest differs.")
        return {"plan_id": plan["id"], "expected_plan_digest": digest, "reason": exact_text(reason, maximum=500)}

    def _lifecycle(self, plan: Mapping[str, Any], operation: str, actor: PostingActor, reason: str, effects: list[str] | None = None) -> None:
        metadata = {"plan_digest": plan["plan_digest"], "reason": reason, "effects": effects or []}
        audit, outbox = self.owner._event(plan, "supplier_return_" + operation, actor, metadata)
        self.connection.execute("""INSERT INTO reconforge.supplier_return_events(tenant_id,plan_id,operation,actor_id,reason,effects,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""", (self.tenant_id, plan["id"], operation, actor.user_id, reason, canonical_json(effects or []), audit, outbox))
        self.connection.execute("UPDATE reconforge.supplier_return_plans SET phase=%s WHERE tenant_id=%s AND id=%s",
                                ({"review": 1, "post": 2, "cancel": 3}[operation], self.tenant_id, plan["id"]))

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "review", plan)
            args = self._request(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "review", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            self._actor(actor, "review", plan)
            if plan["phase"] != 0 or actor.user_id == plan["preparer_actor_id"]:
                raise FinancePostingError("supplier_return_review_denied", "Review requires an independent human and prepared original source.")
            self._current(plan)
            inverse = plan["inverse_plan"]
            self.receipts.review(inverse["plan_id"], command_id=platform_id("SRIRP", plan_id, "review"),
                                 expected_plan_digest=inverse["plan_digest"], reason=reason, actor=actor)
            for entry in sorted(plan["entries"], key=lambda item: item["entry_id"]):
                self.owner.finance.validate_entry(entry["entry_id"], reason=reason, actor_label=actor.username)
            self._lifecycle(plan, "review", actor, reason)
            return self._remember(plan, "review", command_id, actor, digest, args)

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "post", plan)
            args = self._request(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "post", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            self._actor(actor, "post", plan)
            if plan["phase"] != 1:
                raise FinancePostingError("supplier_return_post_denied", "Post requires the complete independent original source review.")
            reviewer = self._one("SELECT actor_id FROM reconforge.supplier_return_events WHERE tenant_id=%s AND plan_id=%s AND operation='review'", (self.tenant_id, plan_id))["actor_id"]
            if plan["phase"] != 1 or actor.user_id in {plan["preparer_actor_id"], reviewer}:
                raise FinancePostingError("supplier_return_post_denied", "Post requires the third independent human and complete review.")
            self._current(plan)
            review = self.receipts._review(self.receipts._plan(plan["inverse_plan"]["plan_id"]))
            if review is None:
                raise FinancePostingError("supplier_return_review_invalid", "Native inverse review is missing.")
            stock = self.receipts.commit(plan["inverse_plan"]["plan_id"], command_id=platform_id("SRIRP", plan_id, "post"),
                expected_review_digest=review["review_digest"], reason=reason, actor=actor)
            effects = [stock["finance_effect"]["id"]]
            for entry in plan["entries"]:
                self._participant = _SupplierReturnPostingParticipant(self, entry["entry_id"])
                try:
                    effect = self.owner.posting.post(entry["entry_id"], command_id=platform_id("SRGL", plan_id, command_id, len(effects)),
                        expected_validation_digest=entry["validation_digest"], reason=reason, actor=actor, _source_owner=self._participant)
                finally:
                    self._participant = None
                effects.append(effect["id"])
            self.connection.execute("""INSERT INTO reconforge.ap_supplier_invoice_credits(tenant_id,plan_id,supplier_invoice_id,amount_minor,
                original_accrual_effect_id,inverse_accrual_effect_id,inventory_inverse_effect_id) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, plan_id, plan["native_invoice_id"], plan["credit_minor"], plan["source_snapshot"]["accrual_effect"]["id"], effects[1], effects[0]))
            self.connection.execute("UPDATE reconforge.ap_supplier_invoices SET status='Credited',updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, plan["native_invoice_id"]))
            self._lifecycle(plan, "post", actor, reason, effects)
            return self._remember(plan, "post", command_id, actor, digest, args)

    def cancel(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "cancel", plan)
            args = self._request(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "cancel", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            self._actor(actor, "cancel", plan)
            reviewer = self.connection.execute("SELECT actor_id FROM reconforge.supplier_return_events WHERE tenant_id=%s AND plan_id=%s AND operation='review'", (self.tenant_id, plan_id)).fetchone()
            if plan["phase"] not in (0, 1) or actor.user_id in {plan["preparer_actor_id"], reviewer["actor_id"] if reviewer else None}:
                raise FinancePostingError("supplier_return_cancel_denied", "Cancellation requires independent authority and no posted effects.")
            self._lifecycle(plan, "cancel", actor, reason)
            self.connection.execute("UPDATE reconforge.procurement_partial_receipts SET supplier_return_owner_id=NULL WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan["receipt_id"]))
            self.connection.execute("UPDATE reconforge.ap_supplier_invoices SET supplier_return_owner_id=NULL WHERE tenant_id=%s AND id=%s", (self.tenant_id, plan["native_invoice_id"]))
            return self._remember(plan, "cancel", command_id, actor, digest, args)

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            self._actor(actor, "read", self._row(plan_id))
            self.connection.execute("SELECT reconforge.sr_close(%s,%s)", (self.tenant_id, plan_id))
            return self._view(plan_id)

    def list_plans(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            self.purchase._authorize(self.purchase._order(order_id), actor, "read")
            rows = self.connection.execute("SELECT id FROM reconforge.supplier_return_plans WHERE tenant_id=%s AND order_id=%s ORDER BY created_at DESC,id LIMIT 25", (self.tenant_id, order_id)).fetchall()
            return {"records": [self.get(row["id"], actor=actor) for row in rows]}
