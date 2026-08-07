from __future__ import annotations

import http.client
import http.server
import socket
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from reconforge.connectors.bank_statement_camt053 import (
    BankStatementCamt053Connector,
    bank_statement_camt053_registration,
)
from reconforge.connectors.erpnext_payment_reference import (
    ErpNextPaymentEntryConnector,
    erpnext_payment_entry_registration,
)
from reconforge.connectors.erpnext_reference import ErpNextConnector, erpnext_registration
from reconforge.connectors.network import NetworkConnectorExecutor, PinnedHttpsGetTransport
from tests.https_runtime import create_localhost_certificate


@dataclass
class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tls/synthetic"
        return b"tls-sandbox-secret"


@dataclass
class _SandboxState:
    body: bytes
    next_cursor: str | None = None
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)


@contextmanager
def _https_sandbox(
    tmp_path: Path, *, body: bytes, next_cursor: str | None = None
) -> Iterator[tuple[str, _SandboxState, PinnedHttpsGetTransport]]:
    certificate, key = create_localhost_certificate(tmp_path)
    state = _SandboxState(body=body, next_cursor=next_cursor)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            state.requests.append((self.path, {key: value for key, value in self.headers.items()}))
            if len(state.requests) == 1:
                status = 503
                response_body = b'{"retry":true}'
            else:
                status = 200
                response_body = state.body
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            if state.next_cursor is not None:
                self.send_header("X-ReconForge-Next-Cursor", state.next_cursor)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

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
        del host, address
        return _LocalPinnedConnection("localhost", port, timeout, context)

    transport = PinnedHttpsGetTransport(
        resolver=lambda _host, _port: ("93.184.216.34",),
        connection_factory=factory,
        tls_context=ssl.create_default_context(cafile=str(certificate)),
    )
    try:
        yield f"https://localhost:{server.server_port}", state, transport
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_camt053_provider_boundary_runs_over_pinned_tls_with_retry(tmp_path: Path) -> None:
    body = (Path(__file__).parent / "golden" / "camt053" / "statement.xml").read_bytes()
    with _https_sandbox(tmp_path, body=body) as (base, state, transport):
        registration = bank_statement_camt053_registration(
            credential_reference="vault://tls/synthetic",
            endpoint=f"{base}/api/v1/statements/camt053",
        )
        connector = BankStatementCamt053Connector(
            NetworkConnectorExecutor(transport, secret_resolver=_Secrets(), sleeper=lambda _delay: None),
            registration,
        )
        result = connector.read_statement(
            idempotency_key="tls-camt-1",
            expected_account_id="DE89370400440532013000",
        )

    assert result.attempts == 2
    assert result.statement.statement_id == "STMT-CAMT-001"
    assert state.requests[0][0] == "/api/v1/statements/camt053"
    assert state.requests[1][1]["Authorization"] == "Bearer tls-sandbox-secret"


def test_erpnext_gl_provider_boundary_runs_over_pinned_tls_with_cursor_and_scope(tmp_path: Path) -> None:
    body = (
        b'{"data":[{"name":"GL-1","company":"Acme","account":"4000",'
        b'"debit":"10.00","credit":"0.00","account_currency":"USD",'
        b'"posting_date":"2026-01-01","voucher_no":"INV-1"}]}'
    )
    with _https_sandbox(tmp_path, body=body, next_cursor="50") as (base, state, transport):
        registration = erpnext_registration(
            credential_reference="vault://tls/synthetic",
            endpoint=f"{base}/api/resource/GL%20Entry",
        )
        connector = ErpNextConnector(
            NetworkConnectorExecutor(transport, secret_resolver=_Secrets(), sleeper=lambda _delay: None),
            registration,
        )
        result = connector.read_gl_entries(
            idempotency_key="tls-gl-1", cursor="7", expected_company="Acme", page_length=2
        )

    assert result.attempts == 2
    assert result.page.entries[0].signed_amount == 10
    assert result.page.next_cursor == "50"
    assert "filters=%5B%5B%22company%22%2C%22%3D%22%2C%22Acme%22%5D%5D" in state.requests[1][0]
    assert "limit_page_length=2" in state.requests[1][0]
    assert "limit_start=7" in state.requests[1][0]
    assert state.requests[1][1]["Authorization"] == "token tls-sandbox-secret"


def test_erpnext_payment_entry_provider_boundary_runs_over_pinned_tls(tmp_path: Path) -> None:
    body = (
        b'{"data":[{"name":"PAY-1","company":"Acme","posting_date":"2026-01-01",'
        b'"paid_amount":"10.00","received_amount":"0.00",'
        b'"paid_from_account_currency":"USD","paid_to_account_currency":"USD",'
        b'"status":"Submitted"}]}'
    )
    with _https_sandbox(tmp_path, body=body, next_cursor="50") as (base, state, transport):
        registration = erpnext_payment_entry_registration(
            credential_reference="vault://tls/synthetic",
            endpoint=f"{base}/api/resource/Payment%20Entry",
        )
        connector = ErpNextPaymentEntryConnector(
            NetworkConnectorExecutor(transport, secret_resolver=_Secrets(), sleeper=lambda _delay: None),
            registration,
        )
        result = connector.read_payment_entries(
            idempotency_key="tls-payment-1", cursor="7", expected_company="Acme", page_length=2
        )

    assert result.attempts == 2
    assert result.page.entries[0].paid_amount == "10.00"
    assert result.page.next_cursor == "50"
    assert "filters=%5B%5B%22company%22%2C%22%3D%22%2C%22Acme%22%5D%5D" in state.requests[1][0]
    assert state.requests[1][1]["Authorization"] == "token tls-sandbox-secret"
