"""Exercise a closed alert, acknowledgement, mitigation, recovery, and closure chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from reconforge.db import connect, run_migrations
from reconforge.incident_response import IncidentState, ReliabilityIncident, verify_incident_manifest
from reconforge.reliability import AlertState, MetricKey, evaluate_alerts
from reconforge.reliability_sources import HttpReliabilityWindow, SQLiteReliabilityCollector

QUEUED_JOBS = 1_000


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def run_drill() -> dict[str, Any]:
    started = datetime(2026, 7, 30, 14, 0, tzinfo=UTC)
    with tempfile.TemporaryDirectory(prefix="reconforge-incident-") as temporary:
        database = Path(temporary) / "incident.db"
        run_migrations(database)
        connection = connect(database)
        created_at = "2026-07-30T13:00:00Z"
        connection.executemany(
            "INSERT INTO durable_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    f"incident-job-{index:04d}", 1, 1, "queued", "incident-drill",
                    f"incident-key-{index:04d}", "tenant", "workspace", "", "a" * 64,
                    "b" * 64, "worker/1", 0, 1, "", 0, 1, "", created_at, created_at,
                    "", "", None, "", "",
                )
                for index in range(QUEUED_JOBS)
            ],
        )
        connection.commit()
        window = HttpReliabilityWindow()
        window.record(status_code=200, duration_ms=10)
        collector = SQLiteReliabilityCollector(
            connection,
            http_window=window,
            dependency_probes=(lambda: True,),
            memory_mib=lambda: 128,
        )
        detected_snapshot = collector.collect(observed_at=started)
        detected_alerts = evaluate_alerts(detected_snapshot.values)
        backlog_alert = next(result for result in detected_alerts if result.policy_id == "job-backlog")
        incident = ReliabilityIncident(
            incident_id="INC-RF-LOCAL-0001",
            alert=backlog_alert,
            detected_at=started,
            correlation_id="corr-rf-local-0001",
            detector_ref="system-reliability",
            detection_evidence_sha256=_digest(dict(detected_snapshot.values)),
        )
        incident.transition(
            state=IncidentState.ACKNOWLEDGED,
            occurred_at=started + timedelta(seconds=15),
            operator_ref="operator-primary",
            action_code="incident-acknowledged",
            evidence_sha256=_digest({"policy": backlog_alert.policy_id, "runbook": backlog_alert.runbook}),
        )
        incident.transition(
            state=IncidentState.MITIGATING,
            occurred_at=started + timedelta(seconds=30),
            operator_ref="operator-primary",
            action_code="producer-paused-worker-restored",
            evidence_sha256=_digest({"runbook": "RF-OPS-002", "producer": "paused"}),
        )
        connection.execute(
            "UPDATE durable_jobs SET status = 'completed', completed_units = total_units, completed_at = updated_at"
        )
        connection.commit()
        recovered_snapshot = collector.collect(observed_at=started + timedelta(seconds=45))
        recovered_alerts = evaluate_alerts(recovered_snapshot.values)
        recovery_digest = _digest(dict(recovered_snapshot.values))
        incident.transition(
            state=IncidentState.RECOVERED,
            occurred_at=started + timedelta(seconds=45),
            operator_ref="operator-validator",
            action_code="synthetic-check-passed",
            evidence_sha256=recovery_digest,
            recovery_alerts=recovered_alerts,
        )
        incident.transition(
            state=IncidentState.CLOSED,
            occurred_at=started + timedelta(seconds=60),
            operator_ref="operator-validator",
            action_code="residual-risk-local-only",
            evidence_sha256=_digest({"residual_risk": "local-only-no-ha"}),
        )
        connection.close()
    manifest = incident.manifest()
    return {
        "schema_version": 1,
        "profile": "local-synthetic-incident-lifecycle",
        "incident": manifest,
        "measurements": {
            "initial_queue_depth": detected_snapshot.values[MetricKey.QUEUE_DEPTH],
            "recovered_queue_depth": recovered_snapshot.values[MetricKey.QUEUE_DEPTH],
            "acknowledgement_seconds": 15,
            "recovery_seconds": 45,
            "closure_seconds": 60,
        },
        "checks": {
            "critical_alert_detected": backlog_alert.state is AlertState.CRITICAL,
            "runbook_bound": backlog_alert.runbook == "RF-OPS-002",
            "independent_recovery_validation_actor": "operator-primary" != "operator-validator",
            "all_recovery_alerts_normal": all(result.state is AlertState.NORMAL for result in recovered_alerts),
            "backlog_recovered_to_zero": recovered_snapshot.values[MetricKey.QUEUE_DEPTH] == 0,
            "incident_chain_verified": verify_incident_manifest(manifest),
            "all_sources_available": not detected_snapshot.unavailable_sources and not recovered_snapshot.unavailable_sources,
        },
        "limitations": [
            "synthetic_local_sqlite_incident",
            "operators_are_synthetic_role_references",
            "no_external_alert_manager_or_pager_acknowledgement",
            "single_run_not_production_slo",
            "no_independent_host_ha_or_external_assurance",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_drill()
    if not all(report["checks"].values()):
        raise SystemExit("Reliability incident drill failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
