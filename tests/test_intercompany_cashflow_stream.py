"""Exact original-byte delivery regression for native evidence token streams."""

import hashlib
import json
from pathlib import Path

from reconforge.application.accrual_deferral_evidence import (
    evidence_chunks,
    evidence_digest,
    evidence_size,
    evidence_transport_chunks,
)

TRANSPORT_CHUNK_BYTES = 65_536


def test_original_native_capture_coalesces_44847_tokens_into_six_byte_exact_transport_items():
    path = Path(__file__).with_name("fixtures") / "intercompany-source-cashflow-native-v1.json"
    raw = path.read_bytes()
    assert len(raw) == 388945
    assert hashlib.sha256(raw).hexdigest() == "00afc06b175e4fd3958624c058db8f28acd798b4d4a852cd7cc968de2fd2cb3b"
    original = json.loads(raw)
    tokens = list(evidence_chunks(original))
    chunks = list(evidence_transport_chunks(original))
    assert len(tokens) == 44847 and len(chunks) == 6
    assert all(0 < len(chunk) <= TRANSPORT_CHUNK_BYTES for chunk in chunks)
    assert b"".join(chunks) == b"".join(tokens) == raw
    assert sum(map(len, chunks)) == evidence_size(original)
    assert hashlib.sha256(b"".join(chunks)).hexdigest() == evidence_digest(original)


def test_large_unicode_token_is_split_with_bounded_buffer_without_decoding_or_rounding_native_money():
    value = {"minor": 4500000000000000000, "reference": "مصدر أصلي\u0001" * 20000}
    tokens = list(evidence_chunks(value))
    assert max(map(len, tokens)) > TRANSPORT_CHUNK_BYTES
    chunks = list(evidence_transport_chunks(value))
    assert all(0 < len(chunk) <= TRANSPORT_CHUNK_BYTES for chunk in chunks)
    assert b"".join(chunks) == b"".join(tokens)
    assert b"4500000000000000000" in b"".join(chunks)
    assert sum(map(len, chunks)) == evidence_size(value)
