"""Reviewed AR collections over the existing receipt and Finance Posting engines."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from reconforge.application.receivables import ReceiptAllocationInput
from reconforge.domain.commercial_collections import CommercialCollectionPreparation
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
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository


class _CollectionPostingParticipant:
    def __init__(self, owner: "PostgresCommercialCollectionsRepository", entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class PostgresCommercialCollectionsRepository:
    """One frozen invoice residual, independent review and atomic native collection.

    The native receipt engine repeats exact invoice, identity, currency and
    cumulative checks. Deferred SQL closure requires its matching cash effect.
    """

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self._participant: _CollectionPostingParticipant | None = None

    def _row(self, plan_id: str) -> dict[str, Any]:
        rows = records(self.connection.execute(
            "SELECT * FROM reconforge.commercial_collection_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, text(plan_id, "plan_id"))))
        if not rows:
            raise FinancePostingError("collection_not_found", "Installment is absent or outside current scope.")
        row = rows[0]
        return {**row["payload"], "phase": row["phase"]}

    def _source(self, invoice_id: str) -> tuple[dict[str, Any], int, int]:
        source = self.owner._source("ARReceipt", invoice_id, final=True, settlement=True)
        row = records(self.connection.execute(
            "SELECT status,row_version FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, invoice_id)))[0]
        if row["status"] not in {"Approved", "PartiallyPaid"}:
            raise FinancePostingError("collection_source_changed", "An approved receivable with a positive residual is required.")
        admitted = self.connection.execute(
            "SELECT 1 FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND invoice_id=%s AND status='Invoiced' AND collection_plan_id IS NULL",
            (self.tenant_id, invoice_id)).fetchone()
        if admitted is None:
            raise FinancePostingError("collection_source_invalid", "Complete the stock sale's reviewed revenue posting before collection.")
        allocated = records(self.connection.execute(
            "SELECT coalesce(sum(amount_minor),0) AS amount FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s AND invoice_id=%s",
            (self.tenant_id, invoice_id)))[0]["amount"]
        return source, row["row_version"], int(allocated)

    def _command(self, scope: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command, "command_id", maximum=140)
        digest = digest_payload({"operation": operation, "actor_id": actor.user_id, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, scope["workspace_id"], "collections", command]),))
        rows = records(self.connection.execute(
            "SELECT * FROM reconforge.commercial_collection_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, scope["workspace_id"], command)))
        if not rows:
            return digest, None
        row = rows[0]
        if (row["operation"], row["actor_id"], row["request_digest"]) != (operation, actor.user_id, digest):
            raise FinancePostingError("collection_command_conflict", "Command already identifies another actor or request.")
        self.connection.execute("SELECT reconforge.collection_close(%s,%s)", (self.tenant_id, row["plan_id"]))
        return digest, row["response_json"]

    def _remember(self, plan: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                  request_digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self._view(str(plan["id"]))
        self.connection.execute("""INSERT INTO reconforge.commercial_collection_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"], plan["id"],
             operation, command, actor.user_id, request_digest,
             canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        return result

    def _view(self, plan_id: str) -> dict[str, Any]:
        plan = self._row(plan_id)
        review = records(self.connection.execute(
            "SELECT * FROM reconforge.commercial_collection_reviews WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)))
        links = records(self.connection.execute(
            "SELECT * FROM reconforge.commercial_collection_links WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)))
        result = {**plan, "status": ("Prepared", "Reviewed", "Posted")[plan["phase"]],
                  "reviewer_actor_id": review[0]["reviewer_actor_id"] if review else None,
                  "posting_effect_id": links[0]["posting_effect_id"] if links else None,
                  "receipt_id": links[0]["receipt_id"] if links else None}
        return result

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self.owner._actor(actor, "finance_core.read", plan, mutation=False)
            self.owner._actor(actor, "receivables.read", plan, mutation=False)
            self.connection.execute("SELECT reconforge.collection_close(%s,%s)", (self.tenant_id, plan_id))
            return self._view(plan_id)

    def prepare(self, request: CommercialCollectionPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            self.owner._actor(actor, "finance_core.manage", args, source=True)
            digest, replay = self._command(args, "prepare", command_id, actor, args)
            if replay is not None:
                return replay
            source, version, allocated = self._source(request.source_id)
            policy = records(self.connection.execute(
                "SELECT invoice_parameters FROM reconforge.stock_sales_orders WHERE tenant_id=%s AND invoice_id=%s AND status='Invoiced'",
                (self.tenant_id, request.source_id)))[0]["invoice_parameters"]
            if request.credit_account_code != policy["receivable_account_code"] or request.debit_account_code == request.credit_account_code:
                raise FinancePostingError("collection_account_invalid", "Credit the source receivable and debit a distinct cash asset.")
            self.owner._actor(actor, "sales.manage", args, source=True)
            if self.connection.execute("SELECT 1 FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND workspace_id=%s AND scope=%s AND idempotency_key=%s",
                (self.tenant_id, request.workspace_id, "sales_receipt_name_v1:" + request.workspace_id, request.receipt_number)).fetchone():
                raise FinancePostingError("collection_receipt_conflict", "Receipt number is already reserved by another native command.")
            if self.connection.execute(
                "SELECT 1 FROM reconforge.commercial_collection_plans WHERE tenant_id=%s AND source_id=%s AND phase<2",
                (self.tenant_id, request.source_id)).fetchone() is not None:
                raise FinancePostingError("collection_state_conflict", "Complete the retained pending installment first.")
            count = records(self.connection.execute(
                "SELECT count(*) AS count FROM reconforge.commercial_collection_plans WHERE tenant_id=%s AND source_id=%s",
                (self.tenant_id, request.source_id)))[0]["count"]
            if count >= 200:
                raise FinancePostingError("collection_limit", "The invoice exceeds the bounded 200-installment evidence budget.")
            if any(source[k] != args[k] for k in ("workspace_id", "organization_id", "legal_entity_id")):
                raise FinancePostingError("collection_scope_denied", "Source is outside selected hierarchy.")
            if request.amount_minor > source["amount_minor"] - allocated:
                raise FinancePostingError("collection_amount_invalid", "Installment exceeds the current receivable residual.")
            precision = records(self.connection.execute(
                "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE",
                (self.tenant_id, source["currency_code"])))[0]["minor_units"]
            self.owner._actor(actor, "finance_core.manage", {**args, "currency_precision": precision}, source=True)
            identifier = "CA1-" + uuid4().hex
            amount = exact_minor_text(request.amount_minor, precision)
            entry = self.owner.finance.create_entry(entry_number=identifier.upper(), organization_code=request.organization_code,
                entity_code=request.entity_code, period_id=request.period_id, journal_code=request.journal_code,
                posting_date=request.posting_date, description=request.reason, workspace=request.workspace_id,
                external_reference=identifier, actor_label=actor.username,
                lines=[{"account_code": request.debit_account_code, "debit": amount, "credit": "0", "description": request.reason},
                       {"account_code": request.credit_account_code, "debit": "0", "credit": amount, "description": request.reason}])
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
            if snapshot["entry"]["currency_code"] != source["currency_code"]:
                raise FinancePostingError("collection_currency_invalid", "Native receivable and GL must share functional currency.")
            payload = {"schema_version": "commercial-collection-v1", "id": identifier, **args,
                "entry_id": entry["id"], "invoice_version": version, "allocated_before_minor": allocated,
                "currency_code": source["currency_code"], "currency_precision": precision,
                "source_snapshot": source, "snapshot": snapshot, "preparer_actor_id": actor.user_id}
            seal = digest_payload(payload)
            payload.update(plan_digest=seal, validation_digest=validation_digest(snapshot))
            audit, outbox = self.owner._event(payload, "commercial_collection_prepared", actor, {"plan_digest": seal})
            self.connection.execute("""INSERT INTO reconforge.commercial_collection_plans
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_id,entry_id,amount_minor,phase,payload,audit_event_id,outbox_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s)""",
                (self.tenant_id, identifier, request.workspace_id, request.organization_id, request.legal_entity_id,
                 request.source_id, entry["id"], request.amount_minor, canonical_json(payload), audit, outbox))
            return self._remember(payload, "prepare", command_id, actor, digest, args)

    def _current(self, plan: Mapping[str, Any]) -> None:
        source, version, allocated = self._source(str(plan["source_id"]))
        if (source != plan["source_snapshot"] or version != plan["invoice_version"]
                or allocated != plan["allocated_before_minor"]):
            raise FinancePostingError("collection_source_changed", "Receivable changed after installment preparation.")

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
               actor: PostingActor) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        args = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": reason}
        with self.owner._transaction():
            plan = self._row(plan_id)
            self.owner._actor(actor, "finance_core.validate", plan, source=True)
            self.owner._actor(actor, "sales.approve", plan, source=True)
            digest, replay = self._command(plan, "review", command_id, actor, args)
            if replay is not None:
                return replay
            if plan["phase"] != 0 or plan["plan_digest"] != expected_plan_digest or actor.user_id == plan["preparer_actor_id"]:
                raise FinancePostingError("collection_review_invalid", "An independent reviewer and current prepared digest are required.")
            self._current(plan)
            self.owner.finance.validate_entry(plan["entry_id"], reason=reason, actor_label=actor.username)
            audit, outbox = self.owner._event(plan, "commercial_collection_reviewed", actor, {"plan_digest": plan["plan_digest"]})
            self.connection.execute("""INSERT INTO reconforge.commercial_collection_reviews
                (tenant_id,plan_id,reviewer_actor_id,reason,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, plan_id, actor.user_id, reason, audit, outbox))
            self.connection.execute("UPDATE reconforge.commercial_collection_plans SET phase=1 WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, plan_id))
            return self._remember(plan, "review", command_id, actor, digest, args)

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
             actor: PostingActor) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        args = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": reason}
        with self.owner._transaction():
            plan = self._row(plan_id)
            self.owner._actor(actor, "finance_core.post", plan, source=True)
            self.owner._actor(actor, "receivables.manage", plan, source=True)
            self.owner._actor(actor, "sales.manage", plan, source=True)
            digest, replay = self._command(plan, "post", command_id, actor, args)
            if replay is not None:
                return replay
            if plan["phase"] != 1 or plan["plan_digest"] != expected_plan_digest:
                raise FinancePostingError("collection_review_invalid", "A current reviewed installment is required.")
            if actor.user_id in {plan["preparer_actor_id"], self._view(plan_id)["reviewer_actor_id"]}:
                raise FinancePostingError(
                    "collection_posting_denied", "Posting requires a third authorized human independent of preparation and review.")
            self._current(plan)
            self._participant = _CollectionPostingParticipant(self, str(plan["entry_id"]))
            try:
                effect = self.owner.posting.post(plan["entry_id"], command_id="CA1:" + command_id,
                    expected_validation_digest=plan["validation_digest"], reason=reason, actor=actor, _source_owner=self._participant)
            finally:
                self._participant = None
            source = plan["source_snapshot"]
            customer = records(self.connection.execute(
                "SELECT customer_code FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, source["party_id"])))[0]
            receipt = PostgresReceivablesRepository(self.connection, self.tenant_id).post_receipt(
                receipt_number=plan["receipt_number"], customer_code=customer["customer_code"],
                receipt_date=plan["posting_date"], currency_code=plan["currency_code"], amount_minor=plan["amount_minor"],
                allocations=[ReceiptAllocationInput(invoice_id=plan["source_id"], amount_minor=plan["amount_minor"])],
                workspace=plan["workspace_id"], organization_code=plan["organization_code"], entity_code=plan["entity_code"],
                idempotency_key="CA1:" + plan["id"], actor_label=actor.username)
            audit, outbox = self.owner._event(plan, "commercial_collection_posted", actor,
                {"plan_digest": plan["plan_digest"], "posting_effect_id": effect["id"], "receipt_id": receipt["id"]})
            self.connection.execute("""INSERT INTO reconforge.commercial_collection_links
                (tenant_id,plan_id,posting_effect_id,receipt_id,posted_actor_id,reason,audit_event_id,outbox_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, plan_id, effect["id"], receipt["id"], actor.user_id, reason, audit, outbox))
            self.connection.execute("UPDATE reconforge.commercial_collection_plans SET phase=2 WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, plan_id))
            return self._remember(plan, "post", command_id, actor, digest, args)
