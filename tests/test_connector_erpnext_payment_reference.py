from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from reconforge.connectors.erpnext_payment_reference import (
    ERP_NEXT_PAYMENT_ENTRY_ENDPOINT,
    ErpNextPaymentEntryConnector,
    erpnext_payment_entry_registration,
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


def _connector(body: bytes) -> tuple[ErpNextPaymentEntryConnector, _Transport]:
    transport = _Transport(body)
    registration = erpnext_payment_entry_registration(credential_reference="vault://tenant-a/erpnext")
    return ErpNextPaymentEntryConnector(NetworkConnectorExecutor(transport, secret_resolver=_Secrets()), registration), transport


def test_erpnext_payment_entry_read_uses_token_cursor_company_filter_and_exact_amounts() -> None:
    body = (
        b'{"data":['
        b'{"name":"PAY-2","company":"Acme","posting_date":"2026-01-02",'
        b'"paid_amount":"0.00","received_amount":"20.00",'
        b'"paid_from_account_currency":"USD","paid_to_account_currency":"USD",'
        b'"status":"Submitted","party_type":"Customer","party":"CUST-2",'
        b'"reference_no":"RCPT-2"},'
        b'{"name":"PAY-1","company":"Acme","posting_date":"2026-01-01",'
        b'"paid_amount":"10.00","received_amount":"0.00",'
        b'"paid_from_account_currency":"USD","paid_to_account_currency":"USD",'
        b'"status":"Submitted"}]}'
    )
    connector, transport = _connector(body)

    result = connector.read_payment_entries(
        idempotency_key="erpnext-payment-1", cursor="25", expected_company="Acme", page_length=500
    )

    assert [entry.entry_id for entry in result.page.entries] == ["PAY-2", "PAY-1"]
    assert result.page.next_cursor == "50"
    assert result.page.entries[0].received_amount == "20.00"
    assert transport.calls[0][0] == (
        ERP_NEXT_PAYMENT_ENTRY_ENDPOINT
        + '?filters=%5B%5B%22company%22%2C%22%3D%22%2C%22Acme%22%5D%5D&limit_page_length=500&limit_start=25'
    )
    assert transport.calls[0][1]["Authorization"] == "token api-key:api-secret"
    assert b"api-key:api-secret" not in repr(result).encode("utf-8")
    assert result.response_digest


@pytest.mark.parametrize(
    "body",
    [
        b'{"data":[{"name":"PAY-1","company":"Acme","posting_date":"2026-01-01","paid_amount":"0","received_amount":"0","paid_from_account_currency":"USD","paid_to_account_currency":"USD","status":"Submitted"}]}',
        b'{"data":[{"name":"PAY-1","company":"Acme","posting_date":"2026-01-01","paid_amount":"NaN","received_amount":"0","paid_from_account_currency":"USD","paid_to_account_currency":"USD","status":"Submitted"}]}',
        b'{"data":[{"name":"PAY-1","company":"Acme","posting_date":"2026-01-01","paid_amount":"1","received_amount":"0","paid_from_account_currency":"USD","paid_to_account_currency":"USD","status":"Submitted"},{"name":"PAY-1","company":"Acme","posting_date":"2026-01-01","paid_amount":"1","received_amount":"0","paid_from_account_currency":"USD","paid_to_account_currency":"USD","status":"Submitted"}]}',
        b'{"data":[{"name":"PAY-1","company":"Acme","posting_date":"2026-01-01","paid_amount":"1","received_amount":"0","paid_from_account_currency":"USD","paid_to_account_currency":"USD","status":"Submitted"},{"name":"PAY-2","company":"Other","posting_date":"2026-01-01","paid_amount":"1","received_amount":"0","paid_from_account_currency":"USD","paid_to_account_currency":"USD","status":"Submitted"}]}',
    ],
)
def test_erpnext_payment_entry_rejects_zero_nonfinite_duplicate_or_mixed_company_pages(body: bytes) -> None:
    connector, _transport = _connector(body)
    with pytest.raises(ConnectorNetworkError, match="response_schema_invalid|company_scope_mismatch"):
        connector.read_payment_entries(idempotency_key="erpnext-payment-invalid")


@pytest.mark.parametrize("page_length", [0, 10_001, True])
def test_erpnext_payment_entry_rejects_invalid_page_length_before_transport(page_length: object) -> None:
    connector, transport = _connector(b'{"data":[]}')
    with pytest.raises(ConnectorNetworkError, match="page_length_invalid"):
        connector.read_payment_entries(idempotency_key="erpnext-payment-page-length", page_length=page_length)  # type: ignore[arg-type]
    assert transport.calls == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://erpnext.example.test/api/resource/Payment%20Entry",
        "https://erpnext.example.test/api/resource/GL%20Entry",
        "https://erpnext.example.test/api/resource/Payment%20Entry?limit=10",
        "https://user:pass@erpnext.example.test/api/resource/Payment%20Entry",
    ],
)
def test_erpnext_payment_entry_registration_rejects_endpoint_widening(endpoint: str) -> None:
    with pytest.raises(ConnectorNetworkError, match="endpoint_invalid"):
        erpnext_payment_entry_registration(credential_reference="vault://tenant-a/erpnext", endpoint=endpoint)


def test_erpnext_payment_entry_connector_contract_is_packaged_and_documented() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/connectors/erpnext_payment_reference.py" in manifest
    assert "include tests/test_connector_erpnext_payment_reference.py" in manifest
    assert "include docs/connectors/erpnext-payment-entry-readonly.md" in manifest
    assert "include docs/adr/0436-erpnext-payment-entry-readonly.md" in manifest
    assert (root / "docs/connectors/erpnext-payment-entry-readonly.md").is_file()
    assert (root / "docs/adr/0436-erpnext-payment-entry-readonly.md").is_file()
