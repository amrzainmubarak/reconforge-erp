from __future__ import annotations

import pytest

from reconforge.deployment import WorkerPermissionManifestError, verify_worker_permission_manifest


def _payload() -> dict[str, object]:
    return {
        "worker_id": "reconciliation-worker-a",
        "principal_id": "svc-reconciliation-a",
        "discovery_permission": "match.discover",
        "execution_permission": "match.run",
        "granted_permissions": ["match.discover", "match.run"],
        "scope": "tenant:tenant-a/workspace:workspace-a",
    }


def test_worker_permission_manifest_is_strict_and_digest_stable() -> None:
    manifest = verify_worker_permission_manifest(_payload())
    assert manifest.digest == verify_worker_permission_manifest(dict(_payload())).digest
    assert manifest.to_dict()["granted_permissions"] == ["match.discover", "match.run"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("discovery_permission", "match.run", "distinct"),
        ("granted_permissions", ["match.run"], "must be granted"),
        ("granted_permissions", ["match.run", "match.discover"], "sorted"),
        ("execution_permission", "finance_core.approve", "human-governed"),
    ],
)
def test_worker_permission_manifest_fails_closed(field: str, value: object, message: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(WorkerPermissionManifestError, match=message):
        verify_worker_permission_manifest(payload)


def test_worker_permission_manifest_rejects_unknown_fields() -> None:
    payload = _payload()
    payload["telemetry_endpoint"] = "https://example.invalid"
    with pytest.raises(WorkerPermissionManifestError, match="closed contract"):
        verify_worker_permission_manifest(payload)
