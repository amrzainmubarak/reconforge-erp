import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/schemas/postgres_writeback_identity_migration_drill.schema.json"
REPORT_PATH = ROOT / "docs/execution/POSTGRES_WRITEBACK_IDENTITY_MIGRATION_DRILL_2026-08-22.json"
RUNNER_PATH = ROOT / ".github/scripts/verify_postgres_writeback_identity_migration.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_postgres_writeback_identity_migration", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("write-back identity migration drill runner is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_writeback_identity_migration_drill_is_closed_and_digest_bound() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)

    payload = dict(report)
    supplied_digest = str(payload.pop("report_digest"))
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert supplied_digest == hashlib.sha256(canonical).hexdigest()
    assert report["history"]["valid_history_sha256"] != report["history"]["invalid_history_sha256"]
    assert datetime.fromisoformat(report["executed_at"]).tzinfo is UTC


def test_drill_runner_and_retained_report_bind_the_same_runtime_contract() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    runner = _load_runner()

    assert report["runtime"]["image"] == runner.IMAGE_REFERENCE
    assert report["runtime"]["source_revision"] == runner.SOURCE_REVISION
    assert report["runtime"]["target_revision"] == runner.TARGET_REVISION
    assert report["subject"]["migration_commit"] == runner._migration_commit()
    assert report["subject"]["migration_source_sha256"] == runner._source_digest(runner.MIGRATION_PATH)
    assert report["subject"]["runner_source_sha256"] == runner._source_digest(RUNNER_PATH)
    assert runner.EXPECTED_AUDIT_ERROR in RUNNER_PATH.read_text(encoding="utf-8")

    manifest = set((ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines())
    assert {
        "include .github/scripts/verify_postgres_writeback_identity_migration.py",
        "include docs/adr/0540-prove-writeback-migration-refusal-and-independent-restore.md",
        "include docs/execution/POSTGRES_WRITEBACK_IDENTITY_MIGRATION_DRILL_2026-08-22.json",
        "include docs/schemas/postgres_writeback_identity_migration_drill.schema.json",
        "include tests/test_postgres_writeback_identity_migration_drill.py",
    } <= manifest


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"image_reference": "postgres:16-alpine", "expected_postgresql": "16.14"}, "digest-pinned"),
        ({"image_reference": "postgres:16-alpine@sha256:" + "a" * 64, "expected_postgresql": "16"}, "version"),
        (
            {
                "image_reference": "postgres:16-alpine@sha256:" + "a" * 64,
                "expected_postgresql": "16.14",
                "container_prefix": "../escape",
            },
            "prefix",
        ),
    ),
)
def test_observation_runtime_profile_fails_before_docker_for_unbounded_inputs(
    overrides: dict[str, str], message: str
) -> None:
    runner = _load_runner()
    arguments = {
        "image_reference": "postgres:16-alpine@sha256:" + "a" * 64,
        "expected_postgresql": "16.14",
        "container_prefix": "reconforge-writeback-test",
        **overrides,
    }
    with pytest.raises(runner.DrillError, match=message):
        runner.run_observation(**arguments)


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    (
        (lambda report: report["checks"].update(cleanup_complete=False), "checks.cleanup_complete"),
        (lambda report: report["runtime"].update(postgresql="18.0"), "runtime.postgresql"),
        (lambda report: report.update(undeclared=True), ""),
    ),
)
def test_drill_schema_refuses_failed_or_undeclared_evidence(mutation: object, expected_path: str) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert callable(mutation)
    mutation(report)

    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(report))
    assert errors
    paths = {".".join(str(part) for part in error.path) for error in errors}
    assert expected_path in paths
