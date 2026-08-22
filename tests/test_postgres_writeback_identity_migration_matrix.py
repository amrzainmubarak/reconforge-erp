import hashlib
import json
import runpy
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/schemas/postgres_writeback_identity_migration_matrix.schema.json"
REPORT_PATH = ROOT / "docs/execution/POSTGRES_WRITEBACK_IDENTITY_MIGRATION_MATRIX_2026-08-22.json"
RUNNER_PATH = ROOT / ".github/scripts/verify_postgres_writeback_identity_migration_matrix.py"
OBSERVATION_RUNNER_PATH = ROOT / ".github/scripts/verify_postgres_writeback_identity_migration.py"
POLICY_PATH = ROOT / "docs/security/supply-chain-policy.v1.json"


def _source_digest(path: Path) -> str:
    canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _report() -> dict[str, object]:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def test_retained_postgres_writeback_identity_matrix_is_closed_digest_bound_and_parity_checked() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)

    payload = dict(report)
    supplied = str(payload.pop("report_digest"))
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert supplied == hashlib.sha256(canonical).hexdigest()
    assert datetime.fromisoformat(str(report["executed_at"])).tzinfo is UTC

    runs = report["runs"]
    assert isinstance(runs, list)
    assert [run["runtime"]["postgresql"] for run in runs] == ["16.14", "17.10"]
    assert len({run["history"]["valid_history_sha256"] for run in runs}) == 1
    assert len({run["history"]["invalid_history_sha256"] for run in runs}) == 1
    assert all(all(run["checks"].values()) for run in runs)
    parity = report["parity"]
    assert isinstance(parity, dict)
    assert parity["valid_history_sha256"] == runs[0]["history"]["valid_history_sha256"]
    assert parity["invalid_history_sha256"] == runs[0]["history"]["invalid_history_sha256"]


def test_matrix_subject_supply_chain_and_package_contracts_bind_current_sources() -> None:
    report = _report()
    subject = report["subject"]
    assert isinstance(subject, dict)
    assert subject["migration_source_sha256"] == _source_digest(
        ROOT / "alembic/versions/0089_postgres_writeback_proposal_identity.py"
    )
    assert subject["observation_runner_source_sha256"] == _source_digest(OBSERVATION_RUNNER_PATH)
    assert subject["matrix_runner_source_sha256"] == _source_digest(RUNNER_PATH)
    assert subject["supply_chain_policy_sha256"] == _source_digest(POLICY_PATH)

    namespace = runpy.run_path(str(RUNNER_PATH), run_name="test_e827_matrix_runner")
    assert report["runs"][0]["runtime"]["image"] == namespace["POSTGRES_16_IMAGE_REFERENCE"]
    assert report["runs"][1]["runtime"]["image"] == namespace["POSTGRES_17_IMAGE_REFERENCE"]

    manifest = set((ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines())
    assert {
        "include .github/scripts/verify_postgres_writeback_identity_migration_matrix.py",
        "include docs/execution/POSTGRES_WRITEBACK_IDENTITY_MIGRATION_MATRIX_2026-08-22.json",
        "include docs/schemas/postgres_writeback_identity_migration_matrix.schema.json",
        "include tests/test_postgres_writeback_identity_migration_matrix.py",
        "include docs/adr/0541-prove-writeback-migration-supported-version-matrix.md",
    } <= manifest


def test_ci_runs_and_preserves_the_closed_writeback_migration_matrix() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    job = workflow["jobs"]["server-boundaries"]
    assert job["services"]["postgres"]["image"] == policy["container_resolution"]["service_images"]["postgres_16_ci"]

    steps = job["steps"]
    names = [str(step.get("name", "")) for step in steps]
    matrix_index = names.index("Run PostgreSQL write-back migration version matrix")
    upload_index = names.index("Upload PostgreSQL write-back migration matrix")
    live_index = names.index("Run live server-boundary tests")
    assert matrix_index < upload_index < live_index
    matrix_step = steps[matrix_index]
    assert matrix_step["env"]["RECONFORGE_WRITEBACK_MATRIX_REPORT"] == (
        "${{ runner.temp }}/reconforge-writeback-migration-matrix.json"
    )
    assert str(matrix_step["run"]).strip() == (
        'uv run --no-sync python .github/scripts/verify_postgres_writeback_identity_migration_matrix.py '
        '--output "${RECONFORGE_WRITEBACK_MATRIX_REPORT}"'
    )
    upload = steps[upload_index]
    assert upload["if"] == "always()"
    assert upload["uses"] == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    assert upload["with"]["if-no-files-found"] == "ignore"


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    (
        (lambda report: report["runs"][0]["checks"].update(cleanup_complete=False), "runs.0.checks.cleanup_complete"),
        (lambda report: report["runs"][0]["runtime"].update(postgresql="16.13"), "runs.0.runtime.postgresql"),
        (lambda report: report["parity"].update(all_checks_passed=False), "parity.all_checks_passed"),
        (lambda report: report.update(undeclared=True), ""),
    ),
)
def test_matrix_schema_refuses_failed_drifted_or_undeclared_evidence(mutation: object, expected_path: str) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = _report()
    assert callable(mutation)
    mutation(report)
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(report))
    assert errors
    paths = {".".join(str(part) for part in error.path) for error in errors}
    assert expected_path in paths
