import http.client
import json
import socket
import ssl
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from reconforge.connectors.erp_reference import (
    ERP_REFERENCE_MANIFEST,
    ReferenceErpConnector,
    erp_reference_registration,
)
from reconforge.connectors.network import (
    ConnectorNetworkError,
    NetworkConnectorExecutor,
    NetworkConnectorRegistration,
    NetworkResponse,
    PinnedHttpsGetTransport,
)
from tests.https_runtime import create_localhost_certificate


@dataclass
class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tenant-a/reference-erp"
        return b"synthetic-erp-token-123"


@dataclass
class _Transport:
    body: bytes
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, endpoint: str, *, headers: dict[str, str], timeout_seconds: int, maximum_response_bytes: int) -> NetworkResponse:
        del timeout_seconds, maximum_response_bytes
        self.calls.append((endpoint, dict(headers)))
        return NetworkResponse(200, self.body, "erp-next")


def test_reference_erp_connector_is_read_only_entity_scoped_and_canonical() -> None:
    transport = _Transport(
        b'{"lines":[{"id":"L-2","entity_code":"EGY","account_code":"4000","amount":"20.00","currency":"USD","date":"2026-01-02","document":"INV-2"},{"id":"L-1","entity_code":"EGY","account_code":"4000","amount":"10.00","currency":"USD","date":"2026-01-01","document":"INV-1"}],"next_cursor":"erp-next"}'
    )
    connector = ReferenceErpConnector(
        NetworkConnectorExecutor(transport, secret_resolver=_Secrets()),
        erp_reference_registration(credential_reference="vault://tenant-a/reference-erp"),
    )
    result = connector.read_page(idempotency_key="erp-run-1", cursor="erp-start")
    assert result.page.next_cursor == "erp-next"
    assert [line.line_id for line in result.page.lines] == ["L-2", "L-1"]
    assert result.response_digest
    assert transport.calls[0][0] == ERP_REFERENCE_MANIFEST.egress_destinations[0]
    scoped = connector.read_page(idempotency_key="erp-run-2", expected_entity_code="EGY")
    assert scoped.response_digest == result.response_digest


def test_reference_erp_rejects_expected_entity_scope_mismatch() -> None:
    body = b'{"lines":[{"id":"L-1","entity_code":"EGY","account_code":"4000","amount":"10","currency":"USD","date":"2026-01-01"}]}'
    connector = ReferenceErpConnector(
        NetworkConnectorExecutor(_Transport(body), secret_resolver=_Secrets()),
        erp_reference_registration(credential_reference="vault://tenant-a/reference-erp"),
    )
    with pytest.raises(ConnectorNetworkError, match="entity_scope_mismatch"):
        connector.read_page(idempotency_key="erp-scope-mismatch", expected_entity_code="USA")


@pytest.mark.parametrize(
    "body",
    [
        b'{"lines":[{"id":"L-1","entity_code":"EGY","account_code":"4000","amount":"NaN","currency":"USD","date":"2026-01-01"}]}',
        b'{"lines":[{"id":"L-1","entity_code":"EGY","account_code":"4000","amount":"10","currency":"USD","date":"2026-01-01"},{"id":"L-2","entity_code":"USA","account_code":"4000","amount":"10","currency":"USD","date":"2026-01-01"}]}',
    ],
)
def test_reference_erp_rejects_invalid_amount_or_mixed_entities(body: bytes) -> None:
    connector = ReferenceErpConnector(
        NetworkConnectorExecutor(_Transport(body), secret_resolver=_Secrets()),
        erp_reference_registration(credential_reference="vault://tenant-a/reference-erp"),
    )
    with pytest.raises(ConnectorNetworkError, match="schema_invalid"):
        connector.read_page(idempotency_key="erp-invalid")


def test_reference_erp_registration_rejects_unallowlisted_endpoint() -> None:
    with pytest.raises(ConnectorNetworkError, match="not_allowlisted"):
        erp_reference_registration(
            credential_reference="vault://tenant-a/reference-erp",
            endpoint="https://evil.example.test/ledger-lines",
        )


def test_local_https_erp_sandbox_exercises_real_tls_retry_cursor_and_digest(tmp_path: Path) -> None:
    certificate, key = create_localhost_certificate(tmp_path)
    requests: list[dict[str, str]] = []
    response_body = (
        b'{"lines":[{"id":"L-2","entity_code":"EGY","account_code":"4000",'
        b'"amount":"20.00","currency":"USD","date":"2026-01-02","document":"INV-2"},'
        b'{"id":"L-1","entity_code":"EGY","account_code":"4000","amount":"10.00",'
        b'"currency":"USD","date":"2026-01-01","document":"INV-1"}],"next_cursor":"erp-next"}'
    )

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            requests.append({key: value for key, value in self.headers.items()})
            if len(requests) == 1:
                status = 503
                body = b'{"retry":true}'
            else:
                status = 200
                body = response_body
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-ReconForge-Next-Cursor", "erp-next")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
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
        del host
        pinned_addresses.append(address)
        return _LocalPinnedConnection("localhost", port, timeout, context)

    try:
        endpoint = f"https://localhost:{server.server_port}/v1/ledger-lines"
        manifest = ERP_REFERENCE_MANIFEST.model_copy(update={"egress_destinations": (endpoint,)})
        registration = NetworkConnectorRegistration(
            registration_schema="network-connector-registration-v1",
            manifest=manifest,
            endpoint=endpoint,
            credential_reference="vault://tenant-a/reference-erp",
        )
        transport = PinnedHttpsGetTransport(
            resolver=lambda _host, _port: ("93.184.216.34",),
            connection_factory=factory,
            tls_context=ssl.create_default_context(cafile=str(certificate)),
        )
        result = ReferenceErpConnector(
            NetworkConnectorExecutor(transport, secret_resolver=_Secrets(), sleeper=waits.append, clock=lambda: 0.0),
            registration,
        ).read_page(idempotency_key="erp-sandbox-1", cursor="erp-start", expected_entity_code="EGY")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.attempts == 2
    assert result.page.next_cursor == "erp-next"
    assert [line.line_id for line in result.page.lines] == ["L-2", "L-1"]
    assert result.response_digest
    assert len(requests) == 2
    assert pinned_addresses == ["93.184.216.34"] * 2
    assert {request["Idempotency-Key"] for request in requests} == {"erp-sandbox-1"}
    assert {request["X-ReconForge-Cursor"] for request in requests} == {"erp-start"}
    assert all(request["Authorization"] == "Bearer synthetic-erp-token-123" for request in requests)
    assert b"synthetic-erp-token-123" not in json.dumps(result.__dict__, default=str).encode()
    assert waits
