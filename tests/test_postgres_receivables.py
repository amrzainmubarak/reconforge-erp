from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.receivables import (
    ReceivableInvoiceLineInput,
    ReceivablesRepositoryProtocol,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_receivables import (
    POSTGRES_RECEIVABLES_SCHEMA_SQL,
    PostgresReceivablesRepository,
    _quantity,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0022_postgres_receivables.py"
    spec = importlib.util.spec_from_file_location("migration_0022", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_receivables_schema_covers_complete_aggregate_with_forced_rls() -> None:
    tables = ("ar_customers", "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations", "ar_idempotency_keys")
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "ENABLE ROW LEVEL SECURITY" in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_RECEIVABLES_SCHEMA_SQL


def test_receivables_schema_uses_exact_money_and_unbounded_exact_quantity() -> None:
    for column in ("credit_limit_minor BIGINT", "subtotal_minor BIGINT", "tax_minor BIGINT", "total_minor BIGINT", "unit_price_minor BIGINT", "line_total_minor BIGINT", "amount_minor BIGINT"):
        assert column in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "quantity NUMERIC NOT NULL" in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "quantity_text TEXT NOT NULL" in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "NUMERIC(38,12)" not in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_RECEIVABLES_SCHEMA_SQL


def test_receivables_schema_prevents_cross_tenant_links_and_protects_final_invoices() -> None:
    assert "PRIMARY KEY (tenant_id,id)" in POSTGRES_RECEIVABLES_SCHEMA_SQL
    for parent in ("ar_customers", "ar_invoices", "ar_receipts"):
        assert f"REFERENCES reconforge.{parent}(tenant_id,id)" in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "approved receivable invoices are immutable" in POSTGRES_RECEIVABLES_SCHEMA_SQL
    assert "approved receivable invoice lines are immutable" in POSTGRES_RECEIVABLES_SCHEMA_SQL


def test_receivables_migration_is_linear_and_downgrade_is_child_first() -> None:
    migration = _migration()
    assert migration.revision == "0022_postgres_receivables"
    assert migration.down_revision == "0021_postgres_payables"
    source = (ROOT / "alembic/versions/0022_postgres_receivables.py").read_text(encoding="utf-8")
    positions = [source.index(f'"{table}"') for table in ("ar_idempotency_keys", "ar_receipt_allocations", "ar_receipts", "ar_invoice_lines", "ar_invoices", "ar_customers")]
    assert positions == sorted(positions)


def test_all_receivables_signatures_match_application_contract() -> None:
    methods = (
        "upsert_customer", "create_invoice", "submit_invoice", "approve_invoice",
        "post_receipt", "allocate_receipt", "get_customer", "get_invoice",
        "get_receipt", "list_customers", "list_invoices", "credit_exposure", "aging_report",
    )
    for method_name in methods:
        assert inspect.signature(getattr(PostgresReceivablesRepository, method_name)) == inspect.signature(
            getattr(ReceivablesRepositoryProtocol, method_name)
        )


def test_receivable_quantity_preserves_scale_beyond_twelve_places() -> None:
    quantity, canonical = _quantity("0.0000000000001", "Quantity")
    assert str(quantity) == "1E-13"
    assert canonical == "0.0000000000001"


class _NoWriteConnection:
    def transaction(self) -> object:
        raise AssertionError("validation must finish before a transaction starts")


def test_invoice_line_total_mismatch_fails_before_transaction() -> None:
    repository = PostgresReceivablesRepository(_NoWriteConnection(), "tenant_a")
    with pytest.raises(PlatformError, match="does not equal"):
        repository.create_invoice(
            invoice_number="INV-1", customer_code="CUS-1", invoice_date="2026-07-28",
            currency_code="USD", tax_minor=0,
            lines=[ReceivableInvoiceLineInput("Line", "1.25", 100, 124)],
        )


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_receivables_lifecycle_credit_allocation_aging_and_rls() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a, tenant_b = "receivables_a_" + uuid4().hex[:8], "receivables_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_RECEIVABLES_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            tables = (
                "tenants,organizations,currencies,legal_entities,domain_workspaces,"
                "domain_audit_ledger_state,domain_audit_events,outbox_events,"
                "ar_customers,ar_invoices,ar_invoice_lines,ar_receipts,"
                "ar_receipt_allocations,ar_idempotency_keys"
            )
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{tables.replace(',', ',reconforge.')} TO {app_user}")
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)", (tenant_a, tenant_a, tenant_b, tenant_b))
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Receivables')", (tenant, f"workspace-{tenant}"))
                connection.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)", (tenant,))
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresReceivablesRepository(connection, tenant_a)
            repository.upsert_customer(customer_code="CUS-1", name="Customer", currency_code="USD", credit_limit_minor=10_000, workspace="Receivables")
            invoice = repository.create_invoice(invoice_number="INV-1", customer_code="CUS-1", invoice_date="2026-07-01", currency_code="USD", tax_minor=0, lines=[ReceivableInvoiceLineInput("Exact", "1.0000000000001", 100, 100)], workspace="Receivables", actor_label="maker")
            invoice = repository.submit_invoice(str(invoice["id"]), expected_version=1, actor_label="maker")
            with pytest.raises(PlatformError, match="creator cannot approve"):
                repository.approve_invoice(str(invoice["id"]), expected_version=2, actor_label="maker")
            invoice = repository.approve_invoice(str(invoice["id"]), expected_version=2, actor_label="checker")
            receipt = repository.post_receipt(receipt_number="RCT-1", customer_code="CUS-1", receipt_date="2026-07-28", currency_code="USD", amount_minor=40, workspace="Receivables", actor_label="cashier")
            receipt = repository.allocate_receipt(str(receipt["id"]), invoice_id=str(invoice["id"]), amount_minor=40, expected_version=1, actor_label="cashier")
            assert receipt["unallocated_minor"] == 0
            assert repository.get_invoice(str(invoice["id"]))["outstanding_minor"] == 60
            assert repository.aging_report(workspace="Receivables", as_of_date="2026-07-28")["total_outstanding_minor"] == 60
            assert invoice["lines"][0]["quantity"] == "1.0000000000001"
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresReceivablesRepository(connection, tenant_b)
            assert repository.list_customers(workspace="Receivables") == []
            assert repository.list_invoices(workspace="Receivables") == []
    finally:
        for tenant in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
            except psycopg.Error:
                pass
        admin.close()
