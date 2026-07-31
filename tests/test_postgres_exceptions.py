from __future__ import annotations

import inspect
import os
import re
from contextlib import nullcontext
from typing import Any
from uuid import uuid4

import pytest

from reconforge.application.exceptions import ExceptionQueueRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_exceptions import (
    POSTGRES_EXCEPTIONS_SCHEMA_SQL,
    PostgresExceptionQueueRepository,
)
from reconforge.platform.common import PlatformError


class _Cursor:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> list[Any]:
        return self._rows


class _ExceptionConnection:
    def __init__(self) -> None:
        self.workspace_id = "workspace-a"
        self.records: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.lock_order: list[str] = []

    def transaction(self) -> Any:
        return nullcontext()

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("set local app.tenant_id"):
            return _Cursor()
        if "select id from reconforge.domain_workspaces" in normalized:
            return _Cursor({"id": self.workspace_id})
        if "select * from reconforge.exception_queue_records" in normalized and "order by case" in normalized:
            assert params is not None
            rows = list(self.records.values())
            fields = ("period_name", "entity_code", "account_code", "control_code", "risk_rating", "owner", "status")
            filters = (params[1], params[3], params[5], params[7], params[9], params[11], params[13])
            for field, selected in zip(fields, filters, strict=True):
                if selected:
                    rows = [row for row in rows if row[field] == selected]
            order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            rows.sort(key=lambda row: (-order[row["risk_rating"]], str(row["id"])))
            return _Cursor(rows=rows)
        if "select * from reconforge.exception_queue_records" in normalized:
            assert params is not None
            if "workspace_id=%s and source_type=%s" in normalized:
                row = next(
                    (record for record in self.records.values() if record["workspace_id"] == params[1]
                     and record["source_type"] == params[2] and record["source_id"] == params[3]), None,
                )
                return _Cursor(row)
            identifier = str(params[1])
            if "for update" in normalized:
                self.lock_order.append(identifier)
            return _Cursor(self.records.get(identifier))
        if normalized.startswith("insert into reconforge.exception_queue_records"):
            assert params is not None
            existing = next(
                (record for record in self.records.values() if record["workspace_id"] == params[2]
                 and record["source_type"] == params[3] and record["source_id"] == params[4]), None,
            )
            if existing is None:
                row = {
                    "tenant_id": params[0], "id": params[1], "workspace_id": params[2],
                    "source_type": params[3], "source_id": params[4], "period_name": params[5],
                    "entity_code": params[6], "account_code": params[7], "control_code": params[8],
                    "risk_rating": params[9], "owner": params[10], "status": params[11],
                    "escalation_level": params[12], "sla_target_date": params[13] or None,
                    "description": params[14], "created_by": params[15], "last_actor": params[16],
                    "created_at": "2026-07-28T00:00:00Z", "updated_at": "2026-07-28T00:00:00Z",
                    "row_version": 1,
                }
                self.records[str(params[1])] = row
            else:
                row = existing
                for field, index in (
                    ("period_name", 5), ("entity_code", 6), ("account_code", 7), ("control_code", 8),
                    ("risk_rating", 9), ("owner", 10), ("status", 11), ("escalation_level", 12),
                    ("sla_target_date", 13), ("description", 14), ("last_actor", 16),
                ):
                    row[field] = params[index] or None if field == "sla_target_date" else params[index]
                row["row_version"] += 1
            return _Cursor(row)
        if normalized.startswith("update reconforge.exception_queue_records"):
            assert params is not None
            row = self.records[str(params[4])]
            row["status"], row["owner"], row["last_actor"] = params[0], params[1], params[2]
            row["row_version"] += 1
            return _Cursor(row)
        if normalized.startswith("insert into reconforge.exception_queue_history"):
            assert params is not None
            row = {
                "tenant_id": params[0], "id": params[1], "exception_id": params[2], "action": params[3],
                "from_status": params[4], "to_status": params[5], "from_owner": params[6],
                "to_owner": params[7], "actor_label": params[8], "occurred_at": "2026-07-28T00:01:00Z",
            }
            self.history.append(row)
            return _Cursor()
        if "from reconforge.exception_queue_history" in normalized:
            assert params is not None
            return _Cursor(rows=[row for row in self.history if row["exception_id"] == params[1]])
        return _Cursor()


def test_postgres_exception_queue_contract_signatures_are_exact() -> None:
    methods = ("upsert_exception", "list", "assign", "set_status", "bulk_update", "get")
    for method in methods:
        assert inspect.signature(getattr(PostgresExceptionQueueRepository, method)) == inspect.signature(
            getattr(ExceptionQueueRepositoryProtocol, method)
        )


def test_postgres_exception_queue_lifecycle_history_filters_and_bulk() -> None:
    connection = _ExceptionConnection()
    repository = PostgresExceptionQueueRepository(connection, "tenant-a")
    repository._event = lambda **_: None  # type: ignore[method-assign]
    first = repository.upsert_exception(
        source_type="control", source_id="C-2", description="Critical variance",
        workspace="Finance", period_name="2026-07", entity_code="LE-1",
        risk_rating="critical", actor_label="system",
    )
    second = repository.upsert_exception(
        source_type="control", source_id="C-1", description="High variance",
        workspace="Finance", period_name="2026-07", entity_code="LE-1",
        risk_rating="high", actor_label="system",
    )
    repository.assign(first["id"], owner="reviewer-a", actor_label="lead")
    repository.set_status(first["id"], status="In Review", actor_label="reviewer-a")
    count = repository.bulk_update(
        [second["id"], first["id"], second["id"]], status="Resolved", owner="lead",
        actor_label="controller",
    )
    assert count == 2
    assert connection.lock_order[-2:] == sorted((first["id"], second["id"]))
    assert [row["risk_rating"] for row in repository.list(period_name="2026-07")] == ["critical", "high"]
    record = repository.get(first["id"])
    assert (record["status"], record["owner"]) == ("Resolved", "lead")
    assert [row["action"] for row in record["history"]] == [
        "exception_saved", "exception_assigned", "exception_status_updated", "exception_bulk_updated"
    ]


def test_postgres_exception_queue_bulk_prelocks_all_and_validates_boundaries() -> None:
    connection = _ExceptionConnection()
    repository = PostgresExceptionQueueRepository(connection, "tenant-a")
    events: list[dict[str, Any]] = []
    repository._event = lambda **values: events.append(values)  # type: ignore[method-assign]
    record = repository.upsert_exception(source_type="matching", source_id="M-1", description="Unmatched")
    before = dict(connection.records[record["id"]])
    with pytest.raises(PlatformError, match="not found"):
        repository.bulk_update([record["id"], "missing"], status="Closed")
    assert connection.records[record["id"]] == before
    with pytest.raises(PlatformError, match="status or owner"):
        repository.bulk_update([record["id"]])
    with pytest.raises(PlatformError, match="1000"):
        repository.bulk_update([f"id-{index}" for index in range(1001)], status="Closed")
    with pytest.raises(PlatformError, match="YYYY-MM-DD"):
        repository.upsert_exception(
            source_type="matching", source_id="M-2", description="Bad SLA", sla_target_date="07/31/2026"
        )
    repository.bulk_update([record["id"]], status="Closed")
    first_version = events[-1]["version"]
    repository.bulk_update([record["id"]], status="Closed")
    assert events[-1]["version"] != first_version
    with pytest.raises(PlatformError, match="not text"):
        repository.bulk_update(record["id"], status="Closed")


def test_postgres_exception_queue_schema_has_retention_history_and_rls() -> None:
    schema = POSTGRES_EXCEPTIONS_SCHEMA_SQL
    assert "exception source identity is immutable" in schema
    assert "exception transition history is append-only" in schema
    assert "exception queue records are retained" in schema
    assert "exception transition history must match current state" in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "FOREIGN KEY(tenant_id,workspace_id)" in schema
    assert "ON DELETE RESTRICT" in schema


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service"
)
def test_live_postgres_exception_queue_lifecycle_atomic_bulk_and_rls() -> None:
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
    tenant_a = "exception_a_" + uuid4().hex[:8]
    tenant_b = "exception_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_EXCEPTIONS_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        with factory.connect() as probe:
            role = probe.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("requires a non-superuser, non-BYPASSRLS application role")
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,'finance')",
                    (tenant, f"workspace-{tenant}"),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            queue = PostgresExceptionQueueRepository(connection, tenant_a)
            first = queue.upsert_exception(
                source_type="control", source_id="C-1", description="Critical variance",
                workspace="finance", risk_rating="critical", actor_label="system",
            )
            second = queue.upsert_exception(
                source_type="matching", source_id="M-1", description="Unmatched",
                workspace="finance", actor_label="system",
            )
            queue.assign(first["id"], owner="reviewer", actor_label="lead")
            assert queue.bulk_update([second["id"], first["id"]], status="In Review", actor_label="lead") == 2
            assert len(queue.get(first["id"])["history"]) == 3
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            queue = PostgresExceptionQueueRepository(connection, tenant_b)
            assert queue.list() == []
            with pytest.raises(PlatformError, match="not found"):
                queue.get(first["id"])
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()
