"""Bounded, exact persisted JSON for operational posting evidence."""

from __future__ import annotations

from hashlib import sha256

from reconforge.domain.finance_posting import MAX_SNAPSHOT_BYTES, validation_digest
from reconforge.io.persisted import PersistedJsonError, PersistedJsonObjectDocument
from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy, parse_json_document

POSTING_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=MAX_SNAPSHOT_BYTES,
    max_nodes=100_000,
    max_depth=12,
    max_collection_items=10_000,
    max_scalar_characters=2048,
    max_yaml_aliases=1,
)


def decode_posting_receipt(value: object) -> PersistedJsonObjectDocument:
    """Parse exact integer evidence; backing-record verification is repository-owned."""
    if not isinstance(value, str):
        raise PersistedJsonError("posting_json_text_required")
    try:
        payload = parse_json_document(value, reject_fractional_numbers=True, policy=POSTING_JSON_POLICY)
    except StructuredDocumentError as exc:
        raise PersistedJsonError(f"persisted_{exc.code}") from exc
    if not isinstance(payload, dict):
        raise PersistedJsonError("posting_json_object_required")
    encoded = value.encode("utf-8")
    return PersistedJsonObjectDocument(
        payload,
        value,
        len(encoded),
        sha256(encoded).hexdigest(),
        "finance-posting-json-v1",
        "finance-posting-command-result-v1",
    )


def decode_posting_snapshot(value: object) -> PersistedJsonObjectDocument:
    document = decode_posting_receipt(value)
    try:
        validation_digest(document.payload)
    except ValueError as exc:
        raise PersistedJsonError("posting_snapshot_invalid") from exc
    return PersistedJsonObjectDocument(
        document.payload,
        document.text,
        document.size_bytes,
        document.checksum_sha256,
        document.profile_id,
        "finance-entry-review-v1",
    )
