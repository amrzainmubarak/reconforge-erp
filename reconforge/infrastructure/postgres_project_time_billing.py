"""Whole approved project time owns native AR, project revenue and cash."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from reconforge.domain.finance_posting import PostingActor, canonical_json, digest_payload, text, validation_digest
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.people_project_payroll import PeopleScope
from reconforge.domain.project_time_billing import (
    ProjectPriceAgreement,
    allocate_bill,
    collection_amount,
    fail,
    integer,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.platform.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput


class _ProjectBillingPostingParticipant:
    def __init__(self, owner: "PostgresProjectTimeBillingRepository", entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class PostgresProjectTimeBillingRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self.ar = PostgresReceivablesRepository(connection, tenant_id)
        self.policy = FinancePolicyStore(connection, tenant_id=tenant_id)
        self._participant: _ProjectBillingPostingParticipant | None = None

    def _authorization_view(self, source: Mapping[str, Any]) -> dict[str, Any]:
        """Project money for policy evaluation without changing sealed source JSON."""
        value = dict(source.get("payload", source.get("source_json", source)))
        if "hourly_price_minor" in value:
            policy = value.get("monetary_policy")
            if not isinstance(policy, Mapping) or type(policy.get("currency_precision")) is not int:
                fail("A price authorization requires its explicit captured currency policy.")
            value.update(amount_minor=value["hourly_price_minor"], currency_precision=policy["currency_precision"])
        return value

    def _authorize(self, actor: PostingActor, action: str, scope: Mapping[str, Any], *, mutation: bool = True) -> None:
        scope = self._authorization_view(scope)
        self.owner._actor(actor, "project_time_billing." + action, scope, mutation=mutation)
        if action == "manage":
            self.owner._actor(actor, "receivables.read", scope, mutation=False)
        try:
            self.connection.execute("SELECT reconforge.hc_actor(%s,%s,%s,%s,%s,%s)",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"],
                 actor.user_id, "project_time_billing." + action))
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23514":
                fail("Current persisted source permission and hierarchy grants are required.", "project_billing_actor_denied")
            raise

    def _financial_read(self, actor: PostingActor, source: Mapping[str, Any]) -> None:
        scope = self._authorization_view(source)
        self._authorize(actor, "read", scope, mutation=False)
        for permission in ("finance_core.read", "people_project_payroll.read", "receivables.read"):
            self.owner._actor(actor, permission, scope, mutation=False)
        if scope.get("schema_version") == "project-invoice-v1":
            # A short invoice can expose an original hourly price above its own
            # amount. Authorize that retained price with its captured policy,
            # including when it appears inside sealed calculation.sources.
            price_ids = scope["calculation"]["price_ids"]
            prices = records(self.connection.execute(
                "SELECT * FROM reconforge.pb_prices WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id FOR SHARE",
                (self.tenant_id, price_ids)))
            if len(prices) != len(price_ids) or {price["id"] for price in prices} != set(price_ids):
                fail("Every retained invoice price requires its original scoped source.")
            for price in prices:
                self._financial_read(actor, price)

    def _financial(self, actor: PostingActor, action: str, source: Mapping[str, Any]) -> None:
        self._authorize(actor, action, source)
        finance = {"prepare": "manage", "collect": "manage", "review": "validate", "post": "post"}[action]
        self.owner._actor(actor, "finance_core." + finance, source)
        self.owner._actor(actor, "receivables." + ("receive" if action == "collect" else "approve" if action == "post" else "manage"), source)
        if action == "post":
            self.owner._actor(actor, "receivables.receive", source)

    def _command(self, source: Mapping[str, Any], action: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        text(command_id, "Command ID", maximum=140)
        digest = digest_payload({"operation": action, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, source["workspace_id"], "project-time-billing", command_id]),))
        prior = records(self.connection.execute("SELECT * FROM reconforge.pb_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, source["workspace_id"], command_id)))
        if prior:
            if (prior[0]["actor_id"], prior[0]["operation"], prior[0]["request_digest"]) != (actor.user_id, action, digest):
                fail("Command belongs to another original actor or exact request.", "project_billing_command_conflict")
            return digest, dict(prior[0]["response_json"])
        return digest, None

    def _remember(self, source: Mapping[str, Any], action: str, command_id: str, actor: PostingActor,
                  request: Mapping[str, Any], digest: str, response: dict[str, Any]) -> dict[str, Any]:
        self.connection.execute("""INSERT INTO reconforge.pb_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,operation,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, source["workspace_id"], source["organization_id"], source["legal_entity_id"], command_id,
             action, actor.user_id, digest, canonical_json(dict(request)), canonical_json(response)))
        return response

    def _row(self, identifier: str, *, price: bool = False, lock: bool = False, share: bool = False) -> dict[str, Any]:
        statement = ("SELECT * FROM reconforge.pb_prices WHERE tenant_id=%s AND id=%s" if price
                     else "SELECT * FROM reconforge.pb_plans WHERE tenant_id=%s AND id=%s")
        rows = records(self.connection.execute(statement + (" FOR UPDATE" if lock else " FOR SHARE" if share else ""),
            (self.tenant_id, text(identifier, "Original source"))))
        if not rows:
            fail("Original project source is absent or outside scope.", "project_billing_source_not_found")
        return rows[0]

    def _view(self, source: Mapping[str, Any], *, price: bool = False) -> dict[str, Any]:
        if price:
            return {**source["source_json"], "source_digest": source["source_digest"], "approver_id": source["approver_id"],
                    "status": "Approved" if source["approver_id"] else "Submitted"}
        return {**source["payload"], "phase": source["phase"],
            "status": {0: "Prepared", 1: "Reviewed", 2: "Posted", 3: "Cancelled"}[source["phase"]],
            "reviewer_id": source["reviewer_id"], "posted_actor_id": source["poster_id"], "posting_effect_id": source["effect_id"],
            "receipt_id": source["receipt_id"]}

    def _event(self, source: Mapping[str, Any], action: str, actor: PostingActor, digest: str) -> tuple[str, str]:
        return self.owner._event(source, "project_billing_" + action, actor, {"source_digest": digest})

    @contextmanager
    def _native_ar_owner(self, plan_id: str, *, collection: bool = False) -> Iterator[None]:
        selector = "app.pb_collection_source" if collection else "app.pb_invoice_source"
        previous = records(self.connection.execute("SELECT current_setting(%s,true) AS original", (selector,)))[0]["original"]
        if previous:
            fail("An unrelated native AR owner selector is already active.")
        # This is a routing hint, never authorization. A unique deferred FK and
        # full source/actor/AR/GL closure bind the actual created native header.
        with self.connection.transaction():
            self.connection.execute("SELECT set_config(%s,%s,true)", (selector, plan_id))
            yield
            self.connection.execute("SELECT set_config(%s,%s,true)", (selector, previous or ""))

    def register_price(self, request: ProjectPriceAgreement, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        args = request.payload()
        with self.owner._transaction():
            # Initial permission/hierarchy admission precedes native customer
            # lookup; exact hourly admission follows captured currency policy.
            self._authorize(actor, "manage", {key: args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")})
            self.policy.lock_binding(request.scope.workspace_id)
            digest, replay = self._command(args, "manage", command_id, actor, args)
            if replay is not None:
                self._authorize(actor, "manage", replay)
                return replay
            project = records(self.connection.execute("SELECT * FROM reconforge.hc_projects WHERE tenant_id=%s AND id=%s FOR SHARE",
                (self.tenant_id, request.project_id)))
            if len(project) != 1 or any(project[0][key] != args[key] for key in ("workspace_id", "organization_id", "legal_entity_id")):
                fail("Price requires its original scoped Project.")
            customer = self.ar._customer_by_code(request.scope.workspace_id, request.customer_code, lock=True)
            currency = records(self.connection.execute("SELECT currency_code FROM reconforge.legal_entities WHERE tenant_id=%s AND id=%s AND active FOR SHARE",
                (self.tenant_id, request.scope.legal_entity_id)))
            if (customer["organization_id"], customer["legal_entity_id"], customer["currency_code"]) != (
                    request.scope.organization_id, request.scope.legal_entity_id, request.currency_code) or not currency or currency[0]["currency_code"] != request.currency_code:
                fail("First project billing contract requires the customer's original functional currency and entity.")
            policy = self.ar._capture_policy(request.scope.workspace_id, request.currency_code, actor.username, customer)
            self._authorize(actor, "manage", {**args, "monetary_policy": {"currency_code": request.currency_code, **policy.metadata()}})
            identifier = "PBP-" + uuid4().hex
            payload = {"id": identifier, "tenant_id": self.tenant_id, **args, "preparer_id": actor.user_id,
                "dimension_id": project[0]["dimension_id"], "value_id": project[0]["value_id"],
                "monetary_policy": {"currency_code": request.currency_code, **policy.metadata()}}
            sealed = digest_payload(payload)
            audit, outbox = self._event(payload, "price_registered", actor, sealed)
            self.connection.execute("""INSERT INTO reconforge.pb_prices
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,project_id,customer_code,valid_from,valid_through,currency_code,
                 hourly_price_minor,source_json,source_digest,preparer_id,audit_id,outbox_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s)""",
                (self.tenant_id, identifier, args["workspace_id"], args["organization_id"], args["legal_entity_id"], request.project_id,
                 request.customer_code, request.valid_from, request.valid_through, request.currency_code, request.hourly_price_minor,
                 canonical_json(payload), sealed, actor.user_id, audit, outbox))
            return self._remember(args, "manage", command_id, actor, args, digest, self._view(self._row(identifier, price=True), price=True))

    def approve_price(self, price_id: str, *, expected_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"price_id": price_id, "expected_digest": expected_digest}
        with self.owner._transaction():
            # Match the existing financial commands: hold persisted authority
            # before source locks, then recheck the locked original money view.
            preview = self._row(price_id, price=True)
            self._authorize(actor, "approve_price", preview)
            source = self._row(price_id, price=True, lock=True)
            self._authorize(actor, "approve_price", source)
            digest, replay = self._command(source, "approve_price", command_id, actor, request)
            if replay is not None:
                return replay
            if source["source_digest"] != expected_digest or source["approver_id"] or source["preparer_id"] == actor.user_id:
                fail("Exact price requires an independent current human approval.")
            audit, outbox = self._event(source, "price_approved", actor, expected_digest)
            self.connection.execute("UPDATE reconforge.pb_prices SET approver_id=%s,approve_audit_id=%s,approve_outbox_id=%s WHERE tenant_id=%s AND id=%s",
                (actor.user_id, audit, outbox, self.tenant_id, price_id))
            return self._remember(source, "approve_price", command_id, actor, request, digest, self._view(self._row(price_id, price=True), price=True))

    def _snapshot(self, entry_id: str) -> dict[str, Any]:
        return posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry_id))

    def _period(self, scope: Mapping[str, Any], period_id: str, day: str) -> None:
        period = records(self.connection.execute("SELECT id,status,start_date,end_date FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id=%s AND application_workspace_id=%s FOR SHARE",
            (self.tenant_id, period_id, scope["workspace_id"])))
        if len(period) != 1 or period[0]["status"] != "Open" or not str(period[0]["start_date"]) <= day <= str(period[0]["end_date"]):
            fail("The current original fiscal period must be open and contain the exact posting date.", "project_billing_period_locked")

    def _insert_plan(self, payload: dict[str, Any], *, kind: str, actor: PostingActor) -> dict[str, Any]:
        payload["plan_digest"] = digest_payload(payload)
        audit, outbox = self._event(payload, "prepared", actor, payload["plan_digest"])
        self.connection.execute("""INSERT INTO reconforge.pb_plans
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,kind,parent_id,ar_invoice_id,entry_id,amount_minor,phase,payload,preparer_id,audit_id,outbox_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s,%s)""",
            (self.tenant_id, payload["id"], payload["workspace_id"], payload["organization_id"], payload["legal_entity_id"], kind,
             payload.get("parent_id"), payload["ar_invoice_id"], payload["entry_id"], payload["amount_minor"], canonical_json(payload), actor.user_id, audit, outbox))
        return self._view(self._row(payload["id"]))

    def prepare_invoice(self, scope: PeopleScope, *, time_ids: list[str], price_ids: list[str], customer_code: str,
                        invoice_number: str, period_id: str, posting_date: str, due_date: str, journal_code: str,
                        receivable_account_code: str, revenue_account_code: str, cash_account_code: str,
                        command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {**asdict(scope), "time_ids": time_ids, "price_ids": price_ids, "customer_code": customer_code,
            "invoice_number": invoice_number, "period_id": period_id, "posting_date": posting_date, "due_date": due_date,
            "journal_code": journal_code, "receivable_account_code": receivable_account_code,
            "revenue_account_code": revenue_account_code, "cash_account_code": cash_account_code}
        if len(set(time_ids)) != len(time_ids) or len(set(price_ids)) != len(price_ids):
            fail("Whole original sources must be unique.")
        with self.owner._transaction():
            self._financial(actor, "prepare", request)
            self.owner._actor(actor, "people_project_payroll.read", request, mutation=False)
            self._period(request, period_id, posting_date)
            self.policy.lock_binding(scope.workspace_id)
            digest, replay = self._command(request, "prepare", command_id, actor, request)
            if replay is not None:
                return replay
            customer = self.ar._customer_by_code(scope.workspace_id, customer_code, lock=True)
            policy = self.ar._capture_policy(scope.workspace_id, customer["currency_code"], actor.username, customer)
            _, context = self.policy.entry({"currency_code": customer["currency_code"], **policy.metadata()})
            times = records(self.connection.execute("SELECT * FROM reconforge.hc_times WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id FOR UPDATE",
                (self.tenant_id, time_ids)))
            prices = records(self.connection.execute("SELECT * FROM reconforge.pb_prices WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id FOR SHARE",
                (self.tenant_id, price_ids)))
            if len(times) != len(time_ids) or len(prices) != len(price_ids):
                fail("Original approved whole sources must be visible in their complete bounded population.")
            for row in times:
                row["business_date"] = row["business_date"].isoformat()
            for row in prices:
                row.update({**row["source_json"], "source_json": row["source_json"]})
            calculated = allocate_bill(scope, tenant_id=self.tenant_id, customer_code=customer_code,
                currency_code=customer["currency_code"], registry_context=context, approved_time=times, approved_prices=prices)
            identifier = "PB1-" + uuid4().hex
            with self._native_ar_owner(identifier):
                ar_invoice = self.ar.create_invoice(invoice_number=invoice_number, customer_code=customer_code, invoice_date=posting_date,
                    due_date=due_date, currency_code=customer["currency_code"], tax_minor=0,
                    lines=[ReceivableInvoiceLineInput(project, "1", amount, amount, 0) for project, amount in calculated["project_minor"].items()],
                    workspace=scope.workspace_id, organization_code=scope.organization_code, entity_code=scope.entity_code,
                    idempotency_key=identifier, actor_label=actor.username)
            self.ar.submit_invoice(ar_invoice["id"], expected_version=ar_invoice["row_version"], actor_label=actor.username)
            projects = {row["id"]: row for row in records(self.connection.execute("SELECT * FROM reconforge.hc_projects WHERE tenant_id=%s AND id=ANY(%s)",
                (self.tenant_id, list(calculated["project_minor"]))))}
            lines: list[dict[str, Any]] = [{"account_code": receivable_account_code,
                "debit": exact_minor_text(calculated["amount_minor"], policy.precision), "credit": "0", "description": "Original project receivable"}]
            lines.extend({"account_code": revenue_account_code, "debit": "0", "credit": exact_minor_text(amount, policy.precision),
                "description": "Approved project time revenue", "dimensions": {projects[project]["dimension_code"]: projects[project]["value_code"]}}
                for project, amount in calculated["project_minor"].items())
            entry = self.owner.finance.create_entry(entry_number=identifier, organization_code=scope.organization_code,
                entity_code=scope.entity_code, period_id=period_id, journal_code=journal_code, posting_date=posting_date,
                description="Approved project time billing", lines=lines, workspace=scope.workspace_id,
                external_reference=identifier, actor_label=actor.username)
            snapshot = self._snapshot(entry["id"])
            payload = {"schema_version": "project-invoice-v1", "id": identifier, **asdict(scope), "customer_code": customer_code,
                "ar_invoice_id": ar_invoice["id"], "customer_id": customer["id"], "invoice_number": invoice_number,
                "entry_id": entry["id"], "period_id": period_id, "posting_date": posting_date, "due_date": ar_invoice["due_date"],
                "journal_code": journal_code, "receivable_account_code": receivable_account_code,
                "revenue_account_code": revenue_account_code, "cash_account_code": cash_account_code,
                "calculation": calculated, "amount_minor": calculated["amount_minor"], "currency_precision": policy.precision,
                "monetary_policy": {"currency_code": customer["currency_code"], **policy.metadata()}, "snapshot": snapshot,
                "validation_digest": validation_digest(snapshot), "preparer_id": actor.user_id, "command_request": request}
            result = self._insert_plan(payload, kind="Invoice", actor=actor)
            for role, account_code in (("receivable", receivable_account_code), ("revenue", revenue_account_code), ("cash", cash_account_code)):
                account = records(self.connection.execute("SELECT a.id,a.chart_id,a.account_type FROM reconforge.finance_accounts a JOIN reconforge.finance_journals j ON j.tenant_id=a.tenant_id AND j.chart_id=a.chart_id WHERE a.tenant_id=%s AND a.workspace_id=%s AND a.account_code=%s AND j.id=%s",
                    (self.tenant_id, scope.workspace_id, account_code, snapshot["entry"]["journal_id"])))
                if len(account) != 1:
                    fail("Original source account must belong to its native journal chart.")
                self.connection.execute("INSERT INTO reconforge.pb_account_pins VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (self.tenant_id, identifier, role, account[0]["id"], scope.workspace_id, account[0]["chart_id"], account_code, account[0]["account_type"]))
            for time_id in sorted(time_ids):
                self.connection.execute("SELECT reconforge.pb_claim(%s,%s,%s,%s,%s)", (self.tenant_id, time_id, identifier, "Claim", actor.user_id))
            return self._remember(request, "prepare", command_id, actor, request, digest, result)

    def _locked(self, plan_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        preview = self._row(plan_id)
        parent_id = preview["parent_id"] or plan_id
        parent = self._row(parent_id, lock=True)
        return (parent if parent_id == plan_id else self._row(plan_id, lock=True)), parent

    def prepare_collection(self, invoice_id: str, *, amount_minor: int, period_id: str, posting_date: str,
                           command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"invoice_id": invoice_id, "amount_minor": amount_minor, "period_id": period_id, "posting_date": posting_date}
        with self.owner._transaction():
            preview = self._row(invoice_id)
            self._financial(actor, "collect", preview["payload"])
            # Native period precedes registry and source locks, matching the
            # canonical Finance Core close/post ordering.
            self._period(preview["payload"], period_id, posting_date)
            self.policy.lock_binding(preview["workspace_id"])
            digest, replay = self._command(preview, "collect", command_id, actor, request)
            if replay is not None:
                return replay
            parent = self._row(invoice_id, lock=True)
            if parent["kind"] != "Invoice" or parent["phase"] != 2:
                fail("Collections require their original posted project invoice.")
            if self.connection.execute("SELECT 1 FROM reconforge.pb_plans WHERE tenant_id=%s AND parent_id=%s AND phase<2",
                    (self.tenant_id, invoice_id)).fetchone():
                fail("Complete the pending original collection first.", "project_billing_collection_conflict")
            prior = records(self.connection.execute("SELECT COALESCE(sum(amount_minor),0) AS amount FROM reconforge.pb_plans WHERE tenant_id=%s AND parent_id=%s AND phase=2",
                (self.tenant_id, invoice_id)))[0]["amount"]
            calculated = collection_amount(parent["amount_minor"], int(prior), amount_minor)
            v = parent["payload"]
            identifier = "PB1C-" + uuid4().hex
            entry = self.owner.finance.create_entry(entry_number=identifier, organization_code=v["organization_code"], entity_code=v["entity_code"],
                period_id=period_id, journal_code=v["journal_code"], posting_date=posting_date, description="Original project AR collection",
                lines=[{"account_code": v["cash_account_code"], "debit": exact_minor_text(amount_minor, v["currency_precision"]), "credit": "0", "description": "Recorded project cash"},
                    {"account_code": v["receivable_account_code"], "debit": "0", "credit": exact_minor_text(amount_minor, v["currency_precision"]), "description": "Original project AR settlement"}],
                workspace=v["workspace_id"], external_reference=identifier, actor_label=actor.username)
            snapshot = self._snapshot(entry["id"])
            if any(snapshot["entry"][key] != value for key, value in v["monetary_policy"].items()):
                fail("Collection cannot reinterpret original monetary policy.")
            payload = {"schema_version": "project-collection-v1", "id": identifier,
                **{key: v[key] for key in ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code")},
                "parent_id": invoice_id, "parent_digest": v["plan_digest"], "ar_invoice_id": parent["ar_invoice_id"],
                "entry_id": entry["id"], "amount_minor": amount_minor, "period_id": period_id, "posting_date": posting_date,
                "monetary_policy": v["monetary_policy"], "currency_precision": v["currency_precision"], "calculation": calculated,
                "snapshot": snapshot, "validation_digest": validation_digest(snapshot), "preparer_id": actor.user_id, "command_request": request}
            response = self._insert_plan(payload, kind="Collection", actor=actor)
            return self._remember(parent, "collect", command_id, actor, request, digest, response)

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest}
        with self.owner._transaction():
            preview = self._row(plan_id)
            self._financial(actor, "review", preview["payload"])
            digest, replay = self._command(preview, "review", command_id, actor, request)
            if replay is not None:
                return replay
            source, _ = self._locked(plan_id)
            if source["phase"] != 0 or source["payload"]["plan_digest"] != expected_plan_digest or source["preparer_id"] == actor.user_id:
                fail("Independent review requires original prepared source.")
            self.owner.finance.validate_entry(source["entry_id"], reason="Independent project billing source review", actor_label=actor.username)
            audit, outbox = self._event(source, "reviewed", actor, expected_plan_digest)
            self.connection.execute("UPDATE reconforge.pb_plans SET phase=1,reviewer_id=%s,review_audit_id=%s,review_outbox_id=%s WHERE tenant_id=%s AND id=%s",
                (actor.user_id, audit, outbox, self.tenant_id, plan_id))
            return self._remember(source, "review", command_id, actor, request, digest, self._view(self._row(plan_id)))

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest}
        with self.owner._transaction():
            preview = self._row(plan_id)
            self._financial(actor, "post", preview["payload"])
            digest, replay = self._command(preview, "post", command_id, actor, request)
            if replay is not None:
                return replay
            source, parent = self._locked(plan_id)
            if source["phase"] != 1 or source["payload"]["plan_digest"] != expected_plan_digest or actor.user_id in {source["preparer_id"], source["reviewer_id"]}:
                fail("A third distinct current human must post the reviewed billing source.")
            receipt_id = None
            if source["kind"] == "Invoice":
                ar = self.ar._invoice(source["ar_invoice_id"])
                self.ar.approve_invoice(ar["id"], expected_version=ar["row_version"], actor_label=actor.username)
            else:
                self.owner._actor(actor, "receivables.receive", source["payload"])
                v = parent["payload"]
                with self._native_ar_owner(plan_id, collection=True):
                    receipt = self.ar.post_receipt(receipt_number=plan_id.upper(), customer_code=v["customer_code"],
                        receipt_date=source["payload"]["posting_date"], currency_code=v["monetary_policy"]["currency_code"], amount_minor=source["amount_minor"],
                        allocations=[ReceiptAllocationInput(source["ar_invoice_id"], source["amount_minor"])], workspace=v["workspace_id"],
                        organization_code=v["organization_code"], entity_code=v["entity_code"], idempotency_key=plan_id, actor_label=actor.username)
                receipt_id = receipt["id"]
            self._participant = _ProjectBillingPostingParticipant(self, source["entry_id"])
            try:
                effect = self.owner.posting.post(source["entry_id"], command_id="PB1:" + command_id,
                    expected_validation_digest=source["payload"]["validation_digest"],
                    reason="Original approved project time financial publication", actor=actor, _source_owner=self._participant)
            finally:
                self._participant = None
            audit, outbox = self._event(source, "posted", actor, expected_plan_digest)
            self.connection.execute("UPDATE reconforge.pb_plans SET phase=2,poster_id=%s,effect_id=%s,receipt_id=%s,post_audit_id=%s,post_outbox_id=%s WHERE tenant_id=%s AND id=%s",
                (actor.user_id, effect["id"], receipt_id, audit, outbox, self.tenant_id, plan_id))
            if source["kind"] == "Invoice":
                for time_id in source["payload"]["calculation"]["time_ids"]:
                    self.connection.execute("SELECT reconforge.pb_claim(%s,%s,%s,%s,%s)", (self.tenant_id, time_id, plan_id, "Consume", actor.user_id))
            return self._remember(source, "post", command_id, actor, request, digest, self._view(self._row(plan_id)))

    def cancel(self, invoice_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": invoice_id, "expected_plan_digest": expected_plan_digest}
        with self.owner._transaction():
            preview = self._row(invoice_id)
            self._financial(actor, "prepare", preview["payload"])
            digest, replay = self._command(preview, "cancel", command_id, actor, request)
            if replay is not None:
                return replay
            source, _ = self._locked(invoice_id)
            if source["kind"] != "Invoice" or source["phase"] not in {0, 1} or source["payload"]["plan_digest"] != expected_plan_digest:
                fail("Only an exact unposted invoice can release whole billing-time claims.")
            audit, outbox = self._event(source, "cancelled", actor, expected_plan_digest)
            self.connection.execute("UPDATE reconforge.pb_plans SET phase=3,canceller_id=%s,cancel_audit_id=%s,cancel_outbox_id=%s WHERE tenant_id=%s AND id=%s",
                (actor.user_id, audit, outbox, self.tenant_id, invoice_id))
            for time_id in source["payload"]["calculation"]["time_ids"]:
                self.connection.execute("SELECT reconforge.pb_claim(%s,%s,%s,%s,%s)", (self.tenant_id, time_id, invoice_id, "Release", actor.user_id))
            return self._remember(source, "cancel", command_id, actor, request, digest, self._view(self._row(invoice_id)))

    def get(self, plan_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            preview = self._row(plan_id)
            self._authorize(actor, "read", preview, mutation=False)
            source = self._row(plan_id, share=True)
            self._financial_read(actor, source)
            return self._view(source)

    def _original_rows(self, source: Mapping[str, Any], plans: list[dict[str, Any]]) -> dict[str, Any]:
        """Authorized public source and native financial rows, never personnel pay fields."""
        entry_ids = [row["entry_id"] for row in plans]
        receipt_ids = [row["receipt_id"] for row in plans if row["receipt_id"]]
        v = source["payload"]
        def rows(table: str, where: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
            # All identifiers and predicates below are internal closed literals.
            return records(self.connection.execute("SELECT * FROM reconforge." + table +
                " WHERE tenant_id=%s AND " + where, (self.tenant_id, *parameters)))
        entries = records(self.connection.execute("""SELECT e.*,o.id AS organization_id,le.id AS legal_entity_id
            FROM reconforge.finance_entries e JOIN reconforge.organizations o ON o.tenant_id=e.tenant_id
             AND o.application_workspace_id=e.workspace_id AND o.organization_code=e.organization_code
            JOIN reconforge.legal_entities le ON le.tenant_id=e.tenant_id AND le.organization_id=o.id AND le.entity_code=e.entity_code
            WHERE e.tenant_id=%s AND e.id=ANY(%s) ORDER BY e.id""", (self.tenant_id, entry_ids)))
        lines = rows("finance_entry_lines", "entry_id=ANY(%s) ORDER BY entry_id,line_number", (entry_ids,))
        line_ids = [row["id"] for row in lines]
        pins = rows("pb_account_pins", "invoice_id=%s ORDER BY role", (source["id"],))
        projects = rows("hc_projects", "id=ANY(%s) ORDER BY id", (list(v["calculation"]["project_minor"]),))
        claims = rows("pb_claim_events", "time_id=ANY(%s) ORDER BY time_id,sequence", (v["calculation"]["time_ids"],))
        effects = rows("finance_posting_effects", "entry_id=ANY(%s) ORDER BY id", (entry_ids,))
        prices = rows("pb_prices", "id=ANY(%s) ORDER BY id", (v["calculation"]["price_ids"],))
        audit_ids: set[str] = set()
        outbox_ids: set[str] = set()
        for row in [*plans, *prices, *claims]:
            for key, value in row.items():
                if value and (key == "audit_id" or key.endswith("_audit_id")):
                    audit_ids.add(value)
                if value and (key == "outbox_id" or key.endswith("_outbox_id")):
                    outbox_ids.add(value)
        audit_ids.update(row["audit_event_id"] for row in effects)
        outbox_ids.update(row["outbox_event_id"] for row in effects)
        return {
            "plans": plans, "prices": prices, "entries": entries, "effects": effects, "entry_lines": lines,
            "entry_dimensions": rows("finance_entry_line_dimensions", "entry_line_id=ANY(%s) ORDER BY entry_line_id,dimension_id", (line_ids,)),
            "account_pins": pins, "accounts": rows("finance_accounts", "id=ANY(%s) ORDER BY id", ([row["account_id"] for row in pins],)),
            "projects": projects,
            "customers": records(self.connection.execute("""SELECT tenant_id,id,workspace_id,organization_id,legal_entity_id,
                customer_code,currency_code,status FROM reconforge.ar_customers WHERE tenant_id=%s AND id=%s""", (self.tenant_id, v["customer_id"]))),
            "organizations": rows("organizations", "id=%s", (source["organization_id"],)),
            "entities": rows("legal_entities", "id=%s", (source["legal_entity_id"],)),
            "journals": rows("finance_journals", "id=ANY(%s) ORDER BY id", ([row["journal_id"] for row in entries],)),
            "periods": rows("fiscal_periods", "id=ANY(%s) ORDER BY id", ([row["period_id"] for row in entries],)),
            "dimensions": rows("finance_dimensions", "id=ANY(%s) ORDER BY id", ([row["dimension_id"] for row in projects],)),
            "dimension_values": rows("finance_dimension_values", "id=ANY(%s) ORDER BY id", ([row["value_id"] for row in projects],)),
            "times": rows("hc_times", "id=ANY(%s) ORDER BY id", (v["calculation"]["time_ids"],)),
            "time_claims": rows("pb_time_claims", "time_id=ANY(%s) ORDER BY time_id,invoice_id", (v["calculation"]["time_ids"],)),
            "claim_events": claims, "claim_heads": rows("pb_claim_heads", "time_id=ANY(%s) ORDER BY time_id", (v["calculation"]["time_ids"],)),
            "ar_invoices": rows("ar_invoices", "id=%s", (source["ar_invoice_id"],)),
            "ar_lines": records(self.connection.execute("""SELECT tenant_id,id,invoice_id,line_number,description,quantity::TEXT AS quantity,
                quantity_text,unit_price_minor,tax_minor,line_total_minor,created_at FROM reconforge.ar_invoice_lines
                WHERE tenant_id=%s AND invoice_id=%s ORDER BY line_number""", (self.tenant_id, source["ar_invoice_id"]))),
            "ar_receipts": rows("ar_receipts", "id=ANY(%s) ORDER BY id", (receipt_ids,)),
            "ar_allocations": rows("ar_receipt_allocations", "invoice_id=%s ORDER BY receipt_id", (source["ar_invoice_id"],)),
            "commands": rows("pb_commands", "response_json->>'id'=ANY(%s) ORDER BY command_id", ([row["id"] for row in [*plans, *prices]],)),
            "audits": rows("domain_audit_events", "id=ANY(%s) ORDER BY id", (sorted(audit_ids),)),
            "outbox": rows("outbox_events", "event_id=ANY(%s) ORDER BY event_id", (sorted(outbox_ids),)),
        }

    def evidence(self, invoice_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            preview = self._row(invoice_id)
            self._authorize(actor, "read", preview, mutation=False)
            source = self._row(invoice_id, share=True)
            self._financial_read(actor, source)
            self.connection.execute("SELECT reconforge.pb_close(%s,%s)", (self.tenant_id, invoice_id))
            plans = [source, *records(self.connection.execute("SELECT * FROM reconforge.pb_plans WHERE tenant_id=%s AND parent_id=%s ORDER BY id FOR SHARE", (self.tenant_id, invoice_id)))]
            for collection in plans[1:]:
                self._financial_read(actor, collection)
            return {"schema_version": "project-billing-evidence-v1", "invoice": self._view(source),
                "qualified_scope": {"tenant_id": self.tenant_id, **{key: source[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}},
                "registry_snapshot": records(self.connection.execute("SELECT snapshot_json FROM reconforge.currency_registry_snapshots WHERE tenant_id=%s AND registry_digest=%s",
                    (self.tenant_id, source["payload"]["monetary_policy"]["currency_registry_digest"])))[0]["snapshot_json"],
                "original_rows": self._original_rows(source, plans),
                "observed_native_balances": {row["account_code"]: str(int(row["balance"])) for row in records(self.connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor) AS balance
                    FROM reconforge.finance_entry_lines l JOIN reconforge.finance_posting_effects e ON e.tenant_id=l.tenant_id AND e.entry_id=l.entry_id
                    JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
                    WHERE l.tenant_id=%s AND l.entry_id=ANY(%s) GROUP BY a.account_code""", (self.tenant_id, [row["entry_id"] for row in plans])))},
                "collections": [self._view(row) for row in plans[1:]], "ar_invoice": self.ar.get_invoice(source["ar_invoice_id"]),
                "native_effects": [self.owner.posting.get_effect(row["effect_id"], actor=actor) for row in plans if row["effect_id"]],
                "claims": records(self.connection.execute("SELECT * FROM reconforge.pb_claim_events WHERE tenant_id=%s AND invoice_id=%s ORDER BY time_id,sequence", (self.tenant_id, invoice_id))),
                "times": records(self.connection.execute("SELECT * FROM reconforge.hc_times WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id", (self.tenant_id, source["payload"]["calculation"]["time_ids"]))),
                "prices": records(self.connection.execute("SELECT * FROM reconforge.pb_prices WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id", (self.tenant_id, source["payload"]["calculation"]["price_ids"]))),
                "limitations": ["Functional currency time billing; no country tax pack.", "Recorded cash GL; no external bank transfer."]}

    def catalog(self, scope: PeopleScope, *, after: str = "", limit: int = 25, actor: PostingActor) -> dict[str, Any]:
        integer(limit, "Page size", minimum=1, maximum=100)
        with self.owner._transaction():
            self._authorize(actor, "read", asdict(scope), mutation=False)
            plans = records(self.connection.execute("SELECT * FROM reconforge.pb_plans WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND id>%s ORDER BY id LIMIT %s FOR SHARE",
                (self.tenant_id, scope.workspace_id, scope.organization_id, scope.legal_entity_id, after, limit + 1)))
            prices = records(self.connection.execute("SELECT * FROM reconforge.pb_prices WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND id>%s ORDER BY id LIMIT %s FOR SHARE",
                (self.tenant_id, scope.workspace_id, scope.organization_id, scope.legal_entity_id, after, limit + 1)))
            for source in plans[:limit]:
                self._financial_read(actor, source)
            for source in prices[:limit]:
                self._financial_read(actor, source)
            return {"items": [self._view(row) for row in plans[:limit]], "prices": [self._view(row, price=True) for row in prices[:limit]],
                "has_more": len(plans) > limit, "after": plans[limit-1]["id"] if len(plans) > limit else ""}
