"""Partial stock receipt and payable tranches share one READ COMMITTED owner."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from reconforge.application.payables import PurchaseOrderLineInput, SupplierInvoiceLineInput
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation, exact_text
from reconforge.domain.operational_finance import OperationalFinancePreparation
from reconforge.domain.payables_quantities import exact_sum, quantity_text
from reconforge.domain.procurement_operations import ProcurementPreparation, line_total
from reconforge.domain.procurement_partial import (
    INVOICE_STAGES,
    MAX_PARTS,
    ORDER_STAGES,
    RECEIPT_STAGES,
    PartialQuantityPreparation,
    ProcurementPartialError,
    normalize_order,
    normalize_part,
    reserve_quantity,
)
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_procurement_operations import (
    PERMISSIONS,
    PostgresProcurementOperationsRepository,
    json_value,
)
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.platform.common import platform_id

OPERATIONS = ("submit-order", "approve-order", "review-receipt", "receive", "approve-invoice", "prepare-accrual", "review-accrual", "post-accrual")


class PostgresProcurementPartialRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.shared = PostgresProcurementOperationsRepository(connection, tenant_id)
        self.tenant_id = self.shared.tenant_id
        self.payables, self.receipts = self.shared.payables, self.shared.receipts

    def _one(self, query: str, arguments: tuple[Any, ...]) -> dict[str, Any]:
        result = self.connection.execute(query, arguments).fetchone()
        if result is None:
            raise ProcurementPartialError("procurement_partial_not_found", "Partial procurement source is absent or outside current authority.")
        return dict(result)

    def _order(self, order_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = ("SELECT * FROM reconforge.procurement_partial_orders WHERE tenant_id=%s AND id=%s FOR UPDATE" if lock
                 else "SELECT * FROM reconforge.procurement_partial_orders WHERE tenant_id=%s AND id=%s")
        return self._one(query, (self.tenant_id, exact_text(order_id)))

    def _documents(self, order_id: str, kind: str) -> list[dict[str, Any]]:
        query = ("SELECT * FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s ORDER BY sequence" if kind == "receipt"
                 else "SELECT * FROM reconforge.procurement_partial_invoices WHERE tenant_id=%s AND order_id=%s ORDER BY sequence")
        return [dict(item) for item in self.connection.execute(query, (self.tenant_id, order_id)).fetchall()]

    def _document(self, order_id: str, document_id: str | None, kind: str) -> dict[str, Any]:
        if document_id is None:
            raise ProcurementPartialError("procurement_partial_document_required", "Select the actual owned receipt or invoice.")
        query = ("SELECT * FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s AND id=%s" if kind == "receipt"
                 else "SELECT * FROM reconforge.procurement_partial_invoices WHERE tenant_id=%s AND order_id=%s AND id=%s")
        return self._one(query, (self.tenant_id, order_id, exact_text(document_id)))

    def _scope_transaction(self) -> None:
        ensure_repository_tenant_scope(self.connection, self.tenant_id)
        if self.connection.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
            raise ProcurementPartialError("procurement_partial_isolation_required", "Partial procurement commands require READ COMMITTED.")

    def _command(self, row: Mapping[str, Any], command_id: str, operation: str,
                 payload: Mapping[str, Any], actor: PostingActor) -> tuple[str, dict[str, Any] | None]:
        command_id = exact_text(command_id)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, "procurement-partial-command", row["workspace_id"], command_id]),))
        digest = digest_payload({"order_id": row["id"], "operation": operation, "payload": payload, "actor_id": actor.user_id})
        retained = self.connection.execute("SELECT * FROM reconforge.procurement_partial_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                           (self.tenant_id, row["workspace_id"], command_id)).fetchone()
        if retained is None:
            return digest, None
        if retained["order_id"] != row["id"] or retained["actor_id"] != actor.user_id or retained["request_digest"] != digest:
            raise ProcurementPartialError("procurement_partial_command_conflict", "Command is bound to another exact request or actor.")
        return digest, dict(retained["response_json"])

    def _begin(self, order_id: str, operation: str, expected_version: int, command_id: str,
               payload: Mapping[str, Any], actor: PostingActor) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
        if type(expected_version) is not int or expected_version < 1:
            raise ProcurementPartialError("procurement_partial_version_invalid", "A positive expected version is required.")
        self._scope_transaction()
        row = self._order(order_id)
        self.shared._authorize(row, actor, operation)
        digest, replay = self._command(row, command_id, operation, payload, actor)
        if replay is not None:
            self.shared._authorize(self._order(order_id), actor, operation)
            self.connection.execute("SELECT reconforge.pp_verify_order(%s,%s)", (self.tenant_id, order_id))
            return row, digest, replay
        row = self._order(order_id, lock=True)
        self.shared._authorize(row, actor, operation)
        if row["row_version"] != expected_version:
            raise ProcurementPartialError("procurement_partial_version_conflict", "Order changed; reload before preparing a new command.")
        return row, digest, None

    def _remember(self, order_id: str, command_id: str, operation: str, digest: str,
                  payload: Mapping[str, Any], actor: PostingActor, *, created: bool = False) -> dict[str, Any]:
        if not created:
            self.connection.execute("UPDATE reconforge.procurement_partial_orders SET row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, order_id))
        row = self._order(order_id)
        response = self._view(row)
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.user_id, object_type="procurement_partial_order", object_id=order_id, action="procurement_partial_" + operation.replace("-", "_"),
            metadata={"row_version": row["row_version"], "request_digest": digest})
        outbox = platform_id("PPOUT", order_id, row["row_version"])
        self.connection.execute("""INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,
            workspace_id,organization_id,legal_entity_id,payload) VALUES(%s,%s,'procurement.partial_changed','procurement_partial_order',%s,%s,%s,%s,%s::jsonb)""",
            (self.tenant_id, outbox, order_id, row["workspace_id"], row["organization_id"], row["legal_entity_id"],
             canonical_json({"order_id": order_id, "row_version": row["row_version"], "audit_event_id": audit.id})))
        self.connection.execute("""INSERT INTO reconforge.procurement_partial_commands(tenant_id,workspace_id,command_id,order_id,
            order_version,actor_id,operation,request_json,request_digest,response_json,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s)""",
            (self.tenant_id, row["workspace_id"], exact_text(command_id), order_id, row["row_version"], actor.user_id, operation,
             canonical_json(payload), digest, canonical_json(response), audit.id, outbox))
        return response

    def create(self, request: ProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = normalize_order(request)
        _, total = line_total(request.quantity, request.unit_price_minor)
        with self.connection.transaction():
            self._scope_transaction()
            scope = self.shared._scope(request)
            order_id = platform_id("PPORDER", scope["workspace_id"], request.number)
            row = {**scope, "id": order_id, "request_json": asdict(request), "total_minor": total}
            self.shared._authorize(row, actor, "create")
            digest, replay = self._command(row, command_id, "create", asdict(request), actor)
            if replay is not None:
                self.shared._authorize(self._order(order_id), actor, "create")
                self.connection.execute("SELECT reconforge.pp_verify_order(%s,%s)", (self.tenant_id, order_id))
                return replay
            self._one("""SELECT id FROM reconforge.ap_suppliers WHERE tenant_id=%s AND workspace_id=%s AND supplier_code=%s
                AND status='Active' AND (organization_id IS NULL OR organization_id=%s) AND (legal_entity_id IS NULL OR legal_entity_id=%s)
                AND currency_code=%s FOR SHARE""", (self.tenant_id, scope["workspace_id"], request.supplier_code,
                scope["organization_id"], scope["legal_entity_id"], request.currency_code))
            native = self.payables.create_purchase_order(po_number=request.number, supplier_code=request.supplier_code,
                order_date=request.posting_date, currency_code=request.currency_code,
                lines=[PurchaseOrderLineInput(item_code=request.item_code, ordered_quantity=request.quantity, unit_price_minor=request.unit_price_minor)],
                workspace=scope["workspace_id"], organization_code=request.organization_code, entity_code=request.entity_code,
                idempotency_key=platform_id("PPCMD", command_id, "order"), actor_label=actor.user_id)
            self.connection.execute("""INSERT INTO reconforge.procurement_partial_orders(tenant_id,id,workspace_id,organization_id,legal_entity_id,
                number,request_json,total_minor,purchase_order_id,creator_actor_id) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                (self.tenant_id, order_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], request.number,
                 canonical_json(asdict(request)), total, native["id"], actor.user_id))
            return self._remember(order_id, command_id, "create", digest, asdict(request), actor, created=True)

    def prepare_receipt(self, order_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                        command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            self._scope_transaction()
            parent = self._order(order_id)
            request, amount = normalize_part(request, parent["request_json"]["unit_price_minor"])
            payload = {**asdict(request), "expected_version": expected_version}
            row, digest, replay = self._begin(order_id, "prepare-receipt", expected_version, command_id, payload, actor)
            if replay is not None:
                return replay
            parts = self._documents(order_id, "receipt")
            self._approved(row, len(parts))
            reserve_quantity(request.quantity, row["request_json"]["quantity"], tuple(part["quantity_text"] for part in parts))
            sequence, number = len(parts) + 1, "PPR-" + row["number"] + "-" + str(len(parts) + 1)
            original = ProcurementPreparation(**row["request_json"])
            plan = self.receipts.prepare_receipt(ReceiptPreparation(receipt_number=number, posting_date=request.posting_date,
                period_id=request.period_id, item_code=original.item_code, location_code=original.location_code, quantity=request.quantity,
                total_value_minor=amount, policy_code=original.policy_code, workspace=row["workspace_id"],
                organization_code=original.organization_code, entity_code=original.entity_code, reason=request.reason),
                command_id=platform_id("PPCMD", order_id, command_id, "receipt"), actor=actor)
            if plan["currency_policy"]["currency_code"] != original.currency_code:
                raise ProcurementPartialError("procurement_partial_currency_invalid", "Stock and supplier functional currencies must match.")
            self.connection.execute("""INSERT INTO reconforge.procurement_partial_receipts(tenant_id,id,order_id,sequence,number,
                quantity,quantity_text,total_minor,posting_date,period_id,receipt_plan_id,created_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, platform_id("PPRECEIPT", order_id, sequence), order_id, sequence, number, Decimal(request.quantity),
                 request.quantity, amount, request.posting_date, request.period_id, plan["plan_id"], row["row_version"] + 1))
            return self._remember(order_id, command_id, "prepare-receipt", digest, payload, actor)

    def _approved(self, row: Mapping[str, Any], count: int) -> None:
        if row["stage"] != 2 or count >= MAX_PARTS:
            raise ProcurementPartialError("procurement_partial_state_conflict", "An approved order and available document capacity are required.")

    def match_invoice(self, order_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                      command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            self._scope_transaction()
            parent = self._order(order_id)
            request, amount = normalize_part(request, parent["request_json"]["unit_price_minor"])
            payload = {**asdict(request), "expected_version": expected_version}
            row, digest, replay = self._begin(order_id, "match-invoice", expected_version, command_id, payload, actor)
            if replay is not None:
                return replay
            invoices = self._documents(order_id, "invoice")
            self._approved(row, len(invoices))
            received = quantity_text(exact_sum(Decimal(item["quantity_text"]) for item in self._documents(order_id, "receipt") if item["stage"] == 2))
            reserve_quantity(request.quantity, received, tuple(item["quantity_text"] for item in invoices))
            native_order = self.payables.get_purchase_order(row["purchase_order_id"])
            original = ProcurementPreparation(**row["request_json"])
            sequence, number = len(invoices) + 1, "PPI-" + row["number"] + "-" + str(len(invoices) + 1)
            invoice = self.payables.create_supplier_invoice(invoice_number=number, supplier_code=original.supplier_code,
                invoice_date=request.posting_date, currency_code=original.currency_code, total_minor=amount,
                purchase_order_id=native_order["id"], workspace=row["workspace_id"], organization_code=original.organization_code,
                entity_code=original.entity_code, actor_label=actor.user_id, idempotency_key=platform_id("PPCMD", order_id, command_id, "invoice"),
                lines=[SupplierInvoiceLineInput(purchase_order_line_id=native_order["lines"][0]["id"], invoiced_quantity=request.quantity,
                    unit_price_minor=original.unit_price_minor, line_total_minor=amount)])
            self.payables.submit_supplier_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.user_id)
            matched = self.payables.run_three_way_match(invoice["id"], actor_label=actor.user_id)
            if matched.status != "Passed":
                raise ProcurementPartialError("procurement_partial_match_conflict", "Supplier invoice failed exact three-way matching.")
            self.connection.execute("""INSERT INTO reconforge.procurement_partial_invoices(tenant_id,id,order_id,sequence,number,quantity,
                quantity_text,total_minor,posting_date,period_id,native_invoice_id,created_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, platform_id("PPINVOICE", order_id, sequence), order_id, sequence, number, Decimal(request.quantity),
                 request.quantity, amount, request.posting_date, request.period_id, invoice["id"], row["row_version"] + 1))
            return self._remember(order_id, command_id, "match-invoice", digest, payload, actor)

    def act(self, order_id: str, operation: str, *, expected_version: int, command_id: str, reason: str,
            actor: PostingActor, document_id: str | None = None) -> dict[str, Any]:
        if operation not in OPERATIONS:
            raise ProcurementPartialError("procurement_partial_command_invalid", "Unsupported partial procurement command.")
        reason = exact_text(reason, maximum=500)
        payload = {"expected_version": expected_version, "reason": reason, "document_id": document_id}
        with self.connection.transaction():
            row, digest, replay = self._begin(order_id, operation, expected_version, command_id, payload, actor)
            if replay is not None:
                return replay
            native_order = self.payables.get_purchase_order(row["purchase_order_id"])
            command = platform_id("PPCMD", order_id, command_id, operation)
            if operation in ("submit-order", "approve-order"):
                expected_stage = 0 if operation == "submit-order" else 1
                if row["stage"] != expected_stage or document_id is not None:
                    raise ProcurementPartialError("procurement_partial_state_conflict", "Order approval stage changed.")
                if operation == "submit-order":
                    self.payables.submit_purchase_order(native_order["id"], expected_version=native_order["row_version"], actor_label=actor.user_id)
                else:
                    self.payables.approve_purchase_order(native_order["id"], expected_version=native_order["row_version"], actor_label=actor.user_id)
                query = ("UPDATE reconforge.procurement_partial_orders SET stage=stage+1,submitted_version=%s WHERE tenant_id=%s AND id=%s"
                         if operation == "submit-order" else "UPDATE reconforge.procurement_partial_orders SET stage=stage+1,approved_version=%s WHERE tenant_id=%s AND id=%s")
                self.connection.execute(query, (row["row_version"] + 1, self.tenant_id, order_id))
            elif operation in ("review-receipt", "receive"):
                self._receipt_action(row, native_order, operation, document_id, command, reason, actor)
            else:
                self._invoice_action(row, operation, document_id, command, reason, actor)
            return self._remember(order_id, command_id, operation, digest, payload, actor)

    def _receipt_action(self, row: Mapping[str, Any], native_order: Mapping[str, Any], operation: str, document_id: str | None,
                        command: str, reason: str, actor: PostingActor) -> None:
        part = self._document(row["id"], document_id, "receipt")
        expected = 0 if operation == "review-receipt" else 1
        if part["stage"] != expected:
            raise ProcurementPartialError("procurement_partial_state_conflict", "Receipt review/post stage changed.")
        view = self.receipts.get_plan(part["receipt_plan_id"], actor=actor)
        native_receipt = None
        if operation == "review-receipt":
            self.receipts.review(part["receipt_plan_id"], expected_plan_digest=view["plan"]["plan_digest"], command_id=command, reason=reason, actor=actor)
        else:
            review = view["review"]
            if review is None:
                raise ProcurementPartialError("procurement_partial_review_required", "Receiving requires independent retained review.")
            self.receipts.commit(part["receipt_plan_id"], expected_review_digest=review["review_digest"], command_id=command, reason=reason, actor=actor)
            native_receipt = self.payables.post_receipt(receipt_number=part["number"], purchase_order_id=native_order["id"],
                receipt_date=part["posting_date"].isoformat(), quantities={native_order["lines"][0]["id"]: part["quantity_text"]},
                workspace=row["workspace_id"], idempotency_key=command, actor_label=actor.user_id)["id"]
        if operation == "review-receipt":
            self.connection.execute("UPDATE reconforge.procurement_partial_receipts SET stage=stage+1,reviewed_version=%s WHERE tenant_id=%s AND id=%s",
                                    (row["row_version"] + 1, self.tenant_id, part["id"]))
        else:
            self.connection.execute("UPDATE reconforge.procurement_partial_receipts SET stage=stage+1,posted_version=%s,goods_receipt_id=%s WHERE tenant_id=%s AND id=%s",
                                    (row["row_version"] + 1, native_receipt, self.tenant_id, part["id"]))

    def _invoice_action(self, row: Mapping[str, Any], operation: str, document_id: str | None, command: str, reason: str, actor: PostingActor) -> None:
        part = self._document(row["id"], document_id, "invoice")
        actions = ("approve-invoice", "prepare-accrual", "review-accrual", "post-accrual")
        if part["stage"] >= len(actions) or actions[part["stage"]] != operation:
            raise ProcurementPartialError("procurement_partial_state_conflict", "Invoice review/post stage changed.")
        plan_id, effect_id = None, None
        if operation == "approve-invoice":
            native = self.payables.get_supplier_invoice(part["native_invoice_id"])
            self.payables.approve_supplier_invoice(native["id"], expected_version=native["row_version"], actor_label=actor.user_id)
        else:
            finance = PostgresOperationalFinanceRepository(self.connection, self.tenant_id)
            if operation == "prepare-accrual":
                original = ProcurementPreparation(**row["request_json"])
                mapping = self._one("""SELECT a.account_code FROM reconforge.inventory_receipt_plans r
                    JOIN reconforge.finance_accounts a ON a.tenant_id=r.tenant_id AND a.id=r.receipt_clearing_account_id
                    JOIN reconforge.procurement_partial_receipts d ON d.tenant_id=r.tenant_id AND d.receipt_plan_id=r.id
                    WHERE d.tenant_id=%s AND d.order_id=%s AND d.stage=2 ORDER BY d.sequence LIMIT 1""", (self.tenant_id, row["id"]))
                plan = finance.prepare(OperationalFinancePreparation(workspace_id=row["workspace_id"], organization_id=row["organization_id"],
                    legal_entity_id=row["legal_entity_id"], organization_code=original.organization_code, entity_code=original.entity_code,
                    source_kind="APInvoice", source_id=part["native_invoice_id"], journal_code=original.journal_code, period_id=part["period_id"],
                    posting_date=part["posting_date"].isoformat(), debit_account_code=mapping["account_code"], credit_account_code=original.ap_account_code,
                    reason=reason), command_id=command, actor=actor)
                plan_id = plan["id"]
            else:
                plan = finance.get(part["accrual_plan_id"], actor=actor)
                if operation == "review-accrual":
                    finance.review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id=command, reason=reason, actor=actor)
                else:
                    effect_id = finance.post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id=command, reason=reason, actor=actor)["posting_effect_id"]
        query = {
            "approve-invoice": "UPDATE reconforge.procurement_partial_invoices SET stage=stage+1,approved_version=%s WHERE tenant_id=%s AND id=%s",
            "prepare-accrual": "UPDATE reconforge.procurement_partial_invoices SET stage=stage+1,prepared_version=%s,accrual_plan_id=%s WHERE tenant_id=%s AND id=%s",
            "review-accrual": "UPDATE reconforge.procurement_partial_invoices SET stage=stage+1,reviewed_version=%s WHERE tenant_id=%s AND id=%s",
            "post-accrual": "UPDATE reconforge.procurement_partial_invoices SET stage=stage+1,posted_version=%s,accrual_effect_id=%s WHERE tenant_id=%s AND id=%s",
        }[operation]
        args: tuple[Any, ...] = (row["row_version"] + 1, self.tenant_id, part["id"])
        if operation in ("prepare-accrual", "post-accrual"):
            args = (row["row_version"] + 1, plan_id if operation == "prepare-accrual" else effect_id, self.tenant_id, part["id"])
        self.connection.execute(query, args)

    def _view(self, row: Mapping[str, Any]) -> dict[str, Any]:
        receipts, invoices = self._documents(row["id"], "receipt"), self._documents(row["id"], "invoice")
        order = dict(row)
        order["stage"] = ORDER_STAGES[row["stage"]]
        order["total_minor"] = str(row["total_minor"])
        order["request"] = {key: str(value) for key, value in row["request_json"].items()}
        order.pop("request_json")
        for part in receipts:
            part["stage"] = RECEIPT_STAGES[part["stage"]]
            part["total_minor"] = str(part["total_minor"])
        for part in invoices:
            part["stage"] = INVOICE_STAGES[part["stage"]]
            part["total_minor"] = str(part["total_minor"])
            native = self._one("SELECT status,row_version FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s",
                               (self.tenant_id, part["native_invoice_id"]))
            links = self.connection.execute("SELECT id,finance_effect_id,amount_minor,created_at FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s ORDER BY created_at,id",
                                            (self.tenant_id, part["native_invoice_id"])).fetchall()
            paid = sum(item["amount_minor"] for item in links)
            part.update(native_status=native["status"], native_version=native["row_version"], paid_minor=str(paid),
                        outstanding_minor=str(int(part["total_minor"]) - paid),
                        payment_links=[{**dict(item), "amount_minor": str(item["amount_minor"])} for item in links])
        totals = {
            "ordered_quantity": order["request"]["quantity"],
            "reserved_receipt_quantity": quantity_text(exact_sum(Decimal(item["quantity_text"]) for item in receipts)),
            "received_quantity": quantity_text(exact_sum(Decimal(item["quantity_text"]) for item in receipts if item["stage"] == "Posted")),
            "invoiced_quantity": quantity_text(exact_sum(Decimal(item["quantity_text"]) for item in invoices)),
            "received_minor": str(sum(int(item["total_minor"]) for item in receipts if item["stage"] == "Posted")),
            "accrued_minor": str(sum(int(item["total_minor"]) for item in invoices if item["stage"] == "Accrued")),
            "paid_minor": str(sum(int(item["paid_minor"]) for item in invoices)),
            "outstanding_minor": str(sum(int(item["outstanding_minor"]) for item in invoices if item["stage"] == "Accrued")),
        }
        return json_value({"order": order, "receipts": receipts, "invoices": invoices, "totals": totals})

    def get(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            row = self._order(order_id)
            self.shared._authorize(row, actor, "read")
            self.connection.execute("SELECT reconforge.pp_verify_order(%s,%s)", (self.tenant_id, order_id))
            return self._view(row)

    def list_orders(self, workspace: str, *, actor: PostingActor) -> list[dict[str, Any]]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.receipts._actor(actor, frozenset({"payables.read", "inventory.read", "finance_core.read"}), mutation=False)
            rows = self.connection.execute("SELECT id FROM reconforge.procurement_partial_orders WHERE tenant_id=%s AND workspace_id=%s ORDER BY created_at DESC,id LIMIT 50",
                                           (self.tenant_id, workspace)).fetchall()
            return [self.get(item["id"], actor=actor) for item in rows]

    def options(self, workspace: str, organization: str, entity: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.shared.options(workspace, organization, entity, actor=actor)

    def scopes(self, workspace: str, *, actor: PostingActor) -> list[dict[str, Any]]:
        return self.shared.scopes(workspace, actor=actor)


__all__ = ["OPERATIONS", "PERMISSIONS", "PostgresProcurementPartialRepository"]
