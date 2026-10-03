"""Database guards reject new financial effects on retained unverified AR money."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from reconforge.db import connect, run_migrations
from reconforge.infrastructure.finance_policy_store import FinancePolicyStore
from reconforge.infrastructure.receivables_policy_schema import (
    POSTGRES_RECEIVABLES_POLICY_SCHEMA_SQL,
    SQLITE_RECEIVABLES_POLICY_MIGRATION_SQL,
)
from reconforge.platform.common import ensure_workspace
from tests.test_alembic_postgres import isolated_postgres_migration_dsn

__all__ = ["isolated_postgres_migration_dsn"]

TENANT = "ar_raw_policy"
TABLES = ("ar_customers", "ar_invoices", "ar_invoice_lines", "ar_receipts", "ar_receipt_allocations")
LEGACY_MUTATIONS = {
    "customer_credit": "UPDATE ar_customers SET credit_limit_minor=20000 WHERE id='legacy'",
    "invoice_approval": "UPDATE ar_invoices SET status='Approved' WHERE id='invoice'",
    "invoice_amount": "UPDATE ar_invoices SET subtotal_minor=1200,total_minor=1200 WHERE id='invoice'",
    "invoice_tax": "UPDATE ar_invoices SET tax_minor=200,total_minor=1200 WHERE id='invoice'",
    "invoice_date": "UPDATE ar_invoices SET due_date='2026-02-01' WHERE id='invoice'",
    "line_amount": "UPDATE ar_invoice_lines SET unit_price_minor=1200,line_total_minor=1200 WHERE id='line'",
    "line_reparent": "UPDATE ar_invoice_lines SET invoice_id='captured-invoice' WHERE id='line'",
    "line_delete": "DELETE FROM ar_invoice_lines WHERE id='line'",
    "receipt_amount": "UPDATE ar_receipts SET amount_minor=600 WHERE id='receipt'",
    "receipt_cancellation": "UPDATE ar_receipts SET status='Cancelled' WHERE id='receipt'",
    "receipt_date": "UPDATE ar_receipts SET receipt_date='2026-02-01' WHERE id='receipt'",
    "allocation_amount": "UPDATE ar_receipt_allocations SET amount_minor=20 WHERE id='allocation'",
    "allocation_reparent": "UPDATE ar_receipt_allocations SET invoice_id='captured-invoice' WHERE id='allocation'",
    "allocation_delete": "DELETE FROM ar_receipt_allocations WHERE id='allocation'",
}


class RawDatabase:
    def __init__(self, connection: Any, workspace: str, *, postgres: bool = False, admin_dsn: str = "", app_dsn: str = "") -> None:
        self.connection = connection
        self.workspace = workspace
        self.postgres = postgres
        self.admin_dsn = admin_dsn
        self.app_dsn = app_dsn

    def insert(self, table: str, values: dict[str, Any]) -> None:
        assert table in TABLES
        if self.postgres:
            values = {"tenant_id": TENANT, **values}
        placeholder = "%s" if self.postgres else "?"
        columns = ",".join(values)
        markers = ",".join(placeholder for _ in values)
        self.connection.execute(f"INSERT INTO {table}({columns}) VALUES({markers})", tuple(values.values()))

    def retained_rows(self) -> dict[str, list[tuple[Any, ...]]]:
        return {table: [tuple(row) for row in self.connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()] for table in TABLES}

    def deny(self, operation: Any) -> None:
        before = self.retained_rows()
        self.connection.execute("SAVEPOINT raw_policy_probe")
        try:
            with pytest.raises(Exception) as rejected:
                operation()
            error = rejected.value
            if self.postgres:
                assert getattr(error, "sqlstate", None) in {"23503", "23514", "P0001", "42501"}, repr(error)
            else:
                assert isinstance(error, sqlite3.IntegrityError), repr(error)
                assert any(word in str(error).lower() for word in ("policy", "policies", "immutable", "foreign key", "legacy")), str(error)
        finally:
            self.connection.execute("ROLLBACK TO raw_policy_probe")
            self.connection.execute("RELEASE raw_policy_probe")
        assert self.retained_rows() == before


def customer(database: RawDatabase, identity: str, *, currency: str = "USD", policy: dict[str, Any] | None = None) -> None:
    database.insert("ar_customers", {"id": identity, "workspace_id": database.workspace, "customer_code": identity.upper(),
        "name": "Synthetic", "currency_code": currency, "credit_limit_minor": 10000,
        "created_at": "2026-01-01", "updated_at": "2026-01-01", **(policy or {})})


def invoice(database: RawDatabase, identity: str, parent: str, *, policy: dict[str, Any] | None = None) -> None:
    database.insert("ar_invoices", {"id": identity, "workspace_id": database.workspace, "customer_id": parent,
        "invoice_number": identity.upper(), "invoice_date": "2026-01-01", "due_date": "2026-01-01", "currency_code": "USD",
        "subtotal_minor": 1000, "tax_minor": 0, "total_minor": 1000, "status": "Submitted",
        "created_at": "2026-01-01", "updated_at": "2026-01-01", **(policy or {})})


def line(database: RawDatabase, identity: str, parent: str, number: int) -> None:
    values = {"id": identity, "invoice_id": parent, "line_number": number, "quantity": "1",
              "unit_price_minor": 1000, "tax_minor": 0, "line_total_minor": 1000, "created_at": "2026-01-01"}
    if database.postgres:
        values["quantity_text"] = "1"
    database.insert("ar_invoice_lines", values)


def seed_legacy(database: RawDatabase) -> None:
    customer(database, "legacy")
    invoice(database, "invoice", "legacy")
    line(database, "line", "invoice", 1)
    database.insert("ar_receipts", {"id": "receipt", "workspace_id": database.workspace, "customer_id": "legacy",
        "receipt_number": "SYN-RECEIPT", "receipt_date": "2026-01-01", "currency_code": "USD", "amount_minor": 500,
        "status": "Posted", "created_at": "2026-01-01", "updated_at": "2026-01-01"})
    database.insert("ar_receipt_allocations", {"id": "allocation", "workspace_id": database.workspace,
        "receipt_id": "receipt", "invoice_id": "invoice", "amount_minor": 10, "created_at": "2026-01-01"})


def seed_captured(database: RawDatabase) -> None:
    policy, _ = FinancePolicyStore(database.connection, tenant_id=TENANT if database.postgres else None).capture(
        workspace_id=database.workspace, currency_code="USD", minor_units=2, actor_label="synthetic",
    )
    customer(database, "captured", policy=policy.metadata())
    invoice(database, "captured-invoice", "captured", policy=policy.metadata())


@pytest.fixture(scope="module")
def sqlite_legacy_policy_database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("ar-policy-raw") / "legacy.db"
    run_migrations(path, target_version=48)
    with closing(connect(path)) as connection:
        workspace = ensure_workspace(connection, "default")
        database = RawDatabase(connection, workspace)
        seed_legacy(database)
        connection.commit()
        connection.executescript(SQLITE_RECEIVABLES_POLICY_MIGRATION_SQL)
        seed_captured(database)
        connection.commit()
    return path


@pytest.fixture
def sqlite_raw_policy(sqlite_legacy_policy_database: Path) -> Iterator[RawDatabase]:
    with closing(connect(sqlite_legacy_policy_database)) as connection:
        workspace = str(connection.execute("SELECT workspace_id FROM ar_customers WHERE id='legacy'").fetchone()[0])
        try:
            yield RawDatabase(connection, workspace)
        finally:
            connection.rollback()


@pytest.fixture
def postgres_raw_policy(isolated_postgres_migration_dsn: str) -> Iterator[RawDatabase]:
    psycopg = pytest.importorskip("psycopg")
    from alembic.config import Config

    from alembic import command
    from reconforge.infrastructure.postgres import set_local_tenant_scope

    app_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_DSN")
    if not app_dsn:
        pytest.skip("requires a disposable nonowner PostgreSQL role; PROD033 raw-policy review 2026-10-03")
    command.upgrade(Config("alembic.ini"), "0098_pg_finance_posting")
    params = psycopg.conninfo.conninfo_to_dict(app_dsn)
    params["dbname"] = psycopg.conninfo.conninfo_to_dict(isolated_postgres_migration_dsn)["dbname"]
    with psycopg.connect(isolated_postgres_migration_dsn) as admin:
        admin.execute("SET LOCAL search_path TO reconforge,pg_catalog")
        admin.execute("INSERT INTO tenants(id,name) VALUES(%s,'Synthetic raw policy')", (TENANT,))
        admin.execute("INSERT INTO domain_workspaces(tenant_id,id,name) VALUES(%s,'workspace','Synthetic')", (TENANT,))
        for currency in ("USD", "EUR", "ZZZ"):
            admin.execute("INSERT INTO currencies(tenant_id,code,name,minor_units) VALUES(%s,%s,'Synthetic',2)", (TENANT, currency))
        database = RawDatabase(admin, "workspace", postgres=True)
        seed_legacy(database)
        admin.execute(POSTGRES_RECEIVABLES_POLICY_SCHEMA_SQL)
        seed_captured(database)
        role = psycopg.sql.Identifier(params["user"])
        admin.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(role))
        admin.execute(psycopg.sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(role))
    target_app_dsn = psycopg.conninfo.make_conninfo(**params)
    with psycopg.connect(target_app_dsn) as connection:
        try:
            safety = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            assert safety == (False, False)
            assert connection.execute("SELECT tableowner<>current_user FROM pg_tables WHERE schemaname='reconforge' AND tablename='ar_customers'").fetchone()[0]
            set_local_tenant_scope(connection, TENANT, workspace_id="workspace")
            connection.execute("SET LOCAL search_path TO reconforge,pg_catalog")
            yield RawDatabase(connection, "workspace", postgres=True, admin_dsn=isolated_postgres_migration_dsn, app_dsn=target_app_dsn)
        finally:
            connection.rollback()


@pytest.mark.parametrize("case", LEGACY_MUTATIONS)
def test_sqlite_legacy_financial_raw_mutations_are_denied(sqlite_raw_policy: RawDatabase, case: str) -> None:
    database = sqlite_raw_policy
    database.deny(lambda: database.connection.execute(LEGACY_MUTATIONS[case]))


def test_sqlite_new_line_cannot_attach_to_legacy_invoice(sqlite_raw_policy: RawDatabase) -> None:
    sqlite_raw_policy.deny(lambda: line(sqlite_raw_policy, "extra", "invoice", 2))


def test_postgres_nonowner_legacy_financial_raw_mutations_are_denied(postgres_raw_policy: RawDatabase) -> None:
    database = postgres_raw_policy
    for case, statement in LEGACY_MUTATIONS.items():
        try:
            database.deny(lambda sql=statement: database.connection.execute(sql))
        except AssertionError as exc:
            raise AssertionError(f"Legacy raw mutation was not safely denied: {case}") from exc
    database.deny(lambda: line(database, "extra", "invoice", 2))


FORGED_POLICIES = (("USD", "currency_precision", 3), ("USD", "currency_registry_version", "synthetic-forged-version"), ("ZZZ", None, None))


def reject_forged_policy(database: RawDatabase, currency: str, field: str | None, value: Any) -> None:
    policy, _ = FinancePolicyStore(database.connection, tenant_id=TENANT if database.postgres else None).capture(
        workspace_id=database.workspace, currency_code="USD", minor_units=2, actor_label="synthetic",
    )
    values = policy.metadata()
    if field is not None:
        values[field] = value
    database.deny(lambda: customer(database, "forged", currency=currency, policy=values))


@pytest.mark.parametrize("currency,field,value", FORGED_POLICIES)
def test_sqlite_raw_policy_tuple_must_match_retained_snapshot(sqlite_raw_policy: RawDatabase, currency: str, field: str | None, value: Any) -> None:
    reject_forged_policy(sqlite_raw_policy, currency, field, value)


def test_postgres_nonowner_raw_policy_tuple_must_match_retained_snapshot(postgres_raw_policy: RawDatabase) -> None:
    for currency, field, value in FORGED_POLICIES:
        reject_forged_policy(postgres_raw_policy, currency, field, value)


def reject_missing_policy(database: RawDatabase) -> None:
    database.deny(lambda: customer(database, "new-unverified"))
    database.deny(lambda: invoice(database, "new-unverified", "legacy"))
    database.deny(lambda: database.insert("ar_receipts", {
        "id": "new-unverified", "workspace_id": database.workspace, "customer_id": "legacy",
        "receipt_number": "NEW-UNVERIFIED", "receipt_date": "2026-01-01", "currency_code": "USD",
        "amount_minor": 500, "status": "Posted", "created_at": "2026-01-01", "updated_at": "2026-01-01",
    }))


def test_sqlite_new_parent_records_require_captured_policy(sqlite_raw_policy: RawDatabase) -> None:
    reject_missing_policy(sqlite_raw_policy)


def test_postgres_nonowner_new_parent_records_require_captured_policy(postgres_raw_policy: RawDatabase) -> None:
    reject_missing_policy(postgres_raw_policy)


def test_postgres_customer_currency_change_sees_hidden_child_through_fk(postgres_raw_policy: RawDatabase) -> None:
    psycopg = pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import set_local_tenant_scope

    database = postgres_raw_policy
    with psycopg.connect(database.admin_dsn) as admin:
        for identity in ("org-visible", "org-hidden"):
            admin.execute("INSERT INTO reconforge.organizations(tenant_id,id,name,organization_code,application_workspace_id) VALUES(%s,%s,'Synthetic',%s,'workspace')", (TENANT, identity, identity.upper()))
            admin.execute("INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES(%s,'workspace',%s)", (TENANT, identity))
        admin.execute("UPDATE reconforge.ar_customers SET organization_id='org-visible' WHERE tenant_id=%s AND id='captured'", (TENANT,))
        # Retain a cross-attributed child to exercise history invisibility, not a public creation path.
        admin.execute("UPDATE reconforge.ar_invoices SET organization_id='org-hidden' WHERE tenant_id=%s AND id='captured-invoice'", (TENANT,))
    set_local_tenant_scope(database.connection, TENANT, workspace_id="workspace", organization_id="org-visible")
    assert database.connection.execute("SELECT count(*) FROM ar_customers WHERE id='captured'").fetchone()[0] == 1
    assert database.connection.execute("SELECT count(*) FROM ar_invoices WHERE customer_id='captured'").fetchone()[0] == 0
    before = database.retained_rows()
    with pytest.raises(psycopg.errors.ForeignKeyViolation), database.connection.transaction():
        database.connection.execute("UPDATE ar_customers SET currency_code='EUR' WHERE id='captured'")
    assert database.retained_rows() == before


@pytest.mark.parametrize("first", ["child", "parent"])
def test_postgres_customer_currency_and_child_creation_serialize(postgres_raw_policy: RawDatabase, first: str) -> None:
    psycopg = pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import set_local_tenant_scope

    database = postgres_raw_policy
    with psycopg.connect(database.admin_dsn) as admin:
        admin.execute("SET LOCAL search_path TO reconforge,pg_catalog")
        owner = RawDatabase(admin, "workspace", postgres=True)
        policy, _ = FinancePolicyStore(admin, tenant_id=TENANT).capture(workspace_id="workspace", currency_code="USD", minor_units=2, actor_label="synthetic")
        customer(owner, "racing", policy=policy.metadata())

    def prepare(connection: Any) -> RawDatabase:
        set_local_tenant_scope(connection, TENANT, workspace_id="workspace")
        connection.execute("SET LOCAL search_path TO reconforge,pg_catalog")
        connection.execute("SET LOCAL lock_timeout='10s'")
        return RawDatabase(connection, "workspace", postgres=True)

    def mutate(target: RawDatabase, kind: str) -> None:
        if kind == "child":
            invoice(target, "race-invoice", "racing", policy=policy.metadata())
        else:
            target.connection.execute("UPDATE ar_customers SET currency_code='EUR' WHERE id='racing'")

    with psycopg.connect(database.app_dsn) as first_connection, psycopg.connect(database.app_dsn) as second_connection:
        first_database, second_database = prepare(first_connection), prepare(second_connection)
        mutate(first_database, first)

        def waiting_mutation() -> str:
            try:
                mutate(second_database, "parent" if first == "child" else "child")
                second_connection.commit()
                return "accepted"
            except psycopg.Error as exc:
                second_connection.rollback()
                return str(exc.sqlstate)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(waiting_mutation)
            try:
                observed_lock = False
                with psycopg.connect(database.admin_dsn, autocommit=True) as observer:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline and not future.done():
                        row = observer.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (second_connection.info.backend_pid,)).fetchone()
                        if row and row[0] == "Lock":
                            observed_lock = True
                            break
                        time.sleep(0.02)
                assert observed_lock, "Competing parent/child write did not wait on the resource lock"
            finally:
                first_connection.commit()
            assert future.result(timeout=10) in {"23503", "P0001"}
    stored = database.connection.execute("SELECT currency_code FROM ar_customers WHERE id='racing'").fetchone()[0]
    count = database.connection.execute("SELECT count(*) FROM ar_invoices WHERE customer_id='racing'").fetchone()[0]
    assert (stored, count) == (("USD", 1) if first == "child" else ("EUR", 0))
