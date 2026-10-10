"""External stable-AC controller; frozen child code and power settings are unchanged.

python benchmark_stable_power_pair.py --baseline BASE --candidate CAND --output FRESH

Runs exactly BC,CB,BC, each fresh 1000-cycle child with 20 warmups, four workers,
three read repetitions and the original 1800+900 second budget. Keep the sibling
offline/global/native verifier scripts alongside this stdlib-only controller.
Powercfg reports the active scheme GUID, not Windows power-mode overlay or thermal
state. Sparse AC/saver samples and before/after scheme readings are observations,
not continuous proof. Execution/environment success never grants performance acceptance.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import importlib.util
import json
import re
import subprocess  # nosec B404
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_spec = importlib.util.spec_from_file_location("stable_pair_offline", Path(__file__).with_name("verify_wave4_posting_pair.py"))
if _spec is None or _spec.loader is None:
    raise RuntimeError("Sibling offline verifier is absent")
_offline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_offline)
_pair = _offline._pair
require = _offline.require


class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_uint32), ("BatteryFullLifeTime", ctypes.c_uint32)]


def native_power() -> dict[str, Any]:
    missing = {"status": "unavailable", "raw": None, "ac_online": None, "battery_saver_on": None}
    if sys.platform != "win32":
        return {**missing, "reason": "unsupported_platform"}
    try:
        loader = getattr(ctypes, "WinDLL", None)
        require(callable(loader), "Windows native loader unavailable")
        kernel = loader("kernel32", use_last_error=True)
        kernel.GetSystemPowerStatus.argtypes = [ctypes.POINTER(_PowerStatus)]
        kernel.GetSystemPowerStatus.restype = ctypes.c_int32
        value = _PowerStatus()
        if not kernel.GetSystemPowerStatus(ctypes.byref(value)):
            error = getattr(ctypes, "get_last_error", None)
            return {**missing, "win32_error": int(error()) if callable(error) else None}
        raw = {name: int(getattr(value, name)) for name, _ in _PowerStatus._fields_}
        return {"status": "available", "raw": raw,
                "ac_online": bool(raw["ACLineStatus"]) if raw["ACLineStatus"] in (0, 1) else None,
                "battery_saver_on": bool(raw["SystemStatusFlag"]) if raw["SystemStatusFlag"] in (0, 1) else None}
    except Exception as exc:
        return {**missing, "failure_type": type(exc).__name__}


def scheme_guid(raw: bytes) -> str:
    require(len(raw) <= 65536, "Powercfg output exceeds bound")
    text = raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8", errors="replace")
    matches = re.findall(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", text)
    require(len(matches) == 1, "Powercfg must report exactly one active scheme GUID")
    return matches[0].lower()


def observe_environment() -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    begin = time.monotonic()
    command = ["powercfg", "/getactivescheme"]
    result: dict[str, Any] = {"status": "unavailable", "started_at": started, "command": command}
    try:
        child = subprocess.run(command, capture_output=True, timeout=10, check=False)  # nosec B603
        result.update(exit_code=child.returncode, stdout_base64=base64.b64encode(child.stdout).decode("ascii"),
                      stderr_base64=base64.b64encode(child.stderr).decode("ascii"),
                      stdout_sha256=hashlib.sha256(child.stdout).hexdigest(), stderr_sha256=hashlib.sha256(child.stderr).hexdigest())
        require(child.returncode == 0, "Read-only active scheme query failed")
        result.update(status="available", scheme_guid=scheme_guid(child.stdout))
    except Exception as exc:
        result["failure_type"] = type(exc).__name__
    result.update(power=native_power(), finished_at=datetime.now(UTC).isoformat(), seconds=time.monotonic() - begin)
    return result


def verify_environment(snapshot: dict[str, Any], expected_guid: str | None) -> str:
    require(snapshot.get("status") == "available", "Active scheme observation unavailable")
    guid = snapshot.get("scheme_guid")
    require(isinstance(guid, str) and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", guid) is not None,
            "Invalid active scheme GUID")
    require(expected_guid is None or guid == expected_guid, "Active scheme changed")
    power = snapshot.get("power")
    require(isinstance(power, dict) and power.get("status") == "available"
            and power.get("ac_online") is True and power.get("battery_saver_on") is False,
            "Stable AC with battery saver off is required")
    return guid


def verify_sampled_power(packet: dict[str, Any]) -> dict[str, Any]:
    summary = _offline._host_observations(packet)
    size = summary["sample_count"]
    require(size > 0 and summary["power_counts"] == {"ac": size, "battery": 0, "unavailable": 0}
            and summary["battery_saver_counts"] == {"on": 0, "off": size, "unavailable": 0},
            "Retained samples do not prove observed stable AC/saver-off")
    return summary


def write_json(path: Path, value: dict[str, Any]) -> str:
    raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def verify_sidecars(output: Path, rows: list[dict[str, Any]], expected_guid: str) -> dict[str, Any]:
    require(len(rows) == 6, "Incomplete environmental population")
    bindings = []
    for row in rows:
        for phase in ("before", "after"):
            record = row[f"environment_{phase}"]
            path = _offline._report_path(output.resolve(), record["path"])
            raw = path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == record["sha256"], "Environmental sidecar SHA differs")
            snapshot = _offline._json(raw)
            verify_environment(snapshot, expected_guid)
            require(snapshot["command"] == ["powercfg", "/getactivescheme"] and snapshot["exit_code"] == 0,
                    "Unexpected environmental command or failure")
            stdout = base64.b64decode(snapshot["stdout_base64"], validate=True)
            require(hashlib.sha256(stdout).hexdigest() == snapshot["stdout_sha256"]
                    and scheme_guid(stdout) == expected_guid, "Raw scheme evidence differs")
            bindings.append({"repetition": row["repetition"], "variant": row["variant"], "phase": phase, **record})
    return {"schema_version": "stable-power-environment-proof-v1", "status": "passed",
            "expected_scheme_guid": expected_guid, "sidecar_count": 12, "sidecars": bindings,
            "raw_reports": [{"repetition": row["repetition"], "variant": row["variant"],
                             "report_sha256": row.get("report_sha256")} for row in rows],
            "sampled_ac_and_saver_off_verified": True,
            "scope": "scheme GUID before/after each child and available exact-boolean AC/saver retained samples; no power-mode overlay or continuous measurement"}


def source_state(root: Path) -> str:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=30).strip()  # nosec B603 B607
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, timeout=30)  # nosec B603 B607
    require(not dirty, "Frozen source has tracked modifications")
    return head


def run_pair(roots: dict[str, Path], output: Path, *, expected_guid: str | None = None,
             observe: Any = observe_environment, launch: Any = subprocess.run, source: Any = source_state) -> dict[str, Any]:
    require(not output.exists(), "Fresh output directory required; prior evidence must be preserved")
    output.mkdir(parents=True)
    state: dict[str, Any] = {"schema_version": "stable-power-pair-controller-v1", "status": "running",
        "pairs": 3, "count": 1000, "commits": dict(_offline.COMMITS), "runs": [],
        "order": "BC,CB,BC", "performance_comparison_accepted": False,
        "environment_verification": "pending", "financial_verification": "pending",
        "scheme_reference_origin": "explicit expected GUID" if expected_guid else "first before-child observation",
        "limits": ["Active scheme GUID does not identify Windows power-mode overlay or every power parameter.",
                   "Before/after readings and sparse samples do not prove continuous scheme/power stability.",
                   "Financial/environment verification does not certify resource improvement or vendor superiority."]}
    reference = None
    records = []
    try:
        for label, root in roots.items():
            require(source(root) == _offline.COMMITS[label], "Frozen source commit differs")
        for repetition, label in _offline.ORDER:
            root = roots[label]
            destination = output / f"{repetition}-{label}"
            argv = [sys.executable, str(root / ".github/scripts/benchmark_enterprise_finance.py"), "--counts", "100", "1000",
                    "--workers", "4", "--repetitions", "3", "--posting-warmup", "20", "--max-seconds", "1800", "--output", str(destination)]
            row: dict[str, Any] = {"repetition": repetition, "variant": label, "command": argv,
                                   "report": str(destination / "result.json"), "child_exit_code": None}
            state["runs"].append(row)
            before = observe()
            sidecar = output / f"{repetition}-{label}-power-before.json"
            row["environment_before"] = {"path": sidecar.name, "sha256": write_json(sidecar, before)}
            expected_guid = verify_environment(before, expected_guid)
            state["expected_scheme_guid"] = expected_guid
            write_json(output / "pair.json", state)
            try:
                completed = launch(argv, cwd=root, capture_output=True, text=True, timeout=2700)
                row["child_exit_code"] = completed.returncode
                (output / f"{repetition}-{label}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
            except Exception as exc:
                row["child_failure_type"] = type(exc).__name__
                if isinstance(exc, subprocess.TimeoutExpired):
                    partial = [(value.decode(errors="replace") if isinstance(value, bytes) else value or "")
                               for value in (exc.stdout, exc.stderr)]
                    (output / f"{repetition}-{label}.log").write_text("".join(partial), encoding="utf-8")
            finally:
                after = observe()
                sidecar = output / f"{repetition}-{label}-power-after.json"
                row["environment_after"] = {"path": sidecar.name, "sha256": write_json(sidecar, after)}
            report = destination / "result.json"
            require(report.is_file(), "Child produced no evidence; cleanup is unverified")
            raw = report.read_bytes()
            row["report_sha256"] = hashlib.sha256(raw).hexdigest()
            require(row["child_exit_code"] == 0, "Child workload failed; raw evidence retained")
            packet = _offline._json(raw)
            _offline._current_run_contract(packet)
            row["verified"] = _pair.verify(packet, root, _offline.COMMITS[label], 1000)
            row["financial_verification"] = "passed"
            require(source(root) == _offline.COMMITS[label], "Frozen source changed after child")
            config = {field: packet[field] for field in _pair.CONFIG}
            if reference is None:
                reference = config
            require(config == reference, "Matched CONFIG differs")
            verify_environment(after, expected_guid)
            row["host_observations"] = verify_sampled_power(packet)
            row["environment_verification"] = "passed"
            records.append({"repetition": repetition, "variant": label,
                            "report": f"{repetition}-{label}/result.json", "report_sha256": row["report_sha256"], "child_exit_code": 0})
            write_json(output / "pair.json", state)
            print(json.dumps({"repetition": repetition, "variant": label, "financial_verification": "passed",
                              "environment_verification": "passed", "posting_seconds": row["verified"]["posting_seconds"]}), flush=True)
        manifest = {"schema_version": "wave4-native-posting-pair-manifest-v1", "status": "passed", "pairs": 3,
                    "count": 1000, "commits": dict(_offline.COMMITS), "runs": records}
        pending_manifest = output / "manifest.pending.json"
        digest = write_json(pending_manifest, manifest)
        independent = _offline.verify_manifest(pending_manifest, digest)
        environment_proof = verify_sidecars(output, state["runs"], expected_guid)
        environment_sha = write_json(output / "environment-proof.json", environment_proof)
        pending_manifest.rename(output / "manifest.json")
        proof_sha = write_json(output / "offline-proof.json", independent)
        state.update(status="passed", financial_verification="passed", environment_verification="passed",
                     stable_ac_observed=True, same_active_scheme_before_after=True, matched_configuration=reference,
                     manifest_sha256=digest, offline_proof_sha256=proof_sha, environment_proof_sha256=environment_sha,
                     medians=independent["medians"], candidate_change_percent=independent["candidate_change_percent"],
                     manifest_trust="new controller-generated digest must be retained in a separately trusted channel; no external attestation")
    except Exception as exc:
        state.update(status="failed", failure_type=type(exc).__name__, failure=str(exc),
                     environment_verification="failed", stable_ac_observed=False)
    finally:
        write_json(output / "pair.json", state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-scheme-guid")
    args = parser.parse_args()
    result = run_pair({"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()},
                      args.output.resolve(), expected_guid=args.expected_scheme_guid)
    print(json.dumps({"status": result["status"], "output": str(args.output), "performance_comparison_accepted": False}), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
