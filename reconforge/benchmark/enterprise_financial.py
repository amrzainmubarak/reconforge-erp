"""Reproducible native financial read benchmark; money remains integer minor units.

This measures real adapters over the same immutable effects. Timings and memory
are measurements, not financial values. It makes no vendor performance claim.
"""
from __future__ import annotations

import hashlib
import math
import time
import tracemalloc
from collections.abc import Callable, Sequence
from typing import Any

from reconforge.domain.finance_posting import PostingActor, canonical_json
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository


def amount_minor(seed: str, index: int) -> int:
    """Independent deterministic positive cash/equity oracle, without pricing code."""
    if not seed or type(index) is not int or index < 0:
        raise ValueError("Invalid deterministic financial profile")
    value = hashlib.sha256(f"{seed}:{index}".encode()).digest()
    return 1 + int.from_bytes(value[:8], "big") % 1000000


def expected_totals(seed: str, count: int) -> dict[str, str]:
    if type(count) is not int or not 1 <= count <= 1000000:
        raise ValueError("Financial profile count must be between 1 and 1000000")
    total = sum(amount_minor(seed, index) for index in range(count))
    return {"debit_minor": str(total), "credit_minor": str(total), "cash_minor": str(total), "equity_minor": str(total)}


def percentile(samples: Sequence[float], fraction: float) -> float:
    if not samples or not 0 < fraction <= 1:
        raise ValueError("A latency percentile needs observations")
    return sorted(samples)[max(0, math.ceil(fraction * len(samples)) - 1)]


class MeasuredConnection:
    """Transparent instrumentation of client execute calls, not server statements."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.execute_calls = 0

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        self.execute_calls += 1
        return self.connection.execute(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.connection, name)


def measure_verified_reads(connection: Any, tenant_id: str, effect_ids: Sequence[str], actor: PostingActor,
                           *, batch_size: int = 100, repetitions: int = 3) -> dict[str, Any]:
    """Alternate unchanged per-effect baseline and bounded verifier on identical data."""
    if (not effect_ids or type(repetitions) is not int or not 1 <= repetitions <= 10
            or type(batch_size) is not int or not 1 <= batch_size <= 200):
        raise ValueError("Bounded nonempty read benchmark required")
    measured = MeasuredConnection(connection)
    repository = PostgresFinancePostingRepository(measured, tenant_id)
    # Warm both paths; authentication, authorization and every evidence check remain active.
    repository.get_effect(effect_ids[0], actor=actor)
    repository.get_effects_batch(effect_ids[:min(batch_size, len(effect_ids))], actor=actor)
    results: dict[str, list[dict[str, Any]]] = {"per_effect_baseline": [], "bounded_batch": []}
    reference_digest: str | None = None
    for repetition in range(repetitions):
        modes = ("per_effect_baseline", "bounded_batch") if repetition % 2 == 0 else ("bounded_batch", "per_effect_baseline")
        for mode in modes:
            pages = [[identifier] for identifier in effect_ids] if mode == "per_effect_baseline" else [
                list(effect_ids[start:start + batch_size]) for start in range(0, len(effect_ids), batch_size)]
            read: Callable[[Sequence[str]], list[dict[str, Any]]] = (
                (lambda page: [repository.get_effect(page[0], actor=actor)]) if mode == "per_effect_baseline"
                else (lambda page: repository.get_effects_batch(page, actor=actor)))
            measured.execute_calls = 0
            latencies: list[float] = []
            digest = hashlib.sha256()
            debit = credit = 0
            tracemalloc.start()
            started = time.perf_counter()
            try:
                for page in pages:
                    page_started = time.perf_counter()
                    effects = read(page)
                    latencies.append(time.perf_counter() - page_started)
                    for effect in effects:
                        digest.update(canonical_json(effect).encode())
                        for line in effect["snapshot"]["lines"]:
                            debit += int(line["debit_minor"])
                            credit += int(line["credit_minor"])
                elapsed = time.perf_counter() - started
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            actual_digest = digest.hexdigest()
            if reference_digest is None:
                reference_digest = actual_digest
            if actual_digest != reference_digest or debit != credit:
                raise AssertionError("Verified financial effects differ between benchmark paths")
            results[mode].append({"repetition": repetition, "effects": len(effect_ids), "seconds": elapsed,
                "verified_effects_per_second": len(effect_ids) / elapsed, "client_execute_calls": measured.execute_calls,
                "request_unit": "one_effect" if mode == "per_effect_baseline" else f"up_to_{batch_size}_effects",
                "request_latency_seconds": {"p50": percentile(latencies, .5), "p95": percentile(latencies, .95), "p99": percentile(latencies, .99)},
                "peak_python_allocated_bytes": peak, "debit_minor": str(debit), "credit_minor": str(credit),
                "effects_digest": actual_digest, "error_count": 0})
    before = sorted(row["seconds"] for row in results["per_effect_baseline"])[repetitions // 2]
    after = sorted(row["seconds"] for row in results["bounded_batch"])[repetitions // 2]
    return {"measurement_scope": "authenticated native verified effect reads; no HTTP or database-internal query count",
        "dataset_effect_ids_sha256": hashlib.sha256(canonical_json(list(effect_ids)).encode()).hexdigest(),
        "cache_policy": "both warmed; alternating modes", "samples": results,
        "median_seconds_baseline": before, "median_seconds_optimized": after,
        "measured_speedup": before / after, "financial_effects_digest": reference_digest}
