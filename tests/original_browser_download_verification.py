"""Verify unchanged browser financial downloads with existing isolated oracles.

The trusted caller first accepts its actual browser/TLS run. This helper binds
that run's observed wire/boundary records and currently authorized native
callback; it neither authenticates those records independently nor rewrites an
export. Only Project's exact capture timestamp and dependent envelope anchors
may differ from the retained seed. Existing oracles verify all original seals.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_NODES = 1_000_000
ORACLE_TIMEOUT_SECONDS = 90
SCENARIOS = {
    "intercompany-source-cashflow": (("cashflow-original.json", "verify_intercompany_cashflow_oracle.py", "cashflow"),),
    "intercompany-group-diagnostic": (("group-diagnostic-original.json", "verify_intercompany_group_diagnostic.py", "group"),),
    "project-source-reconciliation": (
        ("project-source-original.json", "verify_project_source_reconciliation.py", "source"),
        ("project-source-close-original.json", "verify_project_source_reconciliation.py", "close"),
    ),
}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("Original browser download refused: " + reason)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")


def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in items:
        require(key not in value, "duplicate JSON member")
        value[key] = member
    return value


def noninteger(value: str) -> None:
    raise ValueError("Original browser download refused: float or nonfinite JSON")


def parse(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw, object_pairs_hook=pairs, parse_float=noninteger, parse_constant=noninteger)
    require(type(value) is dict, "JSON object required")
    pending, count = [value], 0
    while pending:
        item = pending.pop()
        count += 1
        require(count <= MAX_NODES, "JSON node budget")
        if type(item) is dict:
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return value


def regular(path: Path, root: Path) -> None:
    require(root.resolve(strict=True) == root and not root.is_symlink(), "owned directory binding changed")
    directory = root.lstat()
    require(not (getattr(directory, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)),
            "regular non-reparse directory required")
    require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True)), "artifact escaped owned directory")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink()
            and not (getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)),
            "regular non-reparse artifact required")


def read(path: Path, root: Path, limit: int) -> bytes:
    regular(path, root)
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    require(len(raw) <= limit, "artifact byte budget")
    return raw


def record(path: Path, raw: bytes) -> dict[str, Any]:
    return {"path": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def exact(left: Any, right: Any, reason: str) -> None:
    require(canonical(left) == canonical(right), reason)


def source_projection(proof: dict[str, Any]) -> dict[str, Any]:
    # Comparison only: never serialize this projection as an original export.
    captured = proof["original_rows"].get("captured_at")
    require(type(captured) is str and bool(captured), "original native capture timestamp required")
    try:
        require(datetime.fromisoformat(captured).utcoffset() is not None, "capture timestamp must retain its timezone")
    except ValueError as exc:
        raise ValueError("Original browser download refused: invalid original capture timestamp") from exc
    result = {key: value for key, value in proof.items() if key != "evidence_digest"}
    result["original_rows"] = {key: value for key, value in proof["original_rows"].items() if key != "captured_at"}
    return result


def close_projection(proof: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in proof.items()
              if key not in {"evidence_digest", "source_original_sha256", "source_original_bytes"}}
    result["source_evidence"] = source_projection(proof["source_evidence"])
    return result


def artifact_root(output: Path, filenames: tuple[str, ...]) -> Path:
    root = output.resolve(strict=True)
    require(root.is_dir(), "owned output directory required")
    nested = root / "playwright-artifacts"
    if nested.exists():
        require(nested.is_dir() and not nested.is_symlink()
                and nested.resolve(strict=True).is_relative_to(root), "owned browser artifact directory required")
        require(not any((root / name).exists() for name in filenames), "ambiguous flat and nested artifacts")
        return nested.resolve(strict=True)
    return root


def anchors(root: Path, scenario: str, persisted: dict[str, Any]) -> tuple[dict[str, tuple[str, int]], list[dict[str, Any]]]:
    boundary_name = {"intercompany-source-cashflow": "cashflow-browser-read-boundary.json",
                     "intercompany-group-diagnostic": "group-diagnostic-browser-read-boundary.json",
                     "project-source-reconciliation": "project-source-browser-boundary.json"}[scenario]
    boundary_raw = read(root / boundary_name, root, MAX_METADATA_BYTES)
    boundary = parse(boundary_raw)
    require(boundary["browser_financial_writes"] is False, "browser financial writes unsupported")
    records = [record(root / boundary_name, boundary_raw)]
    observed = {}
    if scenario == "project-source-reconciliation":
        expected = persisted["original_evidence"]["report"]["selection"]
        exact((boundary["project_id"], boundary["source_payrun_id"], boundary["source_invoice_id"]),
              (expected["project_id"], expected["payrun_id"], expected["invoice_id"]), "original Project source selection")
        for name, prefix in (("project-source-original.json", ""), ("project-source-close-original.json", "source_close_")):
            observed[name] = (boundary[prefix + "original_sha256"], boundary[prefix + "original_bytes"])
    else:
        wire_name = "cashflow-original-wire.json" if scenario == "intercompany-source-cashflow" else "group-diagnostic-original-wire.json"
        wire_raw = read(root / wire_name, root, MAX_METADATA_BYTES)
        wire = parse(wire_raw)
        require(set(wire) == {"status", "content_type", "content_length", "original_sha256"}
                and type(wire["status"]) is int and wire["status"] == 200
                and type(wire["content_type"]) is str
                and re.fullmatch(r"application/json(?:;\s*charset=utf-8)?", wire["content_type"], re.IGNORECASE) is not None,
                "successful exact original HTTP metadata")
        require(type(wire["content_length"]) is str and re.fullmatch(r"[1-9][0-9]{0,8}", wire["content_length"]) is not None,
                "exact HTTP byte length")
        exact((wire["original_sha256"], int(wire["content_length"])),
              (boundary["original_sha256"], boundary["original_bytes"]), "wire and boundary raw anchors differ")
        records.append(record(root / wire_name, wire_raw))
        name = "cashflow-original.json" if scenario == "intercompany-source-cashflow" else "group-diagnostic-original.json"
        observed[name] = (boundary["original_sha256"], boundary["original_bytes"])
        if scenario == "intercompany-source-cashflow":
            exact(boundary["source_id"], persisted["original_evidence"]["source"]["id"], "original Cashflow source identity")
        else:
            expected_ids = sorted(pin["opening"]["source_id"] for pin in persisted["original_evidence"]["selection"]["pins"])
            exact(boundary["selected_source_ids"], expected_ids, "original Group source identities")
    for digest, length in observed.values():
        require(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
                and type(length) is int and 0 < length <= MAX_BYTES, "separately observed raw SHA and exact byte count")
    return observed, records


def stable(proof: dict[str, Any], persisted: dict[str, Any], kind: str) -> None:
    expected = persisted["source_close_original_evidence"] if kind == "close" else persisted["original_evidence"]
    if kind in {"cashflow", "group"}:
        exact(proof, expected, "original complete selected source evidence changed")
    else:
        projection = close_projection if kind == "close" else source_projection
        exact(projection(proof), projection(expected), "original Project source or stable diagnostic changed")


def verify_original_browser_downloads(output: Path, scenario: str, persisted_effects: dict[str, Any]) -> dict[str, Any]:
    require(type(scenario) is str and scenario in SCENARIOS, "unsupported scenario")
    require(type(persisted_effects) is dict and persisted_effects["browser_financial_writes"] is False,
            "current authorized native callback required")
    configuration = SCENARIOS[scenario]
    root = artifact_root(output, tuple(item[0] for item in configuration))
    observed, metadata = anchors(root, scenario, persisted_effects)
    admitted = []
    for filename, helper_name, kind in configuration:
        path = root / filename
        raw = read(path, root, MAX_BYTES)
        digest, length = observed[filename]
        require(len(raw) == length and hashlib.sha256(raw).hexdigest() == digest, "download raw anchor changed")
        proof = parse(raw)
        stable(proof, persisted_effects, kind)
        helper = ROOT / ".github/scripts" / helper_name
        helper_raw = read(helper, ROOT, MAX_METADATA_BYTES)
        admitted.append((path, raw, proof, helper, helper_raw, kind))
    if scenario == "project-source-reconciliation":
        exact(source_projection(admitted[0][2]), source_projection(admitted[1][2]["source_evidence"]),
              "source and close downloads select different original financial populations")
    # Fresh exclusive directory: an unsuccessful attempt retains all its logs
    # and outputs and cannot be silently overwritten by a retry.
    destination = output.resolve(strict=True) / "original-browser-download-verification"
    destination.mkdir(exist_ok=False)
    interpreter = Path(getattr(sys, "_base_executable", sys.executable)).resolve(strict=True)
    results: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []
    for index, (path, raw, _proof, helper, helper_raw, kind) in enumerate(admitted, 1):
        outputs = []
        for optimized in (False, True):
            tag = f"{index}-{'IO' if optimized else 'I'}"
            result_path = destination / (tag + ".json")
            args = [str(interpreter), "-I", *(["-O"] if optimized else []), str(helper)]
            digest = hashlib.sha256(raw).hexdigest()
            args += (["--evidence", str(path), "--expected-sha256", digest, "--kind", kind]
                     if kind in {"source", "close"} else [str(path), "--sha256", digest])
            args += ["--output", str(result_path)]
            require(read(path, root, MAX_BYTES) == raw and read(helper, ROOT, MAX_METADATA_BYTES) == helper_raw,
                    "original input or reviewed verifier source changed before execution")
            command_raw = canonical({"schema_version": "original-browser-oracle-command-v1", "argv": args,
                "original": record(path, raw), "helper": record(helper, helper_raw), "optimized": optimized,
                "environment_captured": False, "shell": False, "timeout_seconds": ORACLE_TIMEOUT_SECONDS})
            command_path = destination / (tag + ".command.json")
            with command_path.open("xb") as handle:
                handle.write(command_raw)
            generated.append(record(command_path, command_raw))
            try:
                process = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=ORACLE_TIMEOUT_SECONDS, check=False)
            except subprocess.TimeoutExpired as exc:
                for suffix, data in (("stdout", exc.stdout or b""), ("stderr", exc.stderr or b"")):
                    with (destination / (tag + "." + suffix + ".log")).open("xb") as handle:
                        handle.write(data)
                with (destination / (tag + ".execution.json")).open("xb") as handle:
                    handle.write(canonical({"timed_out": True, "returncode": None, "original_accepted": False}))
                raise ValueError("Original browser download refused: isolated verifier timeout") from exc
            for suffix, data in (("stdout", process.stdout), ("stderr", process.stderr)):
                require(len(data) <= MAX_METADATA_BYTES, "oracle log byte budget")
                log_path = destination / (tag + "." + suffix + ".log")
                with log_path.open("xb") as handle:
                    handle.write(data)
                generated.append(record(log_path, data))
            execution_raw = canonical({"timed_out": False, "returncode": process.returncode,
                "stdout": record(destination / (tag + ".stdout.log"), process.stdout),
                "stderr": record(destination / (tag + ".stderr.log"), process.stderr)})
            execution_path = destination / (tag + ".execution.json")
            with execution_path.open("xb") as handle:
                handle.write(execution_raw)
            generated.append(record(execution_path, execution_raw))
            require(process.returncode == 0, "isolated original verifier failed")
            result_raw = read(result_path, destination, MAX_METADATA_BYTES)
            result = parse(result_raw)
            if kind in {"cashflow", "group"}:
                exact((result["original_sha256"], result["original_bytes"]), (digest, len(raw)), "oracle raw anchor differs")
                summary = {key: value for key, value in result.items() if key not in {"original_sha256", "original_bytes"}}
                expected = persisted_effects["independent_oracle"]
            else:
                exact((result["raw_sha256"], result["raw_bytes"], result["raw_export_anchor"]),
                      (digest, len(raw), True), "oracle raw anchor differs")
                volatile = {"raw_sha256", "raw_bytes", "raw_export_anchor", "evidence_digest", "source_original_sha256"}
                summary = {key: value for key, value in result.items() if key not in volatile}
                expected = persisted_effects["source_close_independent_oracle" if kind == "close" else "independent_oracle"]
                expected = {key: value for key, value in expected.items() if key not in volatile}
            exact(summary, expected, "independent original result differs from native callback")
            outputs.append(result_raw)
        require(outputs[0] == outputs[1], "normal and optimized original results differ")
        require(read(path, root, MAX_BYTES) == raw and read(helper, ROOT, MAX_METADATA_BYTES) == helper_raw,
                "original input or reviewed verifier source changed during execution")
        results.append({"original": record(path, raw), "kind": kind, "helper": record(helper, helper_raw),
                        "helper_normalized_source_sha256": hashlib.sha256(helper_raw.replace(b"\r\n", b"\n")).hexdigest(),
                        "normal": record(destination / f"{index}-I.json", outputs[0]),
                        "optimized": record(destination / f"{index}-IO.json", outputs[1]),
                        "normal_optimized_byte_equal": True})
    # A later oracle must not invalidate an earlier completed artifact pair.
    # Pin the whole admitted bundle again before publishing successful custody.
    for path, raw, _proof, helper, helper_raw, _kind in admitted:
        require(read(path, root, MAX_BYTES) == raw and read(helper, ROOT, MAX_METADATA_BYTES) == helper_raw,
                "original input or reviewed verifier source changed before completed custody")
    for artifact in results:
        for mode in ("normal", "optimized"):
            retained_output = artifact[mode]
            path = destination / retained_output["path"]
            exact(record(path, read(path, destination, MAX_METADATA_BYTES)), retained_output,
                  "isolated oracle output changed before completed custody")
    for retained_artifact in generated:
        path = destination / retained_artifact["path"]
        exact(record(path, read(path, destination, MAX_METADATA_BYTES)), retained_artifact,
              "isolated oracle execution artifact changed before completed custody")
    for retained in metadata:
        path = root / retained["path"]
        exact(record(path, read(path, root, MAX_METADATA_BYTES)), retained,
              "original observed HTTP anchor changed during verification")
    result = {"schema_version": "original-browser-download-verification-v1", "scenario": scenario,
              "artifacts": results, "observed_anchor_artifacts": metadata,
              "retained_execution_artifacts": generated, "financial_raw_bytes_unchanged": True,
              "stable_original_callback_membership_equal": True, "isolated_oracle_executions": 2 * len(results),
              "python_executable": str(interpreter), "current_authority_proven_by_this_file_verifier": False,
              "browser_tls_execution_proven_by_this_file_verifier": False, "financial_writes": False,
              "formal_close_workflow_assessed": False, "performance_comparison_accepted": False}
    with (destination / "custody.json").open("xb") as handle:
        handle.write(canonical(result))
    return result
