"""Mocked controller lifecycle; never queries or changes host power or runs children."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.test_wave4_posting_pair_verifier import mock_packet

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("stable_power_controller", ROOT / ".github/scripts/benchmark_stable_power_pair.py")
assert SPEC is not None and SPEC.loader is not None
CONTROLLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTROLLER)
GUID = "381b4222-f694-41f0-9685-ff5bb260df2e"


def snapshot() -> dict[str, Any]:
    raw = f"Power Scheme GUID: {GUID} (Balanced)".encode()
    return {"status": "available", "scheme_guid": GUID, "command": ["powercfg", "/getactivescheme"],
            "exit_code": 0, "stdout_base64": base64.b64encode(raw).decode(), "stdout_sha256": hashlib.sha256(raw).hexdigest(),
            "power": {"status": "available", "ac_online": True, "battery_saver_on": False}}


@pytest.mark.parametrize("damage", ["battery", "unknown", "numeric", "saver", "scheme", "missing"])
def test_before_after_environment_fails_closed(damage: str) -> None:
    value = snapshot()
    if damage == "battery":
        value["power"]["ac_online"] = False
    elif damage == "unknown":
        value["power"]["status"] = "unavailable"
    elif damage == "numeric":
        value["power"]["ac_online"] = 1
    elif damage == "saver":
        value["power"]["battery_saver_on"] = True
    elif damage == "scheme":
        value["scheme_guid"] = "0" * 36
    else:
        del value["power"]
    with pytest.raises(ValueError):
        CONTROLLER.verify_environment(value, GUID)


def test_active_scheme_parser_preserves_locale_independent_guid_and_rejects_ambiguity() -> None:
    raw = f"Power Scheme GUID: {GUID.upper()} (Balanced)".encode()
    assert CONTROLLER.scheme_guid(raw) == GUID
    assert CONTROLLER.scheme_guid(f"خطة: {GUID}".encode("utf-16")) == GUID
    with pytest.raises(ValueError):
        CONTROLLER.scheme_guid(raw + raw)


@pytest.mark.parametrize("damage", ["battery", "saver", "unknown", "numeric"])
def test_retained_sample_power_is_independent_of_priming_and_denies_invalid_state(damage: str) -> None:
    packet = mock_packet(1, "baseline", 0)
    assert CONTROLLER.verify_sampled_power(packet)["power_counts"]["battery"] == 0
    value = packet["resource_sampling"]["raw_samples"][0]["host_processor"]["power"]
    value.update({"battery": {"ac_online": False}, "saver": {"battery_saver_on": True},
                  "unknown": {"status": "unavailable"}, "numeric": {"battery_saver_on": 0}}[damage])
    with pytest.raises(ValueError):
        CONTROLLER.verify_sampled_power(packet)


@pytest.mark.parametrize("damage", [None, "child", "after_scheme", "sample", "timeout"])
def test_mocked_children_preserve_raw_state_and_adverse_results_without_acceptance(tmp_path: Path, damage: str | None) -> None:
    roots = {label: (tmp_path / label).resolve() for label in ("baseline", "candidate")}
    calls = []
    observed = 0

    def observe() -> dict[str, Any]:
        nonlocal observed
        observed += 1
        value = snapshot()
        if damage == "after_scheme" and observed == 2:
            value["scheme_guid"] = "11111111-1111-1111-1111-111111111111"
        return value

    def launch(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        position = len(calls)
        calls.append((argv, kwargs))
        repetition, label = CONTROLLER._offline.ORDER[position]
        packet = mock_packet(repetition, label, position)
        packet["runtime_root"] = str(roots[label])
        if damage == "sample":
            packet["resource_sampling"]["raw_samples"][-1]["host_processor"]["power"]["ac_online"] = False
        destination = Path(argv[-1])
        destination.mkdir()
        (destination / "result.json").write_text(json.dumps(packet), encoding="utf-8")
        if damage == "timeout":
            raise subprocess.TimeoutExpired(argv, 2700, output="partial")
        return subprocess.CompletedProcess(argv, 1 if damage == "child" else 0, "original child output", "")

    output = tmp_path / "evidence"
    state = CONTROLLER.run_pair(roots, output, observe=observe, launch=launch,
                                source=lambda path: CONTROLLER._offline.COMMITS[path.name])
    assert state["performance_comparison_accepted"] is False
    assert (output / "1-baseline-power-before.json").is_file()
    assert (output / "1-baseline-power-after.json").is_file()
    assert (output / "1-baseline/result.json").is_file()
    assert json.loads((output / "pair.json").read_bytes())["status"] == state["status"]
    for argv, kwargs in calls:
        assert argv[2:-2] == ["--counts", "100", "1000", "--workers", "4", "--repetitions", "3", "--posting-warmup", "20", "--max-seconds", "1800"]
        assert kwargs["timeout"] == 2700 and kwargs["capture_output"] is True
    if damage is None:
        assert len(calls) == 6 and observed == 12
        assert state["status"] == state["financial_verification"] == state["environment_verification"] == "passed"
        assert state["stable_ac_observed"] is True
        assert json.loads((output / "environment-proof.json").read_bytes())["sidecar_count"] == 12
        assert not (output / "manifest.pending.json").exists()
        assert state["candidate_change_percent"]["client_cpu_seconds"] > 0
        assert state["candidate_change_percent"]["bounded_batch_read_seconds"] > 0
    else:
        assert len(calls) == 1 and state["status"] == "failed"
        assert state["environment_verification"] == "failed"
        assert not (output / "manifest.json").exists()
    with pytest.raises(ValueError, match="Fresh output"):
        CONTROLLER.run_pair(roots, output, observe=observe, launch=launch)


def test_native_windows_power_boundary_abi_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    class NativeCall:
        def __call__(self, pointer: Any) -> int:
            pointer._obj.ACLineStatus = 1
            pointer._obj.SystemStatusFlag = 0
            return 1

    class Kernel:
        GetSystemPowerStatus = NativeCall()

    monkeypatch.setattr(CONTROLLER.sys, "platform", "win32")
    monkeypatch.setattr(CONTROLLER.ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel(), raising=False)
    assert CONTROLLER.ctypes.sizeof(CONTROLLER._PowerStatus) == 12
    value = CONTROLLER.native_power()
    assert value["status"] == "available" and value["ac_online"] is True and value["battery_saver_on"] is False
    assert value["raw"]["ACLineStatus"] == 1 and value["raw"]["SystemStatusFlag"] == 0


def test_environmental_sidecar_byte_substitution_is_refused(tmp_path: Path) -> None:
    rows = []
    for repetition, variant in CONTROLLER._offline.ORDER:
        row = {"repetition": repetition, "variant": variant}
        for phase in ("before", "after"):
            name = f"{repetition}-{variant}-{phase}.json"
            row[f"environment_{phase}"] = {"path": name, "sha256": CONTROLLER.write_json(tmp_path / name, snapshot())}
        rows.append(row)
    assert CONTROLLER.verify_sidecars(tmp_path, rows, GUID)["status"] == "passed"
    first = tmp_path / rows[0]["environment_before"]["path"]
    first.write_bytes(first.read_bytes() + b" ")
    with pytest.raises(ValueError, match="sidecar SHA"):
        CONTROLLER.verify_sidecars(tmp_path, rows, GUID)
