"""Reliability-plane decision contracts.

This package preserves the pre-existing operator alert API while exposing the
new deterministic HA/DR safety contracts.  Keeping both surfaces here is
intentional: ``reconforge.reliability`` was already a public import path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TypeVar

from reconforge.reliability.ha_dr import (
    HaDrCluster,
    HaDrError,
    HaDrNode,
    HaDrNodeRole,
    HaDrTopology,
    build_quorum_simulation_report,
    verify_quorum_simulation_report,
)


class AlertState(StrEnum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    NO_DATA = "no_data"


class MetricKey(StrEnum):
    HTTP_ERROR_BPS = "http_error_basis_points"
    HTTP_P95_MS = "http_p95_milliseconds"
    QUEUE_DEPTH = "job_queue_depth"
    OLDEST_JOB_AGE_SECONDS = "oldest_queued_job_age_seconds"
    DEPENDENCY_FAILURES = "dependency_readiness_failures"
    AUDIT_FAILURES = "audit_verification_failures"
    PROCESS_MEMORY_MIB = "process_memory_mebibytes"


_MetricInput = TypeVar("_MetricInput", str, MetricKey)


@dataclass(frozen=True)
class AlertPolicy:
    id: str
    metric: MetricKey
    slo_id: str
    runbook: str
    warning_at: int
    critical_at: int

    def __post_init__(self) -> None:
        if not self.id or not self.slo_id or not self.runbook:
            raise ValueError("alert identity, SLO, and runbook are required")
        if self.warning_at < 0 or self.critical_at <= self.warning_at:
            raise ValueError("alert thresholds must be ordered non-negative integers")


@dataclass(frozen=True)
class AlertResult:
    policy_id: str
    metric: MetricKey
    state: AlertState
    observed: int | None
    slo_id: str
    runbook: str
    policy_version: str = "reconforge-reliability-policy-v1"


DEFAULT_ALERT_POLICIES = (
    AlertPolicy("api-errors", MetricKey.HTTP_ERROR_BPS, "api-availability", "RF-OPS-001", 100, 500),
    AlertPolicy("api-latency", MetricKey.HTTP_P95_MS, "api-latency", "RF-OPS-001", 1_000, 3_000),
    AlertPolicy("job-backlog", MetricKey.QUEUE_DEPTH, "durable-job-flow", "RF-OPS-002", 100, 1_000),
    AlertPolicy("job-age", MetricKey.OLDEST_JOB_AGE_SECONDS, "durable-job-flow", "RF-OPS-002", 300, 1_800),
    AlertPolicy("dependency-readiness", MetricKey.DEPENDENCY_FAILURES, "dependency-readiness", "RF-OPS-003", 1, 2),
    AlertPolicy("audit-integrity", MetricKey.AUDIT_FAILURES, "audit-integrity", "RF-OPS-004", 1, 2),
    AlertPolicy("process-memory", MetricKey.PROCESS_MEMORY_MIB, "capacity-headroom", "RF-OPS-005", 2_048, 3_072),
)


def validate_measurements(values: Mapping[_MetricInput, object]) -> Mapping[MetricKey, int]:
    """Return an immutable, schema-closed snapshot without labels or identifiers."""

    resolved: dict[MetricKey, int] = {}
    for raw_key, raw_value in values.items():
        try:
            key = raw_key if isinstance(raw_key, MetricKey) else MetricKey(raw_key)
        except ValueError as exc:
            raise ValueError("unknown reliability metric") from exc
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0 or raw_value > 10**12:
            raise ValueError("reliability measurements must be bounded non-negative integers")
        if key in resolved:
            raise ValueError("duplicate reliability metric")
        resolved[key] = raw_value
    return MappingProxyType(resolved)


def evaluate_alerts(
    values: Mapping[_MetricInput, object], policies: tuple[AlertPolicy, ...] = DEFAULT_ALERT_POLICIES
) -> tuple[AlertResult, ...]:
    """Evaluate all policies; absent measurements are explicit NO_DATA, never green."""

    measurements = validate_measurements(values)
    results: list[AlertResult] = []
    for policy in policies:
        observed = measurements.get(policy.metric)
        if observed is None:
            state = AlertState.NO_DATA
        elif observed >= policy.critical_at:
            state = AlertState.CRITICAL
        elif observed >= policy.warning_at:
            state = AlertState.WARNING
        else:
            state = AlertState.NORMAL
        results.append(
            AlertResult(policy.id, policy.metric, state, observed, policy.slo_id, policy.runbook)
        )
    return tuple(results)

__all__ = [
    "AlertPolicy",
    "AlertResult",
    "AlertState",
    "DEFAULT_ALERT_POLICIES",
    "HaDrCluster",
    "HaDrError",
    "HaDrNode",
    "HaDrNodeRole",
    "HaDrTopology",
    "MetricKey",
    "build_quorum_simulation_report",
    "evaluate_alerts",
    "validate_measurements",
    "verify_quorum_simulation_report",
]
