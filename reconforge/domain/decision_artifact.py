"""Shared integrity checks for serialized, non-posting decision artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence


def canonical_decision_digest(payload: Mapping[str, object]) -> str:
    """Hash the exact canonical decision payload emitted by a control run."""

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def verify_canonical_decision_payload(
    payload: Mapping[str, object],
    *,
    expected_schema_version: int,
    expected_algorithm_version: str,
    digest_fields: Sequence[str],
    decision_sort_key: Callable[[Mapping[str, object]], tuple[str, ...]],
    allowed_statuses: frozenset[str],
) -> None:
    """Verify canonical ordering, status counts, input fingerprints, and digest.

    The helper intentionally validates serialized values instead of rebuilding
    domain objects. Source authenticity and recalculation from source records
    remain separate controls; this closes accidental or partial report edits.
    """

    if payload.get("schema_version") != expected_schema_version:
        raise ValueError("decision artifact schema version is unsupported")
    if payload.get("algorithm_version") != expected_algorithm_version:
        raise ValueError("decision artifact algorithm version is unsupported")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or any(not isinstance(item, dict) for item in decisions):
        raise ValueError("decision artifact decisions are invalid")
    if decisions != sorted(decisions, key=decision_sort_key):
        raise ValueError("decision artifact decisions are not canonical")

    input_digests = payload.get("input_digests")
    if not isinstance(input_digests, list) or any(not isinstance(item, str) for item in input_digests):
        raise ValueError("decision artifact input digests are invalid")
    if input_digests != sorted(set(input_digests)):
        raise ValueError("decision artifact input digests are not canonical")

    counts: dict[str, int] = {}
    for decision in decisions:
        status = decision.get("status")
        if not isinstance(status, str) or status not in allowed_statuses:
            raise ValueError("decision artifact status is invalid")
        counts[status] = counts.get(status, 0) + 1
    if payload.get("status_counts") != dict(sorted(counts.items())):
        raise ValueError("decision artifact status counts are inconsistent")

    try:
        digest_payload = {field: payload[field] for field in digest_fields}
    except KeyError as exc:
        raise ValueError("decision artifact digest fields are incomplete") from exc
    expected_digest = canonical_decision_digest(digest_payload)
    if payload.get("decision_digest") != expected_digest:
        raise ValueError("decision artifact decision digest verification failed")


__all__ = ["canonical_decision_digest", "verify_canonical_decision_payload"]
