from __future__ import annotations

import copy
import hashlib
import json
import runpy
import subprocess
from contextlib import nullcontext
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
SCHEMA_V2_PATH = ROOT / "docs/schemas/postgres_writeback_recovery_compensation_matrix.v2.schema.json"
WRITEBACK_PATH = ROOT / "reconforge/connectors/writeback.py"
POSTGRES_PATH = ROOT / "reconforge/infrastructure/postgres_writeback.py"
SQLITE_PATH = ROOT / "reconforge/infrastructure/sqlite_writeback.py"
MIGRATION_PATH = ROOT / "alembic/versions/0089_postgres_writeback_proposal_identity.py"
POLICY_PATH = ROOT / "docs/security/supply-chain-policy.retained-8629e9c6.v1.json"


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
        "include docs/schemas/postgres_writeback_recovery_compensation_matrix.v2.schema.json",
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


def _profile_runner() -> tuple[dict[str, Any], dict[str, Any]]:
    runner = runpy.run_path(str(RUNNER_PATH), run_name="test_recovery_runtime_profiles")
    return runner, runner["run_matrix"].__globals__


def _current_report(runner: dict[str, Any]) -> dict[str, Any]:
    report = _report()
    report["schema_version"] = "postgres-writeback-recovery-compensation-matrix-v2"
    report["subject"].update(runtime_profile="current-postgres-wave5-v1", current_postgres_policy_sha256=runner["CURRENT_POLICY_SHA256"])
    for run, profile in zip(report["runs"], runner["CURRENT_PROFILES"], strict=True):
        run["runtime"].update(postgresql=profile["postgresql"], image=profile["image"])
    report["parity"]["postgresql_versions"] = ["16.15", "17.11"]
    return report


def test_current_profiles_bind_approved_policy_and_original_constants_remain_historical() -> None:
    runner, _ = _profile_runner()
    profiles, subject = runner["_runtime_profiles"]("current")
    policy = json.loads((ROOT / "docs/security/postgres-current-images.wave5.v1.json").read_text())
    assert [row["postgresql"] for row in profiles] == ["16.15", "17.11"]
    assert [row["image"] for row in profiles] == [policy["current_images"]["server_boundaries"], policy["current_images"]["native_acceptance"]]
    assert subject == {"runtime_profile": "current-postgres-wave5-v1", "current_postgres_policy_sha256": _source_digest(runner["CURRENT_POLICY_PATH"]),
                       "supply_chain_policy_sha256": _source_digest(runner["SUPPLY_CHAIN_POLICY_PATH"])}
    legacy, legacy_subject = runner["_runtime_profiles"]("legacy")
    assert legacy == runner["PROFILES"] and legacy_subject == {"supply_chain_policy_sha256": _source_digest(runner["SUPPLY_CHAIN_POLICY_PATH"])}
    assert [row["postgresql"] for row in legacy] == ["16.14", "17.10"]
    assert [row["image"] for row in legacy] == [row["runtime"]["image"] for row in _report()["runs"]]


@pytest.mark.parametrize("mode", ["current", "legacy"])
def test_coupled_constants_and_profile_drift_refuses_before_any_sqlite_or_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str,
) -> None:
    runner, namespace = _profile_runner()
    key = "CURRENT_PROFILES" if mode == "current" else "PROFILES"
    profiles = copy.deepcopy(runner[key])
    drift = profiles[0]["image"].split("@sha256:")[0] + "@sha256:" + "0" * 64
    profiles[0]["image"] = drift
    constant = "CURRENT_POSTGRES_16_IMAGE_REFERENCE" if mode == "current" else "POSTGRES_16_IMAGE_REFERENCE"
    monkeypatch.setitem(namespace, key, profiles)
    monkeypatch.setitem(namespace, constant, drift)
    effects = []
    monkeypatch.setitem(namespace, "_sqlite_observation", lambda *args, **kwargs: effects.append("sqlite"))
    monkeypatch.setitem(namespace, "_run_postgres_cell", lambda *args, **kwargs: effects.append("docker"))
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="approved policy values"):
        runner["run_matrix"](tmp_path / "unapproved.json", runtime_profile=mode)
    assert effects == [] and not (tmp_path / "unapproved.json").exists()


def test_policy_hash_and_admitted_values_use_the_same_single_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner, namespace = _profile_runner()
    original = runner["CURRENT_POLICY_PATH"].read_bytes()
    profiles = copy.deepcopy(runner["CURRENT_PROFILES"])
    drift = profiles[0]["image"].split("@sha256:")[0] + "@sha256:" + "0" * 64
    profiles[0]["image"] = drift
    changed = json.loads(original)
    changed["current_images"]["server_boundaries"] = drift

    class ChangingPolicy:
        reads = 0

        def read_bytes(self) -> bytes:
            self.reads += 1
            return original if self.reads == 1 else json.dumps(changed).encode()

        def read_text(self, **kwargs: Any) -> str:
            return self.read_bytes().decode()

    source = ChangingPolicy()
    effects = []
    monkeypatch.setitem(namespace, "CURRENT_POLICY_PATH", source)
    monkeypatch.setitem(namespace, "CURRENT_POSTGRES_16_IMAGE_REFERENCE", drift)
    monkeypatch.setitem(namespace, "CURRENT_PROFILES", profiles)
    monkeypatch.setitem(namespace, "_sqlite_observation", lambda *args: effects.append("sqlite"))
    monkeypatch.setitem(namespace, "_run_postgres_cell", lambda **kwargs: effects.append("docker"))
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="approved policy values"):
        runner["run_matrix"](tmp_path / "not-run.json")
    assert source.reads == 1 and effects == []


@pytest.mark.parametrize("mutation", ["unknown_profile", "mixed_version", "swapped_order", "current_policy", "historical_policy"])
def test_unapproved_profile_or_policy_never_starts_matrix_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str,
) -> None:
    runner, namespace = _profile_runner()
    effects = []
    monkeypatch.setitem(namespace, "_sqlite_observation", lambda *args, **kwargs: effects.append("sqlite"))
    monkeypatch.setitem(namespace, "_run_postgres_cell", lambda *args, **kwargs: effects.append("docker"))
    if mutation == "mixed_version":
        profiles = copy.deepcopy(runner["CURRENT_PROFILES"])
        profiles[0]["postgresql"] = "16.14"
        monkeypatch.setitem(namespace, "CURRENT_PROFILES", profiles)
    elif mutation == "swapped_order":
        monkeypatch.setitem(namespace, "CURRENT_PROFILES", tuple(reversed(runner["CURRENT_PROFILES"])))
    elif mutation.endswith("policy"):
        path = tmp_path / "unapproved-policy.json"
        path.write_text('{}\n')
        monkeypatch.setitem(namespace, "CURRENT_POLICY_PATH" if mutation == "current_policy" else "SUPPLY_CHAIN_POLICY_PATH", path)
    with pytest.raises(runner["RecoveryCompensationMatrixError"]):
        runner["run_matrix"](tmp_path / "not-run.json", runtime_profile="unapproved" if mutation == "unknown_profile" else "current")
    assert effects == [] and not (tmp_path / "not-run.json").exists()


@pytest.mark.parametrize("version,image_key", [("17.10", "CURRENT_POSTGRES_17_IMAGE_REFERENCE"),
    ("16.14", "CURRENT_POSTGRES_16_IMAGE_REFERENCE"), ("18.1", "CURRENT_POSTGRES_17_IMAGE_REFERENCE")])
def test_direct_cell_refuses_mixed_or_unknown_pairs_before_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: str, image_key: str,
) -> None:
    runner, namespace = _profile_runner()
    commands = []
    monkeypatch.setitem(namespace, "_run", lambda *args, **kwargs: commands.append(args))
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="approved exact profile"):
        runner["_run_postgres_cell"](image_reference=runner[image_key], expected_postgresql=version, container_prefix="not-run", temporary=tmp_path)
    assert commands == []


@pytest.mark.parametrize("expected,actual,image_key", [("16.15", "16.14", "CURRENT_POSTGRES_16_IMAGE_REFERENCE"),
    ("17.11", "17.10", "CURRENT_POSTGRES_17_IMAGE_REFERENCE")])
def test_actual_server_version_must_equal_selected_pin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, expected: str, actual: str, image_key: str,
) -> None:
    runner, namespace = _profile_runner()
    connection = SimpleNamespace(execute=lambda *args, **kwargs: SimpleNamespace(fetchone=lambda: (actual,)))
    monkeypatch.setitem(namespace, "connect", lambda *args, **kwargs: nullcontext(connection))
    monkeypatch.setitem(namespace, "_run", lambda command, **kwargs: "127.0.0.1:5432" if command[1] == "port" else "a" * 64)
    for name in ("_wait_for_postgres", "_create_database_and_role", "_upgrade", "_grant_application_boundary"):
        monkeypatch.setitem(namespace, name, lambda *args, **kwargs: None)
    monkeypatch.setitem(namespace, "_run_lifecycle", lambda *args, **kwargs: copy.deepcopy(_report()["runs"][0]))
    monkeypatch.setitem(namespace, "PostgresWritebackIntentRepository", lambda *args: SimpleNamespace(get=lambda **kwargs: None))
    monkeypatch.setitem(namespace, "_role_flags", lambda *args: dict.fromkeys(_report()["runs"][0]["role_flags"], False))
    monkeypatch.setitem(namespace, "_mutation_checks", lambda *args: {"direct_update_refused": True, "direct_delete_refused": True})
    cleanup = []
    monkeypatch.setitem(namespace, "_cleanup_owned_container", lambda *args: cleanup.append(args))
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="version does not match declared profile"):
        runner["_run_postgres_cell"](image_reference=runner[image_key], expected_postgresql=expected, container_prefix="synthetic", temporary=tmp_path)
    assert len(cleanup) == 1 and cleanup[0][1] == "a" * 64


@pytest.mark.parametrize("mode", ["current", "legacy"])
def test_matrix_emits_versioned_contract_with_current_default_and_explicit_legacy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str,
) -> None:
    runner, namespace = _profile_runner()
    calls = []
    monkeypatch.setitem(namespace, "_sqlite_observation", lambda *args: copy.deepcopy(_report()["sqlite_reference"]))

    def cell(**kwargs: Any) -> dict[str, Any]:
        calls.append((kwargs["expected_postgresql"], kwargs["image_reference"]))
        original = copy.deepcopy(_report()["runs"][0])
        original["runtime"].update(postgresql=kwargs["expected_postgresql"], image=kwargs["image_reference"])
        return original

    monkeypatch.setitem(namespace, "_run_postgres_cell", cell)
    monkeypatch.setitem(namespace, "_base_commit", lambda: "a" * 40)
    report = runner["run_matrix"](tmp_path / "report.json", **({"runtime_profile": "legacy"} if mode == "legacy" else {}))
    assert report["schema_version"] == "postgres-writeback-recovery-compensation-matrix-" + ("v2" if mode == "current" else "v1")
    assert report["parity"]["postgresql_versions"] == (["16.15", "17.11"] if mode == "current" else ["16.14", "17.10"])
    assert len(calls) == 2
    if mode == "legacy":
        assert set(report["subject"]) == set(_report()["subject"])
    else:
        assert report["subject"]["runtime_profile"] == "current-postgres-wave5-v1"
        assert report["subject"]["current_postgres_policy_sha256"] == _source_digest(runner["CURRENT_POLICY_PATH"])
    payload = dict(report)
    supplied = payload.pop("report_digest")
    assert supplied == runner["_canonical_digest"](payload)
    assert json.loads((tmp_path / "report.json").read_text()) == report


@pytest.mark.parametrize("mode", [None, "current", "legacy"])
def test_cli_selects_only_explicit_versioned_modes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str | None) -> None:
    runner, namespace = _profile_runner()
    called = []

    def matrix(path: Path, *, runtime_profile: str) -> dict[str, Any]:
        called.append(runtime_profile)
        return {"parity": {"postgresql_versions": ["16.14", "17.10"]}, "report_digest": "a" * 64}

    monkeypatch.setitem(namespace, "run_matrix", matrix)
    assert runner["main"](["--output", str(tmp_path / "report.json"), *(["--runtime-profile", mode] if mode else [])]) == 0
    assert called == [mode or "current"]


def test_cli_unknown_mode_has_no_runtime_effect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runner, namespace = _profile_runner()
    called = []
    monkeypatch.setitem(namespace, "run_matrix", lambda *args, **kwargs: called.append(args))
    with pytest.raises(SystemExit) as error:
        runner["main"](["--output", str(tmp_path / "report.json"), "--runtime-profile", "latest"])
    assert error.value.code == 2 and called == []


@pytest.mark.parametrize("mutation", ["legacy_version", "legacy_image", "swapped_runs", "profile", "policy", "cleanup", "role", "history", "unknown_field"])
def test_v2_schema_rejects_mixed_pins_or_weakened_original_controls(mutation: str) -> None:
    runner, _ = _profile_runner()
    report = _current_report(runner)
    validator = runner["_report_validator"](report["schema_version"])
    validator.validate(report)
    if mutation == "legacy_version":
        report["runs"][0]["runtime"]["postgresql"] = "16.14"
    elif mutation == "legacy_image":
        report["runs"][1]["runtime"]["image"] = runner["POSTGRES_17_IMAGE_REFERENCE"]
    elif mutation == "swapped_runs":
        report["runs"].reverse()
    elif mutation == "profile":
        report["subject"]["runtime_profile"] = "legacy"
    elif mutation == "policy":
        report["subject"]["current_postgres_policy_sha256"] = "0" * 64
    elif mutation == "cleanup":
        report["runs"][0]["checks"]["cleanup_complete"] = False
    elif mutation == "role":
        report["runs"][0]["role_flags"]["superuser"] = True
    elif mutation == "history":
        report["runs"][0]["history"].pop()
    else:
        report["subject"]["undeclared"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(report)


def test_v1_v2_schema_contracts_refuse_cross_relabeling() -> None:
    runner, _ = _profile_runner()
    relabeled_current = _current_report(runner)
    relabeled_current["schema_version"] = "postgres-writeback-recovery-compensation-matrix-v1"
    for key in ("runtime_profile", "current_postgres_policy_sha256"):
        relabeled_current["subject"].pop(key)
    with pytest.raises(jsonschema.ValidationError) as current_error:
        runner["_report_validator"]("postgres-writeback-recovery-compensation-matrix-v1").validate(relabeled_current)
    assert current_error.value.absolute_path[0] in {"runs", "parity"}
    relabeled_legacy = _report()
    relabeled_legacy["schema_version"] = "postgres-writeback-recovery-compensation-matrix-v2"
    relabeled_legacy["subject"].update(runtime_profile="current-postgres-wave5-v1", current_postgres_policy_sha256=runner["CURRENT_POLICY_SHA256"])
    with pytest.raises(jsonschema.ValidationError) as legacy_error:
        runner["_report_validator"]("postgres-writeback-recovery-compensation-matrix-v2").validate(relabeled_legacy)
    assert legacy_error.value.absolute_path[0] in {"runs", "parity"}
    with pytest.raises(runner["RecoveryCompensationMatrixError"], match="unknown recovery report schema"):
        runner["_report_validator"]("postgres-writeback-recovery-compensation-matrix-v3")


@pytest.mark.parametrize("uri", ["https://unapproved.example/financial-schema", "file:///unapproved/financial-schema.json"])
def test_explicit_schema_registry_refuses_unknown_network_or_file_retrieval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, uri: str) -> None:
    from referencing.exceptions import Unresolvable

    runner, namespace = _profile_runner()
    schema = json.loads(SCHEMA_V2_PATH.read_text())
    schema["properties"]["subject"] = {"$ref": uri}
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema))
    monkeypatch.setitem(namespace, "SCHEMA_V2_PATH", path)
    validator = runner["_report_validator"]("postgres-writeback-recovery-compensation-matrix-v2")
    with pytest.raises(Unresolvable):
        validator.validate(_current_report(runner))


def test_v2_schema_and_transitive_policy_reference_are_in_source_manifest() -> None:
    manifest = set((ROOT / "MANIFEST.in").read_text().splitlines())
    assert "include docs/schemas/postgres_writeback_recovery_compensation_matrix.v2.schema.json" in manifest
    assert "include docs/schemas/postgres_writeback_recovery_compensation_matrix.schema.json" in manifest
    assert "include docs/security/postgres-current-images.wave5.v1.json" in manifest
    jsonschema.Draft202012Validator.check_schema(json.loads(SCHEMA_V2_PATH.read_text()))
