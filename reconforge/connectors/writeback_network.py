"""Explicit, digest-bound HTTPS transport for governed write-back intents.

The transport is an opt-in provider boundary. It resolves a short-lived
payload and credential only for the call, verifies the payload against the
intent digest, uses the original idempotency key on every retry, and returns a
replayable receipt. It never persists payloads, credentials, or provider
responses.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reconforge.connectors.manifest import RetryPolicy
from reconforge.connectors.network import (
    AddressResolver,
    ConnectionFactory,
    ConnectorNetworkError,
    ConnectorSecretResolver,
    DisabledConnectorSecretResolver,
    _connection_factory,
    _system_resolver,
    resolve_public_addresses,
)
from reconforge.connectors.writeback import (
    WritebackAcknowledgement,
    WritebackError,
    WritebackIntent,
    WritebackPolicy,
    WritebackStatus,
    complete_compensation,
)

_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
_OPERATION_PATTERN = r"^[a-z][a-z0-9._-]{0,127}$"
_SECRET_REFERENCE_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,255}$"  # nosec B105 - reference syntax, not a secret
_OPERATION_RE = re.compile(_OPERATION_PATTERN)


class WritebackNetworkError(WritebackError):
    """Safe write-back transport failure without provider or secret disclosure."""


class WritebackNetworkRegistration(BaseModel):
    """Closed runtime registration for one explicitly enabled write boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registration_schema: Literal["writeback-network-registration-v1"]
    connector_id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$")
    endpoint: str = Field(min_length=1, max_length=2_048)
    egress_destinations: tuple[str, ...] = Field(min_length=1, max_length=8)
    credential_reference: str = Field(pattern=_SECRET_REFERENCE_PATTERN)
    allowed_operations: frozenset[str] = Field(min_length=1, max_length=64)
    allowed_compensation_operations: frozenset[str] = Field(default_factory=frozenset, max_length=64)
    feature_enabled: bool = False
    synthetic_sandbox: bool = True
    rate_limit_per_minute: int = Field(default=60, ge=1, le=1_000_000)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    maximum_request_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    maximum_response_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    retry_policy: RetryPolicy = RetryPolicy(maximum_attempts=3, initial_delay_seconds=1, maximum_delay_seconds=8)

    @model_validator(mode="after")
    def validate_boundary(self) -> WritebackNetworkRegistration:
        if any(_OPERATION_RE.fullmatch(operation) is None for operation in self.allowed_operations):
            raise ValueError("allowed_operations contains invalid operation")
        if any(_OPERATION_RE.fullmatch(operation) is None for operation in self.allowed_compensation_operations):
            raise ValueError("allowed_compensation_operations contains invalid operation")
        if tuple(sorted(set(self.egress_destinations))) != self.egress_destinations:
            raise ValueError("egress destinations must be unique and canonically sorted")
        if self.endpoint not in self.egress_destinations:
            raise ValueError("endpoint must exactly match one declared egress destination")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("write-back endpoint must be an exact HTTPS URL without credentials, query, or fragment")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("write-back endpoint port is invalid") from exc
        if port is not None and not 1 <= port <= 65_535:
            raise ValueError("write-back endpoint port is invalid")
        for destination in self.egress_destinations:
            destination_parts = urlsplit(destination)
            if (
                destination_parts.scheme.lower() != "https"
                or not destination_parts.hostname
                or destination_parts.username is not None
                or destination_parts.password is not None
                or destination_parts.query
                or destination_parts.fragment
            ):
                raise ValueError("write-back egress destinations must be exact HTTPS URLs without credentials, query, or fragment")
        return self

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_none=False),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


class WritebackProviderResponse(BaseModel):
    """Closed provider acknowledgement envelope used by the reference adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_reference: str = Field(min_length=1, max_length=512)
    idempotency_key: str = Field(min_length=1, max_length=200)
    accepted: bool
    response_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def canonical_without_digest(self) -> bytes:
        payload = self.model_dump(mode="json", exclude={"response_digest"})
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")

    @model_validator(mode="after")
    def validate_response_digest(self) -> WritebackProviderResponse:
        expected = hashlib.sha256(self.canonical_without_digest).hexdigest()
        if self.response_digest != expected:
            raise ValueError("provider response digest mismatch")
        return self


@dataclass(frozen=True)
class WritebackNetworkResponse:
    status: int
    body: bytes
    content_type: str = "application/json"


class WritebackNetworkTransport(Protocol):
    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> WritebackNetworkResponse: ...


class WritebackPayloadResolver(Protocol):
    def resolve(self, intent: WritebackIntent) -> bytes: ...


@dataclass(frozen=True)
class PinnedHttpsPostTransport:
    """HTTPS POST transport pinned to a resolved public address."""

    resolver: AddressResolver = field(default=_system_resolver, repr=False, compare=False)
    connection_factory: ConnectionFactory = field(default=_connection_factory, repr=False, compare=False)
    tls_context: ssl.SSLContext = field(default_factory=ssl.create_default_context, repr=False, compare=False)

    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> WritebackNetworkResponse:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise WritebackNetworkError("writeback_endpoint_invalid")
        host = parsed.hostname
        port = parsed.port or 443
        addresses = resolve_public_addresses(host, port, resolver=self.resolver)
        connection = self.connection_factory(host, port, addresses[0], timeout_seconds, self.tls_context)
        try:
            connection.request("POST", parsed.path or "/", body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read(maximum_response_bytes + 1)
            if len(response_body) > maximum_response_bytes:
                raise WritebackNetworkError("writeback_response_too_large")
            return WritebackNetworkResponse(
                status=int(response.status),
                body=response_body,
                content_type=response.getheader("Content-Type") or "",
            )
        except WritebackNetworkError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise WritebackNetworkError("writeback_transport_failed") from exc
        finally:
            connection.close()


@dataclass(frozen=True)
class WritebackNetworkDispatch:
    intent: WritebackIntent
    request_digest: str
    response_digest: str
    attempts: int


Sleeper = Callable[[float], None]
Clock = Callable[[], float]


def _canonical_request_digest(
    intent: WritebackIntent,
    registration: WritebackNetworkRegistration,
    *,
    operation: str | None = None,
    idempotency_key: str | None = None,
    payload_digest: str | None = None,
) -> str:
    payload = {
        "connector_id": intent.connector_id,
        "connector_version": registration.version,
        "operation": operation or intent.operation,
        "idempotency_key": idempotency_key or intent.idempotency_key,
        "payload_digest": payload_digest or intent.payload_digest,
        "registration_digest": registration.digest,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_credential(resolver: ConnectorSecretResolver, reference: str) -> str:
    try:
        credential = resolver.resolve(reference)
    except ConnectorNetworkError as exc:
        if str(exc) == "connector_secret_resolution_disabled":
            raise WritebackNetworkError("writeback_secret_resolution_disabled") from exc
        raise WritebackNetworkError("writeback_secret_resolution_failed") from exc
    except Exception as exc:
        raise WritebackNetworkError("writeback_secret_resolution_failed") from exc
    if not 16 <= len(credential) <= 4_096:
        raise WritebackNetworkError("writeback_credential_invalid")
    try:
        text = credential.decode("ascii")
    except UnicodeDecodeError as exc:
        raise WritebackNetworkError("writeback_credential_invalid") from exc
    if any(ord(character) < 33 or ord(character) > 126 for character in text):
        raise WritebackNetworkError("writeback_credential_invalid")
    return text


@dataclass
class WritebackNetworkExecutor:
    """Resolve, verify, and dispatch one approved intent with bounded retries."""

    transport: WritebackNetworkTransport
    payload_resolver: WritebackPayloadResolver
    secret_resolver: ConnectorSecretResolver = field(default_factory=DisabledConnectorSecretResolver)
    sleeper: Sleeper = field(default=lambda _seconds: None, repr=False)
    clock: Clock = field(default=time.monotonic, repr=False)
    _next_allowed_at: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    def dispatch(
        self,
        intent: WritebackIntent,
        *,
        registration: WritebackNetworkRegistration,
        policy: WritebackPolicy,
    ) -> WritebackNetworkDispatch:
        policy.authorize(intent)
        if not registration.feature_enabled or not intent.feature_enabled:
            raise WritebackNetworkError("writeback_network_feature_disabled")
        if intent.status is not WritebackStatus.DISPATCHED:
            raise WritebackNetworkError("writeback_network_dispatch_requires_dispatched")
        if intent.connector_id != registration.connector_id:
            raise WritebackNetworkError("writeback_connector_not_allowed")
        if intent.operation not in registration.allowed_operations:
            raise WritebackNetworkError("writeback_operation_not_allowed")
        try:
            payload = self.payload_resolver.resolve(intent)
        except Exception as exc:
            raise WritebackNetworkError("writeback_payload_resolution_failed") from exc
        if not isinstance(payload, bytes):
            raise WritebackNetworkError("writeback_payload_invalid")
        if not payload or len(payload) > registration.maximum_request_bytes:
            raise WritebackNetworkError("writeback_payload_size_invalid")
        if hashlib.sha256(payload).hexdigest() != intent.payload_digest:
            raise WritebackNetworkError("writeback_payload_digest_mismatch")
        provider, attempts = self._post_and_validate(
            registration=registration,
            payload=payload,
            idempotency_key=intent.idempotency_key,
            operation=intent.operation,
            error_prefix="writeback",
        )
        acknowledged = intent.model_copy(
            update={
                "status": WritebackStatus.ACKNOWLEDGED,
                "acknowledgement": WritebackAcknowledgement(
                    provider_reference=provider.provider_reference,
                    acknowledged_at=datetime.now(UTC),
                    response_digest=provider.response_digest,
                    idempotency_key=provider.idempotency_key,
                    accepted=provider.accepted,
                ),
            }
        )
        return WritebackNetworkDispatch(
            intent=acknowledged,
            request_digest=_canonical_request_digest(intent, registration),
            response_digest=provider.response_digest,
            attempts=attempts,
        )

    def dispatch_compensation(
        self,
        intent: WritebackIntent,
        *,
        registration: WritebackNetworkRegistration,
        policy: WritebackPolicy,
        payload: bytes,
        payload_digest: str,
    ) -> WritebackNetworkDispatch:
        """Dispatch an explicitly allowlisted compensation mutation.

        Compensation is a separate provider operation and idempotency domain.
        The caller supplies a short-lived, already-authorized payload in
        memory; this executor never persists it or reuses the original payload
        implicitly. Provider acknowledgement must carry the ``:compensation``
        key before the intent can become ``compensated``.
        """

        policy.authorize(intent)
        if not registration.feature_enabled or not intent.feature_enabled:
            raise WritebackNetworkError("writeback_network_feature_disabled")
        if intent.status is not WritebackStatus.COMPENSATION_REQUESTED:
            raise WritebackNetworkError("writeback_compensation_requires_requested")
        if intent.connector_id != registration.connector_id:
            raise WritebackNetworkError("writeback_connector_not_allowed")
        if intent.operation not in registration.allowed_compensation_operations:
            raise WritebackNetworkError("writeback_compensation_operation_not_allowed")
        if not isinstance(payload, bytes):
            raise WritebackNetworkError("writeback_compensation_payload_invalid")
        if not payload or len(payload) > registration.maximum_request_bytes:
            raise WritebackNetworkError("writeback_compensation_payload_size_invalid")
        if hashlib.sha256(payload).hexdigest() != payload_digest:
            raise WritebackNetworkError("writeback_compensation_payload_digest_mismatch")
        compensation_key = intent.idempotency_key + ":compensation"
        if len(compensation_key) > 200:
            raise WritebackNetworkError("writeback_compensation_idempotency_key_invalid")
        compensation_operation = "compensate." + intent.operation
        provider, attempts = self._post_and_validate(
            registration=registration,
            payload=payload,
            idempotency_key=compensation_key,
            operation=compensation_operation,
            error_prefix="writeback_compensation",
        )
        acknowledgement = WritebackAcknowledgement(
            provider_reference=provider.provider_reference,
            acknowledged_at=datetime.now(UTC),
            response_digest=provider.response_digest,
            idempotency_key=provider.idempotency_key,
            accepted=provider.accepted,
        )
        try:
            compensated = complete_compensation(intent, acknowledgement=acknowledgement)
        except WritebackError as exc:
            raise WritebackNetworkError(str(exc)) from exc
        return WritebackNetworkDispatch(
            intent=compensated,
            request_digest=_canonical_request_digest(
                intent,
                registration,
                operation=compensation_operation,
                idempotency_key=compensation_key,
                payload_digest=payload_digest,
            ),
            response_digest=provider.response_digest,
            attempts=attempts,
        )

    def _post_and_validate(
        self,
        *,
        registration: WritebackNetworkRegistration,
        payload: bytes,
        idempotency_key: str,
        operation: str,
        error_prefix: str,
    ) -> tuple[WritebackProviderResponse, int]:
        credential = _resolve_credential(self.secret_resolver, registration.credential_reference)
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + credential,
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
            "User-Agent": "ReconForge-Writeback/1",
            "X-ReconForge-Operation": operation,
        }
        attempts = 0
        while attempts < registration.retry_policy.maximum_attempts:
            attempts += 1
            self._apply_rate_limit(registration)
            try:
                response = self.transport.post(
                    registration.endpoint,
                    headers=headers,
                    body=payload,
                    timeout_seconds=registration.timeout_seconds,
                    maximum_response_bytes=registration.maximum_response_bytes,
                )
            except WritebackNetworkError as exc:
                if str(exc) != "writeback_transport_failed" or attempts >= registration.retry_policy.maximum_attempts:
                    raise
                self._retry_wait(registration, attempts)
                continue
            if len(response.body) > registration.maximum_response_bytes:
                raise WritebackNetworkError(f"{error_prefix}_response_too_large")
            if response.status < 200 or response.status >= 300:
                if response.status not in {408, 425, 429} and not 500 <= response.status < 600:
                    raise WritebackNetworkError(f"{error_prefix}_permanent_http_failure")
                if attempts >= registration.retry_policy.maximum_attempts:
                    raise WritebackNetworkError(f"{error_prefix}_retry_exhausted")
                self._retry_wait(registration, attempts)
                continue
            if response.content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise WritebackNetworkError(f"{error_prefix}_response_content_type_invalid")
            try:
                provider = WritebackProviderResponse.model_validate_json(response.body)
            except (TypeError, ValueError) as exc:
                raise WritebackNetworkError(f"{error_prefix}_response_schema_invalid") from exc
            if provider.idempotency_key != idempotency_key:
                raise WritebackNetworkError(f"{error_prefix}_acknowledgement_mismatch")
            return provider, attempts
        raise WritebackNetworkError(f"{error_prefix}_retry_exhausted")

    def _apply_rate_limit(self, registration: WritebackNetworkRegistration) -> None:
        now = self.clock()
        allowed_at = self._next_allowed_at.get(registration.connector_id, now)
        if allowed_at > now:
            self.sleeper(allowed_at - now)
            now = allowed_at
        self._next_allowed_at[registration.connector_id] = now + (60.0 / registration.rate_limit_per_minute)

    def _retry_wait(self, registration: WritebackNetworkRegistration, attempt: int) -> None:
        policy = registration.retry_policy
        delay = min(policy.maximum_delay_seconds, policy.initial_delay_seconds * (2 ** (attempt - 1)))
        if delay:
            self.sleeper(float(delay))


__all__ = [
    "PinnedHttpsPostTransport",
    "WritebackNetworkDispatch",
    "WritebackNetworkError",
    "WritebackNetworkExecutor",
    "WritebackNetworkRegistration",
    "WritebackNetworkResponse",
    "WritebackNetworkTransport",
    "WritebackPayloadResolver",
    "WritebackProviderResponse",
]
