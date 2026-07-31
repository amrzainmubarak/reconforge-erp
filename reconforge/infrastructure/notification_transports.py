"""Pinned, allowlisted HTTPS and SMTPS notification transports.

The transports are optional and perform no network activity until explicitly
constructed with an enabled egress policy.  DNS answers are validated at send
time and the validated address is pinned to the TLS connection, preventing a
second resolver lookup from bypassing the SSRF decision.
"""

from __future__ import annotations

import hmac
import http.client
import ipaddress
import smtplib
import socket
import ssl
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, Protocol
from urllib.parse import urlsplit

from reconforge.application.notifications import (
    NotificationChannel,
    NotificationDeliveryError,
    NotificationEgressPolicy,
    NotificationRequest,
    NotificationRouteRecord,
    normalize_email_address,
)


class SecretResolverProtocol(Protocol):
    """Resolve secret bytes at send time; implementations must not log values."""

    def resolve(self, reference: str) -> bytes: ...


class DisabledSecretResolver:
    """Default resolver that proves secrets and network are opt-in."""

    def resolve(self, reference: str) -> bytes:
        del reference
        raise NotificationDeliveryError("Notification secret resolution is disabled.")


AddressResolver = Callable[[str, int], Iterable[str]]


def _system_resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise NotificationDeliveryError("Notification destination resolution failed.") from exc
    return tuple(str(answer[4][0]) for answer in answers)


def resolve_public_addresses(host: str, port: int, *, resolver: AddressResolver = _system_resolver) -> tuple[str, ...]:
    """Resolve once and reject any non-global answer before selecting an IP."""

    try:
        raw_addresses = tuple(resolver(host, port))
        addresses = tuple(sorted({ipaddress.ip_address(value) for value in raw_addresses}, key=lambda item: item.packed))
    except (TypeError, ValueError) as exc:
        raise NotificationDeliveryError("Notification destination resolution was invalid.") from exc
    if not addresses:
        raise NotificationDeliveryError("Notification destination resolution returned no addresses.")
    if any(not address.is_global for address in addresses):
        raise NotificationDeliveryError("Notification destination resolved to a non-public address.")
    return tuple(str(address) for address in addresses)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        pinned_address: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host=host, port=port, timeout=timeout, context=context)
        self._pinned_address = pinned_address
        self._create_connection = self._connect_pinned

    def _connect_pinned(
        self,
        _address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        return socket.create_connection(
            (self._pinned_address, self.port),
            timeout=timeout,
            source_address=source_address,
        )


WebhookConnectionFactory = Callable[[str, int, str, float, ssl.SSLContext], Any]


def _webhook_connection_factory(
    host: str,
    port: int,
    address: str,
    timeout: float,
    context: ssl.SSLContext,
) -> _PinnedHTTPSConnection:
    return _PinnedHTTPSConnection(host, port, pinned_address=address, timeout=timeout, context=context)


@dataclass(frozen=True)
class HttpsWebhookTransport:
    """Deliver signed JSON to one exact allowlisted HTTPS destination."""

    policy: NotificationEgressPolicy
    secret_resolver: SecretResolverProtocol = field(default_factory=DisabledSecretResolver)
    timeout_seconds: float = 10.0
    max_response_bytes: int = 65_536
    resolver: AddressResolver = field(default=_system_resolver, repr=False, compare=False)
    connection_factory: WebhookConnectionFactory = field(
        default=_webhook_connection_factory, repr=False, compare=False
    )
    tls_context: ssl.SSLContext = field(default_factory=ssl.create_default_context, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not 0 < float(self.timeout_seconds) <= 60:
            raise ValueError("Webhook timeout must be greater than zero and at most 60 seconds.")
        if not 1 <= int(self.max_response_bytes) <= 1_048_576:
            raise ValueError("Webhook response limit must be between 1 and 1048576 bytes.")

    def deliver(self, route: NotificationRouteRecord, request: NotificationRequest) -> None:
        if route.channel is not NotificationChannel.WEBHOOK:
            raise NotificationDeliveryError("Webhook transport received an incompatible route.")
        self.policy.assert_route_allowed(route)
        parsed = urlsplit(route.destination)
        host = parsed.hostname or ""
        port = parsed.port or 443
        addresses = resolve_public_addresses(host, port, resolver=self.resolver)
        secret = self.secret_resolver.resolve(route.registration.secret_ref)
        if not 16 <= len(secret) <= 4_096:
            raise NotificationDeliveryError("Webhook signing secret does not meet the configured bounds.")
        body = request.canonical_json()
        signature = hmac.new(secret, body, "sha256").hexdigest()
        connection = self.connection_factory(host, port, addresses[0], float(self.timeout_seconds), self.tls_context)
        try:
            connection.request(
                "POST",
                parsed.path or "/",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "ReconForge-Notification/1",
                    "Idempotency-Key": request.notification_id,
                    "X-ReconForge-Signature": f"v1={signature}",
                },
            )
            response = connection.getresponse()
            response_body = response.read(int(self.max_response_bytes) + 1)
            if len(response_body) > int(self.max_response_bytes):
                raise NotificationDeliveryError("Webhook response exceeded the configured bound.")
            if not 200 <= int(response.status) < 300:
                raise NotificationDeliveryError(
                    f"Webhook destination returned non-success status {int(response.status)}."
                )
        except NotificationDeliveryError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise NotificationDeliveryError("Webhook delivery failed safely.") from exc
        finally:
            connection.close()


class _PinnedSMTPSSL(smtplib.SMTP_SSL):
    def __init__(
        self,
        relay_host: str,
        relay_port: int,
        *,
        pinned_address: str,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        self._relay_host = relay_host
        self._pinned_address = pinned_address
        super().__init__(host="", port=0, timeout=timeout, context=context)
        self.connect(relay_host, relay_port)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        del host
        raw = socket.create_connection((self._pinned_address, port), timeout=timeout)
        return self.context.wrap_socket(raw, server_hostname=self._relay_host)


SmtpClientFactory = Callable[[str, int, str, float, ssl.SSLContext], Any]


def _smtp_client_factory(
    host: str,
    port: int,
    address: str,
    timeout: float,
    context: ssl.SSLContext,
) -> _PinnedSMTPSSL:
    return _PinnedSMTPSSL(host, port, pinned_address=address, timeout=timeout, context=context)


@dataclass(frozen=True)
class SmtpsEmailTransport:
    """Deliver one plain-text operational notice through an allowlisted SMTPS relay."""

    policy: NotificationEgressPolicy
    relay_host: str
    sender: str
    relay_port: int = 465
    username: str = ""
    secret_resolver: SecretResolverProtocol = field(default_factory=DisabledSecretResolver)
    timeout_seconds: float = 10.0
    resolver: AddressResolver = field(default=_system_resolver, repr=False, compare=False)
    client_factory: SmtpClientFactory = field(default=_smtp_client_factory, repr=False, compare=False)
    tls_context: ssl.SSLContext = field(default_factory=ssl.create_default_context, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sender", normalize_email_address(self.sender))
        if not str(self.relay_host or "").strip() or not 1 <= int(self.relay_port) <= 65_535:
            raise ValueError("SMTPS relay configuration is invalid.")
        if not 0 < float(self.timeout_seconds) <= 60:
            raise ValueError("SMTPS timeout must be greater than zero and at most 60 seconds.")
        self.policy.assert_smtp_relay_allowed(self.relay_host, self.relay_port)

    def deliver(self, route: NotificationRouteRecord, request: NotificationRequest) -> None:
        if route.channel is not NotificationChannel.EMAIL:
            raise NotificationDeliveryError("Email transport received an incompatible route.")
        self.policy.assert_route_allowed(route)
        addresses = resolve_public_addresses(
            self.relay_host, self.relay_port, resolver=self.resolver
        )
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = route.destination
        message["Subject"] = "ReconForge scheduled job dispatched"
        message["Message-ID"] = f"<{request.notification_id}@reconforge.invalid>"
        message.set_content(
            "\n".join(
                (
                    "A ReconForge schedule created a durable job.",
                    f"Notification: {request.notification_id}",
                    f"Schedule: {request.schedule_id} v{request.schedule_version}",
                    f"Scheduled for: {request.scheduled_for.isoformat(timespec='seconds')}",
                    f"Durable job: {request.durable_job_id}",
                    f"Workspace: {request.workspace_id}",
                    f"Entity: {request.entity_id or '-'}",
                )
            ),
            subtype="plain",
            charset="utf-8",
        )
        client = self.client_factory(
            self.relay_host,
            self.relay_port,
            addresses[0],
            float(self.timeout_seconds),
            self.tls_context,
        )
        try:
            if self.username:
                password = self.secret_resolver.resolve(route.registration.secret_ref)
                if not 1 <= len(password) <= 4_096:
                    raise NotificationDeliveryError("SMTP credential does not meet the configured bounds.")
                try:
                    password_text = password.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise NotificationDeliveryError("SMTP credential encoding is invalid.") from exc
                client.login(self.username, password_text)
            client.send_message(message, from_addr=self.sender, to_addrs=[route.destination])
        except NotificationDeliveryError:
            raise
        except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
            raise NotificationDeliveryError("Email delivery failed safely.") from exc
        finally:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                client.close()


@dataclass(frozen=True)
class NotificationTransportRouter:
    webhook: HttpsWebhookTransport | None = None
    email: SmtpsEmailTransport | None = None

    def deliver(self, route: NotificationRouteRecord, request: NotificationRequest) -> None:
        if route.channel is NotificationChannel.WEBHOOK:
            if self.webhook is None:
                raise NotificationDeliveryError("Webhook delivery is not configured.")
            self.webhook.deliver(route, request)
            return
        if self.email is None:
            raise NotificationDeliveryError("Email delivery is not configured.")
        self.email.deliver(route, request)


__all__ = [
    "DisabledSecretResolver",
    "HttpsWebhookTransport",
    "NotificationTransportRouter",
    "SecretResolverProtocol",
    "SmtpsEmailTransport",
    "resolve_public_addresses",
]
