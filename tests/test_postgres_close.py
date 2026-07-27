"""Contract tests for the bounded PostgreSQL close-control repository."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from reconforge.infrastructure.postgres_close import (
    POSTGRES_CLOSE_SCHEMA_SQL,
    PostgresCloseRepository,
    PostgresCloseValidationError,
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
        self.commits = 0
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.period = (
            "tenant_a",
            "close-period-a",
            "period-a",
            "org-a",
            "Open",
            "0.00",
            "created",
            "updated",
            None,
            None,
        )
        self.task = (
            "tenant_a",
            "task-a",
            "close-period-a",
            "CLOSE-001",
            "Load trial balance",
            "",
            "Data",
            "high",
            None,
            "Not Started",
            "",
            "",
            "created",
            "updated",
        )

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "from reconforge.fiscal_periods" in normalized and "start_date" in normalized:
            return _Cursor(row=("period-a", "2026-07", date(2026, 7, 1), date(2026, 7, 31)))
        if "from reconforge.fiscal_periods" in normalized:
            return _Cursor(row=("period-a", "2026-07"))
        if "from reconforge.organizations" in normalized:
            return _Cursor(row=("org-a", "ORG-A", "Organization", "USD", True))
        if "from reconforge.close_periods" in normalized and "organization_code" not in normalized:
            return _Cursor(row=self.period)
        if "from reconforge.close_tasks" in normalized and "status" not in normalized:
            return _Cursor(row=self.task)
        if normalized.startswith("insert into reconforge.close_periods"):
            return _Cursor(row=self.period)
        if normalized.startswith("insert into reconforge.close_tasks"):
            return _Cursor(row=self.task)
        if normalized.startswith("select status from reconforge.close_tasks"):
            return _Cursor(rows=[("Not Started",)])
        if normalized.startswith("update reconforge.close_periods"):
            return _Cursor(row=self.period)
        if normalized.startswith("update reconforge.close_tasks"):
            return _Cursor(row=self.task)
        if "from reconforge.close_tasks as tasks" in normalized:
            return _Cursor(rows=[self.task + ("period-a",)])
        return _Cursor()

    def commit(self) -> None:
        self.commits += 1


def test_close_schema_is_tenant_scoped_and_rls_protected() -> None:
    assert "CREATE TABLE IF NOT EXISTS reconforge.close_periods" in POSTGRES_CLOSE_SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS reconforge.close_tasks" in POSTGRES_CLOSE_SCHEMA_SQL
    assert "close_task_dependencies" in POSTGRES_CLOSE_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_CLOSE_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_CLOSE_SCHEMA_SQL
    assert "readiness_score >= 0 AND readiness_score <= 100" in POSTGRES_CLOSE_SCHEMA_SQL


def test_close_period_and_task_writes_are_caller_owned_and_deterministic() -> None:
    connection = _FakeConnection()
    repository = PostgresCloseRepository(connection)

    period = repository.create_period(
        tenant_id="TENANT_A",
        period_id="close-period-a",
        fiscal_period_id="period-a",
        organization_id="org-a",
        organization_code="ORG-A",
        expected_start_date="2026-07-01",
        expected_end_date="2026-07-31",
    )
    task = repository.upsert_task(
        tenant_id="TENANT_A",
        task_id="task-a",
        close_period_id="close-period-a",
        task_code="CLOSE-001",
        name="Load trial balance",
    )

    assert period["id"] == "close-period-a"
    assert task["task_code"] == "CLOSE-001"
    assert connection.commits == 0
    assert any("INSERT INTO reconforge.close_periods" in sql for sql, _ in connection.executed)
    task_insert = next(sql for sql, _ in connection.executed if "INSERT INTO reconforge.close_tasks" in sql)
    assert "NULLIF(%s, '')::date" in task_insert


def test_close_period_rejects_a_date_mismatch_without_writing() -> None:
    class _MismatchConnection(_FakeConnection):
        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
            normalized = " ".join(sql.split()).lower()
            if "from reconforge.fiscal_periods" in normalized and "start_date" in normalized:
                return _Cursor(row=("period-a", "2026-07", date(2026, 7, 1), date(2026, 7, 31)))
            return super().execute(sql, params)

    connection = _MismatchConnection()
    with pytest.raises(PostgresCloseValidationError, match="start_date"):
        PostgresCloseRepository(connection).create_period(
            tenant_id="tenant_a",
            period_id="close-period-a",
            fiscal_period_id="period-a",
            organization_id="org-a",
            organization_code="ORG-A",
            expected_start_date="2026-07-02",
            expected_end_date="2026-07-31",
        )
    assert not any("INSERT INTO reconforge.close_periods" in sql for sql, _ in connection.executed)


def test_postgres_readiness_uses_exact_decimal_score_and_binding() -> None:
    class _ThreeTaskConnection(_FakeConnection):
        def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
            normalized = " ".join(sql.split()).lower()
            if normalized.startswith("select status from reconforge.close_tasks"):
                self.executed.append((sql, params))
                return _Cursor(rows=[("Complete",), ("In Progress",), ("Blocked",)])
            return super().execute(sql, params)

    connection = _ThreeTaskConnection()
    readiness = PostgresCloseRepository(connection).readiness(tenant_id="tenant_a", period_id="close-period-a")

    assert readiness["readiness_score"] == Decimal("33.33")
    update_params = next(
        params
        for sql, params in connection.executed
        if sql.strip().lower().startswith("update reconforge.close_periods set readiness_score")
    )
    assert update_params is not None
    assert update_params[0] == Decimal("33.33")


def test_postgres_close_status_fails_closed_on_non_complete_decimal_readiness() -> None:
    class _IncompleteRepository(PostgresCloseRepository):
        def readiness(self, *, tenant_id: str, period_id: str) -> dict[str, Any]:
            return {"readiness_score": Decimal("99.999999999999999999")}

    connection = _FakeConnection()
    with pytest.raises(PostgresCloseValidationError, match="all tasks are complete"):
        _IncompleteRepository(connection).set_period_status(
            tenant_id="tenant_a",
            period_id="close-period-a",
            status="Locked",
            actor_id="user-a",
        )

    assert not any(
        sql.strip().lower().startswith("update reconforge.close_periods set status")
        for sql, _ in connection.executed
    )
