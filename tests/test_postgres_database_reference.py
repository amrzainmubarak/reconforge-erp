from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from reconforge.connectors.database_reference import DatabaseQueryProfile
from reconforge.connectors.network import ConnectorNetworkError
from reconforge.connectors.postgres_database_reference import (
    POSTGRES_DATABASE_MANIFEST,
    PostgresDatabaseConnector,
    PostgresNamedQueryTransport,
    postgres_database_registration,
)
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings


class _Cursor:
    def __init__(self, rows: tuple[tuple[object, ...], ...] = ()) -> None:
        self.rows = rows

    def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...] | None]] = []
        self.closed = False

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> _Cursor:
        self.statements.append((sql, params))
        if "FROM reconforge_connector_statement_lines" in sql:
            return _Cursor((("tenant-a", "r-1", Decimal("0E-18"), "USD", date(2026, 8, 2), "ref-1"),))
        return _Cursor()

    def close(self) -> None:
        self.closed = True


def test_postgres_manifest_and_transport_are_named_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Connection()

    class _Psycopg:
        @staticmethod
        def connect(dsn: str, **kwargs: object) -> _Connection:
            assert dsn == "postgresql://user:password@localhost:55433/postgres"
            assert kwargs["options"] == "-c statement_timeout=30000"
            return connection

    monkeypatch.setitem(sys.modules, "psycopg", _Psycopg())
    endpoint = "postgresql://localhost:55433/postgres"
    registration = postgres_database_registration(
        endpoint=endpoint,
        credential_reference="secret/postgres",
        tenant_id="tenant-a",
    )
    rows = PostgresNamedQueryTransport().fetch_named(
        endpoint,
        tenant_id="tenant-a",
        query_profile=DatabaseQueryProfile.STATEMENT_LINES_V1,
        cursor=None,
        credential=b"postgresql://user:password@localhost:55433/postgres",
        maximum_rows=10,
        maximum_cell_characters=1_000,
    )
    assert registration.manifest.kind.value == "database_source"
    assert registration.manifest.capabilities == frozenset({"read"})
    assert rows[0].amount == "0"
    assert connection.closed
    assert any(sql == "SET TRANSACTION READ ONLY" for sql, _ in connection.statements)
    query = next(sql for sql, _ in connection.statements if "FROM reconforge_connector_statement_lines" in sql)
    assert "tenant-a" not in query
    assert "SELECT *" not in query


def test_postgres_registration_pins_endpoint_and_rejects_free_form_credentials() -> None:
    endpoint = "postgresql://localhost:55433/postgres"
    registration = postgres_database_registration(
        endpoint=endpoint,
        credential_reference="secret/postgres",
        tenant_id="tenant-a",
    )
    assert registration.manifest is not POSTGRES_DATABASE_MANIFEST
    with pytest.raises(ConnectorNetworkError, match="endpoint_credential_mismatch|credential_invalid"):
        PostgresNamedQueryTransport().fetch_named(
            endpoint,
            tenant_id="tenant-a",
            query_profile=DatabaseQueryProfile.STATEMENT_LINES_V1,
            cursor=None,
            credential=b"postgresql://user:password@other-host:55433/postgres",
            maximum_rows=10,
            maximum_cell_characters=1_000,
        )


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_postgres_named_query_is_read_only_and_tenant_isolated() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("live PostgreSQL connector test requires a non-privileged application role")
    if not app_user.replace("_", "").isalnum() or not app_user[0].isalpha():
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    parsed = urlsplit(dsn)
    endpoint = f"postgresql://{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
    token = uuid4().hex[:12]
    tenant_a = f"connector_a_{token}"
    tenant_b = f"connector_b_{token}"
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            admin.execute(
                """
                CREATE TABLE IF NOT EXISTS reconforge_connector_statement_lines (
                    tenant_id text NOT NULL,
                    record_id text NOT NULL,
                    amount numeric(38,18) NOT NULL,
                    currency text NOT NULL,
                    business_date date NOT NULL,
                    reference text NOT NULL,
                    PRIMARY KEY (tenant_id, record_id)
                )
                """
            )
            admin.execute("ALTER TABLE reconforge_connector_statement_lines ENABLE ROW LEVEL SECURITY")
            admin.execute(
                """
                DO $$
                BEGIN
                    CREATE POLICY reconforge_connector_tenant_policy
                    ON reconforge_connector_statement_lines
                    USING (tenant_id = current_setting('reconforge.connector_tenant', true));
                EXCEPTION WHEN duplicate_object THEN NULL;
                END
                $$
                """
            )
            admin.execute(f"GRANT SELECT ON reconforge_connector_statement_lines TO {app_user}")
            for tenant, record_id, amount in ((tenant_a, "r-1", "10.00"), (tenant_a, "r-2", "20.00"), (tenant_b, "r-1", "99.00")):
                admin.execute(
                    """
                    INSERT INTO reconforge_connector_statement_lines
                        (tenant_id, record_id, amount, currency, business_date, reference)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, record_id) DO UPDATE SET amount = EXCLUDED.amount
                    """,
                    (tenant, f"{record_id}-{token}", amount, "USD", date(2026, 8, 2), f"ref-{record_id}-{token}"),
                )
    finally:
        admin.close()

    class _Secrets:
        def resolve(self, reference: str) -> bytes:
            assert reference == "secret/postgres"
            return dsn.encode("ascii")

    factory = PostgresNamedQueryTransport()
    connector_registration = postgres_database_registration(
        endpoint=endpoint,
        credential_reference="secret/postgres",
        tenant_id=tenant_a,
    ).model_copy(update={"maximum_rows": 2})
    connector = PostgresDatabaseConnector(factory, _Secrets(), connector_registration)
    first = connector.read_rows(idempotency_key="live-postgres-1")
    replay = connector.read_rows(idempotency_key="live-postgres-1")
    assert [row.amount for row in first.rows] == ["10", "20"]
    assert first.response_digest == replay.response_digest
    assert first.next_cursor == f"r-2-{token}"
    page = connector.read_rows(idempotency_key="live-postgres-2", cursor=first.next_cursor)
    assert page.rows == ()

    sibling = PostgresDatabaseConnector(
        factory,
        _Secrets(),
        postgres_database_registration(
            endpoint=endpoint,
            credential_reference="secret/postgres",
            tenant_id=tenant_b,
        ),
    )
    assert [row.amount for row in sibling.read_rows(idempotency_key="live-postgres-3").rows] == ["99"]

    with pytest.raises(ConnectorNetworkError, match="endpoint_credential_mismatch"):
        factory.fetch_named(
            endpoint,
            tenant_id=tenant_a,
            query_profile=DatabaseQueryProfile.STATEMENT_LINES_V1,
            cursor=None,
            credential=b"postgresql://reconforge_app:wrong@different-host/postgres",
            maximum_rows=10,
            maximum_cell_characters=1_000,
        )
