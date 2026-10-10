"""Atomic original-source stock credits, FIFO restitution and partial refunds."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from reconforge.domain.customer_returns import CustomerRefundPreparation, CustomerReturnPreparation, credit_entitlement
from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.platform.common import platform_id
from reconforge.utils.time import utc_now_text


class _CustomerReturnPostingParticipant:
    def __init__(self, owner: PostgresCustomerReturnsRepository, entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


READ = frozenset({"sales.read", "receivables.read", "inventory.read", "finance_core.read"})
PERMISSIONS = {
    "prepare": READ | {"sales.manage", "receivables.manage", "inventory.valuation.manage", "finance_core.manage", "finance_core.reverse"},
    "review": READ | {"sales.approve", "inventory.valuation.approve", "finance_core.validate", "finance_core.reverse"},
    "post": READ | {"sales.manage", "receivables.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post", "finance_core.reverse"},
    "cancel": READ | {"sales.approve", "finance_core.validate"},
}


class PostgresCustomerReturnsRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self._participant: _CustomerReturnPostingParticipant | None = None

    def _one(self, query: str, parameters: tuple[Any, ...]) -> dict[str, Any]:
        rows = records(self.connection.execute(query, parameters))
        if not rows:
            raise FinancePostingError("customer_return_not_found", "Source is absent from the selected hierarchy.")
        return rows[0]

    def _actor(self, actor: PostingActor, operation: str, plan: Mapping[str, Any]) -> None:
        for permission in sorted(PERMISSIONS.get(operation, READ)):
            self.owner._actor(actor, permission, plan, mutation=operation != "read")
        if operation != "read":
            self.connection.execute("SELECT set_config('app.customer_return_actor_id',%s,true)", (actor.user_id,))

    def _row(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        query = ("SELECT payload,phase FROM reconforge.customer_return_plans WHERE tenant_id=%s AND id=%s FOR UPDATE"
                 if lock else "SELECT payload,phase FROM reconforge.customer_return_plans WHERE tenant_id=%s AND id=%s")
        row = self._one(query, (self.tenant_id, text(identifier, "plan_id")))
        return {**row["payload"], "phase": row["phase"]}

    def _source(self, identifier: str, *, lock: bool = True) -> dict[str, Any]:
        # Immutable identity lookup precedes every row lock, including retries.
        source = self._one("SELECT to_jsonb(s) value FROM reconforge.stock_sales_orders s WHERE tenant_id=%s AND id=%s",
                           (self.tenant_id, identifier))["value"]
        if lock:
            self.connection.execute("SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                    (self.tenant_id, source["customer_id"]))
            self.connection.execute("SELECT id FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                    (self.tenant_id, source["invoice_id"]))
            self.connection.execute("SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                    (self.tenant_id, identifier))
        current = self._one("SELECT reconforge.customer_return_source(%s,%s) value", (self.tenant_id, identifier))["value"]
        if current is None:
            raise FinancePostingError("customer_return_source_invalid", "Complete the source stock delivery and invoice before returning it.")
        return current

    def _locks(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        self.owner.posting._period(plan["period_id"], plan["workspace_id"], plan["posting_date"])
        source = self._source(str(plan["source_order_id"]))
        if plan["operation"] == "Refund":
            self._row(str(plan["return_id"]), lock=True)
        self._row(str(plan["id"]), lock=True)
        if plan["operation"] == "Return":
            stock = source["stock"]
            keys = [f"{stock['workspace_id']}|{stock['legal_entity_id']}|{stock['location_id']}|{stock['item_id']}|",
                    f"{stock['legal_entity_id']}|{stock['item_id']}|"]
            for key in sorted(keys):
                self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
            for layer_id in sorted({item["cost_layer_id"] for item in source["consumptions"]}):
                self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (layer_id,))
                self.connection.execute("SELECT id FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                        (self.tenant_id, layer_id))
        for entry in sorted(plan["entries"], key=lambda item: item["entry_id"]):
            self.connection.execute("SELECT id FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                    (self.tenant_id, entry["entry_id"]))
        return source

    def _command(self, plan: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command_id, "command_id", maximum=140)
        wire = {"operation": operation, "actor_id": actor.user_id, "request": dict(request)}
        digest = digest_payload(wire)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, plan["workspace_id"], "customer-returns", command_id]),))
        rows = records(self.connection.execute("""SELECT * FROM reconforge.customer_return_commands
            WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""", (self.tenant_id, plan["workspace_id"], command_id)))
        if not rows:
            return digest, None
        retained = rows[0]
        if (retained["operation"], retained["actor_id"], retained["request_digest"]) != (operation, actor.user_id, digest):
            raise FinancePostingError("customer_return_command_conflict", "Command identifies another exact request or actor.")
        self.connection.execute("SELECT reconforge.customer_return_close(%s,%s)", (self.tenant_id, retained["plan_id"]))
        return digest, retained["response_json"]

    def _remember(self, plan: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                  digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self._view(str(plan["id"]))
        self.connection.execute("""INSERT INTO reconforge.customer_return_commands
            (tenant_id,workspace_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""", (self.tenant_id, plan["workspace_id"], plan["id"],
            operation, command_id, actor.user_id, digest,
            canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        return result

    def _view(self, identifier: str) -> dict[str, Any]:
        return self._one("SELECT reconforge.customer_return_public(%s,%s) value", (self.tenant_id, identifier))["value"]

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "read", plan)
            self.connection.execute("SELECT reconforge.customer_return_close(%s,%s)", (self.tenant_id, plan_id))
            return self._view(plan_id)

    def list_plans(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            self._actor(actor, "read", scope)
            ids = records(self.connection.execute("""SELECT id FROM reconforge.customer_return_plans WHERE tenant_id=%s
                AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY id COLLATE "C" LIMIT 200""",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"])))
            return {"plans": [self.get(row["id"], actor=actor) for row in ids]}

    def balance(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "read", plan)
            if plan["operation"] != "Return" or plan["phase"] != 2:
                raise FinancePostingError("customer_return_refund_invalid", "Refund balance requires a posted original credit.")
            self.connection.execute("SELECT reconforge.customer_return_close(%s,%s)", (self.tenant_id, plan_id))
            due = self._one("SELECT reconforge.customer_return_refund_due(%s,%s) value", (self.tenant_id, plan_id))["value"]
            return {"return_id": plan_id, "plan_digest": plan["plan_digest"], "credit_minor": plan["credit_minor"],
                    "refund_entitlement_minor": plan["refund_entitlement_minor"], "refund_due_minor": due,
                    "refunded_minor": plan["refund_entitlement_minor"] - due}

    def _inverse(self, effect: Mapping[str, Any], identifier: str, args: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        snapshot = effect["snapshot_json"]
        original = snapshot["entry"]
        entry_id = platform_id("GLE", args["workspace_id"], identifier.upper())
        total = sum(line["credit_minor"] for line in snapshot["lines"])
        now = utc_now_text()
        self.connection.execute("""INSERT INTO reconforge.finance_entries
            (tenant_id,id,workspace_id,journal_id,organization_code,entity_code,period_id,entry_number,posting_date,
             description,external_reference,source_type,status,currency_code,total_debit_minor,total_credit_minor,
             created_by,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest,
             preparer_actor_id,reverses_posting_id,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Generated','Draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (self.tenant_id, entry_id, args["workspace_id"], original["journal_id"], args["organization_code"], args["entity_code"],
             args["period_id"], identifier.upper(), args["posting_date"], args["reason"], args["id"], original["currency_code"],
             total, total, actor.username, original["currency_precision"], original["currency_rounding_policy"],
             original["currency_registry_version"], original["currency_registry_digest"], actor.user_id, effect["id"], now, now))
        for line in snapshot["lines"]:
            line_id = platform_id("GLL", entry_id, line["line_number"])
            self.connection.execute("""INSERT INTO reconforge.finance_entry_lines
                (tenant_id,id,entry_id,line_number,account_id,description,debit_minor,credit_minor,currency_code)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, line_id, entry_id, line["line_number"],
                line["account_id"], line["description"], line["credit_minor"], line["debit_minor"], original["currency_code"]))
            for dimension, value in line["dimensions"].items():
                self.connection.execute("""INSERT INTO reconforge.finance_entry_line_dimensions
                    (tenant_id,entry_line_id,dimension_id,dimension_value_id) VALUES(%s,%s,%s,%s)""",
                    (self.tenant_id, line_id, dimension, value))
        frozen = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry_id))
        return {"entry_id": entry_id, "snapshot": frozen, "validation_digest": validation_digest(frozen),
                "original_effect_id": effect["id"]}

    def _cash_draft(self, identifier: str, args: Mapping[str, Any], amount: int, precision: int,
                    debit: str, credit: str, actor: PostingActor) -> dict[str, Any]:
        exact = exact_minor_text(amount, precision)
        entry = self.owner.finance.create_entry(entry_number=identifier.upper(), organization_code=args["organization_code"],
            entity_code=args["entity_code"], period_id=args["period_id"], journal_code=args["journal_code"],
            posting_date=args["posting_date"], description=args["reason"], external_reference=args["id"],
            workspace=args["workspace_id"], actor_label=actor.username,
            lines=[{"account_code": debit, "debit": exact}, {"account_code": credit, "credit": exact}])
        snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
        return {"entry_id": entry["id"], "snapshot": snapshot, "validation_digest": validation_digest(snapshot), "original_effect_id": None}

    def _save(self, payload: dict[str, Any], actor: PostingActor) -> dict[str, Any]:
        payload["preparer_actor_id"] = actor.user_id
        payload["plan_digest"] = digest_payload(payload)
        audit, outbox = self.owner._event(payload, "customer_return_prepared", actor, {"plan_digest": payload["plan_digest"]})
        self.connection.execute("""INSERT INTO reconforge.customer_return_plans
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_order_id,invoice_id,return_id,operation,amount_minor,
             payload,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
            (self.tenant_id, payload["id"], payload["workspace_id"], payload["organization_id"], payload["legal_entity_id"],
             payload["source_order_id"], payload["invoice_id"], payload.get("return_id"), payload["operation"], payload["amount_minor"],
             canonical_json(payload), audit, outbox))
        return payload

    def prepare(self, request: CustomerReturnPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            source = self._source(request.source_order_id, lock=False)
            governed = {**args, "amount_minor": source["stock"]["total_minor"], "currency_precision": source["invoice"]["currency_precision"]}
            self._actor(actor, "prepare", governed)
            digest, replay = self._command(args, "prepare", command_id, actor, args)
            if replay is not None:
                return replay
            self.owner.posting._period(request.period_id, request.workspace_id, request.posting_date)
            source = self._source(request.source_order_id)
            stock, invoice = source["stock"], source["invoice"]
            self.connection.execute("SELECT reconforge.customer_return_source_available(%s,%s)", (self.tenant_id, request.source_order_id))
            if any(stock[key] != args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                raise FinancePostingError("customer_return_scope_denied", "Original stock source is outside the selected hierarchy.")
            if request.posting_date < invoice["invoice_date"]:
                raise FinancePostingError("customer_return_date_invalid", "Return cannot precede original invoice.")
            entitlement = credit_entitlement(stock["total_minor"], source["allocated_minor"], source["cogs"]["snapshot_json"]["lines"][0]["debit_minor"])
            identifier = "CR1-" + uuid4().hex
            payload = {"schema_version": "customer-return-v1", "id": identifier, **args, "request": args, "operation": "Return",
                       "invoice_id": stock["invoice_id"], "source_snapshot": source,
                       "currency_code": invoice["currency_code"], "currency_precision": invoice["currency_precision"],
                       "amount_minor": entitlement["turnover_minor"], **entitlement,
                       "movement_id": platform_id("MOV", request.workspace_id, identifier.upper()),
                       "valuation_reversal_id": platform_id("IVR", request.workspace_id, identifier.upper())}
            self._actor(actor, "prepare", payload)
            self.connection.execute("SELECT reconforge.customer_return_accounts(%s,%s,%s,%s,%s)",
                (self.tenant_id, request.source_order_id, request.journal_code, request.refund_liability_account_code, request.cash_account_code))
            entries = [self._inverse(source["cogs"], identifier + "-C", payload, actor),
                       self._inverse(source["revenue"], identifier + "-R", payload, actor)]
            if source["allocated_minor"]:
                entries.append(self._cash_draft(identifier + "-L", payload, source["allocated_minor"], invoice["currency_precision"],
                    stock["invoice_parameters"]["receivable_account_code"], request.refund_liability_account_code, actor))
            payload["entries"] = entries
            self._save(payload, actor)
            self.connection.execute("UPDATE reconforge.ar_invoices SET customer_return_owner_id=%s WHERE tenant_id=%s AND id=%s",
                                    (identifier, self.tenant_id, stock["invoice_id"]))
            return self._remember(payload, "prepare", command_id, actor, digest, args)

    def prepare_refund(self, request: CustomerRefundPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            parent = self._row(request.return_id)
            self._actor(actor, "prepare", parent)
            digest, replay = self._command(parent, "prepare_refund", command_id, actor, args)
            if replay is not None:
                return replay
            self.owner.posting._period(request.period_id, parent["workspace_id"], request.posting_date)
            self._source(parent["source_order_id"])
            parent = self._row(request.return_id, lock=True)
            due = self._one("SELECT reconforge.customer_return_refund_due(%s,%s) amount", (self.tenant_id, request.return_id))["amount"]
            if parent["phase"] != 2 or request.amount_minor > due or request.posting_date < parent["posting_date"]:
                raise FinancePostingError("customer_return_refund_invalid", "Refund exceeds a posted original credit's current entitlement.")
            self.connection.execute("SELECT reconforge.customer_return_refund_available(%s,%s)", (self.tenant_id, request.return_id))
            identifier = "CRF1-" + uuid4().hex
            payload = {key: parent[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "organization_code",
                "entity_code", "source_order_id", "invoice_id", "journal_code", "refund_liability_account_code", "cash_account_code",
                "currency_code", "currency_precision")}
            payload.update(schema_version="customer-return-v1", id=identifier, operation="Refund", **args,
                           request=args, refunded_before_minor=parent["refund_entitlement_minor"] - due, parent_digest=parent["plan_digest"])
            # Read authority must cover the whole retained credit source as well as this installment.
            self._actor(actor, "prepare", payload)
            payload["entries"] = [self._cash_draft(identifier, payload, request.amount_minor, parent["currency_precision"],
                parent["refund_liability_account_code"], parent["cash_account_code"], actor)]
            self._save(payload, actor)
            return self._remember(payload, "prepare_refund", command_id, actor, digest, args)

    def _current(self, plan: Mapping[str, Any]) -> None:
        if plan["operation"] == "Return":
            if self._source(plan["source_order_id"], lock=False) != plan["source_snapshot"]:
                raise FinancePostingError("customer_return_source_changed", "Original source changed after exact credit preparation.")
        else:
            due = self._one("SELECT reconforge.customer_return_refund_due(%s,%s) amount", (self.tenant_id, plan["return_id"]))["amount"]
            parent = self._row(plan["return_id"])
            if (parent["phase"] != 2 or parent["plan_digest"] != plan["parent_digest"]
                    or parent["refund_entitlement_minor"] - due != plan["refunded_before_minor"] or plan["amount_minor"] > due):
                raise FinancePostingError("customer_return_source_changed", "Refund entitlement changed after preparation.")

    def _phase_request(self, plan: Mapping[str, Any], expected: str, reason: str) -> dict[str, Any]:
        if expected != plan["plan_digest"]:
            raise FinancePostingError("customer_return_state_conflict", "Expected original plan digest differs.")
        return {"plan_id": plan["id"], "expected_plan_digest": expected, "reason": text(reason, "reason", maximum=500)}

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "review", plan)
            args = self._phase_request(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "review", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            if plan["phase"] != 0 or actor.user_id == plan["preparer_actor_id"]:
                raise FinancePostingError("customer_return_review_denied", "Review requires an independent human and unreviewed source.")
            self._current(plan)
            for entry in sorted(plan["entries"], key=lambda item: item["entry_id"]):
                self.owner.finance.validate_entry(entry["entry_id"], reason=reason, actor_label=actor.username)
            self._lifecycle(plan, "review", actor, reason)
            return self._remember(plan, "review", command_id, actor, digest, args)

    def _lifecycle(self, plan: Mapping[str, Any], operation: str, actor: PostingActor, reason: str,
                   effects: list[str] | None = None) -> None:
        metadata = {"plan_digest": plan["plan_digest"], "reason": reason, "effects": effects or []}
        audit, outbox = self.owner._event(plan, "customer_return_" + operation, actor, metadata)
        self.connection.execute("""INSERT INTO reconforge.customer_return_events
            (tenant_id,plan_id,operation,actor_id,reason,effects,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""", (self.tenant_id, plan["id"], operation, actor.user_id,
            reason, canonical_json(effects or []), audit, outbox))
        self.connection.execute("UPDATE reconforge.customer_return_plans SET phase=%s WHERE tenant_id=%s AND id=%s",
                                ({"review": 1, "post": 2, "cancel": 3}[operation], self.tenant_id, plan["id"]))

    def _restore(self, plan: Mapping[str, Any], actor: PostingActor, reason: str) -> None:
        source, stock = plan["source_snapshot"], plan["source_snapshot"]["stock"]
        location = self._one("""SELECT l.location_code,w.warehouse_code FROM reconforge.inventory_locations l
            JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id WHERE l.tenant_id=%s AND l.id=%s""",
            (self.tenant_id, stock["location_id"]))
        inventory = PostgresInventoryCoreRepository(self.connection, self.tenant_id)
        maker = self._one("SELECT username FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s",
                          (self.tenant_id, plan["preparer_actor_id"]))["username"]
        movement = inventory.create_movement(movement_number=plan["id"].upper(), movement_type="Receipt",
            organization_code=plan["organization_code"], entity_code=plan["entity_code"], period_id=plan["period_id"],
            movement_date=plan["posting_date"], description=plan["reason"], source_reference=plan["id"], source_type="Generated",
            workspace=plan["workspace_id"], actor_label=maker, lines=[{"item_code": stock["source"]["item_code"],
                "quantity": stock["source"]["quantity"], "to_location": location["warehouse_code"] + "/" + location["location_code"]}])
        if movement["id"] != plan["movement_id"]:
            raise FinancePostingError("customer_return_evidence_invalid", "Original inverse movement identity differs.")
        inventory.post_movement(movement["id"], reason=reason, actor_label=actor.username)
        self.connection.execute("""INSERT INTO reconforge.inventory_valuation_reversals
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,original_valuation_document_id,
             reversal_movement_id,reversal_number,reversal_date,currency_code,created_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, plan["valuation_reversal_id"],
            plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"], plan["period_id"], stock["valuation_id"],
            movement["id"], plan["id"].upper(), plan["posting_date"], plan["currency_code"], maker))
        for consumption in source["consumptions"]:
            self.connection.execute("""INSERT INTO reconforge.inventory_valuation_reversal_effects
                (tenant_id,id,reversal_id,original_valuation_line_id,original_consumption_id,cost_layer_id,effect_type,quantity_scaled,value_minor)
                VALUES(%s,%s,%s,%s,%s,%s,'Restore',%s,%s)""", (self.tenant_id, platform_id("IVE", plan["id"], consumption["id"]),
                plan["valuation_reversal_id"], consumption["valuation_line_id"], consumption["id"], consumption["cost_layer_id"],
                consumption["quantity_scaled"], consumption["value_minor"]))
            self.connection.execute("""UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled+%s,
                remaining_value_minor=remaining_value_minor+%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
                (consumption["quantity_scaled"], consumption["value_minor"], self.tenant_id, consumption["cost_layer_id"]))
        self.connection.execute("""UPDATE reconforge.inventory_valuation_reversals SET status='Approved',total_value_minor=%s,
            finance_entry_id=%s,approved_by=%s,approved_at=now(),approval_reason=%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
            (plan["cogs_restored_minor"], plan["entries"][0]["entry_id"], actor.username, reason, self.tenant_id, plan["valuation_reversal_id"]))

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "post", plan)
            args = self._phase_request(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "post", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            reviewer = self._one("SELECT actor_id FROM reconforge.customer_return_events WHERE tenant_id=%s AND plan_id=%s AND operation='review'",
                                 (self.tenant_id, plan_id))["actor_id"]
            if plan["phase"] != 1 or actor.user_id in {plan["preparer_actor_id"], reviewer}:
                raise FinancePostingError("customer_return_post_denied", "Post requires a third independent human and complete review.")
            self._current(plan)
            if plan["operation"] == "Return":
                self._restore(plan, actor, reason)
            effects: list[str] = []
            for entry in plan["entries"]:
                self._participant = _CustomerReturnPostingParticipant(self, entry["entry_id"])
                try:
                    effect = self.owner.posting.post(entry["entry_id"], command_id="CR1:" + command_id + ":" + str(len(effects)),
                        expected_validation_digest=entry["validation_digest"], reason=reason, actor=actor, _source_owner=self._participant)
                finally:
                    self._participant = None
                effects.append(effect["id"])
            if plan["operation"] == "Return":
                self.connection.execute("""UPDATE reconforge.ar_invoices SET status='Cancelled',cancelled_by=%s,cancelled_at=now(),
                    cancel_reason=%s,updated_at=now(),row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
                    (actor.username, plan["id"], self.tenant_id, plan["invoice_id"]))
            self._lifecycle(plan, "post", actor, reason, effects)
            return self._remember(plan, "post", command_id, actor, digest, args)

    def cancel(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self._actor(actor, "cancel", plan)
            args = self._phase_request(plan, expected_plan_digest, reason)
            digest, replay = self._command(plan, "cancel", command_id, actor, args)
            if replay is not None:
                return replay
            self._locks(plan)
            plan = self._row(plan_id, lock=True)
            reviewers = records(self.connection.execute("SELECT actor_id FROM reconforge.customer_return_events WHERE tenant_id=%s AND plan_id=%s AND operation='review'",
                (self.tenant_id, plan_id)))
            if plan["phase"] not in (0, 1) or actor.user_id in {plan["preparer_actor_id"], *(row["actor_id"] for row in reviewers)}:
                raise FinancePostingError("customer_return_cancel_denied", "Cancellation requires independent authority over an unposted plan.")
            self._lifecycle(plan, "cancel", actor, reason)
            if plan["operation"] == "Return":
                self.connection.execute("UPDATE reconforge.ar_invoices SET customer_return_owner_id=NULL WHERE tenant_id=%s AND id=%s",
                                        (self.tenant_id, plan["invoice_id"]))
            return self._remember(plan, "cancel", command_id, actor, digest, args)
