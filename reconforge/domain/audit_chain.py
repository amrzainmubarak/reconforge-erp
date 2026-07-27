"""Pure canonical audit-chain hashing shared by every persistence adapter."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def calculate_audit_event_hash(
    *, event_id: str, sequence: int, previous_hash: str, actor_user_id: str | None,
    actor_label: str, object_type: str, object_id: str, action: str,
    before_hash: str | None, after_hash: str | None, metadata_json: str, created_at: str,
) -> str:
    """Return the version-1 canonical SHA-256 identity for one audit event."""

    payload: dict[str, Any] = {
        "action": action,
        "actor_label": actor_label,
        "actor_user_id": actor_user_id,
        "after_hash": after_hash,
        "before_hash": before_hash,
        "created_at": created_at,
        "id": event_id,
        "metadata_json": metadata_json,
        "object_id": object_id,
        "object_type": object_type,
        "previous_hash": previous_hash,
        "sequence": sequence,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
