"""Tests for the progressive enterprise benchmark suite harness."""

from __future__ import annotations

from reconforge.benchmark.progressive_enterprise_suite import (
    BenchmarkSuiteReport,
    BenchmarkTier,
    LatencyPercentiles,
    run_durable_jobs_crash_resume_workload,
    run_financial_posting_workload,
    run_inventory_fifo_workload,
    run_progressive_enterprise_suite,
    run_reconciliation_matching_workload,
)


def test_latency_percentiles_calculation() -> None:
    """Assert latency percentiles calculate min, p50, p95, p99, max in strict non-decreasing order."""
    latencies = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 5.0, 10.0]
    p = LatencyPercentiles.calculate(latencies)
    assert p.min_ms == 0.1
    assert p.max_ms == 10.0
    assert p.min_ms <= p.p50_ms <= p.p95_ms <= p.p99_ms <= p.max_ms
    assert p.mean_ms > 0.0


def test_financial_ledger_posting_workload_conserves_zero_sum() -> None:
    """Verify financial posting workload enforces Debit == Credit and produces valid signature."""
    result = run_financial_posting_workload(count=500, seed=123)
    assert result.transactions_processed == 500
    assert result.details["zero_sum_balanced"] is True
    assert result.throughput_tps > 0
    assert len(result.output_signature_sha256) == 64
    assert result.latency.min_ms <= result.latency.max_ms


def test_inventory_fifo_workload_conserves_mass_and_cost() -> None:
    """Verify inventory movements strictly conserve layer costs (remaining + cogs == receipts)."""
    result = run_inventory_fifo_workload(count=500, seed=123)
    assert result.transactions_processed == 500
    assert result.details["conservation_verified"] is True
    receipts = result.details["total_receipt_cost_minor"]
    cogs = result.details["total_cogs_minor"]
    remaining = result.details["remaining_layer_cost_minor"]
    assert receipts == cogs + remaining
    assert len(result.output_signature_sha256) == 64


def test_reconciliation_matching_workload_records_matches_and_exceptions() -> None:
    """Verify reconciliation workload computes match/exception rates and valid latency stats."""
    result = run_reconciliation_matching_workload(count=500, seed=123)
    assert result.transactions_processed == 500
    assert result.details["matched_records"] > 0
    assert result.details["exception_records"] > 0
    assert result.details["matched_records"] + result.details["exception_records"] == 500
    assert len(result.output_signature_sha256) == 64


def test_durable_jobs_crash_resume_survives_interruption_without_data_loss() -> None:
    """Verify simulated worker crash transfers partitions to successor with zero duplicate or dropped jobs."""
    result = run_durable_jobs_crash_resume_workload(count=1_000, seed=123)
    assert result.transactions_processed == 1_000
    assert result.details["zero_duplicates_verified"] is True
    assert result.details["zero_dropped_verified"] is True
    assert result.details["worker_1_partitions"] == 5
    assert result.details["worker_2_partitions"] == 5


def test_progressive_suite_tier_1k_execution_and_telemetry() -> None:
    """Verify progressive benchmark suite execution on Tier 1K collects memory and CPU telemetry."""
    report = run_progressive_enterprise_suite(tier=BenchmarkTier.TIER_1K, seed=42)
    assert isinstance(report, BenchmarkSuiteReport)
    assert report.tier == "1k"
    assert report.transaction_count == 1_000
    assert report.total_runtime_seconds < 10.0  # Must be fast local gate
    assert len(report.workloads) == 4
    assert len(report.suite_signature_sha256) == 64

    # Memory telemetry
    assert "process_lifetime_peak_rss_bytes" in report.memory_before or "rss_bytes" in report.memory_before
    assert "process_lifetime_peak_rss_bytes" in report.memory_after or "rss_bytes" in report.memory_after

    # Serialization
    report_dict = report.to_dict()
    assert report_dict["tier"] == "1k"
    assert len(report_dict["workloads"]) == 4


def test_progressive_suite_deterministic_signatures() -> None:
    """Verify identical PRNG seeds produce identical suite and workload SHA-256 signatures."""
    report_a = run_progressive_enterprise_suite(tier=BenchmarkTier.TIER_1K, seed=999)
    report_b = run_progressive_enterprise_suite(tier=BenchmarkTier.TIER_1K, seed=999)

    assert report_a.suite_signature_sha256 == report_b.suite_signature_sha256
    for wa, wb in zip(report_a.workloads, report_b.workloads, strict=True):
        assert wa.output_signature_sha256 == wb.output_signature_sha256
