import hashlib
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/schemas/postgres_writeback_identity_migration_drill.schema.json"
REPORT_PATH = ROOT / "docs/execution/POSTGRES_WRITEBACK_IDENTITY_MIGRATION_DRILL_CLEANUP_2026-10-03.json"
RUNNER_PATH = ROOT / ".github/scripts/verify_postgres_writeback_identity_migration.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_postgres_writeback_identity_migration", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("write-back identity migration drill runner is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("report_date", ["2026-08-22", "2026-10-03", "CLEANUP_2026-10-03"])
def test_retained_writeback_identity_migration_drill_is_closed_and_digest_bound(report_date: str) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads((ROOT / f"docs/execution/POSTGRES_WRITEBACK_IDENTITY_MIGRATION_DRILL_{report_date}.json").read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(report)

    payload = dict(report)
    supplied_digest = str(payload.pop("report_digest"))
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert supplied_digest == hashlib.sha256(canonical).hexdigest()
    assert report["history"]["valid_history_sha256"] != report["history"]["invalid_history_sha256"]
    assert datetime.fromisoformat(report["executed_at"]).tzinfo is UTC


def test_drill_runner_and_retained_report_bind_the_same_runtime_contract() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    runner = _load_runner()
    assert ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head() == runner.TARGET_REVISION

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
        "include docs/execution/POSTGRES_WRITEBACK_IDENTITY_MIGRATION_DRILL_2026-10-03.json",
        "include docs/execution/POSTGRES_WRITEBACK_IDENTITY_MIGRATION_DRILL_CLEANUP_2026-10-03.json",
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


def _cleanup_fixture(monkeypatch: pytest.MonkeyPatch, runner: ModuleType) -> tuple[list[tuple[str, ...]], list[float]]:
    commands: list[tuple[str, ...]] = []
    elapsed = [0.0]

    def run(command: tuple[str, ...], *, capture: bool = False) -> str:
        commands.append(command)
        return "a" * 64 if capture else ""

    def sleep(seconds: float) -> None:
        elapsed[0] += seconds

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: elapsed[0], sleep=sleep))
    return commands, elapsed


@pytest.mark.parametrize("delayed_probes", [0, 2])
def test_owned_cleanup_waits_for_successfully_observed_removal(
    monkeypatch: pytest.MonkeyPatch, delayed_probes: int,
) -> None:
    runner = _load_runner()
    commands, elapsed = _cleanup_fixture(monkeypatch, runner)
    probes = []

    def probe(command: tuple[str, ...], **options: Any) -> SimpleNamespace:
        probes.append(command)
        assert 0 < options["timeout"] <= runner.CLEANUP_TIMEOUT_SECONDS
        assert options["shell"] is False
        assert command == ("docker", "ps", "--all", "--no-trunc", "--quiet", "--filter", "id=" + "a" * 64)
        return SimpleNamespace(returncode=0, stdout="a" * 64 + "\n" if len(probes) <= delayed_probes else "")

    monkeypatch.setattr(runner.subprocess, "run", probe)
    runner._cleanup_owned_container("reconforge-owned-fixture", "a" * 64)
    assert commands == [
        ("docker", "inspect", "--format", "{{.Id}}", "reconforge-owned-fixture"),
        ("docker", "stop", "--time", "10", "a" * 64),
    ]
    assert len(probes) == delayed_probes + 1
    assert elapsed[0] < runner.CLEANUP_TIMEOUT_SECONDS


def test_owned_cleanup_refuses_persistent_container_at_bounded_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    _, elapsed = _cleanup_fixture(monkeypatch, runner)
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="a" * 64))
    with pytest.raises(runner.DrillError, match="cleanup was not verified"):
        runner._cleanup_owned_container("reconforge-owned-fixture", "a" * 64)
    assert elapsed[0] == runner.CLEANUP_TIMEOUT_SECONDS


@pytest.mark.parametrize("failure", ["daemon", "timeout", "unexpected_identity"])
def test_owned_cleanup_never_turns_failed_or_unexpected_probe_into_absence(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    runner = _load_runner()
    _, elapsed = _cleanup_fixture(monkeypatch, runner)

    def probe(command: tuple[str, ...], **options: Any) -> SimpleNamespace:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, options["timeout"])
        return SimpleNamespace(returncode=1 if failure == "daemon" else 0, stdout="" if failure == "daemon" else "b" * 64)

    monkeypatch.setattr(runner.subprocess, "run", probe)
    with pytest.raises(runner.DrillError):
        runner._cleanup_owned_container("reconforge-owned-fixture", "a" * 64)
    assert elapsed[0] == 0


def test_owned_cleanup_identity_mismatch_never_stops_container(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    commands, _ = _cleanup_fixture(monkeypatch, runner)
    with pytest.raises(runner.DrillError, match="unexpected Docker container"):
        runner._cleanup_owned_container("reconforge-owned-fixture", "b" * 64)
    assert commands == [("docker", "inspect", "--format", "{{.Id}}", "reconforge-owned-fixture")]


@pytest.mark.parametrize("container_id", ["", "a" * 12, "a" * 63 + ";"])
def test_owned_cleanup_requires_full_identity_before_any_docker_command(
    monkeypatch: pytest.MonkeyPatch, container_id: str,
) -> None:
    runner = _load_runner()
    commands, _ = _cleanup_fixture(monkeypatch, runner)
    with pytest.raises(runner.DrillError, match="full Docker container identity"):
        runner._cleanup_owned_container("reconforge-owned-fixture", container_id)
    assert commands == []
