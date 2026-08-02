"""Bounded read-only HTTPS execution for data-only connector registrations."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reconforge.connectors.manifest import AuthenticationMethod, ConnectorKind, ConnectorManifest

MAX_CURSOR_BYTES = 4_096
MAX_IDEMPOTENCY_KEY_BYTES = 200


class ConnectorNetworkError(RuntimeError):
    """Safe network connector failure with no response or credential disclosure."""


class NetworkConnectorRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registration_schema: str = Field(pattern=r"^network-connector-registration-v1$")
    manifest: ConnectorManifest
    endpoint: str = Field(min_length=1, max_length=2_048)
    credential_reference: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,255}$")
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    maximum_response_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)

    @model_validator(mode="after")
    def validate_runtime_boundary(self) -> NetworkConnectorRegistration:
        if self.manifest.kind is not ConnectorKind.NETWORK_SOURCE or not self.manifest.network_required:
            raise ValueError("network registration requires a network-source manifest")
        if self.manifest.authentication is not AuthenticationMethod.SECRET_REFERENCE:
            raise ValueError("network registration v1 supports secret-reference authentication only")
        if self.endpoint not in self.manifest.egress_destinations:
            raise ValueError("endpoint must exactly match one declared egress destination")
        if (urlsplit(self.endpoint).scheme or "").lower() != "https":
            raise ValueError("network registration v1 requires an HTTPS endpoint")
        return self

    @property
    def digest(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=False)
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


class ConnectorSecretResolver(Protocol):
    def resolve(self, reference: str) -> bytes: ...


class DisabledConnectorSecretResolver:
    def resolve(self, reference: str) -> bytes:
        del reference
        raise ConnectorNetworkError("connector_secret_resolution_disabled")


@dataclass(frozen=True)
class NetworkResponse:
    status: int
    body: bytes
    next_cursor: str | None = None


class NetworkTransport(Protocol):
    def get(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> NetworkResponse: ...


AddressResolver = Callable[[str, int], Iterable[str]]


def _system_resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ConnectorNetworkError("connector_destination_resolution_failed") from exc
    return tuple(str(answer[4][0]) for answer in answers)


def resolve_public_addresses(host: str, port: int, *, resolver: AddressResolver = _system_resolver) -> tuple[str, ...]:
    try:
        raw = tuple(resolver(host, port))
        addresses = tuple(sorted({ipaddress.ip_address(value) for value in raw}, key=lambda value: value.packed))
    except (TypeError, ValueError) as exc:
        raise ConnectorNetworkError("connector_destination_resolution_invalid") from exc
    if not addresses:
        raise ConnectorNetworkError("connector_destination_resolution_empty")
    if any(not address.is_global for address in addresses):
        raise ConnectorNetworkError("connector_destination_not_public")
    return tuple(str(address) for address in addresses)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, *, address: str, timeout: int, context: ssl.SSLContext) -> None:
        super().__init__(host=host, port=port, timeout=timeout, context=context)
        self._pinned_address = address
        self._create_connection = self._connect_pinned

    def _connect_pinned(
        self,
        _address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        return socket.create_connection((self._pinned_address, self.port), timeout, source_address)


ConnectionFactory = Callable[[str, int, str, int, ssl.SSLContext], Any]


def _connection_factory(host: str, port: int, address: str, timeout: int, context: ssl.SSLContext) -> Any:
    return _PinnedHTTPSConnection(host, port, address=address, timeout=timeout, context=context)


@dataclass(frozen=True)
class PinnedHttpsGetTransport:
    resolver: AddressResolver = field(default=_system_resolver, repr=False, compare=False)
    connection_factory: ConnectionFactory = field(default=_connection_factory, repr=False, compare=False)
    tls_context: ssl.SSLContext = field(default_factory=ssl.create_default_context, repr=False, compare=False)

    def get(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> NetworkResponse:
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ""
        port = parsed.port or 443
        addresses = resolve_public_addresses(host, port, resolver=self.resolver)
        connection = self.connection_factory(host, port, addresses[0], timeout_seconds, self.tls_context)
        try:
            target = parsed.path or "/"
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
            body = response.read(maximum_response_bytes + 1)
            if len(body) > maximum_response_bytes:
                raise ConnectorNetworkError("connector_response_too_large")
            return NetworkResponse(
                status=int(response.status),
                body=body,
                next_cursor=response.getheader("X-ReconForge-Next-Cursor"),
            )
        except ConnectorNetworkError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise ConnectorNetworkError("connector_transport_failed") from exc
        finally:
            connection.close()


@dataclass(frozen=True)
class ConnectorReadResult:
    response_body: bytes
    next_cursor: str | None
    request_digest: str
    response_digest: str
    attempts: int


Sleeper = Callable[[float], None]


def _canonical_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class NetworkConnectorExecutor:
    transport: NetworkTransport
    secret_resolver: ConnectorSecretResolver = field(default_factory=DisabledConnectorSecretResolver)
    sleeper: Sleeper = field(default=lambda _seconds: None, repr=False)
    _next_allowed_at: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    def read(
        self,
        registration: NetworkConnectorRegistration,
        *,
        idempotency_key: str,
        cursor: str | None = None,
    ) -> ConnectorReadResult:
        key_bytes = idempotency_key.encode("utf-8")
        if not key_bytes or len(key_bytes) > MAX_IDEMPOTENCY_KEY_BYTES or any(ord(char) < 33 for char in idempotency_key):
            raise ConnectorNetworkError("connector_idempotency_key_invalid")
        if cursor is not None and (not cursor or len(cursor.encode("utf-8")) > MAX_CURSOR_BYTES):
            raise ConnectorNetworkError("connector_cursor_invalid")
        manifest = registration.manifest
        if not manifest.idempotent_reads:
            raise ConnectorNetworkError("connector_idempotent_reads_required")
        if cursor is not None and not manifest.incremental_cursor:
            raise ConnectorNetworkError("connector_cursor_not_supported")
        credential = self.secret_resolver.resolve(registration.credential_reference)
        if not 16 <= len(credential) <= 4_096:
            raise ConnectorNetworkError("connector_credential_invalid")
        request_digest = _canonical_digest(
            {
                "connector_id": manifest.connector_id,
                "connector_version": manifest.version,
                "cursor": cursor,
                "endpoint": registration.endpoint,
                "idempotency_key": idempotency_key,
                "manifest_digest": manifest.digest,
            }
        )
        try:
            credential_text = credential.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ConnectorNetworkError("connector_credential_invalid") from exc
        if any(ord(character) < 33 or ord(character) > 126 for character in credential_text):
            raise ConnectorNetworkError("connector_credential_invalid")
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer " + credential_text,
            "Idempotency-Key": idempotency_key,
            "User-Agent": "ReconForge-Connector/1",
        }
        if cursor is not None:
            headers["X-ReconForge-Cursor"] = cursor
        attempt = 0
        while attempt < manifest.retry_policy.maximum_attempts:
            attempt += 1
            self._apply_rate_limit(manifest)
            try:
                response = self.transport.get(
                    registration.endpoint,
                    headers=headers,
                    timeout_seconds=registration.timeout_seconds,
                    maximum_response_bytes=registration.maximum_response_bytes,
                )
            except ConnectorNetworkError as exc:
                if str(exc) not in {
                    "connector_destination_resolution_failed",
                    "connector_destination_resolution_empty",
                    "connector_transport_failed",
                } or attempt >= manifest.retry_policy.maximum_attempts:
                    raise
                self._retry_wait(manifest, attempt)
                continue
            if len(response.body) > registration.maximum_response_bytes:
                raise ConnectorNetworkError("connector_response_too_large")
            if response.next_cursor is not None and (
                not manifest.incremental_cursor
                or not response.next_cursor
                or len(response.next_cursor.encode("utf-8")) > MAX_CURSOR_BYTES
            ):
                raise ConnectorNetworkError("connector_response_cursor_invalid")
            if 200 <= response.status < 300:
                return ConnectorReadResult(
                    response_body=response.body,
                    next_cursor=response.next_cursor,
                    request_digest=request_digest,
                    response_digest=hashlib.sha256(response.body).hexdigest(),
                    attempts=attempt,
                )
            if response.status not in {408, 425, 429} and not 500 <= response.status < 600:
                raise ConnectorNetworkError("connector_permanent_http_failure")
            if attempt >= manifest.retry_policy.maximum_attempts:
                raise ConnectorNetworkError("connector_retry_exhausted")
            self._retry_wait(manifest, attempt)
        raise ConnectorNetworkError("connector_retry_exhausted")

    def _apply_rate_limit(self, manifest: ConnectorManifest) -> None:
        rate = manifest.rate_limit_per_minute
        if rate is None:
            raise ConnectorNetworkError("connector_rate_limit_missing")
        now = self.clock()
        allowed_at = self._next_allowed_at.get(manifest.connector_id, now)
        if allowed_at > now:
            self.sleeper(allowed_at - now)
            now = allowed_at
        self._next_allowed_at[manifest.connector_id] = now + (60.0 / rate)

    def _retry_wait(self, manifest: ConnectorManifest, attempt: int) -> None:
        policy = manifest.retry_policy
        delay = min(policy.maximum_delay_seconds, policy.initial_delay_seconds * (2 ** (attempt - 1)))
        if delay:
            self.sleeper(float(delay))
