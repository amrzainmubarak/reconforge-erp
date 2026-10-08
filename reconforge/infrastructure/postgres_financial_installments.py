"""Reviewed AP installments on existing native Finance and payment-link engines."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)
from reconforge.domain.financial_installments import FinancialInstallmentPreparation
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.payables_payment_link import payment_external_reference
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_payables_payment_link import (
    PostgresPayablesPaymentLinkRepository,
    _active_allocation,
)


class _InstallmentPostingParticipant:
    def __init__(self, owner: "PostgresFinancialInstallmentsRepository", entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class PostgresFinancialInstallmentsRepository:
    """One frozen invoice residual, independent review and atomic native allocation.

    No amount is taken from a generic financial effect. The existing payment
    link repeats its exact AP/cash, identity, currency and cumulative checks.
    """

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self._participant: _InstallmentPostingParticipant | None = None

    def _row(self, plan_id: str) -> dict[str, Any]:
        rows = records(self.connection.execute(
            "SELECT * FROM reconforge.financial_installment_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, text(plan_id, "plan_id"))))
        if not rows:
            raise FinancePostingError("installment_not_found", "Installment is absent or outside current scope.")
        row = rows[0]
        return {**row["payload"], "phase": row["phase"]}

    def _source(self, invoice_id: str) -> tuple[dict[str, Any], int, int]:
        source = self.owner._source("APPayment", invoice_id, final=True, settlement=True)
        row = records(self.connection.execute(
            "SELECT status,row_version FROM reconforge.ap_supplier_invoices WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, invoice_id)))[0]
        if row["status"] != "Approved":
            raise FinancePostingError("installment_source_changed", "An approved payable with a positive residual is required.")
        # The first release composes only accrued partial Procurement invoices.
        admitted = self.connection.execute(
            "SELECT 1 FROM reconforge.procurement_partial_invoices WHERE tenant_id=%s AND native_invoice_id=%s AND stage=4",
            (self.tenant_id, invoice_id)).fetchone()
        if admitted is None:
            raise FinancePostingError("installment_source_invalid", "Complete the source's reviewed accrual before payment.")
        return source, row["row_version"], _active_allocation(self.connection, self.tenant_id, invoice_id)

    def _command(self, scope: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command, "command_id", maximum=140)
        digest = digest_payload({"operation": operation, "actor_id": actor.user_id, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, scope["workspace_id"], "installments", command]),))
        rows = records(self.connection.execute(
            "SELECT * FROM reconforge.financial_installment_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, scope["workspace_id"], command)))
        if not rows:
            return digest, None
        row = rows[0]
        if (row["operation"], row["actor_id"], row["request_digest"]) != (operation, actor.user_id, digest):
            raise FinancePostingError("installment_command_conflict", "Command already identifies another actor or request.")
        self.connection.execute("SELECT reconforge.installment_close(%s,%s)", (self.tenant_id, row["plan_id"]))
        return digest, row["response_json"]

    def _remember(self, plan: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                  request_digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self._view(str(plan["id"]))
        self.connection.execute("""INSERT INTO reconforge.financial_installment_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"], plan["id"],
             operation, command, actor.user_id, request_digest,
             canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        return result

    def _view(self, plan_id: str) -> dict[str, Any]:
        plan = self._row(plan_id)
        review = records(self.connection.execute(
            "SELECT * FROM reconforge.financial_installment_reviews WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)))
        links = records(self.connection.execute(
            "SELECT * FROM reconforge.financial_installment_links WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)))
        result = {**plan, "status": ("Prepared", "Reviewed", "Posted")[plan["phase"]],
                  "reviewer_actor_id": review[0]["reviewer_actor_id"] if review else None,
                  "posting_effect_id": links[0]["posting_effect_id"] if links else None,
                  "payment_link_id": links[0]["payment_link_id"] if links else None}
        return result

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._row(plan_id)
            self.owner._actor(actor, "finance_core.read", plan, mutation=False)
            self.owner._actor(actor, "payables.read", plan, mutation=False)
            self.connection.execute("SELECT reconforge.installment_close(%s,%s)", (self.tenant_id, plan_id))
            return self._view(plan_id)

    def prepare(self, request: FinancialInstallmentPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            self.owner._actor(actor, "finance_core.manage", args, source=True)
            digest, replay = self._command(args, "prepare", command_id, actor, args)
            if replay is not None:
                return replay
            source, version, allocated = self._source(request.source_id)
            if any(source[k] != args[k] for k in ("workspace_id", "organization_id", "legal_entity_id")):
                raise FinancePostingError("installment_scope_denied", "Source is outside selected hierarchy.")
            if request.amount_minor > source["amount_minor"] - allocated:
                raise FinancePostingError("installment_amount_invalid", "Installment exceeds the current payable residual.")
            precision = records(self.connection.execute(
                "SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE",
                (self.tenant_id, source["currency_code"])))[0]["minor_units"]
            self.owner._actor(actor, "finance_core.manage", {**args, "currency_precision": precision}, source=True)
            identifier = "FI1-" + uuid4().hex
            amount = exact_minor_text(request.amount_minor, precision)
            entry = self.owner.finance.create_entry(entry_number=identifier.upper(), organization_code=request.organization_code,
                entity_code=request.entity_code, period_id=request.period_id, journal_code=request.journal_code,
                posting_date=request.posting_date, description=request.reason, workspace=request.workspace_id,
                external_reference=payment_external_reference(request.source_id), actor_label=actor.username,
                lines=[{"account_code": request.debit_account_code, "debit": amount, "credit": "0", "description": request.reason},
                       {"account_code": request.credit_account_code, "debit": "0", "credit": amount, "description": request.reason}])
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
            if snapshot["entry"]["currency_code"] != source["currency_code"]:
                raise FinancePostingError("installment_currency_invalid", "Native invoice and GL must share functional currency.")
            payload = {"schema_version": "financial-installment-v1", "id": identifier, **args,
                "entry_id": entry["id"], "invoice_version": version, "allocated_before_minor": allocated,
                "currency_code": source["currency_code"], "currency_precision": precision,
                "source_snapshot": source, "snapshot": snapshot, "preparer_actor_id": actor.user_id}
            seal = digest_payload(payload)
            payload.update(plan_digest=seal, validation_digest=validation_digest(snapshot))
            audit, outbox = self.owner._event(payload, "financial_installment_prepared", actor, {"plan_digest": seal})
            self.connection.execute("""INSERT INTO reconforge.financial_installment_plans
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_id,entry_id,amount_minor,phase,payload,audit_event_id,outbox_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s)""",
                (self.tenant_id, identifier, request.workspace_id, request.organization_id, request.legal_entity_id,
                 request.source_id, entry["id"], request.amount_minor, canonical_json(payload), audit, outbox))
            return self._remember(payload, "prepare", command_id, actor, digest, args)

    def _current(self, plan: Mapping[str, Any]) -> None:
        source, version, allocated = self._source(str(plan["source_id"]))
        if (source != plan["source_snapshot"] or version != plan["invoice_version"]
                or allocated != plan["allocated_before_minor"]):
            raise FinancePostingError("installment_source_changed", "Payable changed after installment preparation.")

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
               actor: PostingActor) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        args = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": reason}
        with self.owner._transaction():
            plan = self._row(plan_id)
            self.owner._actor(actor, "finance_core.validate", plan, source=True)
            digest, replay = self._command(plan, "review", command_id, actor, args)
            if replay is not None:
                return replay
            if plan["phase"] != 0 or plan["plan_digest"] != expected_plan_digest or actor.user_id == plan["preparer_actor_id"]:
                raise FinancePostingError("installment_review_invalid", "An independent reviewer and current prepared digest are required.")
            self._current(plan)
            self.owner.finance.validate_entry(plan["entry_id"], reason=reason, actor_label=actor.username)
            audit, outbox = self.owner._event(plan, "financial_installment_reviewed", actor, {"plan_digest": plan["plan_digest"]})
            self.connection.execute("""INSERT INTO reconforge.financial_installment_reviews
                (tenant_id,plan_id,reviewer_actor_id,reason,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, plan_id, actor.user_id, reason, audit, outbox))
            self.connection.execute("UPDATE reconforge.financial_installment_plans SET phase=1 WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, plan_id))
            return self._remember(plan, "review", command_id, actor, digest, args)

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, reason: str,
             actor: PostingActor) -> dict[str, Any]:
        reason = text(reason, "reason", maximum=500)
        args = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": reason}
        with self.owner._transaction():
            plan = self._row(plan_id)
            self.owner._actor(actor, "finance_core.post", plan, source=True)
            digest, replay = self._command(plan, "post", command_id, actor, args)
            if replay is not None:
                return replay
            if plan["phase"] != 1 or plan["plan_digest"] != expected_plan_digest:
                raise FinancePostingError("installment_review_invalid", "A current reviewed installment is required.")
            self._current(plan)
            self._participant = _InstallmentPostingParticipant(self, str(plan["entry_id"]))
            try:
                effect = self.owner.posting.post(plan["entry_id"], command_id="FI1:" + command_id,
                    expected_validation_digest=plan["validation_digest"], reason=reason, actor=actor, _source_owner=self._participant)
            finally:
                self._participant = None
            link = PostgresPayablesPaymentLinkRepository(self.connection, self.tenant_id).link_finance_payment(
                plan["source_id"], finance_effect_id=effect["id"], ap_account_id=plan["snapshot"]["lines"][0]["account_id"],
                cash_account_id=plan["snapshot"]["lines"][1]["account_id"], expected_invoice_version=plan["invoice_version"],
                command_id="FI1:" + command_id, actor_label=actor.user_id)
            audit, outbox = self.owner._event(plan, "financial_installment_posted", actor,
                {"plan_digest": plan["plan_digest"], "posting_effect_id": effect["id"], "payment_link_id": link["payment_link_id"]})
            self.connection.execute("""INSERT INTO reconforge.financial_installment_links
                (tenant_id,plan_id,posting_effect_id,payment_link_id,posted_actor_id,reason,audit_event_id,outbox_event_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, plan_id, effect["id"], link["payment_link_id"], actor.user_id, reason, audit, outbox))
            self.connection.execute("UPDATE reconforge.financial_installment_plans SET phase=2 WHERE tenant_id=%s AND id=%s",
                                    (self.tenant_id, plan_id))
            return self._remember(plan, "post", command_id, actor, digest, args)
