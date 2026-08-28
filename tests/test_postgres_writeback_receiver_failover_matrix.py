from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/schemas/postgres_writeback_receiver_failover_matrix.schema.json"
REPORT_PATH = ROOT / "docs/execution/POSTGRES_WRITEBACK_RECEIVER_FAILOVER_MATRIX_2026-08-22.json"
CURRENT_REPORT_PATH = ROOT / "docs/execution/POSTGRES_WRITEBACK_RECEIVER_FAILOVER_MATRIX_2026-08-23.json"
RUNNER_PATH = ROOT / ".github/scripts/verify_postgres_writeback_receiver_failover_matrix.py"
RECEIVER_PATH = ROOT / "reconforge/connectors/writeback_receiver.py"
POSTGRES_RECEIVER_PATH = ROOT / "reconforge/connectors/writeback_receiver_postgres.py"
POLICY_PATH = ROOT / "docs/security/supply-chain-policy.v1.json"


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _report() -> dict[str, Any]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_current_receiver_failover_matrix_is_schema_valid_and_replay_parity_bound() -> None:
    report = json.loads(CURRENT_REPORT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)
    payload = dict(report)
    supplied = str(payload.pop("report_digest"))
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert report["parity"]["all_checks_passed"] is True
    assert report["parity"]["all_cleanup_complete"] is True
    assert report["parity"]["canonical_history_sha256"] == report["sqlite_reference"]["canonical_history_sha256"]
    assert [run["runtime"]["postgresql"] for run in report["runs"]] == ["16.14", "17.10"]
    assert all(run["recovery"]["acknowledged_effect_rpo"] == 0 for run in report["runs"])


def test_retained_receiver_failover_matrix_is_closed_digest_and_source_bound() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)

    payload = dict(report)
    supplied = str(payload.pop("report_digest"))
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert datetime.fromisoformat(str(report["executed_at"])).tzinfo is UTC

    subject = report["subject"]
    assert subject["receiver_source_sha256"] == _source_digest(RECEIVER_PATH)
    assert subject["postgres_receiver_source_sha256"] == _source_digest(POSTGRES_RECEIVER_PATH)
    assert subject["matrix_runner_source_sha256"] == _source_digest(RUNNER_PATH)
    assert subject["supply_chain_policy_sha256"] == _source_digest(POLICY_PATH)
    subprocess.run(
        ("git", "cat-file", "-e", f"{subject['base_commit']}^{{commit}}"),
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def test_matrix_proves_acknowledged_replay_uncertain_apply_rejoin_restart_and_parity() -> None:
    report = _report()
    runs = report["runs"]
    assert [run["runtime"]["postgresql"] for run in runs] == ["16.14", "17.10"]
    assert all(run["runtime"]["node_count"] == 2 for run in runs)
    assert all(run["runtime"]["failure_domains"] == 1 for run in runs)
    assert all(not any(run["runtime"]["application_role"].values()) for run in runs)
    assert all(len(run["checks"]) == 23 and all(run["checks"].values()) for run in runs)
    assert all(run["cases"]["acknowledged_response_loss"]["retry_disposition"] == "replayed" for run in runs)
    assert all(run["cases"]["partition_uncertainty"]["sync_rep_wait_observed"] for run in runs)
    assert all(run["cases"]["partition_uncertainty"]["retry_disposition"] == "applied" for run in runs)
    assert all(run["cases"]["promoted_primary_restart"]["endpoint_rediscovered"] for run in runs)
    assert all(run["cases"]["promoted_primary_restart"]["host_port_changed"] for run in runs)
    assert all(run["recovery"]["acknowledged_effect_rpo"] == 0 for run in runs)
    assert all(0 <= run["recovery"]["failover_rto_seconds"] <= 60 for run in runs)

    final_histories = {run["history"]["final_sha256"] for run in runs}
    final_histories.update(run["history"]["rejoined_sha256"] for run in runs)
    final_histories.update(run["history"]["after_restart_sha256"] for run in runs)
    final_histories.add(report["sqlite_reference"]["canonical_history_sha256"])
    assert final_histories == {report["parity"]["canonical_history_sha256"]}
    assert len({run["history"]["before_failover_sha256"] for run in runs}) == 1
    assert len({run["cases"]["acknowledged_response_loss"]["request_digest"] for run in runs}) == 1
    assert len({run["cases"]["partition_uncertainty"]["request_digest"] for run in runs}) == 1


def test_matrix_exact_images_package_and_secret_boundaries() -> None:
    report = _report()
    namespace = runpy.run_path(str(RUNNER_PATH), run_name="test_e830_failover_runner")
    assert report["runs"][0]["runtime"]["image"] == namespace["POSTGRES_16_IMAGE_REFERENCE"]
    assert report["runs"][1]["runtime"]["image"] == namespace["POSTGRES_17_IMAGE_REFERENCE"]
    manifest = set((ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines())
    assert {
        "include .github/scripts/verify_postgres_writeback_receiver_failover_matrix.py",
        "include docs/execution/POSTGRES_WRITEBACK_RECEIVER_FAILOVER_MATRIX_2026-08-22.json",
        "include docs/schemas/postgres_writeback_receiver_failover_matrix.schema.json",
        "include tests/test_postgres_writeback_receiver_failover_matrix.py",
        "include docs/adr/0544-prove-receiver-replay-across-synchronous-postgres-failover.md",
    } <= manifest
    raw = REPORT_PATH.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD" not in raw
    assert "PGPASSWORD" not in raw
    assert "postgresql://" not in raw
    assert '"payload"' not in raw


def test_ci_runs_and_preserves_receiver_failover_matrix_before_live_boundaries() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["server-boundaries"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    run_index = names.index("Run PostgreSQL write-back receiver failover matrix")
    upload_index = names.index("Upload PostgreSQL write-back receiver failover matrix")
    live_index = names.index("Run live server-boundary tests")
    assert run_index < upload_index < live_index
    run_step = steps[run_index]
    assert run_step["env"]["RECONFORGE_RECEIVER_FAILOVER_REPORT"] == (
        "${{ runner.temp }}/reconforge-writeback-receiver-failover.json"
    )
    assert str(run_step["run"]).strip() == (
        "uv run --no-sync python .github/scripts/verify_postgres_writeback_receiver_failover_matrix.py "
        '--output "${RECONFORGE_RECEIVER_FAILOVER_REPORT}"'
    )
    upload = steps[upload_index]
    assert upload["if"] == "always()"
    assert upload["uses"] == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert upload["with"]["if-no-files-found"] == "ignore"


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    (
        (lambda report: report["runs"][0]["checks"].update(primary_identity_fenced=False), "runs.0"),
        (lambda report: report["runs"][0]["runtime"].update(failure_domains=2), "runs.0"),
        (lambda report: report["runs"][1]["recovery"].update(failover_rto_seconds=60.001), "runs.1"),
        (
            lambda report: report["runs"][1]["cases"]["partition_uncertainty"].update(
                primary_outcome="committed"
            ),
            "runs.1",
        ),
        (lambda report: report["parity"].update(all_checks_passed=False), "parity.all_checks_passed"),
        (lambda report: report.update(undeclared=True), ""),
    ),
)
def test_failover_schema_refuses_false_drifted_or_undeclared_evidence(
    mutation: object,
    expected_path: str,
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    assert callable(mutation)
    mutation(report)
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(report))
    assert errors
    paths = {".".join(str(part) for part in error.path) for error in errors}
    assert expected_path in paths
