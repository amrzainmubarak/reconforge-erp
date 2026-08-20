from __future__ import annotations

import hashlib
import http.client
import http.server
import json
import socket
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from reconforge.connectors.bank_statement_camt053 import (
    BankStatementCamt053Connector,
    bank_statement_camt053_registration,
)
from reconforge.connectors.erpnext_payment_reference import (
    ErpNextPaymentEntryConnector,
    erpnext_payment_entry_registration,
)
from reconforge.connectors.erpnext_payment_writeback import (
    ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
    ErpNextPaymentEntryDraft,
    build_erpnext_payment_entry_payload,
    erpnext_payment_entry_writeback_registration,
)
from reconforge.connectors.erpnext_reference import ErpNextConnector, erpnext_registration
from reconforge.connectors.erpnext_writeback import (
    ERP_NEXT_JOURNAL_ENTRY_OPERATION,
    ErpNextJournalEntryDraft,
    ErpNextJournalEntryLine,
    build_erpnext_journal_entry_payload,
    erpnext_writeback_registration,
)
from reconforge.connectors.network import NetworkConnectorExecutor, PinnedHttpsGetTransport
from reconforge.connectors.writeback import WritebackIntent, WritebackPolicy, approve_writeback, dispatch_writeback
from reconforge.connectors.writeback_network import PinnedHttpsPostTransport, WritebackNetworkExecutor
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


@dataclass
class _WritebackSandboxState:
    requests: list[tuple[str, dict[str, str], bytes]] = field(default_factory=list)
    failures_before_success: int = 1


def _provider_acknowledgement(idempotency_key: str) -> bytes:
    fields = {
        "accepted": True,
        "idempotency_key": idempotency_key,
        "provider_reference": "ERPNext-JE-DRAFT-1",
    }
    response_digest = hashlib.sha256(
        json.dumps(fields, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return json.dumps(
        {**fields, "response_digest": response_digest},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


@contextmanager
def _https_writeback_sandbox(
    tmp_path: Path,
) -> Iterator[tuple[str, _WritebackSandboxState, PinnedHttpsPostTransport]]:
    """Run a disposable ERPNext-compatible Journal Entry POST endpoint.

    The endpoint is intentionally synthetic. The production transport still
    performs public-address resolution, TLS hostname verification, bounded
    retries, and sends the original idempotency key on every attempt.
    """

    certificate, key = create_localhost_certificate(tmp_path)
    state = _WritebackSandboxState()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            headers = {header: value for header, value in self.headers.items()}
            state.requests.append((self.path, headers, body))
            if len(state.requests) <= state.failures_before_success:
                status = 503
                response_body = b'{"retry":true}'
            else:
                status = 201
                response_body = _provider_acknowledgement(headers.get("Idempotency-Key", ""))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
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

    transport = PinnedHttpsPostTransport(
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


def test_erpnext_journal_writeback_runs_over_pinned_tls_with_retry_and_idempotency(tmp_path: Path) -> None:
    draft = ErpNextJournalEntryDraft(
        company="Acme",
        posting_date="2026-08-11",
        accounts=(
            ErpNextJournalEntryLine(account="1100 - Cash", debit="125.00", credit="0.00", account_currency="USD"),
            ErpNextJournalEntryLine(account="4000 - Revenue", debit="0.00", credit="125.00", account_currency="USD"),
        ),
        user_remark="Synthetic provider-compatible draft",
    )
    payload = build_erpnext_journal_entry_payload(draft)
    connector_id = "erpnext-journal-entry-writeback"
    operation = ERP_NEXT_JOURNAL_ENTRY_OPERATION
    policy = WritebackPolicy(
        connector_id=connector_id,
        allowed_operations=frozenset({operation}),
        feature_enabled=True,
    )
    intent = WritebackIntent(
        schema_version="connector-writeback-intent-v1",
        intent_id="erpnext-tls-writeback-1",
        tenant_id="tenant-tls",
        workspace_id="workspace-tls",
        connector_id=connector_id,
        operation=operation,
        payload_digest=payload.payload_digest,
        idempotency_key="erpnext-tls-writeback-1",
        requested_by="maker-tls",
        requested_at=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        feature_enabled=True,
    )
    approved = approve_writeback(
        intent,
        policy=policy,
        actor_id="checker-tls",
        approved_at=datetime(2026, 8, 11, 10, 1, tzinfo=UTC),
        assurance="mfa",
        reason="Synthetic independent review",
    )
    dispatched = dispatch_writeback(approved, policy=policy)

    class Payloads:
        def resolve(self, _intent: object) -> bytes:
            return payload.payload

    with _https_writeback_sandbox(tmp_path) as (base, state, transport):
        endpoint = f"{base}/api/resource/Journal%20Entry"
        registration = erpnext_writeback_registration(
            credential_reference="vault://tls/synthetic",
            endpoint=endpoint,
        ).model_copy(update={"feature_enabled": True})
        receipt = WritebackNetworkExecutor(
            transport,
            payload_resolver=Payloads(),
            secret_resolver=_Secrets(),
            sleeper=lambda _delay: None,
        ).dispatch(dispatched, registration=registration, policy=policy)

    assert receipt.attempts == 2
    assert receipt.intent.acknowledgement is not None
    assert receipt.intent.acknowledgement.provider_reference == "ERPNext-JE-DRAFT-1"
    assert [request[0] for request in state.requests] == [
        "/api/resource/Journal%20Entry",
        "/api/resource/Journal%20Entry",
    ]
    assert {request[1]["Idempotency-Key"] for request in state.requests} == {dispatched.idempotency_key}
    assert all(request[1]["Authorization"] == "token tls-sandbox-secret" for request in state.requests)
    assert all(request[1]["X-ReconForge-Operation"] == operation for request in state.requests)
    assert all(request[2] == payload.payload for request in state.requests)
    assert b"tls-sandbox-secret" not in receipt.intent.model_dump_json().encode("utf-8")


def test_erpnext_payment_writeback_runs_over_pinned_tls_with_exact_draft_payload(tmp_path: Path) -> None:
    draft = ErpNextPaymentEntryDraft(
        company="Acme",
        posting_date="2026-08-11",
        paid_from="1100 - Cash",
        paid_to="2100 - Supplier Payables",
        paid_amount="125.00",
        received_amount="0.00",
        paid_from_account_currency="USD",
        paid_to_account_currency="USD",
        party_type="Supplier",
        party="SUP-001",
        reference_no="PAY-2026-001",
        remarks="Synthetic payment draft",
    )
    payload = build_erpnext_payment_entry_payload(draft)
    connector_id = "erpnext-payment-entry-writeback"
    policy = WritebackPolicy(
        connector_id=connector_id,
        allowed_operations=frozenset({ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION}),
        feature_enabled=True,
    )
    intent = WritebackIntent(
        schema_version="connector-writeback-intent-v1",
        intent_id="erpnext-payment-tls-writeback-1",
        tenant_id="tenant-tls",
        workspace_id="workspace-tls",
        connector_id=connector_id,
        operation=ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION,
        payload_digest=payload.payload_digest,
        idempotency_key="erpnext-payment-tls-writeback-1",
        requested_by="maker-tls",
        requested_at=datetime(2026, 8, 11, 10, 0, tzinfo=UTC),
        feature_enabled=True,
    )
    approved = approve_writeback(
        intent,
        policy=policy,
        actor_id="checker-tls",
        approved_at=datetime(2026, 8, 11, 10, 1, tzinfo=UTC),
        assurance="mfa",
        reason="Synthetic independent payment review",
    )
    dispatched = dispatch_writeback(approved, policy=policy)

    class Payloads:
        def resolve(self, _intent: object) -> bytes:
            return payload.payload

    with _https_writeback_sandbox(tmp_path) as (base, state, transport):
        endpoint = f"{base}/api/resource/Payment%20Entry"
        registration = erpnext_payment_entry_writeback_registration(
            credential_reference="vault://tls/synthetic",
            endpoint=endpoint,
        ).model_copy(update={"feature_enabled": True})
        receipt = WritebackNetworkExecutor(
            transport,
            payload_resolver=Payloads(),
            secret_resolver=_Secrets(),
            sleeper=lambda _delay: None,
        ).dispatch(dispatched, registration=registration, policy=policy)

    assert receipt.attempts == 2
    assert receipt.intent.acknowledgement is not None
    assert receipt.intent.acknowledgement.provider_reference == "ERPNext-JE-DRAFT-1"
    assert [request[0] for request in state.requests] == [
        "/api/resource/Payment%20Entry",
        "/api/resource/Payment%20Entry",
    ]
    assert {request[1]["Idempotency-Key"] for request in state.requests} == {dispatched.idempotency_key}
    assert all(request[1]["Authorization"] == "token tls-sandbox-secret" for request in state.requests)
    assert all(request[1]["X-ReconForge-Operation"] == ERP_NEXT_PAYMENT_ENTRY_WRITEBACK_OPERATION for request in state.requests)
    assert all(request[2] == payload.payload for request in state.requests)
    assert b"tls-sandbox-secret" not in receipt.intent.model_dump_json().encode("utf-8")
