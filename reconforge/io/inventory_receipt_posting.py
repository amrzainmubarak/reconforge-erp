"""Bounded exact JSON for reviewed Inventory receipt commands and evidence."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_posting import canonical_json
from reconforge.domain.inventory_receipt_posting import MAX_RECEIPT_BYTES, InventoryReceiptPostingError
from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy, parse_json_document

RECEIPT_JSON_POLICY = StructuredDocumentPolicy(
    max_file_bytes=MAX_RECEIPT_BYTES, max_nodes=2048,
    max_depth=12, max_collection_items=64, max_scalar_characters=2048, max_yaml_aliases=1,
)


def decode_receipt_json(value: object) -> dict[str, Any]:
    if not isinstance(value, str):
        raise InventoryReceiptPostingError("inventory_receipt_evidence_invalid", "Receipt evidence requires retained JSON text.")
    try:
        result = parse_json_document(value, reject_fractional_numbers=True, policy=RECEIPT_JSON_POLICY)
    except StructuredDocumentError as exc:
        raise InventoryReceiptPostingError("inventory_receipt_evidence_invalid", "Receipt evidence failed bounded exact JSON validation.") from exc
    if not isinstance(result, dict):
        raise InventoryReceiptPostingError("inventory_receipt_evidence_invalid", "Receipt evidence requires a closed object.")
    return result


def encode_receipt_json(value: Mapping[str, Any]) -> str:
    encoded = canonical_json(value)
    decode_receipt_json(encoded)
    return encoded
