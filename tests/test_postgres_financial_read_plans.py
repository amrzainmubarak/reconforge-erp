"""Native authority parity through invoker plan boundaries and rollback."""
from __future__ import annotations

from contextlib import closing
from typing import Any

import pytest

from reconforge.infrastructure.postgres import set_local_tenant_scope
from reconforge.infrastructure.postgres_financial_read_plans import (
    POSTGRES_FINANCIAL_READ_PLANS_ROLLBACK_SQL,
    POSTGRES_FINANCIAL_READ_PLANS_SQL,
)
from tests.test_postgres_finance_scope import finance_database, isolated_postgres_migration_dsn

__all__ = ["finance_database", "isolated_postgres_migration_dsn"]


def _rows(connection: Any) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    return tuple((row[0], row[1]) for row in connection.execute(
        "SELECT id,entry_id FROM reconforge.finance_entry_lines ORDER BY id", prepare=True).fetchall()), tuple(
        (row[0], row[1], row[2]) for row in connection.execute(
            "SELECT entry_line_id,dimension_id,dimension_value_id FROM reconforge.finance_entry_line_dimensions ORDER BY 1,2",
            prepare=True).fetchall())


def test_read_plan_visibility_matches_original_policies_across_reused_scopes(finance_database: dict[str, Any]) -> None:
    import psycopg

    db = finance_database
    scopes = [
        {"tenant_id": "finance_scope"},
        {"tenant_id": "finance_scope", "workspace_id": "shared"},
        {"tenant_id": "finance_scope", "organization_id": "org_a", "workspace_id": "shared"},
        {"tenant_id": "finance_scope", "organization_id": "org_a", "workspace_id": "shared", "legal_entity_id": "entity_a1"},
        {"tenant_id": "finance_scope", "organization_id": "org_b", "workspace_id": "shared", "legal_entity_id": "entity_b1"},
        {"tenant_id": "finance_scope", "workspace_id": "other"},
        {"tenant_id": "no_finance_tenant"},
    ]
    snapshots = []
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        original_write = admin.execute("SELECT tablename,with_check FROM pg_policies WHERE policyname='finance_hierarchy' ORDER BY tablename").fetchall()
        function_flags = admin.execute("SELECT proname,prosecdef,provolatile,proisstrict,proconfig FROM pg_proc JOIN pg_namespace n ON n.oid=pronamespace WHERE n.nspname='reconforge' AND proname IN ('finance_entry_read_visible','finance_line_read_visible') ORDER BY proname").fetchall()
        assert len(function_flags) == 2
        assert all(row[1:4] == (False, "s", True) and row[4] == ["search_path=pg_catalog"] for row in function_flags)
    # Repeat the exact same driver connection; a retained function plan must
    # evaluate fresh transaction-local authority, including a narrowed entity.
    with closing(db["factory"].connect()) as connection:
        for migration_sql in (None, POSTGRES_FINANCIAL_READ_PLANS_ROLLBACK_SQL, POSTGRES_FINANCIAL_READ_PLANS_SQL):
            if migration_sql:
                with psycopg.connect(db["admin"], autocommit=True) as admin:
                    admin.execute(migration_sql)
                    assert admin.execute("SELECT tablename,with_check FROM pg_policies WHERE policyname='finance_hierarchy' ORDER BY tablename").fetchall() == original_write
            observed = []
            for scope in scopes:
                with connection.transaction():
                    set_local_tenant_scope(connection, **scope)
                    observed.append(_rows(connection))
            snapshots.append(observed)
        assert snapshots[0] == snapshots[1] == snapshots[2]
        assert snapshots[0][-1] == snapshots[0][-2] == ((), ())
        assert len(snapshots[0][3][0]) == 2 and len(snapshots[0][3][1]) == 2
        with connection.transaction():
            set_local_tenant_scope(connection, "finance_scope", "org_a", workspace_id="shared", legal_entity_id="entity_a1")
            connection.execute("SELECT set_config('app.entity_id','entity_b1',true)")
            assert _rows(connection) == ((), ())


def test_invoker_predicate_keeps_current_parent_privileges(finance_database: dict[str, Any]) -> None:
    import psycopg
    from psycopg import sql

    db = finance_database
    with closing(db["factory"].connect()) as connection:
        role = connection.execute("SELECT current_user").fetchone()[0]
        connection.commit()
        with connection.transaction():
            set_local_tenant_scope(connection, "finance_scope", "org_a", workspace_id="shared", legal_entity_id="entity_a1")
            assert _rows(connection)[0]
        with psycopg.connect(db["admin"], autocommit=True) as admin:
            admin.execute(sql.SQL("REVOKE SELECT ON reconforge.finance_entries FROM {}").format(sql.Identifier(role)))
        try:
            with connection.transaction(), pytest.raises(psycopg.errors.InsufficientPrivilege):
                set_local_tenant_scope(connection, "finance_scope", "org_a", workspace_id="shared", legal_entity_id="entity_a1")
                _rows(connection)
        finally:
            with psycopg.connect(db["admin"], autocommit=True) as admin:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.finance_entries TO {}").format(sql.Identifier(role)))
