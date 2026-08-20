"""Bounded contracts for JSON values already stored by ReconForge."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, NoReturn

from reconforge.io.structured import (
    StructuredDocumentError,
    StructuredDocumentPolicy,
    parse_json_document,
)

FINANCIAL_IDEMPOTENCY_JSON_PROFILE = "financial-idempotency-json-v1"
FINANCIAL_IDEMPOTENCY_RESPONSE_SCHEMA = "financial-idempotency-response-object-v1"
AUDIT_METADATA_JSON_PROFILE = "audit-metadata-json-v1"
AUDIT_METADATA_SCHEMA = "audit-metadata-object-v1"
POSTGRES_OUTBOX_JSON_PROFILE = "postgres-outbox-payload-json-v1"
POSTGRES_OUTBOX_PAYLOAD_SCHEMA = "postgres-outbox-payload-object-v1"
POSTGRES_RECONCILIATION_RULE_JSON_PROFILE = "postgres-reconciliation-rule-json-v1"
POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_PROFILE = "postgres-reconciliation-attributes-json-v1"
POSTGRES_RECONCILIATION_LINEAGE_JSON_PROFILE = "postgres-reconciliation-lineage-json-v1"
POSTGRES_RECONCILIATION_EVIDENCE_JSON_PROFILE = "postgres-reconciliation-evidence-json-v1"
POSTGRES_RECONCILIATION_OBJECT_SCHEMA = "postgres-reconciliation-object-v1"
SQLITE_MATCHING_RULE_JSON_PROFILE = "sqlite-matching-rule-json-v1"
SQLITE_MATCHING_RULE_SCHEMA = "sqlite-matching-rule-object-v1"
REDIS_SESSION_JSON_PROFILE = "redis-session-json-v1"
REDIS_SESSION_SCHEMA = "redis-session-object-v1"
SQLITE_LEGACY_IMPORT_SUMMARY_JSON_PROFILE = "sqlite-legacy-import-summary-json-v1"
SQLITE_LEGACY_IMPORT_SUMMARY_SCHEMA = "sqlite-legacy-import-summary-object-v1"
SQLITE_MATCHING_LINEAGE_JSON_PROFILE = "sqlite-matching-lineage-json-v1"
SQLITE_MATCHING_LINEAGE_SCHEMA = "sqlite-matching-lineage-object-v1"
CURRENCY_REGISTRY_SNAPSHOT_JSON_PROFILE = "currency-registry-snapshot-json-v1"
CURRENCY_REGISTRY_SNAPSHOT_SCHEMA = "currency-registry-snapshot-object-v1"
SQLITE_RETAIL_SETTLEMENT_JSON_PROFILE = "sqlite-retail-settlement-json-v1"
SQLITE_RETAIL_SETTLEMENT_SCHEMA = "retail-settlement-report-object-v1"
SQLITE_PROFESSIONAL_INVOICE_PAYMENT_JSON_PROFILE = "sqlite-professional-invoice-payment-json-v1"
SQLITE_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA = "professional-invoice-payment-report-object-v1"
SQLITE_MANUFACTURING_COST_CONTROL_JSON_PROFILE = "sqlite-manufacturing-cost-control-json-v1"
SQLITE_MANUFACTURING_COST_CONTROL_SCHEMA = "manufacturing-cost-control-report-object-v1"
SQLITE_BANK_STATEMENT_CONTROL_JSON_PROFILE = "sqlite-bank-statement-control-json-v1"
SQLITE_BANK_STATEMENT_CONTROL_SCHEMA = "bank-statement-control-report-object-v1"
CONSOLIDATION_WORKSHEET_JSON_PROFILE = "consolidation-worksheet-json-v1"
CONSOLIDATION_WORKSHEET_SCHEMA = "consolidation-worksheet-v1"
FINANCIAL_IDEMPOTENCY_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
AUDIT_METADATA_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
POSTGRES_OUTBOX_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
POSTGRES_RECONCILIATION_RULE_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
# Preserve the pre-existing producer byte ceiling for canonical input attributes.
POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=100_000,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=100_000,
    max_yaml_aliases=1,
)
POSTGRES_RECONCILIATION_LINEAGE_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
POSTGRES_RECONCILIATION_EVIDENCE_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
SQLITE_MATCHING_RULE_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
REDIS_SESSION_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=16 * 1024,
    max_nodes=16,
    max_depth=2,
    max_collection_items=4,
    max_scalar_characters=256,
    max_yaml_aliases=1,
)
SQLITE_LEGACY_IMPORT_SUMMARY_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
SQLITE_MATCHING_LINEAGE_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=4 * 1024 * 1024,
    max_nodes=100_000,
    max_depth=32,
    max_collection_items=25_000,
    max_scalar_characters=256 * 1024,
    max_yaml_aliases=1,
)
CURRENCY_REGISTRY_SNAPSHOT_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=1_000_000,
    max_nodes=20_000,
    max_depth=16,
    max_collection_items=1_000,
    max_scalar_characters=100_000,
    max_yaml_aliases=1,
)
CONSOLIDATION_WORKSHEET_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=32 * 1024 * 1024,
    max_nodes=1_000_000,
    max_depth=64,
    max_collection_items=150_000,
    max_scalar_characters=1024 * 1024,
    max_yaml_aliases=1,
)
_REDIS_SESSION_FIELDS = frozenset({"session_id", "user_id", "token_hash", "expires_at"})


class PersistedJsonError(ValueError):
    """Safe rejection containing only a stable non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Persisted JSON rejected ({code}).")


@dataclass(frozen=True)
class PersistedJsonObjectDocument:
    """One bounded object plus the exact canonical or stored-text fingerprint."""

    payload: dict[str, Any]
    text: str
    size_bytes: int
    checksum_sha256: str
    profile_id: str
    schema_id: str


def _reject(code: str) -> NoReturn:
    raise PersistedJsonError(code)


def _preflight_value(
    value: object,
    policy: StructuredDocumentPolicy,
    *,
    reject_floats: bool,
) -> None:
    """Bound producer work before JSON allocation."""

    stack: list[tuple[object, int, bool]] = [(value, 1, False)]
    active_containers: set[int] = set()
    nodes = 0
    while stack:
        current, depth, exiting = stack.pop()
        if exiting:
            active_containers.remove(id(current))
            continue
        nodes += 1
        if nodes > policy.max_nodes:
            _reject("persisted_json_node_limit")
        if depth > policy.max_depth:
            _reject("persisted_json_depth_limit")
        if reject_floats and isinstance(current, float):
            _reject("persisted_json_fractional_number_forbidden")

        children: list[object] | None = None
        if isinstance(current, Mapping):
            if len(current) > policy.max_collection_items:
                _reject("persisted_json_collection_limit")
            children = []
            for key, item in current.items():
                if not isinstance(key, str):
                    _reject("persisted_json_key_invalid")
                children.extend((key, item))
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if len(current) > policy.max_collection_items:
                _reject("persisted_json_collection_limit")
            children = list(current)

        if children is not None:
            identity = id(current)
            if identity in active_containers:
                _reject("persisted_json_cycle_forbidden")
            active_containers.add(identity)
            stack.append((current, depth, True))
            stack.extend((child, depth + 1, False) for child in reversed(children))
            continue

        scalar = current if isinstance(current, str) else str(current)
        if len(scalar) > policy.max_scalar_characters:
            _reject("persisted_json_scalar_limit")


def _document(
    text: str,
    *,
    policy: StructuredDocumentPolicy,
    profile_id: str,
    schema_id: str,
    reject_fractional_numbers: bool,
) -> PersistedJsonObjectDocument:
    try:
        payload = parse_json_document(
            text,
            reject_fractional_numbers=reject_fractional_numbers,
            policy=policy,
        )
    except StructuredDocumentError as exc:
        raise PersistedJsonError(f"persisted_{exc.code}") from exc
    if not isinstance(payload, dict):
        _reject("persisted_json_object_required")
    encoded = text.encode("utf-8", errors="strict")
    return PersistedJsonObjectDocument(
        payload=payload,
        text=text,
        size_bytes=len(encoded),
        checksum_sha256=sha256(encoded).hexdigest(),
        profile_id=profile_id,
        schema_id=schema_id,
    )


def _validated_redis_session_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(payload)
    if set(value) != _REDIS_SESSION_FIELDS:
        _reject("persisted_redis_session_fields_invalid")
    if not all(isinstance(item, str) for item in value.values()):
        _reject("persisted_redis_session_field_invalid")

    for field_name in ("session_id", "user_id"):
        text = value[field_name]
        if (
            not text.strip()
            or len(text) > 256
            or any(ord(character) < 32 or ord(character) == 127 for character in text)
        ):
            _reject("persisted_redis_session_identifier_invalid")

    token_hash = value["token_hash"]
    if len(token_hash) != 64 or any(character not in "0123456789abcdef" for character in token_hash):
        _reject("persisted_redis_session_token_hash_invalid")

    expires_at = value["expires_at"]
    if not expires_at or len(expires_at) > 64 or "T" not in expires_at or not expires_at.endswith(("Z", "+00:00")):
        _reject("persisted_redis_session_expiry_invalid")
    try:
        parsed_expiry = datetime.fromisoformat(
            expires_at.removesuffix("Z") + ("+00:00" if expires_at.endswith("Z") else ""),
        )
    except ValueError as exc:
        raise PersistedJsonError("persisted_redis_session_expiry_invalid") from exc
    if parsed_expiry.utcoffset() != timedelta(0):
        _reject("persisted_redis_session_expiry_invalid")
    return value


def decode_redis_session(value: object) -> PersistedJsonObjectDocument:
    """Decode one tenant-scoped Redis session under its closed v1 contract."""

    document = _document(
        str(value),
        policy=REDIS_SESSION_JSON_POLICY,
        profile_id=REDIS_SESSION_JSON_PROFILE,
        schema_id=REDIS_SESSION_SCHEMA,
        reject_fractional_numbers=True,
    )
    _validated_redis_session_payload(document.payload)
    return document


def encode_redis_session(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize one closed Redis session object before client access."""

    value = _validated_redis_session_payload(payload)
    _preflight_value(value, REDIS_SESSION_JSON_POLICY, reject_floats=True)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=REDIS_SESSION_JSON_POLICY,
        profile_id=REDIS_SESSION_JSON_PROFILE,
        schema_id=REDIS_SESSION_SCHEMA,
        reject_fractional_numbers=True,
    )


def _encode_sqlite_export_object(
    payload: Mapping[str, Any],
    *,
    policy: StructuredDocumentPolicy,
    profile_id: str,
    schema_id: str,
    ensure_ascii: bool,
) -> PersistedJsonObjectDocument:
    try:
        value = dict(payload)
    except (TypeError, ValueError) as exc:
        raise PersistedJsonError("persisted_json_object_required") from exc
    _preflight_value(value, policy, reject_floats=False)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=ensure_ascii,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=policy,
        profile_id=profile_id,
        schema_id=schema_id,
        reject_fractional_numbers=False,
    )


def decode_sqlite_legacy_import_summary(value: object) -> PersistedJsonObjectDocument:
    """Decode one legacy-import summary without changing valid stored bytes."""

    return _document(
        str(value),
        policy=SQLITE_LEGACY_IMPORT_SUMMARY_JSON_POLICY,
        profile_id=SQLITE_LEGACY_IMPORT_SUMMARY_JSON_PROFILE,
        schema_id=SQLITE_LEGACY_IMPORT_SUMMARY_SCHEMA,
        reject_fractional_numbers=False,
    )


def encode_sqlite_legacy_import_summary(
    payload: Mapping[str, Any],
) -> PersistedJsonObjectDocument:
    """Canonicalize one bridge summary using its historical compact ASCII text."""

    return _encode_sqlite_export_object(
        payload,
        policy=SQLITE_LEGACY_IMPORT_SUMMARY_JSON_POLICY,
        profile_id=SQLITE_LEGACY_IMPORT_SUMMARY_JSON_PROFILE,
        schema_id=SQLITE_LEGACY_IMPORT_SUMMARY_SCHEMA,
        ensure_ascii=True,
    )


def decode_sqlite_matching_lineage(value: object) -> PersistedJsonObjectDocument:
    """Decode one SQLite match-result lineage object under bounded limits."""

    return _document(
        str(value),
        policy=SQLITE_MATCHING_LINEAGE_JSON_POLICY,
        profile_id=SQLITE_MATCHING_LINEAGE_JSON_PROFILE,
        schema_id=SQLITE_MATCHING_LINEAGE_SCHEMA,
        reject_fractional_numbers=False,
    )


def decode_currency_registry_snapshot(value: object) -> PersistedJsonObjectDocument:
    """Decode one persisted currency registry snapshot under bounded JSON limits."""

    return _document(
        str(value),
        policy=CURRENCY_REGISTRY_SNAPSHOT_JSON_POLICY,
        profile_id=CURRENCY_REGISTRY_SNAPSHOT_JSON_PROFILE,
        schema_id=CURRENCY_REGISTRY_SNAPSHOT_SCHEMA,
        reject_fractional_numbers=True,
    )


def encode_sqlite_matching_lineage(
    payload: Mapping[str, Any],
) -> PersistedJsonObjectDocument:
    """Canonicalize lineage using the established compact UTF-8 representation."""

    return _encode_sqlite_export_object(
        payload,
        policy=SQLITE_MATCHING_LINEAGE_JSON_POLICY,
        profile_id=SQLITE_MATCHING_LINEAGE_JSON_PROFILE,
        schema_id=SQLITE_MATCHING_LINEAGE_SCHEMA,
        ensure_ascii=False,
    )


def decode_financial_idempotency_response(value: object) -> PersistedJsonObjectDocument:
    """Decode one stored AP/AR idempotency response under the v1 contract."""

    return _document(
        str(value),
        policy=FINANCIAL_IDEMPOTENCY_JSON_POLICY,
        profile_id=FINANCIAL_IDEMPOTENCY_JSON_PROFILE,
        schema_id=FINANCIAL_IDEMPOTENCY_RESPONSE_SCHEMA,
        reject_fractional_numbers=True,
    )


def encode_financial_idempotency_response(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize one AP/AR response before it enters the transaction table."""

    value = dict(payload)
    _preflight_value(value, FINANCIAL_IDEMPOTENCY_JSON_POLICY, reject_floats=True)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=FINANCIAL_IDEMPOTENCY_JSON_POLICY,
        profile_id=FINANCIAL_IDEMPOTENCY_JSON_PROFILE,
        schema_id=FINANCIAL_IDEMPOTENCY_RESPONSE_SCHEMA,
        reject_fractional_numbers=True,
    )


def decode_consolidation_worksheet(value: object) -> PersistedJsonObjectDocument:
    """Decode one persisted worksheet under the bounded v1 profile."""

    return _document(
        str(value),
        policy=CONSOLIDATION_WORKSHEET_JSON_POLICY,
        profile_id=CONSOLIDATION_WORKSHEET_JSON_PROFILE,
        schema_id=CONSOLIDATION_WORKSHEET_SCHEMA,
        reject_fractional_numbers=True,
    )


def encode_consolidation_worksheet(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize a replay-valid worksheet before database persistence."""

    value = dict(payload)
    _preflight_value(value, CONSOLIDATION_WORKSHEET_JSON_POLICY, reject_floats=True)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=CONSOLIDATION_WORKSHEET_JSON_POLICY,
        profile_id=CONSOLIDATION_WORKSHEET_JSON_PROFILE,
        schema_id=CONSOLIDATION_WORKSHEET_SCHEMA,
        reject_fractional_numbers=True,
    )


def decode_audit_metadata(value: object) -> PersistedJsonObjectDocument:
    """Decode stored audit metadata without inventing a replacement value."""

    return _document(
        str(value),
        policy=AUDIT_METADATA_JSON_POLICY,
        profile_id=AUDIT_METADATA_JSON_PROFILE,
        schema_id=AUDIT_METADATA_SCHEMA,
        reject_fractional_numbers=False,
    )


def encode_audit_metadata(payload: Mapping[str, Any] | None) -> PersistedJsonObjectDocument:
    """Canonicalize bounded audit metadata before hashing and persistence."""

    value = dict(payload or {})
    _preflight_value(value, AUDIT_METADATA_JSON_POLICY, reject_floats=False)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=AUDIT_METADATA_JSON_POLICY,
        profile_id=AUDIT_METADATA_JSON_PROFILE,
        schema_id=AUDIT_METADATA_SCHEMA,
        reject_fractional_numbers=False,
    )


def decode_postgres_outbox_payload(value: object) -> PersistedJsonObjectDocument:
    """Decode one stored PostgreSQL outbox payload under the v1 contract."""

    if isinstance(value, Mapping):
        return encode_postgres_outbox_payload(value)
    return _document(
        str(value),
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=POSTGRES_OUTBOX_JSON_PROFILE,
        schema_id=POSTGRES_OUTBOX_PAYLOAD_SCHEMA,
        reject_fractional_numbers=False,
    )


def decode_sqlite_retail_settlement(value: object) -> PersistedJsonObjectDocument:
    """Decode one bounded persisted retail settlement report object."""

    return _document(
        str(value),
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=SQLITE_RETAIL_SETTLEMENT_JSON_PROFILE,
        schema_id=SQLITE_RETAIL_SETTLEMENT_SCHEMA,
        reject_fractional_numbers=True,
    )


def encode_sqlite_retail_settlement(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize a retail settlement report before SQLite persistence."""

    try:
        value = dict(payload)
    except (TypeError, ValueError) as exc:
        raise PersistedJsonError("persisted_json_object_required") from exc
    _preflight_value(value, POSTGRES_OUTBOX_JSON_POLICY, reject_floats=True)
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=SQLITE_RETAIL_SETTLEMENT_JSON_PROFILE,
        schema_id=SQLITE_RETAIL_SETTLEMENT_SCHEMA,
        reject_fractional_numbers=True,
    )


def decode_sqlite_professional_invoice_payment(value: object) -> PersistedJsonObjectDocument:
    """Decode one bounded persisted professional invoice/payment report."""

    return _document(
        str(value),
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=SQLITE_PROFESSIONAL_INVOICE_PAYMENT_JSON_PROFILE,
        schema_id=SQLITE_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA,
        reject_fractional_numbers=True,
    )


def encode_sqlite_professional_invoice_payment(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize a professional invoice/payment report before SQLite persistence."""

    try:
        value = dict(payload)
    except (TypeError, ValueError) as exc:
        raise PersistedJsonError("persisted_json_object_required") from exc
    _preflight_value(value, POSTGRES_OUTBOX_JSON_POLICY, reject_floats=True)
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=SQLITE_PROFESSIONAL_INVOICE_PAYMENT_JSON_PROFILE,
        schema_id=SQLITE_PROFESSIONAL_INVOICE_PAYMENT_SCHEMA,
        reject_fractional_numbers=True,
    )


def decode_sqlite_manufacturing_cost_control(value: object) -> PersistedJsonObjectDocument:
    """Decode one bounded persisted manufacturing cost-control report."""

    return _document(
        str(value),
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=SQLITE_MANUFACTURING_COST_CONTROL_JSON_PROFILE,
        schema_id=SQLITE_MANUFACTURING_COST_CONTROL_SCHEMA,
        reject_fractional_numbers=True,
    )


def encode_sqlite_manufacturing_cost_control(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize a manufacturing cost-control report before persistence."""

    try:
        value = dict(payload)
    except (TypeError, ValueError) as exc:
        raise PersistedJsonError("persisted_json_object_required") from exc
    _preflight_value(value, POSTGRES_OUTBOX_JSON_POLICY, reject_floats=True)
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=SQLITE_MANUFACTURING_COST_CONTROL_JSON_PROFILE,
        schema_id=SQLITE_MANUFACTURING_COST_CONTROL_SCHEMA,
        reject_fractional_numbers=True,
    )


def decode_sqlite_bank_statement_control(value: object) -> PersistedJsonObjectDocument:
    """Decode one bounded persisted bank-statement control report."""

    return _document(
        str(value),
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=SQLITE_BANK_STATEMENT_CONTROL_JSON_PROFILE,
        schema_id=SQLITE_BANK_STATEMENT_CONTROL_SCHEMA,
        reject_fractional_numbers=True,
    )


def encode_sqlite_bank_statement_control(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize a bank-statement control report before SQLite persistence."""

    try:
        value = dict(payload)
    except (TypeError, ValueError) as exc:
        raise PersistedJsonError("persisted_json_object_required") from exc
    _preflight_value(value, POSTGRES_OUTBOX_JSON_POLICY, reject_floats=True)
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=SQLITE_BANK_STATEMENT_CONTROL_JSON_PROFILE,
        schema_id=SQLITE_BANK_STATEMENT_CONTROL_SCHEMA,
        reject_fractional_numbers=True,
    )


def encode_postgres_outbox_payload(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize a bounded outbox payload before JSONB persistence."""

    value = dict(payload)
    _preflight_value(value, POSTGRES_OUTBOX_JSON_POLICY, reject_floats=False)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=POSTGRES_OUTBOX_JSON_POLICY,
        profile_id=POSTGRES_OUTBOX_JSON_PROFILE,
        schema_id=POSTGRES_OUTBOX_PAYLOAD_SCHEMA,
        reject_fractional_numbers=False,
    )


def _decode_postgres_reconciliation_object(
    value: object,
    *,
    policy: StructuredDocumentPolicy,
    profile_id: str,
) -> PersistedJsonObjectDocument:
    if isinstance(value, Mapping):
        return _encode_postgres_reconciliation_object(value, policy=policy, profile_id=profile_id)
    stored = _document(
        str(value),
        policy=policy,
        profile_id=profile_id,
        schema_id=POSTGRES_RECONCILIATION_OBJECT_SCHEMA,
        reject_fractional_numbers=False,
    )
    # PostgreSQL JSONB rendering does not preserve producer whitespace.  Return
    # the established compact canonical producer bytes for stable fingerprints.
    return _encode_postgres_reconciliation_object(stored.payload, policy=policy, profile_id=profile_id)


def _encode_postgres_reconciliation_object(
    payload: Mapping[str, Any] | None,
    *,
    policy: StructuredDocumentPolicy,
    profile_id: str,
) -> PersistedJsonObjectDocument:
    try:
        value = dict(payload or {})
    except (TypeError, ValueError) as exc:
        raise PersistedJsonError("persisted_json_object_required") from exc
    _preflight_value(value, policy, reject_floats=False)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=policy,
        profile_id=profile_id,
        schema_id=POSTGRES_RECONCILIATION_OBJECT_SCHEMA,
        reject_fractional_numbers=False,
    )


def decode_postgres_reconciliation_rule(value: object) -> PersistedJsonObjectDocument:
    """Decode one stored PostgreSQL reconciliation rule object."""

    return _decode_postgres_reconciliation_object(
        value,
        policy=POSTGRES_RECONCILIATION_RULE_JSON_POLICY,
        profile_id=POSTGRES_RECONCILIATION_RULE_JSON_PROFILE,
    )


def encode_postgres_reconciliation_rule(payload: Mapping[str, Any] | None) -> PersistedJsonObjectDocument:
    """Canonicalize one reconciliation rule before JSONB persistence."""

    return _encode_postgres_reconciliation_object(
        payload,
        policy=POSTGRES_RECONCILIATION_RULE_JSON_POLICY,
        profile_id=POSTGRES_RECONCILIATION_RULE_JSON_PROFILE,
    )


def decode_postgres_reconciliation_attributes(value: object) -> PersistedJsonObjectDocument:
    """Decode canonical input attributes under their historical byte ceiling."""

    return _decode_postgres_reconciliation_object(
        value,
        policy=POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY,
        profile_id=POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_PROFILE,
    )


def encode_postgres_reconciliation_attributes(
    payload: Mapping[str, Any] | None,
) -> PersistedJsonObjectDocument:
    """Canonicalize input attributes before JSONB persistence."""

    return _encode_postgres_reconciliation_object(
        payload,
        policy=POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_POLICY,
        profile_id=POSTGRES_RECONCILIATION_ATTRIBUTES_JSON_PROFILE,
    )


def decode_postgres_reconciliation_lineage(value: object) -> PersistedJsonObjectDocument:
    """Decode one stored reconciliation decision-lineage object."""

    return _decode_postgres_reconciliation_object(
        value,
        policy=POSTGRES_RECONCILIATION_LINEAGE_JSON_POLICY,
        profile_id=POSTGRES_RECONCILIATION_LINEAGE_JSON_PROFILE,
    )


def encode_postgres_reconciliation_lineage(payload: Mapping[str, Any] | None) -> PersistedJsonObjectDocument:
    """Canonicalize decision lineage before JSONB persistence."""

    return _encode_postgres_reconciliation_object(
        payload,
        policy=POSTGRES_RECONCILIATION_LINEAGE_JSON_POLICY,
        profile_id=POSTGRES_RECONCILIATION_LINEAGE_JSON_PROFILE,
    )


def decode_postgres_reconciliation_evidence(value: object) -> PersistedJsonObjectDocument:
    """Decode one stored reconciliation-exception evidence object."""

    return _decode_postgres_reconciliation_object(
        value,
        policy=POSTGRES_RECONCILIATION_EVIDENCE_JSON_POLICY,
        profile_id=POSTGRES_RECONCILIATION_EVIDENCE_JSON_PROFILE,
    )


def encode_postgres_reconciliation_evidence(payload: Mapping[str, Any] | None) -> PersistedJsonObjectDocument:
    """Canonicalize exception evidence before JSONB persistence."""

    return _encode_postgres_reconciliation_object(
        payload,
        policy=POSTGRES_RECONCILIATION_EVIDENCE_JSON_POLICY,
        profile_id=POSTGRES_RECONCILIATION_EVIDENCE_JSON_PROFILE,
    )


def decode_sqlite_matching_rule(value: object) -> PersistedJsonObjectDocument:
    """Decode one stored SQLite matching rule and restore producer formatting."""

    if isinstance(value, Mapping):
        return _encode_sqlite_matching_rule(value, reject_floats=False)
    stored = _document(
        str(value),
        policy=SQLITE_MATCHING_RULE_JSON_POLICY,
        profile_id=SQLITE_MATCHING_RULE_JSON_PROFILE,
        schema_id=SQLITE_MATCHING_RULE_SCHEMA,
        reject_fractional_numbers=False,
    )
    return _encode_sqlite_matching_rule(stored.payload, reject_floats=False)


def encode_sqlite_matching_rule(payload: Mapping[str, Any]) -> PersistedJsonObjectDocument:
    """Canonicalize a rule using the established spaced, sorted SQLite text."""

    return _encode_sqlite_matching_rule(payload, reject_floats=True)


def _encode_sqlite_matching_rule(
    payload: Mapping[str, Any],
    *,
    reject_floats: bool,
) -> PersistedJsonObjectDocument:

    try:
        value = dict(payload)
    except (TypeError, ValueError) as exc:
        raise PersistedJsonError("persisted_json_object_required") from exc
    _preflight_value(value, SQLITE_MATCHING_RULE_JSON_POLICY, reject_floats=reject_floats)
    try:
        # Default separators are part of the historical match_jobs/match_rules
        # text contract and therefore intentionally differ from compact JSON.
        text = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PersistedJsonError("persisted_json_encoding_invalid") from exc
    return _document(
        text,
        policy=SQLITE_MATCHING_RULE_JSON_POLICY,
        profile_id=SQLITE_MATCHING_RULE_JSON_PROFILE,
        schema_id=SQLITE_MATCHING_RULE_SCHEMA,
        reject_fractional_numbers=False,
    )
