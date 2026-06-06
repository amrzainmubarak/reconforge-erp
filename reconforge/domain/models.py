"""Pydantic domain reference models for the local database backbone."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_LOCAL_FIRST_NOTE = "Local-first workspace. Data remains in user-selected local paths."


def utc_now_text() -> str:
    """Return an ISO-8601 UTC timestamp with a Z suffix."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_domain_id(prefix: str) -> str:
    """Create a compact local domain identifier."""

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class _DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Workspace(_DomainModel):
    """A local ReconForge workspace."""

    id: str = Field(default_factory=lambda: new_domain_id("WS"))
    name: str
    created_at: str = Field(default_factory=utc_now_text)
    local_first_note: str = DEFAULT_LOCAL_FIRST_NOTE


class Organization(_DomainModel):
    """An organization inside a local workspace."""

    id: str = Field(default_factory=lambda: new_domain_id("ORG"))
    workspace_id: str
    name: str
    created_at: str = Field(default_factory=utc_now_text)


class LegalEntity(_DomainModel):
    """A legal entity reference for export-based finance workflows."""

    id: str = Field(default_factory=lambda: new_domain_id("LE"))
    organization_id: str
    entity_code: str
    name: str
    currency: str
    created_at: str = Field(default_factory=utc_now_text)


class Period(_DomainModel):
    """A local finance period reference."""

    id: str = Field(default_factory=lambda: new_domain_id("PER"))
    workspace_id: str
    name: str
    start_date: str
    end_date: str
    status: str = "Open"
    created_at: str = Field(default_factory=utc_now_text)


class UserReference(_DomainModel):
    """A user reference without authentication credentials."""

    id: str = Field(default_factory=lambda: new_domain_id("USR"))
    username: str
    display_name: str
    email: str | None = None
    disabled: bool = False
    created_at: str = Field(default_factory=utc_now_text)


class Role(_DomainModel):
    """A role reference for later RBAC primitives."""

    id: str = Field(default_factory=lambda: new_domain_id("ROLE"))
    name: str


class Permission(_DomainModel):
    """A permission reference for later RBAC primitives."""

    name: str
    description: str


class ReconciliationReference(_DomainModel):
    """A reconciliation reference for DB-backed workflows."""

    id: str = Field(default_factory=lambda: new_domain_id("REC"))
    workspace_id: str
    period_id: str
    account_id: str | None = None
    type: str = "account"
    status: str = "Draft"
    owner_user_id: str | None = None
    created_at: str = Field(default_factory=utc_now_text)


class EvidenceReference(_DomainModel):
    """A local evidence object reference."""

    id: str = Field(default_factory=lambda: new_domain_id("EVD"))
    workspace_id: str
    source_path: str
    checksum_sha256: str
    provenance_type: str
    redaction_status: str
    created_at: str = Field(default_factory=utc_now_text)


class AuditEventReference(_DomainModel):
    """An append-only audit event record reference."""

    id: str
    sequence: int = Field(ge=1)
    previous_hash: str
    event_hash: str
    actor_user_id: str | None = None
    actor_label: str
    object_type: str
    object_id: str
    action: str
    before_hash: str | None = None
    after_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
