"""Shared central-policy guard for hosted service workers.

The guard is opt-in so Community/local workers keep their existing contract.
When configured, a worker must present a service-account context whose actor and
tenant scope match the lane being processed before any repository connection is
opened.
"""

from __future__ import annotations

from collections.abc import Callable

from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext, audit_policy_decision


def require_service_worker_policy(
    *,
    tenant_id: str,
    worker_id: str,
    actor_id: str,
    policy_context_supplier: Callable[[str], PolicyEvaluationContext] | None,
    policy_permission: str,
    surface: str,
    error_factory: Callable[[str], Exception],
    policy: CentralPolicyEngine | None = None,
    request_id: str = "",
) -> None:
    """Require a tenant-only, non-human central-policy decision before I/O."""

    if policy_context_supplier is None:
        return
    try:
        context = policy_context_supplier(tenant_id)
    except Exception as exc:  # noqa: BLE001 - worker boundary must fail closed.
        raise error_factory("Unable to resolve worker policy context safely.") from exc
    if context.principal_type != "service_account":
        raise error_factory("Hosted workers require a service-account principal.")
    normalized_actor = actor_id.strip() or worker_id.strip()
    if context.user_id != normalized_actor:
        raise error_factory("Worker actor does not match policy identity.")
    if context.tenant_id != tenant_id or context.workspace_id is not None or context.entity_id is not None:
        raise error_factory("Worker policy scope does not match tenant lane scope.")
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


__all__ = ["require_service_worker_policy"]
