"""Deterministic application contract for hierarchical control-plane exports."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol

_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DATASET_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SCOPE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SCOPED_EXPORT_SCHEMA_VERSION = 1


class ScopedExportError(ValueError):
    """Raised when a scoped export is invalid or unsafe to publish."""


@dataclass(frozen=True)
class ScopedExportScope:
    """Provider-neutral hierarchy required by one Enterprise export."""

    tenant_id: str
    workspace_id: str
    organization_id: str = ""
    entity_id: str = ""

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "workspace_id", "organization_id", "entity_id"):
            value = str(getattr(self, field_name) or "").strip().lower()
            if (field_name in {"tenant_id", "workspace_id"} or value) and not _SCOPE_PATTERN.fullmatch(value):
                raise ScopedExportError(f"Export {field_name} is invalid.")
            object.__setattr__(self, field_name, value)
        if self.entity_id and not self.organization_id:
            raise ScopedExportError("A legal-entity export requires its organization scope.")


@dataclass(frozen=True)
class ScopedExportDataset:
    """One ordered, bounded dataset inside a control-plane snapshot."""

    name: str
    rows: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if not _DATASET_PATTERN.fullmatch(self.name):
            raise ScopedExportError("Export dataset name is invalid.")
        canonical_rows = tuple(
            sorted(
                ({str(key): value for key, value in row.items()} for row in self.rows),
                key=_canonical_json,
            )
        )
        object.__setattr__(self, "rows", canonical_rows)

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(list(self.rows)).encode("utf-8")).hexdigest()

    def payload(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "name": self.name,
            "row_count": len(self.rows),
            "rows": list(self.rows),
        }


@dataclass(frozen=True)
class ScopedExportSnapshot:
    """Canonical export whose identity includes the complete requested hierarchy."""

    scope: ScopedExportScope
    datasets: tuple[ScopedExportDataset, ...]
    schema_version: int = SCOPED_EXPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCOPED_EXPORT_SCHEMA_VERSION:
            raise ScopedExportError("Scoped export schema version is unsupported.")
        names = [dataset.name for dataset in self.datasets]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ScopedExportError("Export datasets must be unique and sorted.")

    def payload_without_digest(self) -> dict[str, object]:
        return {
            "artifact_type": "reconforge-scoped-control-plane-export",
            "datasets": [dataset.payload() for dataset in self.datasets],
            "schema_version": self.schema_version,
            "scope": {
                "entity_id": self.scope.entity_id,
                "organization_id": self.scope.organization_id,
                "tenant_id": self.scope.tenant_id,
                "workspace_id": self.scope.workspace_id,
            },
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.payload_without_digest()).encode("utf-8")).hexdigest()

    def to_bytes(self) -> bytes:
        payload = {**self.payload_without_digest(), "artifact_digest": self.digest}
        return (_canonical_json(payload) + "\n").encode("utf-8")


@dataclass(frozen=True)
class PublishedScopedExport:
    """Verified immutable reference returned after object publication."""

    digest: str
    object_name: str
    byte_size: int
    version_id: str

    def __post_init__(self) -> None:
        if not _DIGEST_PATTERN.fullmatch(self.digest):
            raise ScopedExportError("Published export digest is invalid.")
        if not self.object_name.startswith("exports/control-plane/"):
            raise ScopedExportError("Published export reference is invalid.")
        if self.byte_size <= 0:
            raise ScopedExportError("Published export must contain bytes.")


class ScopedExportRepository(Protocol):
    """Read one database-enforced hierarchy snapshot."""

    def snapshot(self, scope: ScopedExportScope) -> ScopedExportSnapshot: ...


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ScopedExportError("Scoped export contains a non-canonical value.") from exc
