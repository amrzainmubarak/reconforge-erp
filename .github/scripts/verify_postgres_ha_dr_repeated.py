"""Run the bounded single-host PostgreSQL HA/DR drill three times without cherry-picking."""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNS = 3


def _run_once() -> dict[str, Any]:
    completed = subprocess.run(  # nosec B603
        (sys.executable, str(ROOT / ".github/scripts/verify_postgres_ha_dr.py")),
        cwd=ROOT,
        check=True,
        shell=False,
        text=True,
        capture_output=True,
        timeout=900,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError("HA/DR child emitted an unexpected output shape")
    value = json.loads(lines[0])
    if not isinstance(value, dict):
        raise RuntimeError("HA/DR child output is not an object")
    labelled_containers = subprocess.run(
        ("docker", "ps", "--all", "--filter", "label=reconforge.drill", "--format", "{{.ID}}"),
        cwd=ROOT, check=True, shell=False, text=True, capture_output=True, timeout=30,  # nosec B603
    ).stdout.strip()
    labelled_volumes = subprocess.run(
        ("docker", "volume", "ls", "--filter", "label=reconforge.drill", "--format", "{{.Name}}"),
        cwd=ROOT, check=True, shell=False, text=True, capture_output=True, timeout=30,  # nosec B603
    ).stdout.strip()
    labelled_networks = subprocess.run(
        ("docker", "network", "ls", "--filter", "label=reconforge.drill", "--format", "{{.Name}}"),
        cwd=ROOT, check=True, shell=False, text=True, capture_output=True, timeout=30,  # nosec B603
    ).stdout.strip()
    if labelled_containers or labelled_volumes or labelled_networks:
        raise RuntimeError("HA/DR child left labelled Docker resources")
    value["cleanup_passed"] = True
    return value


def build_report(results: list[dict[str, Any]], *, executed_at: str = "2026-07-30") -> dict[str, Any]:
    if len(results) != RUNS:
        raise ValueError("exactly three complete runs are required")
    try:
        date.fromisoformat(executed_at)
    except ValueError as exc:
        raise ValueError("executed_at must be an ISO date") from exc
    runs = [
        {
            "run": index,
            "failover_rpo_transactions": int(result["rpo_transactions"]),
            "failover_rto_seconds": float(result["rto_seconds"]),
            "failback_rpo_transactions": int(result["failback_rpo_transactions"]),
            "failback_rto_seconds": float(result["failback_rto_seconds"]),
            "final_sequence": int(result["sentinel_sequences"][-1]),
            "cleanup_passed": result.get("cleanup_passed") is True,
        }
        for index, result in enumerate(results, start=1)
    ]
    failover = [run["failover_rto_seconds"] for run in runs]
    failback = [run["failback_rto_seconds"] for run in runs]
    return {
        "schema_version": 1,
        "executed_at": executed_at,
        "profile": "docker-single-host-primary-synchronous-standby-v1",
        "infrastructure": {
            "docker_server": "Docker Engine 29.6.2",
            "postgres_image": "postgres:17.10-alpine",
            "node_count_per_run": 2,
            "failure_domains_per_run": 1,
        },
        "runs": runs,
        "summary": {
            "run_count": RUNS,
            "zero_acknowledged_transaction_loss_runs": sum(
                run["failover_rpo_transactions"] == run["failback_rpo_transactions"] == 0 for run in runs
            ),
            "failover_rto_min_seconds": min(failover),
            "failover_rto_median_seconds": median(failover),
            "failover_rto_max_seconds": max(failover),
            "failback_rto_min_seconds": min(failback),
            "failback_rto_median_seconds": median(failback),
            "failback_rto_max_seconds": max(failback),
            "rto_ceiling_seconds": 60.0,
            "all_runs_passed": all(
                run["cleanup_passed"]
                and run["failover_rpo_transactions"] == 0
                and run["failback_rpo_transactions"] == 0
                and run["failover_rto_seconds"] <= 60.0
                and run["failback_rto_seconds"] <= 60.0
                for run in runs
            ),
        },
        "limitations": [
            "single_host_not_host_loss",
            "no_cross_zone_or_cross_region",
            "manual_controller_not_automatic_failover",
            "no_quorum_or_witness",
            "synthetic_data_and_key_only",
            "three_runs_not_production_slo",
            "no_enterprise_ready_claim",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--executed-at",
        default=datetime.now(UTC).date().isoformat(),
        help="ISO execution date recorded in the report (defaults to current UTC date)",
    )
    args = parser.parse_args()
    report = build_report([_run_once() for _ in range(RUNS)], executed_at=args.executed_at)
    if not report["summary"]["all_runs_passed"]:
        raise SystemExit("Repeated HA/DR gate failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
