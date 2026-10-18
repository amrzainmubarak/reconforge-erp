"""Native workforce ownership on the existing finance and budget engines."""
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from reconforge.domain.budget_control import BudgetScope, CommitmentAction
from reconforge.domain.finance_posting import PostingActor, canonical_json, text, validation_digest
from reconforge.domain.operational_finance import exact_minor_text
from reconforge.domain.people_project_payroll import (
    EmployeeRegistration,
    EmploymentAgreement,
    PeopleScope,
    TimeSubmission,
    earnings,
    fail,
    integer,
    settlement,
    source_digest,
)
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.platform.common import current_server_principal


def _table_sql(template: str, table: str, *, lock: bool = False, columns: str = "*") -> Any:
    """Quote closed owner identifiers separately from all bound record values."""
    from psycopg import sql

    selected = sql.SQL("*") if columns == "*" else sql.SQL(",").join(sql.Identifier(name) for name in columns.split(","))
    return sql.SQL(template).format(table=sql.Identifier(table), columns=selected,
                                    lock=sql.SQL(" FOR UPDATE" if lock else ""))


class _PeoplePayrollPostingParticipant:
    def __init__(self, owner: "PostgresPeopleProjectPayrollRepository", entry_id: str) -> None:
        self.owner, self.entry_id = owner, entry_id

    def admits(self, connection: Any, tenant_id: str, entry_id: str) -> bool:
        return (self.owner._participant is self and self.owner.connection is connection
                and self.owner.tenant_id == tenant_id and self.entry_id == entry_id)


class PostgresPeopleProjectPayrollRepository:
    def __init__(self, connection: Any, tenant_id: str, *, require_live_session_assurance: bool = False) -> None:
        self.connection, self.tenant_id = connection, tenant_id
        self.owner = PostgresOperationalFinanceRepository(connection, tenant_id)
        self.budgets = PostgresBudgetControlRepository(connection, tenant_id,
            require_live_session_assurance=require_live_session_assurance)
        self._participant: _PeoplePayrollPostingParticipant | None = None

    def _scope(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value[key] for key in ("workspace_id", "organization_id", "legal_entity_id")}

    def _authorize(self, actor: PostingActor, action: str, scope: Mapping[str, Any], *, mutation: bool = True) -> None:
        permission = "people_project_payroll." + action
        self.owner._actor(actor, permission, scope, mutation=mutation)
        if action in {"personnel", "read_sensitive"}:
            self.owner._actor(actor, "people_project_payroll.read_sensitive", scope, mutation=False)
            self.connection.execute("SELECT set_config('app.personnel_actor_id',%s,true)", (actor.user_id,))
        # Read requests also recheck and lock the persisted hierarchy grants;
        # a previously authenticated principal is not a revocation lease.
        try:
            self.connection.execute("SELECT reconforge.hc_actor(%s,%s,%s,%s,%s,%s)",
                (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], actor.user_id, permission))
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23514":
                fail("Current persisted workforce permission and hierarchy grants are required.", "people_permission_denied")
            raise
        principal = current_server_principal()
        if principal is None:
            fail("Current authenticated principal is required.", "people_permission_denied")

    def _command(self, scope: Mapping[str, Any], action: str, command_id: str, actor: PostingActor,
                 request: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        command_id = text(command_id, "Command ID", maximum=140)
        digest = source_digest({"operation": action, "request": dict(request)})
        self.connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (canonical_json([self.tenant_id, scope["workspace_id"], "people-project-payroll", command_id]),))
        rows = records(self.connection.execute("SELECT * FROM reconforge.hc_commands WHERE tenant_id=%s AND workspace_id=%s AND command_id=%s",
            (self.tenant_id, scope["workspace_id"], command_id)))
        if rows:
            prior = rows[0]
            if prior["actor_id"] != actor.user_id or prior["operation"] != action or prior["request_digest"] != digest:
                fail("Command ID already belongs to a different actor or exact request.", "people_command_conflict")
            return digest, dict(prior["response_json"])
        return digest, None

    def _remember(self, scope: Mapping[str, Any], action: str, command_id: str, actor: PostingActor,
                  request: Mapping[str, Any], digest: str, result: dict[str, Any]) -> dict[str, Any]:
        self.connection.execute("""INSERT INTO reconforge.hc_commands
            (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,operation,actor_id,request_digest,request_json,response_json)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
            (self.tenant_id, scope["workspace_id"], scope["organization_id"], scope["legal_entity_id"], command_id,
             action, actor.user_id, digest, canonical_json(dict(request)), canonical_json(result)))
        return result

    def _row(self, table: str, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        if table not in {"hc_employees", "hc_projects", "hc_times", "hc_payruns", "hc_payments"}:
            fail("Unsupported workforce source.")
        # Both the table and lock clause are closed owner literals; identifiers bind.
        rows = records(self.connection.execute(_table_sql("SELECT * FROM reconforge.{table} WHERE tenant_id=%s AND id=%s{lock}", table, lock=lock),
            (self.tenant_id, text(identifier, "Source ID"))))
        if not rows:
            fail("Source is absent or outside current scope.", "people_source_not_found")
        return rows[0]

    def _event(self, source: Mapping[str, Any], action: str, actor: PostingActor, digest: str) -> tuple[str, str]:
        return self.owner._event(source, "people_" + action, actor, {"source_digest": digest})

    def register_employee(self, request: EmployeeRegistration, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        payload = {**asdict(request.scope), "employee_code": request.employee_code, "display_name": request.display_name,
                   "linked_user_id": request.linked_user_id}
        with self.owner._transaction():
            self._authorize(actor, "personnel", payload)
            digest, replay = self._command(payload, "personnel", command_id, actor, payload)
            if replay is not None:
                return replay
            identifier = "HCE-" + uuid4().hex
            audit, outbox = self._event({"id": identifier, **payload}, "employee_registered", actor, digest)
            self.connection.execute("""INSERT INTO reconforge.hc_employees
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,employee_code,linked_user_id,preparer_id,audit_id,outbox_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, identifier, payload["workspace_id"], payload["organization_id"], payload["legal_entity_id"],
                 request.employee_code, request.linked_user_id, actor.user_id, audit, outbox))
            self.connection.execute("""INSERT INTO reconforge.hc_employee_private
                (tenant_id,employee_id,workspace_id,organization_id,legal_entity_id,display_name)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, identifier, payload["workspace_id"], payload["organization_id"], payload["legal_entity_id"], request.display_name))
            return self._remember(payload, "personnel", command_id, actor, payload, digest, {"id": identifier, **payload})

    def employ(self, request: EmploymentAgreement, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            employee = self._row("hc_employees", request.employee_id, lock=True)
            self._authorize(actor, "personnel", employee)
            args = asdict(request)
            digest, replay = self._command(employee, "personnel", command_id, actor, args)
            if replay is not None:
                return replay
            currency = records(self.connection.execute("""SELECT c.minor_units FROM reconforge.currencies c
                JOIN reconforge.legal_entities e ON e.tenant_id=c.tenant_id AND e.currency_code=c.code
                WHERE c.tenant_id=%s AND e.id=%s AND c.code=%s AND c.active AND e.active FOR SHARE OF c,e""",
                (self.tenant_id, employee["legal_entity_id"], request.currency_code)))
            if len(currency) != 1:
                fail("Employment currency must be the entity's active native functional currency.")
            policy, _ = FinancePolicyStore(self.connection, tenant_id=self.tenant_id).capture(
                workspace_id=employee["workspace_id"], currency_code=request.currency_code,
                minor_units=currency[0]["minor_units"], actor_label=actor.username)
            identifier = "HCA-" + uuid4().hex
            audit, outbox = self._event({**employee, "id": identifier}, "employment_registered", actor, digest)
            self.connection.execute("""INSERT INTO reconforge.hc_employments
                (tenant_id,id,employee_id,workspace_id,organization_id,legal_entity_id,valid_from,valid_through,
                 currency_code,currency_precision,currency_rounding_policy,currency_registry_version,currency_registry_digest,preparer_id,request_digest,audit_id,outbox_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, identifier, request.employee_id, employee["workspace_id"], employee["organization_id"], employee["legal_entity_id"],
                 request.valid_from, request.valid_through, request.currency_code, policy.precision,
                 policy.rounding_policy, policy.registry_version, policy.registry_digest, actor.user_id, digest, audit, outbox))
            self.connection.execute("""INSERT INTO reconforge.hc_rates
                (tenant_id,employment_id,workspace_id,organization_id,legal_entity_id,hourly_rate_minor)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, identifier, employee["workspace_id"], employee["organization_id"], employee["legal_entity_id"], request.hourly_rate_minor))
            return self._remember(employee, "personnel", command_id, actor, args, digest,
                {"id": identifier, **args, "currency_policy": policy.metadata()})

    def register_project(self, scope: PeopleScope, *, project_code: str, dimension_code: str, value_code: str,
                         command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {**asdict(scope), "project_code": text(project_code, "Project code"),
                   "dimension_code": text(dimension_code, "Project dimension"), "value_code": text(value_code, "Project value")}
        with self.owner._transaction():
            self._authorize(actor, "manage", request)
            digest, replay = self._command(request, "manage", command_id, actor, request)
            if replay is not None:
                return replay
            rows = records(self.connection.execute("""SELECT d.id AS dimension_id,v.id AS value_id
                FROM reconforge.finance_dimensions d JOIN reconforge.finance_dimension_values v ON v.tenant_id=d.tenant_id AND v.dimension_id=d.id
                WHERE d.tenant_id=%s AND d.workspace_id=%s AND d.dimension_code=%s AND v.value_code=%s AND d.active AND v.active AND d.dimension_type='Project'""",
                (self.tenant_id, scope.workspace_id, dimension_code, value_code)))
            if len(rows) != 1:
                fail("Project requires its original active native Project dimension/value.")
            identifier = "HCP-" + uuid4().hex
            audit, outbox = self._event({**request, "id": identifier}, "project_registered", actor, digest)
            self.connection.execute("""INSERT INTO reconforge.hc_projects
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,project_code,dimension_id,value_id,dimension_code,value_code,preparer_id,request_digest,audit_id,outbox_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self.tenant_id, identifier, scope.workspace_id, scope.organization_id, scope.legal_entity_id,
                 project_code, rows[0]["dimension_id"], rows[0]["value_id"], dimension_code, value_code, actor.user_id, digest, audit, outbox))
            return self._remember(request, "manage", command_id, actor, request, digest, {"id": identifier, **request})

    def submit_time(self, request: TimeSubmission, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            employee = self._row("hc_employees", request.employee_id, lock=True)
            self._authorize(actor, "manage", employee)
            args = {"employee_id": request.employee_id, "business_date": request.business_date,
                    "lines": [asdict(line) for line in request.lines], "reason": request.reason}
            digest, replay = self._command(employee, "manage", command_id, actor, args)
            if replay is not None:
                return replay
            employment = records(self.connection.execute("""SELECT id FROM reconforge.hc_employments WHERE tenant_id=%s AND employee_id=%s
                AND valid_from<=%s::date AND valid_through>=%s::date FOR SHARE""",
                (self.tenant_id, request.employee_id, request.business_date, request.business_date)))
            if len(employment) != 1:
                fail("Time requires exactly one original employment effective on its business date.")
            identifier = "HCT-" + uuid4().hex
            sealed = source_digest({**args, "employment_id": employment[0]["id"]})
            audit, outbox = self._event({**employee, "id": identifier}, "time_submitted", actor, digest)
            self.connection.execute("""INSERT INTO reconforge.hc_times
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,employee_id,employment_id,business_date,lines,source_digest,submitter_id,request_json,submit_audit_id,submit_outbox_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s,%s)""",
                (self.tenant_id, identifier, employee["workspace_id"], employee["organization_id"], employee["legal_entity_id"],
                 request.employee_id, employment[0]["id"], request.business_date, canonical_json(args["lines"]), sealed, actor.user_id, canonical_json(args), audit, outbox))
            return self._remember(employee, "manage", command_id, actor, args, digest,
                {"id": identifier, **args, "status": "Submitted", "source_digest": sealed})

    def approve_time(self, time_id: str, *, expected_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._row("hc_times", time_id, lock=True)
            self._authorize(actor, "approve_time", source)
            request = {"time_id": time_id, "expected_digest": expected_digest}
            digest, replay = self._command(source, "approve_time", command_id, actor, request)
            if replay is not None:
                return replay
            employee = self._row("hc_employees", source["employee_id"])
            if source["source_digest"] != expected_digest or source["approver_id"] is not None or actor.user_id in {source["submitter_id"], employee["linked_user_id"]}:
                fail("Time approval requires an independent human and the exact retained source digest.")
            audit, outbox = self._event(source, "time_approved", actor, digest)
            self.connection.execute("UPDATE reconforge.hc_times SET approver_id=%s,audit_id=%s,outbox_id=%s WHERE tenant_id=%s AND id=%s",
                (actor.user_id, audit, outbox, self.tenant_id, time_id))
            return self._remember(source, "approve_time", command_id, actor, request, digest,
                {"id": time_id, "source_digest": expected_digest, "status": "Approved", "approver_id": actor.user_id})

    def _financial(self, source: Mapping[str, Any], action: str, actor: PostingActor) -> None:
        self._authorize(actor, action, source)
        self._authorize(actor, "read_sensitive", source, mutation=False)
        permission = {"prepare": "finance_core.manage", "review": "finance_core.validate", "post": "finance_core.post", "pay": "finance_core.manage"}[action]
        self.owner._actor(actor, permission, source)

    def _plan(self, plan_id: str, *, lock: bool = False) -> tuple[str, dict[str, Any]]:
        table = "hc_payments" if plan_id.startswith("HC1P-") else "hc_payruns" if plan_id.startswith("HC1-") else ""
        if not table:
            fail("Unknown workforce financial source.", "people_source_not_found")
        return table, self._row(table, plan_id, lock=lock)

    def _private(self, table: str, identifier: str) -> dict[str, Any]:
        if table not in {"hc_payrun_private", "hc_payment_private"}:
            fail("Unknown private workforce source.")
        rows = records(self.connection.execute(_table_sql("SELECT payload FROM reconforge.{table} WHERE tenant_id=%s AND plan_id=%s", table),
            (self.tenant_id, identifier)))
        if len(rows) != 1:
            fail("Private workforce source is unavailable under current authority.", "people_permission_denied")
        return dict(rows[0]["payload"])

    def _view(self, table: str, source: Mapping[str, Any], *, sensitive: bool = False, actor: PostingActor | None = None) -> dict[str, Any]:
        result = {**dict(source["payload"]), "phase": source["phase"],
            "status": {0: "Prepared", 1: "Reviewed", 2: "Posted", 3: "Cancelled"}[source["phase"]],
            "reviewer_id": source["reviewer_id"], "posted_actor_id": source["poster_id"], "posting_effect_id": source["effect_id"]}
        if sensitive:
            result["private"] = self._private("hc_payment_private" if table == "hc_payments" else "hc_payrun_private", source["id"])
            if actor is not None:
                result["native_effect"] = self.owner.posting.get_effect(source["effect_id"], actor=actor) if source["effect_id"] else None
        return result

    def _budget_lock(self, source: Mapping[str, Any]) -> dict[str, Any]:
        self.connection.execute("SELECT id FROM reconforge.budget_envelopes WHERE tenant_id=%s AND id=%s FOR UPDATE",
            (self.tenant_id, source["budget_id"]))
        return self.budgets.get(BudgetScope(**self._scope(source)), source["budget_id"])

    def _locked(self, plan_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        table, initial = self._plan(plan_id)
        payrun = initial if table == "hc_payruns" else self._row("hc_payruns", initial["payrun_id"])
        FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(initial["workspace_id"])
        self._budget_lock(payrun)
        ids = payrun["payload"]["time_entry_ids"]
        self.connection.execute("SELECT id FROM reconforge.hc_times WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id FOR UPDATE",
            (self.tenant_id, ids)).fetchall()
        payrun = self._row("hc_payruns", payrun["id"], lock=True)
        return table, payrun if table == "hc_payruns" else self._row(table, plan_id, lock=True), payrun

    def prepare_payrun(self, scope: PeopleScope, *, time_ids: list[str], budget_id: str, expected_budget_version: int,
                       period_id: str, posting_date: str, journal_code: str, expense_account_code: str,
                       liability_account_code: str, cash_account_code: str, command_id: str,
                       actor: PostingActor) -> dict[str, Any]:
        if not 1 <= len(time_ids) <= 1000 or len(set(time_ids)) != len(time_ids):
            fail("Select bounded distinct whole approved time entries.")
        if len({expense_account_code, liability_account_code, cash_account_code}) != 3:
            fail("Wage expense, payroll payable and cash accounts must be distinct.")
        request = {**asdict(scope), "time_ids": sorted(time_ids), "budget_id": budget_id, "expected_budget_version": expected_budget_version,
            "period_id": period_id, "posting_date": posting_date, "journal_code": journal_code,
            "expense_account_code": expense_account_code, "liability_account_code": liability_account_code, "cash_account_code": cash_account_code}
        with self.owner._transaction():
            FinancePolicyStore(self.connection, tenant_id=self.tenant_id).lock_binding(scope.workspace_id)
            self._financial(request, "prepare", actor)
            digest, replay = self._command(request, "prepare", command_id, actor, request)
            if replay is not None:
                return replay
            budget = self._budget_lock(request)
            rows = records(self.connection.execute("""SELECT t.*,r.hourly_rate_minor FROM reconforge.hc_times t
                JOIN reconforge.hc_rates r ON r.tenant_id=t.tenant_id AND r.employment_id=t.employment_id
                WHERE t.tenant_id=%s AND t.id=ANY(%s) ORDER BY t.id FOR UPDATE OF t""", (self.tenant_id, sorted(time_ids))))
            if len(rows) != len(time_ids) or any(self._scope(row) != self._scope(request) for row in rows):
                fail("Approved source set must exactly match the payrun scope.")
            for row in rows:
                row["business_date"] = row["business_date"].isoformat()
                row["status"] = "Approved" if row["approver_id"] else "Submitted"
                occupied = self.connection.execute("SELECT state FROM reconforge.hc_claim_heads WHERE tenant_id=%s AND time_id=%s FOR UPDATE",
                    (self.tenant_id, row["id"])).fetchone()
                if occupied is not None and occupied["state"] != "Released":
                    fail("Approved time already has an active or consumed payrun claim.", "people_time_claim_conflict")
            calculated = earnings(rows)
            self._financial({**request, "amount_minor": calculated["gross_minor"], "currency_precision": budget["monetary_policy"]["precision"]}, "prepare", actor)
            identifier = "HC1-" + uuid4().hex
            projects = {row["id"]: row for row in records(self.connection.execute(
                "SELECT * FROM reconforge.hc_projects WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id FOR SHARE",
                (self.tenant_id, list(calculated["project_minor"]))))}
            if len(projects) != len(calculated["project_minor"]):
                fail("Original project dimensions are unavailable.")
            precision = budget["monetary_policy"]["precision"]
            lines: list[dict[str, Any]] = [{"account_code": expense_account_code, "debit": exact_minor_text(amount, precision), "credit": "0",
                "description": "Approved project labor", "dimensions": {projects[project]["dimension_code"]: projects[project]["value_code"]}}
                for project, amount in calculated["project_minor"].items() if amount]
            lines.append({"account_code": liability_account_code, "debit": "0", "credit": exact_minor_text(calculated["gross_minor"], precision), "description": "Aggregate workforce liability"})
            entry = self.owner.finance.create_entry(entry_number=identifier, organization_code=scope.organization_code, entity_code=scope.entity_code,
                period_id=period_id, journal_code=journal_code, posting_date=posting_date, description="Nonstatutory approved workforce accrual",
                workspace=scope.workspace_id, lines=lines, external_reference=identifier, actor_label=actor.username)
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
            monetary = {key: snapshot["entry"][key] for key in ("currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest")}
            if budget["currency_code"] != monetary["currency_code"] or budget["period_id"] != period_id:
                fail("Budget and payroll must share original functional currency and fiscal period.")
            reserved = self.budgets.record(BudgetScope(**self._scope(request)), budget_id,
                CommitmentAction("Reserve", calculated["gross_minor"], posting_date, identifier, "Approved workforce cost reservation"),
                expected_version=expected_budget_version, command_id="HC1:" + command_id)
            payload = {"schema_version": "people-payrun-v1", "id": identifier, **asdict(scope), "entry_id": entry["id"],
                "budget_id": budget_id, "commitment_id": reserved["commitment_id"], "time_entry_ids": sorted(time_ids), "project_minor": calculated["project_minor"],
                "amount_minor": calculated["gross_minor"], "period_id": period_id, "posting_date": posting_date, "journal_code": journal_code,
                "expense_account_code": expense_account_code, "liability_account_code": liability_account_code, "cash_account_code": cash_account_code,
                "monetary_policy": monetary, "currency_precision": monetary["currency_precision"], "earnings_rounding": "HALF_EVEN",
                "validation_digest": validation_digest(snapshot), "preparer_id": actor.user_id, "command_request": request}
            payload["plan_digest"] = source_digest({**payload, "private": calculated})
            audit, outbox = self._event(payload, "payrun_prepared", actor, payload["plan_digest"])
            self.connection.execute("""INSERT INTO reconforge.hc_payruns
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,entry_id,budget_id,commitment_id,amount_minor,phase,payload,preparer_id,audit_id,outbox_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s,%s)""",
                (self.tenant_id, identifier, scope.workspace_id, scope.organization_id, scope.legal_entity_id, entry["id"], budget_id,
                 reserved["commitment_id"], calculated["gross_minor"], canonical_json(payload), actor.user_id, audit, outbox))
            self.connection.execute("INSERT INTO reconforge.hc_payrun_private(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id,payload) VALUES(%s,%s,%s,%s,%s,%s::jsonb)",
                (self.tenant_id, identifier, scope.workspace_id, scope.organization_id, scope.legal_entity_id, canonical_json(calculated)))
            for row in rows:
                self.connection.execute("SELECT reconforge.hc_claim(%s,%s,%s,%s,%s)",
                    (self.tenant_id, row["id"], identifier, "Claim", actor.user_id))
            result = self._view("hc_payruns", self._row("hc_payruns", identifier))
            return self._remember(request, "prepare", command_id, actor, request, digest, result)

    def prepare_payment(self, payrun_id: str, *, employees_minor: dict[str, int], period_id: str,
                        posting_date: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"payrun_id": payrun_id, "employees_minor": employees_minor, "period_id": period_id, "posting_date": posting_date}
        with self.owner._transaction():
            _, source, _ = self._locked(payrun_id)
            self._financial(source["payload"], "pay", actor)
            digest, replay = self._command(source, "pay", command_id, actor, request)
            if replay is not None:
                return replay
            if source["phase"] != 2:
                fail("Cash settlement requires an original posted wage accrual.")
            if self.connection.execute("SELECT 1 FROM reconforge.hc_payments WHERE tenant_id=%s AND payrun_id=%s AND phase<2",
                (self.tenant_id, payrun_id)).fetchone() is not None:
                fail("Complete the currently prepared settlement first.", "people_payment_conflict")
            paid: dict[str, int] = {}
            for row in records(self.connection.execute("""SELECT private.payload FROM reconforge.hc_payments p JOIN reconforge.hc_payment_private private
                ON private.tenant_id=p.tenant_id AND private.plan_id=p.id WHERE p.tenant_id=%s AND p.payrun_id=%s AND p.phase=2""", (self.tenant_id, payrun_id))):
                for employee, amount in row["payload"]["employees_minor"].items():
                    paid[employee] = paid.get(employee, 0) + integer(amount, "Settled employee amount")
            allocation = settlement(self._private("hc_payrun_private", payrun_id), paid, employees_minor)
            identifier = "HC1P-" + uuid4().hex
            v = source["payload"]
            entry = self.owner.finance.create_entry(entry_number=identifier, organization_code=v["organization_code"], entity_code=v["entity_code"],
                period_id=period_id, journal_code=v["journal_code"], posting_date=posting_date, description="Nonstatutory workforce liability settlement",
                workspace=v["workspace_id"], lines=[
                    {"account_code": v["liability_account_code"], "debit": exact_minor_text(allocation["amount_minor"], v["currency_precision"]), "credit": "0"},
                    {"account_code": v["cash_account_code"], "debit": "0", "credit": exact_minor_text(allocation["amount_minor"], v["currency_precision"])}],
                external_reference=identifier, actor_label=actor.username)
            snapshot = posting_snapshot(self.connection, self.tenant_id, posting_entry(self.connection, self.tenant_id, entry["id"]))
            if any(snapshot["entry"][key] != value for key, value in v["monetary_policy"].items()):
                fail("Settlement requires the original captured monetary policy; no historical reinterpretation.")
            payload = {"schema_version": "people-payment-v1", "id": identifier, **self._scope(v), "payrun_id": payrun_id,
                "entry_id": entry["id"], "amount_minor": allocation["amount_minor"], "period_id": period_id,
                "posting_date": posting_date, "monetary_policy": v["monetary_policy"], "currency_precision": v["currency_precision"],
                "validation_digest": validation_digest(snapshot), "preparer_id": actor.user_id, "command_request_digest": digest}
            payload["plan_digest"] = source_digest({**payload, "private": allocation})
            audit, outbox = self._event(payload, "payment_prepared", actor, payload["plan_digest"])
            self.connection.execute("""INSERT INTO reconforge.hc_payments
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,payrun_id,entry_id,amount_minor,phase,payload,preparer_id,audit_id,outbox_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,0,%s::jsonb,%s,%s,%s)""",
                (self.tenant_id, identifier, v["workspace_id"], v["organization_id"], v["legal_entity_id"], payrun_id,
                 entry["id"], allocation["amount_minor"], canonical_json(payload), actor.user_id, audit, outbox))
            self.connection.execute("INSERT INTO reconforge.hc_payment_private(tenant_id,plan_id,workspace_id,organization_id,legal_entity_id,payload) VALUES(%s,%s,%s,%s,%s,%s::jsonb)",
                (self.tenant_id, identifier, v["workspace_id"], v["organization_id"], v["legal_entity_id"], canonical_json(allocation)))
            return self._remember(source, "pay", command_id, actor, request, digest, self._view("hc_payments", self._row("hc_payments", identifier)))

    def review(self, plan_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest}
        with self.owner._transaction():
            table, source, _ = self._locked(plan_id)
            self._financial(source["payload"], "review", actor)
            digest, replay = self._command(source, "review", command_id, actor, request)
            if replay is not None:
                return replay
            if source["phase"] != 0 or source["payload"]["plan_digest"] != expected_plan_digest or source["preparer_id"] == actor.user_id:
                fail("Independent review requires the current prepared source.", "people_review_denied")
            self.owner.finance.validate_entry(source["entry_id"], reason="Independent workforce source review", actor_label=actor.username)
            audit, outbox = self._event(source, "plan_reviewed", actor, expected_plan_digest)
            self.connection.execute(_table_sql("UPDATE reconforge.{table} SET phase=1,reviewer_id=%s,review_audit_id=%s,review_outbox_id=%s WHERE tenant_id=%s AND id=%s", table),
                (actor.user_id, audit, outbox, self.tenant_id, plan_id))
            return self._remember(source, "review", command_id, actor, request, digest, self._view(table, self._row(table, plan_id)))

    def post(self, plan_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"plan_id": plan_id, "expected_plan_digest": expected_plan_digest}
        with self.owner._transaction():
            table, source, payrun = self._locked(plan_id)
            self._financial(source["payload"], "post", actor)
            digest, replay = self._command(source, "post", command_id, actor, request)
            if replay is not None:
                return replay
            if source["phase"] != 1 or source["payload"]["plan_digest"] != expected_plan_digest or actor.user_id in {source["preparer_id"], source["reviewer_id"]}:
                fail("A third distinct authorized human must post the reviewed source.", "people_post_denied")
            if table == "hc_payruns":
                budget = self._budget_lock(source)
                self.budgets.record(BudgetScope(**self._scope(source)), source["budget_id"],
                    CommitmentAction("Consume", source["amount_minor"], source["payload"]["posting_date"], plan_id, "Approved workforce accrual consumption"),
                    expected_version=budget["row_version"], command_id="HC1-C:" + command_id, commitment_id=source["commitment_id"])
            self._participant = _PeoplePayrollPostingParticipant(self, source["entry_id"])
            try:
                effect = self.owner.posting.post(source["entry_id"], command_id="HC1:" + command_id,
                    expected_validation_digest=source["payload"]["validation_digest"], reason="Source-owned nonstatutory workforce accounting",
                    actor=actor, _source_owner=self._participant)
            finally:
                self._participant = None
            audit, outbox = self._event(source, "plan_posted", actor, expected_plan_digest)
            self.connection.execute(_table_sql("UPDATE reconforge.{table} SET phase=2,poster_id=%s,effect_id=%s,post_audit_id=%s,post_outbox_id=%s WHERE tenant_id=%s AND id=%s", table),
                (actor.user_id, effect["id"], audit, outbox, self.tenant_id, plan_id))
            if table == "hc_payruns":
                for time_id in payrun["payload"]["time_entry_ids"]:
                    self.connection.execute("SELECT reconforge.hc_claim(%s,%s,%s,%s,%s)", (self.tenant_id, time_id, plan_id, "Consume", actor.user_id))
            return self._remember(source, "post", command_id, actor, request, digest, self._view(table, self._row(table, plan_id)))

    def cancel(self, payrun_id: str, *, expected_plan_digest: str, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request = {"payrun_id": payrun_id, "expected_plan_digest": expected_plan_digest}
        with self.owner._transaction():
            _, source, _ = self._locked(payrun_id)
            self._financial(source["payload"], "prepare", actor)
            digest, replay = self._command(source, "cancel", command_id, actor, request)
            if replay is not None:
                return replay
            if source["phase"] not in {0, 1} or source["payload"]["plan_digest"] != expected_plan_digest:
                fail("Only an unposted exact payrun can cancel; posted wages cannot be freely reused.")
            budget = self._budget_lock(source)
            self.budgets.record(BudgetScope(**self._scope(source)), source["budget_id"],
                CommitmentAction("Release", source["amount_minor"], source["payload"]["posting_date"], payrun_id, "Cancelled unposted workforce reservation"),
                expected_version=budget["row_version"], command_id="HC1-R:" + command_id, commitment_id=source["commitment_id"])
            audit, outbox = self._event(source, "payrun_cancelled", actor, expected_plan_digest)
            self.connection.execute("UPDATE reconforge.hc_payruns SET phase=3,canceller_id=%s,cancel_audit_id=%s,cancel_outbox_id=%s WHERE tenant_id=%s AND id=%s",
                (actor.user_id, audit, outbox, self.tenant_id, payrun_id))
            for time_id in source["payload"]["time_entry_ids"]:
                self.connection.execute("SELECT reconforge.hc_claim(%s,%s,%s,%s,%s)", (self.tenant_id, time_id, payrun_id, "Release", actor.user_id))
            return self._remember(source, "cancel", command_id, actor, request, digest, self._view("hc_payruns", self._row("hc_payruns", payrun_id)))

    def get(self, plan_id: str, *, actor: PostingActor, sensitive: bool = False) -> dict[str, Any]:
        with self.owner._transaction():
            table, source = self._plan(plan_id)
            self._authorize(actor, "read", source["payload"], mutation=False)
            if sensitive:
                self._authorize(actor, "read_sensitive", source["payload"], mutation=False)
                self.owner._actor(actor, "finance_core.read", source["payload"], mutation=False)
            return self._view(table, source, sensitive=sensitive, actor=actor)

    def evidence(self, payrun_id: str, *, actor: PostingActor) -> dict[str, Any]:
        with self.owner._transaction():
            source = self._row("hc_payruns", payrun_id)
            self._authorize(actor, "read_sensitive", source["payload"], mutation=False)
            self._authorize(actor, "read", source["payload"], mutation=False)
            self.owner._actor(actor, "finance_core.read", source["payload"], mutation=False)
            self.connection.execute("SELECT reconforge.hc_close(%s,%s)", (self.tenant_id, payrun_id))
            effects = []
            all_sources = [source, *records(self.connection.execute("SELECT * FROM reconforge.hc_payments WHERE tenant_id=%s AND payrun_id=%s ORDER BY id",
                (self.tenant_id, payrun_id)))]
            for plan in all_sources:
                if plan["effect_id"]:
                    effects.append(self.owner.posting.get_effect(plan["effect_id"], actor=actor))
            return {"schema_version": "people-payroll-evidence-v1", "payrun": self._view("hc_payruns", source, sensitive=True, actor=actor),
                "native_effects": effects, "times": records(self.connection.execute("""SELECT t.*,rate.hourly_rate_minor,e.currency_code,
                    e.currency_precision,e.currency_rounding_policy,e.currency_registry_version,e.currency_registry_digest
                    FROM reconforge.hc_times t JOIN reconforge.hc_employments e ON e.tenant_id=t.tenant_id AND e.id=t.employment_id
                    JOIN reconforge.hc_rates rate ON rate.tenant_id=e.tenant_id AND rate.employment_id=e.id
                    WHERE t.tenant_id=%s AND t.id=ANY(%s) ORDER BY t.id""", (self.tenant_id, source["payload"]["time_entry_ids"]))),
                "claims": records(self.connection.execute("SELECT * FROM reconforge.hc_claim_events WHERE tenant_id=%s AND payrun_id=%s ORDER BY time_id,sequence", (self.tenant_id, payrun_id))),
                "projects": records(self.connection.execute("SELECT id,dimension_id,value_id,dimension_code,value_code,workspace_id,organization_id,legal_entity_id FROM reconforge.hc_projects WHERE tenant_id=%s AND id=ANY(%s) ORDER BY id",
                    (self.tenant_id, list(source["payload"]["project_minor"])))),
                "accounts": records(self.connection.execute("SELECT id,account_code FROM reconforge.finance_accounts WHERE tenant_id=%s AND workspace_id=%s AND account_code=ANY(%s) ORDER BY account_code",
                    (self.tenant_id, source["workspace_id"], [source["payload"]["expense_account_code"], source["payload"]["liability_account_code"], source["payload"]["cash_account_code"]]))),
                "budget_events": records(self.connection.execute("SELECT * FROM reconforge.budget_commitment_events WHERE tenant_id=%s AND commitment_id=%s ORDER BY budget_version", (self.tenant_id, source["commitment_id"]))),
                "payments": [self._view("hc_payments", plan, sensitive=True, actor=actor) for plan in all_sources[1:]],
                "limitations": ["Nonstatutory management wage/time accounting; statutory countries supported: zero.", "Recorded cash GL settlement; no external bank payment."]}

    def catalog(self, kind: str, scope: PeopleScope, *, after: str = "", limit: int = 25, actor: PostingActor) -> dict[str, Any]:
        tables = {"employees": ("hc_employees", "id,employee_code,linked_user_id"),
            "employment": ("hc_employments", "id,employee_id,valid_from,valid_through,currency_code"),
            "projects": ("hc_projects", "id,project_code,dimension_code,value_code"),
            "times": ("hc_times", "id,employee_id,business_date,lines,source_digest,submitter_id,approver_id"),
            "payruns": ("hc_payruns", "id,phase,payload"), "payments": ("hc_payments", "id,phase,payload")}
        if kind not in tables or type(limit) is not int or not 1 <= limit <= 100:
            fail("Unsupported bounded workforce catalog.")
        table, columns = tables[kind]
        with self.owner._transaction():
            self._authorize(actor, "read", asdict(scope), mutation=False)
            rows = records(self.connection.execute(_table_sql("SELECT {columns} FROM reconforge.{table} WHERE tenant_id=%s AND workspace_id=%s AND organization_id=%s AND legal_entity_id=%s AND id>%s ORDER BY id LIMIT %s", table, columns=columns),
                (self.tenant_id, scope.workspace_id, scope.organization_id, scope.legal_entity_id, after, limit + 1)))
            if kind in {"payruns", "payments"}:
                for row in rows[:limit]:
                    self._authorize(actor, "read", row["payload"], mutation=False)
            return {"items": rows[:limit], "has_more": len(rows)>limit, "after": rows[limit-1]["id"] if len(rows)>limit else ""}

