"""Bounded read-only HTTPS execution for data-only connector registrations."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reconforge.connectors.manifest import AuthenticationMethod, ConnectorKind, ConnectorManifest

MAX_CURSOR_BYTES = 4_096
MAX_IDEMPOTENCY_KEY_BYTES = 200
_CURSOR_PARAMETER_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"
_QUERY_PARAMETER_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"
MAX_QUERY_PARAMETERS = 16
MAX_QUERY_PARAMETER_VALUE_BYTES = 4_096


class ConnectorNetworkError(RuntimeError):
    """Safe network connector failure with no response or credential disclosure."""


class NetworkConnectorRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registration_schema: str = Field(pattern=r"^network-connector-registration-v1$")
    manifest: ConnectorManifest
    endpoint: str = Field(min_length=1, max_length=2_048)
    credential_reference: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,255}$")
    credential_auth_scheme: Literal["bearer", "token"] = "bearer"
    cursor_query_parameter: str | None = Field(default=None, pattern=_CURSOR_PARAMETER_PATTERN)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    maximum_response_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)

    @model_validator(mode="after")
    def validate_runtime_boundary(self) -> NetworkConnectorRegistration:
        if self.manifest.kind is not ConnectorKind.NETWORK_SOURCE or not self.manifest.network_required:
            raise ValueError("network registration requires a network-source manifest")
        if self.manifest.authentication not in {AuthenticationMethod.NONE, AuthenticationMethod.SECRET_REFERENCE}:
            raise ValueError("network registration v1 supports no-auth or secret-reference authentication only")
        if self.manifest.authentication is AuthenticationMethod.SECRET_REFERENCE and self.credential_reference is None:
            raise ValueError("secret-reference authentication requires credential_reference")
        if self.manifest.authentication is AuthenticationMethod.NONE and self.credential_reference is not None:
            raise ValueError("no-auth network registration cannot carry credential_reference")
        if self.cursor_query_parameter is not None and not self.manifest.incremental_cursor:
            raise ValueError("cursor_query_parameter requires incremental cursor support")
        if self.cursor_query_parameter is not None:
            existing_query_keys = {key for key, _value in parse_qsl(urlsplit(self.endpoint).query, keep_blank_values=True)}
            if self.cursor_query_parameter in existing_query_keys:
                raise ValueError("cursor_query_parameter must not already exist in endpoint")
        if self.manifest.authentication is AuthenticationMethod.NONE and self.credential_auth_scheme != "bearer":
            raise ValueError("no-auth network registration cannot declare token authentication")
        if self.endpoint not in self.manifest.egress_destinations:
            raise ValueError("endpoint must exactly match one declared egress destination")
        if (urlsplit(self.endpoint).scheme or "").lower() != "https":
            raise ValueError("network registration v1 requires an HTTPS endpoint")
        return self

    @property
    def digest(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=False)
        # Preserve v1 digests for registrations that use the original bearer
        # header and header-only cursor behavior. New provider-specific modes
        # remain digest-bound without invalidating existing durable jobs.
        if self.credential_auth_scheme == "bearer":
            payload.pop("credential_auth_scheme", None)
        if self.cursor_query_parameter is None:
            payload.pop("cursor_query_parameter", None)
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
            # The query is part of the operator-declared exact egress
            # destination. It is never merged with runtime input, so preserving
            # it does not widen the allowlist or create redirect-following.
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
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
    circuit_failure_threshold: int = 3
    circuit_open_seconds: float = 30.0
    _circuit_failures: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _circuit_open_until: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _circuit_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.circuit_failure_threshold, int) or isinstance(self.circuit_failure_threshold, bool):
            raise ValueError("circuit_failure_threshold must be an integer")
        if not 1 <= self.circuit_failure_threshold <= 100:
            raise ValueError("circuit_failure_threshold must be between 1 and 100")
        if isinstance(self.circuit_open_seconds, bool) or not isinstance(self.circuit_open_seconds, (int, float)):
            raise ValueError("circuit_open_seconds must be numeric")
        if not 0 <= float(self.circuit_open_seconds) <= 3_600:
            raise ValueError("circuit_open_seconds must be between 0 and 3600")

    def read(
        self,
        registration: NetworkConnectorRegistration,
        *,
        idempotency_key: str,
        cursor: str | None = None,
        query_parameters: tuple[tuple[str, str], ...] = (),
    ) -> ConnectorReadResult:
        key_bytes = idempotency_key.encode("utf-8")
        if not key_bytes or len(key_bytes) > MAX_IDEMPOTENCY_KEY_BYTES or any(ord(char) < 33 for char in idempotency_key):
            raise ConnectorNetworkError("connector_idempotency_key_invalid")
        if cursor is not None and (not cursor or len(cursor.encode("utf-8")) > MAX_CURSOR_BYTES):
            raise ConnectorNetworkError("connector_cursor_invalid")
        if not isinstance(query_parameters, tuple) or len(query_parameters) > MAX_QUERY_PARAMETERS:
            raise ConnectorNetworkError("connector_query_parameters_invalid")
        query_keys: set[str] = set()
        for item in query_parameters:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ConnectorNetworkError("connector_query_parameters_invalid")
            key, value = item
            if (
                not isinstance(key, str)
                or not isinstance(value, str)
                or key in query_keys
                or re.fullmatch(_QUERY_PARAMETER_PATTERN, key) is None
                or len(key.encode("utf-8")) > 64
                or len(value.encode("utf-8")) > MAX_QUERY_PARAMETER_VALUE_BYTES
                or any(ord(character) < 33 or ord(character) == 127 for character in value)
            ):
                raise ConnectorNetworkError("connector_query_parameters_invalid")
            query_keys.add(key)
        if tuple(sorted(query_parameters)) != query_parameters:
            raise ConnectorNetworkError("connector_query_parameters_invalid")
        manifest = registration.manifest
        if not manifest.idempotent_reads:
            raise ConnectorNetworkError("connector_idempotent_reads_required")
        if cursor is not None and not manifest.incremental_cursor:
            raise ConnectorNetworkError("connector_cursor_not_supported")
        circuit_key = (
            f"{manifest.connector_id}|{registration.endpoint}|{registration.credential_reference or 'public'}"
        )
        self._ensure_circuit_available(circuit_key)
        credential: bytes | None = None
        if manifest.authentication is AuthenticationMethod.SECRET_REFERENCE:
            if registration.credential_reference is None:
                raise ConnectorNetworkError("connector_credential_missing")
            credential = self.secret_resolver.resolve(registration.credential_reference)
            if not 16 <= len(credential) <= 4_096:
                raise ConnectorNetworkError("connector_credential_invalid")
        request_endpoint = registration.endpoint
        parsed_endpoint = urlsplit(request_endpoint)
        existing_query_keys = {key for key, _value in parse_qsl(parsed_endpoint.query, keep_blank_values=True)}
        if query_keys.intersection(existing_query_keys):
            raise ConnectorNetworkError("connector_query_parameters_invalid")
        if registration.cursor_query_parameter is not None and registration.cursor_query_parameter in query_keys:
            raise ConnectorNetworkError("connector_query_parameters_invalid")
        runtime_query_items = list(query_parameters)
        if cursor is not None and registration.cursor_query_parameter is not None:
            runtime_query_items.append((registration.cursor_query_parameter, cursor))
        if runtime_query_items:
            runtime_query = urlencode(runtime_query_items)
            request_endpoint = urlunsplit(
                (
                    parsed_endpoint.scheme,
                    parsed_endpoint.netloc,
                    parsed_endpoint.path,
                    parsed_endpoint.query + ("&" if parsed_endpoint.query else "") + runtime_query,
                    parsed_endpoint.fragment,
                )
            )
        request_payload: dict[str, object] = {
            "connector_id": manifest.connector_id,
            "connector_version": manifest.version,
            "cursor": cursor,
            "endpoint": registration.endpoint,
            "idempotency_key": idempotency_key,
            "manifest_digest": manifest.digest,
        }
        if request_endpoint != registration.endpoint:
            request_payload["request_endpoint"] = request_endpoint
        request_digest = _canonical_digest(request_payload)
        headers = {
            "Accept": "application/json",
            "Idempotency-Key": idempotency_key,
            "User-Agent": "ReconForge-Connector/1",
        }
        if credential is not None:
            try:
                credential_text = credential.decode("ascii")
            except UnicodeDecodeError as exc:
                raise ConnectorNetworkError("connector_credential_invalid") from exc
            if any(ord(character) < 33 or ord(character) > 126 for character in credential_text):
                raise ConnectorNetworkError("connector_credential_invalid")
            prefix = "token " if registration.credential_auth_scheme == "token" else "Bearer "
            headers["Authorization"] = prefix + credential_text
        if cursor is not None:
            headers["X-ReconForge-Cursor"] = cursor
        attempt = 0
        while attempt < manifest.retry_policy.maximum_attempts:
            attempt += 1
            self._apply_rate_limit(manifest)
            try:
                response = self.transport.get(
                    request_endpoint,
                    headers=headers,
                    timeout_seconds=registration.timeout_seconds,
                    maximum_response_bytes=registration.maximum_response_bytes,
                )
            except ConnectorNetworkError as exc:
                retryable_transport = str(exc) in {
                    "connector_destination_resolution_failed",
                    "connector_destination_resolution_empty",
                    "connector_transport_failed",
                }
                if not retryable_transport or attempt >= manifest.retry_policy.maximum_attempts:
                    if retryable_transport:
                        self._record_circuit_failure(circuit_key)
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
                self._record_circuit_success(circuit_key)
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
                self._record_circuit_failure(circuit_key)
                raise ConnectorNetworkError("connector_retry_exhausted")
            self._retry_wait(manifest, attempt)
        raise ConnectorNetworkError("connector_retry_exhausted")

    def _ensure_circuit_available(self, circuit_key: str) -> None:
        with self._circuit_lock:
            open_until = self._circuit_open_until.get(circuit_key)
            if open_until is None:
                return
            now = self.clock()
            if now < open_until:
                raise ConnectorNetworkError("connector_circuit_open")
            self._circuit_open_until.pop(circuit_key, None)
            self._circuit_failures.pop(circuit_key, None)

    def _record_circuit_failure(self, circuit_key: str) -> None:
        with self._circuit_lock:
            failures = self._circuit_failures.get(circuit_key, 0) + 1
            self._circuit_failures[circuit_key] = failures
            if failures >= self.circuit_failure_threshold:
                self._circuit_open_until[circuit_key] = self.clock() + float(self.circuit_open_seconds)

    def _record_circuit_success(self, circuit_key: str) -> None:
        with self._circuit_lock:
            self._circuit_failures.pop(circuit_key, None)
            self._circuit_open_until.pop(circuit_key, None)

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
