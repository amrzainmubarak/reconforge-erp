"""Historical foreign AR, effective tax and realized FX in one native transaction."""

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text, validation_digest
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.operational_fx_revaluation import revaluation_equation, reversal_equation
from reconforge.domain.operational_fx_tax import (
    MAX_SETTLEMENTS,
    ForeignInvoicePreparation,
    HistoricalRate,
    canonical_day,
    fail,
    invoice_equation,
    settlement_equation,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.platform.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput


class _FxPostingParticipant:
    def __init__(self, owner: "PostgresOperationalFxTaxRepository", entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class PostgresOperationalFxTaxRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self.ar = PostgresReceivablesRepository(connection, tenant_id)
        self._participant: _FxPostingParticipant | None = None

    def _peek(self, table: str, identifier: str) -> dict[str, Any]:
        # These two closed statements only inspect already RLS-scoped immutable
        # metadata. The command lock precedes native parent and owner row locks.
        statement = {
            "source": "SELECT payload FROM reconforge.operational_fx_sources WHERE tenant_id=%s AND id=%s",
            "plan": "SELECT payload FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND id=%s",
        }[table]
        rows = records(self.connection.execute(statement, (self.tenant_id, text(identifier, table + "_id"))))
        if not rows:
            fail("Foreign receivable is absent or outside current scope.", "fx_" + table + "_not_found")
        return dict(rows[0]["payload"])

    def _period(self, period_id: str) -> None:
        if self.connection.execute("SELECT id FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s FOR SHARE",
                                   (self.tenant_id, period_id)).fetchone() is None:
            fail("A current scoped accounting period is required.", "fx_scope_denied")

    def _source(self, source_id: str) -> dict[str, Any]:
        rows = records(self.connection.execute(
            "SELECT invoice_id FROM reconforge.operational_fx_sources WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, text(source_id, "source_id"))))
        if not rows:
            fail("Foreign receivable is absent or outside current scope.", "fx_source_not_found")
        # All detail, evidence and mutation paths lock the native customer and
        # invoice before the retained owner and plan. Native AR uses that order.
        self.connection.execute("""SELECT c.id FROM reconforge.ar_customers c JOIN reconforge.ar_invoices i
            ON i.tenant_id=c.tenant_id AND i.customer_id=c.id WHERE i.tenant_id=%s AND i.id=%s FOR UPDATE OF c""",
            (self.tenant_id, rows[0]["invoice_id"]))
        self.connection.execute("SELECT id FROM reconforge.ar_invoices WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                (self.tenant_id, rows[0]["invoice_id"]))
        row = records(self.connection.execute(
            "SELECT payload FROM reconforge.operational_fx_sources WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, source_id)))[0]
        return dict(row["payload"])

    def _plan(self, plan_id: str) -> dict[str, Any]:
        rows = records(self.connection.execute("SELECT source_id FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND id=%s",
                                               (self.tenant_id, text(plan_id, "plan_id"))))
        if not rows:
            fail("Foreign receivable plan is absent or outside current scope.", "fx_plan_not_found")
        self._source(rows[0]["source_id"])
        row = records(self.connection.execute("SELECT payload,phase FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND id=%s FOR UPDATE",
                                              (self.tenant_id, plan_id)))[0]
        return {**row["payload"], "phase": row["phase"]}

    def _authorize(self, actor: PostingActor, permission: str, source: Mapping[str, Any],
                   plan: Mapping[str, Any] | None = None, *, mutation: bool = True) -> None:
        scope = {key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
        foreign, functional = source["foreign_policy"], source["functional_policy"]
        self.owner._actor(actor, permission, {**scope, "amount_minor": source["foreign_gross_minor"],
                         "currency_precision": foreign["currency_precision"]}, mutation=mutation)
        self.owner._actor(actor, permission, {**scope, "amount_minor": source["functional_gross_minor"],
                         "currency_precision": functional["currency_precision"]}, mutation=mutation)
        if plan:
            self.owner._actor(actor, permission, plan, mutation=mutation)
            if mutation and plan["kind"] == "reverse_revaluation":
                self.owner._actor(actor, "finance_core.reverse", plan, mutation=True)
            if plan["kind"] == "settle":
                self.owner._actor(actor, permission, {**scope, "amount_minor": plan["equation"]["foreign_minor"],
                    "currency_precision": foreign["currency_precision"]}, mutation=mutation)
        ar_permission = "receivables.read" if not mutation else "receivables.approve" if permission == "finance_core.validate" else "receivables.manage"
        self.owner._actor(actor, ar_permission, {**scope, "amount_minor": source["foreign_gross_minor"],
                         "currency_precision": foreign["currency_precision"]}, mutation=mutation)

    def _command(self, scope: Mapping[str, Any], operation: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command_id, "command_id", maximum=140)
        digest = digest_payload({"operation": operation, "actor_id": actor.user_id, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "operational-fx-tax", command_id]),))
        rows = records(self.connection.execute("""SELECT * FROM reconforge.operational_fx_commands
            WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s""", (self.tenant_id, scope["workspace_id"], command_id)))
        if not rows:
            return digest, None
        row = rows[0]
        if (row["operation"], row["actor_id"], row["request_digest"]) != (operation, actor.user_id, digest):
            fail("Command identifies a different actor or immutable request.", "fx_command_conflict")
        return digest, row["response_json"]

    def _view(self, plan_id: str) -> dict[str, Any]:
        plan = self._plan(plan_id)
        review = records(self.connection.execute("SELECT reviewer_actor_id FROM reconforge.operational_fx_reviews WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)))
        links = records(self.connection.execute("SELECT posting_effect_id,receipt_id FROM reconforge.operational_fx_links WHERE tenant_id=%s AND plan_id=%s", (self.tenant_id, plan_id)))
        return {**plan, "status": ("Prepared", "Reviewed", "Posted")[plan["phase"]],
                "reviewer_actor_id": review[0]["reviewer_actor_id"] if review else None,
                "posting_effect_id": links[0]["posting_effect_id"] if links else None,
                "receipt_id": links[0]["receipt_id"] if links else None}

    def _remember(self, plan: Mapping[str, Any], operation: str, command: str, actor: PostingActor,
                  digest: str, request: Mapping[str, Any]) -> dict[str, Any]:
        result = self._view(str(plan["id"]))
        self.connection.execute("""INSERT INTO reconforge.operational_fx_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,command_id,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, plan["workspace_id"], plan["organization_id"], plan["legal_entity_id"], plan["id"], operation,
             command, actor.user_id, digest, canonical_json({"operation": operation, "actor_id": actor.user_id, "request": dict(request)}), canonical_json(result)))
        return result

    def _state(self, source: Mapping[str, Any]) -> dict[str, Any]:
        rows = records(self.connection.execute("""SELECT id,kind,sequence,payload FROM reconforge.operational_fx_plans
            WHERE tenant_id=%s AND source_id=%s AND phase=2 ORDER BY sequence""", (self.tenant_id, source["id"])))
        active = None
        for row in rows:
            if row["kind"] == "revalue":
                active = row
            elif row["kind"] == "reverse_revaluation":
                active = None
        return {"recognized": bool(rows), "sequence": len(rows),
                "foreign_paid_minor": sum(row["payload"]["equation"]["foreign_minor"] for row in rows if row["kind"] == "settle"),
                "historical_released_minor": sum(row["payload"]["equation"]["historical_release_minor"] for row in rows if row["kind"] == "settle"),
                "last_posting_date": rows[-1]["payload"]["posting_date"] if rows else source["request"]["posting_date"],
                "active_revaluation_plan_id": active["id"] if active else None,
                "unrealized_fx_minor": active["payload"]["equation"]["unrealized_fx_minor"] if active else 0}

    def _prepare(self, source: Mapping[str, Any], *, kind: str, equation: dict[str, Any], period_id: str,
                 posting_date: str, reason: str, sequence: int, request: Mapping[str, Any],
                 command_id: str, digest: str, actor: PostingActor, reverses_posting_id: str | None = None) -> dict[str, Any]:
        if self.connection.execute("SELECT 1 FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND source_id=%s AND phase<2",
                                   (self.tenant_id, source["id"])).fetchone():
            fail("Complete the pending foreign receivable operation first.", "fx_state_conflict")
        plan_id = "FX1-" + uuid4().hex
        precision = source["functional_policy"]["currency_precision"]
        scope = {key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}
        burden = sum(line["debit_minor"] for line in equation["lines"])
        self._authorize(actor, "finance_core.manage", source, {**scope, "kind": kind, "equation": equation,
                        "amount_minor": burden, "currency_precision": precision})
        entry = self.owner.finance.create_entry(entry_number=plan_id.upper(),
            organization_code=source["request"]["organization_code"], entity_code=source["request"]["entity_code"],
            period_id=period_id, journal_code=source["request"]["journal_code"], posting_date=posting_date,
            description=reason, workspace=source["workspace_id"], external_reference="FX:" + source["id"] + ":" + kind,
            source_type="Generated" if reverses_posting_id else "Manual",
            actor_label=actor.username, lines=[{"account_code": line["account_code"],
                "debit": exact_minor_text(line["debit_minor"], precision) if line["debit_minor"] else "0",
                "credit": exact_minor_text(line["credit_minor"], precision) if line["credit_minor"] else "0",
                "description": reason} for line in equation["lines"]])
        if reverses_posting_id:
            self.connection.execute("UPDATE reconforge.finance_entries SET reverses_posting_id=%s WHERE tenant_id=%s AND id=%s",
                                    (reverses_posting_id, self.tenant_id, entry["id"]))
        snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
        if any(snapshot["entry"][key] != value for key, value in source["functional_policy"].items()):
            fail("Native GL must retain the original functional currency policy.", "fx_currency_invalid")
        plan = {"schema_version": "operational-fx-plan-v2" if kind in {"revalue", "reverse_revaluation"} else "operational-fx-plan-v1",
                "id": plan_id, "source_id": source["id"], **scope,
                "kind": kind, "sequence": sequence, "period_id": period_id, "posting_date": posting_date, "reason": reason,
                "currency_code": source["functional_policy"]["currency_code"], "currency_precision": precision,
                "source_digest": source["source_digest"], "entry_id": entry["id"], "equation": equation,
                "amount_minor": burden, "snapshot": snapshot, "preparer_actor_id": actor.user_id, "command_request": dict(request)}
        plan.update(plan_digest=digest_payload(plan), validation_digest=validation_digest(snapshot))
        audit, outbox = self.owner._event(plan, "operational_fx_prepared", actor, {"plan_digest": plan["plan_digest"]})
        self.connection.execute("""INSERT INTO reconforge.operational_fx_plans
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_id,entry_id,sequence,kind,phase,payload,audit_event_id,outbox_event_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s)""", (self.tenant_id, plan_id, *scope.values(), source["id"],
            entry["id"], sequence, kind, canonical_json(plan), audit, outbox))
        return self._remember(plan, "prepare", command_id, actor, digest, request)

    def prepare_invoice(self, request: ForeignInvoicePreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            digest, replay = self._command(args, "prepare", command_id, actor, {"kind": "recognize", **args})
            self._period(request.period_id)
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(request.workspace_id)
            if replay is not None:
                self._authorize(actor, "finance_core.manage", self._source(replay["source_id"]), replay)
                self.connection.execute("SELECT reconforge.fx_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            rows = records(self.connection.execute("""SELECT e.currency_code,c.minor_units FROM reconforge.legal_entities e
                JOIN reconforge.currencies c ON c.tenant_id=e.tenant_id AND c.code=e.currency_code AND c.active
                WHERE e.tenant_id=%s AND e.id=%s AND e.organization_id=%s FOR SHARE OF e,c""",
                (self.tenant_id, request.legal_entity_id, request.organization_id)))
            if not rows:
                fail("A current functional currency and entity are required.", "fx_scope_denied")
            foreign_master = records(self.connection.execute("SELECT minor_units FROM reconforge.currencies WHERE tenant_id=%s AND code=%s AND active FOR SHARE",
                                                            (self.tenant_id, request.foreign_currency_code)))
            if not foreign_master:
                fail("An active foreign currency master is required.", "fx_currency_invalid")
            store = FinancePolicyStore(self.connection, tenant_id=self.tenant_id)
            _, context = store.capture(workspace_id=request.workspace_id, currency_code=request.foreign_currency_code,
                                       minor_units=foreign_master[0]["minor_units"], actor_label=actor.username)
            store.capture(workspace_id=request.workspace_id, currency_code=rows[0]["currency_code"], minor_units=rows[0]["minor_units"], actor_label=actor.username)
            equation = invoice_equation(request, rows[0]["currency_code"], context)
            source = {"schema_version": "operational-fx-source-v1", "id": "FX-" + uuid4().hex,
                      **{key: args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")},
                      **equation, "preparer_actor_id": actor.user_id}
            self._authorize(actor, "finance_core.manage", source)
            invoice = self.ar.create_invoice(invoice_number="FX1-" + request.invoice_number, customer_code=request.customer_code,
                invoice_date=request.posting_date, due_date=request.due_date, currency_code=request.foreign_currency_code,
                tax_minor=equation["foreign_tax_minor"], lines=[ReceivableInvoiceLineInput(description=request.reason, quantity="1",
                    unit_price_minor=request.net_minor, tax_minor=equation["foreign_tax_minor"], line_total_minor=request.net_minor)],
                workspace=request.workspace_id, organization_code=request.organization_code, entity_code=request.entity_code,
                idempotency_key="FX1:invoice:" + command_id, actor_label=actor.username)
            invoice = self.ar.submit_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            source["invoice_id"] = invoice["id"]
            source["source_digest"] = digest_payload(source)
            self.connection.execute("""INSERT INTO reconforge.operational_fx_sources
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,invoice_id,payload) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                (self.tenant_id, source["id"], request.workspace_id, request.organization_id, request.legal_entity_id,
                 invoice["id"], canonical_json(source)))
            return self._prepare(source, kind="recognize", equation={"lines": equation["lines"]}, period_id=request.period_id,
                posting_date=request.posting_date, reason=request.reason, sequence=0, request={"kind": "recognize", **args}, command_id=command_id, digest=digest, actor=actor)

    def prepare_settlement(self, source_id: str, *, foreign_minor: int, settlement_rate: HistoricalRate,
                           period_id: str, posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"kind": "settle", "source_id": text(source_id, "source_id"), "foreign_minor": foreign_minor,
                   "settlement_rate": settlement_rate.payload(posting_date), "period_id": text(period_id, "period_id"),
                   "posting_date": canonical_day(posting_date, "posting_date"), "reason": text(reason, "reason", maximum=500)}
        with self.owner._transaction():
            source = self._peek("source", source_id)
            self._authorize(actor, "finance_core.manage", source)
            digest, replay = self._command(source, "prepare", command_id, actor, request)
            self._period(period_id)
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(source["workspace_id"])
            source = self._source(source_id)
            if replay is not None:
                self._authorize(actor, "finance_core.manage", source, replay)
                self.connection.execute("SELECT reconforge.fx_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            state = self._state(source)
            if state["active_revaluation_plan_id"]:
                fail("Explicitly reverse the posted closing valuation before settling its historical source.", "fx_state_conflict")
            if not state["recognized"] or state["sequence"] > MAX_SETTLEMENTS or posting_date < state["last_posting_date"]:
                fail("A posted recognition, monotonic date and bounded settlement history are required.", "fx_state_invalid")
            _, context = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(source["foreign_policy"])
            equation = settlement_equation(source, foreign_minor=foreign_minor, foreign_before_minor=state["foreign_paid_minor"],
                historical_before_minor=state["historical_released_minor"], settlement_rate=settlement_rate, posting_date=posting_date, context=context)
            return self._prepare(source, kind="settle", equation=equation, period_id=period_id, posting_date=posting_date,
                reason=str(request["reason"]), sequence=state["sequence"], request=request, command_id=command_id, digest=digest, actor=actor)

    def prepare_revaluation(self, source_id: str, *, closing_rate: HistoricalRate, unrealized_gain_account_code: str,
                            unrealized_loss_account_code: str, period_id: str, posting_date: str, reason: str,
                            command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"kind": "revalue", "source_id": text(source_id, "source_id"), "closing_rate": closing_rate.payload(posting_date),
                   "unrealized_gain_account_code": text(unrealized_gain_account_code, "unrealized gain account", maximum=64),
                   "unrealized_loss_account_code": text(unrealized_loss_account_code, "unrealized loss account", maximum=64),
                   "period_id": text(period_id, "period_id"), "posting_date": canonical_day(posting_date, "posting_date"),
                   "reason": text(reason, "reason", maximum=500)}
        return self._prepare_valuation(source_id, request=request, command_id=command_id, actor=actor)

    def prepare_revaluation_reversal(self, source_id: str, *, original_revaluation_id: str, period_id: str,
                                    posting_date: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"kind": "reverse_revaluation", "source_id": text(source_id, "source_id"),
                   "original_revaluation_id": text(original_revaluation_id, "original revaluation"),
                   "period_id": text(period_id, "period_id"), "posting_date": canonical_day(posting_date, "posting_date"),
                   "reason": text(reason, "reason", maximum=500)}
        return self._prepare_valuation(source_id, request=request, command_id=command_id, actor=actor)

    def _prepare_valuation(self, source_id: str, *, request: dict[str, Any], command_id: str,
                           actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._peek("source", source_id)
            self._authorize(actor, "finance_core.manage", source)
            digest, replay = self._command(source, "prepare", command_id, actor, request)
            self._period(request["period_id"])
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(source["workspace_id"])
            source = self._source(source_id)
            if replay is not None:
                self._authorize(actor, "finance_core.manage", source, replay)
                self.connection.execute("SELECT reconforge.fx_close(%s,%s)", (self.tenant_id, replay["id"]))
                return replay
            state = self._state(source)
            if not state["recognized"] or state["sequence"] > MAX_SETTLEMENTS or request["posting_date"] < state["last_posting_date"]:
                fail("A posted recognition, monotonic date and bounded operation history are required.", "fx_state_invalid")
            reversal = None
            if request["kind"] == "revalue":
                if state["active_revaluation_plan_id"]:
                    fail("Explicitly reverse the previous closing valuation first.", "fx_state_conflict")
                _, context = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).entry(source["foreign_policy"])
                equation = revaluation_equation(source, foreign_before_minor=state["foreign_paid_minor"],
                    historical_before_minor=state["historical_released_minor"], closing_rate=HistoricalRate(**request["closing_rate"]),
                    posting_date=request["posting_date"], unrealized_gain_account_code=request["unrealized_gain_account_code"],
                    unrealized_loss_account_code=request["unrealized_loss_account_code"], context=context)
            else:
                if state["active_revaluation_plan_id"] != request["original_revaluation_id"]:
                    fail("Use the exact active posted closing valuation.", "fx_state_conflict")
                original = self._view(request["original_revaluation_id"])
                self._authorize(actor, "finance_core.manage", source, original)
                equation = reversal_equation(original)
                reversal = original["posting_effect_id"]
            return self._prepare(source, kind=request["kind"], equation=equation, period_id=request["period_id"],
                posting_date=request["posting_date"], reason=request["reason"], sequence=state["sequence"], request=request,
                command_id=command_id, digest=digest, actor=actor, reverses_posting_id=reversal)

    def _phase(self, operation: str, plan_id: str, *, expected_plan_digest: str, reason: str,
               command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest, "reason": text(reason, "reason", maximum=500)}
        permission = "finance_core.validate" if operation == "review" else "finance_core.post"
        with self.owner._transaction():
            plan = self._peek("plan", plan_id)
            source = self._peek("source", plan["source_id"])
            self._authorize(actor, permission, source, plan)
            digest, replay = self._command(plan, operation, command_id, actor, request)
            self._period(plan["period_id"])
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(plan["workspace_id"])
            plan = self._plan(plan_id)
            source = self._source(plan["source_id"])
            # Grants can be revoked while the command waits for a currency or
            # native parent lock; retained ACKs require authority at return.
            self._authorize(actor, permission, source, plan)
            if replay is not None:
                self.connection.execute("SELECT reconforge.fx_close(%s,%s)", (self.tenant_id, plan_id))
                return replay
            if plan["plan_digest"] != expected_plan_digest or plan["phase"] != (0 if operation == "review" else 1):
                fail("Use the current retained plan digest and expected lifecycle phase.", "fx_state_conflict")
            if actor.user_id == plan["preparer_actor_id"]:
                fail("An independent reviewer and third posting human are required.", "fx_actor_denied")
            state = self._state(source)
            if plan["sequence"] != state["sequence"]:
                fail("The foreign residual changed after preparation.", "fx_state_conflict")
            if operation == "review":
                if plan["kind"] == "recognize":
                    invoice = self.ar.get_invoice(source["invoice_id"])
                    self.ar.approve_invoice(source["invoice_id"], expected_version=invoice["row_version"], actor_label=actor.username)
                self.owner.finance.validate_entry(plan["entry_id"], reason=request["reason"], actor_label=actor.username)
                audit, outbox = self.owner._event(plan, "operational_fx_reviewed", actor, {"plan_digest": plan["plan_digest"]})
                self.connection.execute("""INSERT INTO reconforge.operational_fx_reviews
                    (tenant_id,plan_id,reviewer_actor_id,reason,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s)""",
                    (self.tenant_id, plan_id, actor.user_id, request["reason"], audit, outbox))
                phase = 1
            else:
                if actor.user_id == self._view(plan_id)["reviewer_actor_id"]:
                    fail("Posting requires a third distinct human.", "fx_actor_denied")
                receipt_id = None
                if plan["kind"] == "settle":
                    receipt = self.ar.post_receipt(receipt_number=plan_id, customer_code=source["request"]["customer_code"],
                        receipt_date=plan["posting_date"], currency_code=source["foreign_policy"]["currency_code"],
                        amount_minor=plan["equation"]["foreign_minor"], allocations=[ReceiptAllocationInput(source["invoice_id"], plan["equation"]["foreign_minor"])],
                        workspace=source["workspace_id"], organization_code=source["request"]["organization_code"], entity_code=source["request"]["entity_code"],
                        idempotency_key="FX1:receipt:" + command_id, actor_label=actor.username)
                    receipt_id = receipt["id"]
                self._participant = _FxPostingParticipant(self, plan["entry_id"])
                try:
                    effect = self.owner.posting.post(plan["entry_id"], command_id="FX1:" + command_id,
                        expected_validation_digest=plan["validation_digest"], reason=request["reason"], actor=actor, _source_owner=self._participant)
                finally:
                    self._participant = None
                audit, outbox = self.owner._event(plan, "operational_fx_posted", actor, {"plan_digest": plan["plan_digest"], "posting_effect_id": effect["id"]})
                self.connection.execute("""INSERT INTO reconforge.operational_fx_links
                    (tenant_id,plan_id,posting_effect_id,receipt_id,posted_actor_id,reason,audit_event_id,outbox_event_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (self.tenant_id, plan_id, effect["id"], receipt_id, actor.user_id, request["reason"], audit, outbox))
                phase = 2
            self.connection.execute("UPDATE reconforge.operational_fx_plans SET phase=%s WHERE tenant_id=%s AND id=%s", (phase, self.tenant_id, plan_id))
            return self._remember(plan, operation, command_id, actor, digest, request)

    def review(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase("review", plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def post(self, plan_id: str, *, expected_plan_digest: str, reason: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self._phase("post", plan_id, expected_plan_digest=expected_plan_digest, reason=reason, command_id=command_id, actor=actor)

    def get(self, source_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._source(source_id)
            self._authorize(actor, "finance_core.read", source, mutation=False)
            ids = records(self.connection.execute("SELECT id FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND source_id=%s ORDER BY sequence", (self.tenant_id, source_id)))
            plans = [self._view(row["id"]) for row in ids]
            for plan in plans:
                self._authorize(actor, "finance_core.read", source, plan, mutation=False)
                self.connection.execute("SELECT reconforge.fx_close(%s,%s)", (self.tenant_id, plan["id"]))
            state = self._state(source)
            return {**source, **state, "foreign_outstanding_minor": source["foreign_gross_minor"] - state["foreign_paid_minor"],
                    "functional_outstanding_minor": source["functional_gross_minor"] - state["historical_released_minor"],
                    "valued_functional_outstanding_minor": source["functional_gross_minor"] - state["historical_released_minor"] + state["unrealized_fx_minor"],
                    "plans": plans}

    def list_sources(self, scope: Mapping[str, Any], *, actor: PostingActor, after: str = "", limit: int = 25) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            fail("Use a bounded page size between one and 100.")
        with self.owner._transaction():
            self.owner._actor(actor, "finance_core.read", scope, mutation=False)
            rows = records(self.connection.execute("""SELECT id,payload FROM reconforge.operational_fx_sources
                WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND id>%s ORDER BY id COLLATE "C" LIMIT %s""",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], after, limit + 1)))
            for row in rows[:limit]:
                self._authorize(actor, "finance_core.read", row["payload"], mutation=False)
            return {"invoices": [row["payload"] for row in rows[:limit]], "next_after": rows[limit - 1]["id"] if len(rows) > limit else None}

    def plan_evidence(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            plan = self._plan(plan_id)
            source = self._source(plan["source_id"])
            self._authorize(actor, "finance_core.read", source, plan, mutation=False)
            self.connection.execute("SELECT reconforge.fx_close(%s,%s)", (self.tenant_id, plan_id))
            view = self._view(plan_id)
            native = self.owner.posting.get_effect(view["posting_effect_id"], actor=actor) if plan["phase"] == 2 else None
            phases = records(self.connection.execute("""SELECT 'operational_fx_prepared' AS action, payload->>'preparer_actor_id' AS actor_id,audit_event_id,outbox_event_id
                FROM reconforge.operational_fx_plans WHERE tenant_id=%s AND id=%s
                UNION ALL SELECT 'operational_fx_reviewed',reviewer_actor_id,audit_event_id,outbox_event_id FROM reconforge.operational_fx_reviews WHERE tenant_id=%s AND plan_id=%s
                UNION ALL SELECT 'operational_fx_posted',posted_actor_id,audit_event_id,outbox_event_id FROM reconforge.operational_fx_links WHERE tenant_id=%s AND plan_id=%s""",
                (self.tenant_id, plan_id, self.tenant_id, plan_id, self.tenant_id, plan_id)))
            if native:
                phases.append({"action": "finance_entry_posted", "actor_id": native["posted_actor_id"], "audit_event_id": native["audit_event_id"], "outbox_event_id": native["outbox_event_id"]})
            return {"schema_version": "operational-fx-native-evidence-v1", "source": source, "plan": view,
                "canonical_source_json": canonical_json({key: value for key, value in source.items() if key != "source_digest"}),
                "canonical_plan_json": canonical_json({key: value for key, value in plan.items() if key not in {"phase", "plan_digest", "validation_digest"}}),
                "canonical_snapshot_json": canonical_json(plan["snapshot"]),
                "native_effect": {key: native[key] for key in ("id", "entry_id", "validation_digest", "posted_actor_id", "audit_event_id", "outbox_event_id")} if native else None,
                "phases": phases, "totals": {side + "_minor": str(sum(line[side + "_minor"] for line in plan["snapshot"]["lines"])) for side in ("debit", "credit")}}
