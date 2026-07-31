from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from reconforge.incident_response import IncidentState, ReliabilityIncident, verify_incident_manifest
from reconforge.reliability import AlertResult, AlertState, MetricKey, evaluate_alerts

ZERO = "0" * 64


def _alert(state: AlertState = AlertState.CRITICAL) -> AlertResult:
    return AlertResult("job-backlog", MetricKey.QUEUE_DEPTH, state, 1_000, "durable-job-flow", "RF-OPS-002")


def _incident() -> tuple[ReliabilityIncident, datetime]:
    now = datetime(2026, 7, 30, 13, 0, tzinfo=UTC)
    return (
        ReliabilityIncident(
            incident_id="INC-RF-0001",
            alert=_alert(),
            detected_at=now,
            correlation_id="corr-rf-0001",
            detector_ref="system-reliability",
            detection_evidence_sha256=ZERO,
        ),
        now,
    )


def _close(incident: ReliabilityIncident, now: datetime) -> dict[str, object]:
    incident.transition(
        state=IncidentState.ACKNOWLEDGED,
        occurred_at=now + timedelta(seconds=10),
        operator_ref="operator-blue",
        action_code="incident-acknowledged",
        evidence_sha256="1" * 64,
    )
    incident.transition(
        state=IncidentState.MITIGATING,
        occurred_at=now + timedelta(seconds=20),
        operator_ref="operator-blue",
        action_code="producer-paused",
        evidence_sha256="2" * 64,
    )
    incident.transition(
        state=IncidentState.RECOVERED,
        occurred_at=now + timedelta(seconds=30),
        operator_ref="operator-green",
        action_code="synthetic-check-passed",
        evidence_sha256="3" * 64,
        recovery_alerts=evaluate_alerts({metric: 0 for metric in MetricKey}),
    )
    incident.transition(
        state=IncidentState.CLOSED,
        occurred_at=now + timedelta(seconds=40),
        operator_ref="operator-green",
        action_code="residual-risk-recorded",
        evidence_sha256="4" * 64,
    )
    return incident.manifest()


def test_incident_lifecycle_is_ordered_chained_and_verifiable() -> None:
    incident, now = _incident()
    manifest = _close(incident, now)
    assert verify_incident_manifest(manifest)
    assert [event["state"] for event in manifest["events"]] == [state.value for state in IncidentState]  # type: ignore[index]
    assert manifest["initial_observed"] == 1_000


def test_incident_rejects_false_recovery_and_out_of_order_transition() -> None:
    incident, now = _incident()
    with pytest.raises(ValueError, match="not allowed"):
        incident.transition(
            state=IncidentState.MITIGATING,
            occurred_at=now + timedelta(seconds=1),
            operator_ref="operator-blue",
            action_code="producer-paused",
            evidence_sha256=ZERO,
        )
    incident.transition(
        state=IncidentState.ACKNOWLEDGED,
        occurred_at=now + timedelta(seconds=1),
        operator_ref="operator-blue",
        action_code="incident-acknowledged",
        evidence_sha256=ZERO,
    )
    incident.transition(
        state=IncidentState.MITIGATING,
        occurred_at=now + timedelta(seconds=2),
        operator_ref="operator-blue",
        action_code="producer-paused",
        evidence_sha256=ZERO,
    )
    with pytest.raises(ValueError, match="all-normal"):
        incident.transition(
            state=IncidentState.RECOVERED,
            occurred_at=now + timedelta(seconds=3),
            operator_ref="operator-green",
            action_code="synthetic-check-passed",
            evidence_sha256=ZERO,
            recovery_alerts=(_alert(AlertState.WARNING),),
        )


@pytest.mark.parametrize("unsafe", ["ab", "has space", "secret=value", "../escape", "x" * 129])
def test_incident_rejects_unsafe_free_form_identifiers(unsafe: str) -> None:
    with pytest.raises(ValueError, match="safe bounded"):
        ReliabilityIncident(
            incident_id=unsafe,
            alert=_alert(),
            detected_at=datetime.now(UTC),
            correlation_id="corr-rf-0001",
            detector_ref="system-reliability",
            detection_evidence_sha256=ZERO,
        )


def test_incident_rejects_naive_or_non_monotonic_time_and_bad_digest() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ReliabilityIncident(
            incident_id="INC-RF-0001",
            alert=_alert(),
            detected_at=datetime(2026, 7, 30),
            correlation_id="corr-rf-0001",
            detector_ref="system-reliability",
            detection_evidence_sha256=ZERO,
        )
    incident, now = _incident()
    with pytest.raises(ValueError, match="increase"):
        incident.transition(
            state=IncidentState.ACKNOWLEDGED,
            occurred_at=now,
            operator_ref="operator-blue",
            action_code="incident-acknowledged",
            evidence_sha256=ZERO,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        incident.transition(
            state=IncidentState.ACKNOWLEDGED,
            occurred_at=now + timedelta(seconds=1),
            operator_ref="operator-blue",
            action_code="incident-acknowledged",
            evidence_sha256="not-a-digest",
        )


def test_manifest_tampering_is_detected() -> None:
    incident, now = _incident()
    manifest = _close(incident, now)
    tampered = deepcopy(manifest)
    tampered["events"][2]["action_code"] = "unsafe-action"  # type: ignore[index]
    assert not verify_incident_manifest(tampered)


def test_normal_or_no_data_alert_cannot_open_incident() -> None:
    for state in (AlertState.NORMAL, AlertState.NO_DATA):
        with pytest.raises(ValueError, match="warning or critical"):
            ReliabilityIncident(
                incident_id="INC-RF-0001",
                alert=_alert(state),
                detected_at=datetime.now(UTC),
                correlation_id="corr-rf-0001",
                detector_ref="system-reliability",
                detection_evidence_sha256=ZERO,
            )
