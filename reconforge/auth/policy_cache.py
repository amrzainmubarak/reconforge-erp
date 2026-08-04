"""Fail-closed, scope-aware cache for explicitly adopted policy evaluations.

The cache is opt-in.  Denials and delegated decisions are never cached, so a
caller that has not wired mutation invalidation cannot accidentally turn a
temporary deny or expiring grant into durable authority.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from contextlib import suppress
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from threading import RLock
from typing import Protocol

from reconforge.auth.policy import (
    POLICY_VERSION,
    CentralPolicyEngine,
    PolicyDecision,
    PolicyEvaluationContext,
    permission_requires_human,
)


class PolicyEvaluator(Protocol):
    def evaluate(
        self,
        ctx: PolicyEvaluationContext,
        *,
        required_permission: str | None = None,
        enforce_sod: bool = True,
        enforce_ownership: bool = True,
    ) -> PolicyDecision: ...

    def evaluate_any(
        self,
        ctx: PolicyEvaluationContext,
        *,
        required_permissions: frozenset[str],
    ) -> PolicyDecision: ...


class PolicyCacheVersionStore(Protocol):
    """Optional shared version boundary used to invalidate other processes."""

    def current_version(self) -> str: ...

    def bump_version(self) -> str: ...


class PolicyCacheError(ValueError):
    """Raised when cache configuration is unsafe."""


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, (set, frozenset)):
        return sorted(str(item) for item in value)
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    return value


def policy_cache_key(
    context: PolicyEvaluationContext,
    *,
    required_permission: str,
    enforce_sod: bool,
    enforce_ownership: bool,
    policy_version: str,
) -> str:
    """Return a deterministic digest over every policy-relevant attribute."""

    payload = {
        "policy_version": policy_version,
        "required_permission": required_permission,
        "enforce_sod": enforce_sod,
        "enforce_ownership": enforce_ownership,
        "context": {field.name: _canonical(getattr(context, field.name)) for field in fields(context)},
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PolicyDecisionCache:
    """Bounded cache that requires explicit scope invalidation by adopters."""

    def __init__(
        self,
        *,
        max_entries: int = 1024,
        policy_version: str = POLICY_VERSION,
        version_store: PolicyCacheVersionStore | None = None,
    ) -> None:
        if not isinstance(max_entries, int) or isinstance(max_entries, bool) or not 1 <= max_entries <= 100_000:
            raise PolicyCacheError("max_entries must be between 1 and 100000")
        if not policy_version.strip():
            raise PolicyCacheError("policy_version must be non-empty")
        self._max_entries = max_entries
        self._policy_version = policy_version
        self._version_store = version_store
        self._entries: OrderedDict[str, tuple[PolicyDecision, str | None, str | None]] = OrderedDict()
        self._lock = RLock()

    def evaluate(
        self,
        context: PolicyEvaluationContext,
        *,
        required_permission: str,
        enforce_sod: bool = True,
        enforce_ownership: bool = True,
        evaluator: PolicyEvaluator | None = None,
    ) -> PolicyDecision:
        """Evaluate with an allowed-only cache; delegation always bypasses it."""

        if not required_permission.strip():
            raise PolicyCacheError("required_permission must be non-empty")
        engine = evaluator or CentralPolicyEngine()
        if context.delegation_id is not None or context.delegation_expires_at is not None:
            return engine.evaluate(
                context,
                required_permission=required_permission,
                enforce_sod=enforce_sod,
                enforce_ownership=enforce_ownership,
            )
        version = self._policy_version
        if self._version_store is not None:
            try:
                version = f"{version}:{self._version_store.current_version()}"
            except Exception:
                # A shared cache outage must remove a performance optimization,
                # never remove authorization. Evaluate without caching.
                return engine.evaluate(
                    context,
                    required_permission=required_permission,
                    enforce_sod=enforce_sod,
                    enforce_ownership=enforce_ownership,
                )
        key = policy_cache_key(
            context,
            required_permission=required_permission,
            enforce_sod=enforce_sod,
            enforce_ownership=enforce_ownership,
            policy_version=version,
        )
        with self._lock:
            cached = self._entries.pop(key, None)
            if cached is not None:
                self._entries[key] = cached
                return cached[0]
        decision = engine.evaluate(
            context,
            required_permission=required_permission,
            enforce_sod=enforce_sod,
            enforce_ownership=enforce_ownership,
        )
        if not decision.allowed:
            return decision
        with self._lock:
            self._entries[key] = (decision, context.tenant_id, context.workspace_id)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return decision

    def evaluate_any(
        self,
        context: PolicyEvaluationContext,
        *,
        required_permissions: frozenset[str],
        evaluator: PolicyEvaluator | None = None,
    ) -> PolicyDecision:
        """Evaluate an any-of contract while reusing the safe single-permission cache.

        The selected permission follows ``CentralPolicyEngine.evaluate_any``:
        the smallest eligible permission is evaluated with the full contextual
        checks.  Empty or non-matching contracts stay on the engine so their
        denials are never cached.
        """

        if not required_permissions or any(not value.strip() for value in required_permissions):
            engine = evaluator or CentralPolicyEngine()
            return engine.evaluate_any(context, required_permissions=required_permissions)
        candidates = context.user_permissions.intersection(required_permissions)
        if context.principal_type == "service_account":
            candidates = frozenset(permission for permission in candidates if not permission_requires_human(permission))
        if not candidates:
            engine = evaluator or CentralPolicyEngine()
            return engine.evaluate_any(context, required_permissions=required_permissions)
        return self.evaluate(
            context,
            required_permission=min(candidates),
            evaluator=evaluator,
        )

    def invalidate(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> int:
        """Remove entries matching the supplied scope; no arguments clears all."""

        if workspace_id is not None and tenant_id is None:
            raise PolicyCacheError("workspace invalidation requires tenant_id")
        if self._version_store is not None and tenant_id is None and workspace_id is None:
            with suppress(Exception):
                self._version_store.bump_version()
        with self._lock:
            if tenant_id is None:
                removed = len(self._entries)
                self._entries.clear()
                return removed
            keys = [
                key
                for key, (_decision, entry_tenant, entry_workspace) in self._entries.items()
                if entry_tenant == tenant_id and (workspace_id is None or entry_workspace == workspace_id)
            ]
            for key in keys:
                del self._entries[key]
            return len(keys)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
