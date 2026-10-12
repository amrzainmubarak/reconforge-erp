"""Bounded synthetic crash-recovery measurements for actual outbox adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class OutboxRecoveryMeasurement:
    """Recovery-only wall time; provisioning, seeding and claims are excluded."""

    backend: str
    events: int
    batch_limit: int
    calls: int
    recovered: int
    largest_batch: int
    wall_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def measure_bounded_recovery(
    *, backend: str, events: int, batch_limit: int, recover: Callable[[int], int],
) -> OutboxRecoveryMeasurement:
    """Drain a preexisting expired synthetic queue through real transactions."""
    if type(events) is not int or not 1 <= events <= 10_000:
        raise ValueError("recovery benchmark events must be between1 and10000")
    if type(batch_limit) is not int or not 1 <= batch_limit <= 1000:
        raise ValueError("recovery benchmark batch_limit must be between1 and1000")
    recovered = calls = largest = 0
    start = perf_counter()
    while recovered < events:
        count = recover(batch_limit)
        calls += 1
        if type(count) is not int or not 1 <= count <= batch_limit:
            raise AssertionError("recovery did not make bounded progress")
        recovered += count
        largest = max(largest, count)
        if recovered > events or calls > events:
            raise AssertionError("recovery repeated or exceeded the seeded event set")
    if recover(batch_limit) != 0:
        raise AssertionError("recovery did not reach an idempotent drained state")
    return OutboxRecoveryMeasurement(backend, events, batch_limit, calls + 1, recovered, largest, perf_counter() - start)
