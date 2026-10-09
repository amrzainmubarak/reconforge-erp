"""Partial stock receipt and payable tranches share one READ COMMITTED owner."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, fields
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
    MAX_ENTERPRISE_PARTS,
    MAX_PARTS,
    ORDER_STAGES,
    RECEIPT_STAGES,
    MultilineInvoicePreparation,
    MultilineProcurementPreparation,
    PartialQuantityPreparation,
    ProcurementPartialError,
    document_page_size,
    normalize_invoice_lines,
    normalize_multiline,
    normalize_order,
    normalize_part,
    require_third_poster,
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
from reconforge.platform.inventory_values import quantity_to_scaled

OPERATIONS = ("submit-order", "approve-order", "review-receipt", "receive", "approve-invoice", "prepare-accrual", "review-accrual", "post-accrual")


class PostgresProcurementPartialRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.shared = PostgresProcurementOperationsRepository(connection, tenant_id)
        self.tenant_id = self.shared.tenant_id
        self.payables, self.receipts = self.shared.payables, self.shared.receipts
        self.receipt_after = 0
        self.invoice_after = 0

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
        row = self._order(order_id)
        if row.get("multiline", False):
            query = ("SELECT * FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s AND sequence>%s ORDER BY sequence LIMIT %s" if kind == "receipt"
                     else "SELECT * FROM reconforge.procurement_partial_invoices WHERE tenant_id=%s AND order_id=%s AND sequence>%s ORDER BY sequence LIMIT %s")
            return [dict(item) for item in self.connection.execute(query,
                (self.tenant_id, order_id, self.receipt_after if kind == "receipt" else self.invoice_after, document_page_size(row["line_count"]))).fetchall()]
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
        authority = {"prepare-receipt-line": "prepare-receipt", "match-invoice-lines": "match-invoice"}.get(operation, operation)
        self.shared._authorize(row, actor, authority)
        digest, replay = self._command(row, command_id, operation, payload, actor)
        if replay is not None:
            self.shared._authorize(self._order(order_id), actor, authority)
            self.connection.execute("SELECT reconforge.pp_verify_order(%s,%s)", (self.tenant_id, order_id))
            return row, digest, replay
        row = self._order(order_id, lock=True)
        self.shared._authorize(row, actor, authority)
        if row["row_version"] != expected_version:
            raise ProcurementPartialError("procurement_partial_version_conflict", "Order changed; reload before preparing a new command.")
        return row, digest, None

    def _remember(self, order_id: str, command_id: str, operation: str, digest: str,
                  payload: Mapping[str, Any], actor: PostingActor, *, created: bool = False) -> dict[str, Any]:
        if not created:
            self.connection.execute("UPDATE reconforge.procurement_partial_orders SET row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, order_id))
        row = self._order(order_id)
        if row.get("multiline", False) and operation not in ("create", "submit-order", "approve-order"):
            if "receipt" in operation or operation == "receive":
                focus = self._one("SELECT sequence FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s AND (id=%s OR created_version=%s) ORDER BY sequence DESC LIMIT 1",
                    (self.tenant_id, order_id, payload.get("document_id"), row["row_version"]))
                self.receipt_after = max(0, focus["sequence"] - document_page_size(row["line_count"]))
            else:
                focus = self._one("SELECT sequence FROM reconforge.procurement_partial_invoices WHERE tenant_id=%s AND order_id=%s AND (id=%s OR created_version=%s) ORDER BY sequence DESC LIMIT 1",
                    (self.tenant_id, order_id, payload.get("document_id"), row["row_version"]))
                self.invoice_after = max(0, focus["sequence"] - document_page_size(row["line_count"]))
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
            item = self.receipts.inventory._item(scope["workspace_id"], request.item_code, active=True)
            if item["item_type"] not in ("Stock", "Consumable") or item["tracking_mode"] != "None" or not item["uom_active"] or item["organization_id"] not in (None, scope["organization_id"]):
                raise ProcurementPartialError("procurement_partial_item_invalid", "An active untracked stock item and unit in this organization are required.")
            quantity_to_scaled(request.quantity, item["decimal_places"])
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
            if parent.get("multiline", False):
                raise ProcurementPartialError("procurement_partial_line_required", "Select an actual enterprise purchase line for receiving.")
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
            if parent.get("multiline", False):
                raise ProcurementPartialError("procurement_partial_line_required", "Select exact enterprise purchase line allocations for this invoice.")
            request, amount = normalize_part(request, parent["request_json"]["unit_price_minor"])
            payload = {**asdict(request), "expected_version": expected_version}
            row, digest, replay = self._begin(order_id, "match-invoice", expected_version, command_id, payload, actor)
            if replay is not None:
                return replay
            invoices = self._documents(order_id, "invoice")
            self._approved(row, len(invoices))
            received = quantity_text(exact_sum(Decimal(item["quantity_text"]) for item in self._documents(order_id, "receipt") if item["stage"] == 2))
            reserve_quantity(request.quantity, received, tuple(item["quantity_text"] for item in invoices))
            unit = self._one("""SELECT p.quantity_precision FROM reconforge.procurement_partial_receipts r
                JOIN reconforge.inventory_receipt_plans p ON p.tenant_id=r.tenant_id AND p.id=r.receipt_plan_id
                WHERE r.tenant_id=%s AND r.order_id=%s AND r.stage=2 ORDER BY r.sequence LIMIT 1""", (self.tenant_id, order_id))
            quantity_to_scaled(request.quantity, unit["quantity_precision"])
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
            require_third_poster(view["plan"]["preparer"]["user_id"], review["reviewer"]["user_id"], actor.user_id)
            self.receipts.commit(part["receipt_plan_id"], expected_review_digest=review["review_digest"], command_id=command, reason=reason, actor=actor)
            native_receipt = self.payables.post_receipt(receipt_number=part["number"], purchase_order_id=native_order["id"],
                receipt_date=part["posting_date"].isoformat(), quantities={self._native_receipt_line(row, part, native_order): part["quantity_text"]},
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
                original = ProcurementPreparation(**{field.name: row["request_json"][field.name] for field in fields(ProcurementPreparation)})
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
                    require_third_poster(plan["preparer_actor_id"], plan["reviewer_actor_id"], actor.user_id)
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
        installments_available = self.connection.execute("SELECT to_regclass('reconforge.financial_installment_plans') IS NOT NULL AS installed").fetchone()["installed"]
        order = dict(row)
        order["stage"] = ORDER_STAGES[row["stage"]]
        order["total_minor"] = str(row["total_minor"])
        order["request"] = {key: str(value) for key, value in row["request_json"].items() if key != "lines"}
        order.pop("request_json")
        for part in receipts:
            part["stage"] = RECEIPT_STAGES[part["stage"]]
            part["total_minor"] = str(part["total_minor"])
            actors = self._one("""SELECT p.preparer_actor_id,r.reviewer_actor_id,l.posted_actor_id
                FROM reconforge.inventory_receipt_plans p
                LEFT JOIN reconforge.inventory_receipt_reviews r ON r.tenant_id=p.tenant_id AND r.plan_id=p.id
                LEFT JOIN reconforge.inventory_receipt_links l ON l.tenant_id=p.tenant_id AND l.plan_id=p.id
                WHERE p.tenant_id=%s AND p.id=%s""", (self.tenant_id, part["receipt_plan_id"]))
            part.update(dict(actors))
        for part in invoices:
            part["stage"] = INVOICE_STAGES[part["stage"]]
            part["total_minor"] = str(part["total_minor"])
            part.update(accrual_preparer_actor_id=None, accrual_reviewer_actor_id=None, accrual_posted_actor_id=None)
            if part["accrual_plan_id"] is not None:
                actors = self._one("""SELECT p.preparer_actor_id AS accrual_preparer_actor_id,
                    r.reviewer_actor_id AS accrual_reviewer_actor_id,l.posted_actor_id AS accrual_posted_actor_id
                    FROM reconforge.operational_finance_plans p
                    LEFT JOIN reconforge.operational_finance_reviews r ON r.tenant_id=p.tenant_id AND r.plan_id=p.id
                    LEFT JOIN reconforge.operational_finance_links l ON l.tenant_id=p.tenant_id AND l.plan_id=p.id
                    WHERE p.tenant_id=%s AND p.id=%s""", (self.tenant_id, part["accrual_plan_id"]))
                part.update(dict(actors))
            native = self._one("SELECT status,row_version FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s",
                               (self.tenant_id, part["native_invoice_id"]))
            if row.get("multiline", False):
                links = self.connection.execute("SELECT id,finance_effect_id,amount_minor,created_at FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s ORDER BY created_at DESC,id DESC LIMIT 25",
                                                (self.tenant_id, part["native_invoice_id"])).fetchall()
                payment_summary = self._one("SELECT COALESCE(sum(amount_minor),0) AS paid,count(*) AS total FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s",
                    (self.tenant_id, part["native_invoice_id"]))
                part["payment_history_count"] = payment_summary["total"]
                paid = int(payment_summary["paid"])
            else:
                links = self.connection.execute("SELECT id,finance_effect_id,amount_minor,created_at FROM reconforge.ap_payment_links WHERE tenant_id=%s AND supplier_invoice_id=%s ORDER BY created_at,id",
                                                (self.tenant_id, part["native_invoice_id"])).fetchall()
                paid = sum(item["amount_minor"] for item in links)
            part.update(native_status=native["status"], native_version=native["row_version"], paid_minor=str(paid),
                        outstanding_minor=str(int(part["total_minor"]) - paid),
                        payment_links=[{**dict(item), "amount_minor": str(item["amount_minor"])} for item in links])
            part["installment_plans"] = []
            if installments_available:
                plan_query = """SELECT p.id,p.payload,p.phase,r.reviewer_actor_id,l.posting_effect_id,l.payment_link_id
                    FROM reconforge.financial_installment_plans p LEFT JOIN reconforge.financial_installment_reviews r ON r.tenant_id=p.tenant_id AND r.plan_id=p.id
                    LEFT JOIN reconforge.financial_installment_links l ON l.tenant_id=p.tenant_id AND l.plan_id=p.id
                    WHERE p.tenant_id=%s AND p.source_id=%s """
                plan_query += "ORDER BY (p.phase<2) DESC,p.created_at DESC,p.id DESC LIMIT 25" if row.get("multiline", False) else "ORDER BY p.created_at,p.id LIMIT 200"
                plans = self.connection.execute(plan_query, (self.tenant_id, part["native_invoice_id"])).fetchall()
                for plan in plans:
                    self.connection.execute("SELECT reconforge.installment_close(%s,%s)", (self.tenant_id, plan["id"]))
                    payload = plan["payload"]
                    keys = ("id", "workspace_id", "organization_id", "legal_entity_id", "source_id", "source_kind", "entry_id",
                            "period_id", "posting_date", "currency_code", "currency_precision", "plan_digest", "validation_digest",
                            "preparer_actor_id", "invoice_version")
                    part["installment_plans"].append({**{key: payload[key] for key in keys},
                        "phase": plan["phase"], "status": ("Prepared", "Reviewed", "Posted")[plan["phase"]],
                        "reviewer_actor_id": plan["reviewer_actor_id"], "posting_effect_id": plan["posting_effect_id"],
                        "payment_link_id": plan["payment_link_id"], "amount_minor": str(payload["amount_minor"]),
                        "allocated_before_minor": str(payload["allocated_before_minor"])})
        totals = {
            "ordered_quantity": order["request"]["quantity"],
            "reserved_receipt_quantity": quantity_text(exact_sum(Decimal(item["quantity_text"]) for item in receipts)),
            "received_quantity": quantity_text(exact_sum(Decimal(item["quantity_text"]) for item in receipts if item["stage"] == "Posted")),
            "invoiced_quantity": quantity_text(exact_sum(Decimal(item["quantity_text"]) for item in invoices if item["quantity_text"] is not None)),
            "received_minor": str(sum(int(item["total_minor"]) for item in receipts if item["stage"] == "Posted")),
            "accrued_minor": str(sum(int(item["total_minor"]) for item in invoices if item["stage"] == "Accrued")),
            "paid_minor": str(sum(int(item["paid_minor"]) for item in invoices)),
            "outstanding_minor": str(sum(int(item["outstanding_minor"]) for item in invoices if item["stage"] == "Accrued")),
        }
        result = {"order": order, "receipts": receipts, "invoices": invoices, "totals": totals}
        if row.get("multiline", False):
            result = self._multiline_view(row, result)
        return json_value(result)

    def _native_receipt_line(self, row: Mapping[str, Any], part: Mapping[str, Any], native_order: Mapping[str, Any]) -> str:
        if row.get("multiline", False):
            return str(self._one("SELECT purchase_order_line_id FROM reconforge.procurement_partial_order_lines WHERE tenant_id=%s AND order_id=%s AND id=%s",
                (self.tenant_id, row["id"], part["order_line_id"]))["purchase_order_line_id"])
        return str(native_order["lines"][0]["id"])

    def _multiline_view(self, row: Mapping[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """Bounded document pages and all-line summaries, with no mixed-unit sums."""
        lines = [dict(item) for item in self.connection.execute("""SELECT l.*,
            COALESCE((SELECT sum(r.quantity) FROM reconforge.procurement_partial_receipts r WHERE r.tenant_id=l.tenant_id AND r.order_id=l.order_id AND r.order_line_id=l.id),0)::text AS reserved_receipt_quantity,
            COALESCE((SELECT sum(r.quantity) FROM reconforge.procurement_partial_receipts r WHERE r.tenant_id=l.tenant_id AND r.order_id=l.order_id AND r.order_line_id=l.id AND r.stage=2),0)::text AS received_quantity,
            COALESCE((SELECT sum(i.quantity) FROM reconforge.procurement_partial_invoice_lines i WHERE i.tenant_id=l.tenant_id AND i.order_id=l.order_id AND i.order_line_id=l.id),0)::text AS invoiced_quantity,
            u.uom_code FROM reconforge.procurement_partial_order_lines l JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=l.tenant_id AND u.id=l.uom_id
            WHERE l.tenant_id=%s AND l.order_id=%s ORDER BY l.sequence""", (self.tenant_id, row["id"])).fetchall()]
        for line in lines:
            line["unit_price_minor"], line["total_minor"] = str(line["unit_price_minor"]), str(line["total_minor"])
        for invoice in result["invoices"]:
            allocations = self.connection.execute("""SELECT a.id,a.order_line_id AS line_id,a.sequence,a.quantity_text,a.total_minor,l.item_code,l.location_code,l.uom_id
                FROM reconforge.procurement_partial_invoice_lines a JOIN reconforge.procurement_partial_order_lines l ON l.tenant_id=a.tenant_id AND l.id=a.order_line_id
                WHERE a.tenant_id=%s AND a.invoice_id=%s ORDER BY a.sequence""", (self.tenant_id, invoice["id"])).fetchall()
            invoice["lines"] = [{**dict(item), "total_minor": str(item["total_minor"])} for item in allocations]
        totals = self._one("""SELECT
            COALESCE((SELECT sum(total_minor) FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s AND stage=2),0) AS received_minor,
            COALESCE(sum(CASE WHEN i.stage=4 THEN i.total_minor ELSE 0 END),0) AS accrued_minor,
            COALESCE(sum((SELECT COALESCE(sum(p.amount_minor),0) FROM reconforge.ap_payment_links p WHERE p.tenant_id=i.tenant_id AND p.supplier_invoice_id=i.native_invoice_id)),0) AS paid_minor,
            COALESCE(sum(CASE WHEN i.stage=4 THEN i.total_minor-(SELECT COALESCE(sum(p.amount_minor),0) FROM reconforge.ap_payment_links p WHERE p.tenant_id=i.tenant_id AND p.supplier_invoice_id=i.native_invoice_id) ELSE 0 END),0) AS outstanding_minor
            FROM reconforge.procurement_partial_invoices i WHERE i.tenant_id=%s AND i.order_id=%s""",
            (self.tenant_id, row["id"], self.tenant_id, row["id"]))
        result["totals"] = {**{key: "0" for key in ("ordered_quantity", "reserved_receipt_quantity", "received_quantity", "invoiced_quantity")},
                            **{key: str(value) for key, value in totals.items()}}
        counts = self._one("""SELECT
            (SELECT count(*) FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s) AS receipts,
            (SELECT count(*) FROM reconforge.procurement_partial_invoices WHERE tenant_id=%s AND order_id=%s) AS invoices""",
            (self.tenant_id, row["id"], self.tenant_id, row["id"]))
        result["lines"] = lines
        if self.receipt_after > counts["receipts"] or self.invoice_after > counts["invoices"]:
            raise ProcurementPartialError("procurement_partial_cursor_invalid", "Document cursors cannot exceed the retained source history.")
        result["pages"] = {"receipt_after": self.receipt_after, "invoice_after": self.invoice_after, "page_size": document_page_size(row["line_count"]),
            "receipt_count": counts["receipts"], "invoice_count": counts["invoices"],
            "next_receipt_after": result["receipts"][-1]["sequence"] if result["receipts"] and result["receipts"][-1]["sequence"] < counts["receipts"] else None,
            "next_invoice_after": result["invoices"][-1]["sequence"] if result["invoices"] and result["invoices"][-1]["sequence"] < counts["invoices"] else None}
        return result

    def create_multiline(self, request: MultilineProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request, total = normalize_multiline(request)
        header = asdict(request)
        header.pop("lines")
        payload = {**header, **asdict(request.lines[0]), "lines": [asdict(line) for line in request.lines]}
        original = ProcurementPreparation(**{field.name: payload[field.name] for field in fields(ProcurementPreparation)})
        with self.connection.transaction():
            self._scope_transaction()
            scope = self.shared._scope(original)
            order_id = platform_id("PPORDER", scope["workspace_id"], request.number)
            row = {**scope, "id": order_id, "request_json": payload, "total_minor": total}
            self.shared._authorize(row, actor, "create")
            digest, replay = self._command(row, command_id, "create", payload, actor)
            if replay is not None:
                self.shared._authorize(self._order(order_id), actor, "create")
                self.connection.execute("SELECT reconforge.pp_verify_order(%s,%s)", (self.tenant_id, order_id))
                return replay
            self._one("""SELECT id FROM reconforge.ap_suppliers WHERE tenant_id=%s AND workspace_id=%s AND supplier_code=%s
                AND status='Active' AND (organization_id IS NULL OR organization_id=%s) AND (legal_entity_id IS NULL OR legal_entity_id=%s)
                AND currency_code=%s FOR SHARE""", (self.tenant_id, scope["workspace_id"], request.supplier_code,
                scope["organization_id"], scope["legal_entity_id"], request.currency_code))
            retained: list[dict[str, Any]] = []
            clearing: str | None = None
            for line in request.lines:
                item = self.receipts.inventory._item(scope["workspace_id"], line.item_code, active=True)
                if item["item_type"] not in ("Stock", "Consumable") or item["tracking_mode"] != "None" or not item["uom_active"] or item["organization_id"] not in (None, scope["organization_id"]):
                    raise ProcurementPartialError("procurement_partial_item_invalid", "Active untracked stock items and their exact units are required.")
                quantity_to_scaled(line.quantity, item["decimal_places"])
                location = self.receipts.inventory._location_reference(scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], line.location_code)
                if location is None or location["location_type"] != "Internal" or location["allow_negative"]:
                    raise ProcurementPartialError("procurement_partial_location_invalid", "An active internal location with negative stock disabled is required.")
                policy = self._one("""SELECT id,receipt_clearing_account_id FROM reconforge.inventory_valuation_policies
                    WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND policy_code=%s
                    AND active AND costing_method='FIFO' AND currency_code=%s FOR SHARE""",
                    (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], line.policy_code, request.currency_code))
                if clearing is not None and clearing != policy["receipt_clearing_account_id"]:
                    raise ProcurementPartialError("procurement_partial_mapping_invalid", "Purchase lines require one exact receipt clearing account for payable accrual.")
                clearing = policy["receipt_clearing_account_id"]
                retained.append({"item": item, "location": location, "policy": policy})
            native = self.payables.create_purchase_order(po_number=request.number, supplier_code=request.supplier_code,
                order_date=request.posting_date, currency_code=request.currency_code,
                lines=[PurchaseOrderLineInput(item_code=line.item_code, ordered_quantity=line.quantity, unit_price_minor=line.unit_price_minor) for line in request.lines],
                workspace=scope["workspace_id"], organization_code=request.organization_code, entity_code=request.entity_code,
                idempotency_key=platform_id("PPCMD", order_id, command_id, "order"), actor_label=actor.user_id)
            self.connection.execute("""INSERT INTO reconforge.procurement_partial_orders(tenant_id,id,workspace_id,organization_id,legal_entity_id,
                number,request_json,total_minor,purchase_order_id,creator_actor_id,multiline,line_count) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,true,%s)""",
                (self.tenant_id, order_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], request.number,
                 canonical_json(payload), total, native["id"], actor.user_id, len(request.lines)))
            for sequence, (line, master, native_line) in enumerate(zip(request.lines, retained, native["lines"], strict=True), 1):
                _, amount = line_total(line.quantity, line.unit_price_minor)
                self.connection.execute("""INSERT INTO reconforge.procurement_partial_order_lines(tenant_id,id,order_id,sequence,
                    purchase_order_line_id,item_id,item_code,uom_id,quantity_precision,location_id,location_code,policy_id,policy_code,
                    quantity,quantity_text,unit_price_minor,total_minor) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (self.tenant_id, platform_id("PPLINE", order_id, sequence), order_id, sequence, native_line["id"], master["item"]["id"],
                     line.item_code, master["item"]["uom_id"], master["item"]["decimal_places"], master["location"]["id"], line.location_code,
                     master["policy"]["id"], line.policy_code, Decimal(line.quantity), line.quantity, line.unit_price_minor, amount))
            return self._remember(order_id, command_id, "create", digest, payload, actor, created=True)

    def prepare_receipt_line(self, order_id: str, line_id: str, request: PartialQuantityPreparation, *, expected_version: int,
                             command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            self._scope_transaction()
            line = self._one("SELECT * FROM reconforge.procurement_partial_order_lines WHERE tenant_id=%s AND order_id=%s AND id=%s",
                (self.tenant_id, order_id, exact_text(line_id)))
            request, amount = normalize_part(request, line["unit_price_minor"])
            payload = {**asdict(request), "line_id": line_id, "expected_version": expected_version}
            row, digest, replay = self._begin(order_id, "prepare-receipt-line", expected_version, command_id, payload, actor)
            if replay is not None:
                return replay
            self._require_multiline(row)
            summary = self._one("SELECT count(*) AS count,COALESCE(max(sequence),0) AS sequence FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s",
                (self.tenant_id, order_id))
            self._approved_multiline(row, summary["count"])
            quantities = tuple(item["quantity_text"] for item in self.connection.execute("SELECT quantity_text FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s AND order_line_id=%s",
                (self.tenant_id, order_id, line_id)).fetchall())
            reserve_quantity(request.quantity, line["quantity_text"], quantities)
            quantity_to_scaled(request.quantity, line["quantity_precision"])
            sequence, number = summary["sequence"] + 1, "PPR-" + row["number"] + "-" + str(summary["sequence"] + 1)
            original = row["request_json"]
            plan = self.receipts.prepare_receipt(ReceiptPreparation(receipt_number=number, posting_date=request.posting_date,
                period_id=request.period_id, item_code=line["item_code"], location_code=line["location_code"], quantity=request.quantity,
                total_value_minor=amount, policy_code=line["policy_code"], workspace=row["workspace_id"],
                organization_code=original["organization_code"], entity_code=original["entity_code"], reason=request.reason),
                command_id=platform_id("PPCMD", order_id, command_id, "receipt"), actor=actor)
            if plan["currency_policy"]["currency_code"] != original["currency_code"]:
                raise ProcurementPartialError("procurement_partial_currency_invalid", "Stock and supplier functional currencies must match.")
            self.connection.execute("""INSERT INTO reconforge.procurement_partial_receipts(tenant_id,id,order_id,sequence,number,
                quantity,quantity_text,total_minor,posting_date,period_id,receipt_plan_id,created_version,order_line_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, platform_id("PPRECEIPT", order_id, sequence), order_id, sequence, number, Decimal(request.quantity),
                 request.quantity, amount, request.posting_date, request.period_id, plan["plan_id"], row["row_version"] + 1, line_id))
            return self._remember(order_id, command_id, "prepare-receipt-line", digest, payload, actor)

    def _require_multiline(self, row: Mapping[str, Any]) -> None:
        if not row.get("multiline", False):
            raise ProcurementPartialError("procurement_partial_multiline_required", "This operation requires an actual multiline purchase owner.")

    def _approved_multiline(self, row: Mapping[str, Any], count: int) -> None:
        if row["stage"] != 2 or count >= MAX_ENTERPRISE_PARTS:
            raise ProcurementPartialError("procurement_partial_state_conflict", "An approved enterprise order and available document capacity are required.")

    def match_invoice_lines(self, order_id: str, request: MultilineInvoicePreparation, *, expected_version: int,
                            command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = normalize_invoice_lines(request)
        with self.connection.transaction():
            self._scope_transaction()
            normalized = []
            originals = []
            total = 0
            for allocation in request.lines:
                line = self._one("SELECT * FROM reconforge.procurement_partial_order_lines WHERE tenant_id=%s AND order_id=%s AND id=%s",
                    (self.tenant_id, order_id, allocation.line_id))
                part, amount = normalize_part(PartialQuantityPreparation(quantity=allocation.quantity, posting_date=request.posting_date,
                    period_id=request.period_id, reason=request.reason), line["unit_price_minor"])
                quantity_to_scaled(part.quantity, line["quantity_precision"])
                normalized.append({"line_id": allocation.line_id, "quantity": part.quantity})
                originals.append((line, part.quantity, amount))
                total += amount
            if total > 9_000_000_000_000_000_000:
                raise ProcurementPartialError("procurement_partial_amount_invalid", "Invoice amount exceeds supported exact minor units.")
            payload = {"lines": normalized, "posting_date": request.posting_date, "period_id": request.period_id,
                       "reason": request.reason, "expected_version": expected_version}
            row, digest, replay = self._begin(order_id, "match-invoice-lines", expected_version, command_id, payload, actor)
            if replay is not None:
                return replay
            self._require_multiline(row)
            summary = self._one("SELECT count(*) AS count,COALESCE(max(sequence),0) AS sequence FROM reconforge.procurement_partial_invoices WHERE tenant_id=%s AND order_id=%s",
                (self.tenant_id, order_id))
            self._approved_multiline(row, summary["count"])
            for line, quantity, _ in originals:
                capacity = self._one("SELECT COALESCE(sum(quantity),0)::text AS quantity FROM reconforge.procurement_partial_receipts WHERE tenant_id=%s AND order_id=%s AND order_line_id=%s AND stage=2",
                    (self.tenant_id, order_id, line["id"]))["quantity"]
                allocated = tuple(item["quantity_text"] for item in self.connection.execute("SELECT quantity_text FROM reconforge.procurement_partial_invoice_lines WHERE tenant_id=%s AND order_id=%s AND order_line_id=%s",
                    (self.tenant_id, order_id, line["id"])).fetchall())
                reserve_quantity(quantity, capacity, allocated)
            sequence, number = summary["sequence"] + 1, "PPI-" + row["number"] + "-" + str(summary["sequence"] + 1)
            original = row["request_json"]
            invoice = self.payables.create_supplier_invoice(invoice_number=number, supplier_code=original["supplier_code"],
                invoice_date=request.posting_date, currency_code=original["currency_code"], total_minor=total,
                purchase_order_id=row["purchase_order_id"], workspace=row["workspace_id"], organization_code=original["organization_code"],
                entity_code=original["entity_code"], actor_label=actor.user_id, idempotency_key=platform_id("PPCMD", order_id, command_id, "invoice"),
                lines=[SupplierInvoiceLineInput(purchase_order_line_id=line["purchase_order_line_id"], invoiced_quantity=quantity,
                    unit_price_minor=line["unit_price_minor"], line_total_minor=amount) for line, quantity, amount in originals])
            self.payables.submit_supplier_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.user_id)
            matched = self.payables.run_three_way_match(invoice["id"], actor_label=actor.user_id)
            if matched.status != "Passed":
                raise ProcurementPartialError("procurement_partial_match_conflict", "Supplier invoice failed exact three-way matching.")
            identifier = platform_id("PPINVOICE", order_id, sequence)
            self.connection.execute("""INSERT INTO reconforge.procurement_partial_invoices(tenant_id,id,order_id,sequence,number,quantity,
                quantity_text,total_minor,posting_date,period_id,native_invoice_id,created_version) VALUES(%s,%s,%s,%s,%s,NULL,NULL,%s,%s,%s,%s,%s)""",
                (self.tenant_id, identifier, order_id, sequence, number, total, request.posting_date, request.period_id, invoice["id"], row["row_version"] + 1))
            for allocation_sequence, ((line, quantity, amount), native_line) in enumerate(zip(originals, invoice["lines"], strict=True), 1):
                self.connection.execute("""INSERT INTO reconforge.procurement_partial_invoice_lines(tenant_id,id,order_id,invoice_id,order_line_id,
                    native_invoice_line_id,sequence,quantity,quantity_text,total_minor) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (self.tenant_id, platform_id("PPILINE", identifier, allocation_sequence), order_id, identifier, line["id"], native_line["id"],
                     allocation_sequence, Decimal(quantity), quantity, amount))
            return self._remember(order_id, command_id, "match-invoice-lines", digest, payload, actor)

    def document_page(self, order_id: str, *, receipt_after: int = 0, invoice_after: int = 0, actor: PostingActor) -> dict[str, Any]:
        if type(receipt_after) is not int or type(invoice_after) is not int or not 0 <= receipt_after <= MAX_ENTERPRISE_PARTS or not 0 <= invoice_after <= MAX_ENTERPRISE_PARTS:
            raise ProcurementPartialError("procurement_partial_cursor_invalid", "Document cursors must be bounded retained sequence numbers.")
        self.receipt_after, self.invoice_after = receipt_after, invoice_after
        return self.get(order_id, actor=actor)

    def payment_page(self, order_id: str, invoice_id: str, *, after: str = "", actor: PostingActor) -> dict[str, Any]:
        from reconforge.infrastructure.postgres_financial_installments import PostgresFinancialInstallmentsRepository
        if len(after) > 160:
            raise ProcurementPartialError("procurement_partial_cursor_invalid", "A bounded payment plan keyset cursor is required.")
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            row = self._order(order_id)
            self.shared._authorize(row, actor, "read")
            self.connection.execute("SELECT reconforge.pp_verify_order(%s,%s)", (self.tenant_id, order_id))
            invoice = self._document(order_id, invoice_id, "invoice")
            identifiers = self.connection.execute("""SELECT id FROM reconforge.financial_installment_plans
                WHERE tenant_id=%s AND payload->>'source_kind'='APPayment' AND source_id=%s AND id>%s ORDER BY id LIMIT 26""",
                (self.tenant_id, invoice["native_invoice_id"], after)).fetchall()
            finance = PostgresFinancialInstallmentsRepository(self.connection, self.tenant_id)
            keys = ("id", "workspace_id", "organization_id", "legal_entity_id", "source_id", "source_kind", "entry_id", "period_id",
                    "posting_date", "currency_code", "currency_precision", "status", "phase", "plan_digest", "validation_digest",
                    "preparer_actor_id", "reviewer_actor_id", "posting_effect_id", "payment_link_id", "invoice_version")
            records = []
            for identifier in identifiers[:25]:
                plan = finance.get(identifier["id"], actor=actor)
                records.append({**{key: plan[key] for key in keys}, "amount_minor": str(plan["amount_minor"]),
                                "allocated_before_minor": str(plan["allocated_before_minor"])})
            return {"order_id": order_id, "invoice_id": invoice_id, "native_invoice_id": invoice["native_invoice_id"],
                    "records": records, "next_after": records[-1]["id"] if len(identifiers) > 25 else None}

    def order_page(self, workspace: str, *, actor: PostingActor, after: str = "", page_size: int = 25) -> dict[str, Any]:
        if type(page_size) is not int or not 1 <= page_size <= 50 or len(after) > 160:
            raise ProcurementPartialError("procurement_partial_cursor_invalid", "A bounded keyset cursor and page size are required.")
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.receipts._actor(actor, frozenset({"payables.read", "inventory.read", "finance_core.read"}), mutation=False)
            records = self.connection.execute("""SELECT id,number,workspace_id,organization_id,legal_entity_id,purchase_order_id,row_version,stage,total_minor,
                multiline,line_count,created_at FROM reconforge.procurement_partial_orders WHERE tenant_id=%s AND workspace_id=%s AND id>%s ORDER BY id LIMIT %s""",
                (self.tenant_id, workspace, after, page_size + 1)).fetchall()
            result = []
            for record in records[:page_size]:
                row = self._order(record["id"])
                self.shared._authorize(row, actor, "read")
                result.append({**dict(record), "stage": ORDER_STAGES[record["stage"]], "total_minor": str(record["total_minor"])})
            return json_value({"records": result, "next_after": result[-1]["id"] if len(records) > page_size else None, "page_size": page_size})

    def item_catalog_page(self, workspace: str, organization_id: str, *, actor: PostingActor, after: str = "", search: str = "") -> dict[str, Any]:
        if len(after) > 64 or len(search) > 64:
            raise ProcurementPartialError("procurement_partial_cursor_invalid", "Item search and keyset cursor support at most 64 characters.")
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.receipts._actor(actor, frozenset({"payables.read", "inventory.read", "finance_core.read"}), mutation=False)
            records = self.connection.execute("""SELECT i.item_code AS code,i.name,u.uom_code,u.decimal_places FROM reconforge.inventory_items i
                JOIN reconforge.inventory_units_of_measure u ON u.tenant_id=i.tenant_id AND u.id=i.uom_id
                WHERE i.tenant_id=%s AND i.workspace_id=%s AND (i.organization_id IS NULL OR i.organization_id=%s)
                AND i.active AND u.active AND i.item_type IN ('Stock','Consumable') AND i.tracking_mode='None' AND i.item_code>%s
                AND (strpos(lower(i.item_code),lower(%s))>0 OR strpos(lower(i.name),lower(%s))>0) ORDER BY i.item_code LIMIT 51""",
                (self.tenant_id, workspace, organization_id, after, search, search)).fetchall()
            return json_value({"records": [dict(item) for item in records[:50]], "next_after": records[49]["code"] if len(records) > 50 else None})

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
