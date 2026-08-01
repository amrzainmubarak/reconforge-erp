"""Backend-neutral approval and certification application boundary."""

from __future__ import annotations

from typing import Any, Protocol


class ApprovalRepositoryProtocol(Protocol):
    def submit(
        self,
        *,
        object_type: str,
        object_id: str,
        title: str,
        assigned_to: str,
        requested_by: str = "",
        reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def approve(
        self,
        approval_id: str,
        *,
        actor_label: str = "local-cli",
        reason: str = "",
        override_reason: str = "",
    ) -> dict[str, Any]: ...

    def reject(self, approval_id: str, *, actor_label: str = "local-cli", reason: str) -> dict[str, Any]: ...

    def prepare_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        period_name: str = "",
        entity_code: str = "",
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def review_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def list_requests(self, *, status: str = "") -> list[dict[str, Any]]: ...
    def list_certifications(self) -> list[dict[str, Any]]: ...
    def get(self, approval_id: str) -> dict[str, Any]: ...


class ApprovalApplicationService:
    """Expose approval use cases through a storage-neutral typed port."""

    def __init__(self, repository: ApprovalRepositoryProtocol) -> None:
        self.repository = repository

    def submit(
        self,
        *,
        object_type: str,
        object_id: str,
        title: str,
        assigned_to: str,
        requested_by: str = "",
        reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.submit(
            object_type=object_type,
            object_id=object_id,
            title=title,
            assigned_to=assigned_to,
            requested_by=requested_by,
            reason=reason,
            actor_label=actor_label,
        )

    def approve(
        self,
        approval_id: str,
        *,
        actor_label: str = "local-cli",
        reason: str = "",
        override_reason: str = "",
    ) -> dict[str, Any]:
        return self.repository.approve(
            approval_id, actor_label=actor_label, reason=reason, override_reason=override_reason
        )

    def reject(self, approval_id: str, *, actor_label: str = "local-cli", reason: str) -> dict[str, Any]:
        return self.repository.reject(approval_id, actor_label=actor_label, reason=reason)

    def prepare_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        period_name: str = "",
        entity_code: str = "",
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.prepare_certification(
            object_type=object_type,
            object_id=object_id,
            period_name=period_name,
            entity_code=entity_code,
            note=note,
            actor_label=actor_label,
        )

    def review_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.review_certification(
            object_type=object_type,
            object_id=object_id,
            note=note,
            actor_label=actor_label,
        )

    def list_requests(self, *, status: str = "") -> list[dict[str, Any]]:
        return self.repository.list_requests(status=status)

    def list_certifications(self) -> list[dict[str, Any]]:
        return self.repository.list_certifications()

    def get(self, approval_id: str) -> dict[str, Any]:
        return self.repository.get(approval_id)
