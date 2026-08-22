from __future__ import annotations

import importlib

import pytest

from reconforge.connectors.writeback_receiver import WritebackReceiverError, WritebackReceiverRequest
from reconforge.connectors.writeback_receiver_postgres import (
    _SCHEMA,
    PostgresWritebackReceiverStore,
    _load_psycopg,
    _receiver_key_digest,
)


def _request(*, receiver_id: str, idempotency_key: str) -> WritebackReceiverRequest:
    return WritebackReceiverRequest(
        schema_version="writeback-receiver-request-v1",
        receiver_id=receiver_id,
        operation="payment.create",
        idempotency_key=idempotency_key,
        payload_digest="a" * 64,
    )


def test_postgres_receiver_key_lock_identity_is_stable_and_unambiguous() -> None:
    first = _request(receiver_id="ab", idempotency_key="c")
    repeated = _request(receiver_id="ab", idempotency_key="c")
    concatenation_collision = _request(receiver_id="a", idempotency_key="bc")
    other_receiver = _request(receiver_id="other", idempotency_key="c")

    assert _receiver_key_digest(first) == _receiver_key_digest(repeated)
    assert len(
        {
            _receiver_key_digest(first),
            _receiver_key_digest(concatenation_collision),
            _receiver_key_digest(other_receiver),
        }
    ) == 3


@pytest.mark.parametrize(
    "arguments",
    (
        {"dsn": ""},
        {"dsn": "postgresql://synthetic", "connect_timeout_seconds": 0},
        {"dsn": "postgresql://synthetic", "connect_timeout_seconds": 61},
        {"dsn": "postgresql://synthetic", "statement_timeout_ms": 0},
        {"dsn": "postgresql://synthetic", "statement_timeout_ms": 120_001},
    ),
)
def test_postgres_receiver_refuses_invalid_connection_boundaries(arguments: dict[str, object]) -> None:
    with pytest.raises(WritebackReceiverError, match="writeback_receiver_postgres_.*_invalid"):
        PostgresWritebackReceiverStore(**arguments)  # type: ignore[arg-type]


def test_postgres_receiver_schema_is_atomic_digest_only_and_immutable() -> None:
    assert "PRIMARY KEY (receiver_id, idempotency_key)" in _SCHEMA
    assert "FOREIGN KEY (receiver_id, idempotency_key)" in _SCHEMA
    assert "BEFORE UPDATE OR DELETE" in _SCHEMA
    assert "writeback_receiver_receipt_immutable" in _SCHEMA
    assert "writeback_receiver_effect_immutable" in _SCHEMA
    assert "payload_digest ~ '^[0-9a-f]{64}$'" in _SCHEMA
    assert "payload BYTEA" not in _SCHEMA
    assert "secret" not in _SCHEMA.lower()


def test_postgres_dependency_failure_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def unavailable(name: str, package: str | None = None) -> object:
        if name == "psycopg":
            raise ImportError("synthetic missing dependency")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", unavailable)
    with pytest.raises(WritebackReceiverError, match="writeback_receiver_postgres_dependency_missing"):
        _load_psycopg()
