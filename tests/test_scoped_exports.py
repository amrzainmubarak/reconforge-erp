from __future__ import annotations

import json
import os
import re
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reconforge.application.evidence import EvidenceStorageScope
from reconforge.application.scoped_exports import (
    ScopedExportDataset,
    ScopedExportError,
    ScopedExportScope,
    ScopedExportSnapshot,
)
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.infrastructure.object_storage import (
    LocalObjectStorageSettings,
    LocalObjectStore,
    ObjectStorageIntegrityError,
)
from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings
from reconforge.infrastructure.postgres_export_scope import POSTGRES_EXPORT_SCOPE_SCHEMA_SQL
from reconforge.infrastructure.postgres_scoped_exports import (
    PostgresScopedExportPublisher,
    PostgresScopedExportRepository,
)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False

    def transaction(self) -> Any:
        return nullcontext()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> _Cursor:
        self.calls.append((" ".join(query.split()), params))
        if "FROM reconforge.domain_workspaces" in query:
            return _Cursor(
                [
                    {
                        "id": "workspace-a",
                        "name": "Finance",
                        "created_at": datetime(2026, 7, 29, tzinfo=UTC),
                    }
                ]
            )
        if "FROM reconforge.durable_jobs" in query:
            return _Cursor([{"id": "job-a", "version": 1, "status": "completed"}])
        return _Cursor()

    def close(self) -> None:
        self.closed = True


class _Factory:
    def __init__(self) -> None:
        self.connections: list[_Connection] = []

    def connect(self) -> _Connection:
        connection = _Connection()
        self.connections.append(connection)
        return connection


class _SnapshotRepository:
    def __init__(self, snapshot: ScopedExportSnapshot) -> None:
        self.value = snapshot
        self.calls: list[ScopedExportScope] = []

    def snapshot(self, scope: ScopedExportScope) -> ScopedExportSnapshot:
        self.calls.append(scope)
        assert scope == self.value.scope
        return self.value


def _scope(*, workspace: str = "workspace-a", entity: str = "entity-a") -> ScopedExportScope:
    return ScopedExportScope(
        tenant_id="tenant-a",
        workspace_id=workspace,
        organization_id="organization-a",
        entity_id=entity,
    )


def _policy(scope: ScopedExportScope, *, permissions: frozenset[str] = frozenset({"reports.read"})) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="reviewer-a",
        username="reviewer",
        user_permissions=permissions,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        entity_id=scope.entity_id or None,
        authorized_tenant_ids=frozenset({scope.tenant_id}),
        authorized_workspace_ids=frozenset({scope.workspace_id}),
        authorized_entity_ids=frozenset({scope.entity_id}) if scope.entity_id else frozenset(),
    )


def _snapshot(scope: ScopedExportScope) -> ScopedExportSnapshot:
    return ScopedExportSnapshot(
        scope=scope,
        datasets=(
            ScopedExportDataset(
                name="workspaces",
                rows=({"name": "Finance", "id": scope.workspace_id},),
            ),
        ),
    )


def test_scoped_export_is_deterministic_and_requires_complete_hierarchy() -> None:
    scope = _scope()
    first = ScopedExportSnapshot(
        scope=scope,
        datasets=(
            ScopedExportDataset(
                name="workspaces",
                rows=({"id": "b"}, {"id": "a"}),
            ),
        ),
    )
    second = ScopedExportSnapshot(
        scope=scope,
        datasets=(
            ScopedExportDataset(
                name="workspaces",
                rows=({"id": "a"}, {"id": "b"}),
            ),
        ),
    )
    assert first.digest == second.digest
    assert first.to_bytes() == second.to_bytes()
    assert json.loads(first.to_bytes())["artifact_digest"] == first.digest

    with pytest.raises(ScopedExportError, match="workspace_id"):
        ScopedExportScope(tenant_id="tenant-a", workspace_id="")
    with pytest.raises(ScopedExportError, match="organization"):
        ScopedExportScope(tenant_id="tenant-a", workspace_id="workspace-a", entity_id="entity-a")


def test_postgres_snapshot_sets_full_scope_before_bounded_static_queries() -> None:
    factory = _Factory()
    scope = _scope()
    snapshot = PostgresScopedExportRepository(factory).snapshot(scope)
    connection = factory.connections[0]

    assert connection.closed is True
    assert snapshot.scope == scope
    assert [dataset.name for dataset in snapshot.datasets] == sorted(
        dataset.name for dataset in snapshot.datasets
    )
    assert next(dataset for dataset in snapshot.datasets if dataset.name == "workspaces").rows[0][
        "id"
    ] == "workspace-a"
    calls = connection.calls
    first_select = next(index for index, (query, _) in enumerate(calls) if query.startswith("SELECT id,"))
    assert [params[0] for query, params in calls[:5] if "set_config" in query] == [
        "tenant-a",
        "organization-a",
        "workspace-a",
        "entity-a",
        "entity-a",
    ]
    assert first_select >= 5
    assert all(params == (10_001,) for query, params in calls if " LIMIT %s" in query)


def test_publisher_authorizes_and_separates_sibling_workspace_objects(tmp_path: Path) -> None:
    store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))
    first_scope = _scope(workspace="workspace-a")
    second_scope = _scope(workspace="workspace-b")
    first = PostgresScopedExportPublisher(_SnapshotRepository(_snapshot(first_scope)), store).publish(
        first_scope,
        policy_context=_policy(first_scope),
        request_id="request-a",
    )
    second = PostgresScopedExportPublisher(_SnapshotRepository(_snapshot(second_scope)), store).publish(
        second_scope,
        policy_context=_policy(second_scope),
        request_id="request-b",
    )

    assert first.object_name != second.object_name
    first_key = store.key_for(
        EvidenceStorageScope(
            tenant_id=first_scope.tenant_id,
            workspace_id=first_scope.workspace_id,
            entity_id=first_scope.entity_id,
        ),
        first.object_name,
    )
    second_key = store.key_for(
        EvidenceStorageScope(
            tenant_id=second_scope.tenant_id,
            workspace_id=second_scope.workspace_id,
            entity_id=second_scope.entity_id,
        ),
        second.object_name,
    )
    assert first_key != second_key
    assert (tmp_path / Path(*first_key.split("/"))).is_file()
    assert (tmp_path / Path(*second_key.split("/"))).is_file()


def test_publisher_denies_before_snapshot_or_object_effect(tmp_path: Path) -> None:
    scope = _scope()
    repository = _SnapshotRepository(_snapshot(scope))
    store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))
    publisher = PostgresScopedExportPublisher(repository, store)

    with pytest.raises(ScopedExportError, match="authorization"):
        publisher.publish(scope, policy_context=_policy(scope, permissions=frozenset()))
    assert repository.calls == []
    assert list(tmp_path.rglob("*")) == []

    sibling_context = _policy(_scope(workspace="workspace-b"))
    with pytest.raises(ScopedExportError, match="requested workspace"):
        publisher.publish(scope, policy_context=sibling_context)
    assert repository.calls == []


def test_publisher_rechecks_policy_before_object_effect(tmp_path: Path) -> None:
    scope = _scope()
    repository = _SnapshotRepository(_snapshot(scope))
    store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))
    publisher = PostgresScopedExportPublisher(repository, store)
    allowed = _policy(scope)
    revoked = _policy(scope, permissions=frozenset())
    supplier_calls: list[int] = []

    def current_policy() -> PolicyEvaluationContext:
        supplier_calls.append(1)
        return revoked

    with pytest.raises(ScopedExportError, match="authorization"):
        publisher.publish(
            scope,
            policy_context=allowed,
            policy_context_supplier=current_policy,
        )

    assert supplier_calls == [1]
    assert repository.calls == [scope]
    assert list(tmp_path.rglob("*")) == []


def test_snapshot_and_storage_failures_publish_no_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _scope()
    store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))

    class _FailingRepository:
        def snapshot(self, export_scope: ScopedExportScope) -> ScopedExportSnapshot:
            raise RuntimeError(export_scope.tenant_id)

    with pytest.raises(ScopedExportError, match="snapshot failed"):
        PostgresScopedExportPublisher(_FailingRepository(), store).publish(
            scope,
            policy_context=_policy(scope),
        )
    assert list(tmp_path.rglob("*")) == []

    publisher = PostgresScopedExportPublisher(_SnapshotRepository(_snapshot(scope)), store)

    def fail_storage(*args: object, **kwargs: object) -> object:
        raise RuntimeError("provider detail must not escape")

    monkeypatch.setattr(store, "put_bytes", fail_storage)
    with pytest.raises(ScopedExportError, match="publication failed") as captured:
        publisher.publish(scope, policy_context=_policy(scope))
    assert "provider detail" not in str(captured.value)
    assert list(tmp_path.rglob("*")) == []


def test_publisher_replay_is_idempotent_and_tampered_replay_fails(tmp_path: Path) -> None:
    scope = _scope()
    repository = _SnapshotRepository(_snapshot(scope))
    store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))
    publisher = PostgresScopedExportPublisher(repository, store)
    first = publisher.publish(scope, policy_context=_policy(scope))
    second = publisher.publish(scope, policy_context=_policy(scope))
    assert first == second

    key = store.key_for(
        EvidenceStorageScope(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            entity_id=scope.entity_id,
        ),
        first.object_name,
    )
    (tmp_path / Path(*key.split("/"))).write_bytes(b"tampered")
    with pytest.raises(ObjectStorageIntegrityError):
        publisher.publish(scope, policy_context=_policy(scope))


def test_export_scope_schema_replaces_permissive_evidence_policy_and_links_parent_hierarchy() -> None:
    normalized = " ".join(POSTGRES_EXPORT_SCOPE_SCHEMA_SQL.split())
    for table_name in (
        "evidence_application_registry",
        "evidence_application_links",
        "evidence_application_requirements",
    ):
        assert "tenant_isolation ON reconforge.%I" in normalized
        assert table_name in normalized
    assert "workspace_id=current_setting('app.workspace_id',true)" in normalized
    assert "parent.application_workspace_id=current_setting('app.workspace_id',true)" in normalized
    assert "DROP POLICY IF EXISTS tenant_scope ON reconforge.legal_entities" in normalized
    assert "DROP POLICY IF EXISTS tenant_scope ON reconforge.branches" in normalized


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires live PostgreSQL",
)
def test_live_scoped_export_excludes_sibling_workspace_and_entity(
    tmp_path: Path,
) -> None:
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER is required and must be a safe role name")
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    token = uuid4().hex[:8]
    tenant = f"export_{token}"
    workspace_a, workspace_b = f"ws_a_{token}", f"ws_b_{token}"
    organization_a, organization_b = f"org_a_{token}", f"org_b_{token}"
    entity_a, entity_b = f"ent_a_{token}", f"ent_b_{token}"
    job_a, job_b = f"job-a-{token}", f"job-b-{token}"
    evidence_a, evidence_b = f"ev-a-{token}", f"ev-b-{token}"
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT ON reconforge.domain_workspaces,reconforge.domain_periods,"
                f"reconforge.organizations,reconforge.legal_entities,reconforge.branches,"
                f"reconforge.durable_jobs,reconforge.evidence_application_registry TO {app_user}"
            )
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (tenant, tenant))
            for workspace in (workspace_a, workspace_b):
                admin.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,%s)",
                    (tenant, workspace, workspace),
                )
            for organization, workspace in (
                (organization_a, workspace_a),
                (organization_b, workspace_b),
            ):
                admin.execute(
                    "INSERT INTO reconforge.organizations"
                    "(tenant_id,id,name,organization_code,application_workspace_id) "
                    "VALUES(%s,%s,%s,%s,%s)",
                    (tenant, organization, organization, organization.upper(), workspace),
                )
            admin.execute(
                "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) "
                "VALUES(%s,'USD','US Dollar',2)",
                (tenant,),
            )
            for entity, organization, code in (
                (entity_a, organization_a, "EA"),
                (entity_b, organization_b, "EB"),
            ):
                admin.execute(
                    "INSERT INTO reconforge.legal_entities"
                    "(tenant_id,id,organization_id,entity_code,name,currency_code) "
                    "VALUES(%s,%s,%s,%s,%s,'USD')",
                    (tenant, entity, organization, code, entity),
                )
                admin.execute(
                    "INSERT INTO reconforge.branches"
                    "(tenant_id,id,organization_id,legal_entity_id,branch_code,name) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (tenant, f"branch-{entity}", organization, entity, code, entity),
                )
            for workspace, job, entity, evidence in (
                (workspace_a, job_a, entity_a, evidence_a),
                (workspace_b, job_b, entity_b, evidence_b),
            ):
                admin.execute(
                    "INSERT INTO reconforge.durable_jobs"
                    "(id,schema_version,version,status,idempotency_scope,idempotency_key,tenant_id,"
                    "workspace_id,entity_id,input_digest,config_digest,worker_version,completed_units,"
                    "total_units,retry_count,retry_ceiling,safe_error_code,created_at,updated_at) "
                    "VALUES(%s,1,1,'completed','export',%s,%s,%s,%s,%s,%s,'worker-v1',1,1,0,1,'',"
                    "'2026-07-29T00:00:00Z','2026-07-29T00:00:00Z')",
                    (job, job, tenant, workspace, entity, "1" * 64, "2" * 64),
                )
                admin.execute(
                    "INSERT INTO reconforge.evidence_application_registry"
                    "(tenant_id,id,workspace_id,evidence_code,source_path,checksum_sha256,"
                    "provenance_type,redaction_status,evidence_status,registered_by) "
                    "VALUES(%s,%s,%s,%s,'synthetic',%s,'synthetic','redacted','Available','tester')",
                    (tenant, evidence, workspace, evidence, "3" * 64),
                )

        repository = PostgresScopedExportRepository(app_factory)
        workspace_scope = ScopedExportScope(tenant, workspace_a)
        workspace_snapshot = repository.snapshot(workspace_scope)
        workspace_bytes = workspace_snapshot.to_bytes()
        assert workspace_a.encode() in workspace_bytes
        assert entity_a.encode() in workspace_bytes
        assert job_a.encode() in workspace_bytes
        assert evidence_a.encode() in workspace_bytes
        for sibling in (workspace_b, organization_b, entity_b, job_b, evidence_b):
            assert sibling.encode() not in workspace_bytes

        entity_scope = ScopedExportScope(tenant, workspace_a, organization_a, entity_a)
        entity_snapshot = repository.snapshot(entity_scope)
        assert "evidence_registry" not in {dataset.name for dataset in entity_snapshot.datasets}
        assert entity_a.encode() in entity_snapshot.to_bytes()
        assert entity_b.encode() not in entity_snapshot.to_bytes()

        store = LocalObjectStore(LocalObjectStorageSettings(root=tmp_path.resolve()))
        published = PostgresScopedExportPublisher(repository, store).publish(
            entity_scope,
            policy_context=_policy(entity_scope),
            request_id=f"request-{token}",
        )
        stored = store.get_bytes(
            EvidenceStorageScope(tenant, workspace_a, entity_a),
            published.object_name,
        )
        assert stored.content == entity_snapshot.to_bytes()
    finally:
        with admin.transaction():
            admin.execute(
                "ALTER TABLE reconforge.evidence_application_registry "
                "DISABLE TRIGGER evidence_application_registry_guard"
            )
            admin.execute(
                "DELETE FROM reconforge.evidence_application_registry WHERE tenant_id=%s",
                (tenant,),
            )
            admin.execute(
                "ALTER TABLE reconforge.evidence_application_registry "
                "ENABLE TRIGGER evidence_application_registry_guard"
            )
            admin.execute("DELETE FROM reconforge.durable_jobs WHERE tenant_id=%s", (tenant,))
        with admin.transaction():
            admin.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
        admin.close()
