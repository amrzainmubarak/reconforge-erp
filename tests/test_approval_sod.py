from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.db import connect, run_migrations
from reconforge.platform.approvals import ApprovalService
from reconforge.platform.common import PlatformError


def _service(tmp_path: Path) -> tuple[ApprovalService, object]:
    database = tmp_path / "approval.db"
    run_migrations(database)
    connection = connect(database, require_exists=True)
    return ApprovalService(connection), connection


@pytest.mark.parametrize("override_reason", ["", "emergency", "manager approved"])
def test_requester_cannot_approve_own_request_with_or_without_override(
    tmp_path: Path,
    override_reason: str,
) -> None:
    service, connection = _service(tmp_path)
    try:
        request = service.submit(
            object_type="close_period",
            object_id="PERIOD-1",
            title="Close approval",
            assigned_to="controller",
            requested_by="controller",
            actor_label="controller",
        )

        with pytest.raises(PlatformError, match="requester cannot approve their own request"):
            service.approve(
                str(request["id"]),
                actor_label="controller",
                override_reason=override_reason,
            )

        assert service.get(str(request["id"]))["status"] == "Submitted"
    finally:
        connection.close()  # type: ignore[union-attr]


def test_non_requester_can_approve_without_override_and_override_is_rejected(tmp_path: Path) -> None:
    service, connection = _service(tmp_path)
    try:
        request = service.submit(
            object_type="close_period",
            object_id="PERIOD-2",
            title="Close approval",
            assigned_to="reviewer",
            requested_by="preparer",
            actor_label="preparer",
        )
        approval_id = str(request["id"])

        with pytest.raises(PlatformError, match="overrides are not permitted"):
            service.approve(approval_id, actor_label="reviewer", override_reason="emergency")
        assert service.get(approval_id)["status"] == "Submitted"

        approved = service.approve(approval_id, actor_label="reviewer", reason="Evidence reviewed")
        assert approved["status"] == "Approved"
        assert approved["decided_by"] == "reviewer"
        assert approved["override_reason"] == ""
    finally:
        connection.close()  # type: ignore[union-attr]


def test_requester_may_reject_own_request_with_required_reason(tmp_path: Path) -> None:
    service, connection = _service(tmp_path)
    try:
        request = service.submit(
            object_type="close_period",
            object_id="PERIOD-3",
            title="Close approval",
            assigned_to="controller",
            requested_by="controller",
            actor_label="controller",
        )
        rejected = service.reject(
            str(request["id"]),
            actor_label="controller",
            reason="Withdrawn by requester",
        )
        assert rejected["status"] == "Rejected"
    finally:
        connection.close()  # type: ignore[union-attr]
