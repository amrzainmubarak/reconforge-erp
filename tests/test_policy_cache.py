from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from reconforge.auth.policy import PolicyDecision, PolicyEvaluationContext
from reconforge.auth.policy_cache import PolicyCacheError, PolicyDecisionCache


class _CountingEvaluator:
    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        self.calls = 0

    def evaluate(self, context: PolicyEvaluationContext, **_: object) -> PolicyDecision:
        del context
        self.calls += 1
        return self.decision

    def evaluate_any(self, context: PolicyEvaluationContext, **_: object) -> PolicyDecision:
        del context
        self.calls += 1
        return self.decision


class _VersionStore:
    def __init__(self) -> None:
        self.version = 0
        self.fail = False

    def current_version(self) -> str:
        if self.fail:
            raise RuntimeError("synthetic redis outage")
        return str(self.version)

    def bump_version(self) -> str:
        if self.fail:
            raise RuntimeError("synthetic redis outage")
        self.version += 1
        return str(self.version)

def _context(tenant: str, workspace: str = "workspace-a") -> PolicyEvaluationContext:
    return PolicyEvaluationContext(
        user_id="operator", username="operator", user_permissions={"close.manage"},
        tenant_id=tenant, workspace_id=workspace,
        authorized_tenant_ids=frozenset({tenant}), authorized_workspace_ids=frozenset({workspace}),
    )


def test_allowed_decision_is_bounded_and_scope_invalidation_isolated() -> None:
    cache = PolicyDecisionCache(max_entries=2)
    evaluator = _CountingEvaluator(PolicyDecision(True, "allowed", granted_permission="close.manage"))
    cache.evaluate(_context("tenant-a"), required_permission="close.manage", evaluator=evaluator)
    cache.evaluate(_context("tenant-a"), required_permission="close.manage", evaluator=evaluator)
    cache.evaluate(_context("tenant-b"), required_permission="close.manage", evaluator=evaluator)
    assert evaluator.calls == 2
    assert cache.invalidate(tenant_id="tenant-a") == 1
    cache.evaluate(_context("tenant-a"), required_permission="close.manage", evaluator=evaluator)
    cache.evaluate(_context("tenant-b"), required_permission="close.manage", evaluator=evaluator)
    assert evaluator.calls == 3


def test_denials_and_delegations_are_never_cached() -> None:
    cache = PolicyDecisionCache()
    denied = _CountingEvaluator(PolicyDecision(False, "denied", "permission_missing"))
    context = _context("tenant-a")
    cache.evaluate(context, required_permission="close.manage", evaluator=denied)
    cache.evaluate(context, required_permission="close.manage", evaluator=denied)
    assert denied.calls == 2 and len(cache) == 0

    allowed = _CountingEvaluator(PolicyDecision(True, "allowed", granted_permission="close.manage"))
    delegated = replace(
        context,
        delegation_id="grant-1",
        delegation_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        evaluation_time=datetime.now(UTC),
    )
    cache.evaluate(delegated, required_permission="close.manage", evaluator=allowed)
    cache.evaluate(delegated, required_permission="close.manage", evaluator=allowed)
    assert allowed.calls == 2 and len(cache) == 0


def test_cache_rejects_unsafe_scope_and_capacity_configuration() -> None:
    for kwargs in ({"max_entries": 0}, {"max_entries": 100001}, {"policy_version": ""}):
        try:
            PolicyDecisionCache(**kwargs)
        except PolicyCacheError:
            pass
        else:
            raise AssertionError("unsafe cache configuration was accepted")
    cache = PolicyDecisionCache()
    try:
        cache.invalidate(workspace_id="workspace-a")
    except PolicyCacheError:
        pass
    else:
        raise AssertionError("workspace invalidation without tenant was accepted")


def test_any_permission_uses_same_allowed_only_cache_and_preserves_denial() -> None:
    cache = PolicyDecisionCache()
    evaluator = _CountingEvaluator(PolicyDecision(True, "allowed", granted_permission="close.manage"))
    context = _context("tenant-a")
    required = frozenset({"close.manage", "reports.read"})
    cache.evaluate_any(context, required_permissions=required, evaluator=evaluator)
    cache.evaluate_any(context, required_permissions=required, evaluator=evaluator)
    assert evaluator.calls == 1

    denied = _CountingEvaluator(PolicyDecision(False, "denied", "permission_missing"))
    missing = _context("tenant-a")
    cache.evaluate_any(missing, required_permissions=frozenset({"reports.read"}), evaluator=denied)
    cache.evaluate_any(missing, required_permissions=frozenset({"reports.read"}), evaluator=denied)
    assert denied.calls == 2


def test_shared_generation_invalidates_independent_cache_instances() -> None:
    versions = _VersionStore()
    first = PolicyDecisionCache(version_store=versions)
    second = PolicyDecisionCache(version_store=versions)
    evaluator = _CountingEvaluator(PolicyDecision(True, "allowed", granted_permission="close.manage"))
    context = _context("tenant-a")

    first.evaluate(context, required_permission="close.manage", evaluator=evaluator)
    second.evaluate(context, required_permission="close.manage", evaluator=evaluator)
    assert evaluator.calls == 2
    assert first.invalidate() == 1
    second.evaluate(context, required_permission="close.manage", evaluator=evaluator)
    assert evaluator.calls == 3


def test_shared_generation_outage_falls_back_to_uncached_evaluation() -> None:
    versions = _VersionStore()
    versions.fail = True
    cache = PolicyDecisionCache(version_store=versions)
    evaluator = _CountingEvaluator(PolicyDecision(True, "allowed", granted_permission="close.manage"))
    context = _context("tenant-a")
    cache.evaluate(context, required_permission="close.manage", evaluator=evaluator)
    cache.evaluate(context, required_permission="close.manage", evaluator=evaluator)
    assert evaluator.calls == 2
    assert len(cache) == 0
