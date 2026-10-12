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


def validate_outbox_fencing_storage(
    *,
    events: Iterable[Mapping[str, object]],
    evidence: Iterable[Mapping[str, object]],
) -> None:
    """Verify every retained event/evidence pair without inferring history.

    Storage adapters call this before accepting a fenced outbox database.  It
    deliberately validates the complete retained set visible to the adapter:
    an evidence record without a parent or a post-floor generation gap makes
    the storage unreadable until an operator restores a verified copy.
    """
    events_by_id: dict[str, Mapping[str, object]] = {}
    evidence_by_event: dict[str, list[Mapping[str, object]]] = {}

    for event in events:
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in events_by_id:
            raise OutboxEvidenceIntegrityError("Retained outbox storage has an invalid or duplicate event id.")
        events_by_id[event_id] = event

    for record in evidence:
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or event_id not in events_by_id:
            raise OutboxEvidenceIntegrityError("Retained outbox evidence has no visible parent event.")
        evidence_by_event.setdefault(event_id, []).append(record)

    for event_id, event in events_by_id.items():
        generation = event.get("lease_generation")
        floor = event.get("lease_generation_floor")
        records = evidence_by_event.get(event_id, [])
        validate_outbox_delivery_evidence(
            event_id=event_id,
            lease_generation=generation,  # type: ignore[arg-type]
            lease_generation_floor=floor,  # type: ignore[arg-type]
            evidence=records,
        )
        state = event.get("delivery_state")
        if state is not None:
            _validate_outbox_delivery_state(
                event_id=event_id,
                lease_generation=generation,  # type: ignore[arg-type]
                lease_generation_floor=floor,  # type: ignore[arg-type]
                delivery_state=state,
                evidence=records,
            )


def _validate_outbox_delivery_state(
    *,
    event_id: str,
    lease_generation: int,
    lease_generation_floor: int,
    delivery_state: object,
    evidence: Iterable[Mapping[str, object]],
) -> None:
    """Validate terminal/replay evidence against the retained final state."""
    if delivery_state not in {"pending", "claimed", "published", "dead"}:
        raise OutboxEvidenceIntegrityError("Retained outbox delivery state is invalid.")

    actions_by_generation: dict[int, set[str]] = {}
    claim_workers: dict[int, str] = {}
    terminal_workers: list[tuple[int, str]] = []
    for record in evidence:
        generation = record.get("lease_generation")
        action = record.get("action")
        worker = record.get("worker_id")
        if type(generation) is not int or not isinstance(action, str):
            raise OutboxEvidenceIntegrityError("Invalid outbox delivery evidence record.")
        actions = actions_by_generation.setdefault(generation, set())
        if action in actions:
            raise OutboxEvidenceIntegrityError("Outbox delivery evidence action is duplicated.")
        actions.add(action)
        if action == "claimed":
            claim_workers[generation] = str(worker)
        elif action in {"published", "failed", "expired"}:
            terminal_workers.append((generation, str(worker)))

    for generation, actions in actions_by_generation.items():
        claimed = "claimed" in actions
        terminal_actions = actions & {"published", "failed", "expired"}
        if len(terminal_actions) > 1 or ("published" in actions and "requeued" in actions):
            raise OutboxEvidenceIntegrityError("Outbox delivery evidence has conflicting terminal actions.")
        if generation > lease_generation_floor:
            if not claimed:
                raise OutboxEvidenceIntegrityError("Post-floor outbox evidence has no claimed generation.")
            if generation < lease_generation and not terminal_actions:
                raise OutboxEvidenceIntegrityError("Superseded outbox claim has no terminal evidence.")
        elif generation != lease_generation_floor or actions - {"expired", "requeued"}:
            raise OutboxEvidenceIntegrityError("Historical outbox evidence action is invalid.")
        if "requeued" in actions and not (
            generation == lease_generation_floor == 2 or actions & {"failed", "expired"}
        ):
            raise OutboxEvidenceIntegrityError("Outbox replay has no terminal evidence to replay.")
        if "published" in actions and generation != lease_generation:
            raise OutboxEvidenceIntegrityError("Published outbox evidence cannot be superseded.")
    for generation, worker in terminal_workers:
        if generation > lease_generation_floor and worker != claim_workers.get(generation):
            raise OutboxEvidenceIntegrityError("Outbox terminal evidence has an unbound worker.")

    current_actions = actions_by_generation.get(lease_generation, set())
    if delivery_state == "claimed":
        valid = (
            (lease_generation == lease_generation_floor == 2 and not current_actions)
            or (lease_generation > lease_generation_floor and current_actions == {"claimed"})
        )
    elif delivery_state == "published":
        valid = (
            (lease_generation == lease_generation_floor == 2 and not current_actions)
            or (lease_generation > lease_generation_floor and current_actions == {"claimed", "published"})
        )
    elif delivery_state == "dead":
        valid = (
            (lease_generation == lease_generation_floor == 2 and current_actions <= {"expired"})
            or (
                lease_generation > lease_generation_floor
                and "claimed" in current_actions
                and bool(current_actions & {"failed", "expired"})
                and "requeued" not in current_actions
            )
        )
    else:
        valid = (
            (lease_generation == lease_generation_floor and not current_actions)
            or (
                lease_generation > lease_generation_floor
                and "claimed" in current_actions
                and bool(current_actions & {"failed", "expired", "requeued"})
                and "published" not in current_actions
            )
            or (lease_generation == lease_generation_floor == 2 and current_actions <= {"expired", "requeued"})
        )
    if not valid:
        raise OutboxEvidenceIntegrityError("Outbox delivery evidence is inconsistent with the retained state.")
