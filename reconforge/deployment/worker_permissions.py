"""Offline verifier for hosted reconciliation worker permission manifests.

The manifest is an evidence input, not a provisioning API.  Verification is
deterministic, network-free, and refuses ambiguous or human-only grants.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from reconforge.auth.policy import permission_requires_human

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_PERMISSION = re.compile(r"^[a-z][a-z0-9_.-]{0,159}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class WorkerPermissionManifestError(ValueError):
    """Raised when a worker permission manifest is unsafe or malformed."""


@dataclass(frozen=True)
class WorkerPermissionManifest:
    """Verified service-account grants for one reconciliation worker lane."""

    worker_id: str
    principal_id: str
    discovery_permission: str
    execution_permission: str
    granted_permissions: tuple[str, ...]
    scope: str

    def __post_init__(self) -> None:
        for value, field in ((self.worker_id, "worker_id"), (self.principal_id, "principal_id"), (self.scope, "scope")):
            if not isinstance(value, str) or not _ID.fullmatch(value.strip()):
                raise WorkerPermissionManifestError(f"{field} is invalid")
        for value, field in (
            (self.discovery_permission, "discovery_permission"),
            (self.execution_permission, "execution_permission"),
        ):
            if not isinstance(value, str) or not _PERMISSION.fullmatch(value.strip()):
                raise WorkerPermissionManifestError(f"{field} is invalid")
            if permission_requires_human(value.strip()):
                raise WorkerPermissionManifestError(f"{field} cannot be human-governed")
        if self.discovery_permission == self.execution_permission:
            raise WorkerPermissionManifestError("discovery and execution permissions must be distinct")
        if not self.granted_permissions:
            raise WorkerPermissionManifestError("granted_permissions cannot be empty")
        normalized = tuple(sorted(set(self.granted_permissions)))
        if normalized != self.granted_permissions:
            raise WorkerPermissionManifestError("granted_permissions must be unique and sorted")
        if any(not isinstance(value, str) or not _PERMISSION.fullmatch(value) for value in normalized):
            raise WorkerPermissionManifestError("granted_permissions contains an invalid permission")
        if self.discovery_permission not in normalized or self.execution_permission not in normalized:
            raise WorkerPermissionManifestError("discovery and execution permissions must be granted")

    def to_dict(self) -> dict[str, object]:
        return {
            "discovery_permission": self.discovery_permission,
            "execution_permission": self.execution_permission,
            "granted_permissions": list(self.granted_permissions),
            "principal_id": self.principal_id,
            "scope": self.scope,
            "worker_id": self.worker_id,
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def verify_worker_permission_manifest(payload: Mapping[str, object]) -> WorkerPermissionManifest:
    """Parse a strict JSON-shaped mapping and return a digestable manifest."""

    if not isinstance(payload, Mapping):
        raise WorkerPermissionManifestError("manifest must be an object")
    required = {
        "worker_id",
        "principal_id",
        "discovery_permission",
        "execution_permission",
        "granted_permissions",
        "scope",
    }
    if set(payload) != required:
        raise WorkerPermissionManifestError("manifest fields do not match the closed contract")
    grants = payload["granted_permissions"]
    if not isinstance(grants, (list, tuple)):
        raise WorkerPermissionManifestError("granted_permissions must be an array")
    return WorkerPermissionManifest(
        worker_id=payload["worker_id"],  # type: ignore[arg-type]
        principal_id=payload["principal_id"],  # type: ignore[arg-type]
        discovery_permission=payload["discovery_permission"],  # type: ignore[arg-type]
        execution_permission=payload["execution_permission"],  # type: ignore[arg-type]
        granted_permissions=tuple(cast(list[str] | tuple[str, ...], grants)),
        scope=payload["scope"],  # type: ignore[arg-type]
    )


__all__ = ["WorkerPermissionManifest", "WorkerPermissionManifestError", "verify_worker_permission_manifest"]
