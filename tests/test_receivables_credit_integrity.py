"""Customer currency and credit decisions across independent AR connections."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from uuid import uuid4

import pytest

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
from reconforge.audit import AuditLedgerError
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesError, PostgresReceivablesRepository
from reconforge.infrastructure.sqlite_receivables import SQLiteReceivablesRepository
from reconforge.platform.common import PlatformError
from tests.postgres_test_hygiene import RECEIVABLES_TENANT_CLEANUP_PLAN, cleanup_postgres_test_tenants_as_admin


@dataclass
class ReceivablesDatabase:
    path: Path | None = None
    factory: PostgresConnectionFactory | None = None
    tenant: str = ""
    admin: Any = None

    @contextmanager
    def repository(self) -> Iterator[Any]:
        connection = connect(self.path, require_exists=True) if self.path is not None else self.factory.connect()
        try:
            yield SQLiteReceivablesRepository(connection) if self.path is not None else PostgresReceivablesRepository(connection, self.tenant)
        finally:
            connection.close()

    def seed_legacy_currency(self, customer_id: str, currency: str) -> None:
        """Represent a pre-fix customer edit without using the guarded public API."""
        if self.path is not None:
            connection = connect(self.path, require_exists=True)
            try:
                connection.execute("UPDATE ar_customers SET currency_code=? WHERE id=?", (currency, customer_id))
                connection.commit()
            finally:
                connection.close()
        else:
            with self.admin.transaction():
                self.admin.execute("UPDATE reconforge.ar_customers SET currency_code=%s WHERE tenant_id=%s AND id=%s", (currency, self.tenant, customer_id))

    def cancel_draft(self, invoice_id: str) -> None:
        if self.path is not None:
            connection = connect(self.path, require_exists=True)
            try:
                connection.execute("UPDATE ar_invoices SET status='Cancelled' WHERE id=?", (invoice_id,))
                connection.commit()
            finally:
                connection.close()
        else:
            with self.admin.transaction():
                self.admin.execute("UPDATE reconforge.ar_invoices SET status='Cancelled' WHERE tenant_id=%s AND id=%s", (self.tenant, invoice_id))

    def evidence_counts(self) -> tuple[int, int]:
        if self.path is not None:
            connection = connect(self.path, require_exists=True)
            try:
                return (connection.execute("SELECT COUNT(*) FROM audit_events WHERE object_type LIKE 'ar_%'").fetchone()[0],
                        connection.execute("SELECT COUNT(*) FROM outbox_events WHERE event_type LIKE 'ar.%'").fetchone()[0])
            finally:
                connection.close()
        with self.admin.transaction():
            return (self.admin.execute("SELECT COUNT(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s AND object_type LIKE 'ar_%%'", (self.tenant,)).fetchone()[0],
                    self.admin.execute("SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id=%s AND event_type LIKE 'ar_%%'", (self.tenant,)).fetchone()[0])


@pytest.fixture(params=("sqlite", "postgres"))
def database(request: Any, tmp_path: Path) -> Iterator[ReceivablesDatabase]:
    if request.param == "sqlite":
        path = tmp_path / "receivables-integrity.db"
        run_migrations(path)
        yield ReceivablesDatabase(path=path)
        return
    dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PROD-007 requires migrated live PostgreSQL app-role profile; review 2026-10-03")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin = PostgresConnectionFactory(PostgresSettings(dsn=os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn), require_tls=False)).connect()
    tenant = "ar_integrity_" + uuid4().hex[:16]
    try:
        with admin.transaction():
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant, tenant))
            admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'default')", (tenant, "workspace_" + tenant))
            for currency in ("USD", "EUR"):
                admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,%s,%s,2)", (tenant, currency, currency))
        yield ReceivablesDatabase(factory=factory, tenant=tenant, admin=admin)
    finally:
        cleanup_postgres_test_tenants_as_admin(admin, tenant_ids=(tenant,), plan=RECEIVABLES_TENANT_CLEANUP_PLAN)
        admin.close()


def customer(repository: Any, **changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = dict(customer_code="CUS", name="Synthetic Customer", currency_code="USD", credit_limit_minor=1000, actor_label="maker")
    values.update(changes)
    return repository.upsert_customer(**values)


def invoice(repository: Any, number: str = "INV", *, amount: int = 600, currency: str = "USD") -> dict[str, Any]:
    return repository.create_invoice(invoice_number=number, customer_code="CUS", invoice_date="2026-07-01", currency_code=currency, tax_minor=0,
                                     lines=[ReceivableInvoiceLineInput("Synthetic service", "1", amount, amount)], actor_label="maker")


def receipt(repository: Any, *, number: str = "RCT", amount: int = 600, allocations: tuple[ReceiptAllocationInput, ...] = ()) -> dict[str, Any]:
    return repository.post_receipt(receipt_number=number, customer_code="CUS", receipt_date="2026-07-02", currency_code="USD", amount_minor=amount, allocations=allocations, actor_label="cashier")


@pytest.mark.parametrize("history", ["Draft", "Submitted", "Approved", "Paid", "Cancelled", "Receipt"])
def test_customer_currency_is_frozen_by_all_financial_history(database: ReceivablesDatabase, history: str) -> None:
    with database.repository() as repository:
        saved = customer(repository)
        if history == "Receipt":
            receipt(repository)
        else:
            document = invoice(repository)
            if history in {"Submitted", "Approved", "Paid"}:
                repository.submit_invoice(document["id"], expected_version=1, actor_label="maker")
            if history in {"Approved", "Paid"}:
                repository.approve_invoice(document["id"], expected_version=2, actor_label="checker")
            if history == "Paid":
                receipt(repository, allocations=(ReceiptAllocationInput(document["id"], 600),))
            if history == "Cancelled":
                database.cancel_draft(document["id"])
        before = database.evidence_counts()
        with pytest.raises(PlatformError, match="currency.*history|history.*currency"):
            customer(repository, currency_code="EUR")
        assert repository.get_customer(saved["id"])["currency_code"] == "USD"
        assert repository.get_customer(saved["id"])["row_version"] == 1
        assert database.evidence_counts() == before
        assert customer(repository, name="Updated profile", credit_limit_minor=2000)["row_version"] == 2


def test_customer_currency_can_change_before_first_financial_document(database: ReceivablesDatabase) -> None:
    with database.repository() as repository:
        customer(repository)
        updated = customer(repository, currency_code="EUR")
        assert updated["currency_code"] == "EUR"
        assert invoice(repository, currency="EUR")["currency_code"] == "EUR"


@pytest.mark.parametrize("status", ["Draft", "Suspended", "Closed"])
@pytest.mark.parametrize("override", ["", "Synthetic credit exception"])
def test_approval_requires_active_customer_even_with_override(database: ReceivablesDatabase, status: str, override: str) -> None:
    with database.repository() as repository:
        customer(repository)
        document = invoice(repository)
        repository.submit_invoice(document["id"], expected_version=1, actor_label="maker")
        customer(repository, status=status)
        before = database.evidence_counts()
        with pytest.raises(PlatformError, match="Active"):
            repository.approve_invoice(document["id"], expected_version=2, actor_label="checker", credit_override_reason=override)
        assert repository.get_invoice(document["id"])["status"] == "Submitted"
        assert repository.get_invoice(document["id"])["row_version"] == 2
        assert database.evidence_counts() == before


def test_legacy_currency_mismatch_blocks_approval_even_with_override(database: ReceivablesDatabase) -> None:
    with database.repository() as repository:
        saved = customer(repository)
        document = invoice(repository)
        repository.submit_invoice(document["id"], expected_version=1, actor_label="maker")
        database.seed_legacy_currency(saved["id"], "EUR")
        before = database.evidence_counts()
        with pytest.raises(PlatformError, match="currency|currencies"):
            repository.approve_invoice(document["id"], expected_version=2, actor_label="checker", credit_override_reason="Synthetic override")
        assert repository.get_invoice(document["id"])["status"] == "Submitted"
        assert database.evidence_counts() == before


def test_legacy_currency_mismatch_cannot_relabel_credit_exposure(database: ReceivablesDatabase) -> None:
    with database.repository() as repository:
        saved = customer(repository)
        document = invoice(repository)
        repository.submit_invoice(document["id"], expected_version=1, actor_label="maker")
        repository.approve_invoice(document["id"], expected_version=2, actor_label="checker")
        database.seed_legacy_currency(saved["id"], "EUR")
        with pytest.raises(PlatformError, match="currency|currencies"):
            repository.credit_exposure("CUS")


def test_concurrent_approvals_cannot_overrun_customer_credit(database: ReceivablesDatabase) -> None:
    with database.repository() as repository:
        customer(repository)
        documents = [invoice(repository, number) for number in ("INV-A", "INV-B")]
        for document in documents:
            repository.submit_invoice(document["id"], expected_version=1, actor_label="maker")
    barrier = Barrier(2)

    def approve(document: dict[str, Any]) -> str:
        with database.repository() as repository:
            barrier.wait(timeout=10)
            try:
                return str(repository.approve_invoice(document["id"], expected_version=2, actor_label="checker")["status"])
            except PlatformError as exc:
                assert "credit limit" in str(exc)
                return "Blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, documents))
    assert sorted(results) == ["Approved", "Blocked"]
    with database.repository() as repository:
        assert repository.credit_exposure("CUS")["exposure_minor"] == 600


@pytest.mark.parametrize("operation", ["invoice", "receipt"])
def test_customer_currency_update_and_first_document_are_serialized(database: ReceivablesDatabase, operation: str) -> None:
    with database.repository() as repository:
        customer(repository)
    barrier = Barrier(2)

    def change_currency() -> str:
        with database.repository() as repository:
            barrier.wait(timeout=10)
            try:
                customer(repository, currency_code="EUR")
                return "Changed"
            except PlatformError as exc:
                assert "financial history" in str(exc)
                return "Frozen"

    def create_document() -> str:
        with database.repository() as repository:
            barrier.wait(timeout=10)
            try:
                (invoice if operation == "invoice" else receipt)(repository)
                return "Created"
            except PlatformError as exc:
                assert "currency" in str(exc)
                return "Mismatch"

    with ThreadPoolExecutor(max_workers=2) as pool:
        changed, created = pool.submit(change_currency), pool.submit(create_document)
        assert (changed.result(timeout=15), created.result(timeout=15)) in {("Changed", "Mismatch"), ("Frozen", "Created")}


def test_concurrent_first_customer_upserts_cannot_mix_invoice_currencies(database: ReceivablesDatabase) -> None:
    barrier = Barrier(2)

    def create(currency: str) -> str:
        with database.repository() as repository:
            barrier.wait(timeout=10)
            try:
                customer(repository, currency_code=currency)
                invoice(repository, number=currency, currency=currency)
                return "Created"
            except PlatformError as exc:
                assert "currency" in str(exc)
                return "Blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, ("USD", "EUR")))
    assert sorted(results) == ["Blocked", "Created"]
    with database.repository() as repository:
        customers = repository.list_customers(workspace="default")
        documents = repository.list_invoices()
        assert len(customers) == len(documents) == 1
        assert customers[0]["currency_code"] == documents[0]["currency_code"]


@pytest.mark.parametrize("operation", ["invoice", "receipt", "approval"])
def test_customer_suspend_commit_is_seen_by_waiting_financial_operation(
    database: ReceivablesDatabase, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    with database.repository() as repository:
        customer(repository)
        document = invoice(repository)
        repository.submit_invoice(document["id"], expected_version=1, actor_label="maker")
    written, release, started = Event(), Event(), Event()
    target: Any = import_module("reconforge.infrastructure.sqlite_receivables") if database.path is not None else PostgresReceivablesRepository
    attribute = "_finalize_event" if database.path is not None else "_event"
    original = getattr(target, attribute)

    def pause_customer_commit(*args: Any, **kwargs: Any) -> Any:
        if kwargs["action"] == "ar_customer_saved":
            written.set()
            assert release.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, attribute, pause_customer_commit)

    def suspend() -> None:
        with database.repository() as repository:
            customer(repository, status="Suspended")

    def transact() -> str:
        with database.repository() as repository:
            started.set()
            try:
                if operation == "invoice":
                    invoice(repository, "INV-SECOND")
                elif operation == "receipt":
                    receipt(repository)
                else:
                    repository.approve_invoice(document["id"], expected_version=2, actor_label="checker")
            except PlatformError as exc:
                return str(exc)
            return "Unexpected success"

    with ThreadPoolExecutor(max_workers=2) as pool:
        suspended = pool.submit(suspend)
        try:
            assert written.wait(timeout=10)
            operation_result = pool.submit(transact)
            assert started.wait(timeout=10)
            # Give the independent operation an opportunity to read while the
            # status write is uncommitted; a correct lock waits for the commit.
            with pytest.raises(TimeoutError):
                operation_result.result(timeout=0.2)
        finally:
            release.set()
        suspended.result(timeout=10)
        assert "Active" in operation_result.result(timeout=10)


@pytest.mark.parametrize("failure", ["audit", "outbox"])
@pytest.mark.parametrize("operation", ["approval", "customer", "invoice", "receipt"])
def test_failed_evidence_rolls_back_customer_credit_and_document_effects(
    database: ReceivablesDatabase, monkeypatch: pytest.MonkeyPatch, failure: str, operation: str,
) -> None:
    with database.repository() as repository:
        saved = customer(repository)
        document = invoice(repository)
        repository.submit_invoice(document["id"], expected_version=1, actor_label="maker")
        before = database.evidence_counts()

        def fail(*_args: Any, **_kwargs: Any) -> None:
            raise AuditLedgerError("Synthetic AR evidence failure")

        with monkeypatch.context() as patch:
            if database.path is not None:
                import reconforge.platform.common as common

                module = import_module("reconforge.infrastructure.sqlite_receivables")
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
            with pytest.raises((PlatformError, PostgresReceivablesError, AuditLedgerError)):
                if operation == "approval":
                    repository.approve_invoice(document["id"], expected_version=2, actor_label="checker")
                elif operation == "customer":
                    customer(repository, status="Suspended", credit_limit_minor=0)
                elif operation == "invoice":
                    invoice(repository, "INV-FAILED")
                else:
                    receipt(repository)
        assert repository.get_invoice(document["id"])["status"] == "Submitted"
        assert repository.get_invoice(document["id"])["row_version"] == 2
        assert repository.get_customer(saved["id"])["status"] == "Active"
        assert repository.get_customer(saved["id"])["credit_limit_minor"] == 1000
        assert repository.get_customer(saved["id"])["row_version"] == 1
        assert len(repository.list_invoices()) == 1
        assert database.evidence_counts() == before
        # The failed receipt/invoice can be retried with its same business ID.
        if operation == "receipt":
            assert receipt(repository)["amount_minor"] == 600
        elif operation == "invoice":
            assert invoice(repository, "INV-FAILED")["status"] == "Draft"
        else:
            assert repository.approve_invoice(document["id"], expected_version=2, actor_label="checker")["status"] == "Approved"
