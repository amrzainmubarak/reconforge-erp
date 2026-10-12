"""Financial conservation across independent Payables invoices and connections."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest

from reconforge.audit import AuditLedgerError
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.postgres import (
    ConnectionFactory,
    PostgresConnectionFactory,
    PostgresRuntimeConnectionFactory,
    PostgresSettings,
)
from reconforge.infrastructure.postgres_payables import PostgresPayablesError, PostgresPayablesRepository
from reconforge.infrastructure.sqlite_payables import SQLitePayablesRepository
from reconforge.platform.common import PlatformError
from reconforge.platform.payables import PurchaseOrderLineInput, SupplierInvoiceLineInput
from tests.postgres_test_hygiene import PAYABLES_TENANT_CLEANUP_PLAN, cleanup_postgres_test_tenants_as_admin
from tests.test_alembic_postgres import isolated_postgres_migration_dsn as _isolated_postgres_migration_dsn

isolated_postgres_migration_dsn = _isolated_postgres_migration_dsn


@dataclass
class PayablesDatabase:
    path: Path | None = None
    factory: ConnectionFactory | None = None
    tenant: str = ""
    admin: Any = None

    @contextmanager
    def repository(self) -> Iterator[Any]:
        if self.path is not None:
            connection = connect(self.path, require_exists=True)
        else:
            if self.factory is None:
                raise RuntimeError("PostgreSQL approval-integrity fixture has no application connection factory.")
            connection = self.factory.connect()
        try:
            if self.path is not None:
                yield SQLitePayablesRepository(connection)
            else:
                yield PostgresPayablesRepository(connection, self.tenant)
        finally:
            connection.close()

    def set_legacy_invoice_state(self, invoice_id: str, status: str, version: int) -> None:
        """Seed a pre-upgrade state that public workflows may no longer create."""

        if self.path is not None:
            connection = connect(self.path, require_exists=True)
            try:
                connection.execute("UPDATE ap_supplier_invoices SET status=?,row_version=? WHERE id=?", (status, version, invoice_id))
                connection.commit()
            finally:
                connection.close()
        else:
            with self.admin.transaction():
                self.admin.execute(
                    "UPDATE reconforge.ap_supplier_invoices SET status=%s,row_version=%s WHERE tenant_id=%s AND id=%s",
                    (status, version, self.tenant, invoice_id),
                )

    def approval_evidence_counts(self) -> tuple[int, int]:
        if self.path is not None:
            connection = connect(self.path, require_exists=True)
            try:
                return (
                    connection.execute("SELECT COUNT(*) FROM audit_events WHERE action='ap_supplier_invoice_approved'").fetchone()[0],
                    connection.execute("SELECT COUNT(*) FROM outbox_events WHERE event_type='ap.supplier_invoice.approved'").fetchone()[0],
                )
            finally:
                connection.close()
        with self.admin.transaction():
            return (
                self.admin.execute("SELECT COUNT(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s AND action='ap_supplier_invoice_approved'", (self.tenant,)).fetchone()[0],
                self.admin.execute("SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id=%s AND event_type='ap_supplier_invoice_approved'", (self.tenant,)).fetchone()[0],
            )


@pytest.fixture(params=("sqlite", "postgres"))
def database(request: Any, tmp_path: Path) -> Iterator[PayablesDatabase]:
    if request.param == "sqlite":
        path = tmp_path / "payables-integrity.db"
        run_migrations(path)
        yield PayablesDatabase(path=path)
        return
    dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PROD-002 requires a live PostgreSQL nonowner application profile; review 2026-10-04")
    import psycopg
    from alembic.config import Config

    from alembic import command

    isolated_dsn = request.getfixturevalue("isolated_postgres_migration_dsn")
    command.upgrade(Config(str(Path("alembic.ini").resolve())), "head")
    database_name = psycopg.conninfo.conninfo_to_dict(isolated_dsn).get("dbname")
    app_role = psycopg.conninfo.conninfo_to_dict(dsn).get("user")
    if not isinstance(database_name, str) or not database_name:
        raise AssertionError("the isolated PostgreSQL database DSN must identify its database")
    if not isinstance(app_role, str) or not app_role:
        raise AssertionError("the PostgreSQL application DSN must identify its role")
    factory = PostgresRuntimeConnectionFactory(
        PostgresConnectionFactory(
            PostgresSettings(dsn=psycopg.conninfo.make_conninfo(dsn, dbname=database_name), require_tls=False)
        )
    )
    admin = PostgresConnectionFactory(PostgresSettings(dsn=isolated_dsn, require_tls=False)).connect()
    tenant = "ap_integrity_" + uuid4().hex[:16]
    try:
        with admin.transaction():
            role = psycopg.sql.Identifier(app_role)
            admin.execute(
                psycopg.sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    psycopg.sql.Identifier(database_name),
                    role,
                )
            )
            connect_grant = admin.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_database database
                    CROSS JOIN LATERAL pg_catalog.aclexplode(database.datacl)
                        AS acl_entry(grantor,grantee,privilege_type,is_grantable)
                    JOIN pg_catalog.pg_roles granted_role ON granted_role.oid=acl_entry.grantee
                    WHERE database.datname=pg_catalog.current_database()
                      AND granted_role.rolname=%s
                      AND acl_entry.privilege_type='CONNECT'
                )
                """,
                (app_role,),
            ).fetchone()
            assert connect_grant is not None and connect_grant[0] is True
            admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
            admin.execute(
                psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(
                    role
                )
            )
            admin.execute(psycopg.sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}").format(role))
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant, tenant))
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'default')",
                (tenant, "workspace_" + tenant),
            )
            admin.execute(
                "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)",
                (tenant,),
            )
        with factory.connect() as application_connection:
            assert tuple(
                application_connection.execute(
                    "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).fetchone()
            ) == (False, False)
        yield PayablesDatabase(factory=factory, tenant=tenant, admin=admin)
    finally:
        cleanup_postgres_test_tenants_as_admin(admin, tenant_ids=(tenant,), plan=PAYABLES_TENANT_CLEANUP_PLAN)
        factory.close()
        admin.close()


def received_order(repository: Any, *, quantity: str = "3", receive: bool = True) -> tuple[str, str]:
    repository.upsert_supplier(supplier_code="SUP", name="Synthetic Supplier", currency_code="USD")
    order = repository.create_purchase_order(
        po_number="PO", supplier_code="SUP", order_date="2026-07-01", currency_code="USD",
        lines=[PurchaseOrderLineInput(item_code="ITEM", ordered_quantity=quantity, unit_price_minor=1000)],
        actor_label="maker",
    )
    order = repository.submit_purchase_order(order["id"], expected_version=1, actor_label="maker")
    order = repository.approve_purchase_order(order["id"], expected_version=2, actor_label="checker")
    line_id = order["lines"][0]["id"]
    if receive:
        repository.post_receipt(
            receipt_number="GR", purchase_order_id=order["id"], receipt_date="2026-07-02",
            quantities={line_id: quantity}, actor_label="maker",
        )
    return order["id"], line_id


def submitted_invoice(repository: Any, order_id: str, line_id: str, number: str, *quantities: str) -> str:
    lines = [SupplierInvoiceLineInput(
        purchase_order_line_id=line_id, invoiced_quantity=quantity, unit_price_minor=1000,
        line_total_minor=int(Decimal(quantity) * 1000),
    ) for quantity in quantities]
    invoice = repository.create_supplier_invoice(
        invoice_number=number, supplier_code="SUP", invoice_date="2026-07-03", currency_code="USD",
        total_minor=sum(line.line_total_minor for line in lines), purchase_order_id=order_id,
        lines=lines, actor_label="maker",
    )
    repository.submit_supplier_invoice(invoice["id"], expected_version=1, actor_label="maker")
    return str(invoice["id"])


@pytest.mark.parametrize("precision,text", [(28, "1.0000000000000000000000000001"), (6, "1.000001")])
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_quantity_canonicalization_preserves_all_digits(backend: str, precision: int, text: str) -> None:
    from reconforge.infrastructure.postgres_payables import _quantity as postgres_quantity
    from reconforge.infrastructure.sqlite_payables import _quantity as sqlite_quantity

    with localcontext() as context:
        context.prec = precision
        actual = sqlite_quantity(text, field="Quantity") if backend == "sqlite" else postgres_quantity(text, "Quantity")[1]
    assert Decimal(actual) == Decimal(text)


def test_two_previously_matched_invoices_cannot_consume_one_receipt_twice(database: PayablesDatabase) -> None:
    with database.repository() as repository:
        order, line = received_order(repository)
        first = submitted_invoice(repository, order, line, "INV-A", "3")
        second = submitted_invoice(repository, order, line, "INV-B", "3")
        assert repository.run_three_way_match(first).status == "Passed"
        assert repository.run_three_way_match(second).status == "Passed"
        repository.approve_supplier_invoice(first, expected_version=3, actor_label="checker")
        with pytest.raises(PlatformError, match="quantity|quantities"):
            repository.approve_supplier_invoice(second, expected_version=3, actor_label="checker")
        assert repository.get_supplier_invoice(second)["status"] == "Matched"
        assert repository.get_supplier_invoice(second)["row_version"] == 3
    assert database.approval_evidence_counts() == (1, 1)


@pytest.mark.parametrize("actor", ["maker", "MAKER", "  MaKeR  "])
def test_supplier_invoice_creator_cannot_approve_and_denial_releases_lock(
    database: PayablesDatabase, actor: str,
) -> None:
    with database.repository() as repository:
        order, line = received_order(repository)
        invoice = submitted_invoice(repository, order, line, "INV", "3")
        assert repository.run_three_way_match(invoice).status == "Passed"
        with pytest.raises(PlatformError, match="creator cannot approve"):
            repository.approve_supplier_invoice(invoice, expected_version=3, actor_label=actor)
        unchanged = repository.get_supplier_invoice(invoice)
        assert unchanged["status"] == "Matched"
        assert unchanged["row_version"] == 3
        assert database.approval_evidence_counts() == (0, 0)
        # A second connection can approve while the denied caller remains open.
        with database.repository() as independent:
            approved = independent.approve_supplier_invoice(invoice, expected_version=3, actor_label="checker")
            assert approved["status"] == "Approved"
    assert database.approval_evidence_counts() == (1, 1)


def test_duplicate_po_line_references_are_aggregated_before_matching(database: PayablesDatabase) -> None:
    with database.repository() as repository:
        order, line = received_order(repository)
        invoice = submitted_invoice(repository, order, line, "INV", "3", "3")
        match = repository.run_three_way_match(invoice)
        assert match.status == "Exception"
        assert f"AP-3WM-QUANTITY:{line}" in match.reason


def test_partial_invoices_and_nonapproved_documents_preserve_available_quantity(database: PayablesDatabase) -> None:
    with database.repository() as repository:
        order, line = received_order(repository)
        unused = submitted_invoice(repository, order, line, "INV-UNUSED", "3")
        assert repository.run_three_way_match(unused).status == "Passed"
        first = submitted_invoice(repository, order, line, "INV-A", "1")
        assert repository.run_three_way_match(first).status == "Passed"
        repository.approve_supplier_invoice(first, expected_version=3, actor_label="checker")
        second = submitted_invoice(repository, order, line, "INV-B", "1", "1")
        assert repository.run_three_way_match(second).status == "Passed"
        assert repository.approve_supplier_invoice(second, expected_version=3, actor_label="checker")["status"] == "Approved"
        assert repository.get_supplier_invoice(unused)["status"] == "Matched"


def test_paid_invoice_still_consumes_receipt_quantity_after_payment_link_upgrade(tmp_path: Path) -> None:
    """A paid invoice retained from schema 53 still consumes its receipt after upgrade."""

    database = PayablesDatabase(path=tmp_path / "legacy-paid-invoice.db")
    assert database.path is not None
    run_migrations(database.path, target_version=53)
    with database.repository() as repository:
        order, line = received_order(repository)
        first = submitted_invoice(repository, order, line, "INV-A", "3")
        second = submitted_invoice(repository, order, line, "INV-B", "3")
        repository.run_three_way_match(first)
        repository.run_three_way_match(second)
        repository.approve_supplier_invoice(first, expected_version=3, actor_label="checker")
    database.set_legacy_invoice_state(first, "Paid", 4)
    run_migrations(database.path)
    with database.repository() as repository, pytest.raises(PlatformError, match="quantity|quantities"):
        repository.approve_supplier_invoice(second, expected_version=3, actor_label="checker")


def test_approved_invoice_cannot_be_rematched_to_release_consumption(database: PayablesDatabase) -> None:
    with database.repository() as repository:
        order, line = received_order(repository)
        invoice = submitted_invoice(repository, order, line, "INV", "3")
        repository.run_three_way_match(invoice)
        repository.approve_supplier_invoice(invoice, expected_version=3, actor_label="checker")
        with pytest.raises(PlatformError, match="submitted"):
            repository.run_three_way_match(invoice)
        assert repository.get_supplier_invoice(invoice)["status"] == "Approved"


def test_approval_rechecks_legacy_matched_duplicate_lines(database: PayablesDatabase) -> None:
    with database.repository() as repository:
        order, line = received_order(repository)
        invoice = submitted_invoice(repository, order, line, "INV", "3", "3")
    database.set_legacy_invoice_state(invoice, "Matched", 3)
    with database.repository() as repository, pytest.raises(PlatformError, match="quantity"):
        repository.approve_supplier_invoice(invoice, expected_version=3, actor_label="checker")
    assert database.approval_evidence_counts() == (0, 0)


def test_concurrent_approvals_consume_quantity_once(database: PayablesDatabase) -> None:
    with database.repository() as repository:
        order, line = received_order(repository)
        invoices = [submitted_invoice(repository, order, line, number, "3") for number in ("INV-A", "INV-B")]
        for invoice in invoices:
            repository.run_three_way_match(invoice)
    barrier = Barrier(2)

    def approve(invoice: str) -> str:
        with database.repository() as repository:
            barrier.wait(timeout=10)
            try:
                return str(repository.approve_supplier_invoice(invoice, expected_version=3, actor_label="checker")["status"])
            except PlatformError as exc:
                assert "quantit" in str(exc)
                return "Rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(approve, invoices)) == ["Approved", "Rejected"]


def test_concurrent_receipts_cannot_overreceive(database: PayablesDatabase) -> None:
    with database.repository() as repository:
        order, line = received_order(repository, receive=False)
    barrier = Barrier(2)

    def receive(number: str) -> str:
        with database.repository() as repository:
            barrier.wait(timeout=10)
            try:
                return str(repository.post_receipt(
                    receipt_number=number, purchase_order_id=order, receipt_date="2026-07-02",
                    quantities={line: "3"}, actor_label="maker",
                )["status"])
            except PlatformError as exc:
                assert "exceeds ordered quantity" in str(exc)
                return "Rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(receive, ("GR-A", "GR-B"))) == ["Posted", "Rejected"]


def test_quantity_conservation_beyond_28_digits_and_low_context(database: PayablesDatabase) -> None:
    tiny = "0.0000000000000000000000000001"
    with database.repository() as repository, localcontext() as context:
        context.prec = 6
        order, line = received_order(repository, quantity="1.0000000000000000000000000001")
        assert repository.get_purchase_order(order)["lines"][0]["ordered_quantity"] == "1.0000000000000000000000000001"
        first = submitted_invoice(repository, order, line, "INV-A", "1")
        match = repository.run_three_way_match(first)
        assert match.status == "Passed"
        assert match.quantity_variance == "-" + tiny
        repository.approve_supplier_invoice(first, expected_version=3, actor_label="checker")
        second = submitted_invoice(repository, order, line, "INV-B", tiny)
        assert repository.run_three_way_match(second).status == "Passed"
        repository.approve_supplier_invoice(second, expected_version=3, actor_label="checker")
        third = submitted_invoice(repository, order, line, "INV-C", tiny)
        assert repository.run_three_way_match(third).status == "Exception"


@pytest.mark.parametrize("failure", ("audit", "outbox"))
def test_failed_approval_evidence_rolls_back_consumption(
    database: PayablesDatabase, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    with database.repository() as repository:
        order, line = received_order(repository)
        first = submitted_invoice(repository, order, line, "INV-A", "3")
        second = submitted_invoice(repository, order, line, "INV-B", "3")
        repository.run_three_way_match(first)
        repository.run_three_way_match(second)

        def fail(*_args: Any, **_kwargs: Any) -> None:
            raise AuditLedgerError("Synthetic evidence failure")

        with monkeypatch.context() as patch:
            if database.path is not None:
                from importlib import import_module

                import reconforge.platform.common as common

                module = import_module("reconforge.infrastructure.sqlite_payables")
                patch.setattr(common if failure == "audit" else module, "audit" if failure == "audit" else "append_outbox_event", fail)
            elif failure == "audit":
                from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository

                patch.setattr(PostgresAuditEventRepository, "append", fail)
            else:
                connection = repository.connection

                class FailOutbox:
                    def __getattr__(self, name: str) -> Any:
                        return getattr(connection, name)

                    def execute(self, query: str, parameters: Any = ()) -> Any:
                        if "INSERT INTO reconforge.outbox_events" in query:
                            fail()
                        return connection.execute(query, parameters)

                patch.setattr(repository, "connection", FailOutbox())
            with pytest.raises((PlatformError, PostgresPayablesError, AuditLedgerError)):
                repository.approve_supplier_invoice(first, expected_version=3, actor_label="checker")
        assert repository.get_supplier_invoice(first)["status"] == "Matched"
        assert repository.get_supplier_invoice(first)["row_version"] == 3
        assert database.approval_evidence_counts() == (0, 0)
        assert repository.approve_supplier_invoice(second, expected_version=3, actor_label="checker")["status"] == "Approved"
    assert database.approval_evidence_counts() == (1, 1)
