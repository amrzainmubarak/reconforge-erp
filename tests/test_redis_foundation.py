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
    RedisPolicyCacheVersionStore,
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

    def incr(self, key: str) -> int:
        self.calls.append(("incr", key))
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

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


class _RedisConnectionFailure(Exception):
    """Minimal redis-py-shaped connection failure without importing redis."""


_RedisConnectionFailure.__module__ = "redis.exceptions"
_RedisConnectionFailure.__name__ = "ConnectionError"


class _FailingRedis:
    def __getattr__(self, _name: str) -> object:
        raise _RedisConnectionFailure("synthetic disconnect")


class _ReconnectFactory:
    def __init__(self, clients: list[object]) -> None:
        self.settings = RedisSettings(url="rediss://redis.example", require_tls=True)
        self._clients = clients
        self._index = 0
        self.close_calls = 0

    def client(self) -> object:
        client = self._clients[min(self._index, len(self._clients) - 1)]
        self._index += 1
        return client

    def close(self) -> None:
        self.close_calls += 1


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


def test_policy_cache_generation_is_atomic_and_shared_between_instances() -> None:
    client = _FakeRedis()
    first = RedisPolicyCacheVersionStore(_Factory(client))
    second = RedisPolicyCacheVersionStore(_Factory(client))
    assert first.current_version() == "0"
    assert first.bump_version() == "1"
    assert second.current_version() == "1"
    assert second.bump_version() == "2"
    assert first.current_version() == "2"


def test_redis_read_reconnect_is_single_bounded_attempt_and_mutations_are_not_replayed() -> None:
    recovered_client = _FakeRedis()
    factory = _ReconnectFactory([_FailingRedis(), recovered_client])
    store = TenantRedisStore(factory)  # type: ignore[arg-type]

    assert store.get_session("tenant-a", "missing") is None
    assert factory.close_calls == 1
    assert factory._index == 2

    mutation_factory = _ReconnectFactory([_FailingRedis(), _FakeRedis()])
    mutation_store = TenantRedisStore(mutation_factory)  # type: ignore[arg-type]
    token_hash = hashlib.sha256(b"raw-token").hexdigest()
    with pytest.raises(RuntimeError, match="Redis operation failed"):
        mutation_store.revoke_token_hash("tenant-a", token_hash, ttl_seconds=60)
    assert mutation_factory.close_calls == 0
    assert mutation_factory._index == 1


def test_policy_cache_read_reconnect_preserves_generation_without_replaying_bump() -> None:
    recovered_client = _FakeRedis()
    recovered_client.values["reconforge:policy-cache:generation"] = "7"
    factory = _ReconnectFactory([_FailingRedis(), recovered_client])
    store = RedisPolicyCacheVersionStore(factory)  # type: ignore[arg-type]

    assert store.current_version() == "7"
    assert factory.close_calls == 1

    mutation_factory = _ReconnectFactory([_FailingRedis(), _FakeRedis()])
    mutation_store = RedisPolicyCacheVersionStore(mutation_factory)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="policy-cache generation operation failed"):
        mutation_store.bump_version()
    assert mutation_factory.close_calls == 0


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_REDIS_URL"), reason="requires a live Redis service")
def test_live_redis_tenant_key_isolation() -> None:
    pytest.importorskip("redis")
    settings = RedisSettings(url=os.environ["RECONFORGE_TEST_REDIS_URL"], require_tls=False)
    factory = RedisConnectionFactory(settings)
    store = TenantRedisStore(factory)
    token_hash = hashlib.sha256(b"live-token").hexdigest()
    session = RedisSessionRecord("SES-LIVE", "USR-LIVE", token_hash, "2030-01-01T00:00:00Z")
    session_key = store._hashed_key("test_redis_a", "session", session.session_id)
    try:
        store.revoke_token_hash("test_redis_a", token_hash, ttl_seconds=60)
        assert store.is_token_hash_revoked("test_redis_a", token_hash) is True
        assert store.is_token_hash_revoked("test_redis_b", token_hash) is False
        store.put_session("test_redis_a", session, ttl_seconds=60)
        assert store.get_session("test_redis_a", session.session_id) == session
        assert store.get_session("test_redis_b", session.session_id) is None
        assert 0 < int(factory.client().ttl(session_key)) <= 60
    finally:
        factory.client().delete(store._key("test_redis_a", "revoked-token", token_hash))
        factory.client().delete(session_key)
        factory.close()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_REDIS_URL"), reason="requires a live Redis service")
def test_live_redis_policy_cache_generation_invalidates_other_process_cache() -> None:
    pytest.importorskip("redis")
    settings = RedisSettings(url=os.environ["RECONFORGE_TEST_REDIS_URL"], require_tls=False)
    first_factory = RedisConnectionFactory(settings)
    second_factory = RedisConnectionFactory(settings)
    first = RedisPolicyCacheVersionStore(first_factory)
    second = RedisPolicyCacheVersionStore(second_factory)
    key = first._key
    client = first_factory.client()
    try:
        client.delete(key)
        assert first.current_version() == "0"
        assert first.bump_version() == "1"
        assert second.current_version() == "1"
        assert second.bump_version() == "2"
        assert first.current_version() == "2"
    finally:
        client.delete(key)
        first_factory.close()
        second_factory.close()


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_REDIS_URL"), reason="requires a live Redis service")
def test_live_redis_read_reconnects_after_connection_pool_disconnect() -> None:
    pytest.importorskip("redis")
    settings = RedisSettings(url=os.environ["RECONFORGE_TEST_REDIS_URL"], require_tls=False)
    factory = RedisConnectionFactory(settings)
    store = TenantRedisStore(factory)
    token_hash = hashlib.sha256(b"live-reconnect-token").hexdigest()
    session = RedisSessionRecord("SES-RECONNECT", "USR-RECONNECT", token_hash, "2030-01-01T00:00:00Z")
    session_key = store._hashed_key("test_redis_reconnect", "session", session.session_id)
    try:
        store.put_session("test_redis_reconnect", session, ttl_seconds=60)
        factory.client().connection_pool.disconnect()
        assert store.get_session("test_redis_reconnect", session.session_id) == session
    finally:
        factory.client().delete(session_key)
        factory.close()
