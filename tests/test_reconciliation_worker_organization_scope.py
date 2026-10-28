"""Worker policy must bind the organization before claiming a run."""

from contextlib import contextmanager

import pytest

import reconforge.workers.postgres_reconciliation as worker_module
from reconforge.auth.policy import PolicyEvaluationContext
from reconforge.deployment.worker_permissions import WorkerPermissionManifest
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationBusyError
from reconforge.workers.postgres_reconciliation import (
    PostgresReconciliationPolicyDenied,
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerError,
    PostgresReconciliationWorkerSettings,
)


def _context(tenant: str, workspace: str | None, organization: str | None, entity: str | None,
             *, grants: frozenset[str] = frozenset({"org_a"})) -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="worker", username="worker", principal_type="service_account",
        user_permissions=frozenset({"match.run", "match.discover"}), tenant_id=tenant,
        workspace_id=workspace, organization_id=organization, entity_id=entity,
        authorized_tenant_ids=frozenset({"tenant"}), authorized_workspace_ids=frozenset({"workspace"}),
        authorized_organization_ids=grants, authorized_entity_ids=frozenset({"entity"}),
    )


def _manifest() -> WorkerPermissionManifest:
    return WorkerPermissionManifest(
        worker_id="worker", principal_id="worker", discovery_permission="match.discover",
        execution_permission="match.run", granted_permissions=("match.discover", "match.run"),
        scope="tenant:tenant",
    )


class _Boundary:
    def __init__(self) -> None:
        self.entered: list[dict[str, object]] = []

    @contextmanager
    def transaction(self, tenant_id: str, **scope: object):
        self.entered.append({"tenant_id": tenant_id, **scope})
        yield object()


def _worker(settings: PostgresReconciliationWorkerSettings, boundary: _Boundary) -> PostgresReconciliationWorker:
    worker = PostgresReconciliationWorker(
        lambda: None, tenant_supplier=lambda: ["tenant"], matcher=lambda _: None, settings=settings,
    )
    worker._transaction = lambda: boundary  # type: ignore[method-assign]
    return worker


def _legacy_settings() -> PostgresReconciliationWorkerSettings:
    return PostgresReconciliationWorkerSettings(
        worker_id="worker", permission_manifest=_manifest(), discovery_policy_permission="match.discover",
        policy_context_scope_supplier=lambda tenant, workspace, entity: _context(tenant, workspace, None, entity),
    )


def test_organization_scope_requires_hierarchy_supplier_before_connection() -> None:
    boundary = _Boundary()
    worker = _worker(_legacy_settings(), boundary)
    with pytest.raises(PostgresReconciliationWorkerError, match="hierarchy-aware"):
        worker.process_run(tenant_id="tenant", run_id="run", workspace_id="workspace",
                           organization_id="org_b", entity_id="entity")
    assert boundary.entered == []


def test_hierarchy_supplier_denies_other_organization_before_connection() -> None:
    boundary = _Boundary()
    settings = PostgresReconciliationWorkerSettings(
        worker_id="worker", permission_manifest=_manifest(), discovery_policy_permission="match.discover",
        policy_context_hierarchy_supplier=lambda tenant, workspace, organization, entity:
            _context(tenant, workspace, organization, entity),
    )
    worker = _worker(settings, boundary)
    with pytest.raises(PostgresReconciliationPolicyDenied, match="organization_scope_denied"):
        worker.process_run(tenant_id="tenant", run_id="run", workspace_id="workspace",
                           organization_id="org_b", entity_id="entity")
    assert boundary.entered == []


def test_hierarchy_supplier_cannot_authorize_different_selected_organization() -> None:
    boundary = _Boundary()
    settings = PostgresReconciliationWorkerSettings(
        worker_id="worker", permission_manifest=_manifest(), discovery_policy_permission="match.discover",
        policy_context_hierarchy_supplier=lambda tenant, workspace, organization, entity:
            _context(tenant, workspace, "org_a" if organization is not None else None, entity),
    )
    with pytest.raises(PostgresReconciliationWorkerError, match="scope does not match"):
        _worker(settings, boundary).process_run(
            tenant_id="tenant", run_id="run", workspace_id="workspace", organization_id="org_b", entity_id="entity",
        )
    assert boundary.entered == []


def test_revoked_organization_is_rechecked_before_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _Boundary()
    scoped_evaluations = 0
    claims: list[object] = []

    def supplier(tenant: str, workspace: str | None, organization: str | None, entity: str | None):
        nonlocal scoped_evaluations
        if organization is not None:
            scoped_evaluations += 1
        grants = frozenset({"org_a"}) if scoped_evaluations < 2 else frozenset()
        return _context(tenant, workspace, organization, entity, grants=grants)

    class Repository:
        def __init__(self, connection: object) -> None:
            pass

        def claim_run(self, **kwargs: object) -> object:
            claims.append(kwargs)
            raise AssertionError("unauthorized claim")

    monkeypatch.setattr(worker_module, "PostgresReconciliationRepository", Repository)
    settings = PostgresReconciliationWorkerSettings(
        worker_id="worker", permission_manifest=_manifest(), discovery_policy_permission="match.discover",
        policy_context_hierarchy_supplier=supplier,
    )
    worker = _worker(settings, boundary)
    with pytest.raises(PostgresReconciliationPolicyDenied, match="organization_scope_denied"):
        worker.process_run(tenant_id="tenant", run_id="run", workspace_id="workspace",
                           organization_id="org_a", entity_id="entity")
    assert scoped_evaluations == 2
    assert claims == []
    assert len(boundary.entered) == 1


def test_legacy_supplier_remains_supported_without_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _Boundary()
    claims: list[object] = []

    class Repository:
        def __init__(self, connection: object) -> None:
            pass

        def claim_run(self, **kwargs: object) -> object:
            claims.append(kwargs)
            raise PostgresReconciliationBusyError("synthetic busy")

    monkeypatch.setattr(worker_module, "PostgresReconciliationRepository", Repository)
    worker = _worker(_legacy_settings(), boundary)
    with pytest.raises(PostgresReconciliationBusyError, match="synthetic busy"):
        worker.process_run(tenant_id="tenant", run_id="run", workspace_id="workspace")
    assert len(claims) == 1
    assert claims[0]["organization_id"] is None


def test_discovery_passes_organization_and_skips_denied_run(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _Boundary()
    claims: list[dict[str, object]] = []
    scopes: list[tuple[str | None, str | None]] = []

    def supplier(tenant: str, workspace: str | None, organization: str | None, entity: str | None):
        scopes.append((workspace, organization))
        return _context(tenant, workspace, organization, entity)

    class Repository:
        def __init__(self, connection: object) -> None:
            pass

        def list_runs(self, **kwargs: object) -> list[dict[str, object]]:
            return [
                {"id": "denied", "workspace_id": "workspace", "organization_id": "org_b",
                 "legal_entity_id": "entity", "rule_json": {}},
                {"id": "allowed", "workspace_id": "workspace", "organization_id": "org_a",
                 "legal_entity_id": "entity", "rule_json": {}},
            ]

        def claim_run(self, **kwargs: object) -> object:
            claims.append(kwargs)
            raise PostgresReconciliationBusyError("synthetic busy")

    monkeypatch.setattr(worker_module, "PostgresReconciliationRepository", Repository)
    settings = PostgresReconciliationWorkerSettings(
        worker_id="worker", permission_manifest=_manifest(), discovery_policy_permission="match.discover",
        policy_context_hierarchy_supplier=supplier,
    )
    summary = _worker(settings, boundary).process_once()
    assert (summary.discovered, summary.denied, summary.skipped) == (2, 1, 1)
    assert len(claims) == 1
    assert claims[0]["run_id"] == "allowed" and claims[0]["organization_id"] == "org_a"
    assert ("workspace", "org_b") in scopes
    assert scopes.count(("workspace", "org_a")) == 2
    assert boundary.entered[1]["organization_id"] == "org_a"


def test_explicit_unbound_opt_out_preserves_existing_hosted_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    boundary = _Boundary()
    claims: list[dict[str, object]] = []

    class Repository:
        def __init__(self, connection: object) -> None:
            pass

        def claim_run(self, **kwargs: object) -> object:
            claims.append(kwargs)
            raise PostgresReconciliationBusyError("synthetic busy")

    monkeypatch.setattr(worker_module, "PostgresReconciliationRepository", Repository)
    worker = _worker(PostgresReconciliationWorkerSettings(worker_id="worker", allow_unbound_hosted_policy=True), boundary)
    with pytest.raises(PostgresReconciliationBusyError, match="synthetic busy"):
        worker.process_run(tenant_id="tenant", run_id="run", workspace_id="workspace",
                           organization_id="org_b", entity_id="entity")
    assert len(claims) == 1 and claims[0]["organization_id"] == "org_b"


def test_hierarchy_supplier_without_manifest_fails_before_connection() -> None:
    boundary = _Boundary()
    worker = _worker(PostgresReconciliationWorkerSettings(
        worker_id="worker",
        policy_context_hierarchy_supplier=lambda tenant, workspace, organization, entity:
            _context(tenant, workspace, organization, entity),
    ), boundary)
    with pytest.raises(PostgresReconciliationWorkerError, match="permission manifest"):
        worker.process_run(tenant_id="tenant", run_id="run", workspace_id="workspace",
                           organization_id="org_a", entity_id="entity")
    assert boundary.entered == []


def test_discovery_missing_hierarchy_supplier_fails_as_configuration_without_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _Boundary()
    claims: list[dict[str, object]] = []

    class Repository:
        def __init__(self, connection: object) -> None:
            pass

        def list_runs(self, **kwargs: object) -> list[dict[str, object]]:
            return [{"id": "run", "workspace_id": "workspace", "organization_id": "org_a",
                     "legal_entity_id": "entity", "rule_json": {}}]

        def claim_run(self, **kwargs: object) -> object:
            claims.append(kwargs)
            raise AssertionError("claim must not run")

    monkeypatch.setattr(worker_module, "PostgresReconciliationRepository", Repository)
    with pytest.raises(PostgresReconciliationWorkerError, match="hierarchy-aware"):
        _worker(_legacy_settings(), boundary).process_once()
    assert len(boundary.entered) == 1  # Tenant-wide discovery preceded the configuration failure.
    assert claims == []
