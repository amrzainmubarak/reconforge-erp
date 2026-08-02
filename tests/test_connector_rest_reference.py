from dataclasses import dataclass, field

import pytest

from reconforge.connectors.network import ConnectorNetworkError, NetworkConnectorExecutor, NetworkResponse
from reconforge.connectors.rest_reference import (
    REFERENCE_REST_MANIFEST,
    ReferenceRestConnector,
    reference_rest_registration,
)


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
