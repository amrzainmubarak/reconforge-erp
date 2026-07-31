"""Backend-neutral approval application contract tests."""

from __future__ import annotations

from typing import cast
from unittest.mock import Mock

from reconforge.application.approvals import (
    ApprovalApplicationService,
    ApprovalRepositoryProtocol,
)


def test_approval_application_service_delegates_complete_public_contract() -> None:
    repository = Mock()
    repository.submit.return_value = {"id": "APR-1", "status": "Submitted"}
    repository.approve.return_value = {"id": "APR-1", "status": "Approved"}
    repository.reject.return_value = {"id": "APR-2", "status": "Rejected"}
    repository.prepare_certification.return_value = {"id": "CERT-1", "status": "Prepared"}
    repository.review_certification.return_value = {"id": "CERT-1", "status": "Reviewed"}
    repository.list_requests.return_value = [{"id": "APR-1"}]
    repository.list_certifications.return_value = [{"id": "CERT-1"}]
    repository.get.return_value = {"id": "APR-1"}
    service = ApprovalApplicationService(cast(ApprovalRepositoryProtocol, repository))

    assert service.submit(
        object_type="close_period", object_id="P-1", title="Review",
        assigned_to="reviewer", requested_by="preparer", actor_label="preparer",
    )["status"] == "Submitted"
    assert service.approve("APR-1", actor_label="reviewer", reason="checked")["status"] == "Approved"
    assert service.reject("APR-2", actor_label="reviewer", reason="invalid")["status"] == "Rejected"
    assert service.prepare_certification(
        object_type="close_period", object_id="P-1", period_name="2026-07",
        actor_label="preparer",
    )["status"] == "Prepared"
    assert service.review_certification(
        object_type="close_period", object_id="P-1", actor_label="reviewer"
    )["status"] == "Reviewed"
    assert service.list_requests(status="Submitted") == [{"id": "APR-1"}]
    assert service.list_certifications() == [{"id": "CERT-1"}]
    assert service.get("APR-1") == {"id": "APR-1"}

    repository.submit.assert_called_once_with(
        object_type="close_period", object_id="P-1", title="Review",
        assigned_to="reviewer", requested_by="preparer", reason="",
        actor_label="preparer",
    )
    repository.approve.assert_called_once_with(
        "APR-1", actor_label="reviewer", reason="checked", override_reason=""
    )
