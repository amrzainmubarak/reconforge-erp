from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Literal
from uuid import uuid4

import pytest

from reconforge.application.matching import MatchingRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_matching import (
    POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL,
    PostgresMatchingRepository,
    _located_records,
)
from reconforge.infrastructure.postgres_reconciliation import POSTGRES_RECONCILIATION_SCHEMA_SQL
from reconforge.platform.common import PlatformError
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY, SOURCE_POSITION_COLUMN

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0023_postgres_matching_application.py"
    spec = importlib.util.spec_from_file_location("migration_0023", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matching_workspace_schema_is_tenant_bound_forced_rls_and_reversible() -> None:
    assert "CREATE TABLE IF NOT EXISTS reconforge.matching_run_workspaces" in POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL
    assert "REFERENCES reconforge.reconciliation_runs(tenant_id,id)" in POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL
    assert "REFERENCES reconforge.domain_workspaces(tenant_id,id)" in POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL
    assert "current_setting('app.tenant_id', true)" in POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL
    migration = _migration()
    assert migration.revision == "0023_postgres_matching_app"
    assert migration.down_revision == "0022_postgres_receivables"
    assert "DROP TABLE IF EXISTS reconforge.matching_run_workspaces" in (
        ROOT / "alembic/versions/0023_postgres_matching_application.py"
    ).read_text(encoding="utf-8")


def test_all_matching_signatures_match_application_contract() -> None:
    for method_name in ("run", "benchmark", "job_status", "results", "list_jobs", "match_records"):
        assert inspect.signature(getattr(PostgresMatchingRepository, method_name)) == inspect.signature(
            getattr(MatchingRepositoryProtocol, method_name)
        )


class _Result:
    def __init__(self, one: object = None, many: list[object] | None = None) -> None:
        self.one, self.many = one, many or []

    def fetchone(self) -> object:
        return self.one

    def fetchall(self) -> list[object]:
        return self.many


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> None:
        self.connection.entered += 1

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> Literal[False]:
        self.connection.exited += 1
        self.connection.rolled_back = exc is not None
        return False


class _Connection:
    def __init__(self) -> None:
        self.entered = self.exited = 0
        self.rolled_back = False
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def execute(self, query: str, parameters: tuple[object, ...] = ()) -> _Result:
        self.queries.append((query, parameters))
        if "FROM reconforge.domain_workspaces" in query:
            return _Result({"id": "workspace-a"})
        if "FROM reconforge.currencies" in query:
            return _Result({"minor_units": 2, "active": True})
        return _Result()


class _Persistence:
    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.exceptions: list[dict[str, Any]] = []

    def create_run(self, **kwargs: Any) -> dict[str, Any]:
        return {"id": kwargs["run_id"], "status": "Running"}

    def register_input(self, **kwargs: Any) -> dict[str, Any]:
        self.inputs.append(kwargs)
        return kwargs

    def append_result(self, **kwargs: Any) -> dict[str, Any]:
        self.results.append(kwargs)
        return kwargs

    def append_exception(self, **kwargs: Any) -> dict[str, Any]:
        self.exceptions.append(kwargs)
        return kwargs

    def complete_run(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "id": kwargs["run_id"], "status": "Complete",
            "result_count": len(self.results),
            "matched_count": sum(item["status"] == "Matched" for item in self.results),
        }


def test_postgres_matching_persists_complete_engine_output_without_sqlite() -> None:
    connection = _Connection()
    repository = PostgresMatchingRepository(connection, "tenant_a")
    persistence = _Persistence()
    repository.persistence = persistence  # type: ignore[assignment]

    result = repository._run_records(
        left_records=_located_records([{"id": "L-1", "amount": "10.00", "date": "2026-07-28", "reference": "INV-1"}], "left.json"),
        right_records=_located_records([{"id": "R-1", "amount": "10.00", "date": "2026-07-28", "reference": "INV-1"}], "right.json"),
        workspace="default", name="match", left_source="left.json", right_source="right.json",
        left_checksum="a" * 64, right_checksum="b" * 64,
        left_id_field="id", right_id_field="id", amount_field="amount", date_field="date",
        reference_field="reference", exact_fields="", amount_tolerance="0", date_window_days=0,
        allow_many_to_one=False, allow_one_to_many=False, allow_many_to_many=False,
        reference_normalization_rules=None, idempotency_key="idem-1", actor_label="maker",
        financial_input_policy="strict-financial-input-v2",
        record_identity_policy=RECORD_IDENTITY_POLICY,
    )

    assert result.result_count == result.matched_count == 1
    assert {(item["side"], item["source_id"]) for item in persistence.inputs} == {("Left", "L-1"), ("Right", "R-1")}
    assert persistence.results[0]["lineage"]["left_record"]["source_location"]["position"] == 1
    assert connection.entered == connection.exited == 1
    assert not connection.rolled_back
    assert not any("sqlite" in query.lower() for query, _parameters in connection.queries)


def test_source_records_are_registered_with_exact_zero_and_no_internal_lineage() -> None:
    connection = _Connection()
    repository = PostgresMatchingRepository(connection, "tenant_a")
    persistence = _Persistence()
    repository.persistence = persistence  # type: ignore[assignment]
    repository._register_inputs(
        "match-a", "Left",
        [{"id": "L-0", "amount": 0, "date": "2026-07-28", "reference": "ZERO", SOURCE_POSITION_COLUMN: 1}],
        {1: ("L-0", "f" * 64)}, "amount", "date", "reference", False,
    )
    saved = persistence.inputs[0]
    assert saved["amount"] == 0
    assert saved["amount_original"] == "0"
    assert SOURCE_POSITION_COLUMN not in saved["attributes"]


def test_runtime_module_has_no_sqlite_dependency() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_matching.py").read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "SQLite" not in source


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_matching_application_lifecycle_and_rls() -> None:
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
    tenant_a, tenant_b = "matching_a_" + uuid4().hex[:8], "matching_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_RECONCILIATION_SCHEMA_SQL)
            admin.execute(POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            tables = (
                "tenants,currencies,domain_workspaces,audit_events,outbox_events,"
                "reconciliation_runs,reconciliation_inputs,reconciliation_results,"
                "reconciliation_exceptions,matching_run_workspaces"
            )
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{tables.replace(',', ',reconforge.')} TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)", (tenant_a, tenant_a, tenant_b, tenant_b))
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Matching')", (tenant, f"workspace-{tenant}"))
                connection.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'USD','US Dollar',2)", (tenant,))
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresMatchingRepository(connection, tenant_a)
            result = repository._run_records(
                left_records=_located_records([{"id": "L-1", "amount": "10.00", "currency": "USD", "date": "2026-07-28", "reference": "INV-1"}], "left.json"),
                right_records=_located_records([{"id": "R-1", "amount": "10.00", "currency": "USD", "date": "2026-07-28", "reference": "INV-1"}], "right.json"),
                workspace="Matching", name="live-match", left_source="left.json", right_source="right.json",
                left_checksum="a" * 64, right_checksum="b" * 64,
                left_id_field="id", right_id_field="id", amount_field="amount", date_field="date",
                reference_field="reference", exact_fields="", amount_tolerance="0", date_window_days=0,
                allow_many_to_one=False, allow_one_to_many=False, allow_many_to_many=False,
                reference_normalization_rules=None, idempotency_key="live-idempotency", actor_label="live-user",
                financial_input_policy="strict-financial-input-v2", record_identity_policy=RECORD_IDENTITY_POLICY,
            )
            assert result.result_count == result.matched_count == 1
            assert repository.job_status(result.job_id)["status"] == "Complete"
            assert repository.results(result.job_id)[0]["status"] == "Matched"
            assert len(repository.list_jobs()) == 1
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresMatchingRepository(connection, tenant_b)
            assert repository.list_jobs() == []
            with pytest.raises(PlatformError, match="not found"):
                repository.job_status(result.job_id)
    finally:
        for tenant in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
            except psycopg.Error:
                pass
        admin.close()
