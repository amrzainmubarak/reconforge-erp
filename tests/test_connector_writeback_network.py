"""Provider-neutral HTTPS write-back transport contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from reconforge.connectors.conformance import (
    verify_writeback_compensation_retry_failure_injection,
    verify_writeback_retry_failure_injection,
)
from reconforge.connectors.writeback import (
    WritebackPolicy,
    WritebackStatus,
    approve_writeback,
    dispatch_writeback,
    request_compensation,
)
from reconforge.connectors.writeback_network import (
    PinnedHttpsPostTransport,
    WritebackNetworkError,
    WritebackNetworkExecutor,
    WritebackNetworkRegistration,
    WritebackNetworkResponse,
    WritebackProviderResponse,
)
from tests.test_connector_writeback import NOW, _intent

PAYLOAD = b'{"amount":"10.00","currency":"USD","reference":"payment-1"}'
COMPENSATION_PAYLOAD = b'{"amount":"10.00","currency":"USD","reference":"payment-1","action":"reverse"}'
CONNECTOR_ID = "reference-rest-writeback"
POLICY = WritebackPolicy(
    connector_id=CONNECTOR_ID,
    allowed_operations=frozenset({"payment.create"}),
    feature_enabled=True,
)


def _registration(**updates: object) -> WritebackNetworkRegistration:
    values: dict[str, object] = {
        "registration_schema": "writeback-network-registration-v1",
        "connector_id": CONNECTOR_ID,
        "version": "1.0.0",
        "endpoint": "https://api.example.test/v1/writeback",
        "egress_destinations": ("https://api.example.test/v1/writeback",),
        "credential_reference": "vault://tenant-a/writeback-token",
        "allowed_operations": frozenset({"payment.create"}),
        "allowed_compensation_operations": frozenset(),
        "feature_enabled": True,
        "synthetic_sandbox": True,
        "rate_limit_per_minute": 60,
        "timeout_seconds": 7,
    }
    values.update(updates)
    return WritebackNetworkRegistration.model_validate(values)


def _dispatched_intent(payload: bytes = PAYLOAD):
    proposed = _intent(
        connector_id=CONNECTOR_ID,
        payload_digest=hashlib.sha256(payload).hexdigest(),
        operation="payment.create",
    )
    approved = approve_writeback(
        proposed,
        policy=POLICY,
        actor_id="checker-1",
        approved_at=NOW,
        assurance="mfa",
        reason="independent provider review",
    )
    return dispatch_writeback(approved, policy=POLICY)


def _compensation_requested_intent():
    return request_compensation(_dispatched_intent(), reason="provider accepted the original mutation but downstream state diverged")


def _provider_body(intent_idempotency_key: str, *, reference: str = "provider-1", accepted: bool = True) -> bytes:
    payload = {
        "accepted": accepted,
        "idempotency_key": intent_idempotency_key,
        "provider_reference": reference,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
    return json.dumps({**payload, "response_digest": digest}, sort_keys=True, separators=(",", ":")).encode("ascii")


class _Secrets:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault://tenant-a/writeback-token"
        return b"synthetic-writeback-token-123"


@dataclass
class _Payloads:
    payload: bytes = PAYLOAD

    def resolve(self, intent: object) -> bytes:
        del intent
        return self.payload


@dataclass
class _Transport:
    responses: list[WritebackNetworkResponse | Exception]
    calls: list[tuple[str, dict[str, str], bytes, int, int]] = field(default_factory=list)

    def post(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> WritebackNetworkResponse:
        self.calls.append((endpoint, dict(headers), body, timeout_seconds, maximum_response_bytes))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_writeback_registration_is_explicit_and_canonical() -> None:
    first = _registration()
    second = _registration()
    assert first.digest == second.digest
    assert first.feature_enabled is True
    with pytest.raises(ValidationError, match="exact HTTPS"):
        _registration(endpoint="http://api.example.test/v1/writeback", egress_destinations=("http://api.example.test/v1/writeback",))
    with pytest.raises(ValidationError, match="query"):
        _registration(endpoint="https://api.example.test/v1/writeback?unsafe=1", egress_destinations=("https://api.example.test/v1/writeback?unsafe=1",))
    with pytest.raises(ValidationError, match="canonically sorted"):
        _registration(egress_destinations=("https://z.example.test/writeback", "https://api.example.test/v1/writeback"))


def test_network_dispatch_verifies_payload_sends_secret_only_to_transport_and_binds_ack() -> None:
    intent = _dispatched_intent()
    transport = _Transport([WritebackNetworkResponse(200, _provider_body(intent.idempotency_key))])
    receipt = WritebackNetworkExecutor(
        transport,
        payload_resolver=_Payloads(),
        secret_resolver=_Secrets(),
        clock=lambda: 0.0,
    ).dispatch(intent, registration=_registration(), policy=POLICY)
    assert receipt.intent.status is WritebackStatus.ACKNOWLEDGED
    assert receipt.intent.acknowledgement is not None
    assert receipt.intent.acknowledgement.provider_reference == "provider-1"
    assert receipt.attempts == 1
    assert len(receipt.request_digest) == len(receipt.response_digest) == 64
    endpoint, headers, body, timeout, maximum = transport.calls[0]
    assert endpoint == "https://api.example.test/v1/writeback"
    assert body == PAYLOAD
    assert headers["Idempotency-Key"] == intent.idempotency_key
    assert headers["Authorization"].startswith("Bearer ")
    assert b"synthetic-writeback-token" not in receipt.intent.model_dump_json().encode()
    assert (timeout, maximum) == (7, 1_048_576)


def test_network_compensation_uses_separate_allowlist_key_and_payload_digest() -> None:
    intent = _compensation_requested_intent()
    compensation_digest = hashlib.sha256(COMPENSATION_PAYLOAD).hexdigest()
    compensation_key = intent.idempotency_key + ":compensation"
    transport = _Transport([WritebackNetworkResponse(200, _provider_body(compensation_key, reference="compensation-1"))])
    receipt = WritebackNetworkExecutor(
        transport,
        payload_resolver=_Payloads(),
        secret_resolver=_Secrets(),
        clock=lambda: 0.0,
    ).dispatch_compensation(
        intent,
        registration=_registration(allowed_compensation_operations=frozenset({"payment.create"})),
        policy=POLICY,
        payload=COMPENSATION_PAYLOAD,
        payload_digest=compensation_digest,
    )
    assert receipt.intent.status is WritebackStatus.COMPENSATED
    assert receipt.intent.acknowledgement is not None
    assert receipt.intent.acknowledgement.idempotency_key == compensation_key
    assert receipt.intent.acknowledgement.provider_reference == "compensation-1"
    endpoint, headers, body, _timeout, _maximum = transport.calls[0]
    assert endpoint == "https://api.example.test/v1/writeback"
    assert headers["Idempotency-Key"] == compensation_key
    assert headers["X-ReconForge-Operation"] == "compensate.payment.create"
    assert body == COMPENSATION_PAYLOAD


def test_network_compensation_fails_closed_without_allowlist_or_with_tampered_payload() -> None:
    intent = _compensation_requested_intent()
    digest = hashlib.sha256(COMPENSATION_PAYLOAD).hexdigest()
    executor = WritebackNetworkExecutor(_Transport([]), payload_resolver=_Payloads(), secret_resolver=_Secrets())
    with pytest.raises(WritebackNetworkError, match="compensation_operation_not_allowed"):
        executor.dispatch_compensation(
            intent,
            registration=_registration(),
            policy=POLICY,
            payload=COMPENSATION_PAYLOAD,
            payload_digest=digest,
        )
    with pytest.raises(WritebackNetworkError, match="compensation_payload_digest_mismatch"):
        executor.dispatch_compensation(
            intent,
            registration=_registration(allowed_compensation_operations=frozenset({"payment.create"})),
            policy=POLICY,
            payload=b"tampered",
            payload_digest=digest,
        )


def test_network_compensation_rejects_negative_provider_acknowledgement() -> None:
    intent = _compensation_requested_intent()
    compensation_key = intent.idempotency_key + ":compensation"
    transport = _Transport([WritebackNetworkResponse(200, _provider_body(compensation_key, accepted=False))])
    with pytest.raises(WritebackNetworkError, match="compensation_not_accepted"):
        WritebackNetworkExecutor(
            transport,
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
        ).dispatch_compensation(
            intent,
            registration=_registration(allowed_compensation_operations=frozenset({"payment.create"})),
            policy=POLICY,
            payload=COMPENSATION_PAYLOAD,
            payload_digest=hashlib.sha256(COMPENSATION_PAYLOAD).hexdigest(),
        )


def test_network_compensation_retries_with_the_same_compensation_key() -> None:
    intent = _compensation_requested_intent()
    compensation_key = intent.idempotency_key + ":compensation"
    transport = _Transport(
        [
            WritebackNetworkResponse(503, b"retry"),
            WritebackNetworkError("writeback_transport_failed"),
            WritebackNetworkResponse(200, _provider_body(compensation_key)),
        ]
    )
    waits: list[float] = []
    receipt = WritebackNetworkExecutor(
        transport,
        payload_resolver=_Payloads(),
        secret_resolver=_Secrets(),
        sleeper=waits.append,
        clock=lambda: 0.0,
    ).dispatch_compensation(
        intent,
        registration=_registration(allowed_compensation_operations=frozenset({"payment.create"})),
        policy=POLICY,
        payload=COMPENSATION_PAYLOAD,
        payload_digest=hashlib.sha256(COMPENSATION_PAYLOAD).hexdigest(),
    )
    assert receipt.attempts == 3
    assert all(call[1]["Idempotency-Key"] == compensation_key for call in transport.calls)
    assert all(call[1]["X-ReconForge-Operation"] == "compensate.payment.create" for call in transport.calls)
    assert 1.0 in waits and 2.0 in waits


def test_formal_compensation_failure_injection_conformance_is_bounded() -> None:
    intent = _compensation_requested_intent()
    digest = hashlib.sha256(COMPENSATION_PAYLOAD).hexdigest()
    waits: list[float] = []
    result = verify_writeback_compensation_retry_failure_injection(
        _registration(allowed_compensation_operations=frozenset({"payment.create"})),
        lambda transport: WritebackNetworkExecutor(
            transport,
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
            sleeper=waits.append,
            clock=lambda: 0.0,
        ),
        intent,
        POLICY,
        payload=COMPENSATION_PAYLOAD,
        payload_digest=digest,
        transient_statuses=(503, 429),
    )
    assert result.checks == (
        "registration_valid",
        "synthetic_failure_injection",
        "bounded_compensation_retry",
        "successful_compensation",
        "compensation_acknowledgement_bound",
    )
    assert 1.0 in waits and 2.0 in waits


def test_network_dispatch_rejects_disabled_state_wrong_scope_and_payload_digest() -> None:
    intent = _dispatched_intent()
    transport = _Transport([])
    with pytest.raises(WritebackNetworkError, match="digest_mismatch"):
        WritebackNetworkExecutor(
            transport,
            payload_resolver=_Payloads(payload=b"tampered"),
            secret_resolver=_Secrets(),
        ).dispatch(intent, registration=_registration(), policy=POLICY)
    with pytest.raises(WritebackNetworkError, match="feature_disabled"):
        WritebackNetworkExecutor(transport, payload_resolver=_Payloads(), secret_resolver=_Secrets()).dispatch(
            intent, registration=_registration(feature_enabled=False), policy=POLICY
        )
    with pytest.raises(WritebackNetworkError, match="connector_not_allowed"):
        WritebackNetworkExecutor(transport, payload_resolver=_Payloads(), secret_resolver=_Secrets()).dispatch(
            intent, registration=_registration(connector_id="other-connector", egress_destinations=("https://api.example.test/v1/writeback",)), policy=POLICY
        )


def test_network_dispatch_retries_transient_http_and_transport_failures_with_same_key() -> None:
    intent = _dispatched_intent()
    transport = _Transport(
        [
            WritebackNetworkResponse(503, b"retry"),
            WritebackNetworkError("writeback_transport_failed"),
            WritebackNetworkResponse(200, _provider_body(intent.idempotency_key)),
        ]
    )
    waits: list[float] = []
    receipt = WritebackNetworkExecutor(
        transport,
        payload_resolver=_Payloads(),
        secret_resolver=_Secrets(),
        sleeper=waits.append,
        clock=lambda: 0.0,
    ).dispatch(intent, registration=_registration(), policy=POLICY)
    assert receipt.attempts == 3
    assert len(transport.calls) == 3
    assert all(call[1]["Idempotency-Key"] == intent.idempotency_key for call in transport.calls)
    assert all(call[2] == PAYLOAD for call in transport.calls)
    assert 1.0 in waits and 2.0 in waits


def test_formal_writeback_failure_injection_conformance_is_bounded_and_idempotent() -> None:
    intent = _dispatched_intent()
    waits: list[float] = []
    result = verify_writeback_retry_failure_injection(
        _registration(),
        lambda transport: WritebackNetworkExecutor(
            transport,
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
            sleeper=waits.append,
            clock=lambda: 0.0,
        ),
        intent,
        POLICY,
        transient_statuses=(503, 429),
    )
    assert result.checks == (
        "registration_valid",
        "synthetic_failure_injection",
        "bounded_idempotent_retry",
        "successful_recovery",
        "acknowledgement_bound",
    )
    assert 1.0 in waits and 2.0 in waits


@pytest.mark.parametrize(
    "response, error",
    [
        (WritebackNetworkResponse(400, b"provider-secret"), "permanent_http_failure"),
        (WritebackNetworkResponse(200, b"{}", content_type="text/plain"), "content_type_invalid"),
        (WritebackNetworkResponse(200, _provider_body("wrong-key")), "acknowledgement_mismatch"),
    ],
)
def test_network_dispatch_fails_closed_on_permanent_or_misbound_provider_response(
    response: WritebackNetworkResponse, error: str
) -> None:
    with pytest.raises(WritebackNetworkError, match=error):
        intent = _dispatched_intent()
        WritebackNetworkExecutor(
            _Transport([response]), payload_resolver=_Payloads(), secret_resolver=_Secrets()
        ).dispatch(intent, registration=_registration(), policy=POLICY)


def test_network_dispatch_rejects_secret_payload_response_and_provider_digest_bounds() -> None:
    intent = _dispatched_intent()
    with pytest.raises(WritebackNetworkError, match="secret_resolution_disabled"):
        WritebackNetworkExecutor(_Transport([]), payload_resolver=_Payloads()).dispatch(
            intent, registration=_registration(), policy=POLICY
        )
    with pytest.raises(WritebackNetworkError, match="payload_size_invalid"):
        WritebackNetworkExecutor(
            _Transport([]), payload_resolver=_Payloads(payload=b"x" * 10), secret_resolver=_Secrets()
        ).dispatch(intent, registration=_registration(maximum_request_bytes=9), policy=POLICY)
    with pytest.raises(WritebackNetworkError, match="response_too_large"):
        WritebackNetworkExecutor(
            _Transport([WritebackNetworkResponse(200, b"x" * 10)]),
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
        ).dispatch(intent, registration=_registration(maximum_response_bytes=9), policy=POLICY)
    with pytest.raises(ValidationError, match="response digest"):
        WritebackProviderResponse.model_validate(
            {
                "provider_reference": "provider-1",
                "idempotency_key": intent.idempotency_key,
                "accepted": True,
                "response_digest": "0" * 64,
            }
        )


def test_pinned_https_post_transport_preserves_hostname_and_never_follows_redirect() -> None:
    captured: list[tuple[object, ...]] = []

    class _Response:
        status = 302

        def read(self, amount: int) -> bytes:
            captured.append(("read", amount))
            return b"redirect"

        def getheader(self, name: str) -> str:
            assert name == "Content-Type"
            return "application/json"

    class _Connection:
        def request(self, method: str, target: str, *, body: bytes, headers: dict[str, str]) -> None:
            captured.append((method, target, body, headers))

        def getresponse(self) -> _Response:
            return _Response()

        def close(self) -> None:
            captured.append(("close",))

    def factory(host: str, port: int, address: str, timeout: int, context: object) -> _Connection:
        captured.append((host, port, address, timeout, context))
        return _Connection()

    transport = PinnedHttpsPostTransport(
        resolver=lambda _host, _port: ("93.184.216.34",), connection_factory=factory
    )
    response = transport.post(
        "https://api.example.test/v1/writeback",
        headers={"Idempotency-Key": "key-1"},
        body=PAYLOAD,
        timeout_seconds=7,
        maximum_response_bytes=100,
    )
    assert response.status == 302
    assert captured[0][0:4] == ("api.example.test", 443, "93.184.216.34", 7)
    assert ("POST", "/v1/writeback", PAYLOAD, {"Idempotency-Key": "key-1"}) in captured
