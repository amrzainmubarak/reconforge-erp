from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from reconforge.infrastructure.redis import (
    RedisConfigurationError,
    RedisDataError,
    RedisSessionRecord,
    RedisSettings,
    TenantRedisStore,
)
from reconforge.io import persisted as persisted_module
from reconforge.io.persisted import (
    REDIS_SESSION_JSON_POLICY,
    REDIS_SESSION_JSON_PROFILE,
    REDIS_SESSION_SCHEMA,
    PersistedJsonError,
    decode_redis_session,
    encode_redis_session,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.calls: list[tuple[object, ...]] = []

    def set(self, key: str, value: str, **kwargs: object) -> bool:
        self.calls.append(("set", key, value, kwargs))
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        self.calls.append(("get", key))
        return self.values.get(key)


class _Factory:
    def __init__(self, client: _FakeRedis) -> None:
        self.settings = RedisSettings(url="rediss://redis.example")
        self._client = client

    def client(self) -> _FakeRedis:
        return self._client


def _payload() -> dict[str, str]:
    return {
        "session_id": "SES-1",
        "user_id": "USR-1",
        "token_hash": hashlib.sha256(b"synthetic-token").hexdigest(),
        "expires_at": "2030-01-01T00:00:00Z",
    }


def test_redis_session_round_trip_is_canonical_and_schema_valid() -> None:
    produced = encode_redis_session(_payload())
    decoded = decode_redis_session(produced.text)
    schema = json.loads(Path("docs/schemas/redis_session.schema.json").read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(decoded.payload)
    assert produced == decoded
    assert produced.text == json.dumps(_payload(), sort_keys=True, separators=(",", ":"))
    assert produced.profile_id == REDIS_SESSION_JSON_PROFILE
    assert produced.schema_id == REDIS_SESSION_SCHEMA


@pytest.mark.parametrize(
    ("stored", "code"),
    [
        ('{"session_id":"one","session_id":"two"}', "persisted_json_duplicate_key"),
        ('{"session_id":"SES-1","user_id":"USR-1","token_hash":NaN,"expires_at":"2030-01-01T00:00:00Z"}', "persisted_document_non_finite_number"),
        ("[]", "persisted_json_object_required"),
        ('{"session_id":"SES-1"}', "persisted_redis_session_fields_invalid"),
        (json.dumps({**_payload(), "unexpected": "value"}), "persisted_document_collection_limit"),
        (json.dumps({**_payload(), "user_id": 7}), "persisted_redis_session_field_invalid"),
        (json.dumps({**_payload(), "token_hash": "not-a-digest"}), "persisted_redis_session_token_hash_invalid"),
        (json.dumps({**_payload(), "expires_at": "2030-01-01T00:00:00"}), "persisted_redis_session_expiry_invalid"),
        (json.dumps({**_payload(), "expires_at": "2030-01-01T01:00:00+01:00"}), "persisted_redis_session_expiry_invalid"),
    ],
)
def test_redis_session_rejects_ambiguous_or_invalid_stored_values(stored: str, code: str) -> None:
    with pytest.raises(PersistedJsonError) as captured:
        decode_redis_session(stored)

    assert captured.value.code == code
    assert "SES-1" not in str(captured.value)


def test_redis_session_accepts_explicit_zero_offset_historical_timestamp() -> None:
    historical = {**_payload(), "expires_at": "2030-01-01T00:00:00+00:00"}

    decoded = decode_redis_session(json.dumps(historical))

    assert decoded.payload == historical


def test_session_store_preserves_tenant_key_ttl_and_payload_compatibility() -> None:
    client = _FakeRedis()
    store = TenantRedisStore(_Factory(client))
    payload = _payload()
    record = RedisSessionRecord(**payload)

    store.put_session("Tenant_A", record, ttl_seconds=317)
    tenant_a_key = store._hashed_key("tenant_a", "session", record.session_id)
    tenant_b_key = store._hashed_key("tenant_b", "session", record.session_id)

    assert client.calls == [("set", tenant_a_key, encode_redis_session(payload).text, {"ex": 317})]
    assert tenant_a_key != tenant_b_key
    assert store.get_session("tenant_a", record.session_id) == record
    assert store.get_session("tenant_b", record.session_id) is None


def test_session_producer_rejects_before_redis_client_access(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeRedis()
    store = TenantRedisStore(_Factory(client))
    monkeypatch.setattr(
        persisted_module,
        "REDIS_SESSION_JSON_POLICY",
        type(REDIS_SESSION_JSON_POLICY)(max_file_bytes=4),
    )

    with pytest.raises(RedisConfigurationError, match="session data is invalid"):
        store.put_session(
            "tenant-a",
            RedisSessionRecord(**_payload()),
            ttl_seconds=60,
        )

    assert client.calls == []
    assert client.values == {}


def test_corrupt_session_read_fails_without_replacement_or_mutation() -> None:
    client = _FakeRedis()
    store = TenantRedisStore(_Factory(client))
    key = store._hashed_key("tenant-a", "session", "SES-1")
    corrupt = '{"session_id":"SES-1","user_id":"USR-1","token_hash":"bad","expires_at":"2030-01-01T00:00:00Z"}'
    client.values[key] = corrupt

    with pytest.raises(RedisDataError, match="session data is malformed") as captured:
        store.get_session("tenant-a", "SES-1")

    assert "USR-1" not in str(captured.value)
    assert client.values[key] == corrupt
    assert client.calls == [("get", key)]


def test_session_identifier_mismatch_remains_fail_closed() -> None:
    client = _FakeRedis()
    store = TenantRedisStore(_Factory(client))
    key = store._hashed_key("tenant-a", "session", "SES-1")
    client.values[key] = encode_redis_session({**_payload(), "session_id": "SES-2"}).text

    with pytest.raises(RedisDataError, match="identifier does not match"):
        store.get_session("tenant-a", "SES-1")


def test_redis_session_call_sites_have_no_direct_decoder_and_encode_before_set() -> None:
    source = Path("reconforge/infrastructure/redis.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in {"put_session", "get_session"}
    }
    put_calls = [(ast.unparse(call.func), call.lineno) for call in ast.walk(functions["put_session"]) if isinstance(call, ast.Call)]
    get_calls = [ast.unparse(call.func) for call in ast.walk(functions["get_session"]) if isinstance(call, ast.Call)]

    assert "json.loads" not in get_calls
    assert "decode_redis_session" in get_calls
    assert next(line for name, line in put_calls if name == "encode_redis_session") < next(
        line for name, line in put_calls if name == "self._call"
    )


def test_redis_session_policy_has_narrow_explicit_resource_ceilings() -> None:
    assert REDIS_SESSION_JSON_POLICY.max_file_bytes == 16 * 1024
    assert REDIS_SESSION_JSON_POLICY.max_nodes == 16
    assert REDIS_SESSION_JSON_POLICY.max_depth == 2
    assert REDIS_SESSION_JSON_POLICY.max_collection_items == 4
    assert REDIS_SESSION_JSON_POLICY.max_scalar_characters == 256
