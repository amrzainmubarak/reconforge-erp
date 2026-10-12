from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/schemas/postgres_writeback_recovery_compensation_matrix.schema.json"
REPORT_PATH = ROOT / "docs/execution/POSTGRES_WRITEBACK_RECOVERY_COMPENSATION_MATRIX_2026-10-08.json"
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


@pytest.mark.parametrize("report_date", ["2026-10-03", "2026-10-08"])
def test_retained_recovery_compensation_report_is_schema_and_source_bound(report_date: str) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    report = json.loads((ROOT / f"docs/execution/POSTGRES_WRITEBACK_RECOVERY_COMPENSATION_MATRIX_{report_date}.json").read_text(encoding="utf-8"))
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
    # Historical reports remain bound to their recorded policy subject.
    if report_date == "2026-10-08":
        policy_source = POLICY_PATH.read_text(encoding="utf-8")
    else:
        policy_source = subprocess.run(
            ("git", "show", f"{subject['base_commit']}:docs/security/supply-chain-policy.v1.json"),
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    policy_digest = hashlib.sha256(policy_source.replace("\r\n", "\n").encode("utf-8")).hexdigest()
    assert subject["supply_chain_policy_sha256"] == policy_digest
    # Retained evidence stays bound to the original runner, not a later cleanup fix.
    runner_source = subprocess.run(
        ("git", "show", f"{subject['base_commit']}:{RUNNER_PATH.relative_to(ROOT).as_posix()}"),
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    assert subject["matrix_runner_source_sha256"] == hashlib.sha256(runner_source.replace("\r\n", "\n").encode()).hexdigest()
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
        "include docs/execution/POSTGRES_WRITEBACK_RECOVERY_COMPENSATION_MATRIX_2026-10-08.json",
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


def _cleanup_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], list[tuple[str, ...]], list[float]]:
    runner = runpy.run_path(str(RUNNER_PATH), run_name="test_recovery_cleanup_runner")
    namespace = runner["_cleanup_owned_container"].__globals__
    commands: list[tuple[str, ...]] = []
    elapsed = [0.0]

    def run(command: tuple[str, ...], *, capture: bool = False) -> str:
        commands.append(command)
        return "a" * 64 if capture else ""

    def sleep(seconds: float) -> None:
        elapsed[0] += seconds

    monkeypatch.setitem(namespace, "_run", run)
    monkeypatch.setitem(namespace, "time", SimpleNamespace(monotonic=lambda: elapsed[0], sleep=sleep))
    return runner, commands, elapsed


@pytest.mark.parametrize("delayed_probes", [0, 2])
@pytest.mark.parametrize("error_prefix", ["Error: ", "Error response from daemon: "])
def test_owned_cleanup_proves_delayed_removal_after_successful_stop(
    monkeypatch: pytest.MonkeyPatch, delayed_probes: int, error_prefix: str,
) -> None:
    runner, commands, elapsed = _cleanup_fixture(monkeypatch)
    probes = []

    def probe(command: tuple[str, ...], **options: Any) -> SimpleNamespace:
        probes.append(command)
        assert command == ("docker", "container", "inspect", "--format", "{{.Id}}", "a" * 64)
        assert options["shell"] is False and options["check"] is False
        assert 0 < options["timeout"] <= 5.0
        if len(probes) <= delayed_probes:
            return SimpleNamespace(returncode=0, stdout="a" * 64 + "\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr=error_prefix + "No such container: " + "a" * 64 + "\n")

    monkeypatch.setattr(runner["subprocess"], "run", probe)
    runner["_cleanup_owned_container"]("reconforge-owned-fixture", "a" * 64)
    assert commands == [
        ("docker", "container", "inspect", "--format", "{{.Id}}", "reconforge-owned-fixture"),
        ("docker", "stop", "--time", "10", "a" * 64),
    ]
    assert len(probes) == delayed_probes + 1
    assert elapsed[0] == delayed_probes * runner["CLEANUP_POLL_SECONDS"]


def test_owned_cleanup_refuses_permanent_presence_at_bounded_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _, elapsed = _cleanup_fixture(monkeypatch)
    monkeypatch.setattr(runner["subprocess"], "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="a" * 64, stderr=""))
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="cleanup was not verified before the deadline"):
        runner["_cleanup_owned_container"]("reconforge-owned-fixture", "a" * 64)
    assert elapsed[0] == runner["CLEANUP_TIMEOUT_SECONDS"]


def test_owned_cleanup_refuses_an_absence_response_observed_after_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _, elapsed = _cleanup_fixture(monkeypatch)

    def probe(*args: Any, **kwargs: Any) -> SimpleNamespace:
        elapsed[0] = runner["CLEANUP_TIMEOUT_SECONDS"] + 0.001
        return SimpleNamespace(returncode=1, stdout="", stderr="Error: No such container: " + "a" * 64)

    monkeypatch.setattr(runner["subprocess"], "run", probe)
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="exceeded the cleanup deadline"):
        runner["_cleanup_owned_container"]("reconforge-owned-fixture", "a" * 64)


@pytest.mark.parametrize("failure", ["daemon", "permission", "ambiguous", "wrong_absent_id", "wrong_present_id", "extra_stdout", "timeout", "os_error"])
def test_owned_cleanup_never_accepts_failed_or_ambiguous_inspection(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    runner, _, elapsed = _cleanup_fixture(monkeypatch)

    def probe(command: tuple[str, ...], **options: Any) -> SimpleNamespace:
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, options["timeout"])
        if failure == "os_error":
            raise OSError("synthetic unavailable Docker executable")
        stdout, stderr, code = "", "", 1
        if failure == "daemon":
            stderr = "Cannot connect to the Docker daemon"
        elif failure == "permission":
            stderr = "permission denied"
        elif failure == "ambiguous":
            stderr = "Error: No such object: " + "a" * 64
        elif failure == "wrong_absent_id":
            stderr = "Error: No such container: " + "b" * 64
        elif failure == "wrong_present_id":
            stdout, code = "b" * 64, 0
        else:
            stdout, stderr = "unexpected output", "Error: No such container: " + "a" * 64
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(runner["subprocess"], "run", probe)
    with pytest.raises(runner["RecoveryCompensationMatrixError"]):
        runner["_cleanup_owned_container"]("reconforge-owned-fixture", "a" * 64)
    assert elapsed[0] == 0.0


def test_owned_cleanup_wrong_owner_never_stops_a_container(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, commands, _ = _cleanup_fixture(monkeypatch)
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="unexpected Docker container"):
        runner["_cleanup_owned_container"]("reconforge-owned-fixture", "b" * 64)
    assert commands == [("docker", "container", "inspect", "--format", "{{.Id}}", "reconforge-owned-fixture")]


@pytest.mark.parametrize("container_id", ["", "a" * 12, "a" * 63 + ";"])
def test_owned_cleanup_requires_full_identity_before_docker(monkeypatch: pytest.MonkeyPatch, container_id: str) -> None:
    runner, commands, _ = _cleanup_fixture(monkeypatch)
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="full Docker container identity"):
        runner["_cleanup_owned_container"]("reconforge-owned-fixture", container_id)
    assert commands == []
