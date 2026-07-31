from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from reconforge.application.notifications import (
    NotificationChannel,
    NotificationDeliveryError,
    NotificationEgressPolicy,
    NotificationError,
    NotificationOutboxPublisher,
    NotificationRequest,
    NotificationRouteRecord,
    NotificationRouteRegistration,
    OutboxPublisherRouter,
    normalize_email_address,
    normalize_webhook_url,
)
from reconforge.infrastructure.notification_transports import (
    HttpsWebhookTransport,
    NotificationTransportRouter,
    SmtpsEmailTransport,
    resolve_public_addresses,
)


def _policy() -> NotificationEgressPolicy:
    return NotificationEgressPolicy(
        enabled=True,
        webhook_urls=frozenset({"https://hooks.example.com/reconforge"}),
        email_domains=frozenset({"example.com"}),
        smtp_relays=frozenset({"smtps://mail.example.com:465"}),
    )


def _route(channel: NotificationChannel = NotificationChannel.WEBHOOK) -> NotificationRouteRecord:
    destination = (
        "https://hooks.example.com/reconforge"
        if channel is NotificationChannel.WEBHOOK
        else "ops@example.com"
    )
    return NotificationRouteRecord(
        registration=NotificationRouteRegistration(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            entity_id="entity-a",
            route_id=f"{channel.value}-route",
            version=1,
            channel=channel,
            destination=destination,
            secret_ref="vault/notification-secret",
        ),
        enabled=True,
        created_by="notification-admin",
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )


def _request(route: NotificationRouteRecord | None = None) -> NotificationRequest:
    selected = route or _route()
    return NotificationRequest(
        tenant_id="tenant-a",
        notification_id="a" * 64,
        route_id=selected.registration.route_id,
        route_version=selected.registration.version,
        destination_digest=selected.registration.destination_digest,
        workspace_id="workspace-a",
        entity_id="entity-a",
        schedule_id="daily-close",
        schedule_version=1,
        dispatch_key="b" * 64,
        scheduled_for=datetime(2026, 7, 29, 12, tzinfo=UTC),
        durable_job_id="scheduled-job-abc",
    )


@dataclass
class _Event:
    tenant_id: str
    id: str
    event_type: str
    payload: dict[str, Any]


def _event(request: NotificationRequest) -> _Event:
    return _Event(
        tenant_id=request.tenant_id,
        id=request.notification_id,
        event_type="notification.scheduler_dispatch.v1",
        payload=request.canonical_payload(),
    )


def test_notification_egress_is_default_deny_and_destinations_are_closed() -> None:
    route = _route()
    with pytest.raises(NotificationError, match="disabled"):
        NotificationEgressPolicy().assert_route_allowed(route)
    for unsafe in (
        "http://hooks.example.com/reconforge",
        "https://user:secret@hooks.example.com/reconforge",
        "https://hooks.example.com/reconforge?token=secret",
        "https://hooks.example.com/reconforge#fragment",
        "https://localhost/reconforge",
    ):
        with pytest.raises(NotificationError):
            normalize_webhook_url(unsafe)
    for unsafe_email in ("Display <ops@example.com>", "ops@localhost", "ops\n@example.com"):
        with pytest.raises(NotificationError):
            normalize_email_address(unsafe_email)
    with pytest.raises(NotificationError, match="not allowlisted"):
        _policy().assert_route_allowed(
            NotificationRouteRegistration(
                tenant_id="tenant-a",
                workspace_id="workspace-a",
                entity_id="",
                route_id="other",
                version=1,
                channel=NotificationChannel.WEBHOOK,
                destination="https://other.example.com/hook",
                secret_ref="vault/hook",
            )
        )


def test_notification_envelope_is_deterministic_redacted_and_rejects_extra_fields() -> None:
    request = _request()
    payload = request.canonical_payload()
    assert request.canonical_json() == json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    serialized = request.canonical_json().decode("ascii")
    assert "https://" not in serialized
    assert "vault/" not in serialized
    assert "amount" not in serialized
    assert NotificationRequest.from_outbox_event(_event(request)) == request
    invalid = _event(request)
    invalid.payload["raw_financial_row"] = "forbidden"
    with pytest.raises(NotificationError, match="shape"):
        NotificationRequest.from_outbox_event(invalid)

    schema = json.loads(
        (Path(__file__).parents[1] / "docs" / "schemas" / "notification_request.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)


def test_notification_publisher_rechecks_scope_digest_and_routes_unrelated_events() -> None:
    route = _route()
    request = _request(route)

    class Resolver:
        def resolve(self, _request: NotificationRequest) -> NotificationRouteRecord:
            return route

    delivered: list[str] = []

    class Transport:
        def deliver(self, _route: NotificationRouteRecord, item: NotificationRequest) -> None:
            delivered.append(item.notification_id)

    publisher = NotificationOutboxPublisher(resolver=Resolver(), transport=Transport(), policy=_policy())
    publisher.publish(_event(request))
    assert delivered == [request.notification_id]

    wrong = NotificationRouteRecord(
        registration=NotificationRouteRegistration(
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            entity_id="entity-a",
            route_id=route.registration.route_id,
            version=1,
            channel=NotificationChannel.WEBHOOK,
            destination="https://hooks.example.com/changed",
            secret_ref="vault/notification-secret",
        ),
        enabled=True,
        created_by="admin",
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )

    class WrongResolver:
        def resolve(self, _request: NotificationRequest) -> NotificationRouteRecord:
            return wrong

    changed_policy = NotificationEgressPolicy(
        enabled=True,
        webhook_urls=frozenset({wrong.destination}),
    )
    with pytest.raises(NotificationDeliveryError, match="binding changed"):
        NotificationOutboxPublisher(
            resolver=WrongResolver(), transport=Transport(), policy=changed_policy
        ).publish(_event(request))

    delegated: list[str] = []
    router = OutboxPublisherRouter(
        notification_publisher=publisher,
        default_publisher=lambda event: delegated.append(event.id),
    )
    router.publish(_Event("tenant-a", "domain-event", "ledger.posted", {}))
    assert delegated == ["domain-event"]


class _SecretResolver:
    def resolve(self, reference: str) -> bytes:
        assert reference == "vault/notification-secret"
        return b"synthetic-secret-material-32-bytes"


class _Response:
    status = 204

    def read(self, limit: int) -> bytes:
        assert limit == 65_537
        return b""


class _WebhookConnection:
    def __init__(self) -> None:
        self.request_call: tuple[object, ...] | None = None
        self.closed = False

    def request(self, method: str, path: str, *, body: bytes, headers: dict[str, str]) -> None:
        self.request_call = (method, path, body, headers)

    def getresponse(self) -> _Response:
        return _Response()

    def close(self) -> None:
        self.closed = True


class _LargeResponse(_Response):
    def read(self, limit: int) -> bytes:
        return b"x" * limit


class _LargeResponseConnection(_WebhookConnection):
    def getresponse(self) -> _LargeResponse:
        return _LargeResponse()


def test_webhook_transport_pins_validated_public_dns_and_signs_redacted_body() -> None:
    route = _route()
    request = _request(route)
    connection = _WebhookConnection()
    connected: list[tuple[str, int, str]] = []

    def factory(host: str, port: int, address: str, _timeout: float, _context: object) -> _WebhookConnection:
        connected.append((host, port, address))
        return connection

    transport = HttpsWebhookTransport(
        policy=_policy(),
        secret_resolver=_SecretResolver(),
        resolver=lambda host, port: ("93.184.216.34",),
        connection_factory=factory,  # type: ignore[arg-type]
    )
    transport.deliver(route, request)
    assert connected == [("hooks.example.com", 443, "93.184.216.34")]
    assert connection.closed is True and connection.request_call is not None
    method, path, body, headers = connection.request_call
    assert (method, path, body) == ("POST", "/reconforge", request.canonical_json())
    assert headers["Idempotency-Key"] == request.notification_id  # type: ignore[index]
    assert str(headers["X-ReconForge-Signature"]).startswith("v1=")  # type: ignore[index]

    with pytest.raises(NotificationDeliveryError, match="non-public"):
        resolve_public_addresses("hooks.example.com", 443, resolver=lambda _host, _port: ("127.0.0.1",))
    with pytest.raises(NotificationDeliveryError, match="non-public"):
        resolve_public_addresses(
            "hooks.example.com",
            443,
            resolver=lambda _host, _port: ("93.184.216.34", "169.254.169.254"),
        )
    oversized = _LargeResponseConnection()
    bounded = HttpsWebhookTransport(
        policy=_policy(),
        secret_resolver=_SecretResolver(),
        resolver=lambda host, port: ("93.184.216.34",),
        connection_factory=lambda *_args: oversized,
        max_response_bytes=8,
    )
    with pytest.raises(NotificationDeliveryError, match="response exceeded"):
        bounded.deliver(route, request)
    assert oversized.closed is True


class _SmtpClient:
    def __init__(self) -> None:
        self.login_call: tuple[str, str] | None = None
        self.message: EmailMessage | None = None
        self.quit_called = False

    def login(self, username: str, password: str) -> None:
        self.login_call = (username, password)

    def send_message(self, message: EmailMessage, *, from_addr: str, to_addrs: list[str]) -> None:
        assert from_addr == "reconforge@example.com"
        assert to_addrs == ["ops@example.com"]
        self.message = message

    def quit(self) -> None:
        self.quit_called = True


def test_email_transport_uses_allowlisted_pinned_smtps_and_plain_redacted_message() -> None:
    route = _route(NotificationChannel.EMAIL)
    request = _request(route)
    client = _SmtpClient()
    connected: list[tuple[str, int, str]] = []

    def factory(host: str, port: int, address: str, _timeout: float, _context: object) -> _SmtpClient:
        connected.append((host, port, address))
        return client

    transport = SmtpsEmailTransport(
        policy=_policy(),
        relay_host="mail.example.com",
        sender="reconforge@example.com",
        username="smtp-user",
        secret_resolver=_SecretResolver(),
        resolver=lambda host, port: ("93.184.216.35",),
        client_factory=factory,  # type: ignore[arg-type]
    )
    NotificationTransportRouter(email=transport).deliver(route, request)
    assert connected == [("mail.example.com", 465, "93.184.216.35")]
    assert client.login_call == ("smtp-user", "synthetic-secret-material-32-bytes")
    assert client.quit_called is True and client.message is not None
    text = client.message.get_content()
    assert request.durable_job_id in text
    assert "https://" not in text and "vault/" not in text
