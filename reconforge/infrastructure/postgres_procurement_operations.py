"""One outer transaction composes AP, reviewed stock/FIFO/GL and payment evidence."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from reconforge.application.payables import PurchaseOrderLineInput, SupplierInvoiceLineInput
from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload
from reconforge.domain.inventory_receipt_posting import (
    COMMIT_PERMISSIONS,
    PREPARE_PERMISSIONS,
    REVIEW_PERMISSIONS,
    ReceiptPreparation,
    exact_text,
)
from reconforge.domain.procurement_operations import (
    APPROVE,
    MANAGE,
    READ,
    STAGES,
    ProcurementError,
    ProcurementPreparation,
    line_total,
    normalize,
)
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_receipt_posting import PostgresInventoryReceiptPostingRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_payables_payment_link import PostgresPayablesPaymentLinkRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.platform.common import current_server_principal, platform_id

OPERATIONS = ("submit-order", "approve-order", "prepare-receipt", "review-receipt", "receive",
              "match-invoice", "approve-invoice", "prepare-accrual", "review-accrual", "post-accrual",
              "prepare-payment", "review-payment", "pay")
PERMISSIONS = {
    "create": MANAGE, "submit-order": MANAGE, "approve-order": APPROVE,
    "prepare-receipt": MANAGE | PREPARE_PERMISSIONS, "review-receipt": APPROVE | REVIEW_PERMISSIONS,
    "receive": MANAGE | COMMIT_PERMISSIONS, "match-invoice": MANAGE | frozenset({"payables.match"}),
    "approve-invoice": APPROVE, "prepare-accrual": MANAGE | frozenset({"finance_core.manage"}),
    "review-accrual": APPROVE | frozenset({"finance_core.validate"}),
    "post-accrual": APPROVE | frozenset({"finance_core.post"}),
    "prepare-payment": frozenset({"payables.settle", "finance_core.manage"}),
    "review-payment": frozenset({"payables.settle", "finance_core.validate"}),
    "pay": frozenset({"payables.settle", "finance_core.post"}),
}


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


class PostgresProcurementOperationsRepository:
    """Request-scoped owner. Every failed participant escapes and rolls back all effects."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, validate_tenant_id(tenant_id)
        self.payables = PostgresPayablesRepository(connection, tenant_id)
        self.receipts = PostgresInventoryReceiptPostingRepository(connection, tenant_id, strict_command_actor=True)

    def _one(self, query: str, arguments: tuple[Any, ...]) -> dict[str, Any]:
        result = self.connection.execute(query, arguments).fetchone()
        if result is None:
            raise ProcurementError("procurement_not_found", "Procurement source is absent or outside current authority.")
        return dict(result)

    def _cycle(self, cycle_id: str, *, lock: bool = False) -> dict[str, Any]:
        return self._one("SELECT * FROM reconforge.procurement_cycles WHERE tenant_id=%s AND id=%s" +
            (" FOR UPDATE" if lock else ""), (self.tenant_id, exact_text(cycle_id)))

    def _scope(self, request: ProcurementPreparation) -> dict[str, Any]:
        return self._codes_scope(request.workspace, request.organization_code, request.entity_code)

    def _codes_scope(self, workspace_name: str, organization_code: str, entity_code: str) -> dict[str, Any]:
        workspace = self.payables._workspace_id(workspace_name)
        organization, entity = self.payables._scope_ids(workspace or "", organization_code=organization_code,
            entity_code=entity_code)
        if not organization or not entity:
            raise ProcurementError("procurement_scope_denied", "A canonical organization and entity are required.")
        return {"workspace_id": workspace, "organization_id": organization, "legal_entity_id": entity,
            "organization_code": organization_code, "entity_code": entity_code}

    def _authorize(self, row: Mapping[str, Any], actor: PostingActor, operation: str) -> None:
        required = READ | (PERMISSIONS[operation] if operation != "read" else frozenset())
        self.receipts._actor(actor, required, mutation=operation != "read")
        if not required.issubset(PostgresIdentityRepository(self.connection).user_permissions(tenant_id=self.tenant_id, user_id=actor.user_id)):
            raise ProcurementError("procurement_actor_denied", "Persisted current permissions no longer authorize this operation.")
        request = row.get("request_json", row)
        scope = {key: row[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
        scope.update(organization_code=request["organization_code"], entity_code=request["entity_code"])
        self.receipts._scope(scope)
        principal = current_server_principal()
        if principal is None:
            raise ProcurementError("procurement_actor_denied", "Current human authority is required.")
        currency = self._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
            (self.tenant_id, request["currency_code"]))
        total = int(row["total_minor"])
        factor = 10 ** currency["minor_units"]
        amount = Decimal(str(total) if factor == 1 else f"{total // factor}.{total % factor:0{currency['minor_units']}d}")
        for permission in required:
            if not evaluate_principal_access(principal, required_permission=permission, tenant_id=self.tenant_id,
                workspace_id=scope["workspace_id"], organization_id=scope["organization_id"], entity_id=scope["legal_entity_id"],
                amount=amount, authorized_tenant_ids=principal.authorized_tenant_ids,
                authorized_workspace_ids=principal.authorized_workspace_ids, authorized_organization_ids=principal.authorized_organization_ids,
                authorized_entity_ids=principal.authorized_legal_entity_ids).allowed:
                raise ProcurementError("procurement_scope_denied", "Procurement exceeds current scoped or amount authority.")

    def _command(self, workspace: str, cycle_id: str, command: str, operation: str,
                 payload: Mapping[str, Any], actor: PostingActor) -> tuple[str, dict[str, Any] | None]:
        command = exact_text(command)
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, "procurement-command", workspace, command]),))
        digest = digest_payload({"cycle_id": cycle_id, "operation": operation, "payload": payload, "actor_id": actor.user_id})
        retained = self.connection.execute("SELECT * FROM reconforge.procurement_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, workspace, command)).fetchone()
        if retained:
            if retained["actor_id"] != actor.user_id or retained["cycle_id"] != cycle_id or retained["request_digest"] != digest:
                raise ProcurementError("procurement_command_conflict", "Command is already bound to another exact request or actor.")
            return digest, dict(retained["response_json"])
        return digest, None

    def _remember(self, row: Mapping[str, Any], operation: str, command: str, digest: str, actor: PostingActor, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = self._view(row, actor)
        event_id = platform_id("PCOB", row["id"], row["row_version"])
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="procurement_cycle", object_id=row["id"], action="procurement_" + operation.replace("-", "_"),
            metadata={"stage": STAGES[row["stage"]], "row_version": row["row_version"], "request_digest": digest})
        self.connection.execute("""INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,
            workspace_id,organization_id,legal_entity_id,payload) VALUES(%s,%s,'procurement.cycle_changed','procurement_cycle',%s,%s,%s,%s,%s::jsonb)""",
            (self.tenant_id, event_id, row["id"], row["workspace_id"], row["organization_id"], row["legal_entity_id"],
             canonical_json({"cycle_id": row["id"], "stage": STAGES[row["stage"]], "row_version": row["row_version"], "audit_event_id": audit.id})))
        self.connection.execute("""INSERT INTO reconforge.procurement_commands(tenant_id,workspace_id,command_id,cycle_id,actor_id,
            operation,request_json,cycle_version,request_digest,response_json,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s,%s)""",
            (self.tenant_id, row["workspace_id"], command, row["id"], actor.user_id, operation, canonical_json(payload), row["row_version"], digest, canonical_json(response), audit.id, event_id))
        return response

    def create(self, request: ProcurementPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = normalize(request)
        _, total = line_total(request.quantity, request.unit_price_minor)
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            scope = self._scope(request)
            self._authorize({**scope, "request_json": asdict(request), "total_minor": total}, actor, "create")
            cycle_id = platform_id("PCYCLE", scope["workspace_id"], request.number)
            digest, replay = self._command(scope["workspace_id"], cycle_id, command_id, "create", asdict(request), actor)
            if replay is not None:
                self._authorize(self._cycle(cycle_id), actor, "create")
                return replay
            if self.connection.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] != "read committed":
                raise ProcurementError("procurement_isolation_required", "Procurement writes require READ COMMITTED.")
            self._one("""SELECT id FROM reconforge.ap_suppliers WHERE tenant_id=%s AND workspace_id=%s AND supplier_code=%s
                AND status='Active' AND (organization_id IS NULL OR organization_id=%s) AND (legal_entity_id IS NULL OR legal_entity_id=%s)
                AND currency_code=%s FOR SHARE""", (self.tenant_id, scope["workspace_id"], request.supplier_code,
                scope["organization_id"], scope["legal_entity_id"], request.currency_code))
            order = self.payables.create_purchase_order(po_number=request.number, supplier_code=request.supplier_code,
                order_date=request.posting_date, currency_code=request.currency_code,
                lines=[PurchaseOrderLineInput(item_code=request.item_code, ordered_quantity=request.quantity, unit_price_minor=request.unit_price_minor)],
                workspace=scope["workspace_id"], organization_code=request.organization_code, entity_code=request.entity_code,
                idempotency_key=platform_id("PCMD", command_id, "order"), actor_label=actor.username)
            self.connection.execute("""INSERT INTO reconforge.procurement_cycles(tenant_id,id,workspace_id,organization_id,legal_entity_id,
                number,request_json,total_minor,purchase_order_id,creator_actor_id) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                (self.tenant_id, cycle_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], request.number,
                 canonical_json(asdict(request)), total, order["id"], actor.user_id))
            return self._remember(self._cycle(cycle_id), "create", command_id, digest, actor, asdict(request))

    def act(self, cycle_id: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, actor: PostingActor) -> dict[str, Any]:
        if operation not in OPERATIONS or isinstance(expected_version, bool) or expected_version < 1:
            raise ProcurementError("procurement_command_invalid", "A supported command and positive expected version are required.")
        reason = exact_text(reason, maximum=500)
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            row = self._cycle(cycle_id)
            self._authorize(row, actor, operation)
            digest, replay = self._command(row["workspace_id"], cycle_id, command_id, operation,
                {"expected_version": expected_version, "reason": reason}, actor)
            if replay is not None:
                self._authorize(self._cycle(cycle_id), actor, operation)
                return replay
            row = self._cycle(cycle_id, lock=True)
            if row["row_version"] != expected_version or row["stage"] >= len(OPERATIONS) or OPERATIONS[row["stage"]] != operation:
                raise ProcurementError("procurement_version_conflict", "Procurement changed or the next command differs; reload before proceeding.")
            request = ProcurementPreparation(**row["request_json"])
            order = self.payables.get_purchase_order(row["purchase_order_id"])
            changes: dict[str, Any] = {}
            command = platform_id("PCMD", cycle_id, command_id, operation)
            if operation == "submit-order":
                self.payables.submit_purchase_order(order["id"], expected_version=order["row_version"], actor_label=actor.username)
            elif operation == "approve-order":
                self.payables.approve_purchase_order(order["id"], expected_version=order["row_version"], actor_label=actor.username)
            elif operation == "prepare-receipt":
                plan = self.receipts.prepare_receipt(ReceiptPreparation(receipt_number="GR-" + request.number,
                    posting_date=request.posting_date, period_id=request.period_id, item_code=request.item_code,
                    location_code=request.location_code, quantity=request.quantity, total_value_minor=row["total_minor"],
                    policy_code=request.policy_code, workspace=row["workspace_id"], organization_code=request.organization_code,
                    entity_code=request.entity_code, reason=reason), command_id=command, actor=actor)
                if plan["currency_policy"]["currency_code"] != request.currency_code:
                    raise ProcurementError("procurement_currency_invalid", "Supplier and FIFO functional currencies must match.")
                changes["receipt_plan_id"] = plan["plan_id"]
            elif operation == "review-receipt":
                view = self.receipts.get_plan(row["receipt_plan_id"], actor=actor)
                self.receipts.review(row["receipt_plan_id"], expected_plan_digest=view["plan"]["plan_digest"],
                    command_id=command, reason=reason, actor=actor)
            elif operation == "receive":
                view = self.receipts.get_plan(row["receipt_plan_id"], actor=actor)
                review = view["review"]
                if review is None:
                    raise ProcurementError("procurement_review_required", "Receiving requires retained independent review.")
                self.receipts.commit(row["receipt_plan_id"], expected_review_digest=review["review_digest"],
                    command_id=command, reason=reason, actor=actor)
                receipt = self.payables.post_receipt(receipt_number="GR-" + request.number, purchase_order_id=order["id"],
                    receipt_date=request.posting_date, quantities={order["lines"][0]["id"]: request.quantity},
                    workspace=row["workspace_id"], idempotency_key=command, actor_label=actor.username)
                changes["goods_receipt_id"] = receipt["id"]
            elif operation == "match-invoice":
                line = order["lines"][0]
                invoice = self.payables.create_supplier_invoice(invoice_number="INV-" + request.number, supplier_code=request.supplier_code,
                    invoice_date=request.posting_date, currency_code=request.currency_code, total_minor=row["total_minor"],
                    purchase_order_id=order["id"], workspace=row["workspace_id"], organization_code=request.organization_code,
                    entity_code=request.entity_code, idempotency_key=command, actor_label=actor.username,
                    lines=[SupplierInvoiceLineInput(purchase_order_line_id=line["id"], invoiced_quantity=request.quantity,
                        unit_price_minor=request.unit_price_minor, line_total_minor=row["total_minor"])])
                self.payables.submit_supplier_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
                result = self.payables.run_three_way_match(invoice["id"], actor_label=actor.username)
                if result.status != "Passed":
                    raise ProcurementError("procurement_match_failed", "The supplier invoice failed exact three-way matching.")
                changes["invoice_id"] = invoice["id"]
            elif operation == "approve-invoice":
                invoice = self.payables.get_supplier_invoice(row["invoice_id"])
                self.payables.approve_supplier_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            else:
                changes = self._finance(row, request, operation, command, reason, actor)
            self._advance(row, changes)
            return self._remember(self._cycle(cycle_id), operation, command_id, digest, actor, {"expected_version": expected_version, "reason": reason})

    def _advance(self, row: Mapping[str, Any], changes: Mapping[str, Any]) -> None:
        allowed = {"receipt_plan_id", "goods_receipt_id", "invoice_id", "accrual_plan_id", "payment_plan_id", "accrual_effect_id", "payment_effect_id", "payment_link_id"}
        if not set(changes).issubset(allowed):
            raise ProcurementError("procurement_link_invalid", "Unsupported engine link.")
        assignments = "".join("," + key + "=%s" for key in changes)
        self.connection.execute("UPDATE reconforge.procurement_cycles SET stage=stage+1,row_version=row_version+1,updated_at=now()" +
            assignments + " WHERE tenant_id=%s AND id=%s", (*changes.values(), self.tenant_id, row["id"]))

    def _finance(self, row: Mapping[str, Any], request: ProcurementPreparation, operation: str,
                  command: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        from reconforge.domain.operational_finance import OperationalFinancePreparation
        from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
        finance = PostgresOperationalFinanceRepository(self.connection, self.tenant_id)
        payment = "payment" in operation or operation == "pay"
        field = "payment_plan_id" if payment else "accrual_plan_id"
        if operation.startswith("prepare-"):
            receipt = self.receipts.get_plan(row["receipt_plan_id"], actor=actor)
            clearing = self._one("SELECT account_code FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, receipt["plan"]["mapping"]["receipt_clearing_account_id"]))["account_code"]
            plan = finance.prepare(OperationalFinancePreparation(workspace_id=row["workspace_id"], organization_id=row["organization_id"],
                legal_entity_id=row["legal_entity_id"], organization_code=request.organization_code, entity_code=request.entity_code,
                source_kind="APPayment" if payment else "APInvoice", source_id=row["invoice_id"], journal_code=request.journal_code,
                period_id=request.period_id, posting_date=request.posting_date,
                debit_account_code=request.ap_account_code if payment else clearing,
                credit_account_code=request.cash_account_code if payment else request.ap_account_code,
                reason=reason), command_id=command, actor=actor)
            return {field: plan["id"]}
        plan = finance.get(row[field], actor=actor)
        if operation.startswith("review-"):
            finance.review(row[field], expected_plan_digest=plan["plan_digest"], command_id=command, reason=reason, actor=actor)
            return {}
        result = finance.post(row[field], expected_plan_digest=plan["plan_digest"], command_id=command, reason=reason, actor=actor)
        if not payment:
            return {"accrual_effect_id": result["posting_effect_id"]}
        invoice = self.payables.get_supplier_invoice(row["invoice_id"])
        accounts = {}
        for key, account in (("ap_account_id", request.ap_account_code), ("cash_account_id", request.cash_account_code)):
            accounts[key] = self._one("SELECT id FROM reconforge.finance_accounts WHERE tenant_id=%s AND workspace_id=%s AND account_code=%s",
                (self.tenant_id, row["workspace_id"], account))["id"]
        link = PostgresPayablesPaymentLinkRepository(self.connection, self.tenant_id).link_finance_payment(invoice["id"],
            finance_effect_id=result["posting_effect_id"], **accounts, expected_invoice_version=invoice["row_version"],
            command_id=command, actor_label=actor.user_id)
        return {"payment_effect_id": result["posting_effect_id"], "payment_link_id": link["payment_link_id"]}

    def _view(self, row: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        self.connection.execute("SELECT reconforge.procurement_verify_cycle(c) FROM reconforge.procurement_cycles c WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, row["id"]))
        if row["accrual_plan_id"] or row["payment_plan_id"]:
            from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
            finance = PostgresOperationalFinanceRepository(self.connection, self.tenant_id)
            for field in ("accrual_plan_id", "payment_plan_id"):
                if row[field]:
                    finance.get(row[field], actor=actor)
        request = dict(row["request_json"])
        request["unit_price_minor"] = str(request["unit_price_minor"])
        cycle = {**{key: row[key] for key in ("id", "workspace_id", "organization_id", "legal_entity_id", "number", "row_version",
            "purchase_order_id", "receipt_plan_id", "goods_receipt_id", "invoice_id", "accrual_plan_id", "payment_plan_id",
            "accrual_effect_id", "payment_effect_id", "payment_link_id")}, "stage": STAGES[row["stage"]],
            "total_minor": str(row["total_minor"]), "request": request,
            "next_action": OPERATIONS[row["stage"]] if row["stage"] < len(OPERATIONS) else ""}
        receipt = self.receipts.get_plan(row["receipt_plan_id"], actor=actor) if row["receipt_plan_id"] else None
        return json_value({"cycle": cycle, "receipt": receipt})

    def get(self, cycle_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            row = self._cycle(cycle_id)
            self._authorize(row, actor, "read")
            return self._view(row, actor)

    def list_cycles(self, workspace: str, *, actor: PostingActor) -> list[Mapping[str, Any]]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.receipts._actor(actor, READ, mutation=False)
            workspace_id = self.payables._workspace_id(workspace)
            rows = self.connection.execute("SELECT * FROM reconforge.procurement_cycles WHERE tenant_id=%s AND workspace_id=%s ORDER BY created_at DESC,id LIMIT 50",
                (self.tenant_id, workspace_id)).fetchall()
            result = []
            for row in rows:
                self._authorize(row, actor, "read")
                result.append(self._view(row, actor)["cycle"])
            return result

    def options(self, workspace: str, organization: str, entity: str, *, actor: PostingActor) -> dict[str, Any]:
        """Bounded current master references, never synthetic fixture identifiers."""
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.receipts._actor(actor, READ, mutation=False)
            scope = self._codes_scope(workspace, organization, entity)
            self.receipts._scope(scope)
            parameters = (self.tenant_id, scope["workspace_id"])
            suppliers = self.connection.execute("""SELECT supplier_code AS code,name,currency_code FROM reconforge.ap_suppliers WHERE tenant_id=%s AND workspace_id=%s
                AND status='Active' AND (organization_id IS NULL OR organization_id=%s) AND (legal_entity_id IS NULL OR legal_entity_id=%s)
                ORDER BY supplier_code LIMIT 200""", (*parameters, scope["organization_id"], scope["legal_entity_id"])).fetchall()
            items = self.connection.execute("""SELECT item_code AS code,name FROM reconforge.inventory_items WHERE tenant_id=%s AND workspace_id=%s
                AND active AND item_type IN ('Stock','Consumable') AND tracking_mode='None' AND (organization_id IS NULL OR organization_id=%s)
                ORDER BY item_code LIMIT 200""", (*parameters, scope["organization_id"])).fetchall()
            locations = self.connection.execute("""SELECT w.warehouse_code||'/'||l.location_code AS code,l.name FROM reconforge.inventory_locations l
                JOIN reconforge.inventory_warehouses w ON w.tenant_id=l.tenant_id AND w.id=l.warehouse_id WHERE l.tenant_id=%s AND w.workspace_id=%s
                AND w.organization_id=%s AND (w.legal_entity_id IS NULL OR w.legal_entity_id=%s) AND w.active AND l.active AND l.location_type='Internal' AND NOT l.allow_negative
                ORDER BY code LIMIT 200""", (*parameters, scope["organization_id"], scope["legal_entity_id"])).fetchall()
            policies = self.connection.execute("""SELECT policy_code AS code,currency_code FROM reconforge.inventory_valuation_policies WHERE tenant_id=%s AND workspace_id=%s
                AND organization_id=%s AND legal_entity_id=%s AND active AND costing_method='FIFO' ORDER BY policy_code LIMIT 200""",
                (*parameters, scope["organization_id"], scope["legal_entity_id"])).fetchall()
            periods = self.connection.execute("""SELECT p.id,p.name,p.start_date,p.end_date FROM reconforge.fiscal_periods p JOIN reconforge.master_data_workspace_periods w
                ON w.tenant_id=p.tenant_id AND w.period_id=p.id WHERE p.tenant_id=%s AND w.workspace_id=%s AND p.status='Open' ORDER BY p.start_date DESC LIMIT 200""", parameters).fetchall()
            journals = self.connection.execute("""SELECT j.journal_code AS code,j.name,j.currency_code,c.chart_code FROM reconforge.finance_journals j
                JOIN reconforge.finance_charts c ON c.tenant_id=j.tenant_id AND c.id=j.chart_id WHERE j.tenant_id=%s AND j.workspace_id=%s
                AND j.organization_code=%s AND j.active AND c.active AND c.organization_code IN ('',%s) ORDER BY j.journal_code LIMIT 200""",
                (*parameters, organization, organization)).fetchall()
            accounts = self.connection.execute("""SELECT a.account_code AS code,a.name,a.account_type,c.chart_code FROM reconforge.finance_accounts a
                JOIN reconforge.finance_charts c ON c.tenant_id=a.tenant_id AND c.id=a.chart_id WHERE a.tenant_id=%s AND a.workspace_id=%s
                AND a.active AND a.allow_posting AND a.allow_manual_posting AND c.active AND c.organization_code IN ('',%s)
                AND a.account_type IN ('Asset','Liability') ORDER BY a.account_code LIMIT 200""", (*parameters, organization)).fetchall()
            catalogs = {"suppliers": suppliers, "items": items, "locations": locations, "policies": policies,
                "periods": periods, "journals": journals, "accounts": accounts}
            return json_value({key: [dict(row) for row in rows] for key, rows in catalogs.items()})

    def scopes(self, workspace: str, *, actor: PostingActor) -> list[dict[str, Any]]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self.receipts._actor(actor, READ, mutation=False)
            workspace_id = self.payables._workspace_id(workspace)
            rows = self.connection.execute("""SELECT o.id AS organization_id,o.organization_code,o.name AS organization_name,
                e.id AS legal_entity_id,e.entity_code,e.name AS entity_name,e.currency_code,%s AS workspace_id
                FROM reconforge.organizations o JOIN reconforge.legal_entities e ON e.tenant_id=o.tenant_id AND e.organization_id=o.id
                JOIN reconforge.master_data_workspace_organizations w ON w.tenant_id=o.tenant_id AND w.organization_id=o.id
                WHERE o.tenant_id=%s AND w.workspace_id=%s AND o.active AND e.active
                ORDER BY o.organization_code,e.entity_code LIMIT 200""", (workspace_id, self.tenant_id, workspace_id)).fetchall()
            principal = current_server_principal()
            if principal is None:
                raise ProcurementError("procurement_actor_denied", "Current human authority is required.")
            return [dict(row) for row in rows if all(not grants or row[key] in grants for key, grants in (
                ("workspace_id", principal.authorized_workspace_ids), ("organization_id", principal.authorized_organization_ids),
                ("legal_entity_id", principal.authorized_legal_entity_ids)))]
