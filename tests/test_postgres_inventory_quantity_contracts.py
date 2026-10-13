"""Accepted legacy Core coordination remains subordinate to exact native parents."""
from __future__ import annotations

import re
from typing import Any

import pytest

from reconforge.infrastructure.postgres_inventory_quantity_contracts import DOWNGRADE_SQL, UPGRADE_SQL
from tests.test_postgres_inventory_scope import inventory_scope_database as _inventory_scope_database
from tests.test_postgres_inventory_scope import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

inventory_scope_database = _inventory_scope_database
isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn


def test_generic_quantity_coordination_retains_original_strict_owner_contracts() -> None:
    assert "SECURITY DEFINER" not in UPGRADE_SQL
    assert "SECURITY INVOKER" in UPGRADE_SQL
    assert UPGRADE_SQL.count("CREATE OR REPLACE FUNCTION") == 2
    assert UPGRADE_SQL.count("ALTER POLICY") == 1
    assert "ON reconforge.inventory_quantity_claim_gates" in UPGRADE_SQL
    assert not re.search(r"\b(?:GRANT|DISABLE|DELETE|DROP TABLE|set_config)\b", UPGRADE_SQL, re.I)
    assert "Legacy inventory coordination requires compatible contracts or restore" in DOWNGRADE_SQL


def test_original_core_legacy_pool_and_direct_sql_hierarchy_isolation(inventory_scope_database: dict[str, Any]) -> None:
    import psycopg

    db = inventory_scope_database
    with db["boundary"].transaction("inventory_scope") as connection:
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
        connection.execute("SELECT reconforge.touch_inventory_quantity_claim_gate('inventory_scope','shared','legacy','item_legacy','location_legacy')")
        assert [tuple(row) for row in connection.execute("SELECT pool_kind,version FROM reconforge.inventory_quantity_claim_gates ORDER BY pool_kind")] == [("FIFO", 1), ("Location", 1)]
        connection.execute("SELECT reconforge.touch_inventory_quantity_claim_gate('inventory_scope','shared','legacy','item_legacy','location_legacy')")
        assert [tuple(row) for row in connection.execute("SELECT version FROM reconforge.inventory_quantity_claim_gates ORDER BY pool_kind")] == [(2,), (2,)]
        # A raw gate cannot forge an entity's organization or workspace even in
        # the accepted tenant-unbound inventory mode.
        for workspace, org, entity in (("shared", "a", "legacy"), ("other", "legacy", "legacy"), ("shared", "legacy", "a1")):
            assert connection.execute("SELECT reconforge.inventory_quantity_coordination_scope('inventory_scope',%s,%s,%s)", (workspace, org, entity)).fetchone()[0] is False
            with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.CheckViolation)), connection.transaction():
                connection.execute("INSERT INTO reconforge.inventory_quantity_claim_gates(tenant_id,workspace_id,organization_id,legal_entity_id,item_id,pool_kind,location_id,version) VALUES('inventory_scope',%s,%s,%s,'item_legacy','FIFO','',1)", (workspace, org, entity))
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("SELECT reconforge.touch_inventory_quantity_claim_gate('inventory_scope','shared','legacy','item_legacy','location_a1')")
    for tenant, dimensions in (("inventory_foreign", {}), ("inventory_scope", {"workspace_id": "shared", "organization_id": "a", "legal_entity_id": "a1"}), ("inventory_scope", {"workspace_id": "shared", "organization_id": "legacy", "legal_entity_id": "legacy"})):
        with db["boundary"].transaction(tenant, **dimensions) as connection, pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("SELECT reconforge.inventory_quantity_source_pool_lock('inventory_scope','shared','legacy','item_legacy')")
    with db["boundary"].transaction("inventory_scope", workspace_id="shared", organization_id="a", legal_entity_id="a1") as connection:
        connection.execute("SELECT set_config('app.entity_id','a2',true)")
        assert connection.execute("SELECT reconforge.inventory_quantity_coordination_scope('inventory_scope','shared','a','a1')").fetchone()[0] is False


def test_quantity_coordination_retains_current_caller_acl(inventory_scope_database: dict[str, Any]) -> None:
    import os

    import psycopg
    from psycopg import sql

    db = inventory_scope_database
    role = sql.Identifier(psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])["user"])
    with psycopg.connect(db["admin"]) as admin:
        assert admin.execute("SELECT bool_or(prosecdef) FROM pg_proc WHERE pronamespace='reconforge'::regnamespace AND proname IN ('inventory_quantity_coordination_scope','inventory_quantity_source_pool_lock','touch_inventory_quantity_claim_gate')").fetchone()[0] is False
        admin.execute(sql.SQL("REVOKE SELECT ON reconforge.inventory_quantity_claim_gates FROM {}").format(role))
    try:
        with db["boundary"].transaction("inventory_scope") as connection, pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("SELECT reconforge.inventory_quantity_source_pool_lock('inventory_scope','shared','legacy','item_legacy')")
    finally:
        with psycopg.connect(db["admin"]) as admin:
            admin.execute(sql.SQL("GRANT SELECT ON reconforge.inventory_quantity_claim_gates TO {}").format(role))


def test_quantity_contract_empty_inverse_and_populated_legacy_refusal(inventory_scope_database: dict[str, Any]) -> None:
    import psycopg

    db = inventory_scope_database
    query = "SELECT proname,pg_get_functiondef(oid) FROM pg_proc WHERE pronamespace='reconforge'::regnamespace AND proname IN ('inventory_quantity_guard_birth','inventory_quantity_gate_guard','inventory_quantity_release_close') ORDER BY proname"
    with psycopg.connect(db["admin"]) as admin:
        before = admin.execute(query).fetchall()
        assert before
        admin.execute(DOWNGRADE_SQL)
        assert admin.execute("SELECT to_regprocedure('reconforge.inventory_quantity_coordination_scope(text,text,text,text)')").fetchone()[0] is None
        admin.execute(UPGRADE_SQL)
        assert admin.execute(query).fetchall() == before
    with db["boundary"].transaction("inventory_scope") as connection:
        connection.execute("SELECT reconforge.inventory_quantity_source_pool_lock('inventory_scope','shared','legacy','item_legacy')")
    with psycopg.connect(db["admin"]) as admin:
        with pytest.raises(psycopg.errors.CheckViolation, match="Legacy inventory coordination"), admin.transaction():
            admin.execute(DOWNGRADE_SQL)
        assert admin.execute(query).fetchall() == before
        assert admin.execute("SELECT to_regprocedure('reconforge.inventory_quantity_coordination_scope(text,text,text,text)')").fetchone()[0] is not None
        assert admin.execute("SELECT version FROM reconforge.inventory_quantity_claim_gates WHERE organization_id='legacy'").fetchall() == [(1,)]
