"""Contract tests for the PostgreSQL-backed reconciliation read API boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import RequestExecutionScope, request_tenant_id
from reconforge.auth.models import LocalUser


class _FakeReconciliationRepository:
    def __init__(self) -> None:
        self.run = {
            "tenant_id": "tenant-a",
            "id": "run-a",
            "name": "Bank to GL",
            "status": "Complete",
            "result_count": 1,
            "matched_count": 1,
            "exception_count": 0,
        }
        self.inputs = [{"tenant_id": "tenant-a", "run_id": "run-a", "side": "Left", "source_id": "bank-1"}]
        self.results = [{"tenant_id": "tenant-a", "run_id": "run-a", "id": "match-a", "status": "Matched"}]
        self.exceptions: list[dict[str, object]] = []
        self.submitted_inputs: list[dict[str, object]] = []
        self.submitted_run: dict[str, object] | None = None

    def create_run(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        self.submitted_run = {
            **self.run,
            "id": values["run_id"],
            "execution_status": "Queued",
            "rule": values["rule"],
        }
        return self.submitted_run

    def register_input(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        self.submitted_inputs.append(values)
        return values

    def list_runs(self, **values: object) -> list[dict[str, object]]:
        assert values["tenant_id"] == "tenant-a"
        assert values["status"] == ""
        return [self.run]

    def get_run_metadata(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        assert values["run_id"] == "run-a"
        return self.run

    def list_inputs(self, **values: object) -> list[dict[str, object]]:
        assert values["tenant_id"] == "tenant-a"
        assert values["run_id"] == "run-a"
        return self.inputs

    def list_results(self, **values: object) -> list[dict[str, object]]:
        assert values["tenant_id"] == "tenant-a"
        assert values["run_id"] == "run-a"
        return self.results

    def list_exceptions(self, **values: object) -> list[dict[str, object]]:
        assert values["tenant_id"] == "tenant-a"
        assert values["run_id"] == "run-a"
        return self.exceptions

    def cancel_run(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        return {**self.run, "cancel_requested": True, "execution_status": "Running"}

    def requeue_run(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        return {**self.run, "cancel_requested": False, "execution_status": "Queued"}


def test_server_reconciliation_routes_are_tenant_scoped_and_read_only(tmp_path: Path, monkeypatch: Any) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.reconciliation as reconciliation_routes

    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    permissions = frozenset({"reconciliation.read", "reconciliation.manage"})
    repository = _FakeReconciliationRepository()
    scoped_permissions: list[dict[str, object]] = []

    def authenticate(request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        assert request_tenant_id(request) == "tenant-a"
        return (user, permissions) if token == "server-token" else None

    def execute(request: Any, operation: Any) -> Any:
        assert request_tenant_id(request) == "tenant-a"
        return operation(repository, "tenant-a")

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(
        reconciliation_routes,
        "request_execution_scope",
        lambda _request: RequestExecutionScope("tenant-a", "workspace-a", "org-a", "entity-a"),
    )
    monkeypatch.setattr(
        reconciliation_routes,
        "enforce_server_scoped_permissions",
        lambda _request, **kwargs: scoped_permissions.append(kwargs),
    )
    monkeypatch.setattr(reconciliation_routes, "execute_postgres_reconciliation", execute)

    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://reconciliation.test/postgres",
            postgres_require_tls=False,
        )
    )
    headers = {"X-ReconForge-Tenant": "tenant-a", "Authorization": "Bearer server-token"}

    submitted = client.post(
        "/api/v1/reconciliations/runs",
        headers={**headers, "Idempotency-Key": "submit-1"},
        json={
            "run_id": "run-submit",
            "name": "Bank to GL",
            "left_source": "bank.csv",
            "right_source": "gl.csv",
            "algorithm_version": "deterministic-global-v1",
            "rule": {"amount_field": "amount", "date_field": "date"},
            "input_hash": "manifest-hash",
            "inputs": [
                {"side": "Left", "source_id": "bank-1", "record_hash": "left-hash", "amount": "10.00"},
                {"side": "Right", "source_id": "gl-1", "record_hash": "right-hash", "amount": "10.00"},
            ],
        },
    )
    rejected_legacy_policy = client.post(
        "/api/v1/reconciliations/runs",
        headers=headers,
        json={
            "run_id": "run-legacy-policy",
            "name": "Legacy policy run",
            "left_source": "bank.csv",
            "right_source": "gl.csv",
            "rule": {"financial_input_policy": "legacy-financial-input-v1"},
            "input_hash": "legacy-policy-manifest",
            "inputs": [
                {"side": "Left", "source_id": "bank-1", "record_hash": "left-hash", "amount": "10.00"},
                {"side": "Right", "source_id": "gl-1", "record_hash": "right-hash", "amount": "10.00"},
            ],
        },
    )
    rejected_binary_tolerance = client.post(
        "/api/v1/reconciliations/runs",
        headers=headers,
        json={
            "run_id": "run-binary-tolerance",
            "name": "Binary tolerance run",
            "left_source": "bank.csv",
            "right_source": "gl.csv",
            "rule": {"amount_tolerance": 0.1},
            "input_hash": "binary-tolerance-manifest",
            "inputs": [
                {"side": "Left", "source_id": "bank-1", "record_hash": "left-hash", "amount": "10.00"},
                {"side": "Right", "source_id": "gl-1", "record_hash": "right-hash", "amount": "10.00"},
            ],
        },
    )
    rejected_legacy_identity_policy = client.post(
        "/api/v1/reconciliations/runs",
        headers=headers,
        json={
            "run_id": "run-legacy-identity-policy",
            "name": "Legacy identity policy run",
            "left_source": "bank.csv",
            "right_source": "gl.csv",
            "rule": {"record_identity_policy": "row-order-occurrence-legacy-v0"},
            "input_hash": "legacy-identity-policy-manifest",
            "inputs": [
                {"side": "Left", "source_id": "bank-1", "record_hash": "left-hash", "amount": "10.00"},
                {"side": "Right", "source_id": "gl-1", "record_hash": "right-hash", "amount": "10.00"},
            ],
        },
    )

    runs = client.get("/api/v1/reconciliations/runs", headers=headers)
    run = client.get("/api/v1/reconciliations/runs/run-a", headers=headers)
    inputs = client.get("/api/v1/reconciliations/runs/run-a/inputs", headers=headers)
    results = client.get("/api/v1/reconciliations/runs/run-a/results", headers=headers)
    exceptions = client.get("/api/v1/reconciliations/runs/run-a/exceptions", headers=headers)
    cancelled = client.post(
        "/api/v1/reconciliations/runs/run-a/cancel",
        headers=headers,
        json={"reason": "Operator requested stop"},
    )
    requeued = client.post(
        "/api/v1/reconciliations/runs/run-a/requeue",
        headers=headers,
        json={"reason": "Retry after validation"},
    )

    assert runs.status_code == 200, runs.text
    assert submitted.status_code == 202, submitted.text
    assert rejected_legacy_policy.status_code == 400
    assert (
        rejected_legacy_policy.json()["error"]["code"]
        == "reconciliation_financial_input_policy_invalid"
    )
    assert rejected_binary_tolerance.status_code == 400
    assert rejected_binary_tolerance.json()["error"]["code"] == "reconciliation_rule_invalid"
    assert rejected_legacy_identity_policy.status_code == 400
    assert (
        rejected_legacy_identity_policy.json()["error"]["code"]
        == "reconciliation_record_identity_policy_invalid"
    )
    assert submitted.json()["run"]["execution_status"] == "Queued"
    assert submitted.json()["input_count"] == 2
    assert repository.submitted_run is not None
    assert repository.submitted_run["rule"]["financial_input_policy"] == "strict-financial-input-v2"
    assert (
        repository.submitted_run["rule"]["record_identity_policy"]
        == "canonical-multiset-occurrence-v1"
    )
    assert repository.submitted_run["rule"]["amount_tolerance"] == "0"
    assert len(repository.submitted_inputs) == 2
    assert repository.submitted_inputs[0]["amount"] == "10.00"
    assert runs.json()["runs"][0]["id"] == "run-a"
    assert runs.json()["source"]["kind"] == "postgresql-reconciliation-results"
    assert run.status_code == 200
    assert run.json()["run"]["status"] == "Complete"
    assert inputs.status_code == 200
    assert inputs.json()["inputs"][0]["source_id"] == "bank-1"
    assert results.status_code == 200
    assert results.json()["results"][0]["id"] == "match-a"
    assert exceptions.status_code == 200
    assert exceptions.json()["exceptions"] == []
    assert cancelled.status_code == 200
    assert cancelled.json()["run"]["cancel_requested"] is True
    assert requeued.status_code == 200
    assert requeued.json()["run"]["execution_status"] == "Queued"
    assert len(scoped_permissions) == 11
    assert scoped_permissions[:4] == [
        {
            "permissions": frozenset({"reconciliation.manage", "match.run"}),
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "organization_id": "org-a",
            "entity_id": "entity-a",
        }
    ] * 4
    assert scoped_permissions[4:9] == [
        {
            "permissions": frozenset({"reconciliation.read", "reconciliation.manage", "match.read", "match.run"}),
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "organization_id": "org-a",
            "entity_id": "entity-a",
        }
    ] * 5
    assert scoped_permissions[9:] == [
        {
            "permissions": frozenset({"reconciliation.manage", "match.run"}),
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "organization_id": "org-a",
            "entity_id": "entity-a",
        }
    ] * 2


def test_server_reconciliation_routes_require_read_permission(tmp_path: Path, monkeypatch: Any) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies

    user = LocalUser(id="user-a", username="alice", display_name="Alice")

    def authenticate(request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        assert request_tenant_id(request) == "tenant-a"
        return (user, frozenset()) if token == "server-token" else None

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://reconciliation.test/postgres",
            postgres_require_tls=False,
        )
    )

    response = client.get(
        "/api/v1/reconciliations/runs",
        headers={"X-ReconForge-Tenant": "tenant-a", "Authorization": "Bearer server-token"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
