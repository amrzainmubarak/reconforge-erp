"""Backend-neutral validation of retained outbox lease evidence continuity."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


class OutboxEvidenceIntegrityError(ValueError):
    """Delivery history cannot justify the retained outbox generation."""


def validate_outbox_delivery_evidence(
    *, event_id: str, lease_generation: int, lease_generation_floor: int,
    evidence: Iterable[Mapping[str, object]],
) -> None:
    """Verify contiguous claims without inventing pre-migration history.

    Historical rows reserve floor two. Evidence at or below that watermark
    need not exist; every later claimed generation must exist exactly once.
    The check is independent of row ordering and linear in retained evidence,
    apart from sorting claim generations. It never enumerates an untrusted
    generation interval.
    """
    if (
        not event_id
        or type(lease_generation) is not int
        or type(lease_generation_floor) is not int
        or lease_generation_floor not in (0, 2)
        or not lease_generation_floor <= lease_generation < 2**63
    ):
        raise OutboxEvidenceIntegrityError("Invalid retained outbox generation or historical watermark.")
    claims: list[int] = []
    for record in evidence:
        generation = record.get("lease_generation")
        attempts = record.get("attempts")
        action = record.get("action")
        worker = record.get("worker_id")
        if (
            record.get("event_id") != event_id
            or type(generation) is not int
            or not 1 <= generation <= lease_generation
            or type(attempts) is not int
            or attempts < 0
            or action not in ("claimed", "published", "failed", "expired", "requeued")
            or not isinstance(worker, str)
            or not worker.strip()
        ):
            raise OutboxEvidenceIntegrityError("Invalid outbox delivery evidence record.")
        if action == "claimed":
            if generation <= lease_generation_floor:
                raise OutboxEvidenceIntegrityError("Historical outbox claims cannot be inferred.")
            claims.append(generation)
    claims.sort()
    expected_count = lease_generation - lease_generation_floor
    if len(claims) != expected_count or (
        claims and (
            claims[0] != lease_generation_floor + 1
            or claims[-1] != lease_generation
            or any(right != left + 1 for left, right in zip(claims, claims[1:], strict=False))
        )
    ):
        raise OutboxEvidenceIntegrityError("Outbox claimed generations are missing, duplicated or discontinuous.")
