import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from statistics import median

import jsonschema
import yaml

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
    assert _script_module().build_report(
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
        ],
        executed_at="2026-08-04",
    )["executed_at"] == "2026-08-04"


def test_current_postgres_ha_dr_artifact_is_schema_valid_and_packaged() -> None:
    artifact = json.loads(
        (ROOT / "docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION_2026-08-05.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "docs/schemas/ha_dr_repeated_drill_report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(artifact)
    assert "include docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION_2026-08-05.json" in (
        ROOT / "MANIFEST.in"
    ).read_text(encoding="utf-8")


def test_latest_postgres_ha_dr_artifact_is_schema_valid_and_reproducible() -> None:
    artifact = json.loads(
        (ROOT / "docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION_2026-08-06.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "docs/schemas/ha_dr_repeated_drill_report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(artifact)
    assert artifact["summary"]["all_runs_passed"] is True
    assert artifact["summary"]["zero_acknowledged_transaction_loss_runs"] == 3
    assert artifact["summary"]["failover_rto_max_seconds"] == 11.137
    assert artifact["summary"]["failback_rto_max_seconds"] == 0.968
    assert "include docs/execution/POSTGRES_HA_DR_REPEATED_VERIFICATION_2026-08-06.json" in (
        ROOT / "MANIFEST.in"
    ).read_text(encoding="utf-8")


def test_ci_runs_the_repeated_postgres_ha_dr_drill_and_uploads_its_report() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["postgres-ha-dr"]
    run_steps = [step["run"] for step in job["steps"] if "run" in step]
    assert any("verify_postgres_ha_dr_repeated.py" in run and "--executed-at" in run for run in run_steps)
    artifact_steps = [step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")]
    assert len(artifact_steps) == 1
    assert artifact_steps[0]["with"]["name"] == "reconforge-postgres-ha-dr-report"
