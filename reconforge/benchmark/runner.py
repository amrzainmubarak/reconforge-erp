"""Benchmark runner."""

from __future__ import annotations

import time
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows fallback
    resource = None  # type: ignore[assignment]

from reconforge.benchmark.metrics import BenchmarkMetrics, build_metrics
from reconforge.benchmark.report import write_benchmark_reports
from reconforge.config import load_config
from reconforge.engines.registry import get_engine


def _memory_mb() -> float:
    if resource is None:
        return 0.0
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage / 1024 if usage > 10_000 else usage


def run_benchmark(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    engine_name: str = "pandas",
    config_path: Path | str | None = None,
) -> BenchmarkMetrics:
    """Run a reconciliation benchmark and write outputs."""

    config = load_config(config_path)
    engine = get_engine(engine_name)
    start = time.perf_counter()
    result = engine.run(Path(input_dir), config)
    runtime = time.perf_counter() - start
    report_start = time.perf_counter()
    metrics = build_metrics(
        runtime_seconds=runtime,
        report_generation_time=0.0,
        stock_rows=result.stock_rows,
        gl_rows=result.gl_rows,
        matched_rows=result.matched_rows,
        exception_rows=result.exception_rows,
        memory_mb=_memory_mb(),
        engine=result.engine,
    )
    write_benchmark_reports(metrics, output_dir)
    report_time = time.perf_counter() - report_start
    metrics = build_metrics(
        runtime_seconds=runtime,
        report_generation_time=report_time,
        stock_rows=result.stock_rows,
        gl_rows=result.gl_rows,
        matched_rows=result.matched_rows,
        exception_rows=result.exception_rows,
        memory_mb=_memory_mb(),
        engine=result.engine,
    )
    write_benchmark_reports(metrics, output_dir)
    return metrics
