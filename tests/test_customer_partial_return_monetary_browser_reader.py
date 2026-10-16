"""Custody components only; empty synthetic rows never prove a posted cycle."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from tests import customer_partial_return_monetary_browser_reader as reader


def family(private: Path, *, case: str = "identity", restore: bool = True) -> tuple[Path, Path]:
    data, observations = private / reader.FAMILY / case, private / reader.OBSERVATIONS / case
    data.mkdir(parents=True)
    observations.mkdir(parents=True)
    tables = {name: [] for name in reader.TABLES}
    captures = [{"capture": index, "tables": deepcopy(tables)} for index in range(len(reader.VERSIONS[case]))]
    for capture in captures:
        (data / f"committed-capture-{capture['capture']}.json").write_bytes(reader._encode(capture))
    (data / reader.PACKET).write_bytes(reader._encode({"schema_version": "customer-partial-return-monetary-posted-cycle-input-v1", "tenant_id": "synthetic", "source_order_id": "source", "captures": captures}))
    kinds = [("RetainedReplay", "retained-replay.json"), ("ScopeRefusal", "scope-refusal.json"), ("FinalRead", "final-observation.json")]
    if case == "foreign":
        kinds.insert(0, ("ActiveValuationRefusal", "active-valuation-refusal.json"))
    values = []
    for kind, name in kinds:
        index = 5 if kind == "ActiveValuationRefusal" else len(captures) - (3 if kind == "RetainedReplay" else 1)
        pinned = kind in {"RetainedReplay", "ActiveValuationRefusal"}
        refusal = {"operation": "PrepareReturn", "status": 409, "code": "monetary_return_state_conflict"} if kind == "ActiveValuationRefusal" else {"operation": "ReadSource", "status": 403, "code": "scope_denied"} if kind == "ScopeRefusal" else None
        value = {"schema_version": "customer-partial-return-monetary-browser-observation-v1", "kind": kind, "tenant_id": "synthetic", "source_order_id": "source",
                 "capture": index, "history_version": reader.VERSIONS[case][index], "plan_id": ("FX1-" if kind == "ActiveValuationRefusal" else "CRF3-") + "1" * 32 if pinned else None,
                 "plan_digest": "a" * 64 if pinned else None, "tables": deepcopy(tables), "refusal": refusal}
        (observations / name).write_bytes(reader._encode(value))
        values.append(value)
    (observations / reader.OBSERVATION_PACKET).write_bytes(reader._encode({"schema_version": "customer-partial-return-monetary-posted-observations-input-v1", "tenant_id": "synthetic", "source_order_id": "source", "observations": values}))
    if case == "foreign":
        (observations / reader.REFUSED_REQUEST).write_bytes(reader._encode({"method": "POST", "route": "/api/v3/customer-partial-returns/plans", "body": {
            "command_id": "synthetic", "source_order_id": "source", "quantity_scaled": "4", "period_id": "period", "posting_date": "2026-10-15", "reason": "Known active source valuation", "expected_history_version": 2}}))
    if restore:
        (data / reader.RESTORE).write_bytes(reader._encode({"schema_version": "customer-partial-return-monetary-posted-restored-input-v1", "tenant_id": "synthetic", "source_order_id": "source", "tables": deepcopy(tables)}))
    return data, observations


@pytest.mark.parametrize("case", ["identity", "foreign"])
@pytest.mark.parametrize("restore", [False, True])
def test_closed_family_binds_exact_captures_observations_request_and_restore_without_financial_claim(tmp_path: Path, case: str, restore: bool) -> None:
    family(tmp_path, case=case, restore=restore)
    value = reader._family(tmp_path, case=case, require_restore=restore)
    assert value["case"] == case and value["require_restore"] is restore
    assert value["source"]["sha256"] == reader.READER_SHA256
    assert "status" not in value and "posted_journals_bound" not in value


@pytest.mark.parametrize("mutation", ["extra", "missing", "main-drift", "capture-bool", "observation-drift", "restore-drift", "other-case", "failed-observation"])
def test_family_membership_and_exact_byte_join_refuse_drift(tmp_path: Path, mutation: str) -> None:
    data, observations = family(tmp_path)
    if mutation == "extra":
        (data / "other.json").write_bytes(b"{}")
    elif mutation == "missing":
        (data / "committed-capture-1.json").unlink()
    elif mutation == "main-drift":
        (data / "committed-capture-1.json").write_bytes(reader._encode({"capture": 1, "tables": {}}))
    elif mutation == "capture-bool":
        packet = reader._decode((data / reader.PACKET).read_bytes())
        packet["captures"][0]["capture"] = False
        (data / reader.PACKET).write_bytes(reader._encode(packet))
    elif mutation == "observation-drift":
        value = reader._decode((observations / "scope-refusal.json").read_bytes())
        value["refusal"]["status"] = True
        (observations / "scope-refusal.json").write_bytes(reader._encode(value))
    elif mutation == "restore-drift":
        restored = reader._decode((data / reader.RESTORE).read_bytes())
        restored["tables"]["ar_invoices"].append('{"tenant_id":"synthetic","id":"changed"}')
        (data / reader.RESTORE).write_bytes(reader._encode(restored))
    elif mutation == "other-case":
        (data.parent / "foreign").mkdir()
    else:
        (tmp_path / "native-customer-partial-return-monetary-failed-observation-originals").mkdir()
    with pytest.raises(ValueError):
        reader._family(tmp_path, case="identity", require_restore=True)


@pytest.mark.parametrize("change", [{"quantity_scaled": "5"}, {"expected_history_version": True}, {"source_order_id": "other"}, {"allocation_policy": "override"}])
def test_actual_refusal_request_cannot_be_reinterpreted_as_other_intent(tmp_path: Path, change: dict[str, Any]) -> None:
    _data, observations = family(tmp_path, case="foreign")
    path = observations / reader.REFUSED_REQUEST
    value = reader._decode(path.read_bytes())
    value["body"].update(change)
    path.write_bytes(reader._encode(value))
    with pytest.raises(ValueError):
        reader._family(tmp_path, case="foreign", require_restore=True)


def test_source_pin_mismatch_refuses_before_starting_an_independent_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    family(tmp_path)
    monkeypatch.setattr(reader, "READER_SHA256", "f" * 64)
    with pytest.raises(ValueError):
        reader.verify_monetary_original_rows(tmp_path, case="identity", require_restore=True)
    assert not (tmp_path / reader.EXECUTIONS).exists()


def test_source_tree_symlink_classification_refuses_before_any_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data, _observations = family(tmp_path)
    target = data / reader.PACKET
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(ValueError):
        reader.verify_monetary_original_rows(tmp_path, case="identity", require_restore=True)
    assert not (tmp_path / reader.EXECUTIONS).exists()


def test_empty_raw_foundation_can_never_become_financial_success_and_originals_stay_private(tmp_path: Path) -> None:
    family(tmp_path)
    before = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*.json")}
    with pytest.raises((ValueError, OSError)):
        reader.verify_monetary_original_rows(tmp_path, case="identity", require_restore=True)
    assert all((tmp_path / name).read_bytes() == value for name, value in before.items())
    executions = list((tmp_path / reader.EXECUTIONS).iterdir())
    assert len(executions) == 1 and (executions[0] / "I.result.json").is_file()
    assert not (executions[0] / "reader-custody.json").exists()


def test_partial_or_metadata_only_core_proof_has_no_acceptance_path() -> None:
    with pytest.raises(ValueError):
        reader._proof(reader._encode({"status": "passed", "tables": 91, "captures": 10}), {})
