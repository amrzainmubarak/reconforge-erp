"""Synthetic offline binding regressions; no native power calls or child benchmark."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.test_stable_power_pair_controller import GUID, snapshot
from tests.test_wave4_posting_pair_verifier import mock_packet, write_json

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("stable_environment_offline", ROOT / ".github/scripts/verify_stable_power_environment.py")
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
CONTROLLER = VERIFIER._controller


def fixture(directory: Path) -> tuple[str, str]:
    rows = []
    manifest: dict[str, Any] = {"schema_version": "wave4-native-posting-pair-manifest-v1", "status": "passed",
        "pairs": 3, "count": 1000, "commits": dict(CONTROLLER._offline.COMMITS), "runs": []}
    for position, (repetition, variant) in enumerate(CONTROLLER._offline.ORDER):
        relative = f"{repetition}-{variant}/result.json"
        digest = write_json(directory / relative, mock_packet(repetition, variant, position))
        row: dict[str, Any] = {"repetition": repetition, "variant": variant, "child_exit_code": 0,
                               "report": str((directory / relative).resolve()), "report_sha256": digest}
        for phase in ("before", "after"):
            name = f"{repetition}-{variant}-power-{phase}.json"
            row[f"environment_{phase}"] = {"path": name, "sha256": write_json(directory / name, snapshot())}
        rows.append(row)
        manifest["runs"].append({"repetition": repetition, "variant": variant, "child_exit_code": 0,
                                "report": relative, "report_sha256": digest})
    manifest_sha = write_json(directory / "manifest.json", manifest)
    proof_sha = write_json(directory / "environment-proof.json", CONTROLLER.verify_sidecars(directory, rows, GUID))
    original_rows = copy.deepcopy(rows)
    for row in original_rows:
        row["report"] = f"C:/original-host/frozen-output/{row['repetition']}-{row['variant']}/result.json"
    state = {"schema_version": "stable-power-pair-controller-v1", "status": "passed",
             "pairs": 3, "count": 1000, "order": "BC,CB,BC",
             "financial_verification": "passed", "environment_verification": "passed", "performance_comparison_accepted": False,
             "commits": dict(CONTROLLER._offline.COMMITS), "expected_scheme_guid": GUID,
             "manifest_sha256": manifest_sha, "environment_proof_sha256": proof_sha, "runs": original_rows}
    return write_json(directory / "pair.json", state), manifest_sha


def test_portable_environment_reproduces_six_reports_twelve_sidecars_without_power_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = tmp_path / "original"
    pair_sha, manifest_sha = fixture(packet)
    copied = tmp_path / "outside-checkout"
    shutil.copytree(packet, copied)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Offline verification must never sample power or start a subprocess")

    monkeypatch.setattr(CONTROLLER, "observe_environment", forbidden)
    monkeypatch.setattr(CONTROLLER, "native_power", forbidden)
    monkeypatch.setattr(CONTROLLER.subprocess, "run", forbidden)
    result = VERIFIER.verify_packet(copied, pair_sha, manifest_sha, GUID)
    assert result["status"] == result["financial_verification"] == result["environment_verification"] == "passed"
    assert result["performance_comparison_accepted"] is False
    assert result["environment"]["sidecar_count"] == 12
    assert len(result["environment"]["raw_reports"]) == 6
    assert result["environment"]["sampled_ac_and_saver_off_verified"] is True
    assert result["financial"]["independent_oracle_minor"] == {"100": "46669102", "1000": "493671004"}


@pytest.mark.parametrize("damage", ["pair_bytes", "pair_pin", "manifest_pin", "sidecar_bytes", "proof_bytes",
                                   "original_root", "running", "performance_claim", "null_report_sha", "workload"])
def test_portable_trust_membership_and_original_proof_fail_closed(tmp_path: Path, damage: str) -> None:
    pair_sha, manifest_sha = fixture(tmp_path)
    state = json.loads((tmp_path / "pair.json").read_bytes())
    if damage == "pair_bytes":
        target = tmp_path / "pair.json"
        target.write_bytes(target.read_bytes() + b" ")
    elif damage == "pair_pin":
        pair_sha = "0" * 64
    elif damage == "manifest_pin":
        manifest_sha = "0" * 64
    elif damage in ("sidecar_bytes", "proof_bytes"):
        target = tmp_path / (state["runs"][0]["environment_before"]["path"] if damage == "sidecar_bytes" else "environment-proof.json")
        target.write_bytes(target.read_bytes() + b" ")
    else:
        if damage == "original_root":
            state["runs"][2]["report"] = "D:/unrelated-host/2-candidate/result.json"
        elif damage == "running":
            state["status"] = "running"
        elif damage == "performance_claim":
            state["performance_comparison_accepted"] = True
        elif damage == "workload":
            state["count"] = 100
        else:
            state["runs"][0]["report_sha256"] = None
        pair_sha = write_json(tmp_path / "pair.json", state)
    with pytest.raises(ValueError):
        VERIFIER.verify_packet(tmp_path, pair_sha, manifest_sha, GUID)


def test_rehashed_battery_report_remains_financially_valid_but_environment_refuses(tmp_path: Path) -> None:
    _, _ = fixture(tmp_path)
    state = json.loads((tmp_path / "pair.json").read_bytes())
    manifest = json.loads((tmp_path / "manifest.json").read_bytes())
    path = tmp_path / manifest["runs"][0]["report"]
    raw = json.loads(path.read_bytes())
    raw["resource_sampling"]["raw_samples"][-1]["host_processor"]["power"]["ac_online"] = False
    sha = write_json(path, raw)
    manifest["runs"][0]["report_sha256"] = sha
    state["runs"][0]["report_sha256"] = sha
    manifest_sha = write_json(tmp_path / "manifest.json", manifest)
    state["manifest_sha256"] = manifest_sha
    pair_sha = write_json(tmp_path / "pair.json", state)
    assert CONTROLLER._offline.verify_manifest(tmp_path / "manifest.json", manifest_sha)["financial_verification"] == "passed"
    with pytest.raises(ValueError, match="stable AC/saver-off"):
        VERIFIER.verify_packet(tmp_path, pair_sha, manifest_sha, GUID)


@pytest.mark.parametrize("optimized", [False, True])
def test_extracted_cli_isolated_normal_and_optimized_use_only_original_bytes(tmp_path: Path, optimized: bool) -> None:
    packet = tmp_path / "packet"
    pair_sha, manifest_sha = fixture(packet)
    tools = tmp_path / "extracted-tools"
    tools.mkdir()
    for name in ("verify_stable_power_environment.py", "benchmark_stable_power_pair.py", "verify_wave4_posting_pair.py",
                 "benchmark_global_engineering_pair.py", "verify_native_posting_pair.py"):
        shutil.copyfile(ROOT / ".github/scripts" / name, tools / name)
    report = tmp_path / "fresh-proof.json"
    argv = [sys.executable, "-I", *(["-O"] if optimized else []), str(tools / "verify_stable_power_environment.py"),
            "--packet", str(packet), "--pair-sha256", pair_sha, "--manifest-sha256", manifest_sha,
            "--expected-scheme-guid", GUID, "--report", str(report)]
    completed = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=20, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    proof = json.loads(report.read_bytes())
    assert proof["status"] == "passed" and proof["performance_comparison_accepted"] is False
    repeated = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=20, check=False)
    assert repeated.returncode != 0
