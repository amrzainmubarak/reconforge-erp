"""Private fourth-cohort binding controls; synthetic rows are never native proof."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests import customer_partial_return_restituted_browser_reader as gate
from tests.test_customer_partial_return_restituted_cycle_oracle import observations_fixture


def family(private: Path, *, restore: bool = False) -> Path:
    packet, observations, restored = observations_fixture()
    root = private / gate.FAMILY
    root.mkdir(parents=True)
    for number, value in enumerate(packet["captures"]):
        (root / f"checkpoint-{number}.json").write_bytes(gate._encode(value))
    (root / gate.PACKET).write_bytes(gate._encode(packet))
    folder = private / gate.OBSERVATIONS
    folder.mkdir()
    for value in observations["observations"]:
        (folder / (value["kind"] + ".json")).write_bytes(gate._encode(value))
    (folder / gate.OBSERVATIONS_PACKET).write_bytes(gate._encode(observations))
    if restore:
        (root / gate.RESTORE).write_bytes(gate._encode(restored))
    return root


def simulated(monkeypatch: pytest.MonkeyPatch, private: Path, *, restore: bool = False,
              patch: dict[str, Any] | None = None, mode: str = "success") -> list[list[str]]:
    calls = []
    def run(argv: list[str], **options: Any) -> Any:
        calls.append(argv)
        assert options["check"] is False and options["timeout"] == 60 and options["stdin"] == gate.subprocess.DEVNULL
        assert not {"RECONFORGE_GFO_APP_DSN", "RECONFORGE_ERP_PASSWORD", "PYTHONPATH"} & set(options["env"])
        if mode == "timeout":
            raise gate.subprocess.TimeoutExpired(argv, 60)
        if mode == "launch":
            raise OSError("private error detail must remain private")
        if mode == "nonzero":
            return SimpleNamespace(returncode=2)
        proof = gate._expected(gate._family(private, require_restore=restore), 3, "a" * 64)
        if patch:
            proof.update(copy.deepcopy(patch))
        output = Path(argv[argv.index("--output") + 1])
        output.write_bytes(json.dumps(proof, indent=2).encode() if mode == "io-drift" and "-O" in argv else gate._encode(proof))
        if mode == "input-drift":
            path = private / gate.FAMILY / "checkpoint-0.json"
            path.write_bytes(path.read_bytes() + b" ")
        if mode == "stderr":
            options["stderr"].write(b"private raw output")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(gate.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("restore", [False, True])
def test_actual_isolated_c_reader_binds_synthetic_checkpoint_and_full_restore_originals(tmp_path: Path, restore: bool) -> None:
    family(tmp_path, restore=restore)
    proof = gate.verify_restituted_original_rows(tmp_path, require_restore=restore)
    gate.require_restituted_original_binding(tmp_path, proof, require_restore=restore)
    assert proof["restored"] is restore and proof["checkpoints"] == 4 and proof["observations"] == 3
    assert proof["isolated_modes_byte_equal"] and proof["dependency_refusal_http_proven"]
    assert proof["final_actual_posting_effects"] == 5 and proof["final_actual_posted_lines"] == 10
    assert proof["final_debits_minor"] == proof["final_credits_minor"] == 203
    assert not proof["raw_financial_rows_published"] and not proof["current_authorization_proven"]
    public = gate._encode(proof)
    assert all(value not in public for value in (str(tmp_path).encode(), b'"tenant"', b'"old-stock"', b'"resale"', b'"CR2-'))
    with pytest.raises(gate.RestitutedOriginalRefusal):
        gate.verify_restituted_original_rows(tmp_path, require_restore=restore)


@pytest.mark.parametrize("patch", [
    {"checkpoints": True}, {"checkpoints": 3}, {"tables": 78}, {"sources": 1}, {"governed_returns": 3},
    {"final_debits_minor": "203"}, {"final_credits_minor": 202}, {"final_actual_posting_effects": 6},
    {"final_actual_posted_lines": 11}, {"no_fake_zero_financial_entries": False}, {"resale_original_cogs_absent": False},
    {"dependency_refusal_http_proven": False}, {"current_authorization_proven": True}, {"benchmark": True},
    {"appended_audit_events": True}, {"appended_audit_events": 1}, {"appended_audit_events": 8193},
    {"observation_chronology_bound": False}, {"business_original_rows_equal": False}, {"audit_chain_valid": False},
    {"original_cost_admission": {}}, {"input_sha256": {}}, {"reader_source_sha256": {}}, {"raw_rows": "PRIVATE_FINANCE"},
])
def test_no_malformed_financial_or_raw_extra_child_proof_is_publishable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, patch: dict[str, Any]) -> None:
    family(tmp_path)
    simulated(monkeypatch, tmp_path, patch=patch)
    with pytest.raises(gate.RestitutedOriginalRefusal):
        gate.verify_restituted_original_rows(tmp_path, require_restore=False)


@pytest.mark.parametrize("attack", ["missing", "extra", "capture-order", "raw-map", "capture-drift", "foreign-source", "same-source",
    "missing-table", "extra-table", "duplicate-key", "fraction", "observation-order", "observation-drift", "refusal-status", "refusal-route", "restore-drift"])
def test_unjoined_foreign_or_malformed_families_refuse_before_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str) -> None:
    root = family(tmp_path, restore=True)
    if attack == "missing":
        (root / "checkpoint-3.json").unlink()
    elif attack == "extra":
        (root / "secret.json").write_bytes(b"{}")
    else:
        path = root / (gate.PACKET if attack in {"raw-map", "foreign-source", "same-source", "capture-order"} else gate.RESTORE if attack == "restore-drift" else "checkpoint-3.json")
        if attack.startswith("observation"):
            path = tmp_path / gate.OBSERVATIONS / gate.OBSERVATIONS_PACKET
        if attack.startswith("refusal"):
            path = tmp_path / gate.OBSERVATIONS / "DependencyRefusal.json"
        value = gate._decode(path.read_bytes())
        if attack == "capture-order":
            value["captures"].reverse()
        elif attack == "raw-map":
            value["captures"] = [row["tables"] for row in value["captures"]]
        elif attack == "capture-drift":
            value["tables"]["finance_accounts"] = []
        elif attack == "foreign-source":
            value["resale_source_order_id"] = "foreign"
        elif attack == "same-source":
            value["resale_source_order_id"] = value["original_source_order_id"]
        elif attack == "missing-table":
            value["tables"].pop("customer_partial_return_allocation_witnesses")
        elif attack == "extra-table":
            value["tables"]["unknown"] = []
        elif attack == "observation-order":
            value["observations"].reverse()
        elif attack == "observation-drift":
            value["observations"][1]["plan_digest"] = "e" * 64
        elif attack == "refusal-status":
            value["refusal"]["status"] = True
        elif attack == "refusal-route":
            value["refusal"]["route"] = "/api/v1/customer-returns/plans"
        elif attack == "restore-drift":
            value["tables"]["finance_accounts"] = []
        data = gate._encode(value)
        if attack == "duplicate-key":
            data = data.replace(b'"checkpoint":"ResaleReturned"', b'"checkpoint":"ResaleReturned","checkpoint":"ResaleReturned"')
        elif attack == "fraction":
            data = data.replace(b'"checkpoint":"ResaleReturned"', b'"checkpoint":1.5')
        path.write_bytes(data)
    calls = simulated(monkeypatch, tmp_path, restore=True)
    with pytest.raises((gate.RestitutedOriginalRefusal, ValueError)):
        gate.verify_restituted_original_rows(tmp_path, require_restore=True)
    assert calls == []


@pytest.mark.parametrize("mode", ["timeout", "launch", "nonzero", "io-drift", "input-drift", "stderr"])
def test_actual_child_failures_or_drift_never_retry_or_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    family(tmp_path)
    calls = simulated(monkeypatch, tmp_path, mode=mode)
    with pytest.raises(gate.RestitutedOriginalRefusal):
        gate.verify_restituted_original_rows(tmp_path, require_restore=False)
    assert len(calls) == (2 if mode == "io-drift" else 1)
    execution = next((tmp_path / gate.EXECUTIONS).iterdir())
    result = gate._decode((execution / "I.result.json").read_bytes())
    assert result["timed_out"] is (mode == "timeout") and result["launch_failed"] is (mode == "launch")
    assert (execution / "I.stdout").exists() and (execution / "I.stderr").exists()


@pytest.mark.parametrize("attack", ["input-bytes", "input-membership", "observation-bytes", "I-proof", "IO-proof", "receipt", "result",
    "source-pin", "public-projection", "extra-execution", "restore-switch"])
def test_postpublication_binding_refuses_every_changed_original_or_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str) -> None:
    family(tmp_path, restore=True)
    simulated(monkeypatch, tmp_path, restore=True)
    proof = gate.verify_restituted_original_rows(tmp_path, require_restore=True)
    execution = next((tmp_path / gate.EXECUTIONS).iterdir())
    if attack == "source-pin":
        monkeypatch.setitem(gate.SOURCE_HASHES, "customer_partial_return_restituted_source_oracle.py", "0" * 64)
    elif attack == "public-projection":
        proof["final_debits_minor"] = 0
    elif attack == "extra-execution":
        (execution / "unknown.json").write_bytes(b"{}")
    elif attack == "input-membership":
        (tmp_path / gate.FAMILY / "unknown.json").write_bytes(b"{}")
    elif attack != "restore-switch":
        path = {"input-bytes": tmp_path / gate.FAMILY / "checkpoint-3.json", "observation-bytes": tmp_path / gate.OBSERVATIONS / "FinalRead.json",
                "I-proof": execution / "I.json", "IO-proof": execution / "IO.json", "receipt": execution / "reader-custody.json", "result": execution / "IO.result.json"}[attack]
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(gate.RestitutedOriginalRefusal):
        gate.require_restituted_original_binding(tmp_path, proof, require_restore=attack != "restore-switch")


@pytest.mark.parametrize("target", ["raw", "observation", "execution"])
def test_reparse_ancestors_are_refused_without_traversing_or_creating_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    family(tmp_path)
    parent = tmp_path / {"raw": gate.FAMILY, "observation": gate.OBSERVATIONS, "execution": gate.EXECUTIONS}[target]
    parent.mkdir(exist_ok=True)
    original = Path.lstat
    def lstat(path: Path) -> Any:
        return SimpleNamespace(st_mode=original(path).st_mode, st_file_attributes=gate.stat.FILE_ATTRIBUTE_REPARSE_POINT) if path == parent else original(path)
    monkeypatch.setattr(Path, "lstat", lstat)
    calls = simulated(monkeypatch, tmp_path)
    with pytest.raises(gate.RestitutedOriginalRefusal):
        gate.verify_restituted_original_rows(tmp_path, require_restore=False)
    assert calls == []
