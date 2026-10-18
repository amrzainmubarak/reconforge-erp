"""Atomic native budget reservation, AP consumption and unreceived release."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from decimal import Decimal
from typing import Any
from uuid import uuid4

from reconforge.domain.budget_control import BudgetScope, CommitmentAction
from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload
from reconforge.domain.inventory_receipt_posting import exact_date, exact_text
from reconforge.domain.procurement_commitments import BudgetPurchasePreparation, normalize, version
from reconforge.domain.procurement_partial import ProcurementPartialError
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_procurement_partial import PostgresProcurementPartialRepository
from reconforge.platform.common import platform_id


class _ProcurementCommitmentParticipant:
    def __init__(self, owner: PostgresProcurementCommitmentRepository, order_id: str, invoice_id: str) -> None:
        self.owner, self.order_id, self.invoice_id = owner, order_id, invoice_id

    def admits(self, repository: PostgresProcurementPartialRepository, order_id: str, invoice_id: str | None) -> bool:
        return (self.owner._participant is self and self.owner.purchase is repository
                and self.order_id == order_id and self.invoice_id == invoice_id)


class PostgresProcurementCommitmentRepository:
    def __init__(self, connection: Any, tenant_id: str, *, require_live_session_assurance: bool = False) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.purchase = PostgresProcurementPartialRepository(connection, tenant_id)
        self.budgets = PostgresBudgetControlRepository(connection, tenant_id,
            require_live_session_assurance=require_live_session_assurance)
        self._participant: _ProcurementCommitmentParticipant | None = None

    @staticmethod
    def _scope(row: Mapping[str, Any]) -> BudgetScope:
        return BudgetScope(*(str(row[key]) for key in ("workspace_id", "organization_id", "legal_entity_id")))

    def _owner(self, order_id: str) -> dict[str, Any]:
        return self.purchase._one("SELECT * FROM reconforge.procurement_commitment_plans WHERE tenant_id=%s AND order_id=%s",
                                  (self.tenant_id, exact_text(order_id)))

    def _authorize(self, row: Mapping[str, Any], actor: PostingActor, operation: str, *, budget_id: str | None = None) -> None:
        self.purchase.shared._authorize(row, actor, operation)
        if budget_id is None:
            precision = self.connection.execute("SELECT reconforge.pc_currency_precision(%s,%s,%s) AS precision",
                (self.tenant_id, row["id"], row["request_json"]["currency_code"])).fetchone()["precision"]
        else:
            envelope = self.budgets._row(self._scope(row), budget_id)
            currency = self.purchase._one("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active",
                                          (self.tenant_id, row["request_json"]["currency_code"]))
            precision = envelope["currency_precision"]
            if envelope["currency_code"] != row["request_json"]["currency_code"] or currency["minor_units"] != precision:
                raise ProcurementPartialError("procurement_commitment_currency_policy", "Original appropriation currency precision must remain authoritative.")
        amount = Decimal((0, tuple(map(int, str(int(row["total_minor"])))), -precision))
        if operation != "read":
            self.budgets._actor(self._scope(row), "budget_control.read", write=False, amount=amount)
        user = self.budgets._actor(self._scope(row), "budget_control.read" if operation == "read" else "budget_control.manage",
                                  write=operation != "read", amount=amount)
        if user.id != actor.user_id:
            raise ProcurementPartialError("procurement_commitment_actor_denied", "Budget and purchase require the same current persisted human.")

    def _period(self, row: Mapping[str, Any], period_id: str) -> None:
        self.purchase._one("SELECT id FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s AND status='Open' FOR SHARE",
                           (self.tenant_id, period_id, row["workspace_id"]))

    def _lock(self, order_id: str, actor: PostingActor, operation: str) -> tuple[dict[str, Any], dict[str, Any]]:
        self.purchase._scope_transaction()
        row = self.purchase._order(order_id)
        self._authorize(row, actor, operation)
        owner = self._owner(order_id)
        self._period(row, row["request_json"]["period_id"])
        self.budgets._row(self._scope(row), owner["budget_id"], lock=True)
        row = self.purchase._order(order_id, lock=True)
        self._authorize(row, actor, operation)
        return row, owner

    def _command(self, row: Mapping[str, Any], operation: str, command_id: str,
                 request: Mapping[str, Any], actor: PostingActor) -> tuple[str, dict[str, Any] | None]:
        command_id = exact_text(command_id, maximum=140)
        digest = digest_payload({"operation": operation, "actor_id": actor.user_id, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                (canonical_json([self.tenant_id, row["workspace_id"], "procurement-commitment", command_id]),))
        retained = self.connection.execute("SELECT * FROM reconforge.procurement_commitment_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                           (self.tenant_id, row["workspace_id"], command_id)).fetchone()
        if retained is None:
            return digest, None
        if (retained["order_id"], retained["actor_id"], retained["request_digest"]) != (row["id"], actor.user_id, digest):
            raise ProcurementPartialError("procurement_commitment_command_conflict", "Command belongs to another exact source, scope or human.")
        self.connection.execute("SELECT reconforge.pc_close(%s,%s)", (self.tenant_id, row["id"]))
        self.budgets._public(self.budgets._row(self._scope(row), self._owner(row["id"])["budget_id"]))
        return digest, dict(retained["response_json"])

    def _remember(self, row: Mapping[str, Any], operation: str, command_id: str, request: Mapping[str, Any],
                  request_digest: str, budget: Mapping[str, Any], actor: PostingActor, invoice_id: str | None = None) -> dict[str, Any]:
        evidence = budget["evidence"]
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(actor_user_id=actor.user_id,
            actor_label=actor.username, object_type="procurement_commitment", object_id=row["id"], action="procurement_commitment_" + operation,
            metadata={"request_digest": request_digest, "budget_event_id": evidence["event_id"]})
        outbox_id = "PCOUT-" + uuid4().hex
        self.connection.execute("""INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,
            workspace_id,organization_id,legal_entity_id,payload) VALUES(%s,%s,%s,'procurement_commitment',%s,%s,%s,%s,%s::jsonb)""",
            (self.tenant_id, outbox_id, "procurement_commitment_" + operation, row["id"], row["workspace_id"], row["organization_id"], row["legal_entity_id"],
             canonical_json({"request_digest": request_digest, "budget_event_id": evidence["event_id"], "audit_event_id": audit.id})))
        self.connection.execute("""INSERT INTO reconforge.procurement_commitment_commands(tenant_id,workspace_id,order_id,command_id,
            operation,actor_id,request_json,request_digest,budget_event_id,invoice_id,order_version,audit_event_id,outbox_event_id,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,'{}'::jsonb)""",
            (self.tenant_id, row["workspace_id"], row["id"], command_id, operation, actor.user_id,
             canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), request_digest,
             evidence["event_id"], invoice_id, row["row_version"], audit.id, outbox_id))
        result = self.connection.execute("SELECT reconforge.pc_ack(%s,%s) AS response", (self.tenant_id, evidence["event_id"])).fetchone()["response"]
        self.connection.execute("UPDATE reconforge.procurement_commitment_commands SET response_json=%s::jsonb WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
                                (canonical_json(result), self.tenant_id, row["workspace_id"], command_id))
        self.connection.execute("SELECT reconforge.pc_close(%s,%s)", (self.tenant_id, row["id"]))
        return dict(result)

    def create(self, request: BudgetPurchasePreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request, total = normalize(request)
        with self.connection.transaction():
            self.purchase._scope_transaction()
            scope = self.purchase.shared._codes_scope(request.order.workspace, request.order.organization_code, request.order.entity_code)
            row = {**scope, "id": platform_id("PPORDER", scope["workspace_id"], request.order.number),
                   "request_json": asdict(request.order), "total_minor": total}
            self._authorize(row, actor, "create", budget_id=request.budget_id)
            self._period(row, request.order.period_id)
            envelope = self.budgets._row(self._scope(row), request.budget_id, lock=True)
            digest, replay = self._command(row, "create", command_id, asdict(request), actor)
            if replay is not None:
                return replay
            if envelope["currency_code"] != request.order.currency_code or envelope["period_id"] != request.order.period_id:
                raise ProcurementPartialError("procurement_commitment_mapping_invalid", "Purchase currency and period must exactly match the approved appropriation.")
            budget = self.budgets.record(self._scope(row), request.budget_id,
                CommitmentAction("Reserve", total, request.order.posting_date, "BPC1:" + row["id"], request.reason),
                expected_version=request.expected_budget_version, command_id=platform_id("PCBUD", row["id"], command_id, "create"))
            payload = {"order_request": asdict(request.order), "scope": {key: scope[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                       "budget_id": request.budget_id, "budget_policy": {key: envelope[key] for key in ("currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest")},
                       "amount_minor": total, "preparer_actor_id": actor.user_id}
            self.connection.execute("""INSERT INTO reconforge.procurement_commitment_plans(tenant_id,order_id,budget_id,commitment_id,reserve_event_id,
                payload,plan_digest) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                (self.tenant_id, row["id"], request.budget_id, budget["commitment_id"], budget["evidence"]["event_id"], canonical_json(payload), digest_payload(payload)))
            self.purchase.create_multiline(request.order, command_id=platform_id("PCORDER", command_id), actor=actor)
            return self._remember(self.purchase._order(row["id"]), "create", command_id, asdict(request), digest, budget, actor)

    def consume_invoice(self, order_id: str, invoice_id: str, *, expected_order_version: int,
                        expected_budget_version: int, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        version(expected_order_version)
        version(expected_budget_version)
        reason, invoice_id = exact_text(reason, maximum=500), exact_text(invoice_id)
        request = {"order_id": order_id, "invoice_id": invoice_id, "expected_order_version": expected_order_version,
                   "expected_budget_version": expected_budget_version, "reason": reason}
        with self.connection.transaction():
            row, owner = self._lock(order_id, actor, "post-accrual")
            digest, replay = self._command(row, "consume", command_id, request, actor)
            if replay is not None:
                return replay
            invoice = self.purchase._document(order_id, invoice_id, "invoice")
            if row["row_version"] != expected_order_version or invoice["stage"] != 3:
                raise ProcurementPartialError("procurement_commitment_version_conflict", "Select the current independently reviewed AP invoice and purchase version.")
            if invoice["period_id"] != row["request_json"]["period_id"]:
                raise ProcurementPartialError("procurement_commitment_period_conflict", "AP accrual must use the original appropriation period.")
            budget = self.budgets.record(self._scope(row), owner["budget_id"],
                CommitmentAction("Consume", int(invoice["total_minor"]), invoice["posting_date"].isoformat(), "BPC1:" + order_id, reason),
                expected_version=expected_budget_version, commitment_id=owner["commitment_id"],
                command_id=platform_id("PCBUD", order_id, command_id, "consume"))
            self._participant = _ProcurementCommitmentParticipant(self, order_id, invoice_id)
            self.purchase._commitment_participant = self._participant
            try:
                self.purchase.act(order_id, "post-accrual", expected_version=expected_order_version,
                    command_id=platform_id("PCAP", command_id), reason=reason, document_id=invoice_id, actor=actor)
            finally:
                self.purchase._commitment_participant = None
                self._participant = None
            return self._remember(self.purchase._order(order_id), "consume", command_id, request, digest, budget, actor, invoice_id)

    def release(self, order_id: str, *, expected_order_version: int, expected_budget_version: int,
                posting_date: str, command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        version(expected_order_version)
        version(expected_budget_version)
        reason, posting_date = exact_text(reason, maximum=500), exact_date(posting_date)
        request = {"order_id": order_id, "expected_order_version": expected_order_version,
                   "expected_budget_version": expected_budget_version, "posting_date": posting_date, "reason": reason}
        with self.connection.transaction():
            row, owner = self._lock(order_id, actor, "approve-order")
            digest, replay = self._command(row, "release", command_id, request, actor)
            if replay is not None:
                return replay
            if row["row_version"] != expected_order_version or actor.user_id == owner["payload"]["preparer_actor_id"]:
                raise ProcurementPartialError("procurement_commitment_duties_conflict", "Release requires the current purchase version and an independent human.")
            self.connection.execute("SELECT reconforge.pc_release_admit(%s,%s)", (self.tenant_id, order_id))
            remaining = self.connection.execute("SELECT remaining_minor FROM reconforge.budget_commitment_events WHERE tenant_id=%s AND budget_id=%s AND commitment_id=%s ORDER BY budget_version DESC LIMIT 1",
                (self.tenant_id, owner["budget_id"], owner["commitment_id"])).fetchone()["remaining_minor"]
            budget = self.budgets.record(self._scope(row), owner["budget_id"], CommitmentAction("Release", remaining, posting_date, "BPC1:" + order_id, reason),
                expected_version=expected_budget_version, commitment_id=owner["commitment_id"], command_id=platform_id("PCBUD", order_id, command_id, "release"))
            return self._remember(row, "release", command_id, request, digest, budget, actor)

    def get(self, order_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.connection.transaction():
            self.purchase._scope_transaction()
            row = self.purchase._order(order_id)
            self._authorize(row, actor, "read")
            owner = self._owner(order_id)
            self.connection.execute("SELECT reconforge.pc_close(%s,%s)", (self.tenant_id, order_id))
            self.budgets._public(self.budgets._row(self._scope(row), owner["budget_id"]))
            latest = self.connection.execute("SELECT c.budget_event_id FROM reconforge.procurement_commitment_commands c JOIN reconforge.budget_commitment_events e ON e.tenant_id=c.tenant_id AND e.id=c.budget_event_id WHERE c.tenant_id=%s AND c.order_id=%s ORDER BY e.budget_version DESC LIMIT 1",
                                             (self.tenant_id, order_id)).fetchone()
            return dict(self.connection.execute("SELECT reconforge.pc_ack(%s,%s) AS response", (self.tenant_id, latest["budget_event_id"])).fetchone()["response"])
