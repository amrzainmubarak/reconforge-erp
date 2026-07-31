"""Safe, provider-neutral contracts for optional operational notifications.

Notification payloads deliberately contain only bounded control-plane
identifiers and timestamps.  Raw financial rows, amounts, free-form text, and
transport credentials are outside this contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit


class NotificationError(ValueError):
    """Raised for safe notification validation and policy failures."""


class NotificationDeliveryError(RuntimeError):
    """A retryable delivery failure whose message is safe to persist."""


class NotificationChannel(StrEnum):
    WEBHOOK = "webhook"
    EMAIL = "email"


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SECRET_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_LOCAL_PART = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_NOTIFICATION_EVENT_TYPE = "notification.scheduler_dispatch.v1"
_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "notification_id",
        "route_id",
        "route_version",
        "destination_digest",
        "workspace_id",
        "entity_id",
        "schedule_id",
        "schedule_version",
        "dispatch_key",
        "scheduled_for",
        "durable_job_id",
    }
)


def _identifier(value: object, field_name: str, *, optional: bool = False) -> str:
    normalized = str(value or "").strip()
    if optional and not normalized:
        return ""
    if not _IDENTIFIER.fullmatch(normalized):
        raise NotificationError(f"{field_name} is invalid or exceeds 160 characters.")
    return normalized


def _secret_reference(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized and not _SECRET_REFERENCE.fullmatch(normalized):
        raise NotificationError("secret_ref is invalid or exceeds 256 characters.")
    return normalized


def _domain(value: object, field_name: str) -> str:
    raw = str(value or "").strip().rstrip(".")
    if not raw or len(raw) > 253 or any(ord(character) < 33 for character in raw):
        raise NotificationError(f"{field_name} is invalid.")
    try:
        normalized = raw.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise NotificationError(f"{field_name} is invalid.") from exc
    labels = normalized.split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in labels
    ):
        raise NotificationError(f"{field_name} is invalid.")
    return normalized


def normalize_email_address(value: object) -> str:
    """Return a conservative mailbox form without display names or controls."""

    raw = str(value or "").strip()
    if len(raw) > 254 or raw.count("@") != 1 or any(ord(character) < 33 for character in raw):
        raise NotificationError("Email destination is invalid.")
    local, raw_domain = raw.rsplit("@", 1)
    if not _LOCAL_PART.fullmatch(local) or local.startswith(".") or local.endswith(".") or ".." in local:
        raise NotificationError("Email destination is invalid.")
    return f"{local}@{_domain(raw_domain, 'Email destination domain')}"


def normalize_webhook_url(value: object) -> str:
    """Return an exact HTTPS URL with credentials, query, and fragment forbidden."""

    raw = str(value or "").strip()
    if not raw or len(raw) > 2_048 or any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise NotificationError("Webhook destination is invalid.")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise NotificationError("Webhook destination is invalid.") from exc
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise NotificationError("Webhook destinations require HTTPS and a hostname.")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise NotificationError("Webhook credentials, query strings, and fragments are forbidden.")
    host = _domain(parsed.hostname, "Webhook hostname")
    selected_port = 443 if port is None else port
    if not 1 <= selected_port <= 65_535:
        raise NotificationError("Webhook port is invalid.")
    path = parsed.path or "/"
    if not path.startswith("/") or "\\" in path or len(path) > 1_024:
        raise NotificationError("Webhook path is invalid.")
    netloc = host if selected_port == 443 else f"{host}:{selected_port}"
    return urlunsplit(SplitResult("https", netloc, path, "", ""))


def destination_digest(channel: NotificationChannel, destination: str) -> str:
    canonical = f"{channel.value}\n{destination}".encode()
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class NotificationEgressPolicy:
    """Closed, default-deny egress allowlist supplied by the deployment."""

    enabled: bool = False
    webhook_urls: frozenset[str] = frozenset()
    email_domains: frozenset[str] = frozenset()
    smtp_relays: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "webhook_urls",
            frozenset(normalize_webhook_url(value) for value in self.webhook_urls),
        )
        object.__setattr__(
            self,
            "email_domains",
            frozenset(_domain(value, "Email allowlist domain") for value in self.email_domains),
        )
        normalized_relays: set[str] = set()
        for value in self.smtp_relays:
            raw = str(value or "").strip()
            try:
                parsed = urlsplit(raw)
                port = parsed.port
            except ValueError as exc:
                raise NotificationError("SMTP relay allowlist entry is invalid.") from exc
            if (
                parsed.scheme.casefold() != "smtps"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                raise NotificationError("SMTP relays require exact smtps://host:port entries.")
            selected_port = 465 if port is None else port
            if not 1 <= selected_port <= 65_535:
                raise NotificationError("SMTP relay port is invalid.")
            normalized_relays.add(f"smtps://{_domain(parsed.hostname, 'SMTP relay hostname')}:{selected_port}")
        object.__setattr__(self, "smtp_relays", frozenset(normalized_relays))

    def assert_route_allowed(self, route: NotificationRouteRegistration | NotificationRouteRecord) -> None:
        if not self.enabled:
            raise NotificationError("Notification egress is disabled.")
        if route.channel is NotificationChannel.WEBHOOK:
            if route.destination not in self.webhook_urls:
                raise NotificationError("Webhook destination is not allowlisted.")
            return
        domain = route.destination.rsplit("@", 1)[1]
        if domain not in self.email_domains:
            raise NotificationError("Email destination domain is not allowlisted.")

    def assert_smtp_relay_allowed(self, host: str, port: int) -> None:
        if not self.enabled:
            raise NotificationError("Notification egress is disabled.")
        relay = f"smtps://{_domain(host, 'SMTP relay hostname')}:{int(port)}"
        if relay not in self.smtp_relays:
            raise NotificationError("SMTP relay is not allowlisted.")


@dataclass(frozen=True)
class NotificationRouteRegistration:
    """Immutable versioned route registration; secret material is never accepted."""

    tenant_id: str
    workspace_id: str
    entity_id: str
    route_id: str
    version: int
    channel: NotificationChannel
    destination: str
    secret_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _identifier(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "workspace_id", _identifier(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "entity_id", _identifier(self.entity_id, "entity_id", optional=True))
        object.__setattr__(self, "route_id", _identifier(self.route_id, "route_id"))
        if not 1 <= int(self.version) <= 2_147_483_647:
            raise NotificationError("route version must be between 1 and 2147483647.")
        object.__setattr__(self, "version", int(self.version))
        channel = NotificationChannel(self.channel)
        object.__setattr__(self, "channel", channel)
        normalized_destination = (
            normalize_webhook_url(self.destination)
            if channel is NotificationChannel.WEBHOOK
            else normalize_email_address(self.destination)
        )
        object.__setattr__(self, "destination", normalized_destination)
        object.__setattr__(self, "secret_ref", _secret_reference(self.secret_ref))
        if channel is NotificationChannel.WEBHOOK and not self.secret_ref:
            raise NotificationError("Webhook routes require a signing secret reference.")

    @property
    def destination_digest(self) -> str:
        return destination_digest(self.channel, self.destination)


@dataclass(frozen=True)
class NotificationRouteRecord:
    registration: NotificationRouteRegistration
    enabled: bool
    created_by: str
    created_at: datetime

    @property
    def channel(self) -> NotificationChannel:
        return self.registration.channel

    @property
    def destination(self) -> str:
        return self.registration.destination


@dataclass(frozen=True)
class NotificationRequest:
    """Closed redacted envelope emitted atomically with a schedule dispatch."""

    tenant_id: str
    notification_id: str
    route_id: str
    route_version: int
    destination_digest: str
    workspace_id: str
    entity_id: str
    schedule_id: str
    schedule_version: int
    dispatch_key: str
    scheduled_for: datetime
    durable_job_id: str

    def __post_init__(self) -> None:
        for name in ("tenant_id", "notification_id", "route_id", "workspace_id", "schedule_id", "durable_job_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "entity_id", _identifier(self.entity_id, "entity_id", optional=True))
        if not 1 <= int(self.route_version) <= 2_147_483_647:
            raise NotificationError("route_version is invalid.")
        if not 1 <= int(self.schedule_version) <= 2_147_483_647:
            raise NotificationError("schedule_version is invalid.")
        if not _DIGEST.fullmatch(self.destination_digest):
            raise NotificationError("destination_digest must be a lowercase SHA-256 digest.")
        if not _DIGEST.fullmatch(self.dispatch_key):
            raise NotificationError("dispatch_key must be a lowercase SHA-256 digest.")
        if self.scheduled_for.tzinfo is None or self.scheduled_for.utcoffset() is None or self.scheduled_for.microsecond:
            raise NotificationError("scheduled_for must be a whole-second timezone-aware timestamp.")
        object.__setattr__(self, "scheduled_for", self.scheduled_for.astimezone(UTC))

    @classmethod
    def from_outbox_event(cls, event: NotificationOutboxEvent) -> NotificationRequest:
        if str(event.event_type) != _NOTIFICATION_EVENT_TYPE:
            raise NotificationError("Outbox event is not a supported notification request.")
        payload = event.payload
        if not isinstance(payload, dict) or frozenset(payload) != _PAYLOAD_KEYS:
            raise NotificationError("Notification payload shape is invalid.")
        if payload.get("schema_version") != "reconforge.notification.v1":
            raise NotificationError("Notification payload schema version is unsupported.")
        try:
            scheduled_for = datetime.fromisoformat(str(payload["scheduled_for"]).replace("Z", "+00:00"))
            request = cls(
                tenant_id=event.tenant_id,
                notification_id=payload["notification_id"],
                route_id=payload["route_id"],
                route_version=int(payload["route_version"]),
                destination_digest=payload["destination_digest"],
                workspace_id=payload["workspace_id"],
                entity_id=payload["entity_id"],
                schedule_id=payload["schedule_id"],
                schedule_version=int(payload["schedule_version"]),
                dispatch_key=payload["dispatch_key"],
                scheduled_for=scheduled_for,
                durable_job_id=payload["durable_job_id"],
            )
        except (KeyError, TypeError, ValueError, NotificationError) as exc:
            raise NotificationError("Notification payload values are invalid.") from exc
        if request.notification_id != str(event.id):
            raise NotificationError("Notification payload identity does not match its outbox event.")
        return request

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": "reconforge.notification.v1",
            "notification_id": self.notification_id,
            "route_id": self.route_id,
            "route_version": self.route_version,
            "destination_digest": self.destination_digest,
            "workspace_id": self.workspace_id,
            "entity_id": self.entity_id,
            "schedule_id": self.schedule_id,
            "schedule_version": self.schedule_version,
            "dispatch_key": self.dispatch_key,
            "scheduled_for": self.scheduled_for.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "durable_job_id": self.durable_job_id,
        }

    def canonical_json(self) -> bytes:
        return json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")


class NotificationOutboxEvent(Protocol):
    tenant_id: str
    id: str
    event_type: str
    payload: dict[str, Any]


class NotificationRouteRepositoryProtocol(Protocol):
    def register(
        self, registration: NotificationRouteRegistration, *, actor_id: str
    ) -> tuple[NotificationRouteRecord, bool]: ...

    def subscribe_schedule(
        self,
        *,
        tenant_id: str,
        schedule_id: str,
        schedule_version: int,
        route_id: str,
        route_version: int,
        actor_id: str,
    ) -> bool: ...


class NotificationRouteResolverProtocol(Protocol):
    def resolve(self, request: NotificationRequest) -> NotificationRouteRecord: ...


class NotificationTransportProtocol(Protocol):
    def deliver(self, route: NotificationRouteRecord, request: NotificationRequest) -> None: ...


class NotificationApplicationService:
    """Register allowlisted routes and explicit schedule subscriptions."""

    def __init__(self, repository: NotificationRouteRepositoryProtocol, *, policy: NotificationEgressPolicy) -> None:
        self.repository = repository
        self.policy = policy

    def register_route(
        self, registration: NotificationRouteRegistration, *, actor_id: str
    ) -> tuple[NotificationRouteRecord, bool]:
        self.policy.assert_route_allowed(registration)
        return self.repository.register(registration, actor_id=_identifier(actor_id, "actor_id"))

    def subscribe_schedule(
        self,
        *,
        tenant_id: str,
        schedule_id: str,
        schedule_version: int,
        route_id: str,
        route_version: int,
        actor_id: str,
    ) -> bool:
        if not 1 <= int(schedule_version) <= 2_147_483_647 or not 1 <= int(route_version) <= 2_147_483_647:
            raise NotificationError("Schedule and route versions must be positive integers.")
        return self.repository.subscribe_schedule(
            tenant_id=_identifier(tenant_id, "tenant_id"),
            schedule_id=_identifier(schedule_id, "schedule_id"),
            schedule_version=int(schedule_version),
            route_id=_identifier(route_id, "route_id"),
            route_version=int(route_version),
            actor_id=_identifier(actor_id, "actor_id"),
        )


class NotificationOutboxPublisher:
    """Resolve and deliver one notification while rechecking runtime policy."""

    def __init__(
        self,
        *,
        resolver: NotificationRouteResolverProtocol,
        transport: NotificationTransportProtocol,
        policy: NotificationEgressPolicy,
    ) -> None:
        self.resolver = resolver
        self.transport = transport
        self.policy = policy

    def publish(self, event: NotificationOutboxEvent) -> None:
        request = NotificationRequest.from_outbox_event(event)
        route = self.resolver.resolve(request)
        self.policy.assert_route_allowed(route)
        if route.registration.destination_digest != request.destination_digest:
            raise NotificationDeliveryError("Notification destination binding changed.")
        try:
            self.transport.deliver(route, request)
        except NotificationDeliveryError:
            raise
        except Exception as exc:
            raise NotificationDeliveryError("Notification transport failed safely.") from exc


class OutboxPublisherRouter:
    """Route notification events without consuming unrelated domain events."""

    def __init__(self, *, notification_publisher: NotificationOutboxPublisher, default_publisher: Any) -> None:
        if default_publisher is None:
            raise NotificationError("A default outbox publisher is required.")
        self.notification_publisher = notification_publisher
        self.default_publisher = default_publisher

    def publish(self, event: NotificationOutboxEvent) -> None:
        if str(event.event_type) == _NOTIFICATION_EVENT_TYPE:
            self.notification_publisher.publish(event)
            return
        if callable(self.default_publisher):
            self.default_publisher(event)
        else:
            self.default_publisher.publish(event)


__all__ = [
    "NotificationApplicationService",
    "NotificationChannel",
    "NotificationDeliveryError",
    "NotificationEgressPolicy",
    "NotificationError",
    "NotificationOutboxPublisher",
    "NotificationRequest",
    "NotificationRouteRecord",
    "NotificationRouteRegistration",
    "OutboxPublisherRouter",
    "destination_digest",
    "normalize_email_address",
    "normalize_webhook_url",
]
