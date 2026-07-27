"""Contract, balance, and optional live-isolation tests for the PostgreSQL ledger boundary."""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_ledger import (
    POSTGRES_LEDGER_SCHEMA_SQL,
    LedgerLine,
    PostgresLedgerIntegrityError,
    PostgresLedgerNotFoundError,
    PostgresLedgerRepository,
    PostgresLedgerValidationError,
    _hash_payload,
)
from reconforge.infrastructure.postgres_master_data import (
    POSTGRES_MASTER_DATA_SCHEMA_SQL,
    PostgresMasterDataRepository,
)


class _Cursor:
    def __init__(self, row: tuple[Any, ...] | None = None, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.row = row
        self.rows = rows or []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.commits = 0
        self.entry_row = (
            "tenant_a",
            "entry-a",
            "JE-001",
            "org-a",
            "USD",
            date(2026, 1, 31),
            "Month-end",
            "Posted",
            "Manual",
            None,
            "fingerprint",
            "created",
            "posted",
        )
        self.line_rows = [
            ("tenant_a", "entry-a", 1, "cash-a", "", "", "100.00", "0"),
            ("tenant_a", "entry-a", 2, "revenue-a", "", "", "0", "100.00"),
        ]
        self.account_row = (
            "tenant_a",
            "org-a",
            "org-a",
            "1000",
            "Cash",
            "Asset",
            "Debit",
            True,
            "created",
            "updated",
        )

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "select entry_fingerprint, status" in normalized:
            return _Cursor(row=None)
        if "insert into reconforge.ledger_accounts" in normalized:
            return _Cursor(row=self.account_row)
        if normalized.startswith("update reconforge.ledger_entries"):
            return _Cursor(row=self.entry_row)
        if "select event_hash from reconforge.audit_events" in normalized:
            return _Cursor(row=None)
        if "select tenant_id, id, entry_number" in normalized:
            return _Cursor(row=self.entry_row)
        if "select tenant_id, entry_id, line_number" in normalized:
            return _Cursor(rows=self.line_rows)
        return _Cursor()

    def commit(self) -> None:
        self.commits += 1


class _TrialBalanceConnection(_FakeConnection):
    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "select id, name, start_date, end_date" in normalized:
            return _Cursor(row=("period-a", "2026-07", date(2026, 7, 1), date(2026, 7, 31)))
        if "select distinct entries.currency_code" in normalized:
            return _Cursor(rows=[("USD",)])
        if "select minor_units from reconforge.currencies" in normalized:
            return _Cursor(row=(2,))
        if "select accounts.account_code" in normalized:
            return _Cursor(rows=[("1000", "Cash", "Asset", "Debit", "100.00", "0")])
        return super().execute(sql, params)


class _AuditConnection(_FakeConnection):
    def __init__(self, *, tampered: bool = False, metadata_json: str = '{"source":"test"}') -> None:
        super().__init__()
        event_hash = _hash_payload(
            {
                "tenant_id": "tenant_a",
                "event_id": "event-1",
                "actor_id": "controller",
                "action": "ledger_entry_posted",
                "resource_type": "ledger_entry",
                "resource_id": "entry-a",
                "occurred_at": "2026-07-23T00:00:00Z",
                "request_id": "request-1",
                "before_state_hash": "",
                "after_state_hash": "after-hash",
                "previous_event_hash": "",
                "reason": "close",
                "metadata": metadata_json,
            }
        )
        self.audit_row = (
            1,
            "tenant_a",
            "event-1",
            "controller",
            "ledger_entry_posted",
            "ledger_entry",
            "entry-a",
            "2026-07-23T00:00:00Z",
            "request-1",
            "",
            "after-hash",
            "",
            "tampered" if tampered else event_hash,
            "close",
            metadata_json,
        )

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "from reconforge.audit_events" in normalized:
            return _Cursor(rows=[self.audit_row])
        return super().execute(sql, params)


def test_ledger_schema_enforces_balance_immutability_audit_and_tenant_scope() -> None:
    assert "NUMERIC(38,18)" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "CHECK ((debit_amount > 0 AND credit_amount = 0)" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "assert_ledger_entry_balanced" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "Posted ledger entries are immutable" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "Audit events are append-only" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "DEFERRABLE INITIALLY DEFERRED" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_LEDGER_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_LEDGER_SCHEMA_SQL


def test_post_entry_is_exact_parameterized_and_atomic_without_repository_commit() -> None:
    connection = _FakeConnection()
    repository = PostgresLedgerRepository(connection)

    result = repository.post_entry(
        tenant_id="TENANT_A",
        entry_id="ENTRY-A",
        entry_number="je-001",
        organization_id="ORG-A",
        currency_code="usd",
        posting_date="2026-01-31",
        description="Month-end",
        lines=(
            LedgerLine(account_id="cash-a", debit="100.00", credit="0"),
            LedgerLine(account_id="revenue-a", debit="0", credit="100.00"),
        ),
        actor_id="controller@example.test",
        request_id="request-1",
        reason="close",
        metadata={"source": "test"},
    )

    assert result["id"] == "entry-a"
    assert result["lines"][0]["line_number"] == 1
    assert connection.commits == 0
    assert any("INSERT INTO reconforge.audit_events" in sql for sql, _ in connection.executed)
    assert any("INSERT INTO reconforge.outbox_events" in sql for sql, _ in connection.executed)
    assert any(params is not None and "tenant_a" in params for _, params in connection.executed)


def test_account_upsert_can_append_atomic_audit_and_outbox_evidence() -> None:
    connection = _FakeConnection()
    repository = PostgresLedgerRepository(connection)

    result = repository.upsert_account(
        tenant_id="tenant_a",
        organization_id="org-a",
        account_id="org-a",
        account_code="1000",
        name="Cash",
        actor_id="controller@example.test",
        request_id="request-account-1",
        reason="configure chart",
        metadata={"source": "test"},
    )

    assert result["account_code"] == "1000"
    assert any("INSERT INTO reconforge.audit_events" in sql for sql, _ in connection.executed)
    assert any("INSERT INTO reconforge.outbox_events" in sql for sql, _ in connection.executed)
    assert connection.commits == 0


@pytest.mark.parametrize(
    "lines",
    [
        (LedgerLine(account_id="cash-a", debit="100.00", credit="0"),),
        (
            LedgerLine(account_id="cash-a", debit="100.00", credit="0"),
            LedgerLine(account_id="revenue-a", debit="0", credit="99.99"),
        ),
        (
            LedgerLine(account_id="cash-a", debit="100.00", credit="1.00"),
            LedgerLine(account_id="revenue-a", debit="0", credit="99.00"),
        ),
        (
            LedgerLine(account_id="cash-a", debit=1.25, credit="0"),
            LedgerLine(account_id="revenue-a", debit="0", credit="1.25"),
        ),
    ],
)
def test_post_entry_rejects_invalid_or_unbalanced_financial_values(lines: tuple[LedgerLine, ...]) -> None:
    connection = _FakeConnection()
    repository = PostgresLedgerRepository(connection)
    with pytest.raises(PostgresLedgerValidationError):
        repository.post_entry(
            tenant_id="tenant_a",
            entry_id="entry-a",
            entry_number="JE-001",
            organization_id="org-a",
            currency_code="USD",
            posting_date="2026-01-31",
            description="Invalid",
            lines=lines,
            actor_id="controller",
        )
    assert connection.executed == []


def test_post_entry_rejects_precision_and_missing_amount_without_zero_fallback() -> None:
    repository = PostgresLedgerRepository(_FakeConnection())
    with pytest.raises(PostgresLedgerValidationError):
        repository.post_entry(
            tenant_id="tenant_a",
            entry_id="entry-a",
            entry_number="JE-001",
            organization_id="org-a",
            currency_code="USD",
            posting_date="2026-01-31",
            description="Invalid",
            lines=(
                LedgerLine(account_id="cash-a", debit=None, credit="0"),
                LedgerLine(account_id="revenue-a", debit="0", credit="1"),
            ),
            actor_id="controller",
        )


def test_trial_balance_aggregates_exact_posted_amounts_for_a_fiscal_period() -> None:
    repository = PostgresLedgerRepository(_TrialBalanceConnection())

    result = repository.trial_balance(
        tenant_id="tenant_a",
        organization_id="org-a",
        organization_code="ORG-A",
        period_id="period-a",
    )

    assert result["currency_code"] == "USD"
    assert result["totals"] == {
        "debit_minor": 10000,
        "credit_minor": 0,
        "balanced": False,
        "debit": "100.00",
        "credit": "0.00",
    }
    assert result["accounts"][0]["balance"] == "100.00"


def test_trial_balance_requires_a_postgres_fiscal_period() -> None:
    with pytest.raises(PostgresLedgerNotFoundError):
        PostgresLedgerRepository(_FakeConnection()).trial_balance(
            tenant_id="tenant_a",
            organization_id="org-a",
            organization_code="ORG-A",
            period_id="period-a",
        )


def test_postgres_audit_events_list_and_verify_are_tenant_scoped() -> None:
    repository = PostgresLedgerRepository(_AuditConnection())

    events = repository.list_audit_events(tenant_id="TENANT_A", limit=10)
    verification = repository.verify_audit_events(tenant_id="TENANT_A")

    assert events[0]["event_id"] == "event-1"
    assert events[0]["metadata"] == {"source": "test"}
    assert verification == {"ok": True, "checked_events": 1, "head_hash": events[0]["event_hash"], "issues": []}


def test_postgres_audit_verification_detects_tampering() -> None:
    result = PostgresLedgerRepository(_AuditConnection(tampered=True)).verify_audit_events(tenant_id="tenant_a")

    assert result["ok"] is False
    assert result["checked_events"] == 1
    assert result["issues"] == [{"sequence": 1, "message": "Audit event hash does not match row content."}]


def test_postgres_audit_metadata_corruption_is_not_normalized_into_valid_evidence() -> None:
    repository = PostgresLedgerRepository(_AuditConnection(metadata_json='{"source":"a","source":"b"}'))

    with pytest.raises(PostgresLedgerIntegrityError, match="audit metadata is invalid"):
        repository.list_audit_events(tenant_id="tenant_a")

    verification = repository.verify_audit_events(tenant_id="tenant_a")
    assert verification["ok"] is False
    assert {issue["message"] for issue in verification["issues"]} >= {
        "Audit event metadata is invalid.",
    }


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_postgres_ledger_is_balanced_immutable_and_tenant_isolated() -> None:
    psycopg = pytest.importorskip("psycopg")
    from reconforge.infrastructure.postgres import install_postgres_rls_schema

    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    admin = admin_factory.connect()
    app = factory.connect()
    tenant_a = "ledger_a"
    tenant_b = "ledger_b"
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, reconforge.organizations, "
                    f"reconforge.currencies, reconforge.ledger_accounts, reconforge.ledger_entries, "
                    f"reconforge.ledger_lines, reconforge.audit_events, reconforge.outbox_events TO {app_user}"
                )
                admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
        role = app.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("live ledger test requires a non-superuser, non-BYPASSRLS application role")

        for tenant_id, name in ((tenant_a, "Ledger A"), (tenant_b, "Ledger B")):
            with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                connection.execute(
                    "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tenant_id, name),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            master = PostgresMasterDataRepository(connection)
            master.upsert_currency(tenant_id=tenant_a, code="USD", name="US Dollar")
            master.upsert_organization(
                tenant_id=tenant_a,
                organization_id="org-a",
                organization_code="ORG_A",
                name="North",
                base_currency="USD",
            )
            ledger = PostgresLedgerRepository(connection)
            ledger.upsert_account(
                tenant_id=tenant_a,
                organization_id="org-a",
                account_id="cash-a",
                account_code="1000",
                name="Cash",
                account_type="Asset",
                normal_balance="Debit",
            )
            ledger.upsert_account(
                tenant_id=tenant_a,
                organization_id="org-a",
                account_id="revenue-a",
                account_code="4000",
                name="Revenue",
                account_type="Income",
                normal_balance="Credit",
            )
            posted = ledger.post_entry(
                tenant_id=tenant_a,
                entry_id="entry-a",
                entry_number="JE-001",
                organization_id="org-a",
                currency_code="USD",
                posting_date="2026-01-31",
                description="Month-end",
                lines=(
                    LedgerLine(account_id="cash-a", debit="100.00", credit="0"),
                    LedgerLine(account_id="revenue-a", debit="0", credit="100.00"),
                ),
                actor_id="controller",
            )
            assert posted["status"] == "Posted"
            assert len(posted["lines"]) == 2
            assert connection.execute(
                "SELECT COUNT(*) FROM reconforge.audit_events WHERE tenant_id = %s", (tenant_a,)
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id = %s", (tenant_a,)
            ).fetchone()[0] == 1
            with pytest.raises(psycopg.Error):
                connection.execute(
                    "UPDATE reconforge.ledger_entries SET description = %s WHERE tenant_id = %s AND id = %s",
                    ("tampered", tenant_a, "entry-a"),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            ledger = PostgresLedgerRepository(connection)
            assert ledger.list_accounts(tenant_id=tenant_b) == []
            with pytest.raises(PostgresLedgerIntegrityError):
                ledger.get_entry(tenant_id=tenant_b, entry_id="entry-a")
    finally:
        for tenant_id in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id = %s", (tenant_id,))
            except psycopg.Error:
                pass
        app.close()
        admin.close()
