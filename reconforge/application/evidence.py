"""Backend-neutral evidence-registry application boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

LOCAL_STORAGE_BACKEND = "local-filesystem"
OBJECT_STORAGE_BACKEND = "s3-compatible-object-storage"
_STORAGE_SCOPE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class EvidenceStorageScope:
    """Provider-neutral hierarchy used to identify one evidence artifact."""

    tenant_id: str
    workspace_id: str = ""
    entity_id: str = ""

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "workspace_id", "entity_id"):
            value = str(getattr(self, field_name) or "").strip().lower()
            if (field_name == "tenant_id" or value) and not _STORAGE_SCOPE_ID_PATTERN.fullmatch(value):
                raise ValueError(f"{field_name} has an invalid storage-scope format.")
            object.__setattr__(self, field_name, value)
        if self.entity_id and not self.workspace_id:
            raise ValueError("entity_id requires workspace_id.")


@dataclass(frozen=True)
class EvidenceVerification:
    """Checksum verification result for one evidence object."""

    evidence_id: str
    ok: bool
    expected_sha256: str
    actual_sha256: str


class StoredEvidenceObject(Protocol):
    """Structural result returned by evidence object stores."""

    @property
    def content(self) -> bytes: ...

    @property
    def sha256(self) -> str: ...

    @property
    def metadata(self) -> dict[str, str]: ...

    @property
    def version_id(self) -> str | None: ...


class EvidenceObjectStore(Protocol):
    """Minimal object-storage contract required by the evidence registry."""

    def put_bytes(
        self,
        tenant_id: str,
        object_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, object] | None = None,
        retention_until: datetime | None = None,
    ) -> StoredEvidenceObject: ...

    def get_bytes(self, tenant_id: str, object_name: str) -> StoredEvidenceObject: ...


class HierarchicalEvidenceObjectStore(Protocol):
    """Optional capability for tenant/workspace/entity-separated object stores."""

    supports_hierarchical_scope: bool

    def put_bytes(
        self,
        tenant_id: str | EvidenceStorageScope,
        object_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, object] | None = None,
        retention_until: datetime | None = None,
    ) -> StoredEvidenceObject: ...

    def get_bytes(
        self,
        tenant_id: str | EvidenceStorageScope,
        object_name: str,
    ) -> StoredEvidenceObject: ...


class EvidenceRegistryRepositoryProtocol(Protocol):
    """Complete evidence persistence and integrity port."""

    def register(
        self,
        source_path: Path | str,
        *,
        evidence_code: str = "",
        workspace: str = "default",
        provenance_type: str = "local-file",
        redaction_status: str = "unknown",
        evidence_status: str = "Available",
        object_type: str = "",
        object_id: str = "",
        link_type: str = "support",
        actor_label: str = "local-cli",
        object_store: EvidenceObjectStore | None = None,
        storage_tenant_id: str = "",
        storage_object_name: str = "",
        content_type: str = "",
        retention_until: datetime | None = None,
    ) -> dict[str, Any]: ...

    def requirement(
        self,
        *,
        object_type: str,
        object_id: str,
        requirement_code: str,
        description: str,
        workspace: str = "default",
        required_status: str = "Required",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def link(
        self,
        evidence_id: str,
        *,
        object_type: str,
        object_id: str,
        link_type: str = "support",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def verify(
        self,
        evidence_id: str,
        *,
        actor_label: str = "local-cli",
        object_store: EvidenceObjectStore | None = None,
    ) -> EvidenceVerification: ...

    def coverage(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]: ...

    def list_evidence(self, *, status: str = "") -> list[dict[str, Any]]: ...

    def get(self, evidence_id: str) -> dict[str, Any]: ...

    def drill_down(
        self,
        evidence_id: str,
        *,
        direction: str = "both",
        max_depth: int = 2,
        include_sensitive: bool = False,
        limit: int = 250,
        offset: int = 0,
        actor_label: str = "",
    ) -> dict[str, Any]: ...


class EvidenceRegistryApplicationService:
    """Coordinate evidence workflows without importing a database adapter."""

    def __init__(self, repository: EvidenceRegistryRepositoryProtocol) -> None:
        self.repository = repository

    def register(
        self,
        source_path: Path | str,
        *,
        evidence_code: str = "",
        workspace: str = "default",
        provenance_type: str = "local-file",
        redaction_status: str = "unknown",
        evidence_status: str = "Available",
        object_type: str = "",
        object_id: str = "",
        link_type: str = "support",
        actor_label: str = "local-cli",
        object_store: EvidenceObjectStore | None = None,
        storage_tenant_id: str = "",
        storage_object_name: str = "",
        content_type: str = "",
        retention_until: datetime | None = None,
    ) -> dict[str, Any]:
        return self.repository.register(
            source_path,
            evidence_code=evidence_code,
            workspace=workspace,
            provenance_type=provenance_type,
            redaction_status=redaction_status,
            evidence_status=evidence_status,
            object_type=object_type,
            object_id=object_id,
            link_type=link_type,
            actor_label=actor_label,
            object_store=object_store,
            storage_tenant_id=storage_tenant_id,
            storage_object_name=storage_object_name,
            content_type=content_type,
            retention_until=retention_until,
        )

    def requirement(
        self,
        *,
        object_type: str,
        object_id: str,
        requirement_code: str,
        description: str,
        workspace: str = "default",
        required_status: str = "Required",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.requirement(
            object_type=object_type,
            object_id=object_id,
            requirement_code=requirement_code,
            description=description,
            workspace=workspace,
            required_status=required_status,
            actor_label=actor_label,
        )

    def link(
        self,
        evidence_id: str,
        *,
        object_type: str,
        object_id: str,
        link_type: str = "support",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.link(
            evidence_id,
            object_type=object_type,
            object_id=object_id,
            link_type=link_type,
            actor_label=actor_label,
        )

    def verify(
        self,
        evidence_id: str,
        *,
        actor_label: str = "local-cli",
        object_store: EvidenceObjectStore | None = None,
    ) -> EvidenceVerification:
        return self.repository.verify(evidence_id, actor_label=actor_label, object_store=object_store)

    def coverage(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.coverage(workspace=workspace, actor_label=actor_label)

    def list_evidence(self, *, status: str = "") -> list[dict[str, Any]]:
        return self.repository.list_evidence(status=status)

    def get(self, evidence_id: str) -> dict[str, Any]:
        return self.repository.get(evidence_id)

    def drill_down(
        self,
        evidence_id: str,
        *,
        direction: str = "both",
        max_depth: int = 2,
        include_sensitive: bool = False,
        limit: int = 250,
        offset: int = 0,
        actor_label: str = "",
    ) -> dict[str, Any]:
        return self.repository.drill_down(
            evidence_id,
            direction=direction,
            max_depth=max_depth,
            include_sensitive=include_sensitive,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )
