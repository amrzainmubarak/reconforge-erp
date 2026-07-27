"""Contract tests for the tenant-scoped PostgreSQL evidence registry."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from typing import Any

import pytest

from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_evidence import (
    POSTGRES_EVIDENCE_SCHEMA_SQL,
    PostgresEvidenceIntegrityError,
    PostgresEvidenceNotFoundError,
    PostgresEvidenceRepository,
    PostgresEvidenceValidationError,
)
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL


class _Cursor:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self.row = row
        self.rows = rows or []
        self.rowcount = 1 if row is not None else 0

    def fetchone(self) -> Any:
        return self.row

    def fetchall(self) -> list[Any]:
        return self.rows


class _EvidenceConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self.record: dict[str, Any] | None = None
        self.link: dict[str, Any] | None = None
        self.requirement: dict[str, Any] | None = None
        self.coverage_rows: list[tuple[Any, ...]] = [("close_task", "task-a", 1, 1)]

    @contextmanager
    def transaction(self) -> Any:
        yield self
        self.commits += 1

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select pg_advisory_xact_lock"):
            return _Cursor()
        if "select event_hash from reconforge.audit_events" in normalized:
            return _Cursor()
        if normalized.startswith("insert into reconforge.audit_events") or normalized.startswith(
            "insert into reconforge.outbox_events"
        ):
            return _Cursor()
        if "from reconforge.evidence_registry" in normalized and "for update" in normalized:
            if self.record is None:
                return _Cursor()
            return _Cursor(self.record)
        if normalized.startswith("insert into reconforge.evidence_registry"):
            assert params is not None
            self.record = {
                "tenant_id": params[0],
                "id": params[1],
                "evidence_code": params[2],
                "source_name": params[3],
                "source_reference": params[4],
                "checksum_sha256": params[5],
                "provenance_type": params[6],
                "redaction_status": params[7],
                "evidence_status": params[8],
                "storage_backend": params[9],
                "storage_tenant_id": params[10],
                "storage_key": params[11],
                "storage_version_id": params[12],
                "content_type": params[13],
                "byte_size": params[14],
                "retention_until": params[15],
                "last_verified_at": None,
                "last_verified_sha256": None,
                "verification_status": "Unverified",
                "registered_by": params[16],
                "created_at": "2026-07-23T00:00:00Z",
                "updated_at": "2026-07-23T00:00:00Z",
            }
            return _Cursor(self.record)
        if normalized.startswith("update reconforge.evidence_registry"):
            assert self.record is not None
            if "last_verified_sha256" in normalized:
                assert params is not None
                self.record["last_verified_sha256"] = params[0]
                self.record["verification_status"] = params[1]
                self.record["last_verified_at"] = "2026-07-23T00:01:00Z"
            else:
                assert params is not None
                for field, index in (
                    ("source_name", 0),
                    ("source_reference", 1),
                    ("provenance_type", 2),
                    ("redaction_status", 3),
                    ("evidence_status", 4),
                    ("content_type", 5),
                    ("byte_size", 6),
                    ("retention_until", 7),
                    ("registered_by", 8),
                ):
                    self.record[field] = params[index]
                self.record["updated_at"] = "2026-07-23T00:01:00Z"
            return _Cursor(self.record)
        if "from reconforge.evidence_registry" in normalized and "where tenant_id = %s and id = %s" in normalized:
            return _Cursor(self.record)
        if "from reconforge.evidence_links" in normalized and "where tenant_id = %s and evidence_id = %s" in normalized:
            return _Cursor(rows=[self.link] if self.link is not None else [])
        if normalized.startswith("insert into reconforge.evidence_links"):
            assert params is not None
            self.link = {
                "tenant_id": params[0],
                "id": params[1],
                "evidence_id": params[2],
                "object_type": params[3],
                "object_id": params[4],
                "link_type": params[5],
                "created_at": "2026-07-23T00:02:00Z",
            }
            return _Cursor(self.link)
        if "from reconforge.evidence_requirements" in normalized and "for update" in normalized:
            return _Cursor(self.requirement)
        if normalized.startswith("insert into reconforge.evidence_requirements"):
            assert params is not None
            self.requirement = {
                "tenant_id": params[0],
                "id": params[1],
                "object_type": params[2],
                "object_id": params[3],
                "requirement_code": params[4],
                "description": params[5],
                "required_status": params[6],
                "created_at": "2026-07-23T00:03:00Z",
                "updated_at": "2026-07-23T00:03:00Z",
            }
            return _Cursor(self.requirement)
        if "from reconforge.evidence_requirements" in normalized and "group by" in normalized:
            return _Cursor(rows=self.coverage_rows)
        return _Cursor()


def test_postgres_evidence_registry_is_atomic_and_tenant_scoped() -> None:
    connection = _EvidenceConnection()
    repository = PostgresEvidenceRepository(connection)
    digest = "a" * 64

    record = repository.register(
        tenant_id="TENANT_A",
        evidence_id="evidence-a",
        evidence_code="CLOSE-001",
        source_name="close binder.pdf",
        checksum_sha256=digest,
        storage_backend="s3-compatible-object-storage",
        storage_tenant_id="tenant_a",
        storage_key="evidence/close-001/a.pdf",
        storage_version_id="version-1",
        content_type="application/pdf",
        byte_size=12,
        actor_id="user-a",
    )
    link = repository.link(
        tenant_id="tenant_a",
        evidence_id="evidence-a",
        object_type="close_task",
        object_id="task-a",
        actor_id="user-a",
    )
    requirement = repository.requirement(
        tenant_id="tenant_a",
        object_type="close_task",
        object_id="task-a",
        requirement_code="TB",
        description="Trial balance support",
        actor_id="user-a",
    )
    verification = repository.verify_checksum(
        tenant_id="tenant_a",
        evidence_id="evidence-a",
        actual_sha256=digest,
        actor_id="user-a",
    )
    coverage = repository.coverage(tenant_id="tenant_a")

    assert record["tenant_id"] == "tenant_a"
    assert record["storage_tenant_id"] == "tenant_a"
    assert link["evidence_id"] == "evidence-a"
    assert requirement["requirement_code"] == "TB"
    assert verification.ok is True
    assert coverage["coverage_pct"] == 100.0
    assert connection.commits == 0
    assert any(params is not None and "tenant_a" in params for _, params in connection.executed)
    assert any("ENABLE ROW LEVEL SECURITY" in POSTGRES_EVIDENCE_SCHEMA_SQL for _ in (0,))


def test_postgres_evidence_registry_rejects_cross_tenant_storage_and_mutation() -> None:
    repository = PostgresEvidenceRepository(_EvidenceConnection())
    with pytest.raises(PostgresEvidenceValidationError, match="storage_tenant_id"):
        repository.register(
            tenant_id="tenant_a",
            evidence_id="evidence-a",
            evidence_code="CLOSE-001",
            source_name="close binder.pdf",
            checksum_sha256="a" * 64,
            storage_backend="s3-compatible-object-storage",
            storage_tenant_id="tenant_b",
            storage_key="evidence/a.pdf",
            actor_id="user-a",
        )

    connection = _EvidenceConnection()
    connection.record = {
        "tenant_id": "tenant_a",
        "id": "evidence-a",
        "evidence_code": "CLOSE-001",
        "source_name": "close binder.pdf",
        "source_reference": "",
        "checksum_sha256": "a" * 64,
        "provenance_type": "external-reference",
        "redaction_status": "unknown",
        "evidence_status": "Available",
        "storage_backend": "external-reference",
        "storage_tenant_id": "tenant_a",
        "storage_key": "evidence/a.pdf",
        "storage_version_id": "version-1",
        "content_type": "application/pdf",
        "byte_size": 12,
        "retention_until": None,
        "last_verified_at": None,
        "last_verified_sha256": None,
        "verification_status": "Unverified",
        "registered_by": "user-a",
        "created_at": "2026-07-23T00:00:00Z",
        "updated_at": "2026-07-23T00:00:00Z",
    }
    with pytest.raises(PostgresEvidenceIntegrityError, match="different artifact content"):
        PostgresEvidenceRepository(connection).register(
            tenant_id="tenant_a",
            evidence_id="evidence-a",
            evidence_code="CLOSE-001",
            source_name="close binder.pdf",
            checksum_sha256="b" * 64,
            storage_backend="external-reference",
            storage_tenant_id="tenant_a",
            storage_key="evidence/a.pdf",
            actor_id="user-a",
        )


def test_postgres_evidence_registry_schema_has_append_only_artifact_guards() -> None:
    assert "evidence_artifact_immutable" in POSTGRES_EVIDENCE_SCHEMA_SQL
    assert "evidence_registry_no_delete" in POSTGRES_EVIDENCE_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_EVIDENCE_SCHEMA_SQL
    assert "storage_tenant_id" in POSTGRES_EVIDENCE_SCHEMA_SQL


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service")
def test_live_postgres_evidence_registry_enforces_tenant_visibility() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("live evidence test requires a non-privileged application role")
    if app_user and not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "evidence_live_a"
    tenant_b = "evidence_live_b"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_EVIDENCE_SCHEMA_SQL)
            if app_user:
                admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
                admin.execute(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, "
                    f"reconforge.audit_events, reconforge.outbox_events, reconforge.evidence_registry, "
                    f"reconforge.evidence_links, reconforge.evidence_requirements TO {app_user}"
                )
                admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            for tenant in (tenant_a, tenant_b):
                admin.execute(
                    "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (tenant, tenant),
                )
        if app_user:
            app_connection = factory.connect()
            try:
                role = app_connection.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                ).fetchone()
            finally:
                app_connection.close()
            if role is None or bool(role[0]) or bool(role[1]):
                pytest.skip("live evidence test requires a non-superuser, non-BYPASSRLS application role")
        digest = "c" * 64
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresEvidenceRepository(connection)
            repository.register(
                tenant_id=tenant_a,
                evidence_id="evidence-live-a",
                evidence_code="CLOSE-LIVE-A",
                source_name="close-live.pdf",
                checksum_sha256=digest,
                storage_backend="s3-compatible-object-storage",
                storage_tenant_id=tenant_a,
                storage_key="evidence/live-a.pdf",
                actor_id="user-live",
            )
            assert len(repository.list_evidence(tenant_id=tenant_a)) == 1
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresEvidenceRepository(connection)
            assert repository.list_evidence(tenant_id=tenant_b) == []
            with pytest.raises(PostgresEvidenceNotFoundError):
                repository.get(tenant_id=tenant_b, evidence_id="evidence-live-a")
    finally:
        admin.close()
