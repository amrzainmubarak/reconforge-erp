from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace

import pytest

from reconforge.api.routes.auth import (
    _clear_login_failures,
    _is_rate_limited_for_request,
    _record_failed_attempt,
)
from reconforge.infrastructure.redis import (
    RedisConfigurationError,
    RedisConnectionFactory,
    RedisDataError,
    RedisSessionRecord,
    RedisSettings,
    RedisUnavailableError,
    TenantRedisStore,
    _load_redis,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.calls: list[tuple[object, ...]] = []

    def set(self, key: str, value: str, **kwargs: object) -> bool:
        self.calls.append(("set", key, value, kwargs))
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        self.calls.append(("get", key))
        return self.values.get(key)

    def eval(self, script: str, key_count: int, key: str, argument: object) -> int:
        self.calls.append(("eval", script, key_count, key, argument))
        if "INCR" in script:
            value = int(self.values.get(key, "0")) + 1
            self.values[key] = str(value)
            return value
        if "DEL" in script and self.values.get(key) == str(argument):
            del self.values[key]
            return 1
        return 0

    def ping(self) -> bool:
        self.calls.append(("ping",))
        return True

    def close(self) -> None:
        self.calls.append(("close",))

    def delete(self, key: str) -> int:
        self.calls.append(("delete", key))
        return int(self.values.pop(key, None) is not None)


class _Factory:
    def __init__(self, client: _FakeRedis) -> None:
        self.settings = RedisSettings(url="rediss://redis.example", require_tls=True)
        self._client = client

    def client(self) -> _FakeRedis:
        return self._client


def test_redis_settings_require_tls_and_redact_url() -> None:
    with pytest.raises(RedisConfigurationError):
        RedisSettings(url="redis://localhost")

    settings = RedisSettings(url="rediss://user:secret@redis.example")
    assert "secret" not in repr(settings)
    assert "rediss://" not in repr(settings)


def test_redis_factory_is_lazy_and_configures_client(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    fake_client = _FakeRedis()

    class _Redis:
        class Redis:
            @staticmethod
            def from_url(url: str, **kwargs: object) -> _FakeRedis:
                calls.append((url, kwargs))
                return fake_client

    monkeypatch.setattr("reconforge.infrastructure.redis._load_redis", lambda: SimpleNamespace(Redis=_Redis.Redis))
    factory = RedisConnectionFactory(RedisSettings(url="rediss://redis.example"))
    assert calls == []
    assert factory.client() is fake_client
    assert factory.client() is fake_client
    assert calls == [
        (
            "rediss://redis.example",
            {
                "decode_responses": True,
                "socket_timeout": 5.0,
                "socket_connect_timeout": 5.0,
                "health_check_interval": 30,
            },
        )
    ]


def test_missing_redis_driver_has_install_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_driver(name: str) -> SimpleNamespace:
        raise ImportError(name)

    monkeypatch.setattr("reconforge.infrastructure.redis.importlib.import_module", missing_driver)
    with pytest.raises(RedisUnavailableError, match="server"):
        _load_redis()


def test_session_storage_contains_only_digest_and_is_tenant_scoped() -> None:
    client = _FakeRedis()
    store = TenantRedisStore(_Factory(client))
    token_hash = hashlib.sha256(b"raw-token").hexdigest()
    store.put_session(
        "Tenant_A",
        RedisSessionRecord("SES-1", "USR-1", token_hash, "2030-01-01T00:00:00Z"),
        ttl_seconds=300,
    )

    loaded = store.get_session("tenant_a", "SES-1")
    assert loaded is not None
    assert loaded.token_hash == token_hash
    assert all("raw-token" not in str(call) for call in client.calls)
    assert store.get_session("tenant_b", "SES-1") is None


def test_revocation_rate_limit_and_lock_operations_are_atomic_and_scoped() -> None:
    client = _FakeRedis()
    store = TenantRedisStore(_Factory(client))
    token_hash = hashlib.sha256(b"raw-token").hexdigest()

    store.revoke_token_hash("tenant-a", token_hash, ttl_seconds=60)
    assert store.is_token_hash_revoked("tenant-a", token_hash) is True
    assert store.is_token_hash_revoked("tenant-b", token_hash) is False

    assert store.rate_limit_count("tenant-a", "login", "10.0.0.1:user") == 0
    assert store.record_rate_limit_failure("tenant-a", "login", "10.0.0.1:user", window_seconds=60) == 1
    assert store.rate_limit_count("tenant-a", "login", "10.0.0.1:user") == 1

    assert store.acquire_lock("tenant-a", "reconcile:period-1", "owner-a", ttl_milliseconds=1000) is True
    assert store.acquire_lock("tenant-a", "reconcile:period-1", "owner-b", ttl_milliseconds=1000) is False
    assert store.release_lock("tenant-a", "reconcile:period-1", "owner-b") is False
    assert store.release_lock("tenant-a", "reconcile:period-1", "owner-a") is True
    assert store.ping() is True


def test_api_login_throttling_uses_redis_when_server_store_is_configured() -> None:
    client = _FakeRedis()
    store = TenantRedisStore(_Factory(client))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(redis_store=store)),
        headers={},
    )
    subject = "127.0.0.1:alice"

    assert _is_rate_limited_for_request(request, subject) is False
    for _ in range(8):
        _record_failed_attempt(request, subject)
    assert _is_rate_limited_for_request(request, subject) is True
    _clear_login_failures(request, subject)
    assert _is_rate_limited_for_request(request, subject) is False


def test_malformed_session_and_invalid_token_hash_fail_closed() -> None:
    client = _FakeRedis()
    store = TenantRedisStore(_Factory(client))
    with pytest.raises(RedisConfigurationError):
        store.revoke_token_hash("tenant-a", "not-a-digest", ttl_seconds=60)

    client.values[store._hashed_key("tenant-a", "session", "SES-1")] = "not-json"
    with pytest.raises(RedisDataError):
        store.get_session("tenant-a", "SES-1")


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_REDIS_URL"), reason="requires a live Redis service")
def test_live_redis_tenant_key_isolation() -> None:
    pytest.importorskip("redis")
    settings = RedisSettings(url=os.environ["RECONFORGE_TEST_REDIS_URL"], require_tls=False)
    factory = RedisConnectionFactory(settings)
    store = TenantRedisStore(factory)
    token_hash = hashlib.sha256(b"live-token").hexdigest()
    try:
        store.revoke_token_hash("test_redis_a", token_hash, ttl_seconds=60)
        assert store.is_token_hash_revoked("test_redis_a", token_hash) is True
        assert store.is_token_hash_revoked("test_redis_b", token_hash) is False
    finally:
        factory.client().delete(store._key("test_redis_a", "revoked-token", token_hash))
        factory.close()
