"""Shared central-policy guard for hosted service workers.

The guard is opt-in so Community/local workers keep their existing contract.
When configured, a worker must present a service-account context whose actor and
tenant scope match the lane being processed before any repository connection is
opened.
"""

from __future__ import annotations

from collections.abc import Callable

from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext, audit_policy_decision

WorkerPolicyContextSupplier = Callable[[str, str | None, str | None], PolicyEvaluationContext]
WorkerPolicyHierarchyContextSupplier = Callable[
    [str, str | None, str | None, str | None], PolicyEvaluationContext
]


def require_service_worker_policy(
    *,
    tenant_id: str,
    worker_id: str,
    actor_id: str,
    policy_context_supplier: Callable[[str], PolicyEvaluationContext] | None,
    policy_context_scope_supplier: WorkerPolicyContextSupplier | None = None,
    policy_context_hierarchy_supplier: WorkerPolicyHierarchyContextSupplier | None = None,
    workspace_id: str | None = None,
    organization_id: str | None = None,
    entity_id: str | None = None,
    policy_permission: str,
    surface: str,
    error_factory: Callable[[str], Exception],
    policy: CentralPolicyEngine | None = None,
    request_id: str = "",
) -> None:
    """Require a non-human central-policy decision for an exact worker scope.

    The one-argument supplier remains supported for legacy tenant-only workers.
    A workspace/entity scope requires the explicit three-argument supplier so a
    tenant-wide identity cannot accidentally process a narrower lane.
    """

    if policy_context_supplier is None and policy_context_scope_supplier is None and policy_context_hierarchy_supplier is None:
        return
    normalized_workspace = str(workspace_id).strip() if workspace_id is not None and str(workspace_id).strip() else None
    normalized_organization = (
        str(organization_id).strip() if organization_id is not None and str(organization_id).strip() else None
    )
    normalized_entity = str(entity_id).strip() if entity_id is not None and str(entity_id).strip() else None
    if policy_context_hierarchy_supplier is None and normalized_organization is not None:
        raise error_factory("A hierarchy-aware worker policy supplier is required for organization-scoped processing.")
    if policy_context_hierarchy_supplier is None and policy_context_scope_supplier is None and (
        normalized_workspace is not None or normalized_entity is not None
    ):
        raise error_factory("A scope-aware worker policy supplier is required for scoped processing.")
    try:
        if policy_context_hierarchy_supplier is not None:
            context = policy_context_hierarchy_supplier(
                tenant_id, normalized_workspace, normalized_organization, normalized_entity
            )
        elif policy_context_scope_supplier is not None:
            context = policy_context_scope_supplier(tenant_id, normalized_workspace, normalized_entity)
        else:
            if policy_context_supplier is None:  # Defensive branch for type narrowing and fail-closed behavior.
                raise error_factory("A worker policy supplier is required when policy enforcement is enabled.")
            context = policy_context_supplier(tenant_id)
    except Exception as exc:  # noqa: BLE001 - worker boundary must fail closed.
        raise error_factory("Unable to resolve worker policy context safely.") from exc
    if context.principal_type != "service_account":
        raise error_factory("Hosted workers require a service-account principal.")
    normalized_actor = actor_id.strip() or worker_id.strip()
    if context.user_id != normalized_actor:
        raise error_factory("Worker actor does not match policy identity.")
    context_workspace = str(context.workspace_id).strip() if context.workspace_id is not None else None
    context_entity = str(context.entity_id).strip() if context.entity_id is not None else None
    context_organization = str(context.organization_id).strip() if context.organization_id is not None else None
    if (
        context.tenant_id != tenant_id
        or context_organization != normalized_organization
        or context_workspace != normalized_workspace
        or context_entity != normalized_entity
    ):
        raise error_factory("Worker policy scope does not match the requested processing scope.")
    permission = policy_permission.strip()
    if not permission:
        raise error_factory("Worker policy permission must be non-empty.")
    decision = (policy or CentralPolicyEngine()).evaluate(
        context,
        required_permission=permission,
        enforce_sod=False,
        enforce_ownership=False,
    )
    audit_policy_decision(
        decision,
        actor_id=normalized_actor,
        required_permissions=frozenset({permission}),
        surface=surface,
        request_id=request_id,
        principal_type=context.principal_type,
    )
    if not decision.allowed:
        raise error_factory(f"Worker policy denied: {decision.reason_code}")


__all__ = [
    "WorkerPolicyContextSupplier",
    "WorkerPolicyHierarchyContextSupplier",
    "require_service_worker_policy",
]
