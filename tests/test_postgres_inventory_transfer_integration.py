"""Canonical146 native dispatch, scoped FK custody and retained MSP originals.

No owned schema is installed here: receipt_database runs the registered full
chain. All attacks use the restricted login and preserve the original rows.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_manufacturing_supply_plan import PostgresManufacturingSupplyPlanRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_inventory_receipt_posting import receipt_database as baseline_receipt_database
from tests.test_postgres_inventory_transfer import TABLES, transfer_runtime
from tests.test_postgres_manufacturing_supply_plan import planning_runtime, seed_partial_stock

_ = baseline_receipt_database
HEAD = "0146_pg_inventory_transfer"
PREVIOUS = "0145_pg_supply_closure"
ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ("inventory_quantity_directory_close", "inventory_quantity_guard_birth", "inventory_quantity_plan_namespace_guard")
MSP_TABLES = ("manufacturing_supply_plans", "manufacturing_supply_requirements", "manufacturing_supply_stock_claims",
              "manufacturing_supply_stock_releases", "manufacturing_supply_procurement_claims", "manufacturing_supply_events",
              "manufacturing_supply_commands", "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_receipt_links",
              "inventory_receipt_commands", "inventory_movements", "inventory_movement_lines", "inventory_cost_layers",
              "inventory_layer_consumptions", "inventory_valuation_documents", "inventory_valuation_lines", "finance_entries",
              "finance_entry_lines", "finance_posting_effects", "domain_audit_events", "outbox_events")


def _migrate(database: tuple[str, str], direction: str, revision: str) -> None:
    result = subprocess.run([sys.executable, "-m", "alembic", direction, revision], cwd=ROOT,
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": database[0]}, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr


def _catalog(connection: Any) -> dict[str, Any]:
    functions = connection.execute("""SELECT p.oid,p.proname,p.proowner,p.proacl,p.prosrc,p.prosecdef,p.proconfig,
        p.prokind,p.proretset,p.pronargs,p.proleakproof,l.lanname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_language l ON l.oid=p.prolang WHERE n.nspname='reconforge' AND p.proname=ANY(%s) ORDER BY p.proname""",
        (list(FUNCTIONS),)).fetchall()
    constraints = connection.execute("""SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.oid,true)
        FROM pg_constraint c WHERE c.conrelid IN('reconforge.inventory_quantity_source_guards'::regclass,
        'reconforge.inventory_quantity_source_releases'::regclass) ORDER BY 1,2""").fetchall()
    return {"functions": [tuple(row) for row in functions], "constraints": [tuple(row) for row in constraints]}


@pytest.fixture(scope="module")
def integration_database(baseline_receipt_database: tuple[str, str]) -> Iterator[tuple[str, str]]:
    import psycopg

    with psycopg.connect(baseline_receipt_database[0]) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD
    yield baseline_receipt_database


def test_registered_empty_146_inverse_restores_145_and_reinstalls_exact_native_contract(integration_database: tuple[str, str]) -> None:
    import psycopg

    with psycopg.connect(integration_database[0]) as admin:
        before = _catalog(admin)
        assert admin.execute("SELECT count(*) FROM reconforge.inventory_transfer_sources").fetchone()[0] == 0
    _migrate(integration_database, "downgrade", PREVIOUS)
    with psycopg.connect(integration_database[0]) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PREVIOUS
        assert admin.execute("SELECT to_regclass('reconforge.inventory_transfer_sources')").fetchone()[0] is None
        assert admin.execute("SELECT to_regprocedure('reconforge.inventory_transfer_native_route()')").fetchone()[0] is None
        assert admin.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='reconforge' AND table_name='inventory_quantity_source_guards' AND column_name IN('it1_claim_pin','msp_claim_pin')").fetchone()[0] == 0
    _migrate(integration_database, "upgrade", HEAD)
    with psycopg.connect(integration_database[0]) as admin:
        assert _catalog(admin) == before
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD
        flags = admin.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='reconforge'::regnamespace AND relname=ANY(%s) ORDER BY relname", (list(TABLES),)).fetchall()
        assert len(flags) == 5 and all(enabled and forced for _, enabled, forced in flags)
        triggers = admin.execute("""SELECT c.relname,t.tgname,t.tgdeferrable,t.tginitdeferred FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relnamespace='reconforge'::regnamespace
            AND t.tgname IN('a_inventory_0_transfer_native','inventory_transfer_native_close') ORDER BY 1,2""").fetchall()
        assert len(triggers) == 4
        assert all(deferred and initially for _, name, deferred, initially in triggers if name == "inventory_transfer_native_close")
        names = admin.execute("SELECT tgname FROM pg_trigger WHERE tgrelid='reconforge.inventory_movement_lines'::regclass AND NOT tgisinternal ORDER BY tgname").fetchall()
        assert [row[0] for row in names].index("a_inventory_0_transfer_native") < [row[0] for row in names].index("a_inventory_quantity_custody")


@pytest.fixture(scope="module")
def original_runtime(integration_database: tuple[str, str]) -> ReceiptRuntime:
    return transfer_runtime(integration_database)


def _rows(connection: Any, tenant: str, tables: tuple[str, ...]) -> bytes:
    from psycopg import sql

    records = {name: [row["original"] for row in connection.execute(sql.SQL(
        "SELECT to_jsonb(t) original FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text").format(sql.Identifier(name)),
        (tenant,))] for name in tables}
    return json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture(scope="module")
def ordinary_without_transfer_acl(integration_database: tuple[str, str], original_runtime: ReceiptRuntime) -> Iterator[ReceiptRuntime]:
    import psycopg
    from psycopg import sql

    role = psycopg.conninfo.conninfo_to_dict(integration_database[1])["user"]
    with psycopg.connect(integration_database[0]) as admin:
        flags = admin.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
        assert flags == (False, False)
        for table in TABLES:
            admin.execute(sql.SQL("REVOKE ALL ON reconforge.{} FROM {}").format(sql.Identifier(table), sql.Identifier(role)))
    try:
        yield original_runtime
    finally:
        with psycopg.connect(integration_database[0]) as admin:
            for table in TABLES:
                admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{} TO {}").format(sql.Identifier(table), sql.Identifier(role)))


@pytest.mark.parametrize("field,operation,context", (("movement_number", "insert", ""), ("source_reference", "insert", "IT1-S-malformed"),
                                                    ("movement_number", "update", ""), ("source_reference", "update", "not-a-source")))
def test_reserved_native_escape_refuses_before_private_owner_lookup(ordinary_without_transfer_acl: ReceiptRuntime,
        field: str, operation: str, context: str) -> None:
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb

    runtime = ordinary_without_transfer_acl
    with runtime.actor("maker") as (connection, _, _):
        assert not connection.execute("SELECT has_table_privilege(current_user,'reconforge.inventory_transfer_sources','SELECT') allowed").fetchone()["allowed"]
        before = _rows(connection, runtime.tenant, ("inventory_movements", "inventory_movement_lines", "finance_posting_effects"))
        original = connection.execute("SELECT to_jsonb(m) original FROM reconforge.inventory_movements m WHERE tenant_id=%s ORDER BY id LIMIT 1", (runtime.tenant,)).fetchone()["original"]
        with pytest.raises(psycopg.errors.CheckViolation, match="closed exact table operation") as refused, connection.transaction():
            connection.execute("SELECT set_config('app.inventory_transfer_id',%s,true)", (context,))
            if operation == "insert":
                injected = {**original, "id": uuid4().hex, "status": "Draft", "row_version": 1, field: "it1-direct-sql"}
                connection.execute("INSERT INTO reconforge.inventory_movements SELECT (jsonb_populate_record(NULL::reconforge.inventory_movements,%s)).*", (Jsonb(injected),))
            else:
                connection.execute(sql.SQL("UPDATE reconforge.inventory_movements SET {}=%s WHERE tenant_id=%s AND id=%s").format(sql.Identifier(field)),
                                   ("it1-direct-sql", runtime.tenant, original["id"]))
        assert refused.value.sqlstate == "23514" and refused.value.diag.constraint_name == "inventory_transfer_owner"
        assert _rows(connection, runtime.tenant, ("inventory_movements", "inventory_movement_lines", "finance_posting_effects")) == before


@pytest.mark.parametrize("field", ("id", "entry_number"))
def test_transfer_namespace_cannot_be_financial_header_even_without_private_acl(ordinary_without_transfer_acl: ReceiptRuntime, field: str) -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    runtime = ordinary_without_transfer_acl
    with runtime.actor("maker") as (connection, _, _):
        before = _rows(connection, runtime.tenant, ("finance_entries", "finance_entry_lines", "finance_posting_effects"))
        original = connection.execute("SELECT to_jsonb(h) original FROM reconforge.finance_entries h WHERE tenant_id=%s ORDER BY id LIMIT 1", (runtime.tenant,)).fetchone()["original"]
        injected = {**original, "id": uuid4().hex, "entry_number": "ordinary-test-" + uuid4().hex, field: "it1-financial-escape"}
        with pytest.raises(psycopg.errors.CheckViolation, match="not financial posting sources") as refused, connection.transaction():
            connection.execute("INSERT INTO reconforge.finance_entries SELECT (jsonb_populate_record(NULL::reconforge.finance_entries,%s)).*", (Jsonb(injected),))
        assert refused.value.sqlstate == "23514"
        assert _rows(connection, runtime.tenant, ("finance_entries", "finance_entry_lines", "finance_posting_effects")) == before


def test_ordinary_native_metadata_has_no_private_transfer_dependency(ordinary_without_transfer_acl: ReceiptRuntime) -> None:
    runtime = ordinary_without_transfer_acl
    with runtime.actor("maker") as (connection, _, _):
        old = connection.execute("SELECT id,name FROM reconforge.inventory_items WHERE tenant_id=%s AND item_code='ITEM'", (runtime.tenant,)).fetchone()
        changed = connection.execute("UPDATE reconforge.inventory_items SET name='Ordinary metadata still available' WHERE tenant_id=%s AND id=%s RETURNING name",
                                     (runtime.tenant, old["id"])).fetchone()
        assert changed["name"] == "Ordinary metadata still available"
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.execute("UPDATE reconforge.inventory_items SET name=%s WHERE tenant_id=%s AND id=%s", (old["name"], runtime.tenant, old["id"]))


@pytest.fixture(scope="module")
def msp_originals(integration_database: tuple[str, str]) -> tuple[Any, dict[str, Any], bytes]:
    _migrate(integration_database, "downgrade", PREVIOUS)
    system, request = planning_runtime(integration_database)
    seed_partial_stock(system)
    with system.actor("maker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="146-msp-create", actor=actor)["source"]
    with system.actor("checker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).approve(source["id"], expected_digest=source["source_digest"],
            command_id="146-msp-approve", reason="Original145 approved stock custody", actor=actor)["source"]
        assert len(source["stock_claims"]) == 2
        before = _rows(connection, system.tenant, MSP_TABLES)
    _migrate(integration_database, "upgrade", HEAD)
    return system, source, before


def test_populated_145_to_146_preserves_actual_msp_sealed_requests_responses_and_original_financial_rows(msp_originals: tuple[Any, dict[str, Any], bytes]) -> None:
    system, source, before = msp_originals
    with system.actor("checker") as (connection, _, actor):
        assert PostgresManufacturingSupplyPlanRepository(connection, system.tenant).get(source["id"], actor=actor) == source
        assert _rows(connection, system.tenant, MSP_TABLES) == before
        guards = connection.execute("SELECT owner_namespace,owner_claim_id,msp_claim_pin,it1_claim_pin FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s ORDER BY id", (system.tenant,)).fetchall()
        assert len(guards) == 2
        assert all(row["owner_namespace"] == "MSP1" and row["owner_claim_id"] == row["msp_claim_pin"] and row["it1_claim_pin"] is None for row in guards)


def test_actual_new_msp_claim_cannot_be_registered_as_it1_custody(integration_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg

    system, request = planning_runtime(integration_database)
    seed_partial_stock(system)
    with system.actor("maker") as (connection, _, actor):
        source = PostgresManufacturingSupplyPlanRepository(connection, system.tenant).create(request, command_id="146-cross-kind-create", actor=actor)["source"]
    with system.actor("checker") as (connection, _, actor):
        owner = PostgresManufacturingSupplyPlanRepository(connection, system.tenant)
        before = _rows(connection, system.tenant, MSP_TABLES + ("inventory_quantity_source_guards",))
        execute = connection.execute
        captured: list[str] = []

        def wrong_kind(query: Any, parameters: Any = None, **kwargs: Any) -> Any:
            if isinstance(query, str) and "INSERT INTO reconforge.inventory_quantity_source_guards" in query:
                identifier = parameters[1]
                # The real owner inserted its exact native MSP claim first. No
                # artificial source, directory or privileged role is admitted.
                assert execute("SELECT id FROM reconforge.manufacturing_supply_stock_claims WHERE tenant_id=%s AND id=%s",
                               (system.tenant, identifier)).fetchone()["id"] == identifier
                captured.append(identifier)
                query = query.replace("'MSP1'", "'IT1'")
            return execute(query, parameters, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(connection, "execute", wrong_kind)
            with pytest.raises(FinancePostingError) as refused, connection.transaction():
                owner.approve(source["id"], expected_digest=source["source_digest"], command_id="146-cross-kind-approve",
                              reason="A source kind cannot borrow another native claim", actor=actor)
        assert len(captured) == 1
        assert refused.value.code == "operational_state_conflict"
        cause = refused.value.__cause__
        assert isinstance(cause, psycopg.errors.ForeignKeyViolation)
        assert cause.sqlstate == "23503" and cause.diag.constraint_name == "quantity_it1_claim_pin"
        assert _rows(connection, system.tenant, MSP_TABLES + ("inventory_quantity_source_guards",)) == before
        with connection.transaction(force_rollback=True):
            valid = owner.approve(source["id"], expected_digest=source["source_digest"], command_id="146-cross-kind-positive",
                                  reason="The original MSP namespace still admits its native claim", actor=actor)["source"]
            assert valid["phase"] == 1 and len(valid["stock_claims"]) == 2
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        assert _rows(connection, system.tenant, MSP_TABLES + ("inventory_quantity_source_guards",)) == before


@pytest.mark.parametrize("namespace,constraint", (("IT1", "quantity_it1_claim_pin"), ("MSP1", "quantity_msp_claim_pin")))
def test_missing_or_wrong_kind_claim_cannot_enter_core_directory(msp_originals: tuple[Any, dict[str, Any], bytes], namespace: str, constraint: str) -> None:
    import psycopg

    system, _, _ = msp_originals
    with system.actor("maker") as (connection, _, _):
        before = _rows(connection, system.tenant, ("inventory_quantity_source_guards",))
        guard = connection.execute("SELECT * FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s ORDER BY id LIMIT 1", (system.tenant,)).fetchone()
        # A real receipt identity is neither an IT1 nor an MSP1 stock claim.
        foreign_id = connection.execute("SELECT id FROM reconforge.inventory_receipt_plans WHERE tenant_id=%s ORDER BY id LIMIT 1", (system.tenant,)).fetchone()["id"]
        with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused, connection.transaction():
            connection.execute("""INSERT INTO reconforge.inventory_quantity_source_guards
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,item_id,uom_id,quantity_precision,location_id,quantity_scaled,
                 owner_namespace,owner_claim_id,source_receipt_plan_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL)""",
                (system.tenant, foreign_id, "work", "org", "entity", guard["item_id"], guard["uom_id"], guard["quantity_precision"], guard["location_id"], 1, namespace, foreign_id))
        assert refused.value.sqlstate == "23503" and refused.value.diag.constraint_name == constraint
        assert _rows(connection, system.tenant, ("inventory_quantity_source_guards",)) == before


@pytest.mark.parametrize("namespace,exception,constraint", (("IT1", "namespace", None), ("MSP1", "missing", "quantity_msp_release_pin")))
def test_release_cannot_switch_guard_kind_or_omit_native_owner(msp_originals: tuple[Any, dict[str, Any], bytes], namespace: str, exception: str, constraint: str | None) -> None:
    import psycopg

    system, _, _ = msp_originals
    with system.actor("maker") as (connection, _, _):
        before = _rows(connection, system.tenant, ("inventory_quantity_source_guards", "inventory_quantity_source_releases"))
        guard = connection.execute("SELECT id FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s ORDER BY id LIMIT 1", (system.tenant,)).fetchone()["id"]
        error = psycopg.errors.CheckViolation if exception == "namespace" else psycopg.errors.ForeignKeyViolation
        with pytest.raises(error) as refused, connection.transaction():
            connection.execute("INSERT INTO reconforge.inventory_quantity_source_releases(tenant_id,guard_id,release_id,owner_namespace) VALUES(%s,%s,%s,%s)",
                               (system.tenant, guard, "IT1-R-" + uuid4().hex.upper(), namespace))
        assert refused.value.sqlstate == ("23514" if exception == "namespace" else "23503")
        if constraint:
            assert refused.value.diag.constraint_name == constraint
        else:
            assert "exact finite source namespace" in str(refused.value)
        assert _rows(connection, system.tenant, ("inventory_quantity_source_guards", "inventory_quantity_source_releases")) == before


@pytest.mark.parametrize("table,column,code", (("inventory_items", "organization_id", "ITEM"), ("inventory_warehouses", "legal_entity_id", "MAIN")))
def test_generated_identity_pin_refuses_hidden_source_reinterpretation(msp_originals: tuple[Any, dict[str, Any], bytes], table: str, column: str, code: str) -> None:
    import psycopg
    from psycopg import sql

    system, _, _ = msp_originals
    selected_org = None if table == "inventory_items" else "org"
    with PostgresTenantBoundary(system.factory).transaction(system.tenant, workspace_id="work", organization_id=selected_org) as connection:
        connection.execute("SELECT set_config('app.entity_id','unselected-source-entity',true)")
        assert connection.execute("SELECT count(*) n FROM reconforge.inventory_quantity_source_guards WHERE tenant_id=%s", (system.tenant,)).fetchone()["n"] == 0
        code_column = "item_code" if table == "inventory_items" else "warehouse_code"
        row = connection.execute(sql.SQL("SELECT id,{} FROM reconforge.{} WHERE tenant_id=%s AND {}=%s").format(
            sql.Identifier(column), sql.Identifier(table), sql.Identifier(code_column)), (system.tenant, code)).fetchone()
        assert row is not None and row[column] is not None
        with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused, connection.transaction():
            changed = connection.execute(sql.SQL("UPDATE reconforge.{} SET {}=NULL WHERE tenant_id=%s AND id=%s RETURNING id").format(
                sql.Identifier(table), sql.Identifier(column)), (system.tenant, row["id"])).fetchall()
            assert len(changed) == 1
        assert refused.value.sqlstate == "23503"
        retained = connection.execute(sql.SQL("SELECT {} FROM reconforge.{} WHERE tenant_id=%s AND id=%s").format(
            sql.Identifier(column), sql.Identifier(table)), (system.tenant, row["id"])).fetchone()
        assert retained[column] == row[column]
