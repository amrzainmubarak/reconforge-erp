"""Fresh alternating native financial populations with independent evidence and power gates.

Reuse the accepted benchmark and independent integer/resource verifier. This
controller grants execution acceptance only: performance/resource tradeoffs must
still be assessed from all three runs. It never changes host power settings.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import statistics
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any


def sibling(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Required independent benchmark verifier is absent")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pair = sibling("benchmark_global_engineering_pair")
power = sibling("benchmark_stable_power_pair")
require = pair.require


def observe() -> dict[str, Any]:
    """Retain full active scheme parameters as well as exact native AC/saver flags."""
    result = power.observe_environment()
    command = ["powercfg", "/query", "SCHEME_CURRENT"]
    child = subprocess.run(command, capture_output=True, timeout=15, check=False)  # nosec B603
    result["active_parameters"] = {
        "command": command, "exit_code": child.returncode,
        "stdout_base64": base64.b64encode(child.stdout).decode("ascii"),
        "stderr_base64": base64.b64encode(child.stderr).decode("ascii"),
        "stdout_sha256": hashlib.sha256(child.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(child.stderr).hexdigest(),
    }
    require(child.returncode == 0, "Read-only active power parameter query failed")
    return result


def run_pair(roots: dict[str, Path], output: Path, *, count: int, max_seconds: int,
             postgres_image: str = "postgres:17.11-alpine@sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3",
             launch: Any = subprocess.run, environment: Any = observe,
             source: Any = power.source_state) -> dict[str, Any]:
    require(not output.exists(), "Preserve previous evidence; use a fresh output directory")
    output.mkdir(parents=True)
    commits = {label: source(root) for label, root in roots.items()}
    state: dict[str, Any] = {
        "schema_version": "wave5-native-engineering-pair-v1", "status": "running",
        "commits": commits, "count": count, "pairs": 3, "runs": [], "order": "BC,CB,BC",
        "performance_comparison_accepted": False, "cost_per_success_currency": None,
        "limits": [
            "Single entity USD native repositories, three humans; not HTTP or mixed ERP latency.",
            "AC/saver and frequency are sampled; thermal state and power-mode overlay remain unmeasured.",
            "Execution success does not prove CPU, memory, latency or throughput improvement.",
            "No monetary infrastructure cost model or comparable competitor measurement is supplied.",
        ],
    }
    expected_scheme = None
    parameters_sha = None
    matched_configuration = None
    try:
        for repetition in range(1, 4):
            labels = ("baseline", "candidate") if repetition % 2 else ("candidate", "baseline")
            for label in labels:
                root = roots[label]
                require(source(root) == commits[label], "Frozen source changed before workload")
                destination = output / f"{repetition}-{label}"
                command = [sys.executable, str(Path(__file__).with_name("benchmark_enterprise_finance.py")),
                           "--counts", "100", str(count), "--workers", "4", "--repetitions", "3",
                           "--posting-warmup", "20", "--max-seconds", str(max_seconds),
                           "--runtime-root", str(root), "--postgres-image", postgres_image, "--output", str(destination)]
                row: dict[str, Any] = {"repetition": repetition, "variant": label, "command": command,
                                       "report": str(destination / "result.json"), "child_exit_code": None}
                state["runs"].append(row)
                before = environment()
                expected_scheme = power.verify_environment(before, expected_scheme)
                current_parameters = before["active_parameters"]["stdout_sha256"]
                parameters_sha = parameters_sha or current_parameters
                require(current_parameters == parameters_sha, "Active power parameters changed")
                before_path = output / f"{repetition}-{label}-power-before.json"
                row["environment_before"] = {"path": before_path.name, "sha256": power.write_json(before_path, before)}
                power.write_json(output / "pair.json", state)
                try:
                    completed = launch(command, cwd=root, capture_output=True, text=True, timeout=max_seconds + 900)
                    row["child_exit_code"] = completed.returncode
                    (output / f"{repetition}-{label}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
                except subprocess.TimeoutExpired as exc:
                    row["child_failure_type"] = type(exc).__name__
                    partial = [(part.decode(errors="replace") if isinstance(part, bytes) else part or "")
                               for part in (exc.stdout, exc.stderr)]
                    (output / f"{repetition}-{label}.log").write_text("".join(partial), encoding="utf-8")
                finally:
                    after = environment()
                    after_path = output / f"{repetition}-{label}-power-after.json"
                    row["environment_after"] = {"path": after_path.name, "sha256": power.write_json(after_path, after)}
                raw = (destination / "result.json").read_bytes()
                row["report_sha256"] = hashlib.sha256(raw).hexdigest()
                require(row["child_exit_code"] == 0, "Workload failed; original partial evidence retained")
                packet = json.loads(raw)
                require(packet["image"] == postgres_image, "Requested immutable server image differs")
                row["verified"] = pair.verify(packet, root, commits[label], count)
                require(source(root) == commits[label], "Frozen source changed after workload")
                require(packet["harness_sha256"] == packet["harness_sha256_after"], "Common harness changed")
                configuration = {field: packet[field] for field in (*pair.CONFIG, "harness_sha256")}
                matched_configuration = matched_configuration or configuration
                require(configuration == matched_configuration, "Hardware/database/workload configuration differs")
                power.verify_environment(after, expected_scheme)
                require(after["active_parameters"]["stdout_sha256"] == parameters_sha, "Active power parameters changed")
                row["host_observations"] = power.verify_sampled_power(packet)
                row["environment_verification"] = row["financial_verification"] = "passed"
                power.write_json(output / "pair.json", state)
                print(json.dumps({"repetition": repetition, "variant": label, "verified": row["verified"]}), flush=True)
        metrics = ("posting_seconds", "throughput", "p50", "p95", "p99", "client_cpu_seconds",
                   "container_cpu_seconds", "total_cpu_seconds_per_success", "bounded_batch_read_seconds",
                   "container_lifetime_peak_memory_bytes", "client_lifetime_peak_memory_bytes")
        state.update(status="passed", expected_scheme_guid=expected_scheme,
                     active_parameters_sha256=parameters_sha, matched_configuration=matched_configuration,
                     financial_verification="passed", environment_verification="passed")
        state["medians"] = {label: {metric: statistics.median(row["verified"][metric] for row in state["runs"]
                                                            if row["variant"] == label) for metric in metrics}
                            for label in roots}
        state["raw_median_change_percent"] = {metric: 100 * (state["medians"]["candidate"][metric]
            / state["medians"]["baseline"][metric] - 1) for metric in metrics}
    except Exception as exc:
        state.update(status="failed", failure_type=type(exc).__name__, failure=str(exc))
    finally:
        power.write_json(output / "pair.json", state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, choices=(1000, 10000, 100000, 1000000), default=1000)
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument("--postgres-image", default="postgres:17.11-alpine@sha256:aa90e97ee862e558111d34cfb8b2c4bec768c2b039fb791341686928560263b3")
    args = parser.parse_args()
    require(30 <= args.max_seconds <= 7200, "Execution budget must remain bounded")
    result = run_pair({"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()},
                      args.output.resolve(), count=args.count, max_seconds=args.max_seconds, postgres_image=args.postgres_image)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
