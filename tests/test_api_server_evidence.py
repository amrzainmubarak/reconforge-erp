"""Contract tests for the PostgreSQL-backed evidence API boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.api.server_identity import RequestExecutionScope, request_tenant_id
from reconforge.auth.field_access import EVIDENCE_DRILL_DOWN_FIELDS, EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS
from reconforge.auth.models import LocalUser
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres_evidence import PostgresEvidenceVerification


class _FakeEvidenceRepository:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}
        self.links: list[dict[str, object]] = []
        self.requirements: list[dict[str, object]] = []

    def list_evidence(self, **values: object) -> list[dict[str, object]]:
        assert values["tenant_id"] == "tenant-a"
        records = list(self.records.values())
        return records[int(values.get("offset", 0)) : int(values.get("offset", 0)) + int(values.get("limit", 500))]

    def get(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        return self.records[str(values["evidence_id"])]

    def coverage(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        return {
            "tenant_id": "tenant-a",
            "object_count": len(self.requirements),
            "requirement_count": len(self.requirements),
            "covered_object_count": len(self.links),
            "coverage_pct": 100.0 if self.requirements and self.links else 0.0,
            "objects": [
                {
                    "object_type": "close_task",
                    "object_id": "task-a",
                    "requirement_count": len(self.requirements),
                    "linked_evidence_count": len(self.links),
                    "unknown_future_object_field": "must-not-escape",
                }
            ],
            "unknown_future_coverage_field": "must-not-escape",
        }

    def register(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        record = {
            "tenant_id": "tenant-a",
            "id": values["evidence_id"],
            "evidence_code": values["evidence_code"],
            "source_name": values["source_name"],
            "source_path": "/synthetic/close.pdf",
            "checksum_sha256": values["checksum_sha256"],
            "storage_backend": values["storage_backend"],
            "links": [],
        }
        self.records[str(record["id"])] = record
        return record

    def link(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        link = {
            "tenant_id": "tenant-a",
            "id": "link-a",
            "evidence_id": values["evidence_id"],
            "object_type": values["object_type"],
            "object_id": values["object_id"],
            "link_type": values["link_type"],
            "unknown_future_column": "must-not-leak",
        }
        self.links.append(link)
        return link

    def requirement(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        requirement = {
            "tenant_id": "tenant-a",
            "id": "requirement-a",
            "object_type": values["object_type"],
            "object_id": values["object_id"],
            "requirement_code": values["requirement_code"],
            "description": values["description"],
        }
        self.requirements.append(requirement)
        return requirement

    def verify_checksum(self, **values: object) -> PostgresEvidenceVerification:
        assert values["tenant_id"] == "tenant-a"
        actual = str(values["actual_sha256"])
        return PostgresEvidenceVerification(
            evidence_id=str(values["evidence_id"]),
            ok=True,
            expected_sha256=actual,
            actual_sha256=actual,
        )

    def drill_down(self, **values: object) -> dict[str, object]:
        assert values["tenant_id"] == "tenant-a"
        evidence_id = str(values["evidence_id"])
        return {
            "evidence_id": evidence_id,
            "direction": values["direction"],
            "max_depth": values["max_depth"],
            "include_sensitive": values["include_sensitive"],
            "nodes": [
                {
                    "node_type": "evidence",
                    "id": evidence_id,
                    "record": {**self.records[evidence_id], "unknown_future_column": "must-not-escape"},
                    "depth": 0,
                }
            ],
            "edges": [],
            "nodes_count": 1,
            "edges_count": 0,
            "pagination": {"limit": values["limit"], "offset": values["offset"]},
        }


def test_server_evidence_routes_use_tenant_scoped_repository(tmp_path: Path, monkeypatch: Any) -> None:
    import reconforge.api.app as app_module
    import reconforge.api.dependencies as dependencies
    import reconforge.api.routes.evidence as evidence_routes

    user = LocalUser(id="user-a", username="alice", display_name="Alice")
    permissions = frozenset({"evidence.read", "evidence.manage", "evidence.verify"})
    repository = _FakeEvidenceRepository()
    scoped_permissions: list[dict[str, object]] = []

    def authenticate(request: Any, token: str) -> tuple[LocalUser, frozenset[str]] | None:
        assert request_tenant_id(request) == "tenant-a"
        return (user, permissions) if token == "server-token" else None

    def execute(request: Any, operation: Any) -> Any:
        assert request_tenant_id(request) == "tenant-a"
        return operation(repository, "tenant-a")

    monkeypatch.setattr(app_module, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "authenticate_server_request", authenticate)
    monkeypatch.setattr(dependencies, "server_audit_administration_enabled", lambda _request: False)
    monkeypatch.setattr(
        evidence_routes,
        "request_execution_scope",
        lambda _request: RequestExecutionScope("tenant-a", "workspace-a", "org-a", "entity-a"),
    )
    monkeypatch.setattr(
        evidence_routes,
        "enforce_server_scoped_permission",
        lambda _request, **kwargs: scoped_permissions.append(kwargs),
    )
    monkeypatch.setattr(
        evidence_routes,
        "enforce_server_scoped_permissions",
        lambda _request, **kwargs: scoped_permissions.append(kwargs),
    )
    monkeypatch.setattr(evidence_routes, "execute_postgres_evidence", execute)

    tenant_root = tmp_path / "tenants"
    tenant_root.mkdir()
    run_migrations(tenant_root / "tenant-a.db")
    client = TestClient(
        create_api_app(
            tmp_path / "unused.db",
            tenant_db_root=tenant_root,
            postgres_dsn="postgresql://evidence.test/postgres",
            postgres_require_tls=False,
            cursor_signing_key=b"evidence-cursor-test-key-32-bytes-minimum",
        )
    )
    headers = {"X-ReconForge-Tenant": "tenant-a", "Authorization": "Bearer server-token"}
    digest = "a" * 64

    created = client.post(
        "/api/v1/evidence/records",
        headers=headers,
        json={
            "evidence_id": "evidence-a",
            "evidence_code": "CLOSE-001",
            "source_name": "close.pdf",
            "checksum_sha256": digest,
        },
    )
    listed = client.get("/api/v1/evidence", headers=headers)
    fetched = client.get("/api/v1/evidence/records/evidence-a", headers=headers)
    linked = client.post(
        "/api/v1/evidence/records/evidence-a/links",
        headers=headers,
        json={"object_type": "close_task", "object_id": "task-a"},
    )
    requirement = client.post(
        "/api/v1/evidence/requirements",
        headers=headers,
        json={
            "object_type": "close_task",
            "object_id": "task-a",
            "requirement_code": "TB",
            "description": "Trial balance support",
        },
    )
    verified = client.post(
        "/api/v1/evidence/records/evidence-a/verify",
        headers=headers,
        json={"actual_sha256": digest},
    )
    drill_down = client.get(
        "/api/v1/evidence/records/evidence-a/drill-down",
        headers=headers,
    )
    sensitive_drill_down = client.get(
        "/api/v1/evidence/records/evidence-a/drill-down?include_sensitive=true",
        headers=headers,
    )
    coverage = client.get("/api/v1/evidence/coverage", headers=headers)

    assert created.status_code == 200, created.text
    assert created.json()["source"]["kind"] == "postgresql-evidence-registry"
    assert listed.status_code == 200
    assert fetched.json()["evidence"]["id"] == "evidence-a"
    assert linked.status_code == 200
    assert linked.json()["link"]["id"] == "link-a"
    assert "unknown_future_column" not in linked.json()["link"]
    assert requirement.status_code == 200
    assert requirement.json()["requirement"]["field_access"]["denied_fields"] == []
    assert verified.status_code == 200
    assert verified.json()["verification"]["ok"] is True
    assert verified.json()["verification"]["field_access"]["denied_fields"] == []
    assert drill_down.status_code == 200
    drill_node = drill_down.json()["drill_down"]["nodes"][0]
    assert drill_node["record"]["source_path"] == "***redacted***"
    assert drill_node["field_access"]["denied_fields"] == ["unknown_future_column"]
    assert drill_down.json()["drill_down"]["field_access"]["version"] == "field-projection-v1"
    assert sensitive_drill_down.status_code == 200
    sensitive_node = sensitive_drill_down.json()["drill_down"]["nodes"][0]
    assert sensitive_node["record"]["source_path"] == "/synthetic/close.pdf"
    assert sensitive_node["field_access"]["masked_fields"] == []
    assert sensitive_node["field_access"]["denied_fields"] == ["unknown_future_column"]
    assert coverage.status_code == 200
    assert coverage.json()["coverage"]["objects"][0]["object_type"] == "close_task"
    assert "unknown_future_coverage_field" not in coverage.text
    assert "unknown_future_object_field" not in coverage.text
    expected_hierarchy = {
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "organization_id": "org-a",
        "entity_id": "entity-a",
    }
    assert scoped_permissions == [
        {"permission": "evidence.manage", **expected_hierarchy},
        {
            "permissions": frozenset({"evidence.read", "evidence.manage"}),
            **expected_hierarchy,
            "requested_field_names": EVIDENCE_DRILL_DOWN_FIELDS - EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS,
            "authorized_field_names": EVIDENCE_DRILL_DOWN_FIELDS - EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS,
        },
        {
            "permissions": frozenset({"evidence.read", "evidence.manage"}),
            **expected_hierarchy,
            "requested_field_names": EVIDENCE_DRILL_DOWN_FIELDS - EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS,
            "authorized_field_names": EVIDENCE_DRILL_DOWN_FIELDS - EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS,
        },
        {"permission": "evidence.manage", **expected_hierarchy},
        {"permission": "evidence.manage", **expected_hierarchy},
        {"permission": "evidence.verify", **expected_hierarchy},
        {
            "permissions": frozenset({"evidence.read", "evidence.manage"}),
            **expected_hierarchy,
            "requested_field_names": EVIDENCE_DRILL_DOWN_FIELDS - EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS,
            "authorized_field_names": EVIDENCE_DRILL_DOWN_FIELDS - EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS,
        },
        {
            "permission": "evidence.manage",
            **expected_hierarchy,
            "requested_field_names": EVIDENCE_DRILL_DOWN_FIELDS,
            "authorized_field_names": EVIDENCE_DRILL_DOWN_FIELDS,
        },
        {"permissions": frozenset({"evidence.read", "evidence.manage"}), **expected_hierarchy},
    ]
