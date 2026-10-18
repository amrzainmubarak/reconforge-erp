"""Populated native wage restore with explicit personnel-role prerequisite.

The trusted fixture supplies an exact root-owned container ID. This test never
stops that service and never persists the dump, connection strings or secrets.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_people_project_payroll import (
    PeopleRuntime,
    approved_budget,
    approved_time,
    commit,
    prepare,
)

pytest_plugins = ("tests.test_postgres_people_project_payroll",)


def native(container: str, tool: str, database: str, data: bytes | None = None) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", container) or not re.fullmatch(r"reconforge_(?:irp|hc_restore)_[0-9a-f]{12}", database):
        raise ValueError("Exact owned container and fixture database required")
    inspected = subprocess.run(["docker", "container", "inspect", "--format", "{{.Id}}", container],
        capture_output=True, timeout=10, check=False)
    if inspected.returncode != 0 or inspected.stdout.decode().strip() != container:
        raise ValueError("Owned fixture identity could not be verified")
    flags = {"pg_dump": ["--format=custom"], "pg_restore": ["--exit-on-error", "--no-owner"]}
    if tool not in flags:
        raise ValueError("Only fixed native dump/restore tools are supported")
    result = subprocess.run(["docker", "exec", "-i", container, tool, "-U", "postgres", *flags[tool], "--dbname", database],
        input=data, capture_output=True, timeout=90, check=False)
    if result.returncode != 0:
        # The administrative dump includes authentication state; retain only
        # bounded safe diagnostics, never raw stderr or environment values.
        raise ValueError(f"Native {tool} failed: exit={result.returncode}, stderr_sha256={hashlib.sha256(result.stderr).hexdigest()}")
    return result.stdout


def history(connection: Any) -> dict[str, Any]:
    from psycopg import sql
    tables = [row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='reconforge' ORDER BY tablename")]
    result: dict[str, Any] = {}
    for table in tables:
        rows = sorted(json.dumps(row[0],sort_keys=True,ensure_ascii=False,separators=(",",":")) for row in
            connection.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier("reconforge",table))))
        result[table] = {"rows":len(rows),"sha256":hashlib.sha256(json.dumps(rows,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()}
    result["revision"] = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    catalog = connection.execute("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' AND c.relname LIKE 'hc_%' ORDER BY c.relname").fetchall()
    result["hc_catalog"] = [list(row) for row in catalog]
    result["hc_policies"] = [list(row) for row in connection.execute("SELECT tablename,policyname,roles,cmd,qual,with_check FROM pg_policies WHERE schemaname='reconforge' AND tablename LIKE 'hc_%' ORDER BY tablename,policyname")]
    return result


def test_populated_native_restore_preserves_claims_privacy_and_remaining_cash(people: PeopleRuntime) -> None:
    import psycopg
    from psycopg import sql
    container = os.environ["RECONFORGE_TEST_POSTGRES_CONTAINER"]
    budget,times = approved_budget(people),approved_time(people)
    plan = prepare(people,times,budget)
    commit(people,plan,"restore-accrual")
    with people.actor("maker") as (_,repository,actor):
        evidence = repository.evidence(plan["id"],actor=actor)
        employees = evidence["payrun"]["private"]["employees"]
        first = next(row["employee_id"] for row in employees if row["gross_minor"]==1502)
        second = next(row["employee_id"] for row in employees if row["gross_minor"]==999)
        partial = repository.prepare_payment(plan["id"],employees_minor={first:1000},period_id="period",posting_date="2026-10-05",command_id="restore-partial",actor=actor)
    posted_partial = commit(people,partial,"restore-partial")
    # Authenticate before the snapshot so comparison occurs before any restored
    # authentication updates its last-used state.
    with people.actor("maker") as (_,repository,actor):
        original_evidence = repository.evidence(plan["id"],actor=actor)
    admin_params = psycopg.conninfo.conninfo_to_dict(people.base.admin_dsn)
    original_database = admin_params["dbname"]
    restored_name = "reconforge_hc_restore_"+uuid4().hex[:12]
    private_login = psycopg.conninfo.conninfo_to_dict(people.private.settings.dsn)["user"]
    ordinary_login = psycopg.conninfo.conninfo_to_dict(people.base.factory.settings.dsn)["user"]
    with psycopg.connect(people.base.admin_dsn) as admin:
        assert admin.execute("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolinherit,rolreplication FROM pg_roles WHERE rolname='reconforge_personnel_runtime'").fetchone()==(False,False,False,False,False,False,False)
        assert admin.execute("SELECT pg_has_role(%s,'reconforge_personnel_runtime','MEMBER'),pg_has_role(%s,'reconforge_personnel_runtime','MEMBER')",(private_login,ordinary_login)).fetchone()==(True,False)
        before = history(admin)
    dump = native(container,"pg_dump",original_database)
    assert dump.startswith(b"PGDMP")
    control_dsn = psycopg.conninfo.make_conninfo(people.base.admin_dsn,dbname="postgres")
    with psycopg.connect(control_dsn,autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored_name)))
    try:
        native(container,"pg_restore",restored_name,dump)
        restored_admin = psycopg.conninfo.make_conninfo(people.base.admin_dsn,dbname=restored_name)
        with psycopg.connect(restored_admin) as admin:
            assert history(admin)==before
            # pg_dump is a database archive, not a cluster role backup. Actual
            # separately provisioned group/login membership is a prerequisite.
            assert admin.execute("SELECT pg_has_role(%s,'reconforge_personnel_runtime','MEMBER'),pg_has_role(%s,'reconforge_personnel_runtime','MEMBER')",(private_login,ordinary_login)).fetchone()==(True,False)
        ordinary = PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(people.base.factory.settings.dsn,dbname=restored_name),require_tls=False))
        private = PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(people.private.settings.dsn,dbname=restored_name),require_tls=False))
        restored = PeopleRuntime(ReceiptRuntime(ordinary,restored_admin,people.base.tenant,people.base.password),private)
        with restored.actor("maker",private=False) as (connection,_,_):
            assert connection.execute("SELECT pg_has_role(session_user,'reconforge_personnel_runtime','MEMBER') AS member").fetchone()["member"] is False
            for table in ("hc_employee_private","hc_rates","hc_payrun_private","hc_payment_private"):
                assert connection.execute(sql.SQL("SELECT count(*) AS n FROM {} ").format(sql.Identifier("reconforge",table))).fetchone()["n"]==0
        with restored.actor("maker") as (_,repository,actor):
            assert repository.evidence(plan["id"],actor=actor)==original_evidence
            # Versioned command receipts replay the original response, while
            # the separately loaded source retains its later posted phase.
            assert repository.prepare_payment(plan["id"],employees_minor={first:1000},period_id="period",posting_date="2026-10-05",command_id="restore-partial",actor=actor)==partial
            assert repository.get(partial["id"],actor=actor)==posted_partial
            final = repository.prepare_payment(plan["id"],employees_minor={first:502,second:999},period_id="period",posting_date="2026-10-06",command_id="restore-final",actor=actor)
        commit(restored,final,"restore-final")
        with restored.actor("maker") as (connection,repository,actor):
            final_evidence = repository.evidence(plan["id"],actor=actor)
            assert len(final_evidence["native_effects"])==3
            balances=connection.execute("SELECT a.account_code,sum(l.debit_minor-l.credit_minor) AS amount FROM reconforge.finance_entry_lines l JOIN reconforge.finance_posting_effects p ON p.tenant_id=l.tenant_id AND p.entry_id=l.entry_id JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id WHERE l.tenant_id=%s GROUP BY a.account_code",(people.base.tenant,)).fetchall()
            assert {row["account_code"]:int(row["amount"]) for row in balances}=={"LABOR":2501,"WAGES":0,"CASH":-2501}
            with pytest.raises(psycopg.errors.CheckViolation),connection.transaction():
                connection.execute("UPDATE reconforge.hc_claim_events SET sequence=sequence+1 WHERE tenant_id=%s",(people.base.tenant,))
        target=Path(__file__).resolve().parents[1]/"output"/("people-project-populated-restore-"+uuid4().hex[:12]+".json")
        target.write_text(json.dumps({"schema_version":"people-payroll-populated-restore-v1","dump_bytes":len(dump),"dump_sha256":hashlib.sha256(dump).hexdigest(),"history":before,"native_effects":3,"wages_minor":2501,"partial_before_restore_minor":1000,"remaining_after_restore_minor":1501,"ordinary_private_rows":0,"personnel_membership_provisioned_separately":True,"benchmark":False},sort_keys=True,separators=(",",":")),encoding="utf-8")
    finally:
        with psycopg.connect(control_dsn,autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(restored_name)))
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s",(restored_name,)).fetchone() is None
