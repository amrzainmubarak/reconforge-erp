from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.payables import (
    PayablesRepositoryProtocol,
    PurchaseOrderLineInput,
    SupplierInvoiceLineInput,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_journals import POSTGRES_JOURNAL_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_payables import (
    POSTGRES_PAYABLES_SCHEMA_SQL,
    PostgresPayablesError,
    PostgresPayablesRepository,
    _quantity,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0021_postgres_payables.py"
    spec = importlib.util.spec_from_file_location("migration_0021", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_payables_schema_covers_complete_aggregate_with_forced_rls() -> None:
    tables = (
        "ap_suppliers",
        "ap_purchase_orders",
        "ap_purchase_order_lines",
        "ap_goods_receipts",
        "ap_goods_receipt_lines",
        "ap_supplier_invoices",
        "ap_supplier_invoice_lines",
        "ap_three_way_matches",
        "ap_idempotency_keys",
    )
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_PAYABLES_SCHEMA_SQL
    assert "ENABLE ROW LEVEL SECURITY" in POSTGRES_PAYABLES_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_PAYABLES_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_PAYABLES_SCHEMA_SQL


def test_payables_schema_uses_exact_financial_and_quantity_storage() -> None:
    for column in (
        "unit_price_minor BIGINT",
        "tax_minor BIGINT",
        "total_minor BIGINT",
        "line_total_minor BIGINT",
        "price_variance_minor BIGINT",
        "total_variance_minor BIGINT",
    ):
        assert column in POSTGRES_PAYABLES_SCHEMA_SQL
    assert "ordered_quantity NUMERIC NOT NULL" in POSTGRES_PAYABLES_SCHEMA_SQL
    assert "NUMERIC(38,12)" not in POSTGRES_PAYABLES_SCHEMA_SQL
    assert "ordered_quantity_text TEXT" in POSTGRES_PAYABLES_SCHEMA_SQL
    assert "invoiced_quantity_text TEXT" in POSTGRES_PAYABLES_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_PAYABLES_SCHEMA_SQL
    assert " REAL " not in POSTGRES_PAYABLES_SCHEMA_SQL


def test_payables_schema_prevents_cross_tenant_parent_links() -> None:
    assert "PRIMARY KEY (tenant_id,id)" in POSTGRES_PAYABLES_SCHEMA_SQL
    for parent in (
        "ap_suppliers",
        "ap_purchase_orders",
        "ap_purchase_order_lines",
        "ap_goods_receipts",
        "ap_supplier_invoices",
    ):
        assert f"REFERENCES reconforge.{parent}(tenant_id,id)" in POSTGRES_PAYABLES_SCHEMA_SQL


def test_payables_migration_is_linear_and_downgrade_is_child_first() -> None:
    migration = _migration()
    assert migration.revision == "0021_postgres_payables"
    assert migration.down_revision == "0020_postgres_master_data_app"
    source = (ROOT / "alembic/versions/0021_postgres_payables.py").read_text(encoding="utf-8")
    positions = [
        source.index(f'"{table}"')
        for table in (
            "ap_idempotency_keys",
            "ap_three_way_matches",
            "ap_supplier_invoice_lines",
            "ap_supplier_invoices",
            "ap_goods_receipt_lines",
            "ap_goods_receipts",
            "ap_purchase_order_lines",
            "ap_purchase_orders",
            "ap_suppliers",
        )
    ]
    assert positions == sorted(positions)


class _Result:
    def __init__(self, *, one: object = None, many: list[object] | None = None) -> None:
        self.one = one
        self.many = many or []

    def fetchone(self) -> object:
        return self.one

    def fetchall(self) -> list[object]:
        return self.many


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> None:
        self.connection.entered += 1

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.connection.exited += 1
        self.connection.rolled_back = exc is not None
        return False


class _Connection:
    def __init__(self, *, workspace: bool = True) -> None:
        self.workspace = workspace
        self.entered = 0
        self.exited = 0
        self.rolled_back = False
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def execute(self, query: str, parameters: tuple[object, ...] = ()) -> _Result:
        self.queries.append((query, parameters))
        if "FROM reconforge.domain_workspaces" in query:
            return _Result(one={"id": "workspace-a"} if self.workspace else None)
        if "FROM reconforge.ap_suppliers" in query and "supplier_code=%s" in query:
            return _Result(
                one={
                    "id": "supplier-a",
                    "workspace_id": "workspace-a",
                    "organization_id": None,
                    "legal_entity_id": None,
                    "supplier_code": "SUP-A",
                    "name": "Supplier A",
                    "currency_code": "EUR",
                    "tax_identifier": "",
                    "status": "Active",
                    "created_at": "2026-07-28T00:00:00Z",
                    "updated_at": "2026-07-28T00:00:00Z",
                    "row_version": 1,
                }
            )
        if "FROM reconforge.ap_suppliers" in query:
            return _Result(
                many=[
                    {
                        "id": "supplier-a",
                        "workspace_id": "workspace-a",
                        "organization_id": None,
                        "legal_entity_id": None,
                        "supplier_code": "SUP-A",
                        "name": "Supplier A",
                        "currency_code": "USD",
                        "tax_identifier": "",
                        "status": "Active",
                        "created_at": "2026-07-28T00:00:00Z",
                        "updated_at": "2026-07-28T00:00:00Z",
                        "row_version": 1,
                    }
                ]
            )
        return _Result()


def test_supplier_list_is_tenant_and_workspace_scoped() -> None:
    connection = _Connection()
    rows = PostgresPayablesRepository(connection, "tenant_a").list_suppliers(workspace="regulated")

    assert rows[0]["supplier_code"] == "SUP-A"
    assert connection.entered == connection.exited == 1
    assert not connection.rolled_back
    supplier_query = next(query for query in connection.queries if "FROM reconforge.ap_suppliers" in query[0])
    assert supplier_query[1][:2] == ("tenant_a", "workspace-a")


def test_missing_required_workspace_rolls_back_without_supplier_write() -> None:
    connection = _Connection(workspace=False)
    repository = PostgresPayablesRepository(connection, "tenant_a")

    with pytest.raises(PostgresPayablesError, match="workspace was not found"):
        repository.upsert_supplier(
            supplier_code="SUP-A",
            name="Supplier A",
            currency_code="USD",
            workspace="missing",
        )

    assert connection.rolled_back
    assert not any("INSERT INTO reconforge.ap_suppliers" in query for query, _parameters in connection.queries)


def test_purchase_order_rejects_currency_mismatch_before_business_write() -> None:
    connection = _Connection()
    repository = PostgresPayablesRepository(connection, "tenant_a")

    with pytest.raises(PlatformError, match="currency must match"):
        repository.create_purchase_order(
            po_number="PO-1",
            supplier_code="SUP-A",
            order_date="2026-07-28",
            currency_code="USD",
            lines=[PurchaseOrderLineInput(item_code="ITEM-1", ordered_quantity="1.25", unit_price_minor=100)],
        )

    assert connection.rolled_back
    assert not any("INSERT INTO reconforge.ap_purchase_orders" in query for query, _ in connection.queries)


def test_purchase_order_quantity_preserves_exact_scale_without_typmod_rounding() -> None:
    quantity, canonical = _quantity("0.0000000000001", "Quantity")

    assert str(quantity) == "1E-13"
    assert canonical == "0.0000000000001"


def test_all_payables_signatures_match_application_contract() -> None:
    methods = (
        "upsert_supplier",
        "create_purchase_order",
        "submit_purchase_order",
        "approve_purchase_order",
        "post_receipt",
        "create_supplier_invoice",
        "submit_supplier_invoice",
        "run_three_way_match",
        "approve_supplier_invoice",
        "get_supplier",
        "get_purchase_order",
        "get_receipt",
        "get_supplier_invoice",
        "list_suppliers",
        "list_supplier_invoices",
    )

    for method_name in methods:
        assert inspect.signature(getattr(PostgresPayablesRepository, method_name)) == inspect.signature(
            getattr(PayablesRepositoryProtocol, method_name)
        )


def test_supplier_invoice_total_mismatch_fails_before_transaction() -> None:
    connection = _Connection()
    repository = PostgresPayablesRepository(connection, "tenant_a")

    with pytest.raises(PlatformError, match="sum of line totals"):
        repository.create_supplier_invoice(
            invoice_number="INV-1",
            supplier_code="SUP-A",
            invoice_date="2026-07-28",
            currency_code="EUR",
            total_minor=101,
            lines=[
                SupplierInvoiceLineInput(
                    purchase_order_line_id="line-1",
                    invoiced_quantity="1",
                    unit_price_minor=100,
                    line_total_minor=100,
                )
            ],
        )

    assert connection.entered == 0
    assert connection.queries == []


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_payables_lifecycle_exactness_and_rls() -> None:
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
    tenant_a = "payables_a_" + uuid4().hex[:8]
    tenant_b = "payables_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_JOURNAL_SCHEMA_SQL)
            admin.execute(POSTGRES_PAYABLES_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            tables = (
                "tenants,organizations,currencies,legal_entities,branches,domain_workspaces,"
                "domain_audit_ledger_state,domain_audit_events,outbox_events,control_exceptions,"
                "ap_suppliers,ap_purchase_orders,ap_purchase_order_lines,ap_goods_receipts,"
                "ap_goods_receipt_lines,ap_supplier_invoices,ap_supplier_invoice_lines,"
                "ap_three_way_matches,ap_idempotency_keys"
            )
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{tables.replace(',', ',reconforge.')} TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Payables')",
                    (tenant, f"workspace-{tenant}"),
                )
                connection.execute(
                    "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)",
                    (tenant,),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresPayablesRepository(connection, tenant_a)
            repository.upsert_supplier(
                supplier_code="SUP-A", name="Supplier A", currency_code="USD", workspace="Payables"
            )
            order = repository.create_purchase_order(
                po_number="PO-1",
                supplier_code="SUP-A",
                order_date="2026-07-28",
                currency_code="USD",
                lines=[
                    PurchaseOrderLineInput(item_code="ITEM-1", ordered_quantity="1.0000000000001", unit_price_minor=100)
                ],
                workspace="Payables",
                idempotency_key="po-1",
                actor_label="maker",
            )
            order = repository.submit_purchase_order(str(order["id"]), expected_version=1, actor_label="maker")
            with pytest.raises(PlatformError, match="creator cannot approve"):
                repository.approve_purchase_order(str(order["id"]), expected_version=2, actor_label="maker")
            order = repository.approve_purchase_order(str(order["id"]), expected_version=2, actor_label="checker")
            line_id = str(order["lines"][0]["id"])
            repository.post_receipt(
                receipt_number="GR-1",
                purchase_order_id=str(order["id"]),
                receipt_date="2026-07-28",
                quantities={line_id: "1.0000000000001"},
                workspace="Payables",
                actor_label="receiver",
            )
            invoice = repository.create_supplier_invoice(
                invoice_number="INV-1",
                supplier_code="SUP-A",
                invoice_date="2026-07-28",
                currency_code="USD",
                total_minor=100,
                purchase_order_id=str(order["id"]),
                lines=[
                    SupplierInvoiceLineInput(
                        purchase_order_line_id=line_id,
                        invoiced_quantity="1.0000000000001",
                        unit_price_minor=100,
                        line_total_minor=100,
                    )
                ],
                workspace="Payables",
                actor_label="maker",
            )
            invoice = repository.submit_supplier_invoice(str(invoice["id"]), expected_version=1, actor_label="maker")
            match = repository.run_three_way_match(str(invoice["id"]), actor_label="matcher")
            assert match.status == "Passed"
            invoice = repository.approve_supplier_invoice(str(invoice["id"]), expected_version=3, actor_label="checker")
            assert invoice["status"] == "Approved"
            assert invoice["lines"][0]["invoiced_quantity"] == "1.0000000000001"
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresPayablesRepository(connection, tenant_b)
            assert repository.list_suppliers(workspace="Payables") == []
            assert repository.list_supplier_invoices(workspace="Payables") == []
    finally:
        for tenant in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
            except psycopg.Error:
                pass
        admin.close()
