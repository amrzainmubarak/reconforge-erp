from __future__ import annotations

import importlib
import os
from uuid import uuid4

import pytest

from reconforge.connectors.writeback_receiver import WritebackReceiverError, WritebackReceiverRequest
from reconforge.connectors.writeback_receiver_postgres import (
    _SCHEMA,
    EFFECTS_TABLE,
    RECEIPTS_TABLE,
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


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_receiver_is_atomic_idempotent_and_digest_replayable() -> None:
    psycopg = pytest.importorskip("psycopg")
    app_dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", app_dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    receiver_id = "live-receiver-" + uuid4().hex[:12]
    request = _request(receiver_id=receiver_id, idempotency_key="idem-" + uuid4().hex[:12])
    admin = psycopg.connect(admin_dsn)
    try:
        admin.execute(_SCHEMA)
        admin.execute(f"GRANT USAGE ON SCHEMA reconforge_receiver_conformance TO {app_user}")
        admin.execute(
            f"GRANT SELECT, INSERT ON {RECEIPTS_TABLE}, {EFFECTS_TABLE} TO {app_user}"
        )
        admin.commit()
    finally:
        admin.close()

    store = PostgresWritebackReceiverStore(dsn=app_dsn)
    before = store.counts()
    applied = store.receive(request)
    digest_after_apply = store.canonical_history_digest()
    replayed = store.receive(request)
    after = store.counts()

    assert applied.disposition.value == "applied"
    assert replayed.disposition.value == "replayed"
    assert replayed.response == applied.response
    assert after.receipts == before.receipts + 1
    assert after.effects == before.effects + 1
    assert store.canonical_history_digest() == digest_after_apply

    with pytest.raises(psycopg.Error):
        connection = psycopg.connect(app_dsn)
        try:
            connection.execute(
                f"DELETE FROM {RECEIPTS_TABLE} WHERE receiver_id = %s",
                (receiver_id,),
            )
            connection.commit()
        finally:
            connection.close()
