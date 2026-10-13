"""File-only orchestration over original native goldens; HTTP anchors are synthetic.

These cases do not execute a browser or database. Existing standalone oracles
execute real integer/Fraction checks in isolated normal/optimized processes.
No original repository fixture is modified.
"""
import copy
import hashlib
import json
import runpy
import subprocess
from pathlib import Path

import pytest

from tests import original_browser_download_verification as verifier

ROOT = Path(__file__).resolve().parents[1]


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def write(path, value):
    path.write_bytes(encode(value))


def oracle(name):
    return runpy.run_path(str(ROOT / ".github/scripts" / name))


def setup_case(tmp_path, scenario, *, nested=False):
    output = tmp_path / "owned"
    output.mkdir()
    root = output / "playwright-artifacts" if nested else output
    root.mkdir(exist_ok=True)
    if scenario == "project-source-reconciliation":
        raw = (ROOT / "tests/fixtures/project_source_close_final_native_v1.json").read_bytes()
        close = json.loads(raw)
        source_raw = encode(close["source_evidence"])
        # This is the exact native wrapper's separately sealed canonical source
        # member; test extraction does not create replacement financial values.
        assert hashlib.sha256(source_raw).hexdigest() == close["source_original_sha256"]
        assert len(source_raw) == close["source_original_bytes"]
        (root / "project-source-original.json").write_bytes(source_raw)
        (root / "project-source-close-original.json").write_bytes(raw)
        helper = oracle("verify_project_source_reconciliation.py")
        callback = {"browser_financial_writes": False, "original_evidence": copy.deepcopy(close["source_evidence"]),
                    "source_close_original_evidence": copy.deepcopy(close),
                    "independent_oracle": helper["verify"](close["source_evidence"]),
                    "source_close_independent_oracle": helper["verify_close"](close)}
        selected = close["diagnostic"]["selection"]
        boundary = {"browser_financial_writes": False, "project_id": selected["project_id"],
                    "source_payrun_id": selected["payrun_id"], "source_invoice_id": selected["invoice_id"],
                    "original_sha256": hashlib.sha256(source_raw).hexdigest(), "original_bytes": len(source_raw),
                    "source_close_original_sha256": hashlib.sha256(raw).hexdigest(), "source_close_original_bytes": len(raw)}
        write(root / "project-source-browser-boundary.json", boundary)
    else:
        cash = scenario == "intercompany-source-cashflow"
        fixture = "intercompany-source-cashflow-native-v1.json" if cash else "intercompany-group-diagnostic-native-v1.json"
        prefix = "cashflow" if cash else "group-diagnostic"
        raw = (ROOT / "tests/fixtures" / fixture).read_bytes()
        original = json.loads(raw)
        (root / (prefix + "-original.json")).write_bytes(raw)
        helper = oracle("verify_intercompany_cashflow_oracle.py" if cash else "verify_intercompany_group_diagnostic.py")
        callback = {"browser_financial_writes": False, "original_evidence": copy.deepcopy(original),
                    "independent_oracle": helper["verify"](original)}
        boundary = {"browser_financial_writes": False, "original_sha256": hashlib.sha256(raw).hexdigest(), "original_bytes": len(raw)}
        if cash:
            boundary["source_id"] = original["source"]["id"]
        else:
            boundary["selected_source_ids"] = sorted(pin["opening"]["source_id"] for pin in original["selection"]["pins"])
        write(root / (prefix + "-browser-read-boundary.json"), boundary)
        write(root / (prefix + "-original-wire.json"), {"status": 200, "content_type": "application/json",
              "content_length": str(len(raw)), "original_sha256": boundary["original_sha256"]})
    return output, root, callback


@pytest.mark.parametrize("scenario", tuple(verifier.SCENARIOS))
@pytest.mark.parametrize("nested", [False, True])
def test_all_actual_native_goldens_execute_isolated_existing_oracles_and_preserve_bytes(tmp_path, scenario, nested):
    output, root, callback = setup_case(tmp_path, scenario, nested=nested)
    before = {path.name: path.read_bytes() for path in root.glob("*.json")}
    result = verifier.verify_original_browser_downloads(output, scenario, callback)
    assert result["isolated_oracle_executions"] == (4 if scenario == "project-source-reconciliation" else 2)
    assert result["current_authority_proven_by_this_file_verifier"] is False
    assert result["browser_tls_execution_proven_by_this_file_verifier"] is False
    for item in result["artifacts"]:
        assert item["normal_optimized_byte_equal"] is True
        assert item["normal"]["sha256"] == item["optimized"]["sha256"]
        assert item["helper"]["sha256"] == hashlib.sha256((ROOT / ".github/scripts" / item["helper"]["path"]).read_bytes()).hexdigest()
    assert all((root / name).read_bytes() == raw for name, raw in before.items())
    with pytest.raises(FileExistsError):
        verifier.verify_original_browser_downloads(output, scenario, callback)


@pytest.mark.parametrize("mutation", ["raw", "length", "source_id", "stable_digest", "missing_raw", "missing_boundary",
                                     "missing_wire", "status", "type", "boolean_bytes", "duplicate_boundary", "ambiguous"])
def test_wrong_original_anchor_subject_or_missing_artifact_refuses_before_cli(tmp_path, monkeypatch, mutation):
    output, root, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    boundary_path = root / "cashflow-browser-read-boundary.json"
    wire_path = root / "cashflow-original-wire.json"
    boundary, wire = json.loads(boundary_path.read_bytes()), json.loads(wire_path.read_bytes())
    if mutation == "raw":
        with (root / "cashflow-original.json").open("ab") as handle:
            handle.write(b" ")
    elif mutation == "length":
        boundary["original_bytes"] += 1
        wire["content_length"] = str(boundary["original_bytes"])
    elif mutation == "source_id":
        boundary["source_id"] += "-foreign"
    elif mutation == "stable_digest":
        callback["original_evidence"]["cashflow"]["cashflow_digest"] = "0" * 64
    elif mutation.startswith("missing_"):
        {"missing_raw": root / "cashflow-original.json", "missing_boundary": boundary_path,
         "missing_wire": wire_path}[mutation].unlink()
    elif mutation == "status":
        wire["status"] = 403
    elif mutation == "type":
        wire["content_type"] = "text/html"
    elif mutation == "boolean_bytes":
        boundary["original_bytes"] = True
    elif mutation == "duplicate_boundary":
        boundary_path.write_bytes(b'{"browser_financial_writes":false,"browser_financial_writes":false}')
    else:
        nested = output / "playwright-artifacts"
        nested.mkdir()
        (nested / "cashflow-original.json").write_bytes(b"{}")
    if mutation not in {"missing_boundary", "duplicate_boundary"}:
        write(boundary_path, boundary)
    if mutation != "missing_wire":
        write(wire_path, wire)
    def forbidden(*args, **kwargs):
        raise AssertionError("No oracle may execute for failed original admission")
    monkeypatch.setattr(verifier.subprocess, "run", forbidden)
    with pytest.raises((ValueError, OSError, KeyError)):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)
    assert not (output / "original-browser-download-verification").exists()


def test_cli_failure_retains_exclusive_original_logs_and_does_not_rewrite_download(tmp_path, monkeypatch):
    output, root, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    raw = (root / "cashflow-original.json").read_bytes()
    monkeypatch.setattr(verifier.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 7, b"original diagnostic", b"refused"))
    with pytest.raises(ValueError, match="isolated original verifier failed"):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)
    directory = output / "original-browser-download-verification"
    assert (directory / "1-I.stdout.log").read_bytes() == b"original diagnostic"
    assert (directory / "1-I.stderr.log").read_bytes() == b"refused"
    assert json.loads((directory / "1-I.execution.json").read_bytes())["returncode"] == 7
    assert (root / "cashflow-original.json").read_bytes() == raw


def test_normal_optimized_output_byte_mismatch_is_refused_and_preserved(tmp_path, monkeypatch):
    output, _, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    original = subprocess.run
    def differ(args, **kwargs):
        result = original(args, **kwargs)
        if "-O" in args and result.returncode == 0:
            with Path(args[-1]).open("ab") as handle:
                handle.write(b" ")
        return result
    monkeypatch.setattr(verifier.subprocess, "run", differ)
    with pytest.raises(ValueError, match="normal and optimized original results differ"):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)
    assert (output / "original-browser-download-verification/1-IO.json").exists()


@pytest.mark.parametrize("field", ["native_effects", "closing_minor"])
def test_independent_result_must_match_original_current_native_callback(tmp_path, field):
    output, _, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    callback["independent_oracle"][field] += 1
    with pytest.raises(ValueError, match="independent original result differs"):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)


@pytest.mark.parametrize("mutation", ["time", "other_native_timestamp", "source", "diagnostic", "missing_clock", "typed_clock", "naive_clock"])
def test_project_only_exact_capture_clock_and_dependent_raw_seals_may_differ(tmp_path, mutation):
    output, root, callback = setup_case(tmp_path, "project-source-reconciliation")
    source = json.loads((root / "project-source-original.json").read_bytes())
    close = json.loads((root / "project-source-close-original.json").read_bytes())
    if mutation == "time":
        source["original_rows"]["captured_at"] = "2026-10-13T22:00:00+00:00"
        close["source_evidence"]["original_rows"]["captured_at"] = "2026-10-13T22:00:01+00:00"
    elif mutation == "other_native_timestamp":
        source["original_rows"]["entries"][0]["created_at"] = "2026-10-13T22:00:00+00:00"
    elif mutation == "source":
        close["source_evidence"]["selection"]["invoice_id"] += "-foreign"
    elif mutation == "missing_clock":
        source["original_rows"].pop("captured_at")
    elif mutation == "typed_clock":
        source["original_rows"]["captured_at"] = True
    elif mutation == "naive_clock":
        source["original_rows"]["captured_at"] = "2026-10-13T22:00:00"
    else:
        close["diagnostic"]["diagnostic_digest"] = "0" * 64
    for proof in (source, close["source_evidence"]):
        proof["evidence_digest"] = hashlib.sha256(encode({key: value for key, value in proof.items() if key != "evidence_digest"})).hexdigest()
    close["source_original_sha256"] = hashlib.sha256(encode(close["source_evidence"])).hexdigest()
    close["source_original_bytes"] = len(encode(close["source_evidence"]))
    close["evidence_digest"] = hashlib.sha256(encode({key: value for key, value in close.items() if key != "evidence_digest"})).hexdigest()
    write(root / "project-source-original.json", source)
    write(root / "project-source-close-original.json", close)
    boundary_path = root / "project-source-browser-boundary.json"
    boundary = json.loads(boundary_path.read_bytes())
    for name, prefix in (("project-source-original.json", ""), ("project-source-close-original.json", "source_close_")):
        raw = (root / name).read_bytes()
        boundary[prefix + "original_sha256"], boundary[prefix + "original_bytes"] = hashlib.sha256(raw).hexdigest(), len(raw)
    write(boundary_path, boundary)
    if mutation == "time":
        assert verifier.verify_original_browser_downloads(output, "project-source-reconciliation", callback)["isolated_oracle_executions"] == 4
    else:
        with pytest.raises(ValueError, match="original Project source or stable diagnostic changed|timestamp"):
            verifier.verify_original_browser_downloads(output, "project-source-reconciliation", callback)


@pytest.mark.parametrize("scenario", ["../../foreign", "unsupported", ""])
def test_no_arbitrary_scenario_or_script_admission(tmp_path, scenario):
    with pytest.raises(ValueError, match="unsupported scenario"):
        verifier.verify_original_browser_downloads(tmp_path, scenario, {})
    assert list(tmp_path.iterdir()) == []


def test_timeout_keeps_original_partial_logs_and_negative_execution(tmp_path, monkeypatch):
    output, root, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    original = (root / "cashflow-original.json").read_bytes()
    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=b"partial stdout", stderr=b"partial stderr")
    monkeypatch.setattr(verifier.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="isolated verifier timeout"):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)
    proof = output / "original-browser-download-verification"
    assert json.loads((proof / "1-I.execution.json").read_bytes()) == {
        "timed_out": True, "returncode": None, "original_accepted": False}
    assert (proof / "1-I.stdout.log").read_bytes() == b"partial stdout"
    assert (root / "cashflow-original.json").read_bytes() == original


def test_changed_reviewed_helper_source_refuses_before_child_launch(tmp_path, monkeypatch):
    output, _, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    actual = verifier.read
    count = 0
    def changed(path, root, limit):
        nonlocal count
        raw = actual(path, root, limit)
        if path.name == "verify_intercompany_cashflow_oracle.py":
            count += 1
            if count > 1:
                return raw + b"\n"
        return raw
    def forbidden(*args, **kwargs):
        raise AssertionError("Changed verifier must not execute")
    monkeypatch.setattr(verifier, "read", changed)
    monkeypatch.setattr(verifier.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="reviewed verifier source changed before execution"):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)


def test_declared_download_byte_budget_is_checked_before_oracle(tmp_path, monkeypatch):
    output, _, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    monkeypatch.setattr(verifier, "MAX_BYTES", 100)
    with pytest.raises(ValueError, match="exact byte count"):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)


def test_nonregular_original_download_refuses_without_reading_it(tmp_path):
    output, root, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    original = root / "cashflow-original.json"
    original.unlink()
    original.mkdir()
    with pytest.raises(ValueError, match="regular non-reparse artifact"):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)


def test_observed_http_anchor_drift_during_cli_refuses_completed_custody(tmp_path, monkeypatch):
    output, root, callback = setup_case(tmp_path, "intercompany-source-cashflow")
    original_run = subprocess.run
    wire = root / "cashflow-original-wire.json"
    def changed(args, **kwargs):
        result = original_run(args, **kwargs)
        value = json.loads(wire.read_bytes())
        value["status"] = 403
        write(wire, value)
        return result
    monkeypatch.setattr(verifier.subprocess, "run", changed)
    with pytest.raises(ValueError, match="original observed HTTP anchor changed"):
        verifier.verify_original_browser_downloads(output, "intercompany-source-cashflow", callback)
    assert not (output / "original-browser-download-verification/custody.json").exists()
