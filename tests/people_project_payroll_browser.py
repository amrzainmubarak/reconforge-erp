"""Synthetic masters and dual-role evidence for the real HC1 browser gate."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from reconforge.domain.budget_control import BudgetScope
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_budget_control import PostgresBudgetControlRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime
from tests.test_postgres_people_project_payroll import PERMISSIONS, PeopleRuntime, approved_budget
from tests.verify_people_project_payroll_oracle import verify

PEOPLE_PROJECT_PAYROLL_TABLES = (
    "hc_employees","hc_employee_private","hc_employments","hc_rates","hc_projects","hc_times","hc_payruns","hc_payrun_private",
    "hc_payments","hc_payment_private","hc_time_claims","hc_claim_events","hc_claim_heads","hc_commands",
    "budget_envelopes","budget_commitment_events","budget_commands",
    "finance_entries","finance_entry_lines","finance_entry_line_dimensions","finance_posting_effects","domain_audit_events","outbox_events",
)
PEOPLE_PROJECT_PAYROLL_WORKSPACE_PROBE_TABLES = tuple(name for name in PEOPLE_PROJECT_PAYROLL_TABLES if name!="domain_audit_events")
PEOPLE_PROJECT_PAYROLL_TAMPER = (
    "UPDATE reconforge.hc_claim_events SET sequence=sequence+1 WHERE tenant_id=%s",
    "UPDATE reconforge.hc_payruns SET amount_minor=amount_minor+1 WHERE tenant_id=%s",
    "DELETE FROM reconforge.hc_commands WHERE tenant_id=%s",
)
_private_credentials: dict[str,str] = {}


def personnel_browser_dsn(base: ReceiptRuntime) -> str:
    """Return a separately authenticated private login, never record its DSN.

    The database-only archive requires this cluster role to be provisioned
    separately. A restored runtime translates the same owned login to its DB.
    """
    import psycopg
    from psycopg import sql
    database=psycopg.conninfo.conninfo_to_dict(base.admin_dsn)["dbname"]
    if base.tenant not in _private_credentials:
        login,password="hc_browser_"+uuid4().hex[:12],"Synthetic-HC-"+uuid4().hex
        with psycopg.connect(base.admin_dsn) as admin:
            flags=admin.execute("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolinherit,rolreplication FROM pg_roles WHERE rolname='reconforge_personnel_runtime'").fetchone()
            if flags!=(False,False,False,False,False,False,False):
                raise ValueError("Safe migrated personnel group is required")
            ordinary=psycopg.conninfo.conninfo_to_dict(base.factory.settings.dsn)["user"]
            if admin.execute("SELECT pg_has_role(%s,'reconforge_personnel_runtime','MEMBER')",(ordinary,)).fetchone()[0] is not False:
                raise ValueError("Ordinary finance login must not be a personnel group member")
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB PASSWORD {}").format(sql.Identifier(login),sql.Literal(password)))
            admin.execute(sql.SQL("GRANT reconforge_personnel_runtime TO {}").format(sql.Identifier(login)))
            for command in ("GRANT USAGE ON SCHEMA reconforge TO {}","GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}","GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}"):
                admin.execute(sql.SQL(command).format(sql.Identifier(login)))
        _private_credentials[base.tenant]=psycopg.conninfo.make_conninfo(base.factory.settings.dsn,user=login,password=password)
    return psycopg.conninfo.make_conninfo(_private_credentials[base.tenant],dbname=database)


def private_runtime(base: ReceiptRuntime) -> PeopleRuntime:
    return PeopleRuntime(base,PostgresConnectionFactory(PostgresSettings(dsn=personnel_browser_dsn(base),require_tls=False)))


def seed_people_project_payroll_browser(admin_dsn: str,app_dsn: str) -> ReceiptRuntime:
    """Only masters and approved budget: employee/time/wage source writes use UI."""
    base=create_receipt_runtime((admin_dsn,app_dsn))
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        identity=PostgresIdentityRepository(connection)
        for permission in sorted(PERMISSIONS):
            identity.create_permission(tenant_id=base.tenant,permission_name=permission)
            identity.grant_permission(tenant_id=base.tenant,role_name="receipt-operator",permission_name=permission)
        for actor in ("maker","checker","poster"):
            for kind,identifier in (("workspace","work"),("organization","org"),("legal_entity","entity")):
                PostgresScopeAuthorityRepository(connection).grant(tenant_id=base.tenant,grant_id="hc-browser-"+actor+kind,
                    principal_type="user",principal_id=actor,scope_type=kind,scope_id=identifier,actor_id=actor)
        finance=PostgresFinanceCoreRepository(connection,base.tenant)
        for code,kind in (("LABOR","Expense"),("WAGES","Liability"),("CASH","Asset")):
            finance.upsert_account(account_code=code,name=code,account_type=kind,chart_code="DEFAULT",workspace="work")
        finance.upsert_dimension(dimension_code="PROJECT",name="Projects",dimension_type="Project",workspace="work",organization_code="ORG")
        for code in ("P1","P2"):
            finance.upsert_dimension_value(dimension_code="PROJECT",value_code=code,name=code,workspace="work")
    approved_budget(private_runtime(base))
    return base


@contextmanager
def people_project_payroll_restore_tamper_actor(base: ReceiptRuntime) -> Iterator[tuple[Any,Any,Any]]:
    with private_runtime(base).actor("poster") as values:
        yield values


def verify_people_project_payroll_browser(base: ReceiptRuntime) -> dict[str,Any]:
    from psycopg import sql
    people=private_runtime(base)
    with people.actor("maker",private=False) as (connection,_,_):
        if connection.execute("SELECT pg_has_role(session_user,'reconforge_personnel_runtime','MEMBER') AS member").fetchone()["member"] is not False:
            raise ValueError("Ordinary browser finance login has private membership")
        for name in ("hc_employee_private","hc_rates","hc_payrun_private","hc_payment_private"):
            if connection.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier("reconforge",name))).fetchone()["n"]!=0:
                raise ValueError("Ordinary forged actor selector leaked private data")
    with people.actor("maker") as (connection,repository,actor):
        rows=connection.execute("SELECT id FROM reconforge.hc_payruns WHERE tenant_id=%s AND phase=2",(base.tenant,)).fetchall()
        if len(rows)!=1:
            raise ValueError("Browser must post exactly one accrual")
        evidence=repository.evidence(rows[0]["id"],actor=actor)
        evidence["observed_budget"]=PostgresBudgetControlRepository(connection,base.tenant).get(BudgetScope("work","org","entity"),evidence["payrun"]["budget_id"])
        balances=connection.execute("SELECT a.account_code,sum(l.debit_minor-l.credit_minor) AS amount FROM reconforge.finance_entry_lines l JOIN reconforge.finance_posting_effects p ON p.tenant_id=l.tenant_id AND p.entry_id=l.entry_id JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=%s GROUP BY a.account_code",(base.tenant,)).fetchall()
        evidence["observed_native_balances"]={row["account_code"]:int(row["amount"]) for row in balances}
    independent=verify(evidence)
    if independent["gross_minor"]!=2501 or independent["settled_minor"]!=2501 or independent["native_effects"]!=3:
        raise ValueError("Browser native financial cycle differs from exact synthetic fixture")
    return {"schema_version":"people-payroll-browser-proof-v1","independent_financial_proof":evidence,
        "independent_oracle":independent,"ordinary_private_rows":0,"private_role_prerequisite":"reconforge_personnel_runtime",
        "statutory_country_packs":0,"bank_execution_proven":False}
