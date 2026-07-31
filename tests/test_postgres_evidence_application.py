from __future__ import annotations

import hashlib
import inspect
import os
import re
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from reconforge.application.evidence import EvidenceRegistryRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_evidence_application import (
    POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL,
    PostgresEvidenceRegistryRepository,
)
from reconforge.platform.common import PlatformError, platform_id


class _Cursor:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> list[Any]:
        return self._rows


class _EvidenceConnection:
    def __init__(self) -> None:
        self.workspace_id = "workspace-a"
        self.records: dict[str, dict[str, Any]] = {}
        self.links: dict[str, dict[str, Any]] = {}
        self.requirements: dict[str, dict[str, Any]] = {}

    def transaction(self) -> Any:
        return nullcontext()

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("set local app.tenant_id"):
            return _Cursor()
        if "select id from reconforge.domain_workspaces" in normalized:
            return _Cursor({"id": self.workspace_id})
        if (
            "select * from reconforge.evidence_application_registry" in normalized
            and "order by created_at desc" not in normalized
        ):
            assert params is not None
            if "workspace_id=%s and evidence_code=%s" in normalized:
                match = next(
                    (row for row in self.records.values() if row["workspace_id"] == params[1]
                     and row["evidence_code"] == params[2]), None,
                )
                return _Cursor(match)
            return _Cursor(self.records.get(str(params[1])))
        if normalized.startswith("insert into reconforge.evidence_application_registry"):
            assert params is not None
            row = {
                "tenant_id": params[0], "id": params[1], "workspace_id": params[2],
                "evidence_code": params[3], "source_path": params[4], "checksum_sha256": params[5],
                "provenance_type": params[6], "redaction_status": params[7], "evidence_status": params[8],
                "storage_backend": params[9], "storage_tenant_id": params[10], "storage_key": params[11],
                "storage_version_id": params[12], "content_type": params[13], "byte_size": params[14],
                "retention_until": params[15], "registered_by": params[16],
                "created_at": "2026-07-28T00:00:00Z", "updated_at": "2026-07-28T00:00:00Z",
                "row_version": 1,
            }
            self.records[str(params[1])] = row
            return _Cursor()
        if normalized.startswith("update reconforge.evidence_application_registry"):
            assert params is not None
            row = self.records[str(params[-1])]
            row["row_version"] += 1
            return _Cursor({"row_version": row["row_version"]})
        if normalized.startswith("insert into reconforge.evidence_application_links"):
            assert params is not None
            existing = next((row for row in self.links.values() if row["id"] == params[1]), None)
            if existing is not None:
                return _Cursor()
            row = {
                "tenant_id": params[0], "id": params[1], "workspace_id": params[2],
                "evidence_id": params[3], "object_type": params[4], "object_id": params[5],
                "link_type": params[6], "created_by": params[7], "created_at": "2026-07-28T00:01:00Z",
            }
            self.links[str(params[1])] = row
            return _Cursor(row)
        if "select * from reconforge.evidence_application_links" in normalized:
            assert params is not None
            if "where tenant_id=%s and id=%s" in normalized:
                return _Cursor(self.links.get(str(params[1])))
            if "object_type=%s and object_id=%s" in normalized:
                rows = [row for row in self.links.values() if row["workspace_id"] == params[1]
                        and row["object_type"] == params[2] and row["object_id"] == params[3]]
                return _Cursor(rows=rows)
            return _Cursor(rows=[row for row in self.links.values() if row["evidence_id"] == params[1]])
        if normalized.startswith("insert into reconforge.evidence_application_requirements"):
            assert params is not None
            row = {
                "tenant_id": params[0], "id": params[1], "workspace_id": params[2],
                "object_type": params[3], "object_id": params[4], "requirement_code": params[5],
                "description": params[6], "required_status": params[7], "created_by": params[8],
                "created_at": "2026-07-28T00:02:00Z", "updated_at": "2026-07-28T00:02:00Z",
                "row_version": 1,
            }
            self.requirements[str(params[1])] = row
            return _Cursor(row)
        if "from reconforge.evidence_application_requirements r" in normalized:
            rows = []
            for requirement in self.requirements.values():
                linked = {link["evidence_id"] for link in self.links.values()
                          if link["object_type"] == requirement["object_type"]
                          and link["object_id"] == requirement["object_id"]}
                rows.append({"object_type": requirement["object_type"], "object_id": requirement["object_id"],
                             "requirement_count": 1, "linked_evidence_count": len(linked)})
            return _Cursor(rows=rows)
        if normalized.startswith("select * from reconforge.evidence_application_registry where tenant_id=%s"):
            rows = list(self.records.values())
            if "evidence_status=%s" in normalized:
                assert params is not None
                rows = [row for row in rows if row["evidence_status"] == params[1]]
            return _Cursor(rows=rows)
        return _Cursor()


def test_postgres_evidence_application_contract_signatures_are_exact() -> None:
    methods = ("register", "requirement", "link", "verify", "coverage", "list_evidence", "get", "drill_down")
    for method in methods:
        assert inspect.signature(getattr(PostgresEvidenceRegistryRepository, method)) == inspect.signature(
            getattr(EvidenceRegistryRepositoryProtocol, method)
        )


def test_postgres_evidence_application_local_lifecycle_and_redacted_graph(tmp_path: Path) -> None:
    source = tmp_path / "binder.txt"
    source.write_bytes(b"immutable evidence\n")
    connection = _EvidenceConnection()
    repository = PostgresEvidenceRegistryRepository(connection, "tenant-a")
    repository._event = lambda **_: None  # type: ignore[method-assign]

    evidence = repository.register(source, evidence_code="CLOSE-001", workspace="Finance", actor_label="maker")
    assert evidence["checksum_sha256"] == "aeff868b6d4b87b297f28da65e4b3e5d838646ca2149123e17fc794d6a023fb5"
    assert repository.verify(evidence["id"], actor_label="reviewer").ok is True
    requirement = repository.requirement(
        object_type="close_task", object_id="task-1", requirement_code="BINDER",
        description="Signed close binder", workspace="Finance", actor_label="reviewer",
    )
    link = repository.link(
        evidence["id"], object_type="close_task", object_id="task-1", actor_label="reviewer",
    )
    assert requirement["workspace_id"] == "workspace-a"
    assert link["evidence_id"] == evidence["id"]
    assert repository.coverage(workspace="Finance")["coverage_pct"] == 100.0
    assert repository.list_evidence(status="Available")[0]["id"] == evidence["id"]
    graph = repository.drill_down(evidence["id"], actor_label="auditor")
    assert graph["nodes_count"] == 2
    assert graph["edges_count"] == 1
    root = next(node for node in graph["nodes"] if node["node_type"] == "evidence")
    assert root["record"]["source_path"] == "***redacted***"


def test_postgres_evidence_application_rejects_artifact_rebinding_and_unsafe_bounds(tmp_path: Path) -> None:
    source = tmp_path / "first.txt"
    source.write_bytes(b"first")
    changed = tmp_path / "changed.txt"
    changed.write_bytes(b"changed")
    repository = PostgresEvidenceRegistryRepository(_EvidenceConnection(), "tenant-a")
    repository._event = lambda **_: None  # type: ignore[method-assign]
    repository.register(source, evidence_code="EV-1")
    with pytest.raises(PlatformError, match="different immutable artifact"):
        repository.register(changed, evidence_code="EV-1")
    with pytest.raises(PlatformError, match="between 1 and 8"):
        repository.drill_down(platform_id("EVDREG", "workspace-a", "ev-1"), max_depth=9)
    with pytest.raises(PlatformError, match="configured object store"):
        repository.register(source, evidence_code="EV-2", storage_object_name="unsafe")


def test_postgres_evidence_application_checks_identity_before_object_upload(tmp_path: Path) -> None:
    source = tmp_path / "object.txt"
    source.write_bytes(b"object evidence")
    calls: list[str] = []

    class _Store:
        def put_bytes(self, tenant_id: str, object_name: str, content: bytes, **_: Any) -> Any:
            calls.append(object_name)
            digest = hashlib.sha256(content).hexdigest()
            return SimpleNamespace(
                content=content, sha256=digest, metadata={"reconforge-tenant": tenant_id}, version_id="v1"
            )

        def get_bytes(self, tenant_id: str, object_name: str) -> Any:
            raise AssertionError((tenant_id, object_name))

    repository = PostgresEvidenceRegistryRepository(_EvidenceConnection(), "tenant-a")
    repository._event = lambda **_: None  # type: ignore[method-assign]
    store = _Store()
    repository.register(
        source, evidence_code="OBJ-1", object_store=store, storage_object_name="evidence/stable.bin"
    )
    repository.register(
        source, evidence_code="OBJ-1", object_store=store, storage_object_name="evidence/stable.bin"
    )
    assert calls == ["evidence/stable.bin"]
    with pytest.raises(PlatformError, match="different immutable artifact"):
        repository.register(
            source, evidence_code="OBJ-1", object_store=store, storage_object_name="evidence/rebound.bin"
        )
    assert calls == ["evidence/stable.bin"]


def test_postgres_evidence_application_schema_is_tenant_bound_and_append_only() -> None:
    schema = POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL
    assert schema.count("FORCE ROW LEVEL SECURITY") == 1  # loop applies it to all three tables
    assert "FOREIGN KEY(tenant_id,workspace_id)" in schema
    assert "evidence records are append-only" in schema
    assert "evidence links are append-only" in schema
    assert "checksum_sha256 ~ '^[0-9a-f]{64}$'" in schema
    assert "evidence_application_requirements CASCADE" not in schema
    assert "DROP POLICY IF EXISTS tenant_isolation" in schema
    assert "policyname='tenant_scope'" in schema


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service"
)
def test_live_schema_reinstall_preserves_composed_workspace_policy() -> None:
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN")
    if not admin_dsn:
        pytest.skip("requires a disposable PostgreSQL administration service")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    connection = factory.connect()
    try:
        with connection.transaction():
            connection.execute(POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL)
        rows = connection.execute(
            "SELECT tablename,policyname FROM pg_policies "
            "WHERE schemaname='reconforge' AND tablename IN "
            "('evidence_application_registry','evidence_application_links','evidence_application_requirements') "
            "ORDER BY tablename,policyname"
        ).fetchall()
        policies: dict[str, set[str]] = {}
        for table_name, policy_name in rows:
            policies.setdefault(str(table_name), set()).add(str(policy_name))
        assert set(policies) == {
            "evidence_application_registry",
            "evidence_application_links",
            "evidence_application_requirements",
        }
        assert all(names == {"tenant_scope"} for names in policies.values())
    finally:
        connection.close()


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires a live PostgreSQL service"
)
def test_live_postgres_evidence_application_enforces_rls_and_lifecycle(tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.skip("requires a safe non-privileged application role")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    source = tmp_path / "live-evidence.txt"
    source.write_bytes(b"live immutable evidence")
    tenant_a = "evidenceapp_a_" + uuid4().hex[:8]
    tenant_b = "evidenceapp_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL)
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
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'default')",
                    (tenant, f"workspace-{tenant}"),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresEvidenceRegistryRepository(connection, tenant_a)
            record = repository.register(source, evidence_code="LIVE-1", workspace="default", actor_label="maker")
            repository.link(record["id"], object_type="close_task", object_id="live-task", actor_label="maker")
            assert repository.verify(record["id"], actor_label="reviewer").ok
            assert repository.drill_down(record["id"])["nodes_count"] == 2
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            repository = PostgresEvidenceRegistryRepository(connection, tenant_b)
            assert repository.list_evidence() == []
            with pytest.raises(PlatformError, match="not found"):
                repository.get(record["id"])
    finally:
        try:
            with admin.transaction():
                admin.execute("DELETE FROM reconforge.tenants WHERE id IN (%s,%s)", (tenant_a, tenant_b))
        except psycopg.Error:
            pass
        admin.close()
