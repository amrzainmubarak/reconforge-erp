"""One ACID source owner for reservations, FIFO issue, COGS, AR and cash."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json, digest_payload, text
from reconforge.domain.operational_finance import OperationalFinancePreparation
from reconforge.domain.sales_revenue import SalesInvoicePreparation, require_sales_monetary_affinity
from reconforge.domain.stock_sales import (
    STOCK_OPERATIONS,
    STOCK_STAGES,
    StockIssuePreparation,
    StockOrder,
    freeze_fifo,
    stock_code,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.infrastructure.postgres_sales_revenue import PostgresSalesRevenueRepository
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import minor_to_text, quantity_to_scaled

READ = frozenset({"sales.read", "inventory.read", "receivables.read", "finance_core.read"})
OPERATION_PERMISSIONS = {
    "create": READ | {"sales.manage"}, "submit": READ | {"sales.manage"}, "approve": READ | {"sales.approve"},
    "reserve": READ | {"sales.manage", "inventory.manage"},
    "prepare-issue": READ | {"sales.manage", "inventory.manage", "inventory.valuation.manage", "finance_core.manage"},
    "review-issue": READ | {"sales.approve", "inventory.valuation.approve", "finance_core.validate"},
    "deliver": READ | {"sales.manage", "inventory.post", "inventory.valuation.approve", "finance_core.post"},
    "prepare-invoice": READ | {"sales.manage", "receivables.manage", "finance_core.manage"},
    "review-invoice": READ | {"sales.approve", "receivables.approve", "finance_core.validate"},
    "invoice": READ | {"sales.manage", "receivables.approve", "finance_core.post"},
    "prepare-collection": READ | {"sales.manage", "finance_core.manage"},
    "review-collection": READ | {"sales.approve", "finance_core.validate"},
    "collect": READ | {"sales.manage", "receivables.manage", "finance_core.post"},
    "cancel": READ | {"sales.manage", "finance_core.manage"},
}


class PostgresStockSalesRepository:
    def __init__(self, connection: Any, tenant_id: str, *, workspace_id: str, organization_id: str,
                 legal_entity_id: str, organization_code: str, entity_code: str) -> None:
        self.connection, self.tenant_id = connection, validate_tenant_id(tenant_id)
        self.scope = {"workspace_id": workspace_id, "organization_id": organization_id, "legal_entity_id": legal_entity_id,
                      "organization_code": organization_code, "entity_code": entity_code}
        self.authority = PostgresSalesRevenueRepository(connection, tenant_id, **self.scope)
        self.inventory = PostgresInventoryCoreRepository(connection, tenant_id)
        self.finance = PostgresFinanceCoreRepository(connection, tenant_id)
        self.postings = PostgresFinancePostingRepository(connection, tenant_id)
        self.ops = PostgresOperationalFinanceRepository(connection, tenant_id)
        self.ar = PostgresReceivablesRepository(connection, tenant_id)

    def _one(self, sql: str, args: tuple[Any, ...]) -> dict[str, Any]:
        row = self.connection.execute(sql, args).fetchone()
        if row is None:
            raise FinancePostingError("stock_sales_source_missing", "Source is absent from the selected scope.")
        return dict(row)

    def _actor(self, actor: PostingActor, operation: str, row: Mapping[str, Any] | None = None) -> None:
        for permission in sorted(OPERATION_PERMISSIONS.get(operation, READ)):
            self.authority._actor(actor, permission, mutation=operation != "read",
                amount=row["total_minor"] if row else None, currency=row["currency_code"] if row else None)
        if operation != "read":
            self.connection.execute("SELECT set_config('app.stock_sales_actor_id',%s,true)", (actor.user_id,))

    def _order(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        args = (self.tenant_id, text(identifier, "stock order"), self.scope["workspace_id"],
                self.scope["organization_id"], self.scope["legal_entity_id"])
        if lock:
            return self._one("""SELECT * FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s
                AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s FOR UPDATE""", args)
        return self._one("""SELECT * FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND id=%s
            AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s""", args)

    def _view(self, identifier: str) -> dict[str, Any]:
        return self._one("SELECT reconforge.stock_sales_public(d) value FROM reconforge.stock_sales_orders d WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, identifier))["value"]

    def _close(self, identifier: str) -> None:
        self.connection.execute("SELECT reconforge.stock_sales_close(%s,%s)", (self.tenant_id, identifier))

    def _request(self, identifier: str, operation: str, parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        return {"id": identifier, "operation": operation, "scope": self.scope, "actor_id": actor.user_id, "payload": dict(parameters)}

    def _replay(self, command: str, request: Mapping[str, Any]) -> dict[str, Any] | None:
        text(command, "command identifier", maximum=100)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("stock-command:" + canonical_json([self.tenant_id, self.scope["workspace_id"], command]),))
        row = self.connection.execute("SELECT * FROM reconforge.stock_sales_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, self.scope["workspace_id"], command)).fetchone()
        if row is None:
            return None
        if row["request_digest"] != digest_payload(request) or row["request"] != request:
            raise FinancePostingError("stock_sales_replay_conflict", "Command identifier already belongs to a different exact request.")
        self._close(row["order_id"])
        return dict(row["result"])

    def _remember(self, row: Mapping[str, Any], command: str, request: Mapping[str, Any], reason: str, actor: PostingActor) -> dict[str, Any]:
        metadata = {"source_digest": row["source_digest"], "version": row["row_version"], "status": row["status"]}
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_label=actor.username,
            actor_user_id=actor.user_id, object_type="stock_sales", object_id=row["id"],
            action="stock_sales." + request["operation"], metadata=metadata)
        self.connection.execute("""INSERT INTO reconforge.stock_sales_events
            (tenant_id,order_id,version,actor_id,operation,reason,status,audit_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, row["id"], row["row_version"], actor.user_id,
            request["operation"], reason, row["status"], audit.id))
        result = self._view(row["id"])
        self.connection.execute("""INSERT INTO reconforge.stock_sales_commands
            (tenant_id,workspace_id,command_id,order_id,version,actor_id,operation,request_digest,request,result)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""", (self.tenant_id, self.scope["workspace_id"],
            command, row["id"], row["row_version"], actor.user_id, request["operation"], digest_payload(request),
            canonical_json(request), canonical_json(result)))
        self._close(row["id"])
        return result

    def create(self, request: StockOrder, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        payload = request.payload()
        identifier = platform_id("STSALE", self.scope["workspace_id"], payload["number"])
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._actor(actor, "create", payload)
            command = self._request(identifier, "create", payload, actor)
            replay = self._replay(command_id, command)
            if replay is not None:
                return replay
            masters = self._one("""SELECT i.id item_id,i.uom_id,u.decimal_places quantity_precision,l.id location_id,
                w.warehouse_code,c.id customer_id,e.currency_code
                FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
                JOIN reconforge.inventory_locations l ON l.tenant_id=i.tenant_id AND l.location_code=%s AND l.active AND NOT l.allow_negative
                JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id AND w.active AND w.warehouse_code=%s
                JOIN reconforge.legal_entities e ON e.tenant_id=w.tenant_id AND e.id=w.legal_entity_id AND e.active
                JOIN reconforge.ar_customers c ON c.tenant_id=e.tenant_id AND c.legal_entity_id=e.id AND c.status='Active' AND c.customer_code=%s
                WHERE i.tenant_id=%s AND i.workspace_id=%s AND i.item_code=%s AND i.active AND i.item_type<>'Service'
                AND i.tracking_mode='None' AND i.inventory_account_id IS NOT NULL AND u.active
                AND (i.organization_id IS NULL OR i.organization_id=%s) AND w.organization_id=%s
                AND w.legal_entity_id=%s AND c.workspace_id=i.workspace_id AND c.currency_code=%s""",
                (payload["location_code"], payload["warehouse_code"], payload["customer_code"], self.tenant_id, self.scope["workspace_id"], payload["item_code"],
                 self.scope["organization_id"], self.scope["organization_id"], self.scope["legal_entity_id"], payload["currency_code"]))
            if masters["currency_code"] != payload["currency_code"]:
                raise FinancePostingError("stock_sales_currency_invalid", "Stock sale uses the entity's functional currency.")
            quantity = quantity_to_scaled(payload["quantity"], masters["quantity_precision"], "Stock order quantity")
            payload["monetary_policy"] = self.ar.get_customer(masters["customer_id"])["monetary_policy"]
            payload["quantity_scaled"] = quantity
            self.connection.execute("""INSERT INTO reconforge.stock_sales_orders
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_id,item_id,uom_id,location_id,number,
                currency_code,quantity_scaled,quantity_precision,total_minor,source,source_digest,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                (self.tenant_id, identifier, self.scope["workspace_id"], self.scope["organization_id"], self.scope["legal_entity_id"],
                 masters["customer_id"], masters["item_id"], masters["uom_id"], masters["location_id"], payload["number"],
                 payload["currency_code"], quantity, masters["quantity_precision"], payload["total_minor"], canonical_json(payload), digest_payload(payload), actor.user_id))
            return self._remember(self._order(identifier), command_id, command, "Create product sales order", actor)

    def _stock_lock(self, row: Mapping[str, Any]) -> None:
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"{row['workspace_id']}|{row['legal_entity_id']}|{row['location_id']}|{row['item_id']}|",))

    def _fifo_lock(self, row: Mapping[str, Any]) -> None:
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"{row['legal_entity_id']}|{row['item_id']}|",))

    def _prepare_issue(self, row: Mapping[str, Any], parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        request = StockIssuePreparation(**dict(parameters)).payload()
        if request["posting_date"] < row["source"]["order_date"]:
            raise FinancePostingError("stock_sales_date_invalid", "Delivery cannot precede the order.")
        self._stock_lock(row)
        self._fifo_lock(row)
        if self.connection.execute("SELECT 1 FROM reconforge.stock_sales_issue_claims WHERE tenant_id=%s AND workspace_id=%s AND legal_entity_id=%s AND item_id=%s AND state='Active'",
            (self.tenant_id, row["workspace_id"], row["legal_entity_id"], row["item_id"])).fetchone():
            raise FinancePostingError("stock_sales_fifo_claim_conflict", "Another reviewed issue currently owns this FIFO item; complete it first.")
        policy = self._one("""SELECT p.*,j.journal_code,j.active journal_active,a.account_code cogs_code,b.account_code stock_code,
            i.inventory_account_id FROM reconforge.inventory_valuation_policies p
            JOIN reconforge.finance_journals j ON j.tenant_id=p.tenant_id AND j.id=p.finance_journal_id
            JOIN reconforge.inventory_items i ON i.tenant_id=p.tenant_id AND i.id=%s
            JOIN reconforge.finance_accounts a ON a.tenant_id=p.tenant_id AND a.id=p.cogs_account_id
            JOIN reconforge.finance_accounts b ON b.tenant_id=i.tenant_id AND b.id=i.inventory_account_id
            WHERE p.tenant_id=%s AND p.workspace_id=%s AND p.organization_id=%s AND p.legal_entity_id=%s
            AND p.policy_code=%s AND p.active AND p.currency_code=%s AND a.active AND a.allow_posting AND a.allow_manual_posting
            AND b.active AND b.allow_posting AND b.allow_manual_posting AND a.account_type='Expense' AND b.account_type='Asset'""",
            (row["item_id"], self.tenant_id, row["workspace_id"], row["organization_id"], row["legal_entity_id"], request["policy_code"], row["currency_code"]))
        layers = [dict(value) for value in self.connection.execute("""SELECT l.*,d.currency_precision,d.currency_rounding_policy,
            d.currency_registry_version,d.currency_registry_digest FROM reconforge.inventory_cost_layers l
            JOIN reconforge.inventory_valuation_lines v ON v.tenant_id=l.tenant_id AND v.id=l.source_valuation_line_id
            JOIN reconforge.inventory_valuation_documents d ON d.tenant_id=v.tenant_id AND d.id=v.valuation_document_id
            WHERE l.tenant_id=%s AND l.workspace_id=%s AND l.legal_entity_id=%s AND l.item_id=%s
            AND l.inventory_lot_id IS NULL AND l.remaining_quantity_scaled>0 AND d.status='Approved'
            ORDER BY l.created_at,l.id FOR UPDATE OF l""", (self.tenant_id, row["workspace_id"], row["legal_entity_id"], row["item_id"])).fetchall()]
        quoted = row["source"]["monetary_policy"]
        currency_policy, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry({"currency_code": quoted["currency_code"],
            "currency_precision": quoted["precision"], "currency_rounding_policy": quoted["rounding_policy"],
            "currency_registry_version": quoted["registry_version"], "currency_registry_digest": quoted["registry_digest"]})
        for layer in layers:
            source_policy, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(layer)
            currency_policy.require_compatible(source_policy)
            if layer["uom_id"] != row["uom_id"] or layer["quantity_precision"] != row["quantity_precision"]:
                raise FinancePostingError("stock_sales_fifo_invalid", "Layer quantity interpretation differs from the order.")
        allocations, total = freeze_fifo(layers, row["quantity_scaled"])
        self._actor(actor, "prepare-issue", {**row, "total_minor": total})
        number = "SS1-" + digest_payload([self.tenant_id, row["id"]])[:32].upper()
        entry_id = platform_id("GLE", row["workspace_id"], number)
        plan = {"schema_version": "stock-sales-issue-v1", "preparer_actor_id": actor.user_id, "preparer_username": actor.username,
            "source_digest": row["source_digest"], "request": request, "allocations": allocations, "total_cost_minor": total,
            "policy_id": policy["id"], "inventory_account_id": policy["inventory_account_id"], "cogs_account_id": policy["cogs_account_id"],
            "entry_id": entry_id, "entry_number": number, "journal_id": policy["finance_journal_id"],
            "currency_policy": asdict(currency_policy)}
        self.connection.execute("""INSERT INTO reconforge.stock_sales_issue_claims
            (tenant_id,order_id,workspace_id,legal_entity_id,item_id,entry_id,payload,plan_digest)
            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""", (self.tenant_id, row["id"], row["workspace_id"], row["legal_entity_id"],
                row["item_id"], entry_id, canonical_json(plan), digest_payload(plan)))
        precision = currency_policy.precision
        entry = self.finance.create_entry(entry_number=number, organization_code=self.scope["organization_code"],
            entity_code=self.scope["entity_code"], period_id=request["period_id"], journal_code=policy["journal_code"],
            posting_date=request["posting_date"], description="Reviewed FIFO COGS for " + row["number"],
            external_reference=row["id"], workspace=row["workspace_id"], actor_label=actor.username,
            lines=[{"account_code": policy["cogs_code"], "debit": minor_to_text(total, precision)},
                   {"account_code": policy["stock_code"], "credit": minor_to_text(total, precision)}])
        return {"issue_plan": plan, "cogs_entry_id": entry["id"]}

    def _deliver(self, row: Mapping[str, Any], actor: PostingActor, command: str, reason: str) -> dict[str, Any]:
        self._stock_lock(row)
        self._fifo_lock(row)
        plan = row["issue_plan"]
        request = plan["request"]
        for allocation in plan["allocations"]:
            layer = self._one("SELECT * FROM reconforge.inventory_cost_layers WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, allocation["cost_layer_id"]))
            if any(layer[key] != allocation[key] for key in ("row_version", "remaining_quantity_scaled", "remaining_value_minor")):
                raise FinancePostingError("stock_sales_fifo_changed", "Frozen FIFO residual changed; retained issue cannot be re-costed.")
        location = self._one("""SELECT l.location_code,w.warehouse_code FROM reconforge.inventory_locations l
            JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id WHERE l.tenant_id=%s AND l.id=%s""",
            (self.tenant_id, row["location_id"]))
        movement = self.inventory.create_movement(movement_number=plan["entry_number"], movement_type="Delivery",
            organization_code=self.scope["organization_code"], entity_code=self.scope["entity_code"], period_id=request["period_id"],
            movement_date=request["posting_date"], description=reason, source_reference=row["id"], source_type="Generated",
            workspace=row["workspace_id"], actor_label=plan["preparer_username"],
            lines=[{"item_code": row["source"]["item_code"], "quantity": row["source"]["quantity"],
                    "from_location": location["warehouse_code"] + "/" + location["location_code"]}])
        self.inventory.post_movement(movement["id"], reason=reason, actor_label=actor.username)
        valuation_id = platform_id("STVAL", row["id"])
        policy = plan["currency_policy"]
        self.connection.execute("""INSERT INTO reconforge.inventory_valuation_documents
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,movement_id,policy_id,valuation_number,
             valuation_date,currency_code,created_by,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, valuation_id,
            row["workspace_id"], row["organization_id"], row["legal_entity_id"], request["period_id"], movement["id"], plan["policy_id"],
            plan["entry_number"], request["posting_date"], row["currency_code"], plan["preparer_username"],
            policy["precision"], policy["rounding_policy"], policy["registry_version"], policy["registry_digest"]))
        line_id = platform_id("STVL", row["id"])
        self.connection.execute("""INSERT INTO reconforge.inventory_valuation_lines
            (tenant_id,id,valuation_document_id,movement_line_id,line_number,flow_direction,item_id,uom_id,quantity_scaled,
             quantity_precision,value_minor,inventory_account_id,offset_account_id) VALUES(%s,%s,%s,%s,1,'Outbound',%s,%s,%s,%s,%s,%s,%s)""",
            (self.tenant_id, line_id, valuation_id, movement["lines"][0]["id"], row["item_id"], row["uom_id"],
             row["quantity_scaled"], row["quantity_precision"], plan["total_cost_minor"], plan["inventory_account_id"], plan["cogs_account_id"]))
        for allocation in plan["allocations"]:
            self.connection.execute("""INSERT INTO reconforge.inventory_layer_consumptions
                (tenant_id,id,workspace_id,valuation_line_id,cost_layer_id,quantity_scaled,value_minor) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, platform_id("STCON", line_id, allocation["cost_layer_id"]), row["workspace_id"], line_id,
                 allocation["cost_layer_id"], allocation["quantity_scaled"], allocation["value_minor"]))
            self.connection.execute("""UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=remaining_quantity_scaled-%s,
                remaining_value_minor=remaining_value_minor-%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
                (allocation["quantity_scaled"], allocation["value_minor"], self.tenant_id, allocation["cost_layer_id"]))
        self.connection.execute("""UPDATE reconforge.inventory_valuation_documents SET status='Approved',total_value_minor=%s,
            finance_entry_id=%s,approved_by=%s,approved_at=now(),approval_reason=%s,row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
            (plan["total_cost_minor"], row["cogs_entry_id"], actor.username, reason, self.tenant_id, valuation_id))
        entry = self._one("SELECT validation_digest FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s",
                          (self.tenant_id, row["cogs_entry_id"]))
        effect = self.postings.post(row["cogs_entry_id"], command_id="stock-issue:" + command,
            expected_validation_digest=entry["validation_digest"], reason=reason, actor=actor)
        self.connection.execute("UPDATE reconforge.stock_sales_reservations SET state='Consumed' WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, row["id"]))
        self.connection.execute("UPDATE reconforge.stock_sales_issue_claims SET state='Consumed' WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, row["id"]))
        return {"movement_id": movement["id"], "valuation_id": valuation_id, "cogs_effect_id": effect["id"]}

    def act(self, identifier: str, operation: str, *, expected_version: int, command_id: str, reason: str,
            parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        if operation not in OPERATION_PERMISSIONS or operation == "create" or type(expected_version) is not int or expected_version < 1:
            raise FinancePostingError("stock_sales_command_invalid", "Supported operation and exact positive version are required.")
        reason = text(reason, "reason", maximum=500)
        if operation not in {"prepare-issue", "prepare-invoice", "prepare-collection"} and parameters:
            raise FinancePostingError("stock_sales_command_invalid", "This transition accepts no participant parameters.")
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            row = self._order(identifier)
            self._actor(actor, operation, row)
            request = self._request(identifier, operation, {"expected_version": expected_version, "reason": reason, **dict(parameters)}, actor)
            replay = self._replay(command_id, request)
            if replay is not None:
                return replay
            row = self._order(identifier, lock=True)
            if row["row_version"] != expected_version or row["status"] not in STOCK_STAGES:
                raise FinancePostingError("stock_sales_version_conflict", "Order changed; reload before proceeding.")
            stage = STOCK_STAGES.index(row["status"])
            if operation != "cancel" and (stage >= len(STOCK_OPERATIONS) or STOCK_OPERATIONS[stage] != operation):
                raise FinancePostingError("stock_sales_state_invalid", "Only the next complete owner operation is allowed.")
            changes: dict[str, Any] = {"status": STOCK_STAGES[stage + 1] if operation != "cancel" else "Cancelled"}
            if operation == "approve":
                if row["created_by"] == actor.user_id:
                    raise FinancePostingError("stock_sales_sod_denied", "Creator cannot approve their product order.")
                changes["approved_by"] = actor.user_id
            elif operation == "reserve":
                self._stock_lock(row)
                self.connection.execute("""INSERT INTO reconforge.stock_sales_reservations
                    (tenant_id,order_id,workspace_id,organization_id,legal_entity_id,location_id,item_id,quantity_scaled)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""", (self.tenant_id, row["id"], row["workspace_id"],
                    row["organization_id"], row["legal_entity_id"], row["location_id"], row["item_id"], row["quantity_scaled"]))
            elif operation == "prepare-issue":
                changes.update(self._prepare_issue(row, {**dict(parameters), "reason": reason}, actor))
            elif operation == "review-issue":
                if row["issue_plan"]["preparer_actor_id"] == actor.user_id:
                    raise FinancePostingError("stock_sales_sod_denied", "Issue preparer cannot review their own COGS.")
                self._actor(actor, operation, {**row, "total_minor": row["issue_plan"]["total_cost_minor"]})
                self.finance.validate_entry(row["cogs_entry_id"], reason=reason, actor_label=actor.username)
                changes["issue_reviewer_id"] = actor.user_id
            elif operation == "deliver":
                self._actor(actor, operation, {**row, "total_minor": row["issue_plan"]["total_cost_minor"]})
                changes.update(self._deliver(row, actor, command_id, reason))
            elif operation == "cancel":
                if stage >= STOCK_STAGES.index("Delivered"):
                    raise FinancePostingError("stock_sales_state_invalid", "Financially delivered orders require a complete inverse, outside this cycle.")
                self._stock_lock(row)
                self._fifo_lock(row)
                if row["cogs_entry_id"]:
                    self.finance.void_entry(row["cogs_entry_id"], reason=reason, actor_label=actor.username)
                self.connection.execute("UPDATE reconforge.stock_sales_reservations SET state='Released' WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, row["id"]))
                self.connection.execute("UPDATE reconforge.stock_sales_issue_claims SET state='Released' WHERE tenant_id=%s AND order_id=%s", (self.tenant_id, row["id"]))
            elif operation != "submit":
                changes.update(self._revenue(row, operation, parameters, actor, command_id, reason))
            self._advance(row, changes)
            return self._remember(self._order(identifier), command_id, request, reason, actor)

    def _advance(self, row: Mapping[str, Any], changes: Mapping[str, Any]) -> None:
        from psycopg import sql
        allowed = {"status", "approved_by", "issue_plan", "cogs_entry_id", "issue_reviewer_id", "movement_id", "valuation_id",
                   "cogs_effect_id", "invoice_id", "invoice_plan_id", "invoice_parameters", "collection_plan_id", "collection_parameters", "receipt_id"}
        if not set(changes) <= allowed:
            raise FinancePostingError("stock_sales_link_invalid", "Unexpected participant output.")
        assignments = [sql.SQL("{}={}").format(sql.Identifier(key), sql.Placeholder() if key not in
            {"issue_plan", "invoice_parameters", "collection_parameters"} else sql.SQL("%s::jsonb")) for key in changes]
        statement = sql.SQL("UPDATE reconforge.stock_sales_orders SET {},row_version=row_version+1,updated_at=now() WHERE tenant_id=%s AND id=%s").format(sql.SQL(",").join(assignments))
        values = [canonical_json(value) if isinstance(value, Mapping) else value for value in changes.values()]
        self.connection.execute(statement, (*values, self.tenant_id, row["id"]))

    def _revenue(self, row: Mapping[str, Any], operation: str, parameters: Mapping[str, Any], actor: PostingActor,
                 command: str, reason: str) -> dict[str, Any]:
        source = row["source"]
        if operation == "prepare-invoice":
            values = SalesInvoicePreparation(**dict(parameters), reason=reason).payload()
            if values["invoice_date"] < row["issue_plan"]["request"]["posting_date"]:
                raise FinancePostingError("stock_sales_date_invalid", "Invoice cannot precede actual product delivery.")
            invoice = self.ar.create_invoice(invoice_number=values["invoice_number"], customer_code=source["customer_code"],
                invoice_date=values["invoice_date"], due_date=values["due_date"], currency_code=row["currency_code"], tax_minor=0,
                workspace=row["workspace_id"], organization_code=self.scope["organization_code"], entity_code=self.scope["entity_code"],
                idempotency_key="stock-sale:" + row["id"], actor_label=actor.username,
                lines=[ReceivableInvoiceLineInput(description=source["description"], quantity=source["quantity"],
                    unit_price_minor=source["net_unit_price_minor"], line_total_minor=row["total_minor"])])
            require_sales_monetary_affinity(source["monetary_policy"], invoice["monetary_policy"])
            self.ar.submit_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            plan = self.ops.prepare(OperationalFinancePreparation(**self.scope, source_kind="ARInvoice", source_id=invoice["id"],
                journal_code=values["journal_code"], period_id=values["period_id"], posting_date=values["invoice_date"],
                debit_account_code=values["receivable_account_code"], credit_account_code=values["revenue_account_code"], reason=reason),
                command_id="stock-invoice:" + command, actor=actor)
            return {"invoice_id": invoice["id"], "invoice_plan_id": plan["id"], "invoice_parameters": values}
        if operation == "prepare-collection":
            values = {key: text(value, key) for key, value in parameters.items()}
            if set(values) != {"receipt_number", "receipt_date", "journal_code", "period_id", "cash_account_code"}:
                raise FinancePostingError("stock_sales_command_invalid", "Complete closed collection parameters are required.")
            values["receipt_number"] = stock_code(values["receipt_number"], "receipt number")
            self.connection.execute("SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s FOR UPDATE", (self.tenant_id, row["customer_id"]))
            self.connection.execute("SELECT reconforge.sales_receipt_name_claim(%s,%s,%s,'StockSales',%s)",
                (self.tenant_id, row["workspace_id"], values["receipt_number"], row["id"]))
            plan = self.ops.prepare(OperationalFinancePreparation(**self.scope, source_kind="ARReceipt", source_id=row["invoice_id"],
                journal_code=values["journal_code"], period_id=values["period_id"], posting_date=values["receipt_date"],
                debit_account_code=values["cash_account_code"], credit_account_code=row["invoice_parameters"]["receivable_account_code"], reason=reason),
                command_id="stock-cash:" + command, actor=actor)
            return {"collection_plan_id": plan["id"], "collection_parameters": values}
        field = "collection_plan_id" if operation in ("review-collection", "collect") else "invoice_plan_id"
        plan = self.ops.get(row[field], actor=actor)
        if operation in ("review-invoice", "review-collection"):
            if operation == "review-invoice":
                invoice = self.ar.get_invoice(row["invoice_id"])
                self.ar.approve_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            self.ops.review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="stock-review:" + command, reason=reason, actor=actor)
            return {}
        if operation == "invoice":
            self.ops.post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="stock-revenue:" + command, reason=reason, actor=actor)
            return {}
        values = row["collection_parameters"]
        receipt = self.ar.post_receipt(receipt_number=values["receipt_number"], customer_code=source["customer_code"],
            receipt_date=values["receipt_date"], currency_code=row["currency_code"], amount_minor=row["total_minor"],
            allocations=[ReceiptAllocationInput(invoice_id=row["invoice_id"], amount_minor=row["total_minor"])],
            workspace=row["workspace_id"], organization_code=self.scope["organization_code"], entity_code=self.scope["entity_code"],
            idempotency_key="stock-collection:" + row["id"], actor_label=actor.username)
        require_sales_monetary_affinity(source["monetary_policy"], receipt["monetary_policy"])
        self.ops.post(plan["id"], expected_plan_digest=plan["plan_digest"], source_effect_id=receipt["id"],
            command_id="stock-settle:" + command, reason=reason, actor=actor)
        return {"receipt_id": receipt["id"]}

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._actor(actor, "read", self._order(identifier))
            self._close(identifier)
            return self._view(identifier)

    def list(self, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._actor(actor, "read")
            rows = self.connection.execute("""SELECT id FROM reconforge.stock_sales_orders WHERE tenant_id=%s
                AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s ORDER BY id COLLATE "C" LIMIT 100""",
                (self.tenant_id, self.scope["workspace_id"], self.scope["organization_id"], self.scope["legal_entity_id"])).fetchall()
            return {"orders": [self.get(row["id"], actor=actor) for row in rows]}

    def options(self, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._actor(actor, "read")
            options = self.authority.options(actor=actor)
            options["items"] = [dict(row) for row in self.connection.execute("""SELECT i.item_code,i.name,u.uom_code,u.decimal_places
                FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
                WHERE i.tenant_id=%s AND i.workspace_id=%s AND(i.organization_id IS NULL OR i.organization_id=%s)
                AND i.active AND u.active AND i.item_type<>'Service' AND i.tracking_mode='None' AND i.inventory_account_id IS NOT NULL
                ORDER BY i.item_code COLLATE "C" LIMIT 100""", (self.tenant_id, self.scope["workspace_id"], self.scope["organization_id"])).fetchall()]
            options["warehouses"] = [dict(row) for row in self.connection.execute("""SELECT warehouse_code,name FROM reconforge.inventory_warehouses
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND active
                ORDER BY warehouse_code COLLATE "C" LIMIT 100""", (self.tenant_id, self.scope["workspace_id"], self.scope["organization_id"], self.scope["legal_entity_id"])).fetchall()]
            options["locations"] = [dict(row) for row in self.connection.execute("""SELECT w.warehouse_code,l.location_code,l.name
                FROM reconforge.inventory_locations l JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id
                WHERE l.tenant_id=%s AND l.workspace_id=%s AND w.organization_id=%s AND w.legal_entity_id=%s AND w.active AND l.active AND NOT l.allow_negative
                ORDER BY w.warehouse_code COLLATE "C",l.location_code COLLATE "C" LIMIT 200""", (self.tenant_id, self.scope["workspace_id"], self.scope["organization_id"], self.scope["legal_entity_id"])).fetchall()]
            options["policies"] = [dict(row) for row in self.connection.execute("""SELECT p.policy_code,p.policy_code name,j.journal_code
                FROM reconforge.inventory_valuation_policies p JOIN reconforge.finance_journals j ON j.tenant_id=p.tenant_id AND j.id=p.finance_journal_id
                WHERE p.tenant_id=%s AND p.workspace_id=%s AND p.organization_id=%s AND p.legal_entity_id=%s AND p.active AND j.active
                ORDER BY p.policy_code COLLATE "C" LIMIT 100""", (self.tenant_id, self.scope["workspace_id"], self.scope["organization_id"], self.scope["legal_entity_id"])).fetchall()]
            return options
