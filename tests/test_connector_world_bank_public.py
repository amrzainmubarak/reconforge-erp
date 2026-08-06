from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import pytest

from reconforge.connectors.network import (
    ConnectorNetworkError,
    NetworkConnectorExecutor,
    NetworkResponse,
    PinnedHttpsGetTransport,
)
from reconforge.connectors.world_bank_public import (
    WORLD_BANK_PUBLIC_MANIFEST,
    WORLD_BANK_PUBLIC_PAGE_SIZE,
    WorldBankPublicConnector,
    world_bank_public_endpoint,
    world_bank_public_registration,
)


@dataclass
class _Transport:
    responses: list[NetworkResponse]
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
        return self.responses.pop(0)


def _payload(*, reverse: bool = False) -> dict[str, Any]:
    rows = [
        {
            "category": "Country",
            "country": "Egypt",
            "development_policy": 10.25,
            "investment_lending": 2,
            "organization": "IBRD",
            "private_sector_window": 0,
            "program_for_results": 1.5,
            "region": "Middle East",
            "time_period": "2024",
            "total": 13.75,
        },
        {
            "category": "Country",
            "country": "Albania",
            "development_policy": 1,
            "investment_lending": 4.5,
            "organization": "IBRD",
            "private_sector_window": 0.25,
            "program_for_results": 0,
            "region": "Europe",
            "time_period": "2024",
            "total": 5.75,
        },
    ]
    if reverse:
        rows.reverse()
    return {"count": 2_890, "data": rows}


def test_world_bank_endpoint_is_exactly_allowlisted_and_public_no_auth() -> None:
    endpoint = world_bank_public_endpoint(0)
    registration = world_bank_public_registration(skip=0)
    assert endpoint == registration.endpoint
    assert "datasetId=DS01556" in endpoint
    assert "resourceId=RS00963" in endpoint
    assert "top=1000" in endpoint and "skip=0" in endpoint and "type=json" in endpoint
    assert registration.credential_reference is None
    assert WORLD_BANK_PUBLIC_MANIFEST.authentication.value == "none"
    assert len(WORLD_BANK_PUBLIC_MANIFEST.digest) == 64
    with pytest.raises(ValueError, match="declared page offsets"):
        world_bank_public_endpoint(3)


def test_world_bank_connector_is_closed_decimal_and_permutation_deterministic() -> None:
    first = _Transport([NetworkResponse(200, json.dumps(_payload()).encode("utf-8"))])
    replay = WorldBankPublicConnector(NetworkConnectorExecutor(first), world_bank_public_registration(skip=0)).read_page(
        idempotency_key="world-bank-test-1"
    )
    second = _Transport([NetworkResponse(200, json.dumps(_payload(reverse=True)).encode("utf-8"))])
    permuted = WorldBankPublicConnector(
        NetworkConnectorExecutor(second), world_bank_public_registration(skip=0)
    ).read_page(idempotency_key="world-bank-test-2")
    assert replay.page.count == 2_890
    assert replay.page.data[0].development_policy.as_tuple().exponent == -2
    assert replay.response_digest == permuted.response_digest
    assert "Authorization" not in first.calls[0][1]
    assert first.calls[0][1]["Accept"] == "application/json"


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": True},
        {"development_policy": "NaN"},
        {"country": ""},
    ],
)
def test_world_bank_connector_rejects_schema_drift_and_nonfinite_values(mutation: dict[str, object]) -> None:
    payload = _payload()
    row = dict(payload["data"][0])
    row.update(mutation)
    payload["data"] = [row]
    transport = _Transport([NetworkResponse(200, json.dumps(payload).encode("utf-8"))])
    connector = WorldBankPublicConnector(NetworkConnectorExecutor(transport), world_bank_public_registration(skip=0))
    with pytest.raises(ConnectorNetworkError, match="response_schema_invalid"):
        connector.read_page(idempotency_key="world-bank-invalid-1")


def test_world_bank_connector_rejects_manifest_substitution() -> None:
    registration = world_bank_public_registration(skip=0).model_copy(
        update={"manifest": WORLD_BANK_PUBLIC_MANIFEST.model_copy(update={"version": "1.0.1"})}
    )
    connector = WorldBankPublicConnector(NetworkConnectorExecutor(_Transport([])), registration)
    with pytest.raises(ConnectorNetworkError, match="manifest_mismatch"):
        connector.read_page(idempotency_key="world-bank-manifest-1")


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_PUBLIC_NETWORK"),
    reason="live public network evidence is opt-in and may drift",
)
def test_live_world_bank_public_page_is_bounded_and_schema_valid() -> None:
    connector = WorldBankPublicConnector(
        NetworkConnectorExecutor(transport=PinnedHttpsGetTransport()),
        world_bank_public_registration(skip=0),
    )
    result = connector.read_page(idempotency_key="world-bank-live-1")
    assert result.page.count >= len(result.page.data)
    assert len(result.page.data) == WORLD_BANK_PUBLIC_PAGE_SIZE
    assert result.attempts == 1
    assert len(result.response_digest) == 64
