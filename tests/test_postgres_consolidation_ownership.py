from __future__ import annotations

import importlib.util
import inspect
import os
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.application.consolidation_ownership import ConsolidationOwnershipRepositoryProtocol
from reconforge.domain.consolidation_lifecycle import ConsolidationOwnershipInterest
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    install_postgres_rls_schema,
    set_local_tenant_scope,
)
from reconforge.infrastructure.postgres_consolidation_ownership import (
    POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL,
    PostgresConsolidationOwnershipRepository,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _interest() -> ConsolidationOwnershipInterest:
    return ConsolidationOwnershipInterest(
        interest_id="OWN-PG-1",
        parent_entity_code="PARENT",
        subsidiary_entity_code="SUB",
        direct_ownership_percentage=Decimal("0.80"),
        effective_from="2026-01-01",
        effective_to="",
        version="1.0.0",
        source_digest="a" * 64,
        prepared_by="ownership-preparer",
        approved_by="ownership-reviewer",
        approved_at="2026-08-01T00:00:00Z",
    )


def test_postgres_schema_is_tenant_scoped_immutable_and_exact() -> None:
    schema = POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL
    assert "NUMERIC NOT NULL" in schema
    assert "DOUBLE PRECISION" not in schema
    assert "FORCE ROW LEVEL SECURITY" in schema
    assert "current_setting('app.tenant_id',true)" in schema
    assert "consolidation ownership interests are immutable" in schema
    assert "prepared_by<>approved_by" in schema


def test_postgres_migration_is_linear_and_reversible() -> None:
    path = ROOT / "alembic/versions/0054_postgres_consolidation_ownership.py"
    spec = importlib.util.spec_from_file_location("migration_0054", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0054_pg_consol_ownership"
    assert module.down_revision == "0053_audit_administration_acl"
    source = path.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS reconforge.consolidation_ownership_interests CASCADE" in source


def test_postgres_adapter_exposes_the_backend_neutral_ownership_port() -> None:
    methods = [
        name
        for name, value in vars(ConsolidationOwnershipRepositoryProtocol).items()
        if callable(value) and not name.startswith("__")
    ]
    assert {"save_interest", "resolve_effective"} <= set(methods)
    for name in methods:
        assert inspect.signature(getattr(PostgresConsolidationOwnershipRepository, name)) == inspect.signature(
            getattr(ConsolidationOwnershipRepositoryProtocol, name)
        )


def test_postgres_adapter_refuses_actor_mismatch_before_connection_use() -> None:
    class _UnusedConnection:
        def transaction(self):
            raise AssertionError("connection must not be used")

    with pytest.raises(PlatformError, match="preparer"):
        PostgresConsolidationOwnershipRepository(_UnusedConnection(), "tenant_a").save_interest(
            _interest(), group_code="GLOBAL-GROUP", actor_label="different-actor"
        )


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL application role",
)
def test_live_postgres_ownership_runtime_is_tenant_isolated_immutable_and_replayable() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    tenant_a = "own_a_" + uuid4().hex[:10]
    tenant_b = "own_b_" + uuid4().hex[:10]
    workspace = "close"
    group = "GLOBAL"
    admin = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False)).connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
    finally:
        admin.close()

    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    connection = factory.connect()
    try:
        interest = _interest()
        repository = PostgresConsolidationOwnershipRepository(connection, tenant_a)
        first = repository.save_interest(interest, group_code=group, workspace=workspace, actor_label=interest.prepared_by)
        replay = repository.save_interest(interest, group_code=group, workspace=workspace, actor_label=interest.prepared_by)
        assert first["id"] == replay["id"]
        assert repository.resolve_effective(
            group_code=group, reporting_date="2026-06-30", workspace=workspace
        ) == (interest,)

        with pytest.raises(PlatformError, match="overlap"):
            repository.save_interest(
                replace(_interest(), interest_id="OWN-PG-2"),
                group_code=group,
                workspace=workspace,
                actor_label="ownership-preparer",
            )

        tenant_b_repository = PostgresConsolidationOwnershipRepository(connection, tenant_b)
        with pytest.raises(PlatformError, match="No effective"):
            tenant_b_repository.resolve_effective(
                group_code=group, reporting_date="2026-06-30", workspace=workspace
            )
    finally:
        connection.close()

    mutation = factory.connect()
    try:
        with pytest.raises(Exception, match="immutable"), mutation.transaction():
            set_local_tenant_scope(mutation, tenant_a)
            mutation.execute(
                "UPDATE reconforge.consolidation_ownership_interests SET version=%s WHERE tenant_id=%s",
                ("2.0.0", tenant_a),
            )
    finally:
        mutation.close()
