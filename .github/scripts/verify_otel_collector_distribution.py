"""Exercise the pinned official Collector distribution and local file backend."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess  # nosec B404
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import run_migrations
from reconforge.observability import OTLPHTTPConfiguration, create_otlp_http_runtime
from reconforge.reliability import MetricKey, evaluate_alerts
from reconforge.reliability_sources import HttpReliabilityWindow

IMAGE = (
    "ghcr.io/open-telemetry/opentelemetry-collector-releases/"
    "opentelemetry-collector-contrib@sha256:93aad750175cbf1a973ae1c5886c3371f4d800f61be25cdd26870b8441ffe9fa"
)


def _run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        argv, cwd=Path(__file__).resolve().parents[2], check=check,
        capture_output=True, text=True, timeout=120,
    )


def run_drill() -> dict[str, Any]:
    name = "reconforge-otel-" + uuid.uuid4().hex[:12]
    config = (Path(__file__).resolve().parents[2] / "docs/operations/otel-collector.v1.yaml").resolve()
    cleanup = False
    collector_tmpfs = "/tmp:rw,noexec,nosuid,size=16m"  # nosec B108
    with tempfile.TemporaryDirectory(prefix="reconforge-otel-output-") as temporary:
        output = Path(temporary).resolve()
        try:
            _run([
                "docker", "run", "--rm", "-d", "--name", name, "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                "--tmpfs", collector_tmpfs, "-p", "127.0.0.1::4318",
                "-v", f"{config}:/etc/otelcol/config.yaml:ro", "-v", f"{output}:/output",
                IMAGE, "--config=/etc/otelcol/config.yaml",
            ])
            for _ in range(120):
                logs = _run(["docker", "logs", name], check=False)
                if "Everything is ready" in logs.stderr + logs.stdout:
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Collector readiness timeout")
            port = _run(["docker", "port", name, "4318/tcp"]).stdout.strip().rsplit(":", 1)[-1]
            previous_proxy = os.environ.get("HTTPS_PROXY")
            os.environ["HTTPS_PROXY"] = "http://127.0.0.1:1"
            runtime = create_otlp_http_runtime(
                OTLPHTTPConfiguration(f"http://127.0.0.1:{port}", export_interval_millis=300_000)
            )
            try:
                database = output / "app.db"
                run_migrations(database)
                window = HttpReliabilityWindow()
                response = TestClient(
                    create_api_app(database, observability=runtime, reliability_window=window)
                ).get("/api/v1/health", headers={"X-Request-ID": "collector-distribution-drill"})
                runtime.record_reliability_measurement(MetricKey.QUEUE_DEPTH, 1_000)
                alert = next(
                    item for item in evaluate_alerts({MetricKey.QUEUE_DEPTH: 1_000})
                    if item.policy_id == "job-backlog"
                )
                runtime.record_alert(alert)
                flushed = runtime.force_flush()
            finally:
                runtime.shutdown()
                if previous_proxy is None:
                    os.environ.pop("HTTPS_PROXY", None)
                else:
                    os.environ["HTTPS_PROXY"] = previous_proxy
            telemetry = output / "telemetry.jsonl"
            for _ in range(80):
                if telemetry.is_file() and telemetry.stat().st_size > 0:
                    content = telemetry.read_bytes()
                    if b"reliability.alert" in content and b"reconforge.operations.job_queue_depth" in content:
                        break
                time.sleep(0.25)
            else:
                raise RuntimeError("Collector backend did not persist every signal")
            checks = {
                "api_request_succeeded": response.status_code == 200,
                "force_flush_succeeded": flushed,
                "trace_persisted": b"HTTP request" in content,
                "metric_persisted": b"reconforge.operations.job_queue_depth" in content,
                "closed_alert_persisted": b"reliability.alert" in content,
                "runbook_binding_persisted": b"RF-OPS-002" in content,
                "policy_binding_persisted": b"reconforge.telemetry.policy" in content,
                "sensitive_markers_absent": not any(
                    marker in content
                    for marker in (b"tenant_id", b"workspace_id", b"amount", b"currency", b"record")
                ),
            }
            backend = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            collector_version = _run(["docker", "exec", name, "/otelcol-contrib", "--version"]).stdout.strip()
        finally:
            removed = _run(["docker", "rm", "-f", name], check=False)
            cleanup = removed.returncode == 0 or "No such container" in removed.stderr
    checks["cleanup_complete"] = cleanup
    return {
        "schema_version": 1,
        "profile": "pinned-official-collector-file-backend",
        "collector": {"image": IMAGE, "version_output": collector_version},
        "backend": backend,
        "checks": checks,
        "limitations": [
            "loopback_single_collector",
            "local_ephemeral_file_backend",
            "no_external_alert_manager_acknowledgement",
            "no_ha_retention_or_production_slo_claim",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_drill()
    if not all(report["checks"].values()):
        raise SystemExit("Collector distribution drill failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
