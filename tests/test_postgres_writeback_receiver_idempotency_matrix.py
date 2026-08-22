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
SCHEMA_PATH = ROOT / "docs/schemas/postgres_writeback_receiver_idempotency_matrix.schema.json"
REPORT_PATH = ROOT / "docs/execution/POSTGRES_WRITEBACK_RECEIVER_IDEMPOTENCY_MATRIX_2026-08-22.json"
RUNNER_PATH = ROOT / ".github/scripts/verify_postgres_writeback_receiver_idempotency_matrix.py"
RECEIVER_PATH = ROOT / "reconforge/connectors/writeback_receiver.py"
POSTGRES_RECEIVER_PATH = ROOT / "reconforge/connectors/writeback_receiver_postgres.py"
SQLITE_REPORT_PATH = ROOT / "docs/execution/WRITEBACK_RECEIVER_IDEMPOTENCY_DRILL_2026-08-22.json"
POLICY_PATH = ROOT / "docs/security/supply-chain-policy.v1.json"


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _report() -> dict[str, Any]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_retained_postgres_receiver_matrix_is_closed_digest_bound_and_source_bound() -> None:
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
    assert isinstance(subject, dict)
    assert subject["receiver_source_sha256"] == _source_digest(RECEIVER_PATH)
    assert subject["postgres_receiver_source_sha256"] == _source_digest(POSTGRES_RECEIVER_PATH)
    assert subject["matrix_runner_source_sha256"] == _source_digest(RUNNER_PATH)
    assert subject["supply_chain_policy_sha256"] == _source_digest(POLICY_PATH)
    sqlite_report = json.loads(SQLITE_REPORT_PATH.read_text(encoding="utf-8"))
    assert subject["sqlite_report_sha256"] == sqlite_report["report_digest"]
    subprocess.run(
        ("git", "cat-file", "-e", f"{subject['base_commit']}^{{commit}}"),
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def test_matrix_proves_version_and_backend_parity_with_one_effect_per_key() -> None:
    report = _report()
    runs = report["runs"]
    parity = report["parity"]
    assert isinstance(runs, list)
    assert isinstance(parity, dict)
    assert [run["runtime"]["postgresql"] for run in runs] == ["16.14", "17.10"]
    assert all(run["cases"]["concurrent"]["applied"] == 1 for run in runs)
    assert all(run["cases"]["concurrent"]["replayed"] == 7 for run in runs)
    assert all(run["history"]["receipts"] == run["history"]["effects"] == 3 for run in runs)
    assert all(all(run["checks"].values()) for run in runs)
    histories = {run["history"]["canonical_sha256"] for run in runs}
    histories.add(json.loads(SQLITE_REPORT_PATH.read_text(encoding="utf-8"))["history"]["canonical_sha256"])
    assert histories == {parity["canonical_history_sha256"]}


def test_matrix_runtime_images_package_and_secret_boundaries_are_exact() -> None:
    report = _report()
    namespace = runpy.run_path(str(RUNNER_PATH), run_name="test_e829_matrix_runner")
    assert report["runs"][0]["runtime"]["image"] == namespace["POSTGRES_16_IMAGE_REFERENCE"]
    assert report["runs"][1]["runtime"]["image"] == namespace["POSTGRES_17_IMAGE_REFERENCE"]
    manifest = set((ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines())
    assert {
        "include reconforge/connectors/writeback_receiver_postgres.py",
        "include .github/scripts/verify_postgres_writeback_receiver_idempotency_matrix.py",
        "include docs/execution/POSTGRES_WRITEBACK_RECEIVER_IDEMPOTENCY_MATRIX_2026-08-22.json",
        "include docs/schemas/postgres_writeback_receiver_idempotency_matrix.schema.json",
        "include tests/test_connector_writeback_receiver_postgres.py",
        "include tests/test_postgres_writeback_receiver_idempotency_matrix.py",
        "include docs/adr/0543-prove-postgres-writeback-receiver-idempotency-parity.md",
    } <= manifest
    raw = REPORT_PATH.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD" not in raw
    assert "Authorization" not in raw
    assert '"payload"' not in raw


def test_ci_runs_and_preserves_postgres_receiver_matrix_before_live_boundaries() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["server-boundaries"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    run_index = names.index("Run PostgreSQL write-back receiver idempotency matrix")
    upload_index = names.index("Upload PostgreSQL write-back receiver idempotency matrix")
    live_index = names.index("Run live server-boundary tests")
    assert run_index < upload_index < live_index
    run_step = steps[run_index]
    assert run_step["env"]["RECONFORGE_POSTGRES_RECEIVER_REPORT"] == (
        "${{ runner.temp }}/reconforge-postgres-writeback-receiver-idempotency.json"
    )
    assert str(run_step["run"]).strip() == (
        "uv run --no-sync python .github/scripts/verify_postgres_writeback_receiver_idempotency_matrix.py "
        '--output "${RECONFORGE_POSTGRES_RECEIVER_REPORT}"'
    )
    upload = steps[upload_index]
    assert upload["if"] == "always()"
    assert upload["uses"] == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert upload["with"]["if-no-files-found"] == "ignore"


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    (
        (lambda report: report["runs"][0]["checks"].update(cleanup_complete=False), "runs.0"),
        (lambda report: report["runs"][0]["runtime"].update(postgresql="16.13"), "runs.0"),
        (lambda report: report["runs"][1]["cases"]["concurrent"].update(applied=2), "runs.1"),
        (lambda report: report["parity"].update(all_checks_passed=False), "parity.all_checks_passed"),
        (lambda report: report.update(undeclared=True), ""),
    ),
)
def test_matrix_schema_refuses_failed_drifted_or_undeclared_evidence(
    mutation: object, expected_path: str
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    assert callable(mutation)
    mutation(report)
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(report))
    assert errors
    paths = {".".join(str(part) for part in error.path) for error in errors}
    assert expected_path in paths
