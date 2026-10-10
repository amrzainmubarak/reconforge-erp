"""Native ordinary-role dispatch and exact original revenue inverse closure."""

from typing import Any

import pytest

from reconforge.infrastructure.postgres_customer_returns import PostgresCustomerReturnsRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_stock_sales_reversal_dispatch_schema import DOWNGRADE_SQL, UPGRADE_SQL
from reconforge.platform.common import server_principal_context
from tests.test_postgres_customer_returns import create_runtime, request, retained_state
from tests.test_postgres_finance_posting import (
    CHECKER,
    MAKER,
    SCOPE,
    finance_database,
    isolated_postgres_migration_dsn,
    posting_database,
    principal,
    reviewed,
)
from tests.test_postgres_inventory_receipt_posting import receipt_database
from tests.test_postgres_posting_snapshot_profile import (
    test_thousand_line_snapshot_matches_legacy_per_line_oracle_under_rls as assert_native_snapshot_parity,
)

__all__ = ["finance_database", "isolated_postgres_migration_dsn", "posting_database", "receipt_database"]

_OBSOLETE = " OR EXISTS(SELECT 1 FROM reconforge.operational_finance_links l WHERE l.tenant_id=d.tenant_id AND l.plan_id=d.invoice_plan_id AND l.posting_effect_id=reverse_effect)"
_CORRECTED = "IF reverse_effect IS NOT NULL THEN\n     SELECT original_entry.external_reference INTO plan"


def _definition(admin: Any) -> str:
    return admin.execute("SELECT pg_get_functiondef('reconforge.stock_sales_native_close()'::regprocedure)").fetchone()[0]


def _install(admin: Any) -> None:
    """Also exercise the additive correction against the frozen owner branch."""
    definition = _definition(admin)
    if _OBSOLETE in definition:
        admin.execute(UPGRADE_SQL)
    assert _CORRECTED in _definition(admin) and _OBSOLETE not in _definition(admin)


def test_corrective_original_effect_dispatch_round_trip_restores_exact_function_and_acl(
    posting_database: dict[str, Any],
) -> None:
    import psycopg

    with psycopg.connect(posting_database["admin"]) as admin:
        if _CORRECTED in _definition(admin):
            admin.execute(DOWNGRADE_SQL)
        original = _definition(admin)
        assert _OBSOLETE in original and _CORRECTED not in original
        metadata = admin.execute("SELECT proowner,proacl,prosecdef,proconfig FROM pg_proc WHERE oid='reconforge.stock_sales_native_close()'::regprocedure").fetchone()
        table_acl = admin.execute("SELECT relname,relacl,relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid IN ('reconforge.stock_sales_orders'::regclass,'reconforge.operational_finance_links'::regclass) ORDER BY relname").fetchall()
        admin.execute(UPGRADE_SQL)
        corrected = _definition(admin)
        assert _OBSOLETE not in corrected and _CORRECTED in corrected
        assert "AND original_entry.external_reference ~ '^OPS1-[a-f0-9]{32}$'" in corrected
        admin.execute(DOWNGRADE_SQL)
        assert _definition(admin) == original
        admin.execute(UPGRADE_SQL)
        assert _definition(admin) == corrected
        assert admin.execute("SELECT proowner,proacl,prosecdef,proconfig FROM pg_proc WHERE oid='reconforge.stock_sales_native_close()'::regprocedure").fetchone() == metadata
        assert admin.execute("SELECT relname,relacl,relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid IN ('reconforge.stock_sales_orders'::regclass,'reconforge.operational_finance_links'::regclass) ORDER BY relname").fetchall() == table_acl
        assert metadata[2] is False


def test_thousand_line_snapshot_and_unrelated_manual_reversal_work_without_ops_link_select(
    posting_database: dict[str, Any],
) -> None:
    import psycopg
    from psycopg import sql

    db = posting_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        role = connection.execute("SELECT current_user").fetchone()[0]
    with psycopg.connect(db["admin"]) as admin:
        _install(admin)
        prior = admin.execute("SELECT has_table_privilege(%s,'reconforge.operational_finance_links','SELECT')", (role,)).fetchone()[0]
        admin.execute(sql.SQL("REVOKE SELECT ON reconforge.operational_finance_links FROM {}").format(sql.Identifier(role)))
    try:
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute("SELECT 1 FROM reconforge.operational_finance_links")
        assert_native_snapshot_parity(db)
        entry_id, digest = reviewed(db, "ORDINARY-UNRELATED-ORIGINAL")
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            posting = PostgresFinancePostingRepository(connection, "finance_scope")
            effect = posting.post(entry_id, command_id="ordinary-post", expected_validation_digest=digest,
                                  reason="Actual ordinary native posting", actor=CHECKER)
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            posting = PostgresFinancePostingRepository(connection, "finance_scope")
            reversal = posting.prepare_reversal(effect["id"], command_id="ordinary-reversal", entry_number="ORDINARY-UNRELATED-INVERSE",
                period_id="period", posting_date="2026-07-29", reason="Actual unrelated native inverse", actor=MAKER)
            with server_principal_context(principal(CHECKER)):
                PostgresFinanceCoreRepository(connection, "finance_scope").validate_entry(reversal["entry_id"],
                    reason="Independent ordinary inverse review", actor_label="checker")
            reversal_digest = posting.preview(reversal["entry_id"], actor=CHECKER)["validation_digest"]
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            posting = PostgresFinancePostingRepository(connection, "finance_scope")
            inverse = posting.post(reversal["entry_id"], command_id="ordinary-inverse-post", expected_validation_digest=reversal_digest,
                                   reason="Post exact unrelated inverse", actor=CHECKER)
            assert inverse["reverses_effect_id"] == effect["id"]
            balance = posting.posted_trial_balance(period_id="period", organization_code="ORG_A", entity_code="A1", workspace="shared", actor=CHECKER)
            assert balance["effect_count"] == 2 and balance["totals"] == {"debit_minor": 20000, "credit_minor": 20000, "balanced": True}
            assert balance["balance_totals"] == {"debit_minor": 0, "credit_minor": 0, "balanced": True}
    finally:
        if prior:
            with psycopg.connect(db["admin"]) as admin:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.operational_finance_links TO {}").format(sql.Identifier(role)))


def test_original_stock_revenue_inverse_remains_closed_with_unrelated_generated_number(
    receipt_database: tuple[str, str],
) -> None:
    import psycopg
    from psycopg import sql

    runtime, order_id, _invoice = create_runtime(receipt_database, 0)
    with psycopg.connect(runtime.admin_dsn) as admin:
        _install(admin)
    with runtime.actor("maker") as (connection, _, _actor):
        original = PostgresCustomerReturnsRepository(connection, runtime.tenant)._source(order_id, lock=False)["revenue"]
        role = connection.execute("SELECT current_user").fetchone()["current_user"]
    before = retained_state(runtime)

    def attempt() -> None:
        with runtime.actor("maker") as (connection, _, actor):
            args = {**request(order_id).payload(), "id": "UNRELATED-NUMBER-REVENUE-INVERSE"}
            PostgresCustomerReturnsRepository(connection, runtime.tenant)._inverse(original,
                "UNRELATED-NUMBER-REVENUE-INVERSE", args, actor)

    with pytest.raises(psycopg.errors.CheckViolation, match="revenue inverse requires complete"):
        attempt()
    assert retained_state(runtime) == before
    with psycopg.connect(runtime.admin_dsn) as admin:
        prior = admin.execute("SELECT has_table_privilege(%s,'reconforge.operational_finance_links','SELECT')", (role,)).fetchone()[0]
        admin.execute(sql.SQL("REVOKE SELECT ON reconforge.operational_finance_links FROM {}").format(sql.Identifier(role)))
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            attempt()
    finally:
        if prior:
            with psycopg.connect(runtime.admin_dsn) as admin:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.operational_finance_links TO {}").format(sql.Identifier(role)))
    assert retained_state(runtime) == before
