"""Versioned receipt request identity; never infer identity from legacy responses."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

RECEIPT_REPLAY_KIND = "receivables.receipt.request-response"


class ReceiptReplayError(ValueError):
    """The persisted receipt cannot prove the caller's request identity."""


def receipt_request_digest(
    *, workspace_id: str, organization_id: str | None, legal_entity_id: str | None,
    customer_id: str, receipt_number: str, receipt_date: str, currency_code: str,
    amount_minor: int, allocations: Sequence[tuple[str, int]], actor_label: str,
) -> str:
    payload = {
        "schema_version": 1, "kind": RECEIPT_REPLAY_KIND, "workspace_id": workspace_id,
        "organization_id": organization_id, "legal_entity_id": legal_entity_id,
        "customer_id": customer_id, "receipt_number": receipt_number, "receipt_date": receipt_date,
        "currency_code": currency_code, "amount_minor": amount_minor,
        "allocations": sorted(allocations), "actor_label": actor_label,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def receipt_replay_envelope(digest: str, response: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema_version": 1, "kind": RECEIPT_REPLAY_KIND, "request_digest": digest, "response": dict(response)}


def receipt_replay_response(envelope: Mapping[str, Any], digest: str) -> dict[str, Any]:
    if set(envelope) != {"schema_version", "kind", "request_digest", "response"} or type(envelope.get("schema_version")) is not int or envelope["schema_version"] != 1 or envelope.get("kind") != RECEIPT_REPLAY_KIND or not isinstance(envelope.get("response"), dict):
        raise ReceiptReplayError("Receipt replay identity is unavailable; read the existing receipt before any new action.")
    if envelope.get("request_digest") != digest:
        raise ReceiptReplayError("Receipt idempotency key belongs to a different request.")
    return dict(envelope["response"])
