from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.approvals import ApprovalRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_approvals import (
    POSTGRES_APPROVALS_SCHEMA_SQL,
    PostgresApprovalRepository,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0029_postgres_approvals.py"
    spec = importlib.util.spec_from_file_location("migration_0029", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_approvals_schema_has_tenant_tables_and_forced_rls() -> None:
    for table in ("approval_requests", "certification_records"):
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_APPROVALS_SCHEMA_SQL
        assert f"'{table}'" in POSTGRES_APPROVALS_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_APPROVALS_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_APPROVALS_SCHEMA_SQL


def test_approvals_schema_guards_sod_no_override_and_immutable_history() -> None:
    schema = POSTGRES_APPROVALS_SCHEMA_SQL
    assert "decided approval requests are immutable" in schema
    assert "approval decisions require maker checker no override and rejection reason" in schema
    assert "approval request history is immutable" in schema
    assert "certification review requires separation of duties" in schema
    assert "reviewed certification metadata is immutable" in schema
    assert "certification metadata history is immutable" in schema


def test_approvals_migration_is_linear_and_drops_tables_before_functions() -> None:
    migration = _migration()
    assert migration.revision == "0029_postgres_approvals"
    assert migration.down_revision == "0028_postgres_accounts"
    source = (ROOT / "alembic/versions/0029_postgres_approvals.py").read_text(encoding="utf-8")
    assert source.index("certification_records CASCADE") < source.index("certification_record_guard")
    assert source.index("approval_requests CASCADE") < source.index("approval_request_guard")


def test_approvals_adapter_matches_all_eight_application_signatures() -> None:
    methods = [
        name for name, value in vars(ApprovalRepositoryProtocol).items()
        if callable(value) and not name.startswith("_")
    ]
    assert len(methods) == 8
    for name in methods:
        assert inspect.signature(getattr(PostgresApprovalRepository, name)) == inspect.signature(
            getattr(ApprovalRepositoryProtocol, name)
        )


def test_approvals_adapter_has_locks_transactional_evidence_and_bounded_reads() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_approvals.py").read_text(encoding="utf-8")
    assert "FOR UPDATE" in source
    assert "Approval SoD overrides are not permitted." in source
    assert "PostgresAuditEventRepository" in source
    assert "encode_postgres_outbox_payload" in source
    assert "LIMIT 10000" in source
    assert "requests." not in source
    assert "httpx." not in source


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_approval_certification_sod_evidence_and_rls() -> None:
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
    tenant_a, tenant_b = "approvals_a_" + uuid4().hex[:8], "approvals_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_APPROVALS_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            approvals = PostgresApprovalRepository(connection, tenant_a)
            request = approvals.submit(
                object_type="close_period", object_id="PERIOD-1", title="Close approval",
                assigned_to="reviewer", requested_by="preparer", reason="Review evidence",
                actor_label="preparer",
            )
            with pytest.raises(PlatformError, match="requester cannot approve"):
                approvals.approve(str(request["id"]), actor_label="preparer")
            with pytest.raises(PlatformError, match="overrides are not permitted"):
                approvals.approve(str(request["id"]), actor_label="reviewer", override_reason="emergency")
            approved = approvals.approve(
                str(request["id"]), actor_label="reviewer", reason="Evidence reviewed"
            )
            assert (approved["status"], approved["decided_by"], approved["override_reason"]) == (
                "Approved", "reviewer", "",
            )
            withdrawal = approvals.submit(
                object_type="close_period", object_id="PERIOD-2", title="Withdraw approval",
                assigned_to="controller", requested_by="controller", actor_label="controller",
            )
            rejected = approvals.reject(
                str(withdrawal["id"]), actor_label="controller", reason="Withdrawn by requester"
            )
            assert rejected["status"] == "Rejected"
            certification = approvals.prepare_certification(
                object_type="account_reconciliation", object_id="AR-1", period_name="2026-07",
                entity_code="EG01", note="Prepared evidence", actor_label="preparer",
            )
            with pytest.raises(PlatformError, match="preparer and reviewer"):
                approvals.review_certification(
                    object_type="account_reconciliation", object_id="AR-1", actor_label="preparer"
                )
            reviewed = approvals.review_certification(
                object_type="account_reconciliation", object_id="AR-1",
                note="Independently reviewed", actor_label="reviewer",
            )
            assert (certification["status"], reviewed["status"], reviewed["reviewed_by"]) == (
                "Prepared", "Reviewed", "reviewer",
            )
            audit_count = connection.execute(
                "SELECT COUNT(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0]
            outbox_count = connection.execute(
                "SELECT COUNT(*) FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0]
            assert audit_count == outbox_count == 6
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            approvals_b = PostgresApprovalRepository(connection, tenant_b)
            assert approvals_b.list_requests() == []
            assert approvals_b.list_certifications() == []
            with pytest.raises(PlatformError, match="not found"):
                approvals_b.get(str(request["id"]))
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()

