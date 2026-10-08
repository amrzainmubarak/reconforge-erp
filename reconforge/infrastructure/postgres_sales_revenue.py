"""Complete service-sales commands over native AR and reviewed operational GL."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json, digest_payload, text
from reconforge.domain.operational_finance import OperationalFinancePreparation
from reconforge.domain.sales_revenue import SalesInvoicePreparation, SalesLine, SalesQuotation
from reconforge.infrastructure.postgres import validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_repository_scope import ensure_repository_tenant_scope
from reconforge.platform.common import current_server_principal, platform_id


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _public(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            key: str(item) if key.endswith("_minor") and type(item) is int else _public(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_public(item) for item in value]
    return value


class PostgresSalesRevenueRepository:
    """One selected tenant/workspace/entity and one outer ACID command owner."""

    def __init__(
        self,
        connection: Any,
        tenant_id: str,
        *,
        workspace_id: str,
        organization_id: str,
        legal_entity_id: str,
        organization_code: str,
        entity_code: str,
    ) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self.scope = {
            "workspace_id": text(workspace_id, "workspace"),
            "organization_id": text(organization_id, "organization"),
            "legal_entity_id": text(legal_entity_id, "entity"),
            "organization_code": text(organization_code, "organization code"),
            "entity_code": text(entity_code, "entity code"),
        }
        self.ar = PostgresReceivablesRepository(connection, self.tenant_id)
        self.finance = PostgresOperationalFinanceRepository(connection, self.tenant_id)
        self._command_requests: dict[str, dict[str, Any]] = {}

    def _actor(
        self,
        actor: PostingActor,
        permission: str,
        *,
        mutation: bool = True,
        amount: int | None = None,
        currency: str | None = None,
    ) -> None:
        actor.require(permission, mutation=mutation)
        principal = current_server_principal()
        if (
            principal is None
            or principal.user.id != actor.user_id
            or principal.user.username != actor.username
            or principal.user.disabled
            or (mutation and not principal.step_up_active)
        ):
            raise FinancePostingError("sales_actor_denied", "A current authenticated human is required.")
        persisted = self.connection.execute(
            "SELECT 1 FROM reconforge.identity_users WHERE tenant_id=%s AND id=%s AND username=%s AND NOT disabled FOR SHARE",
            (self.tenant_id, actor.user_id, actor.username),
        ).fetchone()
        permissions = PostgresIdentityRepository(self.connection).user_permissions(
            tenant_id=self.tenant_id, user_id=actor.user_id
        )
        if persisted is None or permission not in permissions:
            raise FinancePostingError("sales_actor_denied", "Current persisted permissions deny this command.")
        scaled = None
        if amount is not None and currency is not None:
            precision = self.connection.execute(
                "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active",
                (self.tenant_id, currency),
            ).fetchone()
            if precision is None:
                raise FinancePostingError("sales_currency_invalid", "Active currency master is required.")
            places = int(precision["minor_units"])
            factor = 10**places
            scaled = Decimal(str(amount) if places == 0 else f"{amount // factor}.{amount % factor:0{places}d}")
        decision = evaluate_principal_access(
            principal,
            required_permission=permission,
            tenant_id=self.tenant_id,
            workspace_id=self.scope["workspace_id"],
            organization_id=self.scope["organization_id"],
            entity_id=self.scope["legal_entity_id"],
            amount=scaled,
            authorized_tenant_ids=principal.authorized_tenant_ids or frozenset({self.tenant_id}),
            authorized_workspace_ids=principal.authorized_workspace_ids,
            authorized_organization_ids=principal.authorized_organization_ids,
            authorized_entity_ids=principal.authorized_legal_entity_ids,
        )
        if not decision.allowed:
            raise FinancePostingError("sales_scope_denied", "Current authority denies the selected scope or amount.")
        if mutation:
            self.connection.execute("SELECT set_config('app.sales_actor_id',%s,true)", (actor.user_id,))

    def _document(self, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        result = self.connection.execute(
            """SELECT * FROM reconforge.sales_revenue_documents WHERE tenant_id=%s AND id=%s
            AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s"""
            + (" FOR UPDATE" if lock else ""),
            (
                self.tenant_id,
                text(identifier, "document id"),
                self.scope["workspace_id"],
                self.scope["organization_id"],
                self.scope["legal_entity_id"],
            ),
        ).fetchone()
        if result is None:
            raise FinancePostingError("sales_source_missing", "Sales document is absent from the selected scope.")
        document = dict(result)
        self._verify_quotation(document)
        return document

    @staticmethod
    def _verify_quotation(document: Mapping[str, Any]) -> None:
        try:
            quotation = _json(document["quotation"])
            expected = SalesQuotation(
                number=quotation["number"],
                customer_code=quotation["customer_code"],
                business_date=quotation["business_date"],
                valid_until=quotation["valid_until"],
                currency_code=quotation["currency_code"],
                lines=tuple(
                    SalesLine(
                        description=line["description"],
                        quantity=line["quantity"],
                        unit_price_minor=line["gross_unit_price_minor"],
                        discount_basis_points=line["discount_basis_points"],
                    )
                    for line in quotation["lines"]
                ),
            ).snapshot()
            expected["monetary_policy"] = quotation["monetary_policy"]
            expected["digest"] = digest_payload({key: value for key, value in expected.items() if key != "digest"})
            if (
                quotation != expected
                or quotation["digest"] != document["quotation_digest"]
                or quotation["total_minor"] != document["total_minor"]
            ):
                raise ValueError("quote differs")
        except (KeyError, TypeError, ValueError) as exc:
            raise FinancePostingError(
                "sales_evidence_invalid", "Retained quotation does not reproduce its exact source."
            ) from exc

    def _view(self, document: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        self._actor(
            actor, "sales.read", mutation=False, amount=int(document["total_minor"]), currency=document["currency_code"]
        )
        result = dict(document)
        result.pop("tenant_id", None)
        for key in ("quotation", "invoice_parameters", "collection_parameters"):
            result[key] = _json(result[key])
        result["events"] = [
            dict(row)
            for row in self.connection.execute(
                """SELECT version,operation,actor_id,reason,audit_event_id,created_at
            FROM reconforge.sales_revenue_events WHERE tenant_id=%s AND document_id=%s ORDER BY version""",
                (self.tenant_id, document["id"]),
            )
        ]
        if document["invoice_id"]:
            invoice = self.ar.get_invoice(document["invoice_id"])
            result["invoice"] = {
                key: invoice[key]
                for key in (
                    "id",
                    "invoice_number",
                    "status",
                    "total_minor",
                    "outstanding_minor",
                    "allocated_minor",
                    "row_version",
                    "monetary_policy",
                )
            }
        for key in ("invoice_plan_id", "collection_plan_id"):
            if document[key]:
                result[key.removesuffix("_id")] = self.finance.get(document[key], actor=actor)
        if document["receipt_id"]:
            receipt = self.ar.get_receipt(document["receipt_id"])
            result["receipt"] = {
                key: receipt[key]
                for key in ("id", "receipt_number", "amount_minor", "allocated_minor", "status", "monetary_policy")
            }
        return _public(result)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            return self._view(self._document(identifier), actor)

    def list(self, *, actor: PostingActor, after: str = "") -> dict[str, Any]:
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._actor(actor, "sales.read", mutation=False)
            rows = list(
                self.connection.execute(
                    """SELECT id,number,status,currency_code,total_minor,row_version,created_by
                FROM reconforge.sales_revenue_documents WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s
                AND legal_entity_id=%s AND id COLLATE "C">%s COLLATE "C" ORDER BY id COLLATE "C" LIMIT 26""",
                    (
                        self.tenant_id,
                        self.scope["workspace_id"],
                        self.scope["organization_id"],
                        self.scope["legal_entity_id"],
                        after,
                    ),
                )
            )
            return {
                "documents": [_public(dict(row)) for row in rows[:25]],
                "next_cursor": rows[24]["id"] if len(rows) > 25 else None,
            }

    def _command(
        self, command_id: str, actor: PostingActor, operation: str, payload: Mapping[str, Any]
    ) -> tuple[str, dict[str, Any] | None]:
        command_id = text(command_id, "command id", maximum=100)
        request_payload = {
            "scope": self.scope,
            "actor_id": actor.user_id,
            "operation": operation,
            "payload": dict(payload),
        }
        request = digest_payload(request_payload)
        self._command_requests[request] = request_payload
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, self.scope["workspace_id"], "sales", command_id]),),
        )
        row = self.connection.execute(
            "SELECT * FROM reconforge.sales_revenue_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, self.scope["workspace_id"], command_id),
        ).fetchone()
        if row is not None:
            if row["request_digest"] != request or row["actor_id"] != actor.user_id or row["operation"] != operation:
                raise FinancePostingError("sales_command_conflict", "Command already binds different content or human.")
            source = self._document(row["document_id"])
            self._actor(
                actor, "sales.read", mutation=False, amount=int(source["total_minor"]), currency=source["currency_code"]
            )
            result = _json(row["result"])
            if (
                not isinstance(result, dict)
                or result.get("id") != source["id"]
                or result.get("quotation_digest") != source["quotation_digest"]
                or any(result.get(key) != source[key] for key in ("workspace_id", "organization_id", "legal_entity_id"))
                or result.get("total_minor") != str(source["total_minor"])
                or type(result.get("row_version")) is not int
                or not 1 <= result["row_version"] <= source["row_version"]
            ):
                raise FinancePostingError(
                    "sales_evidence_invalid", "Command acknowledgement lacks its retained sales source."
                )
            return request, result
        return request, None

    def _event(self, document: Mapping[str, Any], operation: str, reason: str, actor: PostingActor) -> None:
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor.username,
            actor_user_id=actor.user_id,
            object_type="sales_revenue",
            object_id=document["id"],
            action="sales." + operation,
            metadata={
                "source_digest": document["quotation_digest"],
                "version": document["row_version"],
                "status": document["status"],
                "invoice_id": document["invoice_id"],
                "receipt_id": document["receipt_id"],
            },
        )
        self.connection.execute(
            "INSERT INTO reconforge.sales_revenue_events(tenant_id,document_id,version,actor_id,operation,reason,status,audit_event_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.tenant_id,
                document["id"],
                document["row_version"],
                actor.user_id,
                operation,
                reason,
                document["status"],
                audit.id,
            ),
        )

    def _remember(
        self,
        document: Mapping[str, Any],
        command_id: str,
        operation: str,
        request: str,
        actor: PostingActor,
        result: Mapping[str, Any],
    ) -> None:
        self.connection.execute(
            """INSERT INTO reconforge.sales_revenue_commands
            (tenant_id,workspace_id,command_id,document_id,document_version,operation,actor_id,request_digest,request,result) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (
                self.tenant_id,
                self.scope["workspace_id"],
                command_id,
                document["id"],
                document["row_version"],
                operation,
                actor.user_id,
                request,
                canonical_json(self._command_requests[request]),
                canonical_json(result),
            ),
        )

    def create(self, quotation: SalesQuotation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        snapshot = quotation.snapshot()
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._actor(actor, "sales.manage", amount=snapshot["total_minor"], currency=snapshot["currency_code"])
            request, previous = self._command(command_id, actor, "create", snapshot)
            if previous is not None:
                return previous
            customer = self.connection.execute(
                """SELECT id FROM reconforge.ar_customers WHERE tenant_id=%s AND workspace_id=%s
                AND organization_id=%s AND legal_entity_id=%s AND customer_code=%s AND currency_code=%s AND status='Active' FOR SHARE""",
                (
                    self.tenant_id,
                    self.scope["workspace_id"],
                    self.scope["organization_id"],
                    self.scope["legal_entity_id"],
                    snapshot["customer_code"],
                    snapshot["currency_code"],
                ),
            ).fetchone()
            if customer is None:
                raise FinancePostingError(
                    "sales_customer_invalid", "An active customer in this exact entity/currency is required."
                )
            customer_record = self.ar.get_customer(customer["id"])
            snapshot["monetary_policy"] = customer_record["monetary_policy"]
            snapshot["digest"] = digest_payload({key: value for key, value in snapshot.items() if key != "digest"})
            identifier = platform_id("SALE", self.scope["workspace_id"], snapshot["number"])
            self.connection.execute(
                """INSERT INTO reconforge.sales_revenue_documents
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_id,number,quotation,quotation_digest,currency_code,total_minor,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""",
                (
                    self.tenant_id,
                    identifier,
                    self.scope["workspace_id"],
                    self.scope["organization_id"],
                    self.scope["legal_entity_id"],
                    customer["id"],
                    snapshot["number"],
                    canonical_json(snapshot),
                    snapshot["digest"],
                    snapshot["currency_code"],
                    snapshot["total_minor"],
                    actor.user_id,
                ),
            )
            document = self._document(identifier)
            self._event(document, "create", "Create service quotation", actor)
            result = self._view(document, actor)
            self._remember(document, command_id, "create", request, actor, result)
            return result

    def _run(
        self,
        identifier: str,
        operation: str,
        expected_version: int,
        reason: str,
        command_id: str,
        actor: PostingActor,
        permission: str,
        payload: Mapping[str, Any],
        change: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        if type(expected_version) is not int or expected_version < 1:
            raise FinancePostingError("sales_version_invalid", "Expected version requires a positive exact integer.")
        with self.connection.transaction():
            ensure_repository_tenant_scope(self.connection, self.tenant_id)
            self._actor(actor, permission)
            request, previous = self._command(
                command_id,
                actor,
                operation,
                {"id": identifier, "expected_version": expected_version, "reason": reason, **payload},
            )
            if previous is not None:
                return previous
            document = self._document(identifier, lock=True)
            self._actor(actor, permission, amount=int(document["total_minor"]), currency=document["currency_code"])
            if document["row_version"] != expected_version:
                raise FinancePostingError("sales_version_conflict", "Document changed; reload its current version.")
            updates = change(document)
            from psycopg import sql

            statement = sql.SQL(
                "UPDATE reconforge.sales_revenue_documents SET {},row_version=row_version+1,updated_at=now() WHERE tenant_id=%s AND id=%s"
            ).format(
                sql.SQL(",").join(
                    sql.SQL("{}=%s::jsonb" if key.endswith("_parameters") else "{}=%s").format(sql.Identifier(key))
                    for key in updates
                )
            )
            self.connection.execute(
                statement,
                tuple(canonical_json(value) if key.endswith("_parameters") else value for key, value in updates.items())
                + (self.tenant_id, identifier),
            )
            latest = self._document(identifier)
            self._event(latest, operation, reason, actor)
            result = self._view(latest, actor)
            self._remember(latest, command_id, operation, request, actor, result)
            return result

    @staticmethod
    def _status(document: Mapping[str, Any], expected: str) -> None:
        if document["status"] != expected:
            raise FinancePostingError("sales_state_conflict", "Operation is unavailable at the current sales stage.")

    def transition(
        self,
        identifier: str,
        *,
        operation: str,
        expected_version: int,
        reason: str,
        command_id: str,
        actor: PostingActor,
        reference: str = "",
        business_date: str = "",
    ) -> dict[str, Any]:
        def change(document: dict[str, Any]) -> dict[str, Any]:
            if operation == "cancel":
                if document["status"] not in {"Draft", "Submitted", "Approved", "Ordered"}:
                    raise FinancePostingError(
                        "sales_state_conflict", "Only an unfulfilled quotation/order can be cancelled."
                    )
                return {"status": "Cancelled"}
            source, target = {
                "submit": ("Draft", "Submitted"),
                "approve": ("Submitted", "Approved"),
                "order": ("Approved", "Ordered"),
                "fulfill": ("Ordered", "Fulfilled"),
            }.get(operation, ("", ""))
            self._status(document, source)
            if operation == "approve":
                if document["created_by"] == actor.user_id:
                    raise FinancePostingError(
                        "sales_self_approval_denied", "Quotation creator cannot approve their quotation."
                    )
                return {"status": target, "approved_by": actor.user_id, "approved_reason": reason}
            if operation == "order":
                day = date.fromisoformat(business_date)
                if day.isoformat() != business_date or business_date > _json(document["quotation"])["valid_until"]:
                    raise FinancePostingError("sales_date_invalid", "Order must be accepted within quotation validity.")
                return {"status": target, "order_reference": text(reference, "customer order reference")}
            if operation == "fulfill":
                day = date.fromisoformat(business_date)
                if day.isoformat() != business_date or business_date < _json(document["quotation"])["business_date"]:
                    raise FinancePostingError("sales_date_invalid", "Completion cannot precede the quotation date.")
                return {
                    "status": target,
                    "fulfillment_reference": text(reference, "service completion reference"),
                    "fulfillment_date": day,
                }
            return {"status": target}

        return self._run(
            identifier,
            operation,
            expected_version,
            reason,
            command_id,
            actor,
            "sales.approve" if operation == "approve" else "sales.manage",
            {"reference": reference, "business_date": business_date},
            change,
        )

    def prepare_invoice(
        self,
        identifier: str,
        preparation: SalesInvoicePreparation,
        *,
        expected_version: int,
        command_id: str,
        actor: PostingActor,
    ) -> dict[str, Any]:
        payload = preparation.payload()

        def change(document: dict[str, Any]) -> dict[str, Any]:
            self._status(document, "Fulfilled")
            if payload["invoice_date"] < str(document["fulfillment_date"]):
                raise FinancePostingError("sales_date_invalid", "Invoice cannot precede service completion.")
            self._actor(
                actor, "receivables.manage", amount=int(document["total_minor"]), currency=document["currency_code"]
            )
            snapshot = _json(document["quotation"])
            invoice = self.ar.create_invoice(
                invoice_number=payload["invoice_number"],
                customer_code=snapshot["customer_code"],
                invoice_date=payload["invoice_date"],
                due_date=payload["due_date"],
                currency_code=document["currency_code"],
                tax_minor=0,
                lines=[
                    ReceivableInvoiceLineInput(
                        description=line["description"],
                        quantity=line["quantity"],
                        unit_price_minor=line["unit_price_minor"],
                        line_total_minor=line["line_total_minor"],
                    )
                    for line in snapshot["lines"]
                ],
                workspace=self.scope["workspace_id"],
                organization_code=self.scope["organization_code"],
                entity_code=self.scope["entity_code"],
                idempotency_key="sales:" + identifier,
                actor_label=actor.username,
            )
            self.ar.submit_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            plan = self.finance.prepare(
                OperationalFinancePreparation(
                    **self.scope,
                    source_kind="ARInvoice",
                    source_id=invoice["id"],
                    journal_code=payload["journal_code"],
                    period_id=payload["period_id"],
                    posting_date=payload["invoice_date"],
                    debit_account_code=payload["receivable_account_code"],
                    credit_account_code=payload["revenue_account_code"],
                    reason=payload["reason"],
                ),
                command_id="sales-invoice:" + command_id,
                actor=actor,
            )
            return {
                "status": "InvoicePrepared",
                "invoice_id": invoice["id"],
                "invoice_plan_id": plan["id"],
                "invoice_parameters": payload,
            }

        return self._run(
            identifier,
            "prepare_invoice",
            expected_version,
            preparation.reason,
            command_id,
            actor,
            "sales.manage",
            payload,
            change,
        )

    def review_invoice(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        def change(document: dict[str, Any]) -> dict[str, Any]:
            self._status(document, "InvoicePrepared")
            self._actor(
                actor, "receivables.approve", amount=int(document["total_minor"]), currency=document["currency_code"]
            )
            invoice = self.ar.get_invoice(document["invoice_id"])
            self.ar.approve_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            plan = self.finance.get(document["invoice_plan_id"], actor=actor)
            self.finance.review(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id="sales-review:" + command_id,
                reason=reason,
                actor=actor,
            )
            return {"status": "InvoiceReviewed"}

        return self._run(
            identifier, "review_invoice", expected_version, reason, command_id, actor, "sales.approve", {}, change
        )

    def post_invoice(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        def change(document: dict[str, Any]) -> dict[str, Any]:
            self._status(document, "InvoiceReviewed")
            plan = self.finance.get(document["invoice_plan_id"], actor=actor)
            self.finance.post(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id="sales-post:" + command_id,
                reason=reason,
                actor=actor,
            )
            return {"status": "Invoiced"}

        return self._run(
            identifier, "post_invoice", expected_version, reason, command_id, actor, "sales.manage", {}, change
        )

    def prepare_collection(
        self,
        identifier: str,
        *,
        expected_version: int,
        command_id: str,
        reason: str,
        actor: PostingActor,
        receipt_number: str,
        receipt_date: str,
        journal_code: str,
        period_id: str,
        cash_account_code: str,
    ) -> dict[str, Any]:
        payload = {
            "receipt_number": text(receipt_number, "receipt number", maximum=64),
            "receipt_date": date.fromisoformat(receipt_date).isoformat(),
            "journal_code": text(journal_code, "journal code"),
            "period_id": text(period_id, "period"),
            "cash_account_code": text(cash_account_code, "cash account"),
        }

        def change(document: dict[str, Any]) -> dict[str, Any]:
            self._status(document, "Invoiced")
            invoice = self.ar.get_invoice(document["invoice_id"])
            if int(invoice["outstanding_minor"]) != int(document["total_minor"]):
                raise FinancePostingError(
                    "sales_collection_conflict", "This cycle supports one full unpaid invoice settlement."
                )
            parameters = _json(document["invoice_parameters"])
            plan = self.finance.prepare(
                OperationalFinancePreparation(
                    **self.scope,
                    source_kind="ARReceipt",
                    source_id=invoice["id"],
                    journal_code=payload["journal_code"],
                    period_id=payload["period_id"],
                    posting_date=payload["receipt_date"],
                    debit_account_code=payload["cash_account_code"],
                    credit_account_code=parameters["receivable_account_code"],
                    reason=reason,
                ),
                command_id="sales-collection:" + command_id,
                actor=actor,
            )
            return {"status": "CollectionPrepared", "collection_plan_id": plan["id"], "collection_parameters": payload}

        return self._run(
            identifier,
            "prepare_collection",
            expected_version,
            reason,
            command_id,
            actor,
            "sales.manage",
            payload,
            change,
        )

    def review_collection(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        def change(document: dict[str, Any]) -> dict[str, Any]:
            self._status(document, "CollectionPrepared")
            plan = self.finance.get(document["collection_plan_id"], actor=actor)
            self.finance.review(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id="sales-collection-review:" + command_id,
                reason=reason,
                actor=actor,
            )
            return {"status": "CollectionReviewed"}

        return self._run(
            identifier, "review_collection", expected_version, reason, command_id, actor, "sales.approve", {}, change
        )

    def post_collection(
        self, identifier: str, *, expected_version: int, command_id: str, reason: str, actor: PostingActor
    ) -> dict[str, Any]:
        def change(document: dict[str, Any]) -> dict[str, Any]:
            self._status(document, "CollectionReviewed")
            self._actor(
                actor, "receivables.manage", amount=int(document["total_minor"]), currency=document["currency_code"]
            )
            parameters, quotation = _json(document["collection_parameters"]), _json(document["quotation"])
            receipt = self.ar.post_receipt(
                receipt_number=parameters["receipt_number"],
                customer_code=quotation["customer_code"],
                receipt_date=parameters["receipt_date"],
                currency_code=document["currency_code"],
                amount_minor=int(document["total_minor"]),
                allocations=[
                    ReceiptAllocationInput(invoice_id=document["invoice_id"], amount_minor=int(document["total_minor"]))
                ],
                workspace=self.scope["workspace_id"],
                organization_code=self.scope["organization_code"],
                entity_code=self.scope["entity_code"],
                idempotency_key="sales-collection:" + identifier,
                actor_label=actor.username,
            )
            plan = self.finance.get(document["collection_plan_id"], actor=actor)
            self.finance.post(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id="sales-collection-post:" + command_id,
                source_effect_id=receipt["id"],
                reason=reason,
                actor=actor,
            )
            return {"status": "Paid", "receipt_id": receipt["id"]}

        return self._run(
            identifier, "post_collection", expected_version, reason, command_id, actor, "sales.manage", {}, change
        )
