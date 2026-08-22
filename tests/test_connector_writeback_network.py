"""Provider-neutral HTTPS write-back transport contracts."""

from __future__ import annotations

import hashlib
import http.client
import json
import multiprocessing
import os
import socket
import ssl
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pydantic import ValidationError

from reconforge.connectors.conformance import (
    verify_writeback_compensation_retry_failure_injection,
    verify_writeback_retry_failure_injection,
)
from reconforge.connectors.writeback import (
    WritebackIntent,
    WritebackPolicy,
    WritebackStatus,
    approve_writeback,
    dispatch_writeback,
    request_compensation,
)
from reconforge.connectors.writeback_network import (
    PinnedHttpsPostTransport,
    PinnedHttpsRecoveryTransport,
    WritebackNetworkError,
    WritebackNetworkExecutor,
    WritebackNetworkRegistration,
    WritebackNetworkResponse,
    WritebackProviderOutcome,
    WritebackProviderResponse,
    WritebackRecoveryObservation,
)
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_writeback import SQLiteWritebackIntentRepository
from tests.https_runtime import create_localhost_certificate
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


def _dispatched_intent(payload: bytes = PAYLOAD) -> WritebackIntent:
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


def _compensation_requested_intent() -> WritebackIntent:
    return request_compensation(_dispatched_intent(), reason="provider accepted the original mutation but downstream state diverged")


def _provider_body(
    intent_idempotency_key: str,
    *,
    reference: str = "provider-1",
    accepted: bool = True,
    outcome: WritebackProviderOutcome | None = None,
) -> bytes:
    payload = {
        "accepted": accepted,
        "idempotency_key": intent_idempotency_key,
        "provider_reference": reference,
    }
    if outcome is not None:
        payload["outcome"] = outcome.value
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


@dataclass
class _RecoveryTransport:
    response: WritebackNetworkResponse | Exception
    calls: list[tuple[str, dict[str, str], str, int, int]] = field(default_factory=list)

    def recover(
        self,
        endpoint: str,
        *,
        headers: dict[str, str],
        idempotency_key: str,
        timeout_seconds: int,
        maximum_response_bytes: int,
    ) -> WritebackNetworkResponse:
        self.calls.append((endpoint, dict(headers), idempotency_key, timeout_seconds, maximum_response_bytes))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _crash_after_provider_acceptance_before_persistence(
    database_path: str,
    marker_path: str,
    intent_document: dict[str, object],
) -> None:
    """Accept a provider mutation, then exit before the acknowledgement write.

    The child is intentionally terminated with ``os._exit`` after the injected
    provider has accepted the idempotency key.  This models the narrow crash
    window between provider side effect and durable intent acknowledgement.
    The parent must recover by status lookup rather than issuing a second POST.
    """

    connection = connect(Path(database_path))
    try:
        current = SQLiteWritebackIntentRepository(connection).get(
            intent_id=str(intent_document["intent_id"]),
            tenant_id=str(intent_document["tenant_id"]),
            workspace_id=str(intent_document["workspace_id"]),
        )
        if current is None:
            raise AssertionError("dispatched intent was not staged before crash simulation")

        @dataclass
        class AcceptingTransport:
            calls: int = 0

            def post(
                self,
                endpoint: str,
                *,
                headers: dict[str, str],
                body: bytes,
                timeout_seconds: int,
                maximum_response_bytes: int,
            ) -> WritebackNetworkResponse:
                del endpoint, body, timeout_seconds, maximum_response_bytes
                self.calls += 1
                Path(marker_path).write_text(
                    json.dumps(
                        {"accepted": True, "idempotency_key": headers["Idempotency-Key"], "post_calls": self.calls},
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                return WritebackNetworkResponse(200, _provider_body(headers["Idempotency-Key"], reference="accepted-before-crash"))

        executor = WritebackNetworkExecutor(
            AcceptingTransport(),
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
        )
        executor.dispatch(current["intent"], registration=_registration(), policy=POLICY)
    finally:
        # Deliberately bypass normal cleanup to model a worker/process crash.
        os._exit(0)


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
    with pytest.raises(ValidationError, match="declared as an egress"):
        _registration(recovery_endpoint="https://api.example.test/v1/status")


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


def test_network_recovery_reads_provider_idempotency_status_without_resending_mutation() -> None:
    intent = _dispatched_intent()
    transport = _Transport([])
    recovery = _RecoveryTransport(WritebackNetworkResponse(200, _provider_body(intent.idempotency_key)))
    receipt = WritebackNetworkExecutor(
        transport,
        payload_resolver=_Payloads(),
        secret_resolver=_Secrets(),
    ).recover(
        intent,
        registration=_registration(
            recovery_endpoint="https://api.example.test/v1/status",
            egress_destinations=("https://api.example.test/v1/status", "https://api.example.test/v1/writeback"),
        ),
        policy=POLICY,
        transport=recovery,
    )
    assert receipt.intent.status is WritebackStatus.ACKNOWLEDGED
    assert receipt.intent.acknowledgement is not None
    assert receipt.intent.acknowledgement.idempotency_key == intent.idempotency_key
    assert transport.calls == []
    assert len(recovery.calls) == 1
    endpoint, headers, key, timeout, maximum = recovery.calls[0]
    assert endpoint == "https://api.example.test/v1/status"
    assert key == intent.idempotency_key
    assert headers["Idempotency-Key"] == intent.idempotency_key
    assert headers["X-ReconForge-Recovery"] == "idempotency-status-v1"
    assert (timeout, maximum) == (7, 1_048_576)


def test_network_recovery_fails_closed_for_unknown_or_misbound_provider_status() -> None:
    intent = _dispatched_intent()
    executor = WritebackNetworkExecutor(_Transport([]), payload_resolver=_Payloads(), secret_resolver=_Secrets())
    with pytest.raises(WritebackNetworkError, match="recovery_not_found"):
        executor.recover(
            intent,
            registration=_registration(),
            policy=POLICY,
            transport=_RecoveryTransport(WritebackNetworkResponse(404, b"{}")),
        )


@pytest.mark.parametrize(
    ("status", "body_kind", "expected"),
    [
        (200, "accepted", WritebackProviderOutcome.ACCEPTED),
        (200, "rejected", WritebackProviderOutcome.REJECTED),
        (200, "explicit_pending", WritebackProviderOutcome.PENDING),
        (202, "pending", WritebackProviderOutcome.PENDING),
        (404, "not_found", WritebackProviderOutcome.NOT_FOUND),
        (503, "unavailable", WritebackProviderOutcome.UNKNOWN),
        (200, "malformed", WritebackProviderOutcome.UNKNOWN),
    ],
)
def test_network_recovery_observation_classifies_provider_outcomes_without_state_advance(
    status: int,
    body_kind: str,
    expected: WritebackProviderOutcome,
) -> None:
    intent = _dispatched_intent()
    body = {
        "accepted": _provider_body(intent.idempotency_key),
        "rejected": _provider_body(intent.idempotency_key, accepted=False),
        "explicit_pending": _provider_body(
            intent.idempotency_key,
            accepted=False,
            outcome=WritebackProviderOutcome.PENDING,
        ),
        "pending": b'{"state":"processing"}',
        "not_found": b"{}",
        "unavailable": b"upstream unavailable",
        "malformed": b"not-json",
    }[body_kind]
    observation = WritebackNetworkExecutor(
        _Transport([]),
        payload_resolver=_Payloads(),
        secret_resolver=_Secrets(),
    ).observe_recovery(
        intent,
        registration=_registration(
            recovery_endpoint="https://api.example.test/v1/status",
            egress_destinations=("https://api.example.test/v1/status", "https://api.example.test/v1/writeback"),
        ),
        policy=POLICY,
        transport=_RecoveryTransport(WritebackNetworkResponse(status, body)),
    )

    assert isinstance(observation, WritebackRecoveryObservation)
    assert observation.outcome is expected
    assert observation.idempotency_key == intent.idempotency_key
    assert len(observation.body_digest) == 64
    assert len(observation.digest) == 64
    assert intent.status is WritebackStatus.DISPATCHED
    assert intent.acknowledgement is None


def test_network_provider_outcome_is_digest_bound_and_must_agree_with_accepted_flag() -> None:
    intent = _dispatched_intent()
    valid = WritebackProviderResponse.model_validate_json(
        _provider_body(intent.idempotency_key, accepted=False, outcome=WritebackProviderOutcome.REJECTED)
    )
    assert valid.normalized_outcome is WritebackProviderOutcome.REJECTED
    with pytest.raises(ValidationError, match="contradicts accepted flag"):
        WritebackProviderResponse.model_validate_json(
            _provider_body(intent.idempotency_key, accepted=True, outcome=WritebackProviderOutcome.PENDING)
        )


def test_network_recovery_pending_outcome_requires_a_later_status_observation() -> None:
    intent = _dispatched_intent()
    executor = WritebackNetworkExecutor(
        _Transport([]),
        payload_resolver=_Payloads(),
        secret_resolver=_Secrets(),
    )

    with pytest.raises(WritebackNetworkError, match="recovery_pending"):
        executor.recover(
            intent,
            registration=_registration(
                recovery_endpoint="https://api.example.test/v1/status",
                egress_destinations=("https://api.example.test/v1/status", "https://api.example.test/v1/writeback"),
            ),
            policy=POLICY,
            transport=_RecoveryTransport(WritebackNetworkResponse(202, b'{"state":"processing"}')),
        )

    assert intent.status is WritebackStatus.DISPATCHED
    with pytest.raises(WritebackNetworkError, match="recovery_acknowledgement_mismatch"):
        executor.recover(
            intent,
            registration=_registration(),
            policy=POLICY,
            transport=_RecoveryTransport(WritebackNetworkResponse(200, _provider_body("wrong-key"))),
        )


def test_network_crash_after_provider_acceptance_before_persistence_recovers_without_second_post(tmp_path: Path) -> None:
    """A worker crash after provider acceptance is recovered by idempotency lookup."""

    database_path = tmp_path / "writeback-crash.db"
    marker_path = tmp_path / "provider-accepted.json"
    run_migrations(database_path)
    connection = connect(database_path)
    try:
        repository = SQLiteWritebackIntentRepository(connection)
        staged = repository.put(
            _intent(
                connector_id=CONNECTOR_ID,
                payload_digest=hashlib.sha256(PAYLOAD).hexdigest(),
            ),
            expected_version=0,
        )
        approved = approve_writeback(
            staged,
            policy=POLICY,
            actor_id="checker-1",
            approved_at=NOW,
            assurance="mfa",
            reason="independent provider review",
        )
        repository.put(approved, expected_version=1)
        dispatched = dispatch_writeback(approved, policy=POLICY)
        repository.put(dispatched, expected_version=2)
        staged_version = repository.get(
            intent_id=dispatched.intent_id,
            tenant_id=dispatched.tenant_id,
            workspace_id=dispatched.workspace_id,
        )
        assert staged_version is not None
        assert staged_version["version"] == 3
    finally:
        connection.close()

    context = multiprocessing.get_context("spawn")
    child = context.Process(
        target=_crash_after_provider_acceptance_before_persistence,
        args=(str(database_path), str(marker_path), dispatched.model_dump(mode="json")),
    )
    child.start()
    child.join(timeout=20)
    if child.is_alive():
        child.terminate()
        child.join(timeout=5)
    assert child.exitcode == 0
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker == {"accepted": True, "idempotency_key": dispatched.idempotency_key, "post_calls": 1}

    check = connect(database_path)
    try:
        repository = SQLiteWritebackIntentRepository(check)
        uncertain = repository.get(
            intent_id=dispatched.intent_id,
            tenant_id=dispatched.tenant_id,
            workspace_id=dispatched.workspace_id,
        )
        assert uncertain is not None
        assert uncertain["version"] == 3
        assert uncertain["intent"].status is WritebackStatus.DISPATCHED

        recovery = _RecoveryTransport(
            WritebackNetworkResponse(200, _provider_body(dispatched.idempotency_key, reference="recovered-after-crash"))
        )
        recovered = WritebackNetworkExecutor(
            _Transport([]),
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
        ).recover(
            uncertain["intent"],
            registration=_registration(
                recovery_endpoint="https://api.example.test/v1/status",
                egress_destinations=("https://api.example.test/v1/status", "https://api.example.test/v1/writeback"),
            ),
            policy=POLICY,
            transport=recovery,
        )
        persisted = repository.put(recovered.intent, expected_version=3)
        assert persisted.status is WritebackStatus.ACKNOWLEDGED
        assert persisted.acknowledgement is not None
        assert persisted.acknowledgement.provider_reference == "recovered-after-crash"
        assert len(recovery.calls) == 1
    finally:
        check.close()


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


def test_network_dispatch_rejects_negative_provider_outcome_without_acknowledging() -> None:
    intent = _dispatched_intent()
    transport = _Transport([WritebackNetworkResponse(200, _provider_body(intent.idempotency_key, accepted=False))])

    with pytest.raises(WritebackNetworkError, match="not_accepted"):
        WritebackNetworkExecutor(
            transport,
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
        ).dispatch(intent, registration=_registration(), policy=POLICY)

    assert intent.status is WritebackStatus.DISPATCHED
    assert intent.acknowledgement is None


def test_network_recovery_rejects_negative_provider_outcome_without_acknowledging() -> None:
    intent = _dispatched_intent()
    recovery = _RecoveryTransport(
        WritebackNetworkResponse(200, _provider_body(intent.idempotency_key, accepted=False))
    )

    with pytest.raises(WritebackNetworkError, match="recovery_not_accepted"):
        WritebackNetworkExecutor(
            _Transport([]),
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
        ).recover(
            intent,
            registration=_registration(
                recovery_endpoint="https://api.example.test/v1/status",
                egress_destinations=(
                    "https://api.example.test/v1/status",
                    "https://api.example.test/v1/writeback",
                ),
            ),
            policy=POLICY,
            transport=recovery,
        )

    assert intent.status is WritebackStatus.DISPATCHED
    assert intent.acknowledgement is None


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


def test_pinned_https_recovery_transport_uses_get_and_declared_status_key() -> None:
    captured: list[tuple[object, ...]] = []

    class _Response:
        status = 200

        def read(self, amount: int) -> bytes:
            captured.append(("read", amount))
            return _provider_body("key-1")

        def getheader(self, name: str) -> str:
            assert name == "Content-Type"
            return "application/json"

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

    transport = PinnedHttpsRecoveryTransport(
        resolver=lambda _host, _port: ("93.184.216.34",), connection_factory=factory
    )
    response = transport.recover(
        "https://api.example.test/v1/status",
        headers={"Idempotency-Key": "key-1"},
        idempotency_key="key-1",
        timeout_seconds=7,
        maximum_response_bytes=1000,
    )
    assert response.status == 200
    assert captured[0][0:4] == ("api.example.test", 443, "93.184.216.34", 7)
    assert ("GET", "/v1/status", {"Idempotency-Key": "key-1"}) in captured


def test_local_https_writeback_sandbox_exercises_real_tls_retry_and_idempotency(tmp_path: Path) -> None:
    """Exercise the real HTTPS transport against a disposable local provider sandbox.

    The resolver is intentionally given a public test address while the injected
    connection factory pins the socket to the disposable loopback listener. This
    keeps the production SSRF/public-address gate active without contacting an
    external service or using a real credential.
    """

    certificate, key = create_localhost_certificate(tmp_path)
    requests: list[tuple[dict[str, str], bytes]] = []
    recovery_requests: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            requests.append((dict(self.headers), body))
            if len(requests) < 3:
                status = 503
                response_body = b'{"retry":true}'
            else:
                status = 200
                response_body = _provider_body(self.headers.get("Idempotency-Key", ""))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            recovery_requests.append(dict(self.headers))
            response_body = _provider_body(self.headers.get("Idempotency-Key", ""))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.check_hostname = False
    server_context.verify_mode = ssl.CERT_NONE
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(certificate, key)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    waits: list[float] = []
    pinned_addresses: list[str] = []

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
        pinned_addresses.append(address)
        return _LocalPinnedConnection(host, port, timeout, context)

    try:
        endpoint = f"https://localhost:{server.server_port}/v1/writeback"
        client_context = ssl.create_default_context(cafile=str(certificate))
        transport = PinnedHttpsPostTransport(
            resolver=lambda _host, _port: ("93.184.216.34",),
            connection_factory=factory,
            tls_context=client_context,
        )
        intent = _dispatched_intent()
        receipt = WritebackNetworkExecutor(
            transport,
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
            sleeper=waits.append,
            clock=lambda: 0.0,
        ).dispatch(
            intent,
            registration=_registration(endpoint=endpoint, egress_destinations=(endpoint,)),
            policy=POLICY,
        )
        recovery_endpoint = f"https://localhost:{server.server_port}/v1/status"
        recovery_intent = _dispatched_intent()
        recovery = WritebackNetworkExecutor(
            transport,
            payload_resolver=_Payloads(),
            secret_resolver=_Secrets(),
        ).recover(
            recovery_intent,
            registration=_registration(
                endpoint=endpoint,
                recovery_endpoint=recovery_endpoint,
                egress_destinations=tuple(sorted((endpoint, recovery_endpoint))),
            ),
            policy=POLICY,
            transport=PinnedHttpsRecoveryTransport(
                resolver=lambda _host, _port: ("93.184.216.34",),
                connection_factory=factory,
                tls_context=client_context,
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert receipt.attempts == 3
    assert len(requests) == 3
    assert len(recovery_requests) == 1
    assert pinned_addresses == ["93.184.216.34"] * 4
    assert {headers["Idempotency-Key"] for headers, _body in requests} == {intent.idempotency_key}
    assert all(headers["Authorization"] == "Bearer synthetic-writeback-token-123" for headers, _body in requests)
    assert all(body == PAYLOAD for _headers, body in requests)
    assert recovery_requests[0]["Idempotency-Key"] == recovery_intent.idempotency_key
    assert recovery.intent.status is WritebackStatus.ACKNOWLEDGED
    assert receipt.intent.status is WritebackStatus.ACKNOWLEDGED
    assert receipt.intent.acknowledgement is not None
    assert receipt.intent.acknowledgement.provider_reference == "provider-1"
    assert b"synthetic-writeback-token-123" not in receipt.intent.model_dump_json().encode()
    assert waits
