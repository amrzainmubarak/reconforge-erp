"""Owned native development gate: original foundations plus HC1 source closure.

The focused development fixture installs the owned schema directly over the
accepted core. Ordered migration/restore acceptance is a separate gate.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest

from reconforge.domain.budget_control import BudgetControlError, BudgetDefinition, BudgetScope, CommitmentAction
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.people_project_payroll import (
    EmployeeRegistration,
    EmploymentAgreement,
    PeopleScope,
    TimeLine,
    TimeSubmission,
)
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_people_project_payroll import PostgresPeopleProjectPayrollRepository
from reconforge.infrastructure.postgres_people_project_payroll_schema import upgrade_people_project_payroll_schema
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import ServerPrincipal, server_principal_context
from tests.test_postgres_inventory_receipt_posting import (  # noqa: F401
    ReceiptRuntime,
    create_receipt_runtime,
    receipt_database,
)

SCOPE = PeopleScope("work", "org", "entity", "ORG", "ENTITY")
PERMISSIONS = frozenset({"people_project_payroll." + name for name in
    ("read", "read_sensitive", "personnel", "manage", "approve_time", "prepare", "review", "post", "pay")}) | frozenset({
    "finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post", "finance_core.reverse",
    "budget_control.read", "budget_control.manage", "budget_control.approve"})


@dataclass
class PeopleRuntime:
    base: ReceiptRuntime
    private: PostgresConnectionFactory

    @contextmanager
    def actor(self, name: str, *, private: bool = True) -> Iterator[tuple[Any, PostgresPeopleProjectPayrollRepository, PostingActor]]:
        with PostgresTenantBoundary(self.base.factory).transaction(self.base.tenant) as connection:
            identity = PostgresIdentityRepository(connection)
            user = identity.authenticate_user(tenant_id=self.base.tenant, username=name, password=self.base.password)
            assert user is not None
            permissions = identity.user_permissions(tenant_id=self.base.tenant, user_id=user.id)
        with PostgresTenantBoundary(self.private if private else self.base.factory).transaction(
            self.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity") as connection:
            principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True,
                authorized_tenant_ids=frozenset({self.base.tenant}), authorized_workspace_ids=frozenset({"work"}),
                authorized_organization_ids=frozenset({"org"}), authorized_legal_entity_ids=frozenset({"entity"}))
            with server_principal_context(principal):
                connection.execute("SELECT set_config('app.personnel_actor_id',%s,true)", (user.id,))
                yield connection, PostgresPeopleProjectPayrollRepository(connection, self.base.tenant), PostingActor(user.id, user.username, permissions, step_up_active=True)


@pytest.fixture(scope="module")
def personnel_database(receipt_database: tuple[str, str]) -> Iterator[tuple[str, str, str]]:  # noqa: F811
    import psycopg
    from psycopg import sql
    admin_dsn, ordinary_dsn = receipt_database
    login, password = "hc_personnel_" + uuid4().hex[:12], "Synthetic-HC-" + uuid4().hex
    with psycopg.connect(admin_dsn) as admin:
        if admin.execute("SELECT to_regclass('reconforge.hc_payruns')").fetchone()[0] is None:
            upgrade_people_project_payroll_schema(admin)
        # Integrated migration140 owns installation; the isolated early
        # development fixture installs only when absent, never replaces a head.
        expected_tables = ["hc_employees","hc_employee_private","hc_employments","hc_rates","hc_projects","hc_times","hc_payruns","hc_payrun_private","hc_payments","hc_payment_private","hc_time_claims","hc_claim_events","hc_claim_heads","hc_commands"]
        catalog = admin.execute("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND c.relname=ANY(%s)", (expected_tables,)).fetchall()
        assert len(catalog)==14 and all(row[1] is True and row[2] is True for row in catalog)
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB PASSWORD {}").format(sql.Identifier(login), sql.Literal(password)))
        admin.execute(sql.SQL("GRANT reconforge_personnel_runtime TO {}").format(sql.Identifier(login)))
        ordinary = psycopg.conninfo.conninfo_to_dict(ordinary_dsn)["user"]
        assert admin.execute("SELECT pg_has_role(%s,'reconforge_personnel_runtime','MEMBER')", (ordinary,)).fetchone()[0] is False
        for name in (login, ordinary):
            for command in ("GRANT USAGE ON SCHEMA reconforge TO {}", "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}", "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}"):
                admin.execute(sql.SQL(command).format(sql.Identifier(name)))
    private_dsn = psycopg.conninfo.make_conninfo(ordinary_dsn, user=login, password=password)
    try:
        yield admin_dsn, ordinary_dsn, private_dsn
    finally:
        with psycopg.connect(admin_dsn) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))


@pytest.fixture
def people(personnel_database: tuple[str, str, str]) -> PeopleRuntime:
    admin, app, private = personnel_database
    base = create_receipt_runtime((admin, app))
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in sorted(PERMISSIONS):
            identity.create_permission(tenant_id=base.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=base.tenant, role_name="receipt-operator", permission_name=permission)
        for name in ("maker", "checker", "poster"):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                PostgresScopeAuthorityRepository(connection).grant(tenant_id=base.tenant, grant_id="hc-"+name+kind,
                    principal_type="user", principal_id=name, scope_type=kind, scope_id=identifier, actor_id=name)
        finance = PostgresFinanceCoreRepository(connection, base.tenant)
        for code, kind in (("LABOR", "Expense"), ("WAGES", "Liability"), ("CASH", "Asset")):
            finance.upsert_account(account_code=code, name=code, account_type=kind, chart_code="DEFAULT", workspace="work")
        finance.upsert_dimension(dimension_code="PROJECT", name="Projects", dimension_type="Project", workspace="work", organization_code="ORG")
        for code in ("P1", "P2"):
            finance.upsert_dimension_value(dimension_code="PROJECT", value_code=code, name=code, workspace="work")
    return PeopleRuntime(base, PostgresConnectionFactory(PostgresSettings(dsn=private, require_tls=False)))


def approved_budget(runtime: PeopleRuntime) -> dict[str, Any]:
    scope = BudgetScope("work", "org", "entity")
    with runtime.actor("maker") as (connection, _, _):
        budget = PostgresBudgetControlRepository(connection, runtime.base.tenant)
        result = budget.create(scope, BudgetDefinition("WAGE", "Workforce", "period", "USD", 10000), command_id="b-create")
        result = budget.transition(scope, result["id"], action="submit", expected_version=result["row_version"], reason="Synthetic", command_id="b-submit")
    with runtime.actor("checker") as (connection, _, _):
        return PostgresBudgetControlRepository(connection, runtime.base.tenant).transition(scope, result["id"], action="approve", expected_version=result["row_version"], reason="Independent synthetic", command_id="b-approve")


def approved_time(runtime: PeopleRuntime) -> list[str]:
    with runtime.actor("maker") as (connection, repository, actor):
        visible = connection.execute("SELECT dimension_code,dimension_type FROM reconforge.finance_dimensions WHERE tenant_id=%s", (runtime.base.tenant,)).fetchall()
        assert [(row["dimension_code"],row["dimension_type"]) for row in visible]==[("PROJECT","Project")]
        values = connection.execute("SELECT value_code FROM reconforge.finance_dimension_values WHERE tenant_id=%s ORDER BY value_code", (runtime.base.tenant,)).fetchall()
        assert [row["value_code"] for row in values]==["P1","P2"]
        projects = [repository.register_project(SCOPE, project_code=code, dimension_code="PROJECT", value_code=code, command_id="project-"+code, actor=actor)["id"] for code in ("P1", "P2")]
        times = []
        for index, (rate, minutes) in enumerate(((1001, (61, 29)), (999, (15, 45))), 1):
            employee = repository.register_employee(EmployeeRegistration(SCOPE, "E"+str(index), "Synthetic employee "+str(index), "maker" if index==1 else None), command_id="employee-"+str(index), actor=actor)
            repository.employ(EmploymentAgreement(employee["id"], "2026-10-01", "2026-10-31", rate, "USD", "Synthetic agreement"), command_id="employment-"+str(index), actor=actor)
            result = repository.submit_time(TimeSubmission(employee["id"], "2026-10-03", (TimeLine(projects[0], 0, minutes[0]), TimeLine(projects[1], minutes[0], sum(minutes))), "Approved synthetic time"), command_id="time-"+str(index), actor=actor)
            times.append(result)
    with runtime.actor("checker", private=False) as (_, repository, actor):
        for item in times:
            repository.approve_time(item["id"], expected_digest=item["source_digest"], command_id="approve-"+item["id"], actor=actor)
    return [item["id"] for item in times]


def prepare(runtime: PeopleRuntime, times: list[str], budget: dict[str, Any], command: str = "prepare") -> dict[str, Any]:
    with runtime.actor("maker") as (_, repository, actor):
        return repository.prepare_payrun(SCOPE, time_ids=times, budget_id=budget["id"], expected_budget_version=budget["row_version"],
            period_id="period", posting_date="2026-10-04", journal_code="STOCK", expense_account_code="LABOR", liability_account_code="WAGES", cash_account_code="CASH", command_id=command, actor=actor)


def commit(runtime: PeopleRuntime, plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    with runtime.actor("checker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="review-"+suffix, actor=actor)
    with runtime.actor("poster") as (_, repository, actor):
        return repository.post(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="post-"+suffix, actor=actor)


def test_complete_native_time_accrual_partial_final_cash(people: PeopleRuntime) -> None:
    budget, times = approved_budget(people), approved_time(people)
    plan = prepare(people, times, budget)
    assert plan["amount_minor"] == 2501
    assert sorted(plan["project_minor"].values()) == [1233, 1268]
    commit(people, plan, "accrual")
    with people.actor("maker") as (_, repository, actor):
        proof = repository.evidence(plan["id"], actor=actor)
        employees = proof["payrun"]["private"]["employees"]
        first = next(item for item in employees if item["gross_minor"]==1502)["employee_id"]
        second = next(item for item in employees if item["gross_minor"]==999)["employee_id"]
        partial = repository.prepare_payment(plan["id"], employees_minor={first:1000}, period_id="period", posting_date="2026-10-05", command_id="partial", actor=actor)
    commit(people, partial, "partial")
    with people.actor("maker") as (_, repository, actor):
        final = repository.prepare_payment(plan["id"], employees_minor={first:502, second:999}, period_id="period", posting_date="2026-10-06", command_id="final", actor=actor)
    commit(people, final, "final")
    with people.actor("maker") as (connection, repository, actor):
        proof = repository.evidence(plan["id"], actor=actor)
        assert len(proof["native_effects"])==3
        assert [row["operation"] for row in proof["budget_events"]]==["Reserve", "Consume"]
        budget = PostgresBudgetControlRepository(connection, people.base.tenant).get(BudgetScope("work","org","entity"), budget["id"])
        assert budget["consumed_minor"]=="2501" and budget["available_minor"]=="7499"
        balances = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor) AS balance
            FROM reconforge.finance_entry_lines l JOIN reconforge.finance_posting_effects e ON e.tenant_id=l.tenant_id AND e.entry_id=l.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=%s GROUP BY a.account_code""", (people.base.tenant,)).fetchall()
        assert {row["account_code"]:int(row["balance"]) for row in balances}=={"LABOR":2501,"WAGES":0,"CASH":-2501}
        proof["observed_native_balances"] = {row["account_code"]:int(row["balance"]) for row in balances}
        proof["observed_budget"] = budget
        target = Path(__file__).resolve().parents[1]/"output"/"people-project-native-cycle-evidence.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(proof,sort_keys=True,ensure_ascii=False,separators=(",",":"),default=lambda value:value.isoformat()),encoding="utf-8")


def test_ordinary_role_forged_personnel_selector_denied(people: PeopleRuntime) -> None:
    approved_time(people)
    with people.actor("maker", private=False) as (connection, _, _):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_employee_private").fetchone()["n"]==0
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_rates").fetchone()["n"]==0
        assert connection.execute("SELECT pg_has_role(session_user,'reconforge_personnel_runtime','MEMBER') AS member").fetchone()["member"] is False
    with people.actor("maker") as (connection, _, _):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_employee_private").fetchone()["n"]==2


def test_unposted_cancel_preserves_history_then_reclaims_once(people: PeopleRuntime) -> None:
    budget, times = approved_budget(people), approved_time(people)
    first = prepare(people, times, budget)
    with people.actor("maker") as (connection, repository, actor):
        repository.cancel(first["id"], expected_plan_digest=first["plan_digest"], command_id="cancel", actor=actor)
        budget = PostgresBudgetControlRepository(connection, people.base.tenant).get(BudgetScope("work","org","entity"), budget["id"])
    second = prepare(people, times, budget, "second-prepare")
    commit(people, second, "second")
    with people.actor("maker") as (connection, _, _):
        rows = connection.execute("SELECT operation,sequence FROM reconforge.hc_claim_events WHERE tenant_id=%s ORDER BY time_id,sequence", (people.base.tenant,)).fetchall()
        assert [(row["operation"],row["sequence"]) for row in rows]==[("Claim",1),("Release",2),("Claim",3),("Consume",4)]*2
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_time_claims WHERE tenant_id=%s", (people.base.tenant,)).fetchone()["n"]==4


def test_lost_response_replays_same_native_command_without_new_claim_or_reserve(people: PeopleRuntime) -> None:
    budget, times = approved_budget(people), approved_time(people)
    first = prepare(people, times, budget)
    assert prepare(people, list(reversed(times)), budget)==first
    with people.actor("maker") as (connection, repository, actor):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_payruns WHERE tenant_id=%s", (people.base.tenant,)).fetchone()["n"]==1
        assert connection.execute("SELECT count(*) AS n FROM reconforge.budget_commitment_events WHERE tenant_id=%s", (people.base.tenant,)).fetchone()["n"]==1
        with pytest.raises(FinancePostingError, match="already belongs"):
            repository.prepare_payrun(SCOPE, time_ids=times[:1], budget_id=budget["id"], expected_budget_version=budget["row_version"], period_id="period", posting_date="2026-10-04", journal_code="STOCK", expense_account_code="LABOR", liability_account_code="WAGES", cash_account_code="CASH", command_id="prepare", actor=actor)


def test_two_parallel_payruns_claim_whole_approved_time_once(people: PeopleRuntime) -> None:
    budget, times = approved_budget(people), approved_time(people)
    barrier = Barrier(2)
    def attempt(index: int) -> str:
        barrier.wait(timeout=10)
        try:
            return prepare(people, times, budget, "race-"+str(index))["id"]
        except (FinancePostingError, BudgetControlError):
            return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (1,2)))
    assert outcomes.count("refused")==1
    with people.actor("maker") as (connection, _, _):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_payruns WHERE tenant_id=%s", (people.base.tenant,)).fetchone()["n"]==1
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_claim_heads WHERE tenant_id=%s AND state='Active'", (people.base.tenant,)).fetchone()["n"]==2


def test_direct_sql_cannot_consume_budget_without_accrual_effect(people: PeopleRuntime) -> None:
    import psycopg
    budget, times = approved_budget(people), approved_time(people)
    plan = prepare(people, times, budget)
    with pytest.raises(psycopg.errors.CheckViolation):  # noqa: SIM117 - commit-time refusal belongs to the outer assertion
        with people.actor("maker") as (connection, _, _):
            budget = PostgresBudgetControlRepository(connection, people.base.tenant)
            current = budget.get(BudgetScope("work","org","entity"), plan["budget_id"])
            budget.record(BudgetScope("work","org","entity"), plan["budget_id"], CommitmentAction("Consume",2501,"2026-10-04",plan["id"],"SQL bypass attempt"), expected_version=current["row_version"], commitment_id=plan["commitment_id"], command_id="bypass-consume")
    with people.actor("maker") as (connection, _, _):
        row = connection.execute("SELECT reserved_minor,consumed_minor FROM reconforge.budget_envelopes WHERE tenant_id=%s AND id=%s", (people.base.tenant,plan["budget_id"])).fetchone()
        assert (row["reserved_minor"], row["consumed_minor"])==(2501,0)


@pytest.mark.parametrize("kind", ["time", "rate", "claim", "private", "dimension"])
def test_direct_sql_cannot_rewrite_original_source_or_claim(people: PeopleRuntime, kind: str) -> None:
    import psycopg
    budget, times = approved_budget(people), approved_time(people)
    plan = prepare(people, times, budget)
    with pytest.raises(psycopg.errors.CheckViolation):  # noqa: SIM117 - commit-time refusal belongs to the outer assertion
        with people.actor("maker") as (connection, _, _):
            queries = {"time": "UPDATE reconforge.hc_times SET source_digest=repeat('0',64) WHERE tenant_id=%s",
                "rate": "UPDATE reconforge.hc_rates SET hourly_rate_minor=hourly_rate_minor+1 WHERE tenant_id=%s",
                "claim": "DELETE FROM reconforge.hc_time_claims WHERE tenant_id=%s",
                "private": "UPDATE reconforge.hc_payrun_private SET payload=payload||'{\"gross_minor\":2502}'::jsonb WHERE tenant_id=%s",
                "dimension": "UPDATE reconforge.finance_dimensions SET dimension_type='Custom' WHERE tenant_id=%s"}
            if kind=="dimension":
                # Existing reference update policy needs organization scope;
                # the inverse source guard must still refuse the changed master.
                connection.execute("SELECT set_config('app.entity_id','',true),set_config('app.legal_entity_id','',true)")
            cursor = connection.execute(queries[kind], (people.base.tenant,))
            assert cursor.rowcount>0
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with people.actor("maker") as (_, repository, actor):
        assert repository.evidence(plan["id"], actor=actor)["payrun"]["amount_minor"]==2501


def test_current_private_permission_revocation_and_self_approval_refused(people: PeopleRuntime) -> None:
    approved_time(people)
    with people.actor("poster", private=False) as (connection, repository, actor):
        employee = connection.execute("SELECT id FROM reconforge.hc_employees WHERE tenant_id=%s AND linked_user_id='maker'", (people.base.tenant,)).fetchone()["id"]
        project = connection.execute("SELECT id FROM reconforge.hc_projects WHERE tenant_id=%s ORDER BY id LIMIT 1", (people.base.tenant,)).fetchone()["id"]
        submitted = repository.submit_time(TimeSubmission(employee,"2026-10-04",(TimeLine(project,0,60),),"Synthetic linked identity control"),command_id="linked-time",actor=actor)
    with people.actor("maker") as (connection, repository, actor):
        with pytest.raises(FinancePostingError, match="independent"):
            repository.approve_time(submitted["id"], expected_digest=submitted["source_digest"], command_id="self", actor=actor)
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=false,revoked_at=clock_timestamp(),revoked_by='maker',revocation_reason_code='access_change',lifecycle_version=lifecycle_version+1 WHERE tenant_id=%s AND permission_name='people_project_payroll.read_sensitive'", (people.base.tenant,))
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_rates").fetchone()["n"]==0
        with pytest.raises(FinancePostingError):
            repository.employ(EmploymentAgreement(employee, "2026-11-01", "2026-11-30", 1001, "USD", "Revoked"), command_id="revoked", actor=actor)


def test_cancel_post_race_conserves_one_final_claim_state(people: PeopleRuntime) -> None:
    budget, times = approved_budget(people), approved_time(people)
    plan = prepare(people, times, budget)
    with people.actor("checker") as (_, repository, actor):
        repository.review(plan["id"], expected_plan_digest=plan["plan_digest"], command_id="review-race", actor=actor)
    barrier = Barrier(2)
    def action(kind: str) -> str:
        barrier.wait(timeout=10)
        try:
            with people.actor("maker" if kind=="cancel" else "poster") as (_, repository, actor):
                operation = repository.cancel if kind=="cancel" else repository.post
                operation(plan["id"], expected_plan_digest=plan["plan_digest"], command_id=kind+"-race", actor=actor)
            return kind
        except (FinancePostingError, BudgetControlError):
            return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(action, ("cancel","post")))
    assert result.count("refused")==1
    with people.actor("maker") as (connection, repository, actor):
        current = repository.get(plan["id"], actor=actor)
        assert current["phase"] in {2,3}
        rows = connection.execute("SELECT state FROM reconforge.hc_claim_heads WHERE tenant_id=%s", (people.base.tenant,)).fetchall()
        assert {row["state"] for row in rows}=={"Consumed" if current["phase"]==2 else "Released"}
        events = connection.execute("SELECT operation FROM reconforge.budget_commitment_events WHERE tenant_id=%s ORDER BY budget_version", (people.base.tenant,)).fetchall()
        assert [row["operation"] for row in events]==["Reserve","Consume" if current["phase"]==2 else "Release"]


def test_ordinary_worker_can_deliver_immutable_hc_events_without_private_access(people: PeopleRuntime) -> None:
    from reconforge.infrastructure.postgres_outbox import PostgresOutboxRepository
    budget, times = approved_budget(people), approved_time(people)
    plan = prepare(people,times,budget)
    commit(people,plan,"worker")
    with people.actor("maker",private=False) as (connection,_,_):
        outbox = PostgresOutboxRepository(connection)
        events = outbox.claim_pending(tenant_id=people.base.tenant,worker_id="hc-synthetic-worker",limit=100)
        own = [event for event in events if event.aggregate_id==plan["id"]]
        assert len(own)==3
        for event in events:
            outbox.mark_published(tenant_id=people.base.tenant,event_id=event.id,worker_id="hc-synthetic-worker",lease_generation=event.lease_generation)
        assert connection.execute("SELECT count(*) AS n FROM reconforge.hc_rates").fetchone()["n"]==0
    with people.actor("maker") as (_,repository,actor):
        assert repository.evidence(plan["id"],actor=actor)["payrun"]["status"]=="Posted"
