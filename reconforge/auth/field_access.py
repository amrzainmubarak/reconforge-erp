"""Deterministic field authorization and masking primitives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

REDACTED_VALUE = "[REDACTED]"

# These are response-contract fields, not database columns.  Keeping the
# allowlist here makes the sensitive evidence boundary explicit and gives
# every adapter the same fail-closed projection policy.
EVIDENCE_DRILL_DOWN_FIELDS = frozenset(
    {
        "tenant_id",
        "workspace_id",
        "id",
        "evidence_id",
        "evidence_code",
        "source_name",
        "source_path",
        "source_reference",
        "checksum_sha256",
        "provenance_type",
        "redaction_status",
        "evidence_status",
        "storage_backend",
        "storage_tenant_id",
        "storage_key",
        "storage_version_id",
        "content_type",
        "byte_size",
        "retention_until",
        "retention_version",
        "last_verified_at",
        "last_verified_sha256",
        "verification_status",
        "registered_by",
        "created_at",
        "updated_at",
        "links",
    }
)
EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS = frozenset(
    {
        "source_path",
        "source_reference",
        "checksum_sha256",
        "storage_backend",
        "storage_tenant_id",
        "storage_key",
        "storage_version_id",
        "content_type",
        "byte_size",
        "retention_until",
        "retention_version",
        "last_verified_at",
        "last_verified_sha256",
        "verification_status",
    }
)
EVIDENCE_DRILL_DOWN_LINK_FIELDS = frozenset(
    {"tenant_id", "id", "evidence_id", "object_type", "object_id", "link_type", "created_at"}
)


@dataclass(frozen=True)
class FieldProjection:
    """Allowlisted projection with explicit masked and denied field evidence."""

    visible: dict[str, object]
    masked_fields: tuple[str, ...]
    denied_fields: tuple[str, ...]
    projection_digest: str


def project_fields(
    values: Mapping[str, object],
    *,
    allowed_fields: frozenset[str],
    masked_fields: frozenset[str] = frozenset(),
    mask_value: object = REDACTED_VALUE,
) -> FieldProjection:
    """Project only authorized fields; masking never silently becomes access."""
    if not isinstance(values, Mapping):
        raise TypeError("values must be a mapping")
    if not masked_fields.issubset(allowed_fields):
        raise ValueError("masked fields must be a subset of allowed fields")
    visible: dict[str, object] = {}
    masked: list[str] = []
    denied: list[str] = []
    for name in sorted(values):
        if name not in allowed_fields:
            denied.append(name)
        elif name in masked_fields:
            visible[name] = mask_value
            masked.append(name)
        else:
            visible[name] = values[name]
    digest_payload = {
        "masked_fields": masked,
        "denied_fields": denied,
        "mask_value": mask_value,
        "visible": visible,
        "version": "field-projection-v1",
    }
    digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    return FieldProjection(visible, tuple(masked), tuple(denied), digest)


def project_evidence_drill_down_record(
    values: Mapping[str, object],
    *,
    include_sensitive: bool,
    legacy_mask_value: str = "***redacted***",
) -> FieldProjection:
    """Return the versioned, fail-closed evidence response projection.

    The repositories may expose different physical schemas (SQLite and
    PostgreSQL) and may gain columns over time.  The API therefore projects
    both modes from one response allowlist.  Public reads retain the existing
    redaction token for compatibility; sensitive reads still cannot expose an
    unreviewed future column.
    """

    if not isinstance(values, Mapping):
        raise TypeError("values must be a mapping")
    record = dict(values)
    links = record.get("links")
    if isinstance(links, list):
        projected_links: list[dict[str, object]] = []
        for link in links:
            if not isinstance(link, Mapping):
                raise TypeError("evidence links must be mappings")
            link_projection = project_fields(
                link,
                allowed_fields=EVIDENCE_DRILL_DOWN_LINK_FIELDS,
                masked_fields=frozenset(),
            )
            projected_links.append(link_projection.visible)
        record["links"] = projected_links
    elif links is not None:
        raise TypeError("evidence links must be a list")

    masked_fields = frozenset() if include_sensitive else EVIDENCE_DRILL_DOWN_SENSITIVE_FIELDS
    return project_fields(
        record,
        allowed_fields=EVIDENCE_DRILL_DOWN_FIELDS,
        masked_fields=masked_fields,
        mask_value=legacy_mask_value,
    )
