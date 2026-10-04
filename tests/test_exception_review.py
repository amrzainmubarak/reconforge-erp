"""Pure invariant and application-boundary tests for governed exception review."""

from __future__ import annotations

from typing import Any

import pytest

from reconforge.application.exception_review import ExceptionReviewApplicationService
from reconforge.domain.exception_review import (
    ExceptionReviewAssignment,
    ExceptionReviewConflictError,
    ExceptionReviewError,
    ExceptionReviewQuery,
    ExceptionReviewScope,
    ExceptionReviewSeparationError,
    ExceptionReviewTransition,
)


def _record(*, status: str = "In Review", version: int = 3, creator: str = "maker-user") -> dict[str, object]:
    return {
        "id": "EXQ-1",
        "row_version": version,
        "status": status,
        "created_by": creator,
        "owner": "reviewer-user",
    }


def test_governed_exception_review_enforces_versions_workflow_and_maker_checker() -> None:
    command = ExceptionReviewTransition(
        exception_id="EXQ-1",
        status="Resolved",
        expected_version=3,
        actor_id="reviewer-user",
        actor_label="reviewer",
        reason="Evidence was reconciled.",
    )
    command.validate_record(_record())

    with pytest.raises(ExceptionReviewConflictError, match="changed"):
        command.validate_record(_record(version=4))
    with pytest.raises(ExceptionReviewConflictError, match="Invalid governed"):
        command.validate_record(_record(status="Open"))
    with pytest.raises(ExceptionReviewSeparationError, match="creator"):
        ExceptionReviewTransition(
            exception_id="EXQ-1",
            status="Resolved",
            expected_version=3,
            actor_id="maker-user",
            actor_label="maker",
        ).validate_record(_record())
    with pytest.raises(ExceptionReviewError, match="requires a review reason"):
        ExceptionReviewTransition(
            exception_id="EXQ-1",
            status="Accepted Risk",
            expected_version=3,
            actor_id="reviewer-user",
            actor_label="reviewer",
        ).validate_record(_record())
    with pytest.raises(ExceptionReviewSeparationError, match="assigned"):
        ExceptionReviewAssignment(
            exception_id="EXQ-1",
            owner="maker-user",
            expected_version=3,
            actor_id="reviewer-user",
            actor_label="reviewer",
        ).validate_record(_record())


class _ReviewRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object | None]] = []

    def list_for_review(self, scope: ExceptionReviewScope, query: ExceptionReviewQuery) -> list[dict[str, Any]]:
        self.calls.append(("list", scope, query))
        return [{"id": "EXQ-1"}]

    def get_for_review(self, scope: ExceptionReviewScope, exception_id: str) -> dict[str, Any]:
        self.calls.append(("get", scope, exception_id))
        return {"id": exception_id}

    def assign_for_review(
        self,
        scope: ExceptionReviewScope,
        command: ExceptionReviewAssignment,
    ) -> dict[str, Any]:
        self.calls.append(("assign", scope, command))
        return {"id": command.exception_id}

    def transition_for_review(
        self,
        scope: ExceptionReviewScope,
        command: ExceptionReviewTransition,
    ) -> dict[str, Any]:
        self.calls.append(("transition", scope, command))
        return {"id": command.exception_id}


def test_exception_review_application_service_only_forwards_typed_scope_and_commands() -> None:
    repository = _ReviewRepository()
    service = ExceptionReviewApplicationService(repository)
    scope = ExceptionReviewScope(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        organization_id="organization-a",
        legal_entity_id="entity-a",
    )
    query = ExceptionReviewQuery(status="Open")
    assignment = ExceptionReviewAssignment(
        exception_id="EXQ-1",
        owner="reviewer-user",
        expected_version=1,
        actor_id="manager-user",
        actor_label="manager",
    )
    transition = ExceptionReviewTransition(
        exception_id="EXQ-1",
        status="In Review",
        expected_version=2,
        actor_id="manager-user",
        actor_label="manager",
    )

    assert service.list(scope, query) == [{"id": "EXQ-1"}]
    assert service.get(scope, "EXQ-1") == {"id": "EXQ-1"}
    assert service.assign(scope, assignment) == {"id": "EXQ-1"}
    assert service.transition(scope, transition) == {"id": "EXQ-1"}
    assert repository.calls == [
        ("list", scope, query),
        ("get", scope, "EXQ-1"),
        ("assign", scope, assignment),
        ("transition", scope, transition),
    ]
