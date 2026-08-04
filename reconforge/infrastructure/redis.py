"""Optional Redis boundary for server-side coordination.

The local edition intentionally keeps its SQLite session and in-process login
protection.  This module provides the primitives required by a multi-worker
deployment without importing the optional ``redis`` package unless a server
configuration explicitly uses it.

All keys are tenant-scoped.  Raw bearer tokens are never accepted as Redis
values by this module; callers provide their already-hashed token digest.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, TypeVar
from urllib.parse import urlsplit

from reconforge.infrastructure.postgres import normalize_scope_id
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_redis_session,
    encode_redis_session,
)

_KEY_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,47}$")
_TOKEN_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_INCREMENT_RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""
_RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisConfigurationError(ValueError):
    """Raised when Redis settings or key inputs are unsafe."""


class RedisUnavailableError(RuntimeError):
    """Raised when the optional Redis driver is not installed."""


class RedisDataError(RuntimeError):
    """Raised when a Redis value cannot be interpreted safely."""


class RedisOperationError(RuntimeError):
    """Raised when the Redis dependency cannot complete an operation."""


_RedisResult = TypeVar("_RedisResult")


@dataclass(frozen=True)
class RedisSettings:
    """Connection settings for the optional Redis server boundary."""

    url: str = field(repr=False)
    key_prefix: str = "reconforge"
    socket_timeout_seconds: float = 5.0
    socket_connect_timeout_seconds: float = 5.0
    health_check_interval_seconds: int = 30
    require_tls: bool = True

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.netloc:
            raise RedisConfigurationError("Redis URL must use redis:// or rediss:// with a host.")
        if self.require_tls and parsed.scheme != "rediss":
            raise RedisConfigurationError(
                "Redis TLS is required; use a rediss:// URL or explicitly disable TLS for local development."
            )
        if not _KEY_PREFIX_PATTERN.fullmatch(self.key_prefix):
            raise RedisConfigurationError("Redis key prefix contains unsafe characters or is too long.")
        if self.socket_timeout_seconds <= 0 or self.socket_connect_timeout_seconds <= 0:
            raise RedisConfigurationError("Redis socket timeouts must be positive.")
        if self.health_check_interval_seconds < 0:
            raise RedisConfigurationError("Redis health-check interval cannot be negative.")


def _load_redis() -> ModuleType:
    try:
        return importlib.import_module("redis")
    except ImportError as exc:
        raise RedisUnavailableError(
            "Redis support is optional. Install the server extra with `pip install 'reconforge-erp[server]'`."
        ) from exc


class RedisConnectionFactory:
    """Create one reusable, configured redis-py client lazily."""

    def __init__(self, settings: RedisSettings) -> None:
        self.settings = settings
        self._client: Any | None = None

    def client(self) -> Any:
        """Return the configured client, importing redis-py only on first use."""

        if self._client is None:
            redis_module = _load_redis()
            self._client = redis_module.Redis.from_url(
                self.settings.url,
                decode_responses=True,
                socket_timeout=self.settings.socket_timeout_seconds,
                socket_connect_timeout=self.settings.socket_connect_timeout_seconds,
                health_check_interval=self.settings.health_check_interval_seconds,
            )
        return self._client

    def close(self) -> None:
        """Close the client pool if it has been initialized."""

        if self._client is not None:
            self._client.close()
            self._client = None


@dataclass(frozen=True)
class RedisSessionRecord:
    """Session metadata safe to persist in Redis; it contains no raw token."""

    session_id: str
    user_id: str
    token_hash: str
    expires_at: str


class TenantRedisStore:
    """Tenant-scoped session, revocation, rate-limit, and lock primitives."""

    def __init__(self, connection_factory: RedisConnectionFactory) -> None:
        self.connection_factory = connection_factory
        self.key_prefix = connection_factory.settings.key_prefix

    def _key(self, tenant_id: str, namespace: str, value: str) -> str:
        tenant = normalize_scope_id(tenant_id)
        if not _KEY_PREFIX_PATTERN.fullmatch(namespace):
            raise RedisConfigurationError("Redis namespace contains unsafe characters.")
        return f"{self.key_prefix}:tenant:{tenant}:{namespace}:{value}"

    def _hashed_key(self, tenant_id: str, namespace: str, value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        return self._key(tenant_id, namespace, digest)

    @staticmethod
    def _positive_ttl(ttl_seconds: int) -> int:
        if ttl_seconds <= 0:
            raise RedisConfigurationError("Redis TTL must be positive.")
        return ttl_seconds

    @staticmethod
    def _validate_token_hash(token_hash: str) -> str:
        normalized = str(token_hash or "").strip().lower()
        if not _TOKEN_DIGEST_PATTERN.fullmatch(normalized):
            raise RedisConfigurationError("Token hash must be a lowercase SHA-256 digest.")
        return normalized

    def _call(self, operation: Callable[[Any], _RedisResult]) -> _RedisResult:
        """Translate dependency failures into a safe infrastructure error."""

        try:
            return operation(self.connection_factory.client())
        except (RedisConfigurationError, RedisDataError, RedisUnavailableError, RedisOperationError):
            raise
        except Exception as exc:
            raise RedisOperationError("Redis operation failed.") from exc

    def put_session(self, tenant_id: str, record: RedisSessionRecord, *, ttl_seconds: int) -> None:
        """Store session metadata with an expiry and no raw credential material."""

        ttl = self._positive_ttl(ttl_seconds)
        token_hash = self._validate_token_hash(record.token_hash)
        try:
            payload = encode_redis_session(
                {
                    "session_id": record.session_id,
                    "user_id": record.user_id,
                    "token_hash": token_hash,
                    "expires_at": record.expires_at,
                },
            ).text
        except PersistedJsonError as exc:
            raise RedisConfigurationError("Redis session data is invalid.") from exc
        self._call(
            lambda client: client.set(
                self._hashed_key(tenant_id, "session", record.session_id),
                payload,
                ex=ttl,
            )
        )

    def get_session(self, tenant_id: str, session_id: str) -> RedisSessionRecord | None:
        """Load one session, rejecting malformed persisted data."""

        value = self._call(lambda client: client.get(self._hashed_key(tenant_id, "session", session_id)))
        if value is None:
            return None
        try:
            payload = decode_redis_session(value).payload
            record = RedisSessionRecord(
                session_id=str(payload["session_id"]),
                user_id=str(payload["user_id"]),
                token_hash=str(payload["token_hash"]),
                expires_at=str(payload["expires_at"]),
            )
        except PersistedJsonError as exc:
            raise RedisDataError("Redis session data is malformed.") from exc
        if record.session_id != session_id:
            raise RedisDataError("Redis session identifier does not match its key.")
        return record

    def revoke_session(self, tenant_id: str, session_id: str, *, ttl_seconds: int) -> None:
        """Mark a session revoked until its normal expiry."""

        ttl = self._positive_ttl(ttl_seconds)
        self._call(
            lambda client: client.set(
                self._hashed_key(tenant_id, "revoked-session", session_id),
                "1",
                ex=ttl,
            )
        )

    def is_session_revoked(self, tenant_id: str, session_id: str) -> bool:
        """Return whether a session has a live revocation marker."""

        return (
            self._call(lambda client: client.get(self._hashed_key(tenant_id, "revoked-session", session_id)))
            is not None
        )

    def revoke_token_hash(self, tenant_id: str, token_hash: str, *, ttl_seconds: int) -> None:
        """Store a token revocation marker without accepting the raw token."""

        ttl = self._positive_ttl(ttl_seconds)
        digest = self._validate_token_hash(token_hash)
        self._call(lambda client: client.set(self._key(tenant_id, "revoked-token", digest), "1", ex=ttl))

    def is_token_hash_revoked(self, tenant_id: str, token_hash: str) -> bool:
        """Return whether a token digest has a live revocation marker."""

        digest = self._validate_token_hash(token_hash)
        return self._call(lambda client: client.get(self._key(tenant_id, "revoked-token", digest))) is not None

    def rate_limit_count(self, tenant_id: str, bucket: str, subject: str) -> int:
        """Read a rate-limit counter without incrementing it."""

        value = self._call(lambda client: client.get(self._hashed_key(tenant_id, f"rate-limit-{bucket}", subject)))
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RedisDataError("Redis rate-limit counter is malformed.") from exc

    def record_rate_limit_failure(self, tenant_id: str, bucket: str, subject: str, *, window_seconds: int) -> int:
        """Atomically increment a rate-limit counter and set its first-write expiry."""

        ttl = self._positive_ttl(window_seconds)
        key = self._hashed_key(tenant_id, f"rate-limit-{bucket}", subject)
        value = self._call(lambda client: client.eval(_INCREMENT_RATE_LIMIT_SCRIPT, 1, key, ttl))
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RedisDataError("Redis rate-limit result is malformed.") from exc

    def acquire_lock(self, tenant_id: str, lock_name: str, owner_token: str, *, ttl_milliseconds: int) -> bool:
        """Acquire a tenant-scoped lock with an expiry to prevent deadlocks."""

        if not owner_token or ttl_milliseconds <= 0:
            raise RedisConfigurationError("Lock owner token and TTL must be present and positive.")
        key = self._hashed_key(tenant_id, "lock", lock_name)
        return bool(self._call(lambda client: client.set(key, owner_token, nx=True, px=ttl_milliseconds)))

    def release_lock(self, tenant_id: str, lock_name: str, owner_token: str) -> bool:
        """Release a lock only when the caller still owns it."""

        if not owner_token:
            raise RedisConfigurationError("Lock owner token must be present.")
        key = self._hashed_key(tenant_id, "lock", lock_name)
        result = self._call(lambda client: client.eval(_RELEASE_LOCK_SCRIPT, 1, key, owner_token))
        return bool(int(result))

    def clear_rate_limit(self, tenant_id: str, bucket: str, subject: str) -> None:
        """Clear a failed-attempt counter after successful authentication."""

        self._call(lambda client: client.delete(self._hashed_key(tenant_id, f"rate-limit-{bucket}", subject)))

    def ping(self) -> bool:
        """Return the dependency health without exposing connection details."""

        return bool(self._call(lambda client: client.ping()))


class RedisPolicyCacheVersionStore:
    """Process-shared policy-cache generation backed by one Redis key.

    The generation contains no authorization data.  A mutation increments it;
    every cache process includes the current generation in its key, so stale
    entries become unreachable without requiring pub/sub subscribers.  Redis
    is an optional optimization boundary: callers must fall back to uncached
    policy evaluation when it is unavailable.
    """

    def __init__(self, connection_factory: RedisConnectionFactory) -> None:
        self.connection_factory = connection_factory
        self._key = f"{connection_factory.settings.key_prefix}:policy-cache:generation"

    def _call(self, operation: Callable[[Any], _RedisResult]) -> _RedisResult:
        try:
            return operation(self.connection_factory.client())
        except (RedisConfigurationError, RedisDataError, RedisUnavailableError, RedisOperationError):
            raise
        except Exception as exc:
            raise RedisOperationError("Redis policy-cache generation operation failed.") from exc

    def current_version(self) -> str:
        value = self._call(lambda client: client.get(self._key))
        if value is None:
            return "0"
        try:
            version = int(value)
        except (TypeError, ValueError) as exc:
            raise RedisDataError("Redis policy-cache generation is malformed.") from exc
        if version < 0:
            raise RedisDataError("Redis policy-cache generation is negative.")
        return str(version)

    def bump_version(self) -> str:
        value = self._call(lambda client: client.incr(self._key))
        try:
            version = int(value)
        except (TypeError, ValueError) as exc:
            raise RedisDataError("Redis policy-cache generation result is malformed.") from exc
        if version < 1:
            raise RedisDataError("Redis policy-cache generation did not advance.")
        return str(version)
