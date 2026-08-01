"""Backend-neutral request idempotency contract."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

_TENANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class IdempotencyError(RuntimeError):
    """Base safe idempotency failure."""


class IdempotencyConflictError(IdempotencyError):
    """Raised when a scoped key is bound to different request bytes."""


class IdempotencyInProgressError(IdempotencyError):
    """Raised when an equivalent request is still owned by another execution."""


class IdempotencyOwnershipError(IdempotencyError):
    """Raised when completion does not carry the current reservation token."""


def _utc(value: str) -> datetime:
    if len(value) != 20 or not value.endswith("Z"):
        raise IdempotencyError("Idempotency timestamp must use canonical UTC second precision.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IdempotencyError("Idempotency timestamp is invalid.") from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise IdempotencyError("Idempotency timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)


def digest_bytes(value: bytes) -> str:
    """Return the canonical request/response digest."""

    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class IdempotencyReservation:
    """One scoped key binding and its optional completed response."""

    schema_version: int
    tenant_id: str
    scope: str
    key: str
    request_digest: str
    owner_token: str
    status: str
    response: bytes
    response_digest: str
    content_type: str
    created_at: str
    expires_at: str
    completed_at: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.status not in {"pending", "completed"}:
            raise IdempotencyError("Idempotency reservation version or status is unsupported.")
        if any(
            not str(value).strip()
            for value in (self.tenant_id, self.scope, self.key, self.request_digest, self.owner_token)
        ):
            raise IdempotencyError("Idempotency identity fields must not be blank.")
        if not _TENANT_PATTERN.fullmatch(self.tenant_id):
            raise IdempotencyError("Idempotency tenant scope is invalid.")
        if len(self.scope) > 160 or len(self.key) > 200 or len(self.owner_token) > 200:
            raise IdempotencyError("Idempotency identity field exceeds its limit.")
        if any(ord(character) < 32 for value in (self.scope, self.key, self.owner_token) for character in value):
            raise IdempotencyError("Idempotency identity field contains control characters.")
        if len(self.request_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.request_digest
        ):
            raise IdempotencyError("Idempotency request digest is invalid.")
        created, expires = _utc(self.created_at), _utc(self.expires_at)
        if expires <= created:
            raise IdempotencyError("Idempotency expiry must follow creation.")
        if self.status == "pending" and (self.response or self.response_digest or self.completed_at):
            raise IdempotencyError("Pending idempotency reservation cannot contain a response.")
        if self.status == "completed":
            if not self.completed_at or digest_bytes(self.response) != self.response_digest:
                raise IdempotencyError("Completed idempotency response failed integrity validation.")
            _utc(self.completed_at)


@dataclass(frozen=True)
class IdempotencyBeginResult:
    reservation: IdempotencyReservation
    created: bool
    replayed: bool


class IdempotencyRepositoryProtocol(Protocol):
    def begin(self, reservation: IdempotencyReservation, *, observed_at: str) -> IdempotencyBeginResult: ...

    def complete(
        self,
        reservation: IdempotencyReservation,
        *,
        response: bytes,
        response_digest: str,
        content_type: str,
        completed_at: str,
    ) -> IdempotencyReservation: ...


class IdempotencyApplicationService:
    """Reserve or replay request outcomes without provider-specific behavior."""

    def __init__(
        self,
        repository: IdempotencyRepositoryProtocol,
        *,
        max_request_bytes: int = 1024 * 1024,
        max_response_bytes: int = 1024 * 1024,
    ) -> None:
        if not 1 <= max_request_bytes <= 16 * 1024 * 1024 or not 1 <= max_response_bytes <= 16 * 1024 * 1024:
            raise IdempotencyError("Idempotency request or response limit is invalid.")
        self.repository = repository
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes

    def begin(
        self,
        *,
        tenant_id: str,
        scope: str,
        key: str,
        request: bytes,
        owner_token: str,
        created_at: str,
        expires_at: str,
        observed_at: str,
    ) -> IdempotencyBeginResult:
        if not isinstance(request, bytes) or len(request) > self.max_request_bytes:
            raise IdempotencyError("Idempotency request exceeds its configured byte limit.")
        _utc(observed_at)
        reservation = IdempotencyReservation(
            1,
            tenant_id,
            scope,
            key,
            digest_bytes(request),
            owner_token,
            "pending",
            b"",
            "",
            "",
            created_at,
            expires_at,
            "",
        )
        return self.repository.begin(reservation, observed_at=observed_at)

    def complete(
        self,
        reservation: IdempotencyReservation,
        *,
        response: bytes,
        content_type: str,
        completed_at: str,
    ) -> IdempotencyReservation:
        if not isinstance(response, bytes) or len(response) > self.max_response_bytes:
            raise IdempotencyError("Idempotency response exceeds its configured byte limit.")
        if not content_type.strip() or any(ord(character) < 32 for character in content_type):
            raise IdempotencyError("Idempotency response content type is invalid.")
        _utc(completed_at)
        return self.repository.complete(
            reservation,
            response=response,
            response_digest=digest_bytes(response),
            content_type=content_type,
            completed_at=completed_at,
        )
