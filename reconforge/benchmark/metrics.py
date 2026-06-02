"""Benchmark metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BenchmarkMetrics:
    """Benchmark output metrics."""

    runtime_seconds: float
    report_generation_time: float
    number_of_stock_rows: int
    number_of_gl_rows: int
    matched_rows: int
    exception_rows: int
    match_rate: float
    exception_rate: float
    approximate_memory_mb: float
    engine_used: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_metrics(
    *,
    runtime_seconds: float,
    report_generation_time: float,
    stock_rows: int,
    gl_rows: int,
    matched_rows: int,
    exception_rows: int,
    memory_mb: float,
    engine: str,
) -> BenchmarkMetrics:
    """Build derived benchmark metrics."""

    denominator = max(stock_rows, 1)
    return BenchmarkMetrics(
        runtime_seconds=round(runtime_seconds, 4),
        report_generation_time=round(report_generation_time, 4),
        number_of_stock_rows=stock_rows,
        number_of_gl_rows=gl_rows,
        matched_rows=matched_rows,
        exception_rows=exception_rows,
        match_rate=round(matched_rows / denominator, 4),
        exception_rate=round(exception_rows / denominator, 4),
        approximate_memory_mb=round(memory_mb, 2),
        engine_used=engine,
        timestamp=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    )
