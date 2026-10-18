"""Custody boundary tests; mocked snapshots are never native financial proof."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tests import customer_partial_return_remainder_browser as observer


def tables(version: int, audit: int = 0) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {name: [] for name in observer.TABLES}
    result["customer_partial_return_history"] = [f'{{"id":"original-{number}"}}' for number in range(version)]
    result["domain_audit_events"] = [f'{{"id":"audit-{number:03}"}}' for number in range(audit)]
    result["domain_audit_ledger_state"] = [f'{{"version":{audit}}}']
    return result


def current(version: int, audit: int = 0) -> tuple[int, dict[str, list[str]], dict[str, Any] | None]:
    return version, tables(version, audit), ({"sequence": version, "plan_id": "CR2-" + f"{version:032x}",
        "plan_digest": "a" * 64, "phase": 2} if version else None)


def runtime(dsn: str = "original") -> Any:
    return SimpleNamespace(tenant="synthetic", factory=SimpleNamespace(settings=SimpleNamespace(dsn=dsn)))


def audit_only(before: dict[str, list[str]], after: dict[str, list[str]], tenant: str) -> None:
    assert tenant == "synthetic"
    assert {key: value for key, value in before.items() if key not in {"domain_audit_events", "domain_audit_ledger_state"}} == {
        key: value for key, value in after.items() if key not in {"domain_audit_events", "domain_audit_ledger_state"}}


def capture(root: Path, case: str, version: int) -> dict[str, Any]:
    return observer.capture_remainder_browser(runtime(), "stock-original", root, case=case,
        posted_plan_id="CR2-" + f"{version:032x}" if version else None, plan_digest="a" * 64 if version else None)


@pytest.mark.parametrize("case", ["ordinary", "zero", "refund"])
def test_private_economic_capture_replay_final_observation_and_restore_contract(case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / observer.FAMILY / case
    state = {"version": 0, "audit": 0}
    monkeypatch.setattr(observer, "_snapshot", lambda *args: current(state["version"], state["audit"]))
    monkeypatch.setattr(observer, "_audit", audit_only)
    for version in range(observer.EVENTS[case] + 1):
        state["version"] = version
        capture(root, case, version)
        if version == observer.REPLAY[case]:
            original = (root / f"committed-capture-{version}.json").read_bytes()
            state["audit"] = 2
            capture(root, case, version)
            assert (root / f"committed-capture-{version}.json").read_bytes() == original
    packet = observer.assemble_remainder_browser(root, case=case, tenant="synthetic", source="stock-original")
    assert set(packet) == {"schema_version", "case", "tenant_id", "source_order_id", "captures"}
    assert packet["case"] == case and len(packet["captures"]) == observer.EVENTS[case] + 1
    assert all(set(value) == observer.CAPTURE_FIELDS and set(value["tables"]) == set(observer.TABLES) for value in packet["captures"])
    assert packet["captures"] == [observer._load(root / f"committed-capture-{n}.json", case=case)
                                  for n in range(observer.EVENTS[case] + 1)]
    state["audit"] = 3
    original_proof = observer.verify_remainder_browser(runtime(), custody_root=root, source="stock-original", case=case, original_app_dsn="original")
    repeated = observer.verify_remainder_browser(runtime(), custody_root=root, source="stock-original", case=case, original_app_dsn="original")
    restored = observer.verify_remainder_browser(runtime("restored"), custody_root=root, source="stock-original", case=case, original_app_dsn="original")
    assert original_proof == repeated == restored
    assert len(original_proof["tables"]) == 79 and not original_proof["raw_financial_rows_published"]
    restored_packet = observer.parse_json_document((root / observer.RESTORE).read_text(encoding="utf-8"), reject_fractional_numbers=True)
    assert restored_packet == {"schema_version": "customer-partial-return-remainder-posted-restored-input-v1", "case": case,
        "tenant_id": "synthetic", "source_order_id": "stock-original", "tables": tables(observer.EVENTS[case], 3)}
    observations = tmp_path / observer.OBSERVATIONS / case
    assert {path.name for path in observations.iterdir()} == {f"retained-replay-{observer.REPLAY[case]}.json", "final-observation.json", observer.OBSERVATION_PACKET}
    assert {path.name for path in root.iterdir()} == {observer.PACKET, observer.RESTORE, *(f"committed-capture-{n}.json" for n in range(observer.EVENTS[case] + 1))}


def test_refused_full79_observation_is_private_and_original_economic_bytes_never_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / observer.FAMILY / "ordinary"
    state = {"version": 0}
    monkeypatch.setattr(observer, "_snapshot", lambda *args: current(state["version"]))
    capture(root, "ordinary", 0)
    state["version"] = 1
    capture(root, "ordinary", 1)
    original = (root / "committed-capture-1.json").read_bytes()
    changed = current(1)
    changed[1]["finance_entry_lines"] = ['{"original":"changed"}']
    monkeypatch.setattr(observer, "_snapshot", lambda *args: changed)
    def refused(*args: Any) -> None:
        raise ValueError("Synthetic independent refusal")
    monkeypatch.setattr(observer, "_audit", refused)
    with pytest.raises(ValueError):
        capture(root, "ordinary", 1)
    assert (root / "committed-capture-1.json").read_bytes() == original
    paths = list((tmp_path / observer.REFUSED / "ordinary").iterdir())
    assert len(paths) == 1
    failure = cast(dict[str, Any], observer.parse_json_document(paths[0].read_text(encoding="utf-8"), reject_fractional_numbers=True))
    assert failure["candidate"]["tables"] == changed[1] and len(failure["candidate"]["tables"]) == 79
    assert failure["reason_code"] == "audit_only_transition_refused"


@pytest.mark.parametrize("variant", ["missing", "extra", "duplicate", "unsorted", "decoded", "float"])
def test_exact79_membership_and_opaque_ordered_original_text_is_required(variant: str) -> None:
    value: dict[str, Any] = deepcopy(tables(1))
    if variant == "missing":
        del value["customer_partial_return_allocation_witnesses"]
    elif variant == "extra":
        value["unknown_private_table"] = []
    elif variant == "duplicate":
        value["finance_entry_lines"] = ['{"id":"a"}', '{"id":"a"}']
    elif variant == "unsorted":
        value["finance_entry_lines"] = ['{"id":"b"}', '{"id":"a"}']
    elif variant == "decoded":
        value["finance_entry_lines"] = [{"value_minor": 1}]
    else:
        value["finance_entry_lines"] = [1.0]
    with pytest.raises(ValueError):
        observer._tables(value)


@pytest.mark.parametrize("variant", ["extra-file", "gap", "wrong-family", "wrong-case", "relative", "symlink"])
def test_owned_finite_family_and_contiguous_capture_boundary(variant: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / observer.FAMILY / "ordinary"
    monkeypatch.setattr(observer, "_snapshot", lambda *args: current(0))
    capture(root, "ordinary", 0)
    if variant == "extra-file":
        (root / "raw-secret.json").write_text("private", encoding="utf-8")
    elif variant == "gap":
        (root / "committed-capture-2.json").write_bytes((root / "committed-capture-0.json").read_bytes())
    elif variant == "wrong-family":
        root = tmp_path / "unowned" / "ordinary"
    elif variant == "wrong-case":
        root = tmp_path / observer.FAMILY / "unknown"
    elif variant == "relative":
        root = Path(observer.FAMILY) / "ordinary"
    else:
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == root or original(self))
    with pytest.raises(ValueError):
        capture(root, "ordinary", 0)
