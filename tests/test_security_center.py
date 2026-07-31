from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from reconforge.application.security_center import (
    SecurityCenterApplicationService,
    SecurityCenterCounts,
    SecurityCenterError,
    SecurityCenterRuntime,
)


class _Repository:
    def __init__(self, counts: SecurityCenterCounts) -> None:
        self.counts = counts
        self.calls: list[tuple[str, datetime]] = []

    def read_counts(self, *, tenant_id: str, as_of: datetime) -> SecurityCenterCounts:
        self.calls.append((tenant_id, as_of))
        return self.counts


def _counts() -> SecurityCenterCounts:
    return SecurityCenterCounts(
        total_users=4,
        active_users=3,
        disabled_users=1,
        locked_users=1,
        active_users_without_roles=1,
        roles=2,
        permissions=8,
        role_permission_bindings=7,
        active_sessions=2,
        revoked_sessions=1,
        expired_unrevoked_sessions=1,
        active_step_up_assertions=1,
        active_webauthn_credentials=2,
        users_with_active_webauthn=2,
        linked_federation_providers=1,
        active_federation_links=2,
        disabled_federation_links=1,
        scim_domains=1,
        active_scim_users=2,
        active_scim_credentials=1,
        enabled_service_accounts=1,
        active_service_account_credentials=1,
        enabled_notification_routes=1,
        active_scope_grants=3,
        pending_emergency_requests=1,
        active_emergency_access=1,
        overdue_emergency_reviews=1,
        evidence_records=4,
        evidence_with_retention=2,
        evidence_retention_expired=1,
        evidence_unverified=1,
        evidence_verification_failed=1,
        audit_events=9,
    )


def test_security_snapshot_is_deterministic_tenant_bound_closed_and_not_assurance() -> None:
    as_of = datetime(2026, 7, 29, 20, 0, tzinfo=UTC)
    repository = _Repository(_counts())
    service = SecurityCenterApplicationService(repository, clock=lambda: as_of)
    runtime = SecurityCenterRuntime(
        configured_federation_providers=2,
        federation_air_gap_mode=True,
        webauthn_required_for_privileged_actions=True,
    )

    first = service.snapshot(tenant_id="tenant-a", runtime=runtime)
    second = service.snapshot(tenant_id="tenant-a", runtime=runtime)
    sibling = service.snapshot(tenant_id="tenant-b", runtime=runtime)
    payload = first.to_payload()

    assert first == second
    assert first.snapshot_digest == second.snapshot_digest
    assert first.snapshot_digest != sibling.snapshot_digest
    assert payload["claim_boundary"] == "operational_snapshot_not_security_assurance"
    assert payload["posture"] == "attention_required"
    assert payload["audit"]["chain_verification"] == "not_evaluated_use_audit_verify_endpoint"  # type: ignore[index]
    assert [item["code"] for item in payload["attention_items"]] == [  # type: ignore[index]
        "active_users_without_roles",
        "evidence_verification_failed",
        "locked_users",
        "overdue_emergency_reviews",
        "privileged_mfa_enrollment_gap",
        "evidence_unverified",
        "evidence_without_retention",
        "expired_unrevoked_sessions",
    ]
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "alice@example.test",
        "raw-password",
        "raw-token",
        "192.0.2.10",
        "secret-ref",
        "https://receiver.example",
        "external-subject",
    ):
        assert forbidden not in serialized
    assert repository.calls == [
        ("tenant-a", as_of),
        ("tenant-a", as_of),
        ("tenant-b", as_of),
    ]

    schema = json.loads(
        Path("docs/schemas/security_center_overview.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(payload)
    hostile = dict(payload)
    hostile["username"] = "alice"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(hostile)


def test_security_center_schema_is_in_source_distribution_manifest() -> None:
    manifest_entries = {
        line.strip()
        for line in Path("MANIFEST.in").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert "include docs/schemas/security_center_overview.schema.json" in manifest_entries


@pytest.mark.parametrize(
    "values, message",
    [
        ({"total_users": 1}, "must equal total"),
        ({"total_users": 1, "active_users": 1, "locked_users": 2}, "cannot exceed active"),
        ({"evidence_records": 1, "evidence_with_retention": 2}, "cannot exceed evidence"),
    ],
)
def test_security_counts_reject_inconsistent_aggregates(values: dict[str, int], message: str) -> None:
    with pytest.raises(SecurityCenterError, match=message):
        SecurityCenterCounts(**values)


def test_security_snapshot_rejects_invalid_scope_time_and_runtime() -> None:
    repository = _Repository(SecurityCenterCounts())
    with pytest.raises(SecurityCenterError, match="tenant_id"):
        SecurityCenterApplicationService(repository, clock=lambda: datetime(2026, 7, 29, tzinfo=UTC)).snapshot(
            tenant_id="Tenant A", runtime=SecurityCenterRuntime()
        )
    with pytest.raises(SecurityCenterError, match="timezone"):
        SecurityCenterApplicationService(repository, clock=lambda: datetime(2026, 7, 29)).snapshot(
            tenant_id="tenant-a", runtime=SecurityCenterRuntime()
        )
    with pytest.raises(SecurityCenterError, match="whole-second"):
        SecurityCenterApplicationService(
            repository, clock=lambda: datetime(2026, 7, 29, microsecond=1, tzinfo=UTC)
        ).snapshot(tenant_id="tenant-a", runtime=SecurityCenterRuntime())
    with pytest.raises(SecurityCenterError, match="non-negative"):
        SecurityCenterRuntime(configured_federation_providers=-1)
