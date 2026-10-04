"""Pure invariant and application-boundary tests for governed exception review."""

from __future__ import annotations

from typing import Any

import pytest

from reconforge.application.exception_review import ExceptionReviewApplicationService
from reconforge.domain.exception_review import (
    ExceptionReviewAssigneeError,
    ExceptionReviewAssignment,
    ExceptionReviewConflictError,
    ExceptionReviewCreatorIdentityError,
    ExceptionReviewError,
    ExceptionReviewHistoryPage,
    ExceptionReviewListPage,
    ExceptionReviewQuery,
    ExceptionReviewScope,
    ExceptionReviewSeparationError,
    ExceptionReviewTransition,
)


def _record(
    *,
    status: str = "In Review",
    version: int = 3,
    creator: str = "maker-user",
    creator_actor_id: str | None = "maker-user",
    owner: str = "reviewer-user",
) -> dict[str, object]:
    return {
        "id": "EXQ-1",
        "row_version": version,
        "status": status,
        "created_by": creator,
        "created_by_actor_id": creator_actor_id,
        "owner": owner,
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


def test_governed_review_uses_immutable_creator_ids_and_fails_closed_for_legacy_labels() -> None:
    changed_label = _record(creator="maker-renamed", creator_actor_id="maker-user")
    with pytest.raises(ExceptionReviewSeparationError, match="creator"):
        ExceptionReviewTransition(
            exception_id="EXQ-1",
            status="Resolved",
            expected_version=3,
            actor_id="maker-user",
            actor_label="maker-renamed",
        ).validate_record(changed_label)

    with pytest.raises(ExceptionReviewCreatorIdentityError, match="immutable creator identity"):
        ExceptionReviewAssignment(
            exception_id="EXQ-1",
            owner="reviewer-user",
            expected_version=3,
            actor_id="manager-user",
            actor_label="manager",
        ).validate_record(_record(creator_actor_id=None))
    with pytest.raises(ExceptionReviewCreatorIdentityError, match="immutable creator identity"):
        ExceptionReviewTransition(
            exception_id="EXQ-1",
            status="Resolved",
            expected_version=3,
            actor_id="reviewer-user",
            actor_label="reviewer",
        ).validate_record(_record(creator_actor_id=None))
    with pytest.raises(ExceptionReviewAssigneeError, match="assigned reviewer"):
        ExceptionReviewTransition(
            exception_id="EXQ-1",
            status="Resolved",
            expected_version=3,
            actor_id="other-reviewer",
            actor_label="other-reviewer",
        ).validate_record(_record())
    with pytest.raises(ExceptionReviewConflictError, match="Closed"):
        ExceptionReviewAssignment(
            exception_id="EXQ-1",
            owner="reviewer-user",
            expected_version=3,
            actor_id="manager-user",
            actor_label="manager",
        ).validate_record(_record(status="Closed"))


def test_governed_review_query_and_history_page_validate_boundaries() -> None:
    with pytest.raises(ExceptionReviewError, match="Risk rating"):
        ExceptionReviewQuery(risk_rating="urgent")
    with pytest.raises(ExceptionReviewError, match="status"):
        ExceptionReviewQuery(status="Archived")
    with pytest.raises(ExceptionReviewError, match="1 through 250"):
        ExceptionReviewHistoryPage(limit=0)
    with pytest.raises(ExceptionReviewError, match="1 through 250"):
        ExceptionReviewListPage(limit=251)
    assert ExceptionReviewHistoryPage(limit=2, cursor="EXH-2").cursor == "EXH-2"


class _ReviewRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object | None]] = []

    def list_for_review(self, scope: ExceptionReviewScope, query: ExceptionReviewQuery) -> list[dict[str, Any]]:
        self.calls.append(("list", scope, query))
        return [{"id": "EXQ-1"}]

    def list_page_for_review(
        self,
        scope: ExceptionReviewScope,
        query: ExceptionReviewQuery,
        page: ExceptionReviewListPage,
    ) -> dict[str, Any]:
        self.calls.append(("list_page", scope, (query, page)))
        return {"records": [{"id": "EXQ-1"}], "pagination": {"limit": page.limit}}

    def get_for_review(
        self,
        scope: ExceptionReviewScope,
        exception_id: str,
        history_page: ExceptionReviewHistoryPage,
    ) -> dict[str, Any]:
        self.calls.append(("get", scope, (exception_id, history_page)))
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
    assert service.list_page(scope, query, ExceptionReviewListPage(limit=2)) == {
        "records": [{"id": "EXQ-1"}],
        "pagination": {"limit": 2},
    }
    assert service.get(scope, "EXQ-1") == {"id": "EXQ-1"}
    assert service.assign(scope, assignment) == {"id": "EXQ-1"}
    assert service.transition(scope, transition) == {"id": "EXQ-1"}
    assert repository.calls == [
        ("list", scope, query),
        ("list_page", scope, (query, ExceptionReviewListPage(limit=2))),
        ("get", scope, ("EXQ-1", ExceptionReviewHistoryPage())),
        ("assign", scope, assignment),
        ("transition", scope, transition),
    ]
