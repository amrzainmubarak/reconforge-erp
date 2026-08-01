"""Append-only, schema-closed reliability incident evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from reconforge.reliability import AlertResult, AlertState

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class IncidentState(StrEnum):
    DETECTED = "detected"
    ACKNOWLEDGED = "acknowledged"
    MITIGATING = "mitigating"
    RECOVERED = "recovered"
    CLOSED = "closed"


_NEXT = {
    IncidentState.DETECTED: IncidentState.ACKNOWLEDGED,
    IncidentState.ACKNOWLEDGED: IncidentState.MITIGATING,
    IncidentState.MITIGATING: IncidentState.RECOVERED,
    IncidentState.RECOVERED: IncidentState.CLOSED,
}


def _safe_id(value: str, field: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field} must be a safe bounded identifier")
    return value


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("incident timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class IncidentEvent:
    sequence: int
    state: IncidentState
    occurred_at: str
    operator_ref: str
    action_code: str
    evidence_sha256: str
    previous_event_sha256: str | None
    event_sha256: str

    def payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "state": self.state.value,
            "occurred_at": self.occurred_at,
            "operator_ref": self.operator_ref,
            "action_code": self.action_code,
            "evidence_sha256": self.evidence_sha256,
            "previous_event_sha256": self.previous_event_sha256,
        }


class ReliabilityIncident:
    """Record one strictly ordered incident without accepting free-form sensitive text."""

    def __init__(
        self,
        *,
        incident_id: str,
        alert: AlertResult,
        detected_at: datetime,
        correlation_id: str,
        detector_ref: str,
        detection_evidence_sha256: str,
    ) -> None:
        if alert.state not in {AlertState.WARNING, AlertState.CRITICAL}:
            raise ValueError("an incident requires a warning or critical alert")
        self.incident_id = _safe_id(incident_id, "incident_id")
        self.policy_id = _safe_id(alert.policy_id, "policy_id")
        self.policy_version = _safe_id(alert.policy_version, "policy_version")
        self.runbook = _safe_id(alert.runbook, "runbook")
        self.correlation_id = _safe_id(correlation_id, "correlation_id")
        self.initial_alert_state = alert.state
        self.initial_observed = alert.observed
        self._events: list[IncidentEvent] = []
        self._append(
            state=IncidentState.DETECTED,
            occurred_at=detected_at,
            operator_ref=detector_ref,
            action_code="alert-detected",
            evidence_sha256=detection_evidence_sha256,
        )

    @property
    def state(self) -> IncidentState:
        return self._events[-1].state

    def transition(
        self,
        *,
        state: IncidentState,
        occurred_at: datetime,
        operator_ref: str,
        action_code: str,
        evidence_sha256: str,
        recovery_alerts: tuple[AlertResult, ...] | None = None,
    ) -> IncidentEvent:
        if _NEXT.get(self.state) is not state:
            raise ValueError("incident transition is not allowed")
        if state is IncidentState.RECOVERED and (
            not recovery_alerts or any(result.state is not AlertState.NORMAL for result in recovery_alerts)
        ):
            raise ValueError("recovery requires a complete all-normal alert evaluation")
        return self._append(
            state=state,
            occurred_at=occurred_at,
            operator_ref=operator_ref,
            action_code=action_code,
            evidence_sha256=evidence_sha256,
        )

    def _append(
        self,
        *,
        state: IncidentState,
        occurred_at: datetime,
        operator_ref: str,
        action_code: str,
        evidence_sha256: str,
    ) -> IncidentEvent:
        timestamp = _utc(occurred_at)
        if self._events and timestamp <= self._events[-1].occurred_at:
            raise ValueError("incident timestamps must increase")
        operator = _safe_id(operator_ref, "operator_ref")
        action = _safe_id(action_code, "action_code")
        if not _SHA256.fullmatch(evidence_sha256):
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
        previous = self._events[-1].event_sha256 if self._events else None
        payload = {
            "sequence": len(self._events) + 1,
            "state": state.value,
            "occurred_at": timestamp,
            "operator_ref": operator,
            "action_code": action,
            "evidence_sha256": evidence_sha256,
            "previous_event_sha256": previous,
        }
        event = IncidentEvent(
            sequence=len(self._events) + 1,
            state=state,
            occurred_at=timestamp,
            operator_ref=operator,
            action_code=action,
            evidence_sha256=evidence_sha256,
            previous_event_sha256=previous,
            event_sha256=_digest(payload),
        )
        self._events.append(event)
        return event

    def manifest(self) -> dict[str, object]:
        if self.state is not IncidentState.CLOSED:
            raise ValueError("only a closed incident has a final manifest")
        events = [{**event.payload(), "event_sha256": event.event_sha256} for event in self._events]
        body: dict[str, object] = {
            "schema_version": 1,
            "incident_id": self.incident_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "runbook": self.runbook,
            "correlation_id": self.correlation_id,
            "initial_alert_state": self.initial_alert_state.value,
            "initial_observed": self.initial_observed,
            "final_state": self.state.value,
            "events": events,
        }
        return {**body, "manifest_sha256": _digest(body)}


def verify_incident_manifest(manifest: dict[str, object]) -> bool:
    """Verify the exact event chain and final manifest digest."""

    try:
        body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        if manifest.get("manifest_sha256") != _digest(body):
            return False
        events = manifest["events"]
        if not isinstance(events, list) or len(events) != 5:
            return False
        expected_states = [state.value for state in IncidentState]
        previous: str | None = None
        for index, raw in enumerate(events, start=1):
            if not isinstance(raw, dict):
                return False
            payload = {key: value for key, value in raw.items() if key != "event_sha256"}
            if raw.get("sequence") != index or raw.get("state") != expected_states[index - 1]:
                return False
            if raw.get("previous_event_sha256") != previous or raw.get("event_sha256") != _digest(payload):
                return False
            previous = str(raw["event_sha256"])
        return manifest.get("final_state") == IncidentState.CLOSED
    except (KeyError, TypeError, ValueError):
        return False
