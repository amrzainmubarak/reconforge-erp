import http.client
import json
import socket
import ssl
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from reconforge.connectors.network import (
    ConnectorNetworkError,
    NetworkConnectorExecutor,
    NetworkConnectorRegistration,
    NetworkResponse,
    PinnedHttpsGetTransport,
)
from reconforge.connectors.rest_reference import (
    REFERENCE_REST_MANIFEST,
    ReferenceRestConnector,
    reference_rest_registration,
)
from tests.https_runtime import create_localhost_certificate


@dataclass
class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tenant-a/reference-rest"
        return b"synthetic-reference-token-123"


@dataclass
class _Transport:
    body: bytes
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, endpoint: str, *, headers: dict[str, str], timeout_seconds: int, maximum_response_bytes: int) -> NetworkResponse:
        del timeout_seconds, maximum_response_bytes
        self.calls.append((endpoint, dict(headers)))
        return NetworkResponse(200, self.body, "next-2")


def test_reference_rest_connector_is_read_only_and_canonicalizes_records() -> None:
    transport = _Transport(
        b'{"records":[{"id":"R-2","amount":"20.00","currency":"USD","date":"2026-01-02","partition":"AR"},{"id":"R-1","amount":"10.00","currency":"USD","date":"2026-01-01","partition":"AR"}],"next_cursor":"next-2"}'
    )
    connector = ReferenceRestConnector(
        NetworkConnectorExecutor(transport, secret_resolver=_Secrets()),
        reference_rest_registration(credential_reference="vault://tenant-a/reference-rest"),
    )
    result = connector.read_page(idempotency_key="run-1", cursor="next-1")
    assert result.page.next_cursor == "next-2"
    assert [record.record_id for record in result.page.records] == ["R-2", "R-1"]
    assert result.response_digest
    assert transport.calls[0][0] == REFERENCE_REST_MANIFEST.egress_destinations[0]


def test_reference_rest_rejects_duplicate_ids_and_non_exact_amounts() -> None:
    duplicate = _Transport(
        b'{"records":[{"id":"R-1","amount":"10","currency":"USD","date":"2026-01-01","partition":"AR"},{"id":"R-1","amount":"10","currency":"USD","date":"2026-01-01","partition":"AR"}]}'
    )
    connector = ReferenceRestConnector(
        NetworkConnectorExecutor(duplicate, secret_resolver=_Secrets()),
        reference_rest_registration(credential_reference="vault://tenant-a/reference-rest"),
    )
    with pytest.raises(ConnectorNetworkError, match="schema_invalid"):
        connector.read_page(idempotency_key="duplicate-1")
    malformed = _Transport(
        b'{"records":[{"id":"R-1","amount":"NaN","currency":"USD","date":"2026-01-01","partition":"AR"}]}'
    )
    malformed_connector = ReferenceRestConnector(
        NetworkConnectorExecutor(malformed, secret_resolver=_Secrets()),
        reference_rest_registration(credential_reference="vault://tenant-a/reference-rest"),
    )
    with pytest.raises(ConnectorNetworkError, match="schema_invalid"):
        malformed_connector.read_page(idempotency_key="malformed-1")


def test_reference_registration_rejects_unallowlisted_endpoint() -> None:
    with pytest.raises(ConnectorNetworkError, match="not_allowlisted"):
        reference_rest_registration(credential_reference="vault://tenant-a/reference-rest", endpoint="https://evil.example.test/records")


def test_local_https_rest_sandbox_exercises_real_tls_retry_cursor_and_digest(tmp_path: Path) -> None:
    certificate, key = create_localhost_certificate(tmp_path)
    requests: list[dict[str, str]] = []
    response_body = (
        b'{"records":[{"id":"R-2","amount":"20.00","currency":"USD","date":"2026-01-02",'
        b'"partition":"AR"},{"id":"R-1","amount":"10.00","currency":"USD","date":"2026-01-01",'
        b'"partition":"AR"}],"next_cursor":"next-2"}'
    )

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            requests.append({key: value for key, value in self.headers.items()})
            if len(requests) == 1:
                status = 429
                body = b'{"retry":true}'
            else:
                status = 200
                body = response_body
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-ReconForge-Next-Cursor", "next-2")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.check_hostname = False
    server_context.verify_mode = ssl.CERT_NONE
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(certificate, key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    waits: list[float] = []
    pinned_addresses: list[str] = []

    class _LocalPinnedConnection(http.client.HTTPSConnection):
        def __init__(self, host: str, port: int, timeout: int, context: ssl.SSLContext) -> None:
            super().__init__(host=host, port=port, timeout=timeout, context=context)
            self._create_connection = self._connect_local

        def _connect_local(
            self,
            _address: tuple[str, int],
            timeout: float | None = None,
            source_address: tuple[str, int] | None = None,
        ) -> socket.socket:
            return socket.create_connection(("127.0.0.1", self.port), timeout, source_address)

    def factory(host: str, port: int, address: str, timeout: int, context: ssl.SSLContext) -> http.client.HTTPSConnection:
        pinned_addresses.append(address)
        return _LocalPinnedConnection(host, port, timeout, context)

    try:
        endpoint = f"https://localhost:{server.server_port}/v1/records"
        manifest = REFERENCE_REST_MANIFEST.model_copy(update={"egress_destinations": (endpoint,)})
        registration = NetworkConnectorRegistration(
            registration_schema="network-connector-registration-v1",
            manifest=manifest,
            endpoint=endpoint,
            credential_reference="vault://tenant-a/reference-rest",
        )
        transport = PinnedHttpsGetTransport(
            resolver=lambda _host, _port: ("93.184.216.34",),
            connection_factory=factory,
            tls_context=ssl.create_default_context(cafile=str(certificate)),
        )
        result = ReferenceRestConnector(
            NetworkConnectorExecutor(transport, secret_resolver=_Secrets(), sleeper=waits.append, clock=lambda: 0.0),
            registration,
        ).read_page(idempotency_key="run-1", cursor="next-1")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.attempts == 2
    assert result.page.next_cursor == "next-2"
    assert [record.record_id for record in result.page.records] == ["R-2", "R-1"]
    expected_digest = ReferenceRestConnector(
        NetworkConnectorExecutor(_Transport(response_body), secret_resolver=_Secrets()),
        reference_rest_registration(credential_reference="vault://tenant-a/reference-rest"),
    ).read_page(idempotency_key="digest-check").response_digest
    assert result.response_digest == expected_digest
    assert len(requests) == 2
    assert pinned_addresses == ["93.184.216.34"] * 2
    assert {request["Idempotency-Key"] for request in requests} == {"run-1"}
    assert {request["X-ReconForge-Cursor"] for request in requests} == {"next-1"}
    assert all(request["Authorization"] == "Bearer synthetic-reference-token-123" for request in requests)
    assert b"synthetic-reference-token-123" not in json.dumps(result.__dict__, default=str).encode()
    assert waits
