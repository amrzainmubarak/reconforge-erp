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
SCHEMA_PATH = ROOT / "docs/schemas/postgres_writeback_recovery_compensation_matrix.schema.json"
REPORT_PATH = ROOT / "docs/execution/POSTGRES_WRITEBACK_RECOVERY_COMPENSATION_MATRIX_2026-08-22.json"
RUNNER_PATH = ROOT / ".github/scripts/verify_postgres_writeback_recovery_compensation_matrix.py"
WRITEBACK_PATH = ROOT / "reconforge/connectors/writeback.py"
POSTGRES_PATH = ROOT / "reconforge/infrastructure/postgres_writeback.py"
SQLITE_PATH = ROOT / "reconforge/infrastructure/sqlite_writeback.py"
MIGRATION_PATH = ROOT / "alembic/versions/0089_postgres_writeback_proposal_identity.py"
POLICY_PATH = ROOT / "docs/security/supply-chain-policy.v1.json"


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _report() -> dict[str, Any]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_retained_recovery_compensation_report_is_schema_and_source_bound() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)
    payload = dict(report)
    supplied = str(payload.pop("report_digest"))
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert supplied == hashlib.sha256(encoded).hexdigest()
    assert datetime.fromisoformat(str(report["executed_at"])).tzinfo is UTC
    subject = report["subject"]
    assert subject["writeback_source_sha256"] == _source_digest(WRITEBACK_PATH)
    assert subject["postgres_persistence_source_sha256"] == _source_digest(POSTGRES_PATH)
    assert subject["sqlite_persistence_source_sha256"] == _source_digest(SQLITE_PATH)
    assert subject["migration_source_sha256"] == _source_digest(MIGRATION_PATH)
    assert subject["supply_chain_policy_sha256"] == _source_digest(POLICY_PATH)
    assert subject["matrix_runner_source_sha256"] == _source_digest(RUNNER_PATH)
    subprocess.run(
        ("git", "cat-file", "-e", f"{subject['base_commit']}^{{commit}}"),
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def test_matrix_proves_recovery_compensation_and_sqlite_postgres_parity() -> None:
    report = _report()
    runs = report["runs"]
    assert [run["runtime"]["postgresql"] for run in runs] == ["16.14", "17.10"]
    assert all(not any(run["role_flags"].values()) for run in runs)
    assert all(len(run["checks"]) == 16 and all(run["checks"].values()) for run in runs)
    assert len(report["sqlite_reference"]["checks"]) == 13
    assert all(report["sqlite_reference"]["checks"].values())
    assert all(run["statuses"] == report["sqlite_reference"]["statuses"] for run in runs)
    assert all(run["history_sha256"] == report["parity"]["history_sha256"] for run in runs)
    assert report["sqlite_reference"]["history_sha256"] == report["parity"]["history_sha256"]
    final = runs[0]["history"][-1]["intent_json"]
    assert final["status"] == "compensated"
    assert final["acknowledgement"]["idempotency_key"] == "e831-original-key:compensation"
    assert final["idempotency_key"] == "e831-original-key"
    assert report["parity"]["all_checks_passed"] is True
    assert report["parity"]["all_cleanup_complete"] is True


def test_matrix_package_ci_and_secret_boundaries_are_closed() -> None:
    report = _report()
    namespace = runpy.run_path(str(RUNNER_PATH), run_name="test_e831_recovery_compensation_runner")
    assert report["runs"][0]["runtime"]["image"] == namespace["POSTGRES_16_IMAGE_REFERENCE"]
    assert report["runs"][1]["runtime"]["image"] == namespace["POSTGRES_17_IMAGE_REFERENCE"]
    manifest = set((ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines())
    assert {
        "include .github/scripts/verify_postgres_writeback_recovery_compensation_matrix.py",
        "include docs/execution/POSTGRES_WRITEBACK_RECOVERY_COMPENSATION_MATRIX_2026-08-22.json",
        "include docs/schemas/postgres_writeback_recovery_compensation_matrix.schema.json",
        "include tests/test_postgres_writeback_recovery_compensation_matrix.py",
        "include docs/adr/0545-prove-writeback-recovery-compensation-parity.md",
    } <= manifest
    raw = REPORT_PATH.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD" not in raw
    assert "PGPASSWORD" not in raw
    assert "postgresql://" not in raw
    assert '"payload"' not in raw


def test_ci_runs_and_preserves_recovery_compensation_matrix_before_live_boundaries() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["server-boundaries"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    run_index = names.index("Run PostgreSQL write-back recovery compensation matrix")
    upload_index = names.index("Upload PostgreSQL write-back recovery compensation matrix")
    live_index = names.index("Run live server-boundary tests")
    assert run_index < upload_index < live_index
    run_step = steps[run_index]
    assert run_step["env"]["RECONFORGE_WRITEBACK_RECOVERY_COMPENSATION_REPORT"] == (
        "${{ runner.temp }}/reconforge-writeback-recovery-compensation.json"
    )
    assert str(run_step["run"]).strip() == (
        "uv run --no-sync python .github/scripts/verify_postgres_writeback_recovery_compensation_matrix.py "
        '--output "${RECONFORGE_WRITEBACK_RECOVERY_COMPENSATION_REPORT}"'
    )
    upload = steps[upload_index]
    assert upload["if"] == "always()"
    assert upload["uses"] == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert upload["with"]["if-no-files-found"] == "ignore"


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    (
        (lambda report: report["runs"][0]["checks"].update(direct_update_refused=False), "runs.0"),
        (lambda report: report["runs"][0]["role_flags"].update(superuser=True), "runs.0.role_flags"),
        (lambda report: report["runs"][1]["runtime"].update(postgresql="16.14"), "runs.1.runtime"),
        (
            lambda report: report["runs"][1]["history"][-1]["intent_json"]["acknowledgement"].update(
                idempotency_key="wrong-key"
            ),
            "runs.1",
        ),
        (lambda report: report["parity"].update(all_checks_passed=False), "parity.all_checks_passed"),
        (lambda report: report.update(undeclared=True), ""),
    ),
)
def test_schema_refuses_false_drifted_or_undeclared_recovery_evidence(
    mutation: object, expected_path: str
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    assert callable(mutation)
    mutation(report)
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(report))
    assert errors
    paths = {".".join(str(part) for part in error.path) for error in errors}
    assert any(path == expected_path or path.startswith(expected_path + ".") for path in paths)
