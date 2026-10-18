"""Bounded canonical evidence output; Core posting snapshot limits stay intact."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import cast

from reconforge.domain.finance_posting import FinancePostingError

MAX_EVIDENCE_BYTES = 67_108_864
MAX_EVIDENCE_NODES = 1_000_000
MAX_EVIDENCE_TRANSPORT_CHUNK_BYTES = 65_536


def evidence_chunks(value: object, *, maximum_bytes: int = MAX_EVIDENCE_BYTES) -> Iterator[bytes]:
    """Encode exact primitive values in the existing canonical JSON format."""
    if type(maximum_bytes) is not int or maximum_bytes < 1:
        raise FinancePostingError("accrual_deferral_evidence_invalid", "Evidence byte budget must be a positive exact integer.")
    pending = [value]
    nodes = 0
    while pending:
        item = pending.pop()
        nodes += 1
        if nodes > MAX_EVIDENCE_NODES:
            raise FinancePostingError("accrual_deferral_evidence_too_large", "Source evidence exceeds its explicit node budget.")
        if type(item) is dict:
            if not all(type(key) is str for key in item):
                raise FinancePostingError("accrual_deferral_evidence_invalid", "Evidence object keys must be exact strings.")
            pending.extend(item.values())
        elif type(item) in {list, tuple}:
            pending.extend(cast(list[object] | tuple[object, ...], item))
        elif item is not None and type(item) not in {str, bool, int}:
            raise FinancePostingError("accrual_deferral_evidence_invalid", "Evidence accepts exact integer and text primitives; other numeric types are refused.")
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    total = 0
    for piece in encoder.iterencode(value):
        encoded = piece.encode("utf8")
        total += len(encoded)
        if total > maximum_bytes:
            raise FinancePostingError("accrual_deferral_evidence_too_large", "Source evidence exceeds its explicit artifact byte budget.")
        yield encoded


def evidence_transport_chunks(
    value: object, *, maximum_bytes: int = MAX_EVIDENCE_BYTES,
    chunk_bytes: int = MAX_EVIDENCE_TRANSPORT_CHUNK_BYTES,
) -> Iterator[bytes]:
    """Coalesce canonical tokens for bounded wire delivery without changing bytes.

    A synchronous HTTP response schedules each iterator item separately. Keep
    that boundary at a bounded payload size rather than at each JSON token;
    the existing primitive, node and artifact-budget checks remain the encoder.
    """
    if type(chunk_bytes) is not int or not 1 <= chunk_bytes <= MAX_EVIDENCE_TRANSPORT_CHUNK_BYTES:
        raise FinancePostingError("accrual_deferral_evidence_invalid", "Evidence transport chunks require a positive bounded exact integer.")
    pending = bytearray()
    for encoded in evidence_chunks(value, maximum_bytes=maximum_bytes):
        offset = 0
        while offset < len(encoded):
            take = min(chunk_bytes - len(pending), len(encoded) - offset)
            pending.extend(memoryview(encoded)[offset:offset + take])
            offset += take
            if len(pending) == chunk_bytes:
                yield bytes(pending)
                pending.clear()
    if pending:
        yield bytes(pending)


def evidence_digest(value: object) -> str:
    digest = hashlib.sha256()
    for piece in evidence_chunks(value):
        digest.update(piece)
    return digest.hexdigest()


def evidence_size(value: object) -> int:
    return sum(len(piece) for piece in evidence_chunks(value))
