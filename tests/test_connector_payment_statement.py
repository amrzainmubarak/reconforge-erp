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
from reconforge.connectors.payment_statement_reference import (
    PAYMENT_STATEMENT_MANIFEST,
    ReferencePaymentStatementConnector,
    payment_statement_registration,
)
from tests.https_runtime import create_localhost_certificate


@dataclass
class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tenant-a/payment-statement"
        return b"synthetic-payment-token"


@dataclass
class _Transport:
    body: bytes
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, endpoint: str, *, headers: dict[str, str], timeout_seconds: int, maximum_response_bytes: int) -> NetworkResponse:
        del timeout_seconds, maximum_response_bytes
        self.calls.append((endpoint, dict(headers)))
        return NetworkResponse(200, self.body, "cursor-2")


def test_payment_statement_connector_is_read_only_and_canonical() -> None:
    transport = _Transport(
        b'{"records":[{"id":"L-2","account_id":"BANK-1","bookingDate":"2026-01-02","valueDate":"2026-01-02","amount":"-20.00","currency":"USD","reference":"fee"},{"id":"L-1","account_id":"BANK-1","bookingDate":"2026-01-01","valueDate":"2026-01-02","amount":"100.00","currency":"USD","reference":"sale"}],"next_cursor":"cursor-2"}'
    )
    connector = ReferencePaymentStatementConnector(
        NetworkConnectorExecutor(transport, secret_resolver=_Secrets()),
        payment_statement_registration(credential_reference="vault://tenant-a/payment-statement"),
    )
    result = connector.read_page(idempotency_key="statement-1", cursor="cursor-1")
    assert result.page.next_cursor == "cursor-2"
    assert [line.line_id for line in result.page.records] == ["L-2", "L-1"]
    assert result.response_digest
    assert transport.calls[0][0] == PAYMENT_STATEMENT_MANIFEST.egress_destinations[0]
    assert PAYMENT_STATEMENT_MANIFEST.capabilities == frozenset({"read"})
    scoped = connector.read_page(idempotency_key="statement-2", expected_account_id="BANK-1")
    assert scoped.response_digest == result.response_digest


def test_payment_statement_rejects_account_scope_mismatch() -> None:
    body = b'{"records":[{"id":"L-1","account_id":"BANK-1","bookingDate":"2026-01-01","valueDate":"2026-01-01","amount":"1.00","currency":"USD"}]}'
    connector = ReferencePaymentStatementConnector(
        NetworkConnectorExecutor(_Transport(body), secret_resolver=_Secrets()),
        payment_statement_registration(credential_reference="vault://tenant-a/payment-statement"),
    )
    with pytest.raises(ConnectorNetworkError, match="account_scope_mismatch"):
        connector.read_page(idempotency_key="statement-scope", expected_account_id="BANK-2")


@pytest.mark.parametrize(
    "body",
    [
        b'{"records":[{"id":"L-1","account_id":"BANK-1","bookingDate":"2026-01-02","valueDate":"2026-01-01","amount":"1.00","currency":"USD"}]}',
        b'{"records":[{"id":"L-1","account_id":"BANK-1","bookingDate":"2026-01-01","valueDate":"2026-01-01","amount":"NaN","currency":"USD"}]}',
        b'{"records":[{"id":"L-1","account_id":"BANK-1","bookingDate":"2026-01-01","valueDate":"2026-01-01","amount":"1.00","currency":"USD"},{"id":"L-1","account_id":"BANK-1","bookingDate":"2026-01-01","valueDate":"2026-01-01","amount":"2.00","currency":"USD"}]}',
    ],
)
def test_payment_statement_rejects_invalid_lines(body: bytes) -> None:
    connector = ReferencePaymentStatementConnector(
        NetworkConnectorExecutor(_Transport(body), secret_resolver=_Secrets()),
        payment_statement_registration(credential_reference="vault://tenant-a/payment-statement"),
    )
    with pytest.raises(ConnectorNetworkError, match="schema_invalid"):
        connector.read_page(idempotency_key="invalid-1")


def test_payment_statement_registration_rejects_unallowlisted_endpoint() -> None:
    with pytest.raises(ConnectorNetworkError, match="not_allowlisted"):
        payment_statement_registration(
            credential_reference="vault://tenant-a/payment-statement", endpoint="https://evil.example.test/statement"
        )


def test_local_https_payment_statement_sandbox_exercises_real_tls_retry_cursor_and_digest(tmp_path: Path) -> None:
    certificate, key = create_localhost_certificate(tmp_path)
    requests: list[dict[str, str]] = []
    response_body = (
        b'{"records":[{"id":"L-2","account_id":"BANK-1","bookingDate":"2026-01-02",'
        b'"valueDate":"2026-01-02","amount":"-20.00","currency":"USD","reference":"fee"},'
        b'{"id":"L-1","account_id":"BANK-1","bookingDate":"2026-01-01",'
        b'"valueDate":"2026-01-02","amount":"100.00","currency":"USD",'
        b'"reference":"sale"}],"next_cursor":"statement-next"}'
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
            self.send_header("X-ReconForge-Next-Cursor", "statement-next")
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
        endpoint = f"https://localhost:{server.server_port}/v1/payment-statements"
        manifest = PAYMENT_STATEMENT_MANIFEST.model_copy(update={"egress_destinations": (endpoint,)})
        registration = NetworkConnectorRegistration(
            registration_schema="network-connector-registration-v1",
            manifest=manifest,
            endpoint=endpoint,
            credential_reference="vault://tenant-a/payment-statement",
        )
        transport = PinnedHttpsGetTransport(
            resolver=lambda _host, _port: ("93.184.216.34",),
            connection_factory=factory,
            tls_context=ssl.create_default_context(cafile=str(certificate)),
        )
        result = ReferencePaymentStatementConnector(
            NetworkConnectorExecutor(transport, secret_resolver=_Secrets(), sleeper=waits.append, clock=lambda: 0.0),
            registration,
        ).read_page(idempotency_key="statement-sandbox-1", cursor="statement-start", expected_account_id="BANK-1")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.attempts == 2
    assert result.page.next_cursor == "statement-next"
    assert [line.line_id for line in result.page.records] == ["L-2", "L-1"]
    assert result.response_digest
    assert len(requests) == 2
    assert pinned_addresses == ["93.184.216.34"] * 2
    assert {request["Idempotency-Key"] for request in requests} == {"statement-sandbox-1"}
    assert {request["X-ReconForge-Cursor"] for request in requests} == {"statement-start"}
    assert all(request["Authorization"] == "Bearer synthetic-payment-token" for request in requests)
    assert b"synthetic-payment-token" not in json.dumps(result.__dict__, default=str).encode()
    assert waits
