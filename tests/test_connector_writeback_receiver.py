from __future__ import annotations

import hashlib
import multiprocessing
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from reconforge.connectors.writeback_receiver import (
    SQLiteWritebackReceiverStore,
    WritebackReceiverDisposition,
    WritebackReceiverError,
    WritebackReceiverRequest,
)

PAYLOAD = b'{"amount":"10.00","currency":"USD","reference":"receiver-1"}'
DEFAULT_KEY = "-".join(("receiver", "idempotency", "1"))


def _request(**updates: object) -> WritebackReceiverRequest:
    values: dict[str, object] = {
        "schema_version": "writeback-receiver-request-v1",
        "receiver_id": "synthetic-provider",
        "operation": "payment.create",
        "idempotency_key": DEFAULT_KEY,
        "payload_digest": hashlib.sha256(PAYLOAD).hexdigest(),
    }
    values.update(updates)
    return WritebackReceiverRequest.model_validate(values)


def _receive_worker(
    database: str,
    request_data: dict[str, Any],
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    start.wait(timeout=20)
    request = WritebackReceiverRequest.model_validate(request_data)
    result = SQLiteWritebackReceiverStore(Path(database)).receive(request)
    results.put((result.disposition.value, result.response_body.decode("ascii")))


def _crash_after_receiver_commit(database: str, request_data: dict[str, Any]) -> None:
    request = WritebackReceiverRequest.model_validate(request_data)
    result = SQLiteWritebackReceiverStore(Path(database)).receive(request)
    if result.disposition is not WritebackReceiverDisposition.APPLIED:
        os._exit(91)
    os._exit(0)


def test_receiver_request_is_closed_and_deterministic() -> None:
    request = _request()
    assert request.request_digest == _request().request_digest
    with pytest.raises(ValidationError):
        _request(undeclared=True)
    with pytest.raises(ValidationError):
        _request(idempotency_key="unsafe key")
    with pytest.raises(ValidationError):
        _request(payload_digest="0" * 63)


@given(
    key=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=40),
    first_payload=st.binary(min_size=1, max_size=128),
    second_payload=st.binary(min_size=1, max_size=128),
)
def test_receiver_request_digest_is_permutation_stable_and_payload_separating(
    key: str, first_payload: bytes, second_payload: bytes
) -> None:
    first = _request(idempotency_key=key, payload_digest=hashlib.sha256(first_payload).hexdigest())
    reordered = WritebackReceiverRequest.model_validate(
        {
            "payload_digest": first.payload_digest,
            "idempotency_key": first.idempotency_key,
            "operation": first.operation,
            "receiver_id": first.receiver_id,
            "schema_version": first.schema_version,
        }
    )
    assert first.request_digest == reordered.request_digest
    if first_payload != second_payload:
        changed = _request(idempotency_key=key, payload_digest=hashlib.sha256(second_payload).hexdigest())
        assert first.request_digest != changed.request_digest


def test_receiver_applies_once_replays_exact_response_and_stores_no_payload(tmp_path: Path) -> None:
    database = tmp_path / "receiver.db"
    store = SQLiteWritebackReceiverStore(database)
    store.initialize()
    request = _request()

    applied = store.receive(request)
    replayed = store.receive(request)

    assert applied.disposition is WritebackReceiverDisposition.APPLIED
    assert replayed.disposition is WritebackReceiverDisposition.REPLAYED
    assert applied.request_digest == request.request_digest
    assert applied.response == replayed.response
    assert applied.response_body == replayed.response_body
    assert store.counts().receipts == 1
    assert store.counts().effects == 1
    assert PAYLOAD not in database.read_bytes()


@pytest.mark.parametrize(
    "conflict",
    (
        {"payload_digest": hashlib.sha256(b"different").hexdigest()},
        {"operation": "payment.reverse"},
    ),
)
def test_receiver_refuses_key_retargeting_without_extra_effect(
    tmp_path: Path, conflict: dict[str, object]
) -> None:
    store = SQLiteWritebackReceiverStore(tmp_path / "receiver.db")
    store.initialize()
    store.receive(_request())

    with pytest.raises(WritebackReceiverError, match="idempotency_conflict"):
        store.receive(_request(**conflict))

    assert store.counts().receipts == 1
    assert store.counts().effects == 1


def test_receiver_history_is_immutable_at_the_database_boundary(tmp_path: Path) -> None:
    database = tmp_path / "receiver.db"
    store = SQLiteWritebackReceiverStore(database)
    store.initialize()
    store.receive(_request())

    connection = sqlite3.connect(database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="receipt_immutable"):
            connection.execute("UPDATE writeback_receiver_receipts SET operation = 'changed'")
        with pytest.raises(sqlite3.IntegrityError, match="effect_immutable"):
            connection.execute("DELETE FROM writeback_receiver_effects")
    finally:
        connection.close()

    assert store.counts().receipts == 1
    assert store.counts().effects == 1


def test_receiver_serializes_concurrent_processes_to_one_effect(tmp_path: Path) -> None:
    database = tmp_path / "receiver.db"
    store = SQLiteWritebackReceiverStore(database)
    store.initialize()
    request_data = _request(idempotency_key="receiver-concurrent-1").model_dump(mode="json")
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(target=_receive_worker, args=(str(database), request_data, start, results))
        for _ in range(6)
    ]

    for process in processes:
        process.start()
    start.set()
    observed = [results.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    dispositions = [item[0] for item in observed]
    assert dispositions.count(WritebackReceiverDisposition.APPLIED.value) == 1
    assert dispositions.count(WritebackReceiverDisposition.REPLAYED.value) == 5
    assert len({item[1] for item in observed}) == 1
    assert store.counts().receipts == 1
    assert store.counts().effects == 1


def test_receiver_retry_after_commit_response_crash_replays_without_second_effect(tmp_path: Path) -> None:
    database = tmp_path / "receiver.db"
    store = SQLiteWritebackReceiverStore(database)
    store.initialize()
    request = _request(idempotency_key="receiver-crash-1")
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_crash_after_receiver_commit,
        args=(str(database), request.model_dump(mode="json")),
    )

    process.start()
    process.join(timeout=30)
    assert process.exitcode == 0

    replayed = store.receive(request)
    assert replayed.disposition is WritebackReceiverDisposition.REPLAYED
    assert store.counts().receipts == 1
    assert store.counts().effects == 1
