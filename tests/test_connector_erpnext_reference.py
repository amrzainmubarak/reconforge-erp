from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from reconforge.connectors.erpnext_reference import (
    ERP_NEXT_ENDPOINT,
    ErpNextConnector,
    erpnext_registration,
)
from reconforge.connectors.network import ConnectorNetworkError, NetworkConnectorExecutor, NetworkResponse


@dataclass
class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tenant-a/erpnext"
        return b"api-key:api-secret"


@dataclass
class _Transport:
    body: bytes
    next_cursor: str | None = "50"
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> NetworkResponse:
        del timeout_seconds, maximum_response_bytes
        self.calls.append((endpoint, dict(headers)))
        return NetworkResponse(200, self.body, self.next_cursor)


def _connector(body: bytes, *, next_cursor: str | None = "50") -> tuple[ErpNextConnector, _Transport]:
    transport = _Transport(body, next_cursor=next_cursor)
    registration = erpnext_registration(credential_reference="vault://tenant-a/erpnext")
    return ErpNextConnector(NetworkConnectorExecutor(transport, secret_resolver=_Secrets()), registration), transport


def test_erpnext_gl_entry_read_uses_token_auth_cursor_query_and_company_guard() -> None:
    body = (
        b'{"data":['
        b'{"name":"GL-2","company":"Acme","account":"4000 - Revenue",'
        b'"debit":"0.00","credit":"20.00","account_currency":"USD",'
        b'"posting_date":"2026-01-02","voucher_no":"INV-2"},'
        b'{"name":"GL-1","company":"Acme","account":"4000 - Revenue",'
        b'"debit":"10.00","credit":"0.00","account_currency":"USD",'
        b'"posting_date":"2026-01-01","voucher_no":"INV-1"}]}'
    )
    connector, transport = _connector(body)

    result = connector.read_gl_entries(idempotency_key="erpnext-run-1", cursor="25", expected_company="Acme")

    assert [entry.entry_id for entry in result.page.entries] == ["GL-2", "GL-1"]
    assert result.page.next_cursor == "50"
    assert result.page.entries[0].signed_amount == -20
    assert transport.calls[0][0] == ERP_NEXT_ENDPOINT + "?limit_start=25"
    assert transport.calls[0][1]["Authorization"] == "token api-key:api-secret"
    assert transport.calls[0][1]["X-ReconForge-Cursor"] == "25"
    assert result.response_digest
    assert b"api-key:api-secret" not in repr(result).encode("utf-8")


@pytest.mark.parametrize(
    "body",
    [
        b'{"data":[{"name":"GL-1","company":"Acme","account":"4000","debit":"1","credit":"2","account_currency":"USD","posting_date":"2026-01-01"}]}',
        b'{"data":[{"name":"GL-1","company":"Acme","account":"4000","debit":"NaN","credit":"0","account_currency":"USD","posting_date":"2026-01-01"}]}',
        b'{"data":[{"name":"GL-1","company":"Acme","account":"4000","debit":"1","credit":"0","account_currency":"USD","posting_date":"2026-01-01"},{"name":"GL-2","company":"Other","account":"4000","debit":"1","credit":"0","account_currency":"USD","posting_date":"2026-01-01"}]}',
    ],
)
def test_erpnext_gl_entry_rejects_ambiguous_or_invalid_source(body: bytes) -> None:
    connector, _transport = _connector(body)

    with pytest.raises(ConnectorNetworkError, match="response_schema_invalid"):
        connector.read_gl_entries(idempotency_key="erpnext-invalid")


def test_erpnext_gl_entry_rejects_invalid_cursor_before_transport() -> None:
    connector, transport = _connector(b'{"data":[]}')

    with pytest.raises(ConnectorNetworkError, match="cursor_invalid"):
        connector.read_gl_entries(idempotency_key="erpnext-cursor", cursor="page-two")

    assert transport.calls == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://erpnext.example.test/api/resource/GL%20Entry",
        "https://erpnext.example.test/api/resource/Journal%20Entry",
        "https://erpnext.example.test/api/resource/GL%20Entry?limit=10",
        "https://user:pass@erpnext.example.test/api/resource/GL%20Entry",
    ],
)
def test_erpnext_registration_rejects_endpoint_widening(endpoint: str) -> None:
    with pytest.raises(ConnectorNetworkError, match="endpoint_invalid"):
        erpnext_registration(credential_reference="vault://tenant-a/erpnext", endpoint=endpoint)


def test_erpnext_connector_contract_is_packaged_and_documented() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/connectors/erpnext_reference.py" in manifest
    assert "include tests/test_connector_erpnext_reference.py" in manifest
    assert "include docs/connectors/erpnext-gl-entry-readonly.md" in manifest
    assert "include docs/adr/0432-erpnext-read-only-connector-contract.md" in manifest
    assert (root / "docs/connectors/erpnext-gl-entry-readonly.md").is_file()
    assert (root / "docs/adr/0432-erpnext-read-only-connector-contract.md").is_file()
