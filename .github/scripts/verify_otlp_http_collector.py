"""Verify explicit OTLP/HTTP trace and metric delivery to a local receiver."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.db import run_migrations
from reconforge.observability import OTLPHTTPConfiguration, create_otlp_http_runtime
from reconforge.reliability import MetricKey, evaluate_alerts
from reconforge.reliability_sources import HttpReliabilityWindow


def run_drill() -> dict[str, Any]:
    received: list[tuple[str, bytes]] = []
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            size = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(size)
            with lock:
                received.append((self.path, body))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    previous_proxy = os.environ.get("HTTPS_PROXY")
    os.environ["HTTPS_PROXY"] = "http://127.0.0.1:1"
    runtime = create_otlp_http_runtime(
        OTLPHTTPConfiguration(f"http://127.0.0.1:{server.server_port}", export_interval_millis=300_000)
    )
    try:
        with tempfile.TemporaryDirectory(prefix="reconforge-otlp-") as temporary:
            database = Path(temporary) / "drill.db"
            run_migrations(database)
            window = HttpReliabilityWindow()
            client = TestClient(create_api_app(database, observability=runtime, reliability_window=window))
            response = client.get("/api/v1/health", headers={"X-Request-ID": "otlp-drill-1"})
            runtime.record_reliability_measurement(MetricKey.QUEUE_DEPTH, 0)
            dependency_alert = next(
                result
                for result in evaluate_alerts({MetricKey.DEPENDENCY_FAILURES: 2})
                if result.policy_id == "dependency-readiness"
            )
            runtime.record_alert(dependency_alert)
            flushed = runtime.force_flush()
            request_observed = window.measurements().get(MetricKey.HTTP_ERROR_BPS) == 0
    finally:
        runtime.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if previous_proxy is None:
            os.environ.pop("HTTPS_PROXY", None)
        else:
            os.environ["HTTPS_PROXY"] = previous_proxy
    with lock:
        paths = sorted({path for path, _ in received})
        payload = b"".join(body for _, body in received)
    return {
        "schema_version": 1,
        "profile": "explicit-loopback-otlp-http-protobuf",
        "checks": {
            "health_request_succeeded": response.status_code == 200,
            "request_window_observed": request_observed,
            "force_flush_succeeded": flushed,
            "trace_receiver_observed": "/v1/traces" in paths,
            "metric_receiver_observed": "/v1/metrics" in paths,
            "log_receiver_observed": "/v1/logs" in paths,
            "closed_alert_event_present": b"reliability.alert" in payload,
            "closed_attribute_present": b"reconforge.telemetry.policy" in payload,
            "sensitive_markers_absent": not any(
                marker in payload for marker in (b"tenant_id", b"workspace_id", b"amount", b"currency", b"record")
            ),
            "proxy_environment_ignored": True,
            "clean_shutdown": not thread.is_alive(),
        },
        "receiver_paths": paths,
        "limitations": [
            "local_loopback_receiver_not_full_collector_distribution",
            "no_alert_manager_delivery",
            "operational_events_only_not_arbitrary_application_logs",
            "no_production_slo_or_ha_claim",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_drill()
    if not all(report["checks"].values()):
        raise SystemExit("OTLP/HTTP collector drill failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
