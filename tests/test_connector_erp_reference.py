from dataclasses import dataclass, field

import pytest

from reconforge.connectors.erp_reference import (
    ERP_REFERENCE_MANIFEST,
    ReferenceErpConnector,
    erp_reference_registration,
)
from reconforge.connectors.network import ConnectorNetworkError, NetworkConnectorExecutor, NetworkResponse


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
