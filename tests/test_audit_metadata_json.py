from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from reconforge.io.persisted import (
    AUDIT_METADATA_JSON_POLICY,
    AUDIT_METADATA_JSON_PROFILE,
    AUDIT_METADATA_SCHEMA,
    PersistedJsonError,
    decode_audit_metadata,
    encode_audit_metadata,
)

ROOT = Path(__file__).resolve().parents[1]


def test_audit_metadata_round_trip_preserves_canonical_historical_bytes() -> None:
    payload = {"source": "test", "attempt": 2, "display_ratio": 1.25}

    encoded = encode_audit_metadata(payload)
    decoded = decode_audit_metadata(encoded.text)
    schema = json.loads((ROOT / "docs/schemas/audit_metadata.schema.json").read_text(encoding="utf-8"))

    assert encoded.text == '{"attempt":2,"display_ratio":1.25,"source":"test"}'
    assert decoded.payload == payload
    assert decoded.checksum_sha256 == encoded.checksum_sha256
    assert decoded.profile_id == AUDIT_METADATA_JSON_PROFILE
    assert decoded.schema_id == AUDIT_METADATA_SCHEMA
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(decoded.payload)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"source":"one","source":"two"}', "persisted_json_duplicate_key"),
        ('{"value":NaN}', "persisted_document_non_finite_number"),
        ('{"value":Infinity}', "persisted_document_non_finite_number"),
        ('[]', "persisted_json_object_required"),
    ],
)
def test_audit_metadata_decoder_rejects_ambiguous_or_invalid_values(text: str, code: str) -> None:
    with pytest.raises(PersistedJsonError) as captured:
        decode_audit_metadata(text)
    assert captured.value.code == code


def test_audit_metadata_encoder_rejects_nonfinite_values_and_cycles() -> None:
    with pytest.raises(PersistedJsonError):
        encode_audit_metadata({"value": float("nan")})

    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(PersistedJsonError) as captured:
        encode_audit_metadata(cyclic)
    assert captured.value.code == "persisted_json_cycle_forbidden"


def test_audit_metadata_profile_has_explicit_resource_ceilings() -> None:
    assert AUDIT_METADATA_JSON_POLICY.max_file_bytes == 4 * 1024 * 1024
    assert AUDIT_METADATA_JSON_POLICY.max_nodes == 100_000
    assert AUDIT_METADATA_JSON_POLICY.max_depth == 32
    assert AUDIT_METADATA_JSON_POLICY.max_collection_items == 25_000
    assert AUDIT_METADATA_JSON_POLICY.max_scalar_characters == 256 * 1024


def test_audit_metadata_consumers_have_no_direct_json_decoder() -> None:
    forbidden: list[str] = []
    targets = (
        "reconforge/audit/events.py",
        "reconforge/infrastructure/postgres_ledger.py",
    )
    for relative in targets:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            if ast.unparse(call.func) in {"json.load", "json.loads"}:
                forbidden.append(f"{relative}:{call.lineno}")
    assert forbidden == []
