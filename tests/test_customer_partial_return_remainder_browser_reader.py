"""Custody counterexamples and real isolated readers over synthetic raw controls."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests import customer_partial_return_remainder_browser_reader as gate
from tests.test_customer_partial_return_remainder_posted_oracle import observations_fixture


def family(private: Path, case: str = "ordinary", *, restore: bool = False) -> Path:
    packet, observations, restored = observations_fixture(case)
    root = private / gate.FAMILY / case
    root.mkdir(parents=True)
    for number, value in enumerate(packet["captures"]):
        (root / f"committed-capture-{number}.json").write_bytes(gate._encode(value))
    (root / gate.PACKET).write_bytes(gate._encode(packet))
    folder = private / gate.OBSERVATIONS / case
    folder.mkdir(parents=True)
    for observation, name in zip(observations["observations"], (f"retained-replay-{gate.REPLAY[case]}.json", "final-observation.json"), strict=True):
        (folder / name).write_bytes(gate._encode(observation))
    (folder / gate.OBSERVATIONS_PACKET).write_bytes(gate._encode(observations))
    if restore:
        (root / gate.RESTORE).write_bytes(gate._encode(restored))
    return root


def simulated(monkeypatch: pytest.MonkeyPatch, private: Path, *, case: str = "ordinary", restore: bool = False,
              patch: dict[str, Any] | None = None, mode: str = "success") -> list[list[str]]:
    calls = []

    def run(argv: list[str], **options: Any) -> Any:
        calls.append(argv)
        assert options["check"] is False and options["timeout"] == 60 and options["stdin"] == gate.subprocess.DEVNULL
        assert not any(key in options["env"] for key in ("RECONFORGE_GFO_APP_DSN", "RECONFORGE_ERP_PASSWORD", "PYTHONPATH"))
        if mode == "timeout":
            raise gate.subprocess.TimeoutExpired(argv, 60)
        if mode == "launch":
            raise OSError("private exception text must never be exposed")
        if mode == "nonzero":
            return SimpleNamespace(returncode=7)
        inputs = gate._family(private, case=case, require_restore=restore)
        proof = gate._expected(inputs, 2)
        if patch:
            proof.update(copy.deepcopy(patch))
        output = Path(argv[argv.index("--output") + 1])
        data = json.dumps(proof, indent=2).encode() if mode == "io-drift" and "-O" in argv else gate._encode(proof)
        output.write_bytes(data)
        if mode == "input-drift":
            path = private / gate.FAMILY / case / "committed-capture-0.json"
            path.write_bytes(path.read_bytes() + b" ")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gate.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("case", ["ordinary", "zero", "refund"])
@pytest.mark.parametrize("restore", [False, True])
def test_real_isolated_readers_qualify_synthetic_adapter_and_rebind_all_files(tmp_path: Path, case: str, restore: bool) -> None:
    # This executes the actual stdlib readers, but these synthetic dictionaries
    # remain unit controls and are never evidence of a DB/browser execution.
    family(tmp_path, case, restore=restore)
    proof = gate.verify_remainder_original_rows(tmp_path, case=case, require_restore=restore)
    gate.require_remainder_original_binding(tmp_path, proof, case=case, require_restore=restore)
    assert proof["case"] == case and proof["restored"] is restore
    assert proof["captures"] == gate.EVENTS[case] + 1 and proof["tables"] == 79
    assert proof["isolated_modes_byte_equal"] is True and proof["observations"] == 2
    assert proof["original_zero_cost_admission"] is False and proof["raw_financial_rows_published"] is False
    text = gate._encode(proof)
    assert all(value not in text for value in (str(tmp_path).encode(), b'"tenant"', b'"stock"', b'"plan-1"'))
    with pytest.raises(gate.RemainderOriginalRefusal):
        gate.verify_remainder_original_rows(tmp_path, case=case, require_restore=restore)


@pytest.mark.parametrize("patch", [
    {"events": True}, {"events": 4}, {"captures": 5}, {"case": "zero"}, {"new_debits_minor": "4001"},
    {"new_actual_posting_effects": 5}, {"new_actual_posted_lines": 11}, {"new_credits_minor": 4000},
    {"positive_original_consumptions": 2}, {"original_zero_cost_admission": True}, {"tables": 78},
    {"appended_audit_events": True}, {"appended_audit_events": 0}, {"appended_audit_events": 8193},
    {"audit_chain_valid": False}, {"audit_original_prefix_equal": False}, {"business_original_rows_equal": False},
    {"observation_chronology_bound": False}, {"raw_rows": "PRIVATE_FINANCE"}, {"input_sha256": {}},
    {"reader_source_sha256": {**gate.SOURCE_HASHES, "customer_partial_return_remainder_posted_oracle.py": "f" * 64}},
])
def test_wrong_metrics_types_sources_or_raw_extras_never_become_public_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, patch: dict[str, Any]) -> None:
    family(tmp_path)
    simulated(monkeypatch, tmp_path, patch=patch)
    with pytest.raises(gate.RemainderOriginalRefusal):
        gate.verify_remainder_original_rows(tmp_path, case="ordinary", require_restore=False)


@pytest.mark.parametrize("attack", ["extra", "missing", "raw-map-packet", "capture-drift", "boolean-version", "wrong-tenant",
    "wrong-case", "missing-table", "extra-table", "duplicate-key", "fraction", "observation-drift", "observation-order", "restore-drift"])
def test_unjoined_malformed_or_foreign_capture_families_refuse_before_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str) -> None:
    root = family(tmp_path, restore=True)
    if attack == "extra":
        (root / "foreign-original.json").write_bytes(b"{}")
    elif attack == "missing":
        (root / "committed-capture-3.json").unlink()
    else:
        path = root / (gate.PACKET if attack in {"raw-map-packet", "wrong-case"} else gate.RESTORE if attack == "restore-drift" else "committed-capture-3.json")
        if attack.startswith("observation"):
            path = tmp_path / gate.OBSERVATIONS / "ordinary" / gate.OBSERVATIONS_PACKET
        value = gate._decode(path.read_bytes())
        if attack == "raw-map-packet":
            value["captures"] = [row["tables"] for row in value["captures"]]
        elif attack == "capture-drift":
            value["tables"]["finance_accounts"] = []
        elif attack == "boolean-version":
            value["history_version"] = True
        elif attack == "wrong-tenant":
            value["tenant_id"] = "foreign"
        elif attack == "wrong-case":
            value["case"] = "zero"
        elif attack == "missing-table":
            value["tables"].pop("customer_partial_return_allocation_witnesses")
        elif attack == "extra-table":
            value["tables"]["unreviewed"] = []
        elif attack == "observation-drift":
            value["observations"][-1]["plan_digest"] = "e" * 64
        elif attack == "observation-order":
            value["observations"].reverse()
        elif attack == "restore-drift":
            value["tables"]["finance_accounts"] = []
        original = gate._encode(value)
        if attack == "duplicate-key":
            original = original.replace(b'"history_version":3', b'"history_version":3,"history_version":3')
        elif attack == "fraction":
            original = original.replace(b'"history_version":3', b'"history_version":3.0')
        path.write_bytes(original)
    calls = simulated(monkeypatch, tmp_path, restore=True)
    with pytest.raises((gate.RemainderOriginalRefusal, ValueError)):
        gate.verify_remainder_original_rows(tmp_path, case="ordinary", require_restore=True)
    assert calls == []


@pytest.mark.parametrize("mode", ["timeout", "launch", "nonzero", "io-drift", "input-drift"])
def test_child_failures_and_races_retain_original_outcome_and_refuse_without_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    family(tmp_path)
    calls = simulated(monkeypatch, tmp_path, mode=mode)
    with pytest.raises(gate.RemainderOriginalRefusal):
        gate.verify_remainder_original_rows(tmp_path, case="ordinary", require_restore=False)
    assert len(calls) == (2 if mode == "io-drift" else 1)
    execution = next((tmp_path / gate.EXECUTIONS / "ordinary").iterdir())
    result = gate._decode((execution / "I.result.json").read_bytes())
    assert result["timed_out"] is (mode == "timeout") and result["launch_failed"] is (mode == "launch")
    assert (execution / "I.stdout").exists() and (execution / "I.stderr").exists()


@pytest.mark.parametrize("attack", ["input-bytes", "input-membership", "observation-bytes", "proof-bytes", "receipt-bytes", "result-bytes", "extra-execution", "published-proof", "source-pin"])
def test_after_publication_rebind_refuses_every_private_custody_or_public_projection_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str) -> None:
    family(tmp_path, restore=True)
    simulated(monkeypatch, tmp_path, restore=True)
    proof = gate.verify_remainder_original_rows(tmp_path, case="ordinary", require_restore=True)
    execution = next((tmp_path / gate.EXECUTIONS / "ordinary").iterdir())
    if attack == "published-proof":
        proof["new_debits_minor"] = 0
    elif attack == "source-pin":
        monkeypatch.setitem(gate.SOURCE_HASHES, "customer_partial_return_remainder_oracle.py", "f" * 64)
    elif attack == "extra-execution":
        (execution / "unreviewed.json").write_bytes(b"{}")
    elif attack == "input-membership":
        (tmp_path / gate.FAMILY / "ordinary" / "foreign-original.json").write_bytes(b"{}")
    else:
        path = {"input-bytes": tmp_path / gate.FAMILY / "ordinary" / gate.PACKET,
                "observation-bytes": tmp_path / gate.OBSERVATIONS / "ordinary" / "final-observation.json",
                "proof-bytes": execution / "IO.json", "receipt-bytes": execution / "reader-custody.json",
                "result-bytes": execution / "I.result.json"}[attack]
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(gate.RemainderOriginalRefusal):
        gate.require_remainder_original_binding(tmp_path, proof, case="ordinary", require_restore=True)


def test_case_and_restore_switches_do_not_reuse_another_qualified_cohort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    family(tmp_path, restore=True)
    simulated(monkeypatch, tmp_path, restore=True)
    proof = gate.verify_remainder_original_rows(tmp_path, case="ordinary", require_restore=True)
    for case, restore in (("zero", True), ("ordinary", False), (True, True)):
        with pytest.raises(gate.RemainderOriginalRefusal):
            gate.require_remainder_original_binding(tmp_path, proof, case=case, require_restore=restore)


def test_existing_execution_ancestor_reparse_point_is_refused_before_creating_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    family(tmp_path)
    parent = tmp_path / gate.EXECUTIONS
    parent.mkdir()
    original = Path.lstat

    def lstat(path: Path) -> Any:
        result = original(path)
        if path != parent:
            return result
        # PosixPath.is_symlink reads st_mode before the Windows attribute
        # guard. Preserve the real stat contract on both operating systems.
        fields = {name: getattr(result, name) for name in dir(result) if name.startswith("st_")}
        fields["st_file_attributes"] = getattr(result, "st_file_attributes", 0) | gate.stat.FILE_ATTRIBUTE_REPARSE_POINT
        return SimpleNamespace(**fields)

    monkeypatch.setattr(Path, "lstat", lstat)
    assert not gate.stat.S_ISLNK(lstat(parent).st_mode)
    with pytest.raises(gate.RemainderOriginalRefusal):
        gate.verify_remainder_original_rows(tmp_path, case="ordinary", require_restore=False)
    assert list(parent.iterdir()) == []
