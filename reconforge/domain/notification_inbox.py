"""Closed, deterministic control-plane envelopes for the local notification inbox."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class InboxError(ValueError):
    """Safe notification validation failure."""


class InboxConflictError(InboxError):
    """An idempotency key was reused for another publication."""


class InboxNotFoundError(InboxError):
    """No notification is visible to this recipient and scope."""


class InboxPersistenceError(RuntimeError):
    """Persistence failed without exposing driver or submitted data."""


class InboxTopic(StrEnum):
    REVIEW_REQUIRED = "workflow.review_required"
    JOB_FAILED = "job.failed"
    EXCEPTION_OPENED = "control.exception_opened"
    EVIDENCE_AVAILABLE = "evidence.available"


def inbox_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", value):
        raise InboxError(f"{field} must be a bounded identifier.")
    return value


@dataclass(frozen=True)
class InboxScope:
    tenant_id: str
    workspace_id: str
    organization_id: str = ""
    legal_entity_id: str = ""

    def __post_init__(self) -> None:
        for name in ("tenant_id", "workspace_id"):
            inbox_identifier(getattr(self, name), name)
        for name in ("organization_id", "legal_entity_id"):
            if getattr(self, name):
                inbox_identifier(getattr(self, name), name)
        if self.legal_entity_id and not self.organization_id:
            raise InboxError("Legal-entity scope requires an organization.")


@dataclass(frozen=True)
class InboxPublication:
    scope: InboxScope
    recipient_id: str
    topic: InboxTopic
    resource_type: str
    resource_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        for name in ("recipient_id", "resource_type", "resource_id", "idempotency_key"):
            inbox_identifier(getattr(self, name), name)
        try:
            object.__setattr__(self, "topic", InboxTopic(self.topic))
        except ValueError as exc:
            raise InboxError("Notification topic is unsupported.") from exc

    def digest(self, publisher_id: str) -> str:
        payload = {"schema_version": "reconforge.inbox.v1", "publisher_id": publisher_id, **asdict(self)}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class InboxNotification:
    id: str
    publication: InboxPublication
    publisher_id: str
    payload_digest: str
    created_at: str
    read_at: str | None = None

    def __post_init__(self) -> None:
        inbox_identifier(self.id, "notification_id")
        inbox_identifier(self.publisher_id, "publisher_id")
        if self.payload_digest != self.publication.digest(self.publisher_id):
            raise InboxPersistenceError("Stored notification evidence does not verify.")
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            read = datetime.fromisoformat(self.read_at.replace("Z", "+00:00")) if self.read_at is not None else None
            if created.tzinfo is None or created.utcoffset() != UTC.utcoffset(created) or (read is not None and (read.tzinfo is None or read.utcoffset() != UTC.utcoffset(read) or read < created)):
                raise ValueError("Timestamp is not ordered UTC.")
        except (TypeError, ValueError) as exc:
            raise InboxPersistenceError("Stored notification timestamps do not verify.") from exc

    def public_record(self) -> dict[str, object]:
        """Return the closed user-facing envelope without publication replay keys."""
        return {
            "id": self.id,
            "workspace_id": self.publication.scope.workspace_id,
            "organization_id": self.publication.scope.organization_id,
            "legal_entity_id": self.publication.scope.legal_entity_id,
            "recipient_id": self.publication.recipient_id,
            "topic": self.publication.topic.value,
            "resource_type": self.publication.resource_type,
            "resource_id": self.publication.resource_id,
            "payload_digest": self.payload_digest,
            "created_at": self.created_at,
            "read_at": self.read_at,
        }


@dataclass(frozen=True)
class InboxPage:
    records: tuple[InboxNotification, ...]
    total: int
    unread_count: int

    def public_record(self) -> dict[str, object]:
        return {
            "records": [record.public_record() for record in self.records],
            "total": self.total,
            "unread_count": self.unread_count,
        }


def scope_filter_values(scope: InboxScope) -> tuple[str, ...]:
    return (scope.tenant_id, scope.workspace_id, scope.organization_id, scope.organization_id, scope.legal_entity_id, scope.legal_entity_id)


def notification_from_record(row: Mapping[str, Any]) -> InboxNotification:
    scope = InboxScope(str(row["tenant_id"]), str(row["workspace_id"]), str(row["organization_id"]), str(row["legal_entity_id"]))
    publication = InboxPublication(scope, str(row["recipient_id"]), InboxTopic(row["topic"]), str(row["resource_type"]), str(row["resource_id"]), str(row["idempotency_key"]))
    def timestamp(value: object) -> str:
        return value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else str(value)
    return InboxNotification(str(row["id"]), publication, str(row["publisher_id"]), str(row["payload_digest"]), timestamp(row["created_at"]), timestamp(row["read_at"]) if row["read_at"] is not None else None)
