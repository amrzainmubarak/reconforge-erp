"""Backend-neutral notification inbox use cases; transport egress is separate."""

from __future__ import annotations

from typing import Protocol

from reconforge.domain.notification_inbox import (
    InboxError,
    InboxNotification,
    InboxPage,
    InboxPublication,
    InboxScope,
    inbox_identifier,
)


class InboxRepository(Protocol):
    def workspaces(self, tenant_id: str, actor_id: str) -> tuple[str, ...]: ...

    def publish(self, publication: InboxPublication, publisher_id: str) -> tuple[InboxNotification, bool]: ...

    def page(
        self, scope: InboxScope, recipient_id: str, *, unread_only: bool, limit: int, offset: int
    ) -> InboxPage: ...

    def acknowledge(self, scope: InboxScope, recipient_id: str, notification_id: str) -> InboxNotification: ...


class NotificationInboxService:
    def __init__(self, repository: InboxRepository) -> None:
        self.repository = repository

    def workspaces(self, tenant_id: str, *, actor_id: str) -> tuple[str, ...]:
        return self.repository.workspaces(inbox_identifier(tenant_id, "tenant_id"), inbox_identifier(actor_id, "actor_id"))

    def publish(self, publication: InboxPublication, *, actor_id: str) -> tuple[InboxNotification, bool]:
        return self.repository.publish(publication, inbox_identifier(actor_id, "actor_id"))

    def page(
        self,
        scope: InboxScope,
        *,
        actor_id: str,
        unread_only: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> InboxPage:
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 100_000:
            raise InboxError("Inbox pagination is outside its supported bounds.")
        return self.repository.page(
            scope, inbox_identifier(actor_id, "actor_id"), unread_only=unread_only, limit=limit, offset=offset
        )

    def acknowledge(self, scope: InboxScope, *, actor_id: str, notification_id: str) -> InboxNotification:
        return self.repository.acknowledge(
            scope,
            inbox_identifier(actor_id, "actor_id"),
            inbox_identifier(notification_id, "notification_id"),
        )
