from dataclasses import dataclass, field

import pytest

from reconforge.connectors.network import ConnectorNetworkError, NetworkConnectorExecutor, NetworkResponse
from reconforge.connectors.payment_statement_reference import (
    PAYMENT_STATEMENT_MANIFEST,
    ReferencePaymentStatementConnector,
    payment_statement_registration,
)


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
