#!/usr/bin/env python3
"""Reproduce a completed stable-power packet offline with the stdlib only.

python -I verify_stable_power_environment.py --packet copied-packet \
    --pair-sha256 <separately-trusted-original-pair-sha> \
    --manifest-sha256 <separately-trusted-original-manifest-sha> \
    --expected-scheme-guid <original-exact-guid> --report fresh-proof.json

Keep the four sibling controller/offline/global/native verifier scripts beside
this script. No checkout, application import, power query, subprocess, network,
database or benchmark is used. Original Windows report paths are validated then
rebased to six exact portable packet paths; original bytes remain unchanged.
Explicit trust digests must be supplied from an independent prior channel.
Observed AC/saver samples and twelve scheme bookends do not establish continuous
power stability, the Windows power-mode overlay, or performance acceptance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
from typing import Any

_spec = importlib.util.spec_from_file_location(
    "portable_stable_controller", Path(__file__).with_name("benchmark_stable_power_pair.py"))
if _spec is None or _spec.loader is None:
    raise RuntimeError("Sibling stable-power controller is absent")
_controller = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_controller)
require = _controller.require


def verify_packet(packet: Path, pair_sha256: str, manifest_sha256: str,
                  expected_scheme_guid: str) -> dict[str, Any]:
    """Bind original reports, manifest and twelve sidecars before environment proof."""
    packet = packet.resolve()
    raw = (packet / "pair.json").read_bytes()
    require(_controller._offline._sha(pair_sha256)
            and hashlib.sha256(raw).hexdigest() == pair_sha256, "Trusted original pair SHA differs")
    state = _controller._offline._json(raw)
    require(state["schema_version"] == "stable-power-pair-controller-v1"
            and state["status"] == "passed" and state["financial_verification"] == "passed"
            and state["environment_verification"] == "passed"
            and state["performance_comparison_accepted"] is False, "Original controller not complete")
    require(type(state["pairs"]) is int and state["pairs"] == 3
            and type(state["count"]) is int and state["count"] == 1000
            and state["order"] == "BC,CB,BC", "Original controller workload differs")
    require(state["commits"] == dict(_controller._offline.COMMITS)
            and state["expected_scheme_guid"] == expected_scheme_guid, "Source or scheme differs")
    require(_controller._offline._sha(manifest_sha256)
            and state["manifest_sha256"] == manifest_sha256, "Separately trusted manifest differs")
    financial = _controller._offline.verify_manifest(packet / "manifest.json", manifest_sha256)
    rows = copy.deepcopy(state["runs"])
    require(len(rows) == 6, "Incomplete original run population")
    original_root = None
    for row, (repetition, variant) in zip(rows, _controller._offline.ORDER, strict=True):
        require(row["repetition"] == repetition and row["variant"] == variant
                and row["child_exit_code"] == 0, "Original run order or exit differs")
        original = PureWindowsPath(row["report"])
        require(original.is_absolute() and original.name == "result.json"
                and original.parent.name == f"{repetition}-{variant}", "Original Windows report identity differs")
        if original_root is None:
            original_root = original.parent.parent
        require(original.parent.parent == original_root, "Original report roots differ")
        row["report"] = str(_controller._offline._report_path(packet, f"{repetition}-{variant}/result.json"))
    environment = _controller.verify_sidecars(packet, rows, expected_scheme_guid)
    expected_raw = (packet / "environment-proof.json").read_bytes()
    require(_controller._offline._sha(state["environment_proof_sha256"])
            and hashlib.sha256(expected_raw).hexdigest() == state["environment_proof_sha256"],
            "Original environment proof SHA differs")
    require(_controller._offline._json(expected_raw) == environment, "Reproduced environment differs")
    return {"schema_version": "portable-stable-power-reproduction-v1", "status": "passed",
            "financial_verification": "passed", "environment_verification": "passed",
            "performance_comparison_accepted": False,
            "trusted_pair_sha256": pair_sha256, "trusted_manifest_sha256": manifest_sha256,
            "original_environment_proof_sha256": state["environment_proof_sha256"],
            "environment": environment, "financial": financial,
            "path_rebase": "only six trusted absolute Windows report paths replaced by exact portable expected paths; raw evidence unchanged"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--pair-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--expected-scheme-guid", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError("Fresh output report required")
    try:
        result = verify_packet(args.packet, args.pair_sha256, args.manifest_sha256, args.expected_scheme_guid)
    except Exception as exc:
        result = {"schema_version": "portable-stable-power-reproduction-v1", "status": "failed",
                  "performance_comparison_accepted": False, "failure_type": type(exc).__name__, "failure": str(exc)}
    args.report.write_bytes((json.dumps(result, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    print(json.dumps({"status": result["status"], "report": str(args.report), "performance_comparison_accepted": False}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
