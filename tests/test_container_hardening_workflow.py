from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HARDENING_FLAGS = [
    "--network=none",
    "--read-only",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
]


def _workflow(path: str) -> dict[str, object]:
    payload = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _run_text(workflow: dict[str, object], job_name: str) -> str:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs[job_name]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    runs = [step["run"] for step in steps if isinstance(step, dict) and "run" in step]
    return "\n".join(run for run in runs if isinstance(run, str))


def _assert_hardened_doctor(run_text: str, image: str) -> None:
    assert all(flag in run_text for flag in HARDENING_FLAGS)
    assert f"{image} reconforge doctor" in run_text


def test_required_ci_docker_parity_keeps_hardened_runtime_smoke() -> None:
    workflow = _workflow(".github/workflows/ci.yml")
    _assert_hardened_doctor(_run_text(workflow, "docker-parity"), "reconforge:ci-baseline")


def test_release_candidate_hardening_precedes_registry_login_and_push() -> None:
    path = ROOT / ".github/workflows/release.yml"
    text = path.read_text(encoding="utf-8")
    workflow = _workflow(".github/workflows/release.yml")
    _assert_hardened_doctor(_run_text(workflow, "build-attest-verify"), '"$LOCAL_IMAGE"')

    smoke = text.index("- name: Run hardened candidate image smoke")
    login = text.index("- name: Log in to the candidate image registry")
    push = text.index("- name: Push and verify the scanned image subject")
    assert smoke < login < push


def test_python_test_matrix_fetches_history_for_retained_evidence() -> None:
    workflow = _workflow(".github/workflows/ci.yml")
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["test"]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    checkout = next(
        step for step in steps if isinstance(step, dict) and step.get("name") == "Check out repository"
    )
    with_values = checkout["with"]
    assert isinstance(with_values, dict)
    assert with_values["fetch-depth"] == 0


def test_long_running_ci_jobs_have_finite_timeouts() -> None:
    workflow = _workflow(".github/workflows/ci.yml")
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert jobs["test"]["timeout-minutes"] == 45
    assert jobs["postgres-ha-dr"]["timeout-minutes"] == 30


def test_codeql_analysis_has_a_finite_timeout() -> None:
    workflow = _workflow(".github/workflows/codeql.yml")
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert jobs["analyze"]["timeout-minutes"] == 30


def test_quality_workflows_cancel_stale_same_ref_runs() -> None:
    for path in ("ci.yml", "codeql.yml", "security.yml", "docker.yml"):
        workflow = _workflow(f".github/workflows/{path}")
        concurrency = workflow["concurrency"]
        assert isinstance(concurrency, dict)
        assert concurrency["cancel-in-progress"] is True
        assert "github.ref" in concurrency["group"]
