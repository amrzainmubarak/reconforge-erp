"""Unit tests for Central Policy Engine (RBAC, ABAC, SoD)."""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reconforge.auth.models import LocalUser
from reconforge.auth.policy import (
    HUMAN_ONLY_PERMISSIONS,
    PRIVILEGED_STEP_UP_PERMISSIONS,
    CentralPolicyEngine,
    PolicyEvaluationContext,
    audit_policy_decision,
    evaluate_principal_access,
)
from reconforge.platform.common import ServerPrincipal


def test_policy_engine_deny_by_default_missing_user() -> None:
    engine = CentralPolicyEngine()
    ctx = PolicyEvaluationContext(user_id="", username="", user_permissions=set())
    decision = engine.evaluate(ctx, required_permission="reconciliation.approve")

    assert decision.allowed is False
    assert "missing authenticated user identity" in decision.reason


def test_policy_engine_rbac_permission_granted() -> None:
    engine = CentralPolicyEngine()
    ctx = PolicyEvaluationContext(
        user_id="U-100",
        username="analyst",
        user_permissions={"reconciliation.read", "reconciliation.prepare"},
    )
    decision = engine.evaluate(ctx, required_permission="reconciliation.prepare")

    assert decision.allowed is True
    assert decision.reason == "Access granted."


def test_policy_engine_rbac_permission_denied() -> None:
    engine = CentralPolicyEngine()
    ctx = PolicyEvaluationContext(
        user_id="U-100",
        username="analyst",
        user_permissions={"reconciliation.read"},
    )
    decision = engine.evaluate(ctx, required_permission="reconciliation.approve")

    assert decision.allowed is False
    assert "missing required permission 'reconciliation.approve'" in decision.reason


@pytest.mark.parametrize(
    "permission",
    sorted(HUMAN_ONLY_PERMISSIONS | {"payables.approve", "inventory.valuation.reverse.approve"}),
)
def test_service_accounts_cannot_receive_human_governed_policy_decisions(permission: str) -> None:
    decision = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(
            user_id="svc-worker",
            username="worker",
            user_permissions={permission},
            principal_type="service_account",
        ),
        required_permission=permission,
    )

    assert not decision.allowed
    assert decision.reason_code == "human_principal_required"


def test_service_account_can_use_safe_explicit_permission_and_any_contract_filters_human_permissions() -> None:
    context = PolicyEvaluationContext(
        user_id="svc-worker",
        username="worker",
        user_permissions={"db.read", "accounts.review"},
        principal_type="service_account",
    )
    engine = CentralPolicyEngine()

    assert engine.evaluate(context, required_permission="db.read").allowed
    decision = engine.evaluate_any(context, required_permissions=frozenset({"db.read", "accounts.review"}))
    assert decision.allowed


@pytest.mark.parametrize("permission", sorted(PRIVILEGED_STEP_UP_PERMISSIONS))
def test_privileged_human_permissions_require_recent_step_up(permission: str) -> None:
    without_step_up = PolicyEvaluationContext(
        user_id="human-1", username="controller", user_permissions={permission}, step_up_enforced=True
    )
    with_step_up = PolicyEvaluationContext(
        user_id="human-1",
        username="controller",
        user_permissions={permission},
        step_up_active=True,
        step_up_enforced=True,
    )

    denied = CentralPolicyEngine().evaluate(without_step_up, required_permission=permission)
    allowed = CentralPolicyEngine().evaluate(with_step_up, required_permission=permission)

    assert not denied.allowed
    assert denied.reason_code == "step_up_required"
    assert allowed.allowed


@pytest.mark.parametrize("permission", sorted(PRIVILEGED_STEP_UP_PERMISSIONS))
def test_configured_webauthn_requires_user_verified_mfa_not_password_only(permission: str) -> None:
    password_only = PolicyEvaluationContext(
        user_id="human-1",
        username="controller",
        user_permissions={permission},
        step_up_active=True,
        step_up_enforced=True,
        step_up_method="password_reauthentication",
        required_step_up_method="webauthn_user_verified",
    )
    webauthn = PolicyEvaluationContext(
        user_id="human-1",
        username="controller",
        user_permissions={permission},
        step_up_active=True,
        step_up_enforced=True,
        step_up_method="webauthn_user_verified",
        required_step_up_method="webauthn_user_verified",
    )

    denied = CentralPolicyEngine().evaluate(password_only, required_permission=permission)
    allowed = CentralPolicyEngine().evaluate(webauthn, required_permission=permission)

    assert not denied.allowed and denied.reason_code == "mfa_required"
    assert allowed.allowed


def test_policy_engine_sod_conflict_detected() -> None:
    engine = CentralPolicyEngine()
    ctx = PolicyEvaluationContext(
        user_id="U-100",
        username="analyst",
        user_permissions={"reconciliation.prepare", "reconciliation.approve"},
        object_type="reconciliation",
        object_id="REC-999",
        action="approve",
        prior_actions=[("U-100", "reconciliation", "REC-999", "prepare")],
    )
    decision = engine.evaluate(ctx, required_permission="reconciliation.approve")

    assert decision.allowed is False
    assert "Separation of duties conflict" in decision.reason


def test_policy_engine_self_approval_prevention() -> None:
    engine = CentralPolicyEngine()
    ctx = PolicyEvaluationContext(
        user_id="U-100",
        username="creator",
        user_permissions={"close.approve"},
        object_owner_id="U-100",
        action="approve",
    )
    decision = engine.evaluate(ctx, required_permission="close.approve", enforce_ownership=True)

    assert decision.allowed is False
    assert "cannot approve or review objects they created" in decision.reason


def test_evaluate_principal_access_granted() -> None:
    user = LocalUser(id="U-200", username="manager", display_name="Manager")
    principal = ServerPrincipal(user=user, permissions={"reconciliation.approve"})

    decision = evaluate_principal_access(principal, required_permission="reconciliation.approve")
    assert decision.allowed is True


def test_policy_engine_denies_authenticated_identity_without_a_named_permission_contract() -> None:
    decision = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(user_id="U-1", username="user", user_permissions={"admin"})
    )

    assert not decision.allowed
    assert "no required permission" in decision.reason


SCOPE_IDS = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=1,
    max_size=4,
)


@given(
    resource_tenant=SCOPE_IDS,
    resource_workspace=SCOPE_IDS,
    resource_entity=SCOPE_IDS,
    resource_period=SCOPE_IDS,
    granted_tenants=st.frozensets(SCOPE_IDS, max_size=5),
    granted_workspaces=st.frozensets(SCOPE_IDS, max_size=5),
    granted_entities=st.frozensets(SCOPE_IDS, max_size=5),
    granted_periods=st.frozensets(SCOPE_IDS, max_size=5),
)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=200, deadline=None)
def test_scoped_policy_allows_only_when_every_resource_scope_is_granted(
    resource_tenant: str,
    resource_workspace: str,
    resource_entity: str,
    resource_period: str,
    granted_tenants: frozenset[str],
    granted_workspaces: frozenset[str],
    granted_entities: frozenset[str],
    granted_periods: frozenset[str],
) -> None:
    decision = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(
            user_id="U-1",
            username="user",
            user_permissions={"reconciliation.read"},
            tenant_id=resource_tenant,
            workspace_id=resource_workspace,
            entity_id=resource_entity,
            period_id=resource_period,
            authorized_tenant_ids=granted_tenants,
            authorized_workspace_ids=granted_workspaces,
            authorized_entity_ids=granted_entities,
            authorized_period_ids=granted_periods,
        ),
        required_permission="reconciliation.read",
    )

    expected = all(
        (
            resource_tenant in granted_tenants,
            resource_workspace in granted_workspaces,
            resource_entity in granted_entities,
            resource_period in granted_periods,
        )
    )
    assert decision.allowed is expected


@given(action=st.sampled_from(["approve", "review"]))
def test_creator_can_never_approve_or_review_own_object(action: str) -> None:
    decision = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(
            user_id="U-creator",
            username="creator",
            user_permissions={f"close.{action}"},
            object_owner_id="U-creator",
            action=action,
        ),
        required_permission=f"close.{action}",
    )

    assert not decision.allowed
    assert "cannot approve or review" in decision.reason


def test_any_permission_contract_still_enforces_abac_scope() -> None:
    context = PolicyEvaluationContext(
        user_id="U-1",
        username="reader",
        user_permissions={"evidence.read"},
        tenant_id="tenant-b",
        authorized_tenant_ids=frozenset({"tenant-a"}),
    )
    decision = CentralPolicyEngine().evaluate_any(
        context, required_permissions=frozenset({"evidence.read", "evidence.manage"})
    )
    assert not decision.allowed
    assert decision.reason_code == "tenant_scope_denied"


@pytest.mark.parametrize(
    ("amount", "minimum", "maximum", "expected_code"),
    [
        (Decimal("99.99"), Decimal("100.00"), Decimal("500.00"), "amount_below_floor"),
        (Decimal("500.01"), Decimal("100.00"), Decimal("500.00"), "amount_above_ceiling"),
        (Decimal("250.00"), Decimal("100.00"), Decimal("500.00"), "policy_allowed"),
    ],
)
def test_amount_policy_is_exact_and_fail_closed(
    amount: Decimal, minimum: Decimal, maximum: Decimal, expected_code: str
) -> None:
    decision = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(
            user_id="U-amount",
            username="controller",
            user_permissions={"finance_core.validate"},
            step_up_active=True,
            step_up_enforced=True,
            amount=amount,
            minimum_amount=minimum,
            maximum_amount=maximum,
        ),
        required_permission="finance_core.validate",
    )
    assert decision.reason_code == expected_code
    assert decision.allowed is (expected_code == "policy_allowed")


def test_region_and_data_classification_scopes_are_deny_by_default() -> None:
    context = PolicyEvaluationContext(
        user_id="U-scope",
        username="analyst",
        user_permissions={"evidence.read"},
        region_id="eu",
        data_classification="restricted",
        authorized_region_ids=frozenset({"eu"}),
        authorized_data_classifications=frozenset({"public"}),
    )
    denied = CentralPolicyEngine().evaluate(context, required_permission="evidence.read")
    assert not denied.allowed and denied.reason_code == "data_classification_scope_denied"
    allowed = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(
            **{**context.__dict__, "authorized_data_classifications": frozenset({"restricted"})}
        ),
        required_permission="evidence.read",
    )
    assert allowed.allowed


def test_amount_policy_rejects_non_finite_or_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="finite Decimal"):
        PolicyEvaluationContext(user_id="U", username="u", user_permissions=set(), amount=Decimal("NaN"))
    with pytest.raises(ValueError, match="minimum_amount"):
        PolicyEvaluationContext(
            user_id="U",
            username="u",
            user_permissions=set(),
            minimum_amount=Decimal("2"),
            maximum_amount=Decimal("1"),
        )


def test_policy_audit_record_is_versioned_and_redacts_actor_and_permissions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    decision = CentralPolicyEngine().evaluate(
        PolicyEvaluationContext(user_id="sensitive-user", username="alice", user_permissions={"audit.read"}),
        required_permission="audit.read",
    )
    with caplog.at_level(logging.INFO, logger="reconforge.authorization"):
        audit_policy_decision(
            decision,
            actor_id="sensitive-user",
            required_permissions=frozenset({"audit.read"}),
            surface="GET /api/v1/audit/events",
            request_id="request-1",
            principal_type="service_account",
        )
    record = caplog.records[-1]
    evidence = record.authorization
    assert evidence["policy_version"] == "central-policy-v1"
    assert evidence["allowed"] is True
    assert evidence["reason_code"] == "policy_allowed"
    assert evidence["principal_type"] == "service_account"
    assert len(evidence["actor_digest"]) == 64
    assert "sensitive-user" not in str(evidence)
    assert "audit.read" not in str(evidence)
