"""Central Policy Engine for RBAC, ABAC, and Segregation of Duties (SoD) evaluation."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from reconforge.auth.rbac import check_sod_conflict

if TYPE_CHECKING:
    from reconforge.platform.common import ServerPrincipal

_POLICY_LOGGER = logging.getLogger("reconforge.authorization")
POLICY_VERSION = "central-policy-v1"


@dataclass(frozen=True)
class PolicyEvaluationContext:
    """Contextual attributes for policy evaluation."""

    user_id: str
    username: str
    user_permissions: set[str] | frozenset[str]
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


def audit_policy_decision(
    decision: PolicyDecision,
    *,
    actor_id: str,
    required_permissions: frozenset[str],
    surface: str,
    request_id: str = "",
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

        return PolicyDecision(allowed=True, reason="Access granted.")

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
        selected = min(ctx.user_permissions.intersection(required_permissions))
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
