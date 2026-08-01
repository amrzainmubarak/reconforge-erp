import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from statistics import median

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def _script_module():
    path = ROOT / ".github/scripts/verify_postgres_ha_dr_repeated.py"
    spec = spec_from_file_location("verify_postgres_ha_dr_repeated", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeated_ha_dr_report_preserves_every_run_and_single_host_boundary() -> None:
    report = json.loads(
        (ROOT / "docs/execution/HA_DR_REPEATED_DOCKER_DRILL_2026-07-30.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "docs/schemas/ha_dr_repeated_drill_report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)
    runs = report["runs"]
    assert [run["run"] for run in runs] == [1, 2, 3]
    failover = [run["failover_rto_seconds"] for run in runs]
    failback = [run["failback_rto_seconds"] for run in runs]
    summary = report["summary"]
    assert (min(failover), median(failover), max(failover)) == (
        summary["failover_rto_min_seconds"], summary["failover_rto_median_seconds"], summary["failover_rto_max_seconds"]
    )
    assert (min(failback), median(failback), max(failback)) == (
        summary["failback_rto_min_seconds"], summary["failback_rto_median_seconds"], summary["failback_rto_max_seconds"]
    )
    assert all(run["failover_rpo_transactions"] == run["failback_rpo_transactions"] == 0 for run in runs)
    assert report["infrastructure"]["failure_domains_per_run"] == 1
    assert "no_quorum_or_witness" in report["limitations"]
    rebuilt = _script_module().build_report(
        [
            {
                "rpo_transactions": run["failover_rpo_transactions"],
                "rto_seconds": run["failover_rto_seconds"],
                "failback_rpo_transactions": run["failback_rpo_transactions"],
                "failback_rto_seconds": run["failback_rto_seconds"],
                "sentinel_sequences": [1, 2, 3, run["final_sequence"]],
                "cleanup_passed": run["cleanup_passed"],
            }
            for run in runs
        ]
    )
    assert rebuilt == report
