"""Atomic commercial parent over reusable native stock-to-cash tranches."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json, digest_payload, text
from reconforge.domain.stock_commerce import CommercialOrder
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.infrastructure.postgres_stock_sales import OPERATION_PERMISSIONS, PostgresStockSalesRepository
from reconforge.platform.common import platform_id
from reconforge.platform.inventory_values import quantity_to_scaled

COMMERCE_PERMISSIONS = {**OPERATION_PERMISSIONS, "open-tranche": OPERATION_PERMISSIONS["create"],
    "approve-tranche": OPERATION_PERMISSIONS["approve"] | OPERATION_PERMISSIONS["reserve"]}


def _child_command(command: str, operation: str) -> str:
    return "commerce-native:" + digest_payload([command, operation])


class PostgresStockCommerceRepository:
    def __init__(self, connection: Any, tenant_id: str, **scope: str) -> None:
        self.native = PostgresStockSalesRepository(connection, tenant_id, **scope)
        self.connection, self.tenant_id, self.scope = connection, self.native.tenant_id, self.native.scope

    def _row(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        statement = """SELECT * FROM reconforge.stock_commerce_orders WHERE tenant_id=%s AND id=%s
            AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s"""
        if lock:
            statement += " FOR UPDATE"
        return self.native._one(statement, (self.tenant_id, text(identifier, "commercial order"),
            self.scope["workspace_id"], self.scope["organization_id"], self.scope["legal_entity_id"]))

    def _authority(self, actor: PostingActor, operation: str, row: Mapping[str, Any] | None = None) -> None:
        for permission in sorted(COMMERCE_PERMISSIONS.get(operation, OPERATION_PERMISSIONS["create"] if operation == "create" else OPERATION_PERMISSIONS["submit"])):
            self.native.authority._actor(actor, permission, mutation=operation != "read",
                amount=row["total_minor"] if row else None, currency=row["currency_code"] if row else None)
        self.connection.execute("SELECT set_config('app.stock_commerce_actor_id',%s,true)", (actor.user_id,))
        self.connection.execute("SELECT set_config('app.stock_commerce_operation',%s,true)", (operation,))

    def _snapshot(self, identifier: str) -> dict[str, Any]:
        return self.native._one("SELECT reconforge.stock_commerce_public(d) value FROM reconforge.stock_commerce_orders d WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, identifier))["value"]

    def _request(self, identifier: str, operation: str, payload: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        return {"id": identifier, "operation": operation, "scope": self.scope, "actor_id": actor.user_id, "payload": dict(payload)}

    def _replay(self, command_id: str, request: Mapping[str, Any]) -> dict[str, Any] | None:
        text(command_id, "command identifier", maximum=100)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json(["commerce-command", self.tenant_id, self.scope["workspace_id"], command_id]),))
        command = self.connection.execute("SELECT request_digest,request,result FROM reconforge.stock_commerce_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, self.scope["workspace_id"], command_id)).fetchone()
        if command is None:
            return None
        if command["request_digest"] != digest_payload(request) or command["request"] != request:
            raise FinancePostingError("commerce_replay_conflict", "Command identifier belongs to a different commercial request.")
        self.connection.execute("SELECT reconforge.stock_commerce_close(%s,%s)", (self.tenant_id, request["id"]))
        return dict(command["result"])

    def _remember(self, identifier: str, command_id: str, request: Mapping[str, Any], reason: str, actor: PostingActor) -> dict[str, Any]:
        row = self._row(identifier)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_label=actor.username,
            actor_user_id=actor.user_id, object_type="stock_commerce", object_id=identifier,
            action="stock_commerce." + str(request["operation"]), metadata={"source_digest": row["source_digest"], "version": row["row_version"]})
        result = self.native._one("SELECT reconforge.stock_commerce_ack(d) value FROM reconforge.stock_commerce_orders d WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, identifier))["value"]
        self.connection.execute("""INSERT INTO reconforge.stock_commerce_commands
            (tenant_id,workspace_id,command_id,order_id,version,actor_id,operation,reason,request_digest,request,result,result_digest,audit_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)""",
            (self.tenant_id, self.scope["workspace_id"], command_id, identifier, row["row_version"], actor.user_id,
            request["operation"], reason, digest_payload(request), canonical_json(request), canonical_json(result), digest_payload(result), audit.id))
        self.connection.execute("SELECT reconforge.stock_commerce_close(%s,%s)", (self.tenant_id, identifier))
        return result

    def create(self, order: CommercialOrder, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        payload = order.payload()
        identifier = platform_id("COMSALE", self.scope["workspace_id"], payload["header"]["number"])
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._authority(actor, "create", payload["header"])
            request = self._request(identifier, "create", payload, actor)
            replay = self._replay(command_id, request)
            if replay is not None:
                return replay
            lines: list[dict[str, Any]] = []
            for ordinal, source in enumerate(payload["lines"], 1):
                master = self.native._one("""SELECT i.id item_id,i.uom_id,u.decimal_places quantity_precision,l.id location_id,
                    c.id customer_id,e.currency_code FROM reconforge.inventory_items i
                    JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id AND u.active
                    JOIN reconforge.inventory_locations l ON l.tenant_id=i.tenant_id AND l.location_code=%s AND l.active AND NOT l.allow_negative
                    JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id AND w.warehouse_code=%s AND w.active
                    JOIN reconforge.legal_entities e ON e.tenant_id=w.tenant_id AND e.id=w.legal_entity_id AND e.active
                    JOIN reconforge.ar_customers c ON c.tenant_id=e.tenant_id AND c.legal_entity_id=e.id AND c.workspace_id=i.workspace_id
                    AND c.customer_code=%s AND c.status='Active' AND c.currency_code=%s
                    WHERE i.tenant_id=%s AND i.workspace_id=%s AND i.item_code=%s AND i.active AND i.tracking_mode='None'
                    AND i.item_type<>'Service' AND i.inventory_account_id IS NOT NULL AND(i.organization_id IS NULL OR i.organization_id=%s)
                    AND w.workspace_id=i.workspace_id AND w.organization_id=%s AND w.legal_entity_id=%s""",
                    (source["location_code"], source["warehouse_code"], source["customer_code"], source["currency_code"],
                    self.tenant_id, self.scope["workspace_id"], source["item_code"], self.scope["organization_id"],
                    self.scope["organization_id"], self.scope["legal_entity_id"]))
                if master["currency_code"] != source["currency_code"]:
                    raise FinancePostingError("commerce_currency_invalid", "Commercial order requires functional currency.")
                quantity = quantity_to_scaled(source["quantity"], master["quantity_precision"], "commercial quantity")
                if quantity * source["net_unit_price_minor"] % (10 ** master["quantity_precision"]):
                    raise FinancePostingError("commerce_precision_invalid", "Commercial quantities must have exact additive minor-unit value.")
                source = {**source, "quantity_scaled": quantity,
                    "monetary_policy": self.native.ar.get_customer(master["customer_id"])["monetary_policy"]}
                lines.append({"ordinal": ordinal, "source": source, "master": master})
            seal = {"header": payload["header"], "lines": [line["source"] for line in lines]}
            customer_id = lines[0]["master"]["customer_id"]
            self.connection.execute("""INSERT INTO reconforge.stock_commerce_orders
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_id,number,currency_code,total_minor,line_count,source,source_digest,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                (self.tenant_id, identifier, self.scope["workspace_id"], self.scope["organization_id"], self.scope["legal_entity_id"],
                customer_id, payload["header"]["number"], payload["header"]["currency_code"], payload["header"]["total_minor"],
                len(lines), canonical_json(payload["header"]), digest_payload(seal), actor.user_id))
            for line in lines:
                source, master = line["source"], line["master"]
                self.connection.execute("""INSERT INTO reconforge.stock_commerce_lines
                    (tenant_id,order_id,line_number,item_id,uom_id,location_id,quantity_precision,quantity_scaled,total_minor,source)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (self.tenant_id, identifier, line["ordinal"], master["item_id"], master["uom_id"], master["location_id"],
                    master["quantity_precision"], source["quantity_scaled"], source["total_minor"], canonical_json(source)))
            return self._remember(identifier, command_id, request, "Create authoritative commercial lines", actor)

    def act(self, identifier: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        if operation not in COMMERCE_PERMISSIONS or operation in {"create", "reserve"} or type(expected_version) is not int or expected_version < 1:
            raise FinancePostingError("commerce_command_invalid", "Supported commercial command and exact version are required.")
        reason = text(reason, "reason", maximum=500)
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            row = self._row(identifier)
            self._authority(actor, operation, row)
            request = self._request(identifier, operation, {"expected_version": expected_version, "reason": reason, **dict(parameters)}, actor)
            replay = self._replay(command_id, request)
            if replay is not None:
                return replay
            row = self._row(identifier, lock=True)
            if row["row_version"] != expected_version:
                raise FinancePostingError("commerce_version_conflict", "Commercial order changed; reload it.")
            if operation in {"submit", "approve"}:
                if parameters or row["status"] != ("Draft" if operation == "submit" else "Submitted"):
                    raise FinancePostingError("commerce_state_invalid", "Commercial review requires the exact next state.")
                if operation == "approve" and actor.user_id == row["created_by"]:
                    raise FinancePostingError("commerce_sod_denied", "Order creator cannot approve their commercial terms.")
                self.connection.execute("""UPDATE reconforge.stock_commerce_orders SET status=%s,approved_by=%s,
                    row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
                    ("Submitted" if operation == "submit" else "Approved", actor.user_id if operation == "approve" else None, self.tenant_id, identifier))
            else:
                if row["status"] != "Approved":
                    raise FinancePostingError("commerce_state_invalid", "Independently approve the commercial order first.")
                self.connection.execute("UPDATE reconforge.stock_commerce_orders SET row_version=row_version+1 WHERE tenant_id=%s AND id=%s", (self.tenant_id, identifier))
                if operation == "open-tranche":
                    self._open_tranche(row, parameters, actor, command_id)
                else:
                    self._tranche_action(row, operation, parameters, actor, command_id, reason)
            return self._remember(identifier, command_id, request, reason, actor)

    def _open_tranche(self, row: Mapping[str, Any], parameters: Mapping[str, Any], actor: PostingActor, command: str) -> None:
        if set(parameters) != {"line_number", "quantity"} or type(parameters["line_number"]) is not int:
            raise FinancePostingError("commerce_command_invalid", "A tranche requires an exact line number and quantity.")
        line = self.native._one("SELECT * FROM reconforge.stock_commerce_lines WHERE tenant_id=%s AND order_id=%s AND line_number=%s",
            (self.tenant_id, row["id"], parameters["line_number"]))
        quantity = quantity_to_scaled(parameters["quantity"], line["quantity_precision"], "delivery tranche")
        if quantity * line["source"]["net_unit_price_minor"] % (10 ** line["quantity_precision"]):
            raise FinancePostingError("commerce_precision_invalid", "Tranche quantity must preserve additive exact minor units.")
        used = self.connection.execute("""SELECT coalesce(sum(s.quantity_scaled),0) quantity FROM reconforge.stock_commerce_tranches t
            JOIN reconforge.stock_sales_orders s ON s.tenant_id=t.tenant_id AND s.id=t.stock_order_id
            WHERE t.tenant_id=%s AND t.order_id=%s AND t.line_number=%s AND s.status<>'Cancelled'""", (self.tenant_id, row["id"], line["line_number"])).fetchone()["quantity"]
        if quantity <= 0 or used + quantity > line["quantity_scaled"]:
            raise FinancePostingError("commerce_quantity_exceeded", "Tranche exceeds the authoritative commercial line remainder.")
        tranche_id = platform_id("COMTR", row["id"], str(row["row_version"] + 1))
        source = line["source"]
        child = self.native.create(StockOrder("EC1." + digest_payload({"tranche": tranche_id})[:48], source["customer_code"],
            source["customer_reference"], source["item_code"], source["warehouse_code"], source["location_code"], str(parameters["quantity"]),
            source["unit_price_minor"], source["currency_code"], source["order_date"], source["description"], source["discount_basis_points"]),
            command_id=_child_command(command, "create"), actor=actor)
        self.native.act(child["id"], "submit", expected_version=child["row_version"], command_id=_child_command(command, "submit"),
            reason="Submit retained commercial delivery tranche", parameters={}, actor=actor)
        self.connection.execute("INSERT INTO reconforge.stock_commerce_tranches(tenant_id,id,order_id,line_number,stock_order_id,created_version) VALUES(%s,%s,%s,%s,%s,%s)",
            (self.tenant_id, tranche_id, row["id"], line["line_number"], child["id"], row["row_version"] + 1))

    def _tranche_action(self, row: Mapping[str, Any], operation: str, parameters: Mapping[str, Any], actor: PostingActor, command: str, reason: str) -> None:
        values = dict(parameters)
        identifier = text(values.pop("tranche_id", ""), "tranche identifier")
        required = {"prepare-issue": {"posting_date", "period_id", "policy_code"},
            "prepare-invoice": {"invoice_number", "invoice_date", "due_date", "journal_code", "period_id", "receivable_account_code", "revenue_account_code"},
            "prepare-collection": {"receipt_number", "receipt_date", "journal_code", "period_id", "cash_account_code"}}
        if set(values) != required.get(operation, set()):
            raise FinancePostingError("commerce_command_invalid", "Tranche command requires the closed native participant parameters.")
        tranche = self.native._one("SELECT * FROM reconforge.stock_commerce_tranches WHERE tenant_id=%s AND id=%s AND order_id=%s",
            (self.tenant_id, identifier, row["id"]))
        child = self.native.get(tranche["stock_order_id"], actor=actor)
        native_operation = "approve" if operation == "approve-tranche" else operation
        child = self.native.act(child["id"], native_operation, expected_version=child["row_version"], command_id=_child_command(command, native_operation),
            reason=reason, parameters=values, actor=actor)
        if operation == "approve-tranche":
            self.native.act(child["id"], "reserve", expected_version=child["row_version"], command_id=_child_command(command, "reserve"),
                reason=reason, parameters={}, actor=actor)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.native._actor(actor, "read", self._row(identifier))
            self.connection.execute("SELECT reconforge.stock_commerce_close(%s,%s)", (self.tenant_id, identifier))
            return self._snapshot(identifier)

    def list(self, *, after: str = "", limit: int = 50, actor: PostingActor) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(after, str) or len(after) > 160:
            raise FinancePostingError("commerce_page_invalid", "Commercial paging requires bounded keyset cursor and limit.")
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.native._actor(actor, "read")
            rows = self.connection.execute("""SELECT id,number,row_version,status,currency_code,total_minor::text,line_count FROM reconforge.stock_commerce_orders
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND id COLLATE "C">%s
                ORDER BY id COLLATE "C" LIMIT %s""", (self.tenant_id, self.scope["workspace_id"], self.scope["organization_id"],
                self.scope["legal_entity_id"], after, limit + 1)).fetchall()
            return {"orders": [dict(row) for row in rows[:limit]], "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None}

    def catalog(self, *, prefix: str, after: str, limit: int, actor: PostingActor) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(prefix, str) or len(prefix) > 64 or not isinstance(after, str) or len(after) > 64:
            raise FinancePostingError("commerce_page_invalid", "Catalog search requires bounded prefix, keyset cursor and limit.")
        if prefix and (not prefix.isascii() or any(not(c.isalnum() or c in "-_.") for c in prefix)):
            raise FinancePostingError("commerce_page_invalid", "Catalog prefix accepts literal item-code characters.")
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.native._actor(actor, "read")
            escaped = prefix.upper().replace("_", "\\_")
            rows = self.connection.execute("""SELECT i.item_code,i.name,u.uom_code,u.decimal_places
                FROM reconforge.inventory_items i JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
                WHERE i.tenant_id=%s AND i.workspace_id=%s AND(i.organization_id IS NULL OR i.organization_id=%s)
                AND i.active AND u.active AND i.item_type<>'Service' AND i.tracking_mode='None' AND i.inventory_account_id IS NOT NULL
                AND i.item_code COLLATE "C">%s AND i.item_code LIKE %s ESCAPE '\'
                ORDER BY i.item_code COLLATE "C" LIMIT %s""", (self.tenant_id, self.scope["workspace_id"],
                self.scope["organization_id"], after, escaped + "%", limit + 1)).fetchall()
            return {"items": [dict(row) for row in rows[:limit]], "next_cursor": rows[limit - 1]["item_code"] if len(rows) > limit else None}
