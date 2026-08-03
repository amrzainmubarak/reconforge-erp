from __future__ import annotations

from dataclasses import dataclass, field

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


def _registration(manifest: ConnectorManifest | None = None) -> NetworkConnectorRegistration:
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=manifest or _manifest(),
        endpoint="https://api.example.test/v1/records",
        credential_reference="vault://tenant-a/connector-token",
    )


class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tenant-a/connector-token"
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
        "https://api.example.test/v1/records?expand=all",
        "https://api.example.test/v1/records#fragment",
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


def test_dns_answers_fail_closed_for_private_or_mixed_addresses() -> None:
    assert resolve_public_addresses(
        "api.example.test", 443, resolver=lambda _host, _port: ("93.184.216.34",)
    ) == ("93.184.216.34",)
    for answers in [("127.0.0.1",), ("93.184.216.34", "169.254.169.254")]:
        with pytest.raises(ConnectorNetworkError, match="not_public"):
            resolve_public_addresses(
                "api.example.test", 443, resolver=lambda _host, _port, values=answers: values
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
        "https://api.example.test/v1/records", headers={}, timeout_seconds=7, maximum_response_bytes=100
    )
    assert response.status == 302
    assert captured[0][0:4] == ("api.example.test", 443, "93.184.216.34", 7)
    assert ("GET", "/v1/records", {}) in captured
