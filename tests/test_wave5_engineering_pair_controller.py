"""Benchmark acceptance must reject observed confounding and retain failures."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.test_stable_power_pair_controller import snapshot
from tests.test_wave4_posting_pair_verifier import VERIFIER, mock_packet

COMMITS, ORDER = VERIFIER.COMMITS, VERIFIER.ORDER

SPEC = importlib.util.spec_from_file_location("wave5_controller", Path(__file__).parents[1] / ".github/scripts/benchmark_wave5_engineering_pair.py")
assert SPEC is not None and SPEC.loader is not None
CONTROLLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLLER)


@pytest.mark.parametrize("damage", [None, "power_parameters", "battery", "financial", "child", "timeout"])
def test_fresh_populations_and_power_gates_retain_adverse_raw_evidence(tmp_path: Path, damage: str | None) -> None:
    roots = {label: (tmp_path / label).resolve() for label in COMMITS}
    launches: list[str] = []
    observations = 0

    def observe() -> dict[str, Any]:
        nonlocal observations
        observations += 1
        value = snapshot()
        value["active_parameters"] = {"stdout_sha256": "a" * 64}
        if observations == 2 and damage == "power_parameters":
            value["active_parameters"]["stdout_sha256"] = "b" * 64
        if observations == 2 and damage == "battery":
            value["power"]["ac_online"] = False
        return value

    def launch(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        repetition, label = ORDER[len(launches)]
        packet = mock_packet(repetition, label, len(launches))
        packet["runtime_root"] = str(roots[label])
        packet["image"] = argv[-3]
        packet["harness_sha256"] = packet["harness_sha256_after"] = "c" * 64
        if damage == "financial":
            packet["posting"]["expected"]["debit_minor"] = "1"
        destination = Path(argv[-1])
        destination.mkdir()
        (destination / "result.json").write_text(json.dumps(packet), encoding="utf-8")
        launches.append(label)
        assert kwargs["timeout"] == 2700
        assert argv[2:-6] == ["--counts", "100", "1000", "--workers", "4", "--repetitions", "3",
                              "--posting-warmup", "20", "--max-seconds", "1800"]
        assert argv[-6:-4] == ["--runtime-root", str(roots[label])]
        if damage == "timeout":
            raise subprocess.TimeoutExpired(argv, 2700, output="retained partial stdout")
        return subprocess.CompletedProcess(argv, int(damage == "child"), "original stdout", "original stderr")

    output = tmp_path / "evidence"
    result = CONTROLLER.run_pair(roots, output, count=1000, max_seconds=1800,
                                launch=launch, environment=observe, source=lambda path: COMMITS[path.name])
    assert result["performance_comparison_accepted"] is False
    assert (output / "1-baseline/result.json").is_file()
    assert (output / "1-baseline-power-after.json").is_file()
    assert json.loads((output / "pair.json").read_bytes())["status"] == result["status"]
    if damage is None:
        assert launches == [label for _, label in ORDER]
        assert observations == 12
        assert result["status"] == result["environment_verification"] == result["financial_verification"] == "passed"
        assert result["raw_median_change_percent"]["client_cpu_seconds"] > 0
    else:
        assert result["status"] == "failed" and len(launches) == 1
    with pytest.raises(ValueError, match="Preserve previous"):
        CONTROLLER.run_pair(roots, output, count=1000, max_seconds=1800)
