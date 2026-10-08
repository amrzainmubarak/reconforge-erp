"""Populated native PostgreSQL browser backup/restore with semantic fingerprints."""
from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime

FINANCIAL_TABLES = (
    "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_receipt_links", "inventory_receipt_commands",
    "inventory_movements", "inventory_movement_lines", "inventory_valuation_documents", "inventory_valuation_input_costs",
    "inventory_valuation_lines", "inventory_cost_layers", "inventory_layer_consumptions", "inventory_valuation_reversals",
    "inventory_valuation_reversal_effects", "finance_entries", "finance_entry_lines", "finance_posting_effects",
    "domain_audit_events", "domain_audit_ledger_state", "outbox_events", "currency_registry_snapshots", "currency_registry_bindings",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def database_snapshot(dsn: str) -> dict[str, Any]:
    """Hash canonical rows and PostgreSQL object definitions without exporting data."""
    with psycopg.connect(dsn) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='reconforge' AND c.relkind='r' ORDER BY c.relname")]
        data = {}
        for table in tables:
            rows = [row[0] for row in connection.execute(sql.SQL(
                "SELECT to_jsonb(t)::text FROM reconforge.{} t ORDER BY to_jsonb(t)::text COLLATE \"C\"").format(sql.Identifier(table)))]
            data[table] = {"rows": len(rows), "sha256": digest(rows)}
        definitions = {
            "relations": "SELECT c.relname,c.relkind,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner),"
                "ARRAY(SELECT a::text FROM unnest(c.relacl) a ORDER BY a::text) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='reconforge' ORDER BY c.relname",
            "columns": "SELECT c.relname,a.attname,a.attnum,format_type(a.atttypid,a.atttypmod),a.attnotnull,"
                "pg_get_expr(d.adbin,d.adrelid),ARRAY(SELECT x::text FROM unnest(a.attacl) x ORDER BY x::text) "
                "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
                "WHERE n.nspname='reconforge' AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum",
            "functions": "SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid),"
                "p.prosecdef,p.proconfig,pg_get_userbyid(p.proowner),ARRAY(SELECT a::text FROM unnest(p.proacl) a ORDER BY a::text) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='reconforge' "
                "ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)",
            "triggers": "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='reconforge' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
            "constraints": "SELECT c.relname,k.conname,k.convalidated,pg_get_constraintdef(k.oid) FROM pg_constraint k "
                "JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='reconforge' ORDER BY c.relname,k.conname",
            "policies": "SELECT c.relname,p.polname,p.polpermissive,p.polcmd,"
                "ARRAY(SELECT CASE WHEN r=0 THEN 'public' ELSE pg_get_userbyid(r) END FROM unnest(p.polroles) r ORDER BY r),"
                "pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid) FROM pg_policy p "
                "JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='reconforge' ORDER BY c.relname,p.polname",
            "indexes": "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='reconforge' ORDER BY tablename,indexname",
            "schema_acl": "SELECT nspname,pg_get_userbyid(nspowner),ARRAY(SELECT a::text FROM unnest(nspacl) a ORDER BY a::text) "
                "FROM pg_namespace WHERE nspname='reconforge'",
        }
        objects = {}
        for kind, statement in definitions.items():
            rows = connection.execute(statement).fetchall()
            objects[kind] = {"count": len(rows), "sha256": digest(rows)}
        head = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        protected = connection.execute(
            "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='reconforge' AND c.relname=ANY(%s) ORDER BY c.relname", (list(FINANCIAL_TABLES),)).fetchall()
        require(len(protected) == len(FINANCIAL_TABLES), "Native restore invariant failed.")
        require(all(row[1] and row[2] for row in protected), "Native restore invariant failed.")
        return {"tables": data, "objects": objects, "head": head, "forced_rls_financial_tables": len(protected)}


def verified_effects(runtime: ReceiptRuntime) -> dict[str, str]:
    """Authenticate the restored persisted human and verify complete backing rows."""
    with runtime.actor("checker") as (connection, repository, actor):
        identifiers = [row["id"] for row in connection.execute(
            "SELECT id FROM reconforge.inventory_receipt_plans WHERE tenant_id=%s ORDER BY id COLLATE \"C\"", (runtime.tenant,))]
        require(len(identifiers) == 2, "Native restore invariant failed.")
        effects = {identifier: digest(repository.get_effect(identifier, actor=actor)) for identifier in identifiers}
        return effects


def verify_native_browser_restore(runtime: ReceiptRuntime, container: str,
                                  persisted: Callable[[ReceiptRuntime], dict[str, object]]) -> dict[str, object]:
    database = "gfo_browser_restore_" + uuid4().hex[:12]
    source_effects = verified_effects(runtime)
    before = database_snapshot(runtime.admin_dsn)
    require(before["head"] == "0108_pg_receipt_admission", "Native restore invariant failed.")
    dump = subprocess.run(["docker", "exec", container, "pg_dump", "--username=postgres", "--dbname=postgres", "--format=custom"],
                          capture_output=True, check=True, timeout=120)  # nosec B603 B607
    require(dump.stdout.startswith(b"PGDMP"), "Native restore invariant failed.")
    restored_admin_dsn = psycopg.conninfo.make_conninfo(runtime.admin_dsn, dbname=database)
    restored_app_dsn = psycopg.conninfo.make_conninfo(runtime.factory.settings.dsn, dbname=database)
    created = False
    try:
        with psycopg.connect(runtime.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
            created = True
        subprocess.run(["docker", "exec", "-i", container, "pg_restore", "--username=postgres", "--exit-on-error", f"--dbname={database}"],
                       input=dump.stdout, capture_output=True, check=True, timeout=180)  # nosec B603 B607
        after = database_snapshot(restored_admin_dsn)
        require(before == after, "Native restore changed table contents, definitions, RLS, ACL or migration head.")
        factory = PostgresConnectionFactory(PostgresSettings(dsn=restored_app_dsn, require_tls=False))
        restored = ReceiptRuntime(factory, restored_admin_dsn, runtime.tenant, runtime.password)
        with psycopg.connect(restored_app_dsn) as connection:
            flags = list(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone())
            require(flags == [False, False], "Native restore invariant failed.")
            require(connection.execute("SELECT count(*) FROM reconforge.inventory_receipt_plans").fetchone()[0] == 0, "Native restore invariant failed.")
        with PostgresTenantBoundary(factory).transaction(runtime.tenant, workspace_id="foreign", organization_id="org", legal_entity_id="entity") as connection:
            require(connection.execute("SELECT count(*) n FROM reconforge.inventory_receipt_plans").fetchone()["n"] == 0, "Native restore invariant failed.")
        restored_effects = verified_effects(restored)
        require(source_effects == restored_effects, "Native restore invariant failed.")
        postconditions = persisted(restored)
        reread = database_snapshot(restored_admin_dsn)
        require(all(after["tables"][table] == reread["tables"][table] for table in FINANCIAL_TABLES), "Native restore invariant failed.")
        return {"status": "passed", "format": "native-custom", "dump_sha256": hashlib.sha256(dump.stdout).hexdigest(),
                "all_table_snapshot_sha256": digest(before["tables"]), "objects": before["objects"],
                "table_count": len(before["tables"]), "table_row_hashes": before["tables"],
                "forced_rls_financial_tables": before["forced_rls_financial_tables"], "head": before["head"],
                "verified_original_inverse_effect_hashes": source_effects, "role_privileges": flags,
                "raw_unscoped_and_foreign_workspace_concealed": True, "persisted_effects": postconditions}
    finally:
        if created:
            with psycopg.connect(runtime.admin_dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
                require(admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None, "Native restore invariant failed.")
