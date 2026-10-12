"""Mandatory native 136/137 guard lifecycle; explicit committed runtime, no skips.

This module runs only in the dedicated PostgreSQL diagnostic gate. It retains
the original IC source owner and independent integer financial expectations;
the projection candidate remains unaccepted until these actual SQL gates pass.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reconforge.infrastructure.postgres_intercompany_guard_projection import (
    TABLE_FIELD_PROJECTIONS,
    UPGRADE_SQL,
)
from tests.test_postgres_intercompany_operations import (
    IntercompanyRuntime,
    intercompany_database,
    preparation,
    publish,
    recognize,
    seed_intercompany_masters,
)
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime, receipt_database

__all__ = ["intercompany_database", "receipt_database"]
REVIEWED_RUNTIME = "a4a5282aaf29ff89e182569888877fa606dde6a5"
ORIGINAL_HEAD = "0136_pg_inventory_scope"
PROJECTED_HEAD = "0137_pg_intercompany_projection"
TABLES = tuple(table for table, _ in TABLE_FIELD_PROJECTIONS)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=root, text=True, timeout=15).strip()


@pytest.fixture(scope="module", autouse=True)
def projection_runtime_contract() -> Path:
    names = ("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", "RECONFORGE_TEST_POSTGRES_DSN",
             "RECONFORGE_IC_PROJECTION_RUNTIME_ROOT", "RECONFORGE_IC_PROJECTION_RUNTIME_COMMIT")
    missing = [name for name in names if not os.environ.get(name)]
    assert not missing, "Mandatory native projection prerequisites missing: " + ", ".join(missing)
    root = Path(os.environ["RECONFORGE_IC_PROJECTION_RUNTIME_ROOT"]).resolve()
    actual = os.environ["RECONFORGE_IC_PROJECTION_RUNTIME_COMMIT"]
    assert re.fullmatch(r"[0-9a-f]{40}", actual), "Exact actual diagnostic commit required"
    assert _git(root, "rev-parse", "HEAD") == actual
    subprocess.run(["git", "merge-base", "--is-ancestor", REVIEWED_RUNTIME, actual], cwd=root,
                   check=True, timeout=15)
    for tree in ("reconforge", "alembic"):
        assert _git(root, "rev-parse", f"{actual}:{tree}") == _git(root, "rev-parse", f"{REVIEWED_RUNTIME}:{tree}")
    for name in ("reconforge", "reconforge.infrastructure.postgres_finance_core",
                 "reconforge.infrastructure.postgres_finance_posting",
                 "reconforge.infrastructure.postgres_intercompany_operations_schema",
                 "reconforge.infrastructure.postgres_intercompany_guard_projection"):
        origin = importlib.import_module(name).__file__
        assert origin is not None and Path(origin).resolve().is_relative_to(root)
        relative = Path(origin).resolve().relative_to(root).as_posix()
        assert _git(root, "ls-files", "--", relative) == relative
    assert Path(__file__).resolve().parents[1] == root, "Native control and runtime must share the committed checkout"
    assert not _git(root, "status", "--porcelain", "--untracked-files=normal"), "Committed source must be clean"
    return root


@pytest.fixture(scope="module")
def projection_database(projection_runtime_contract: Path, intercompany_database: tuple[str, str]) -> tuple[str, str]:
    import psycopg

    with psycopg.connect(intercompany_database[1]) as connection:
        assert connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone() == (False, False)
    with psycopg.connect(intercompany_database[0]) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (PROJECTED_HEAD,)
        assert connection.execute("SELECT current_setting('server_version_num')").fetchone() == ("170011",)
    return intercompany_database


@pytest.fixture
def projection_runtime(projection_database: tuple[str, str]) -> IntercompanyRuntime:
    return seed_intercompany_masters(create_receipt_runtime(projection_database))


def _migrate(root: Path, database: tuple[str, str], direction: str, revision: str) -> None:
    # DSNs remain only in the subprocess environment; never argv or evidence.
    result = subprocess.run([sys.executable, "-m", "alembic", direction, revision], cwd=root,
                            env={**os.environ, "PYTHONPATH": str(root), "RECONFORGE_POSTGRES_DSN": database[0]},
                            capture_output=True, timeout=180, check=False)
    assert result.returncode == 0, "Exact native migration command failed"
    import psycopg

    with psycopg.connect(database[0]) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (revision,)


def _catalog(database: tuple[str, str]) -> tuple[dict[str, Any], str]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database[0], row_factory=dict_row) as connection:
        function = connection.execute("""SELECT oid,proowner,proacl,prosecdef,proconfig,prokind,prorettype,
            proargtypes::text,prosrc FROM pg_proc WHERE oid='reconforge.ic_operation_reverse_close()'::regprocedure""").fetchone()
        assert function is not None and function["prosecdef"] is False and function["prokind"] == "f"
        assert function["proconfig"] == ["search_path=pg_catalog"] and function["proargtypes"] == ""
        body = function.pop("prosrc")
        triggers = connection.execute("""SELECT t.oid,t.tgrelid,c.relname,t.tgfoid,t.tgtype,t.tgenabled,
            t.tgdeferrable,t.tginitdeferred,t.tgisinternal,pg_get_triggerdef(t.oid) definition
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            WHERE t.tgfoid='reconforge.ic_operation_reverse_close()'::regprocedure ORDER BY c.relname""").fetchall()
        assert [row["relname"] for row in triggers] == sorted(TABLES)
        assert all(row["tgdeferrable"] and row["tginitdeferred"] and not row["tgisinternal"]
                   and row["tgtype"] == 29 and row["tgenabled"] == "O" for row in triggers)
        policies = connection.execute("""SELECT c.relname,c.oid,c.relrowsecurity,c.relforcerowsecurity,
            p.oid policy_oid,p.polname,p.polcmd,p.polpermissive,p.polroles,
            pg_get_expr(p.polqual,p.polrelid) using_expression,
            pg_get_expr(p.polwithcheck,p.polrelid) check_expression
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_policy p ON p.polrelid=c.oid
            WHERE n.nspname='reconforge' AND c.relname=ANY(%s) ORDER BY c.relname,p.polname""", (list(TABLES),)).fetchall()
        assert {row["relname"] for row in policies} == set(TABLES)
        assert all(row["relrowsecurity"] and row["relforcerowsecurity"] and row["policy_oid"] for row in policies)
        return {"function": dict(function), "triggers": list(map(dict, triggers)), "policies": list(map(dict, policies))}, body


def _retained_rows(database: tuple[str, str], tenant: str) -> dict[str, str]:
    import psycopg
    from psycopg import sql

    result = {}
    with psycopg.connect(database[0]) as connection:
        for table in TABLES:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(t)::text FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text")
                                      .format(sql.Identifier(table)), (tenant,)).fetchall()
            result[table] = hashlib.sha256("\n".join(row[0] for row in rows).encode()).hexdigest()
    return result


def test_native_catalog_projection_covers_every_consumed_existing_text_field(projection_database: tuple[str, str]) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_intercompany_guard_projection import ORIGINAL_FUNCTION_SQL

    consumed = set(re.findall(r"changed->>'([a-z_]+)'", ORIGINAL_FUNCTION_SQL))
    assert consumed == {"tenant_id", "id", "entry_id", "entry_line_id", "reverses_posting_id", "reverses_effect_id",
                        "entry_number", "entity_code", "plan_id", "object_id", "aggregate_id"}
    with psycopg.connect(projection_database[0]) as connection:
        rows = connection.execute("""SELECT table_name,column_name,data_type FROM information_schema.columns
            WHERE table_schema='reconforge' AND table_name=ANY(%s)""", (list(TABLES),)).fetchall()
    actual = {table: {column: kind for name, column, kind in rows if name == table} for table in TABLES}
    for table, fields in TABLE_FIELD_PROJECTIONS:
        assert set(fields) == consumed & set(actual[table])
        assert all(actual[table][field] == "text" for field in fields)


def _integer(value: object) -> int:
    assert type(value) is int or isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value()
    return int(value)  # type: ignore[arg-type]


def _independent_financial_oracle(runtime: IntercompanyRuntime) -> None:
    expected = {("ENTITY", "IC_AR"): 7001, ("ENTITY", "IC_REVENUE"): -10001, ("ENTITY", "CASH"): 3000,
                ("BUYER", "IC_EXPENSE"): 10001, ("BUYER", "IC_AP"): -7001, ("BUYER", "CASH"): -3000,
                ("GROUP", "IC_AR"): -7001, ("GROUP", "IC_AP"): 7001,
                ("GROUP", "IC_REVENUE"): 10001, ("GROUP", "IC_EXPENSE"): -10001}
    with runtime.actor("poster") as (connection, _, _):
        rows = connection.execute("""SELECT e.entity_code,a.account_code,sum(l.debit_minor) debit,
            sum(l.credit_minor) credit FROM reconforge.finance_posting_effects f
            JOIN reconforge.finance_entries e ON e.tenant_id=f.tenant_id AND e.id=f.entry_id
            JOIN reconforge.finance_entry_lines l ON l.tenant_id=e.tenant_id AND l.entry_id=e.id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE f.tenant_id=%s GROUP BY e.entity_code,a.account_code""", (runtime.base.tenant,)).fetchall()
        assert {(row["entity_code"], row["account_code"]): _integer(row["debit"]) - _integer(row["credit"]) for row in rows} == expected
        assert sum(_integer(row["debit"]) for row in rows) == sum(_integer(row["credit"]) for row in rows) == 43004
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()["n"] == 5


def test_populated_exact_function_oid_acl_rls_trigger_and_financial_upgrade_rollback(
    projection_database: tuple[str, str], projection_runtime_contract: Path,
) -> None:
    import psycopg
    from psycopg import sql

    _migrate(projection_runtime_contract, projection_database, "downgrade", ORIGINAL_HEAD)
    try:
        app_role = psycopg.conninfo.conninfo_to_dict(projection_database[1])["user"]
        with psycopg.connect(projection_database[0]) as connection:
            connection.execute("REVOKE EXECUTE ON FUNCTION reconforge.ic_operation_reverse_close() FROM PUBLIC")
            connection.execute(sql.SQL("GRANT EXECUTE ON FUNCTION reconforge.ic_operation_reverse_close() TO {}").format(sql.Identifier(app_role)))
        original_catalog, original_body = _catalog(projection_database)
        assert original_catalog["function"]["proacl"], "Explicit privileges required for ACL preservation proof"
        assert "jsonb_build_array(to_jsonb(NEW))" in original_body
        runtime = seed_intercompany_masters(create_receipt_runtime(projection_database))
        original = recognize(runtime)
        with runtime.actor("maker") as (_, repository, actor):
            installment = repository.prepare_settlement(original["source_id"], amount_minor=3000, period_id="period",
                posting_date="2026-10-04", reason="Native projection partial settlement", command_id="partial", actor=actor)
        publish(runtime, installment, "partial")
        with runtime.actor("maker") as (_, repository, actor):
            elimination = repository.prepare_elimination(original["source_id"], period_id="period", posting_date="2026-10-05",
                reason="Native projection elimination", command_id="elimination", actor=actor)
        publish(runtime, elimination, "elimination")
        retained = _retained_rows(projection_database, runtime.base.tenant)
        _independent_financial_oracle(runtime)
        for direction, revision in (("upgrade", PROJECTED_HEAD), ("downgrade", ORIGINAL_HEAD), ("upgrade", PROJECTED_HEAD)):
            _migrate(projection_runtime_contract, projection_database, direction, revision)
            catalog, body = _catalog(projection_database)
            assert catalog == original_catalog
            assert _retained_rows(projection_database, runtime.base.tenant) == retained
            _independent_financial_oracle(runtime)
            if revision == ORIGINAL_HEAD:
                assert body == original_body
            else:
                assert "to_jsonb(NEW)" not in body and "to_jsonb(OLD)" not in body
                assert body == UPGRADE_SQL.split("AS $ic$", 1)[1].rsplit("$ic$;", 1)[0]
    finally:
        _migrate(projection_runtime_contract, projection_database, "upgrade", PROJECTED_HEAD)


@pytest.mark.parametrize("mutation", ["rename", "delete"])
def test_projected_old_header_relevance_refuses_sql_namespace_laundering(projection_runtime: IntercompanyRuntime, mutation: str) -> None:
    import psycopg

    with projection_runtime.actor("maker") as (_, repository, actor):
        plan = repository.prepare(preparation(), command_id="prepare-original", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation) as denied, projection_runtime.actor("maker") as (connection, _, _):
        entry = plan["entries"][0]["entry_id"]
        if mutation == "rename":
            connection.execute("UPDATE reconforge.finance_entries SET entry_number='BENCH-DETACHED' WHERE tenant_id=%s AND id=%s",
                               (projection_runtime.base.tenant, entry))
        else:
            connection.execute("DELETE FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s", (projection_runtime.base.tenant, entry))
            connection.execute("DELETE FROM reconforge.finance_entries WHERE tenant_id=%s AND id=%s", (projection_runtime.base.tenant, entry))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert denied.value.diag.constraint_name == "intercompany_operation_owner"
    with projection_runtime.actor("maker") as (_, repository, actor):
        assert repository.get_plan(plan["id"], actor=actor) == plan


def test_projected_ordinary_header_still_checks_original_intercompany_inverse(projection_runtime: IntercompanyRuntime) -> None:
    import psycopg

    original = recognize(projection_runtime)
    original_effect = next(iter(original["posting_effect_ids"].values()))
    with pytest.raises(psycopg.errors.CheckViolation) as denied, projection_runtime.actor("maker") as (connection, repository, actor):
        entry = repository.owner.finance.create_entry(entry_number="BENCH-INVERSE-TEMPLATE", organization_code="ORG",
            entity_code="ENTITY", period_id="period", journal_code="STOCK", posting_date="2026-10-04",
            description="Forbidden detached inverse", workspace="work", source_type="Generated", actor_label=actor.username,
            lines=[{"account_code": "IC_REVENUE", "debit": "100.01", "credit": "0"},
                   {"account_code": "IC_AR", "debit": "0", "credit": "100.01"}])
        detached = "projection-detached-" + uuid4().hex
        # Set reversal identity at INSERT. Updating it later would correctly be
        # refused by the earlier immutable-preparer guard, without reaching IC.
        connection.execute("""INSERT INTO reconforge.finance_entries
            SELECT (jsonb_populate_record(NULL::reconforge.finance_entries,to_jsonb(e)||jsonb_build_object(
                'id',%s::text,'entry_number','BENCH-DETACHED-INVERSE','reverses_posting_id',%s::text))).*
            FROM reconforge.finance_entries e WHERE e.tenant_id=%s AND e.id=%s""",
            (detached, original_effect, projection_runtime.base.tenant, entry["id"]))
        connection.execute("""INSERT INTO reconforge.finance_entry_lines
            SELECT (jsonb_populate_record(NULL::reconforge.finance_entry_lines,to_jsonb(l)||jsonb_build_object(
                'id',%s::text||'-'||l.line_number::text,'entry_id',%s::text))).*
            FROM reconforge.finance_entry_lines l WHERE l.tenant_id=%s AND l.entry_id=%s""",
            (detached, detached, projection_runtime.base.tenant, entry["id"]))
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert denied.value.diag.constraint_name == "intercompany_operation_owner"


@pytest.mark.parametrize("operation", ["table", "operation"])
def test_projected_uninstalled_table_and_operation_are_explicitly_refused(projection_database: tuple[str, str], operation: str) -> None:
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation) as denied, psycopg.connect(projection_database[1]) as connection:
        connection.execute("CREATE TEMP TABLE ic_projection_uninstalled(tenant_id TEXT,id TEXT)")
        if operation == "table":
            connection.execute("CREATE TRIGGER projection_probe BEFORE INSERT ON ic_projection_uninstalled FOR EACH ROW EXECUTE FUNCTION reconforge.ic_operation_reverse_close()")
            connection.execute("INSERT INTO ic_projection_uninstalled VALUES('synthetic','uninstalled')")
        else:
            connection.execute("CREATE TRIGGER projection_probe BEFORE TRUNCATE ON ic_projection_uninstalled FOR EACH STATEMENT EXECUTE FUNCTION reconforge.ic_operation_reverse_close()")
            connection.execute("TRUNCATE ic_projection_uninstalled")
    assert denied.value.diag.constraint_name == "intercompany_operation_owner"
    assert f"Unsupported Intercompany deferred guard {operation}" in str(denied.value)
