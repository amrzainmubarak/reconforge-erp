from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import ValidationError

from reconforge.connectors.conformance import verify_network_connector, verify_network_retry_failure_injection
from reconforge.connectors.manifest import (
    AuthenticationMethod,
    ConnectorCapability,
    ConnectorKind,
    ConnectorManifest,
    DataClassification,
    RetryPolicy,
    SupportLevel,
)
from reconforge.connectors.network import (
    ConnectorNetworkError,
    NetworkConnectorExecutor,
    NetworkConnectorRegistration,
    NetworkResponse,
    PinnedHttpsGetTransport,
    resolve_public_addresses,
)


def _manifest(**changes: object) -> ConnectorManifest:
    values: dict[str, object] = {
        "schema_version": "connector-manifest-v1",
        "connector_id": "synthetic_rest",
        "display_name": "Synthetic REST source",
        "version": "1.0.0",
        "kind": ConnectorKind.NETWORK_SOURCE,
        "capabilities": [ConnectorCapability.READ],
        "authentication": AuthenticationMethod.SECRET_REFERENCE,
        "network_required": True,
        "data_classification": DataClassification.RESTRICTED,
        "rate_limit_per_minute": 60,
        "incremental_cursor": True,
        "idempotent_reads": True,
        "retry_policy": RetryPolicy(maximum_attempts=3, initial_delay_seconds=1, maximum_delay_seconds=2),
        "schema_versions": ["synthetic-rest-v1"],
        "synthetic_sandbox": True,
        "threat_model": ["ssrf", "credential-disclosure", "retry-amplification"],
        "secret_handling": "Resolve by reference at execution time; never persist or return values.",
        "egress_destinations": ["https://api.example.test/v1/records"],
        "support_level": SupportLevel.EXPERIMENTAL,
    }
    values.update(changes)
    return ConnectorManifest.model_validate(values)


def _registration(
    manifest: ConnectorManifest | None = None,
    *,
    endpoint: str = "https://api.example.test/v1/records",
) -> NetworkConnectorRegistration:
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=manifest or _manifest(),
        endpoint=endpoint,
        credential_reference="vault://tenant-a/connector-token",
    )


class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference in {
            "vault://tenant-a/connector-token",
            "vault://tenant-b/connector-token",
        }
        return b"synthetic-token-value-123"


@dataclass
class _Transport:
    responses: list[NetworkResponse | Exception]
    calls: list[tuple[str, dict[str, str], int, int]] = field(default_factory=list)

    def get(self, endpoint: str, *, headers: dict[str, str], timeout_seconds: int, maximum_response_bytes: int) -> NetworkResponse:
        self.calls.append((endpoint, dict(headers), timeout_seconds, maximum_response_bytes))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_network_read_is_exact_idempotent_cursor_bound_and_secret_redacted() -> None:
    transport = _Transport([NetworkResponse(200, b'{"records":[]}', "cursor-2")])
    waits: list[float] = []
    executor = NetworkConnectorExecutor(transport, secret_resolver=_Secrets(), sleeper=waits.append)
    result = executor.read(_registration(), idempotency_key="run-1", cursor="cursor-1")
    assert result.next_cursor == "cursor-2"
    assert result.attempts == 1
    assert len(result.request_digest) == len(result.response_digest) == 64
    endpoint, headers, timeout, maximum = transport.calls[0]
    assert endpoint == "https://api.example.test/v1/records"
    assert headers["Idempotency-Key"] == "run-1"
    assert headers["X-ReconForge-Cursor"] == "cursor-1"
    assert headers["Authorization"].startswith("Bearer ")
    assert (timeout, maximum) == (10, 1_048_576)
    assert b"synthetic-token" not in result.response_body


def test_network_read_binds_sorted_query_parameters_without_rewriting_fixed_query() -> None:
    transport = _Transport([NetworkResponse(200, b"{}")])
    registration = _registration(
        manifest=_manifest(egress_destinations=["https://api.example.test/v1/records?fixed=1"]),
        endpoint="https://api.example.test/v1/records?fixed=1",
    )
    result = NetworkConnectorExecutor(transport, secret_resolver=_Secrets()).read(
        registration,
        idempotency_key="query-1",
        query_parameters=(("filters", "[[\"company\",\"=\",\"Acme\"]]"), ("limit", "50")),
    )

    assert transport.calls[0][0] == (
        "https://api.example.test/v1/records?fixed=1&filters=%5B%5B%22company%22%2C%22%3D%22%2C%22Acme%22%5D%5D&limit=50"
    )
    assert result.request_digest


@pytest.mark.parametrize(
    "query_parameters",
    [
        (("limit", "1"), ("filters", "x")),
        (("limit", "1"), ("limit", "2")),
        (("bad key", "1"),),
        (("limit", "a\nb"),),
    ],
)
def test_network_read_rejects_ambiguous_query_parameters(query_parameters: tuple[tuple[str, str], ...]) -> None:
    with pytest.raises(ConnectorNetworkError, match="query_parameters_invalid"):
        NetworkConnectorExecutor(_Transport([]), secret_resolver=_Secrets()).read(
            _registration(), idempotency_key="query-invalid", query_parameters=query_parameters
        )


def test_formal_network_conformance_replays_identically() -> None:
    transport = _Transport(
        [NetworkResponse(200, b'{"records":[]}', "cursor-2"), NetworkResponse(200, b'{"records":[]}', "cursor-2")]
    )
    clock_values = iter([0.0, 1.0])
    result = verify_network_connector(
        _registration(),
        NetworkConnectorExecutor(transport, secret_resolver=_Secrets(), clock=lambda: next(clock_values)),
        idempotency_key="conformance-1",
        cursor="cursor-1",
    )
    assert result.checks[-2:] == ("idempotent_replay", "synthetic_sandbox")


def test_transient_retry_is_bounded_and_permanent_failure_is_not_retried() -> None:
    transient = _Transport([NetworkResponse(503, b"ignored"), NetworkResponse(429, b"ignored"), NetworkResponse(200, b"ok")])
    waits: list[float] = []
    clock_values = iter([0.0, 1.0, 3.0])
    result = NetworkConnectorExecutor(
        transient,
        secret_resolver=_Secrets(),
        sleeper=waits.append,
        clock=lambda: next(clock_values),
    ).read(_registration(), idempotency_key="retry-1")
    assert result.attempts == 3
    assert waits == [1.0, 2.0]
    permanent = _Transport([NetworkResponse(403, b"do-not-disclose")])
    with pytest.raises(ConnectorNetworkError, match="permanent_http_failure"):
        NetworkConnectorExecutor(permanent, secret_resolver=_Secrets()).read(
            _registration(), idempotency_key="permanent-1"
        )
    assert len(permanent.calls) == 1


def test_network_circuit_breaker_fails_fast_and_recovers_after_open_window() -> None:
    transport = _Transport(
        [
            NetworkResponse(503, b"ignored"),
            NetworkResponse(503, b"ignored"),
            NetworkResponse(503, b"ignored"),
            NetworkResponse(200, b"recovered"),
        ]
    )
    now = [0.0]
    executor = NetworkConnectorExecutor(
        transport,
        secret_resolver=_Secrets(),
        circuit_failure_threshold=1,
        circuit_open_seconds=5,
        clock=lambda: now[0],
    )
    with pytest.raises(ConnectorNetworkError, match="retry_exhausted"):
        executor.read(_registration(), idempotency_key="circuit-1")
    assert len(transport.calls) == 3
    with pytest.raises(ConnectorNetworkError, match="circuit_open"):
        executor.read(_registration(), idempotency_key="circuit-2")
    assert len(transport.calls) == 3
    now[0] = 5.0
    result = executor.read(_registration(), idempotency_key="circuit-3")
    assert result.response_body == b"recovered"
    assert result.attempts == 1
    assert len(transport.calls) == 4


@pytest.mark.parametrize(
    ("registration_change", "responses"),
    [
        (
            {"endpoint": "https://api.example.test/v1/other-records"},
            [NetworkResponse(503, b"ignored"), NetworkResponse(503, b"ignored"), NetworkResponse(503, b"ignored"), NetworkResponse(200, b"other")],
        ),
        (
            {"credential_reference": "vault://tenant-b/connector-token"},
            [NetworkResponse(503, b"ignored"), NetworkResponse(503, b"ignored"), NetworkResponse(503, b"ignored"), NetworkResponse(200, b"other")],
        ),
    ],
)
def test_network_circuit_state_isolated_by_endpoint_and_credential(
    registration_change: dict[str, str], responses: list[NetworkResponse | Exception]
) -> None:
    endpoint = "https://api.example.test/v1/other-records"
    manifest = _manifest(
        egress_destinations=[endpoint, "https://api.example.test/v1/records"],
    )
    first = _registration(manifest)
    second = _registration(manifest, endpoint=endpoint) if "endpoint" in registration_change else _registration(manifest)
    if "credential_reference" in registration_change:
        second = _registration(manifest)
        second = second.model_copy(update=registration_change)
    transport = _Transport(responses)
    executor = NetworkConnectorExecutor(
        transport,
        secret_resolver=_Secrets(),
        circuit_failure_threshold=1,
        circuit_open_seconds=30,
        clock=lambda: 0.0,
    )
    with pytest.raises(ConnectorNetworkError, match="retry_exhausted"):
        executor.read(first, idempotency_key="scope-1")
    result = executor.read(second, idempotency_key="scope-2")
    assert result.response_body == b"other"
    assert len(transport.calls) == 4


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("circuit_failure_threshold", 0),
        ("circuit_failure_threshold", 101),
        ("circuit_failure_threshold", True),
        ("circuit_open_seconds", -1),
        ("circuit_open_seconds", 3_601),
        ("circuit_open_seconds", True),
    ],
)
def test_network_circuit_policy_bounds_are_fail_closed(field: str, value: object) -> None:
    invalid_kwargs: dict[str, Any] = {field: value}
    with pytest.raises(ValueError, match=field):
        NetworkConnectorExecutor(_Transport([]), **invalid_kwargs)


def test_formal_failure_injection_conformance_is_bounded_and_provider_neutral() -> None:
    waits: list[float] = []
    result = verify_network_retry_failure_injection(
        _registration(),
        lambda transport: NetworkConnectorExecutor(
            transport,
            secret_resolver=_Secrets(),
            sleeper=waits.append,
            clock=lambda: 0.0,
        ),
        transient_statuses=(503, 429),
    )
    assert result.checks == (
        "manifest_valid",
        "synthetic_failure_injection",
        "bounded_transient_retry",
        "successful_recovery",
        "response_body_isolated",
    )
    assert waits.count(1.0) >= 2 and waits.count(2.0) >= 2


@pytest.mark.parametrize("statuses", [(403,), (503, 503, 503)])
def test_formal_failure_injection_rejects_invalid_or_exhausting_profiles(statuses: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="(retryable HTTP statuses|leave one attempt)"):
        verify_network_retry_failure_injection(
            _registration(),
            lambda transport: NetworkConnectorExecutor(transport, secret_resolver=_Secrets()),
            transient_statuses=statuses,
        )


def test_runtime_fails_closed_for_secret_cursor_size_and_response_bounds() -> None:
    response = NetworkResponse(200, b"x" * 11)
    registration = _registration().model_copy(update={"maximum_response_bytes": 10})
    with pytest.raises(ConnectorNetworkError, match="response_too_large"):
        NetworkConnectorExecutor(_Transport([response]), secret_resolver=_Secrets()).read(
            registration, idempotency_key="bounded-1"
        )
    with pytest.raises(ConnectorNetworkError, match="secret_resolution_disabled"):
        NetworkConnectorExecutor(_Transport([])).read(_registration(), idempotency_key="disabled-1")
    with pytest.raises(ConnectorNetworkError, match="cursor_invalid"):
        NetworkConnectorExecutor(_Transport([]), secret_resolver=_Secrets()).read(
            _registration(), idempotency_key="cursor-1", cursor="x" * 4097
        )
    policy_error = _Transport([ConnectorNetworkError("connector_response_too_large")])
    with pytest.raises(ConnectorNetworkError, match="response_too_large"):
        NetworkConnectorExecutor(policy_error, secret_resolver=_Secrets()).read(
            _registration(), idempotency_key="no-retry-1"
        )
    assert len(policy_error.calls) == 1


@pytest.mark.parametrize(
    "destination",
    [
        "http://api.example.test/v1/records",
        "https://user:pass@api.example.test/v1/records",
        "https://api.example.test/v1/records#fragment",
        "https://api.example.test/v1/records?filter=hello world",
    ],
)
def test_manifest_rejects_unsafe_or_ambiguous_egress(destination: str) -> None:
    with pytest.raises(ValidationError, match="exact HTTPS URLs"):
        _manifest(egress_destinations=[destination])


def test_registration_rejects_undeclared_endpoint_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="exactly match"):
        NetworkConnectorRegistration(
            registration_schema="network-connector-registration-v1",
            manifest=_manifest(),
            endpoint="https://evil.example.test/v1/records",
            credential_reference="vault://tenant-a/connector-token",
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        NetworkConnectorRegistration.model_validate({**_registration().model_dump(), "writeback": True})


def test_manifest_and_registration_accept_operator_declared_query_exactly() -> None:
    endpoint = "https://api.example.test/v1/records?expand=all&page%5Bsize%5D=100"
    manifest = _manifest(egress_destinations=[endpoint])
    registration = _registration(manifest, endpoint=endpoint)
    assert registration.endpoint == endpoint
    assert manifest.egress_destinations == (endpoint,)
    assert len(manifest.digest) == 64


def test_public_network_read_uses_no_secret_and_never_emits_authorization() -> None:
    manifest = _manifest(
        authentication=AuthenticationMethod.NONE,
        data_classification=DataClassification.PUBLIC,
        secret_handling="No secret is required; the operator-declared public endpoint is read only.",
    )
    registration = NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=manifest,
        endpoint="https://api.example.test/v1/records",
    )
    transport = _Transport([NetworkResponse(200, b"{}")])
    result = NetworkConnectorExecutor(transport).read(registration, idempotency_key="public-1")
    assert result.attempts == 1
    assert "Authorization" not in transport.calls[0][1]


def test_public_network_conformance_replays_without_secret_resolution() -> None:
    manifest = _manifest(
        authentication=AuthenticationMethod.NONE,
        data_classification=DataClassification.PUBLIC,
        secret_handling="No secret is required; the operator-declared public endpoint is read only.",
    )
    registration = NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=manifest,
        endpoint="https://api.example.test/v1/records",
    )
    transport = _Transport([NetworkResponse(200, b"{}"), NetworkResponse(200, b"{}")])
    result = verify_network_connector(
        registration,
        NetworkConnectorExecutor(transport),
        idempotency_key="public-conformance-1",
    )
    assert "public_no_auth" in result.checks
    assert all("Authorization" not in call[1] for call in transport.calls)


def test_public_network_registration_rejects_credential_reference() -> None:
    manifest = _manifest(
        authentication=AuthenticationMethod.NONE,
        data_classification=DataClassification.PUBLIC,
        secret_handling="No secret is required; the operator-declared public endpoint is read only.",
    )
    with pytest.raises(ValidationError, match="cannot carry credential_reference"):
        NetworkConnectorRegistration(
            registration_schema="network-connector-registration-v1",
            manifest=manifest,
            endpoint="https://api.example.test/v1/records",
            credential_reference="vault://tenant-a/should-not-be-used",
        )


def test_dns_answers_fail_closed_for_private_or_mixed_addresses() -> None:
    assert resolve_public_addresses(
        "api.example.test", 443, resolver=lambda _host, _port: ("93.184.216.34",)
    ) == ("93.184.216.34",)
    for answers in [("127.0.0.1",), ("93.184.216.34", "169.254.169.254")]:
        def _resolver(_host: str, _port: int, values: tuple[str, ...] = answers) -> tuple[str, ...]:
            return values

        with pytest.raises(ConnectorNetworkError, match="not_public"):
            resolve_public_addresses(
                "api.example.test", 443, resolver=_resolver
            )


def test_pinned_transport_retries_resolved_addresses_until_success() -> None:
    resolved_addresses = ("2606:4700:4401::ac40:9119", "93.184.216.34")
    def _address_sort_key(item: str) -> tuple[int, bytes]:
        address = ipaddress.ip_address(item)
        return (address.version, address.packed)

    expected_addresses = tuple(sorted(resolved_addresses, key=_address_sort_key))
    call_order: list[str] = []

    class _Response:
        status = 200

        def read(self, amount: int) -> bytes:
            return b'{"records":[]}'

        def getheader(self, name: str) -> None:
            return None

    class _Connection:
        def __init__(self, address: str) -> None:
            self._address = address

        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            del method, headers
            if self._address == expected_addresses[0]:
                raise OSError("unreachable")
            assert target == "/v1/records"

        def getresponse(self) -> _Response:
            return _Response()

        def close(self) -> None:
            pass

    def factory(_host: str, _port: int, address: str, _timeout: int, _context: object) -> _Connection:
        call_order.append(address)
        return _Connection(address)

    transport = PinnedHttpsGetTransport(
        resolver=lambda _host, _port: resolved_addresses,
        connection_factory=factory,
    )
    response = transport.get(
        "https://api.example.test/v1/records",
        headers={},
        timeout_seconds=5,
        maximum_response_bytes=100,
    )

    assert response.status == 200
    assert call_order == list(expected_addresses)


def test_pinned_transport_reports_connector_transport_failed_when_all_addresses_unreachable() -> None:
    resolved_addresses = ("93.184.216.34", "8.8.8.8")

    class _Connection:
        def __init__(self, _address: str) -> None:
            pass

        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            del method, target, headers
            raise OSError("unreachable")

        def getresponse(self) -> object:
            raise AssertionError("getresponse should not be called")

        def close(self) -> None:
            pass

    def factory(_host: str, _port: int, _address: str, _timeout: int, _context: object) -> _Connection:
        return _Connection(_address)

    transport = PinnedHttpsGetTransport(
        resolver=lambda _host, _port: resolved_addresses,
        connection_factory=factory,
    )
    with pytest.raises(ConnectorNetworkError, match="connector_transport_failed"):
        transport.get(
            "https://api.example.test/v1/records",
            headers={},
            timeout_seconds=5,
            maximum_response_bytes=100,
        )


def test_pinned_transport_preserves_hostname_and_never_follows_redirect() -> None:
    captured: list[tuple[object, ...]] = []

    class _Response:
        status = 302

        def read(self, amount: int) -> bytes:
            captured.append(("read", amount))
            return b"redirect"

        def getheader(self, name: str) -> None:
            return None

    class _Connection:
        def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
            captured.append((method, target, headers))

        def getresponse(self) -> _Response:
            return _Response()

        def close(self) -> None:
            captured.append(("close",))

    def factory(host: str, port: int, address: str, timeout: int, context: object) -> _Connection:
        captured.append((host, port, address, timeout, context))
        return _Connection()

    transport = PinnedHttpsGetTransport(
        resolver=lambda _host, _port: ("93.184.216.34",), connection_factory=factory
    )
    response = transport.get(
        "https://api.example.test/v1/records?expand=all&page%5Bsize%5D=100",
        headers={},
        timeout_seconds=7,
        maximum_response_bytes=100,
    )
    assert response.status == 302
    assert captured[0][0:4] == ("api.example.test", 443, "93.184.216.34", 7)
    assert ("GET", "/v1/records?expand=all&page%5Bsize%5D=100", {}) in captured
