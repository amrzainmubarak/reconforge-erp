"""Native inventory hierarchy safety under ordinary PostgreSQL roles.

The disposable fixture contains legal Draft inventory graphs, plus intentionally
misbound retained rows written by the administration role. No production trigger,
RLS policy, or financial history is disabled or rewritten by these tests.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_inventory_scope import (
    DOWNGRADE_SQL,
    INVENTORY_SCOPE_FUNCTION_SIGNATURES,
    INVENTORY_SCOPE_TABLES,
    UPGRADE_SQL,
    install_postgres_inventory_scope,
)
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn


def test_inventory_scope_is_additive_invoker_and_never_changes_context_or_history() -> None:
    assert len(INVENTORY_SCOPE_TABLES) == len(set(INVENTORY_SCOPE_TABLES)) == 9
    assert len(INVENTORY_SCOPE_FUNCTION_SIGNATURES) == 10
    assert UPGRADE_SQL.count("SECURITY INVOKER") == 10
    assert UPGRADE_SQL.count("STABLE") == 10
    assert "SECURITY DEFINER" not in UPGRADE_SQL
    assert "SET search_path=pg_catalog" in UPGRADE_SQL
    assert not re.search(r"\b(?:INSERT INTO|UPDATE reconforge|DELETE FROM|set_config|RESET|REVOKE)\b", UPGRADE_SQL, re.I)
    assert "DROP TABLE" not in DOWNGRADE_SQL
    for table in INVENTORY_SCOPE_TABLES:
        assert f"ALTER TABLE reconforge.{table} FORCE ROW LEVEL SECURITY" in UPGRADE_SQL
        assert f"CREATE POLICY inventory_hierarchy ON reconforge.{table} AS RESTRICTIVE" in UPGRADE_SQL
        assert f"DROP POLICY inventory_hierarchy ON reconforge.{table};" in DOWNGRADE_SQL
    for signature in INVENTORY_SCOPE_FUNCTION_SIGNATURES:
        assert f"DROP FUNCTION reconforge.{signature};" in DOWNGRADE_SQL


def test_inventory_scope_parent_graph_has_no_policy_recursion() -> None:
    expected_parents = {
        "inventory_movements": set(),
        "inventory_movement_lines": {"inventory_movements"},
        "inventory_valuation_documents": {"inventory_movements"},
        "inventory_valuation_input_costs": {"inventory_valuation_documents", "inventory_movement_lines"},
        "inventory_valuation_lines": {"inventory_valuation_documents", "inventory_movement_lines"},
        "inventory_cost_layers": {"inventory_valuation_lines", "inventory_valuation_documents"},
        "inventory_layer_consumptions": {"inventory_valuation_lines", "inventory_valuation_documents", "inventory_cost_layers"},
        "inventory_valuation_reversals": {"inventory_movements", "inventory_valuation_documents"},
        "inventory_valuation_reversal_effects": {"inventory_valuation_reversals", "inventory_valuation_lines", "inventory_cost_layers", "inventory_layer_consumptions"},
    }
    functions = dict(re.findall(r"CREATE FUNCTION reconforge\.(\w+)\([^$]+?AS \$inv\$(.*?)\$inv\$;", UPGRADE_SQL, re.S))
    policies = re.findall(r"CREATE POLICY inventory_hierarchy ON reconforge\.(\w+).*?USING\(reconforge\.(\w+)\(", UPGRADE_SQL, re.S)
    def references(name: str, visited: frozenset[str] = frozenset()) -> set[str]:
        assert name not in visited, f"recursive invoker helper: {name}"
        body = functions[name]
        tables = set(re.findall(r"(?:FROM|JOIN) reconforge\.(inventory_\w+)", body)) & set(INVENTORY_SCOPE_TABLES)
        for child in set(re.findall(r"reconforge\.(inventory_scope_\w+)\(", body)):
            tables |= references(child, visited | {name})
        return tables
    for table, helper in policies:
        assert references(helper) == expected_parents[table]
        assert table not in references(helper)
    assert len(policies) == 9


def test_inventory_scope_rejects_alias_mismatch_and_custody_uses_original_parents() -> None:
    assert "ce IS DISTINCT FROM alias_entity" in UPGRADE_SQL
    assert "ce IS NOT NULL AND co IS NULL" in UPGRADE_SQL
    assert "org.application_workspace_id=w" in UPGRADE_SQL
    assert "reference_item.workspace_id=movement.workspace_id" in UPGRADE_SQL
    assert "reference_item.organization_id IS NULL" in UPGRADE_SQL
    assert "reference_uom.workspace_id=movement.workspace_id" in UPGRADE_SQL
    assert "reference_lot.item_id=item" in UPGRADE_SQL
    assert "line.movement_id=document.movement_id" in UPGRADE_SQL
    assert "layer.legal_entity_id=document.legal_entity_id" in UPGRADE_SQL
    assert "line.valuation_document_id=reversal.original_valuation_document_id" in UPGRADE_SQL
    assert "consumption.valuation_line_id=v AND consumption.cost_layer_id=l" in UPGRADE_SQL


def test_inventory_scope_install_executes_one_cohesive_sql_statement() -> None:
    class Connection:
        def __init__(self) -> None:
            self.statements: list[str] = []
        def execute(self, value: str) -> None:
            self.statements.append(value)
    connection = Connection()
    install_postgres_inventory_scope(connection)
    assert connection.statements == [UPGRADE_SQL]


def _seed_graph(admin: Any, tenant: str, label: str, workspace: str, org: str, entity: str) -> None:
    """Draft native graph with real keys; ordinary invoker tests do all probes."""
    admin.execute("INSERT INTO reconforge.inventory_units_of_measure(tenant_id,id,workspace_id,uom_code,name) VALUES(%s,%s,%s,%s,'Synthetic unit')", (tenant, f"uom_{label}", workspace, label.upper()))
    admin.execute("INSERT INTO reconforge.inventory_items(tenant_id,id,workspace_id,organization_id,item_code,name,uom_id) VALUES(%s,%s,%s,%s,%s,'Synthetic item',%s)", (tenant, f"item_{label}", workspace, org, label.upper(), f"uom_{label}"))
    admin.execute("INSERT INTO reconforge.inventory_warehouses(tenant_id,id,workspace_id,organization_id,legal_entity_id,warehouse_code,name) VALUES(%s,%s,%s,%s,%s,%s,'Synthetic warehouse')", (tenant, f"warehouse_{label}", workspace, org, entity, label.upper()))
    admin.execute("INSERT INTO reconforge.inventory_locations(tenant_id,id,warehouse_id,location_code,name) VALUES(%s,%s,%s,'STOCK','Synthetic stock')", (tenant, f"location_{label}", f"warehouse_{label}"))
    admin.execute("INSERT INTO reconforge.inventory_lots(tenant_id,id,workspace_id,organization_id,item_id,lot_serial_code,tracking_type) VALUES(%s,%s,%s,%s,%s,'LOT','Lot')", (tenant, f"lot_{label}", workspace, org, f"item_{label}"))
    admin.execute("INSERT INTO reconforge.finance_charts(tenant_id,id,workspace_id,organization_code,chart_code,name,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,'Synthetic','2026-07-01','2026-07-01')", (tenant, f"chart_{label}", workspace, org.upper(), label.upper()))
    admin.execute("INSERT INTO reconforge.finance_accounts(tenant_id,id,workspace_id,chart_id,account_code,name,account_type,normal_balance,allow_posting,allow_manual_posting,reconciliation_required,active,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,'Synthetic','Asset','Debit',TRUE,TRUE,FALSE,TRUE,'2026-07-01','2026-07-01')", (tenant, f"account_{label}", workspace, f"chart_{label}", label.upper()))
    admin.execute("INSERT INTO reconforge.finance_journals(tenant_id,id,workspace_id,chart_id,organization_code,journal_code,name,currency_code,journal_type,active,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,'Synthetic','USD','General',TRUE,'2026-07-01','2026-07-01')", (tenant, f"journal_{label}", workspace, f"chart_{label}", org.upper(), label.upper()))
    admin.execute("INSERT INTO reconforge.inventory_valuation_policies(tenant_id,id,workspace_id,organization_id,legal_entity_id,policy_code,currency_code,finance_journal_id,receipt_clearing_account_id,cogs_account_id,adjustment_account_id,created_by) VALUES(%s,%s,%s,%s,%s,'FIFO','USD',%s,%s,%s,%s,'maker')", (tenant, f"policy_{label}", workspace, org, entity, f"journal_{label}", f"account_{label}", f"account_{label}", f"account_{label}"))
    for kind, direction in (("in", "Inbound"), ("out", "Outbound"), ("reverse", "Inbound")):
        movement = f"movement_{label}_{kind}"
        admin.execute("INSERT INTO reconforge.inventory_movements(tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,movement_number,movement_type,movement_date,description,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'2026-07-02','Synthetic','maker')", (tenant, movement, workspace, org, entity, f"period_{workspace}", movement.upper(), "Delivery" if kind == "out" else "Receipt"))
        admin.execute("INSERT INTO reconforge.inventory_movement_lines(tenant_id,id,movement_id,line_number,item_id,uom_id,from_location_id,to_location_id,quantity_scaled,quantity_precision) VALUES(%s,%s,%s,1,%s,%s,%s,%s,100,0)", (tenant, f"movement_line_{label}_{kind}", movement, f"item_{label}", f"uom_{label}", f"location_{label}" if kind == "out" else None, None if kind == "out" else f"location_{label}"))
        if kind == "reverse":
            continue
        admin.execute("INSERT INTO reconforge.inventory_valuation_documents(tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,movement_id,policy_id,valuation_number,valuation_date,currency_code,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'2026-07-02','USD','maker')", (tenant, f"document_{label}_{kind}", workspace, org, entity, f"period_{workspace}", movement, f"policy_{label}", f"VALUE_{label}_{kind}".upper()))
        if kind == "in":
            admin.execute("INSERT INTO reconforge.inventory_valuation_input_costs(tenant_id,id,valuation_document_id,movement_line_id,total_cost_minor) VALUES(%s,%s,%s,%s,1000)", (tenant, f"input_{label}", f"document_{label}_in", f"movement_line_{label}_in"))
        admin.execute("INSERT INTO reconforge.inventory_valuation_lines(tenant_id,id,valuation_document_id,movement_line_id,line_number,flow_direction,item_id,uom_id,quantity_scaled,quantity_precision,value_minor,inventory_account_id,offset_account_id) VALUES(%s,%s,%s,%s,1,%s,%s,%s,100,0,1000,%s,%s)", (tenant, f"valuation_line_{label}_{kind}", f"document_{label}_{kind}", f"movement_line_{label}_{kind}", direction, f"item_{label}", f"uom_{label}", f"account_{label}", f"account_{label}"))
        if kind == "in":
            admin.execute("INSERT INTO reconforge.inventory_cost_layers(tenant_id,id,workspace_id,source_valuation_line_id,legal_entity_id,item_id,uom_id,quantity_precision,original_quantity_scaled,remaining_quantity_scaled,original_value_minor,remaining_value_minor,currency_code) VALUES(%s,%s,%s,%s,%s,%s,%s,0,100,100,1000,1000,'USD')", (tenant, f"layer_{label}", workspace, f"valuation_line_{label}_in", entity, f"item_{label}", f"uom_{label}"))
    admin.execute("INSERT INTO reconforge.inventory_layer_consumptions(tenant_id,id,workspace_id,valuation_line_id,cost_layer_id,quantity_scaled,value_minor) VALUES(%s,%s,%s,%s,%s,100,1000)", (tenant, f"consumption_{label}", workspace, f"valuation_line_{label}_out", f"layer_{label}"))
    admin.execute("UPDATE reconforge.inventory_cost_layers SET remaining_quantity_scaled=0,remaining_value_minor=0 WHERE tenant_id=%s AND id=%s", (tenant, f"layer_{label}"))
    admin.execute("INSERT INTO reconforge.inventory_valuation_reversals(tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,original_valuation_document_id,reversal_movement_id,reversal_number,reversal_date,currency_code,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'2026-07-02','USD','maker')", (tenant, f"reversal_{label}", workspace, org, entity, f"period_{workspace}", f"document_{label}_out", f"movement_{label}_reverse", label.upper()))
    admin.execute("INSERT INTO reconforge.inventory_valuation_reversal_effects(tenant_id,id,reversal_id,original_valuation_line_id,original_consumption_id,cost_layer_id,effect_type,quantity_scaled,value_minor) VALUES(%s,%s,%s,%s,%s,%s,'Restore',100,1000)", (tenant, f"effect_{label}", f"reversal_{label}", f"valuation_line_{label}_out", f"consumption_{label}", f"layer_{label}"))


@pytest.fixture
def inventory_scope_database(isolated_postgres_migration_dsn: str) -> Iterator[dict[str, Any]]:
    import psycopg
    from alembic.config import Config

    from alembic import command

    dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("requires a nonowner PostgreSQL application DSN")
    config = Config(str(Path("alembic.ini").resolve()))
    command.upgrade(config, "head")
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn, autocommit=True) as admin:
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
        if admin.execute("SELECT to_regprocedure('reconforge.inventory_scope_unbound(text)')").fetchone()[0] is None:
            install_postgres_inventory_scope(admin)
        for tenant in ("inventory_scope", "inventory_foreign"):
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,'Synthetic')", (tenant,))
            admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'USD','Synthetic',2)", (tenant,))
            for workspace in ("shared", "other"):
                admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)", (tenant, workspace, workspace))
                admin.execute("INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES(%s,%s,%s,'2026-07-01','2026-07-31',2026,7,%s)", (tenant, f"period_{workspace}", workspace, workspace))
            for org, workspace in (("a", "shared"), ("b", "shared"), ("c", "other"), ("legacy", "shared")):
                admin.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES(%s,%s,%s,%s,'USD',%s)", (tenant, org, org.upper(), org, None if org == "legacy" else workspace))
                admin.execute("INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES(%s,%s,%s)", (tenant, workspace, org))
            for entity, org in (("a1", "a"), ("a2", "a"), ("b1", "b"), ("c1", "c"), ("legacy", "legacy")):
                admin.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,%s,%s,%s,%s,'USD')", (tenant, entity, org, entity.upper(), entity))
                _seed_graph(admin, tenant, entity, "other" if org == "c" else "shared", org, entity)
            # The legacy organization was inserted with no authoritative
            # convenience workspace. Retained identity guards are never bypassed.
    factory = PostgresConnectionFactory(PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**params), require_tls=False))
    yield {"factory": factory, "boundary": PostgresTenantBoundary(factory), "admin": isolated_postgres_migration_dsn}


def _scope(connection: Any) -> tuple[Any, ...]:
    return tuple(connection.execute("SELECT current_setting('app.tenant_id',true),current_setting('app.workspace_id',true),current_setting('app.organization_id',true),current_setting('app.legal_entity_id',true),current_setting('app.entity_id',true)").fetchone())


def _ids(connection: Any, table: str) -> set[str]:
    from psycopg import sql

    return {row[0] for row in connection.execute(sql.SQL("SELECT id FROM reconforge.{} ORDER BY id").format(sql.Identifier(table)))}


def test_live_inventory_scope_hides_every_native_child_and_preserves_unbound(inventory_scope_database: dict[str, Any]) -> None:
    db = inventory_scope_database
    with db["boundary"].transaction("inventory_scope") as connection:
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
        before = _scope(connection)
        unbound = {table: _ids(connection, table) for table in INVENTORY_SCOPE_TABLES}
        assert all(any("legacy" in identifier for identifier in ids) for ids in unbound.values())
        assert _scope(connection) == before
    with db["boundary"].transaction("inventory_scope", workspace_id="shared", organization_id="a", legal_entity_id="a1") as connection:
        before = _scope(connection)
        for table in INVENTORY_SCOPE_TABLES:
            ids = _ids(connection, table)
            assert ids and all("_a1" in identifier for identifier in ids), (table, ids)
        assert _scope(connection) == before
    for dimensions, visible_labels in (({"workspace_id": "shared"}, ("a1", "a2", "b1")), ({"organization_id": "a"}, ("a1", "a2")), ({"workspace_id": "other", "organization_id": "c", "legal_entity_id": "c1"}, ("c1",))):
        with db["boundary"].transaction("inventory_scope", **dimensions) as connection:
            for table in INVENTORY_SCOPE_TABLES:
                ids = _ids(connection, table)
                assert ids and all(any(f"_{label}" in identifier for label in visible_labels) for identifier in ids), (dimensions, table, ids)
                assert all(any(f"_{label}" in identifier for identifier in ids) for label in visible_labels), (dimensions, table, ids)
    with db["boundary"].transaction("inventory_foreign", workspace_id="shared", organization_id="a", legal_entity_id="a1") as connection:
        assert connection.execute("SELECT reconforge.inventory_scope_header('inventory_scope','shared','a','a1')").fetchone()[0] is False
    with db["boundary"].transaction("inventory_scope", workspace_id="shared", organization_id="a", legal_entity_id="a1") as connection:
        connection.execute("SELECT set_config('app.entity_id','a2',true)")
        before = _scope(connection)
        assert all(_ids(connection, table) == set() for table in INVENTORY_SCOPE_TABLES)
        assert _scope(connection) == before


def test_live_inventory_scope_rejects_raw_parent_and_reference_laundering(inventory_scope_database: dict[str, Any]) -> None:
    import psycopg

    db = inventory_scope_database
    with db["boundary"].transaction("inventory_scope", workspace_id="shared", organization_id="a", legal_entity_id="a1") as connection:
        before = _scope(connection)
        for index, (item, uom, location, lot) in enumerate((("item_c1", "uom_a1", "location_a1", None), ("item_a1", "uom_c1", "location_a1", None), ("item_a1", "uom_a1", "location_c1", None), ("item_a1", "uom_a1", "location_a1", "lot_c1"))):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute("INSERT INTO reconforge.inventory_movement_lines(tenant_id,id,movement_id,line_number,item_id,uom_id,to_location_id,inventory_lot_id,quantity_scaled,quantity_precision) VALUES('inventory_scope',%s,'movement_a1_in',%s,%s,%s,%s,%s,1,0)", (f"hostile_{index}", index + 2, item, uom, location, lot))
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("INSERT INTO reconforge.inventory_movements(tenant_id,id,workspace_id,organization_id,legal_entity_id,period_id,movement_number,movement_type,movement_date,description,created_by) VALUES('inventory_scope','hostile_parent','shared','c','c1','period_shared','HOSTILE','Receipt','2026-07-02','Synthetic','maker')")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("INSERT INTO reconforge.inventory_valuation_input_costs(tenant_id,id,valuation_document_id,movement_line_id,total_cost_minor) VALUES('inventory_scope','hostile_input','document_a1_in','movement_line_a2_in',1)")
        for statement in (
            "SELECT reconforge.inventory_scope_valuation('inventory_scope','shared','a','a1','movement_a2_in')",
            "SELECT reconforge.inventory_scope_valuation_line('inventory_scope','document_a1_in','movement_line_a2_in')",
            "SELECT reconforge.inventory_scope_layer('inventory_scope','other','a1','valuation_line_a1_in')",
            "SELECT reconforge.inventory_scope_layer('inventory_scope','shared','a2','valuation_line_a1_in')",
            "SELECT reconforge.inventory_scope_consumption('inventory_scope','shared','valuation_line_a1_out','layer_a2')",
            "SELECT reconforge.inventory_scope_reversal('inventory_scope','shared','a','a1','document_a2_out','movement_a1_reverse')",
            "SELECT reconforge.inventory_scope_reversal_effect('inventory_scope','reversal_a1','valuation_line_a1_out','consumption_a2','layer_a1')",
        ):
            assert connection.execute(statement).fetchone()[0] is False
        assert connection.execute("UPDATE reconforge.inventory_movements SET description='Blocked' WHERE tenant_id='inventory_scope' AND id='movement_c1_in'").rowcount == 0
        assert _scope(connection) == before


def test_live_inventory_scope_helpers_retain_caller_table_acl(inventory_scope_database: dict[str, Any]) -> None:
    import psycopg

    db = inventory_scope_database
    params = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("REVOKE SELECT ON reconforge.inventory_movements FROM {}").format(role))
    try:
        with db["boundary"].transaction("inventory_scope") as connection:
            before = _scope(connection)
            assert connection.execute("SELECT count(*) FROM reconforge.inventory_cost_layers").fetchone()[0] == 5
            assert connection.execute("SELECT reconforge.inventory_scope_movement_line('inventory_scope','movement_a1_in',NULL,'location_a1','item_a1','uom_a1',NULL)").fetchone()[0] is True
            assert _scope(connection) == before
        with (
            db["boundary"].transaction("inventory_scope", workspace_id="shared", organization_id="a", legal_entity_id="a1") as connection,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            connection.transaction(),
        ):
            connection.execute("SELECT reconforge.inventory_scope_movement_line('inventory_scope','movement_a1_in',NULL,'location_a1','item_a1','uom_a1',NULL)")
    finally:
        with psycopg.connect(db["admin"], autocommit=True) as admin:
            admin.execute(psycopg.sql.SQL("GRANT SELECT ON reconforge.inventory_movements TO {}").format(role))
