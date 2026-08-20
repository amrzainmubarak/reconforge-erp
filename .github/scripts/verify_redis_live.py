"""Run the bounded live Redis session and policy-generation contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from reconforge.auth.policy import PolicyDecision, PolicyEvaluationContext
from reconforge.auth.policy_cache import PolicyDecisionCache
from reconforge.infrastructure.redis import (
    RedisConnectionFactory,
    RedisPolicyCacheVersionStore,
    RedisSessionRecord,
    RedisSettings,
    TenantRedisStore,
)

REPORT_ID = "redis-live-session-policy-v1"
IMAGE_DIGEST_PREFIX = "sha256:"


class _CountingPolicyEvaluator:
    """Synthetic evaluator used only to prove cache invalidation semantics."""

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(
        self,
        context: PolicyEvaluationContext,
        *,
        required_permission: str | None = None,
        enforce_sod: bool = True,
        enforce_ownership: bool = True,
    ) -> PolicyDecision:
        del context, required_permission, enforce_sod, enforce_ownership
        self.calls += 1
        return PolicyDecision(True, "synthetic_live_allow", granted_permission="close.manage")

    def evaluate_any(
        self,
        context: PolicyEvaluationContext,
        *,
        required_permissions: frozenset[str],
    ) -> PolicyDecision:
        del context, required_permissions
        self.calls += 1
        return PolicyDecision(True, "synthetic_live_allow", granted_permission="close.manage")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required live Redis setting is missing: {name}")
    return value


def _endpoint_shape(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError("Live Redis URL must be redis(s):// without credentials")
    port = parsed.port or (6380 if parsed.scheme == "rediss" else 6379)
    return f"{parsed.scheme}://{parsed.hostname}:{port}"


def _canonical_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_contract() -> dict[str, object]:
    url = _required("RECONFORGE_TEST_REDIS_URL")
    image_digest = _required("RECONFORGE_REDIS_IMAGE_DIGEST")
    if not image_digest.startswith(IMAGE_DIGEST_PREFIX) or len(image_digest) != len(IMAGE_DIGEST_PREFIX) + 64:
        raise RuntimeError("RECONFORGE_REDIS_IMAGE_DIGEST must be a full sha256 digest")
    endpoint = _endpoint_shape(url)
    started = time.perf_counter()
    require_tls = url.startswith("rediss://")
    first_factory = RedisConnectionFactory(RedisSettings(url=url, require_tls=require_tls))
    second_factory = RedisConnectionFactory(RedisSettings(url=url, require_tls=require_tls))
    first_store = TenantRedisStore(first_factory)
    second_store = TenantRedisStore(second_factory)
    raw_token = "redis-live-" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    session_id = "redis-live-session"
    observed = {
        "tenant_key_isolation": False,
        "session_raw_token_absent": False,
        "policy_generation_shared": False,
        "policy_cache_cross_process_invalidation": False,
        "cleanup": False,
    }
    cleanup_keys = (
        first_store._key("redis_live_a", "revoked-token", token_hash),
        first_store._hashed_key("redis_live_a", "session", session_id),
        first_store._key("redis_live_b", "revoked-token", token_hash),
        first_store._hashed_key("redis_live_b", "session", session_id),
        f"{first_store.key_prefix}:policy-cache:generation",
    )
    try:
        client = first_factory.client()
        client.delete(*cleanup_keys)
        first_store.revoke_token_hash("redis_live_a", token_hash, ttl_seconds=60)
        observed["tenant_key_isolation"] = (
            first_store.is_token_hash_revoked("redis_live_a", token_hash)
            and not second_store.is_token_hash_revoked("redis_live_b", token_hash)
        )
        first_store.put_session(
            "redis_live_a",
            RedisSessionRecord(session_id, "user-live", token_hash, "2030-01-01T00:00:00Z"),
            ttl_seconds=60,
        )
        raw_session = client.get(first_store._hashed_key("redis_live_a", "session", session_id))
        loaded = first_store.get_session("redis_live_a", session_id)
        observed["session_raw_token_absent"] = (
            loaded is not None
            and loaded.token_hash == token_hash
            and token_hash in str(raw_session)
            and raw_token not in str(raw_session)
        )
        first_policy = RedisPolicyCacheVersionStore(first_factory)
        second_policy = RedisPolicyCacheVersionStore(second_factory)
        first_policy.bump_version()
        observed["policy_generation_shared"] = second_policy.current_version() == "1" and second_policy.bump_version() == "2"
        context = PolicyEvaluationContext(
            user_id="redis-live-user",
            username="redis-live-user",
            user_permissions={"close.manage"},
            tenant_id="redis_live_a",
            workspace_id="workspace-live",
            authorized_tenant_ids=frozenset({"redis_live_a"}),
            authorized_workspace_ids=frozenset({"workspace-live"}),
        )
        first_evaluator = _CountingPolicyEvaluator()
        second_evaluator = _CountingPolicyEvaluator()
        first_cache = PolicyDecisionCache(version_store=first_policy)
        second_cache = PolicyDecisionCache(version_store=second_policy)
        first_cache.evaluate(context, required_permission="close.manage", evaluator=first_evaluator)
        second_cache.evaluate(context, required_permission="close.manage", evaluator=second_evaluator)
        second_cache.evaluate(context, required_permission="close.manage", evaluator=second_evaluator)
        first_cache.invalidate()
        second_cache.evaluate(context, required_permission="close.manage", evaluator=second_evaluator)
        observed["policy_cache_cross_process_invalidation"] = (
            first_evaluator.calls == 1
            and second_evaluator.calls == 2
            and second_policy.current_version() == "3"
        )
    finally:
        try:
            first_factory.client().delete(*cleanup_keys)
            observed["cleanup"] = all(first_factory.client().exists(key) == 0 for key in cleanup_keys)
        finally:
            first_factory.close()
            second_factory.close()
    if not all(bool(value) for value in observed.values()):
        raise RuntimeError(f"Live Redis invariant failed: {observed!r}")
    report: dict[str, object] = {
        "schema_version": "1.0.0",
        "report_id": REPORT_ID,
        "status": "verified",
        "provider": "redis",
        "image_digest": image_digest,
        "endpoint": endpoint,
        "observed": observed,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "limitations": [
            "single-node disposable Redis process on one CI host",
            "no replication, sentinel, cluster failover, cross-site durability, or Redis HA claim",
            "synthetic keys, token digests, and session metadata only",
        ],
    }
    report["report_digest"] = _canonical_digest(report)
    return report


def verify_report(report: dict[str, object]) -> None:
    required = {
        "schema_version",
        "report_id",
        "status",
        "provider",
        "image_digest",
        "endpoint",
        "observed",
        "elapsed_ms",
        "limitations",
        "report_digest",
    }
    if set(report) != required or report["schema_version"] != "1.0.0" or report["report_id"] != REPORT_ID:
        raise ValueError("Live Redis report shape is invalid")
    observed = report["observed"]
    legacy_observed = {
        "tenant_key_isolation",
        "session_raw_token_absent",
        "policy_generation_shared",
        "cleanup",
    }
    current_observed = legacy_observed | {"policy_cache_cross_process_invalidation"}
    if not isinstance(observed, dict) or set(observed) not in (legacy_observed, current_observed) or not all(observed.values()):
        raise ValueError("Live Redis report invariant set is incomplete")
    if "policy_cache_cross_process_invalidation" in observed and not observed["policy_cache_cross_process_invalidation"]:
        raise ValueError("Live Redis policy-cache invalidation invariant is incomplete")
    supplied = report["report_digest"]
    payload = dict(report)
    payload.pop("report_digest")
    if supplied != _canonical_digest(payload):
        raise ValueError("Live Redis report digest mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = _run_contract()
    verify_report(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
