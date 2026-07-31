from __future__ import annotations

import pytest

from reconforge.reliability import AlertState, MetricKey, evaluate_alerts, validate_measurements


def test_alerts_are_exact_at_boundaries_and_bind_runbooks() -> None:
    results = {result.policy_id: result for result in evaluate_alerts({
        MetricKey.HTTP_ERROR_BPS: 100,
        MetricKey.HTTP_P95_MS: 3_000,
        MetricKey.QUEUE_DEPTH: 99,
        MetricKey.OLDEST_JOB_AGE_SECONDS: 299,
        MetricKey.DEPENDENCY_FAILURES: 1,
        MetricKey.AUDIT_FAILURES: 2,
        MetricKey.PROCESS_MEMORY_MIB: 2_048,
    })}
    assert results["api-errors"].state is AlertState.WARNING
    assert results["api-latency"].state is AlertState.CRITICAL
    assert results["job-backlog"].state is AlertState.NORMAL
    assert results["dependency-readiness"].state is AlertState.WARNING
    assert results["audit-integrity"].state is AlertState.CRITICAL
    assert all(result.slo_id and result.runbook.startswith("RF-OPS-") for result in results.values())


def test_missing_measurements_never_report_green() -> None:
    results = evaluate_alerts({MetricKey.HTTP_ERROR_BPS: 0})
    assert results[0].state is AlertState.NORMAL
    assert all(result.state is AlertState.NO_DATA and result.observed is None for result in results[1:])


@pytest.mark.parametrize("value", [-1, True, 1.5, "1", 10**12 + 1])
def test_measurements_reject_invalid_values(value: object) -> None:
    with pytest.raises(ValueError, match="bounded non-negative integers"):
        validate_measurements({MetricKey.QUEUE_DEPTH: value})


def test_measurements_reject_sensitive_or_unknown_dimensions() -> None:
    for key in ("tenant_id", "amount", "workspace_id"):
        with pytest.raises(ValueError, match="unknown reliability metric"):
            validate_measurements({key: 1})
