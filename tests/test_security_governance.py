from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from reconforge.application.security_governance import (
    EvidenceRetentionChange,
    IntegrationDisableChange,
    IntegrationPage,
    IntegrationSummary,
    RetentionPolicyChange,
    RetentionPolicyPage,
    RetentionPolicySummary,
    SecurityGovernanceApplicationService,
    SecurityGovernanceError,
)


def _integration() -> IntegrationSummary:
    return IntegrationSummary(
        "service_account",
        "svc-worker",
        "active",
        1,
        2,
        1,
        "2026-07-30T00:00:00Z",
        None,
        None,
        "a" * 64,
        "b" * 64,
    )


def _policy() -> RetentionPolicySummary:
    return RetentionPolicySummary(
        "rtp-" + "a" * 32,
        "audit-evidence",
        "Audit evidence",
        "restricted",
        365,
        True,
        1,
        "2026-07-30T00:00:00Z",
        "2026-07-30T00:00:00Z",
        None,
        "c" * 64,
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_integrations(self, **kwargs: Any) -> IntegrationPage:
        self.calls.append(("list_integrations", kwargs))
        return IntegrationPage((_integration(),), "service_account", "svc-worker")

    def disable_integration(self, **kwargs: Any) -> IntegrationDisableChange:
        self.calls.append(("disable_integration", kwargs))
        return IntegrationDisableChange(_integration(), True, 1, "AE-1")

    def list_retention_policies(self, **kwargs: Any) -> RetentionPolicyPage:
        self.calls.append(("list_retention_policies", kwargs))
        return RetentionPolicyPage((_policy(),), "audit-evidence", "rtp-" + "a" * 32)

    def create_retention_policy(self, **kwargs: Any) -> RetentionPolicyChange:
        self.calls.append(("create_retention_policy", kwargs))
        return RetentionPolicyChange(_policy(), True, "AE-2")

    def update_retention_policy(self, **kwargs: Any) -> RetentionPolicyChange:
        self.calls.append(("update_retention_policy", kwargs))
        return RetentionPolicyChange(_policy(), True, "AE-3")

    def apply_retention_policy(self, **kwargs: Any) -> EvidenceRetentionChange:
        self.calls.append(("apply_retention_policy", kwargs))
        return EvidenceRetentionChange(
            "evidence-1",
            "rtp-" + "a" * 32,
            1,
            2,
            None,
            "2027-07-30T00:00:00Z",
            "2027-07-30T00:00:00Z",
            True,
            True,
            "AE-4",
            "d" * 64,
        )


def test_security_governance_application_normalizes_every_effect_before_repository_access() -> None:
    repository = _Repository()
    service = SecurityGovernanceApplicationService(
        repository,
        clock=lambda: datetime(2026, 7, 30, tzinfo=UTC),
    )

    service.list_integrations(limit=20, include_inactive=True)
    service.disable_integration(
        actor_user_id="user-admin",
        kind="SERVICE_ACCOUNT",
        integration_id="svc-worker",
        expected_state_digest="B" * 64,
        reason_code="SECURITY_RESPONSE",
    )
    service.list_retention_policies(limit=20, include_retired=True)
    service.create_retention_policy(
        actor_user_id="user-admin",
        name="AUDIT-EVIDENCE",
        description=" Audit evidence ",
        data_classification="RESTRICTED",
        duration_days=365,
    )
    service.update_retention_policy(
        actor_user_id="user-admin",
        policy_id="rtp-" + "a" * 32,
        expected_lifecycle_version=1,
        reason_code="POLICY_CHANGE",
        duration_days=730,
    )
    service.apply_retention_policy(
        actor_user_id="user-admin",
        policy_id="rtp-" + "a" * 32,
        evidence_id="evidence-1",
        expected_retention_version=1,
        reason_code="POLICY_APPLICATION",
    )

    assert repository.calls[0][1]["as_of"] == datetime(2026, 7, 30, tzinfo=UTC)
    assert repository.calls[1][1]["kind"] == "service_account"
    assert repository.calls[1][1]["expected_state_digest"] == "b" * 64
    assert repository.calls[3][1]["name"] == "audit-evidence"
    assert repository.calls[3][1]["description"] == "Audit evidence"
    assert repository.calls[4][1]["duration_days"] == 730


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        (lambda service: service.list_integrations(limit=0), "security_governance_page_limit_invalid"),
        (
            lambda service: service.disable_integration(
                actor_user_id="admin",
                kind="unknown",
                integration_id="target",
                expected_state_digest="a" * 64,
                reason_code="policy_change",
            ),
            "integration_kind_invalid",
        ),
        (
            lambda service: service.create_retention_policy(
                actor_user_id="admin",
                name="Bad Name",
                description="",
                data_classification="internal",
                duration_days=30,
            ),
            "retention_policy_name_invalid",
        ),
        (
            lambda service: service.update_retention_policy(
                actor_user_id="admin",
                policy_id="rtp-" + "a" * 32,
                expected_lifecycle_version=1,
                reason_code="policy_change",
            ),
            "retention_policy_update_empty",
        ),
        (
            lambda service: service.apply_retention_policy(
                actor_user_id="admin",
                policy_id="rtp-" + "a" * 32,
                evidence_id="evidence-1",
                expected_retention_version=True,
                reason_code="policy_application",
            ),
            "security_governance_version_invalid",
        ),
    ],
)
def test_security_governance_application_rejects_invalid_inputs_before_effects(
    operation: Any,
    code: str,
) -> None:
    repository = _Repository()
    service = SecurityGovernanceApplicationService(
        repository,
        clock=lambda: datetime(2026, 7, 30, tzinfo=UTC),
    )
    with pytest.raises(SecurityGovernanceError) as exc:
        operation(service)
    assert exc.value.code == code
    assert repository.calls == []


def test_security_governance_rejects_non_whole_second_clock() -> None:
    service = SecurityGovernanceApplicationService(
        _Repository(),
        clock=lambda: datetime(2026, 7, 30, 0, 0, 0, 1, tzinfo=UTC),
    )
    with pytest.raises(SecurityGovernanceError) as exc:
        service.list_integrations()
    assert exc.value.code == "security_governance_time_invalid"
