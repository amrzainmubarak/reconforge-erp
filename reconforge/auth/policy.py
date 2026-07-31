"""Central Policy Engine for RBAC, ABAC, and Segregation of Duties (SoD) evaluation."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from reconforge.auth.rbac import check_sod_conflict

if TYPE_CHECKING:
    from reconforge.platform.common import ServerPrincipal

_POLICY_LOGGER = logging.getLogger("reconforge.authorization")
POLICY_VERSION = "central-policy-v1"
PrincipalType = Literal["user", "service_account"]
HUMAN_ONLY_PERMISSIONS = frozenset(
    {
        "accounts.review",
        "accounts.complete",
        "audit.read",
        "audit.verify",
        "close.manage",
        "finance_core.manage",
        "finance_core.validate",
        "inventory.post",
        "receivables.credit_override",
        "roles.manage",
        "service_accounts.manage",
        "security.emergency.approve",
        "security.emergency.review",
        "security.center.read",
        "security.policy.manage",
        "users.manage",
    }
)
PRIVILEGED_STEP_UP_PERMISSIONS = frozenset(
    {
        "audit.read",
        "audit.verify",
        "close.manage",
        "finance_core.manage",
        "finance_core.validate",
        "inventory.post",
        "receivables.credit_override",
        "roles.manage",
        "service_accounts.manage",
        "security.emergency.approve",
        "security.emergency.review",
        "security.center.read",
        "security.policy.manage",
        "users.manage",
    }
)


def permission_requires_human(permission: str) -> bool:
    """Return whether a permission can make or administer a human-governed decision."""

    return permission in HUMAN_ONLY_PERMISSIONS or permission.endswith((".approve", ".review", ".complete"))


@dataclass(frozen=True)
class PolicyEvaluationContext:
    """Contextual attributes for policy evaluation."""

    user_id: str
    username: str
    user_permissions: set[str] | frozenset[str]
    principal_type: PrincipalType = "user"
    step_up_active: bool = False
    step_up_enforced: bool = False
    required_step_up_method: str | None = None
    step_up_method: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None
    entity_id: str | None = None
    period_id: str | None = None
    authorized_tenant_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_workspace_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_entity_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_period_ids: frozenset[str] = field(default_factory=frozenset)
    object_type: str | None = None
    object_id: str | None = None
    object_owner_id: str | None = None
    action: str | None = None
    prior_actions: list[tuple[str, str, str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyDecision:
    """Decision produced by the central policy engine."""

    allowed: bool
    reason: str
    reason_code: str = "policy_allowed"
    evaluator: str = "CentralPolicyEngine"
    granted_permission: str | None = None


def audit_policy_decision(
    decision: PolicyDecision,
    *,
    actor_id: str,
    required_permissions: frozenset[str],
    surface: str,
    request_id: str = "",
    principal_type: PrincipalType = "user",
) -> None:
    """Emit a sanitized structured authorization record without raw scope data."""

    permission_digest = hashlib.sha256(
        json.dumps(sorted(required_permissions), separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    actor_digest = hashlib.sha256(actor_id.strip().casefold().encode("utf-8")).hexdigest() if actor_id.strip() else ""
    _POLICY_LOGGER.info(
        "authorization_decision",
        extra={
            "authorization": {
                "actor_digest": actor_digest,
                "allowed": decision.allowed,
                "evaluator": decision.evaluator,
                "permission_contract_digest": permission_digest,
                "principal_type": principal_type,
                "policy_version": POLICY_VERSION,
                "reason_code": decision.reason_code,
                "request_id": request_id,
                "surface": surface,
            }
        },
    )


class CentralPolicyEngine:
    """Centralized policy engine evaluating RBAC, ABAC, and SoD rules.

    Enforces 'Deny by default' principle.
    """

    def evaluate(
        self,
        ctx: PolicyEvaluationContext,
        *,
        required_permission: str | None = None,
        enforce_sod: bool = True,
        enforce_ownership: bool = True,
    ) -> PolicyDecision:
        """Evaluate access for a given context and policy options."""

        # 1. Deny if context is missing basic user identity
        if not ctx.user_id:
            return PolicyDecision(False, "Deny: missing authenticated user identity.", "identity_missing")

        # 2. A caller must name the permission contract. Identity alone never grants access.
        if not required_permission:
            return PolicyDecision(False, "Deny: no required permission was specified.", "permission_contract_missing")
        if required_permission not in ctx.user_permissions:
            return PolicyDecision(
                allowed=False,
                reason=f"Deny: missing required permission '{required_permission}'.",
                reason_code="permission_missing",
            )
        if ctx.principal_type == "service_account" and permission_requires_human(required_permission):
            return PolicyDecision(
                allowed=False,
                reason="Deny: service accounts cannot perform a human-governed action.",
                reason_code="human_principal_required",
            )
        if ctx.step_up_enforced and required_permission in PRIVILEGED_STEP_UP_PERMISSIONS and not ctx.step_up_active:
            return PolicyDecision(
                allowed=False,
                reason="Deny: this privileged action requires recent human reauthentication.",
                reason_code="step_up_required",
            )
        if (
            required_permission in PRIVILEGED_STEP_UP_PERMISSIONS
            and ctx.required_step_up_method is not None
            and ctx.step_up_method != ctx.required_step_up_method
        ):
            return PolicyDecision(
                allowed=False,
                reason="Deny: this privileged action requires the configured MFA assurance method.",
                reason_code="mfa_required",
            )

        # 3. Enforce every supplied resource scope. Empty grants deny scoped access.
        scope_checks = (
            ("tenant", ctx.tenant_id, ctx.authorized_tenant_ids),
            ("workspace", ctx.workspace_id, ctx.authorized_workspace_ids),
            ("entity", ctx.entity_id, ctx.authorized_entity_ids),
            ("period", ctx.period_id, ctx.authorized_period_ids),
        )
        for scope_name, resource_id, authorized_ids in scope_checks:
            if resource_id is not None and resource_id not in authorized_ids:
                return PolicyDecision(
                    allowed=False,
                    reason=f"Deny: {scope_name} scope is not authorized.",
                    reason_code=f"{scope_name}_scope_denied",
                )

        # 4. Check Segregation of Duties (SoD) if object & action are specified
        if enforce_sod and ctx.object_type and ctx.object_id and ctx.action:
            sod_result = check_sod_conflict(
                user_id=ctx.user_id,
                object_type=ctx.object_type,
                object_id=ctx.object_id,
                action=ctx.action,
                prior_actions=ctx.prior_actions,
            )
            if not sod_result.allowed:
                return PolicyDecision(False, sod_result.reason, "sod_conflict")

        # 5. Self-approval/review is never an ordinary override path.
        if (
            enforce_ownership
            and ctx.object_owner_id
            and ctx.user_id == ctx.object_owner_id
            and ctx.action in {"approve", "review"}
        ):
            return PolicyDecision(
                allowed=False,
                reason="Deny: user cannot approve or review objects they created.",
                reason_code="self_approval_denied",
            )

        return PolicyDecision(allowed=True, reason="Access granted.", granted_permission=required_permission)

    def evaluate_any(
        self,
        ctx: PolicyEvaluationContext,
        *,
        required_permissions: frozenset[str],
    ) -> PolicyDecision:
        """Require one permission from a non-empty, immutable any-of contract."""

        if not required_permissions or any(not value.strip() for value in required_permissions):
            return PolicyDecision(False, "Deny: no required permission was specified.", "permission_contract_missing")
        if not ctx.user_id:
            return PolicyDecision(False, "Deny: missing authenticated user identity.", "identity_missing")
        if ctx.user_permissions.isdisjoint(required_permissions):
            return PolicyDecision(False, "Deny: no required permission is granted.", "permission_missing")
        # Scope and future contextual checks remain centralized in evaluate.
        candidates = ctx.user_permissions.intersection(required_permissions)
        if ctx.principal_type == "service_account":
            candidates = frozenset(permission for permission in candidates if not permission_requires_human(permission))
            if not candidates:
                return PolicyDecision(
                    False,
                    "Deny: service accounts cannot perform a human-governed action.",
                    "human_principal_required",
                )
        selected = min(candidates)
        return self.evaluate(ctx, required_permission=selected)


def evaluate_principal_access(
    principal: ServerPrincipal,
    *,
    required_permission: str,
    object_type: str | None = None,
    object_id: str | None = None,
    action: str | None = None,
    prior_actions: list[tuple[str, str, str, str]] | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    entity_id: str | None = None,
    period_id: str | None = None,
    authorized_tenant_ids: frozenset[str] = frozenset(),
    authorized_workspace_ids: frozenset[str] = frozenset(),
    authorized_entity_ids: frozenset[str] = frozenset(),
    authorized_period_ids: frozenset[str] = frozenset(),
    object_owner_id: str | None = None,
) -> PolicyDecision:
    """Helper for evaluating ServerPrincipal authorization."""

    ctx = PolicyEvaluationContext(
        user_id=principal.user.id,
        username=principal.user.username,
        user_permissions=principal.permissions,
        principal_type=principal.principal_type,
        step_up_active=principal.step_up_active,
        step_up_enforced=True,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        entity_id=entity_id,
        period_id=period_id,
        authorized_tenant_ids=authorized_tenant_ids,
        authorized_workspace_ids=authorized_workspace_ids,
        authorized_entity_ids=authorized_entity_ids,
        authorized_period_ids=authorized_period_ids,
        object_type=object_type,
        object_id=object_id,
        object_owner_id=object_owner_id,
        action=action,
        prior_actions=prior_actions or [],
    )
    engine = CentralPolicyEngine()
    return engine.evaluate(ctx, required_permission=required_permission)
