"""Reader publication custody. Mocked successful results are never native proof."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests import customer_partial_return_browser_reader as gate


def family(private: Path, *, restore: bool = False) -> Path:
    root = private / gate.FAMILY
    root.mkdir()
    tables: dict[str, list[str]] = {name: [] for name in gate.TABLES}
    # Opaque synthetic observation, deliberately NOT a postable native fixture.
    tables["domain_audit_events"] = ['{"private_observation":"PRIVATE_FINANCE"}']
    captures = []
    for number, name in enumerate(gate.CAPTURES):
        value = {"schema_version": "customer-partial-return-browser-capture-v1", "tenant_id": "private-tenant",
                 "source_order_id": "private-stock", "history_version": number,
                 "posted_plan_id": "plan-" + str(number) if number else None,
                 "plan_digest": "d" * 64 if number else None, "tables": tables}
        (root / name).write_bytes(gate._encode(value))
        captures.append(tables)
    packet = {"schema_version": "customer-partial-return-posted-cycle-input-v1", "tenant_id": "private-tenant",
              "source_order_id": "private-stock", "captures": captures}
    (root / gate.PACKET).write_bytes(gate._encode(packet))
    folder = private / gate.OBSERVATIONS
    folder.mkdir()
    observations = []
    for name, kind, version in gate.OBSERVATION_FILES:
        observation = {"schema_version": "customer-partial-return-browser-observation-v1", "kind": kind,
                       "tenant_id": "private-tenant", "source_order_id": "private-stock", "history_version": version,
                       "posted_plan_id": "plan-" + str(version), "plan_digest": "d" * 64, "tables": tables}
        observations.append(observation)
        (folder / name).write_bytes(gate._encode(observation))
    (folder / gate.OBSERVATIONS_PACKET).write_bytes(gate._encode({
        "schema_version": "customer-partial-return-posted-observations-input-v1", "tenant_id": "private-tenant",
        "source_order_id": "private-stock", "observations": observations}))
    if restore:
        restored = {"schema_version": "customer-partial-return-posted-restore-input-v1", "tenant_id": "private-tenant",
                    "source_order_id": "private-stock", "capture": tables}
        (root / gate.RESTORE).write_bytes(gate._encode(restored))
    return root


def simulated_reader(monkeypatch: pytest.MonkeyPatch, *, patch: dict[str, Any] | None = None,
                     mutate: Callable[[list[str], dict[str, Any]], None] | None = None) -> list[list[str]]:
    calls = []
    def run(argv: list[str], **options: Any) -> Any:
        calls.append(argv)
        assert options["check"] is False and options["timeout"] == 60 and options["stdin"] == gate.subprocess.DEVNULL
        assert "RECONFORGE_ERP_PASSWORD" not in options["env"] and "RECONFORGE_GFO_APP_DSN" not in options["env"]
        private = Path(argv[argv.index("--input") + 1]).parents[1]
        inputs = gate._family(private, require_restore="--restore-input" in argv)
        proof = {**deepcopy(gate.EXPECTED_PROOF), "input_sha256": inputs["input_sha256"], "oracle_source_sha256": gate.READER_SHA256,
                 "observations_input_sha256": inputs["observations_input_sha256"], "observation_audit_appended_events": 17}
        if inputs["require_restore"]:
            proof.update(populated_restore_original_rows_equal=True, restored_tables=78, restored_rows=inputs["final_rows"],
                         restore_input_sha256=inputs["restore_input_sha256"], restore_uses_final_observation=True)
        if patch:
            proof.update(deepcopy(patch))
        output = Path(argv[argv.index("--output") + 1])
        output.write_bytes(gate._encode(proof))
        if mutate:
            mutate(argv, options)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(gate.subprocess, "run", run)
    return calls


def execute(private: Path, monkeypatch: pytest.MonkeyPatch, *, restore: bool = False) -> dict[str, Any]:
    family(private, restore=restore)
    simulated_reader(monkeypatch)
    return gate.verify_customer_partial_return_original_rows(private, require_restore=restore)


@pytest.mark.parametrize("restore", [False, True])
def test_simulated_complete_i_io_binding_exposes_only_closed_verified_counts_and_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restore: bool) -> None:
    family(tmp_path, restore=restore)
    monkeypatch.setenv("RECONFORGE_ERP_PASSWORD", "SECRET_PASSWORD")
    calls = simulated_reader(monkeypatch)
    verified = gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=restore)
    gate.require_customer_partial_return_original_binding(tmp_path, verified)
    assert calls[0][1] == "-I" and calls[1][1:3] == ["-I", "-O"]
    assert verified["final_actual_posting_effects"] == 17 and verified["final_actual_posted_lines"] == 35
    assert verified["final_total_debit_minor"] == verified["final_total_credit_minor"] == 385000
    assert verified["restored"] is restore
    assert not any(value in gate._encode(verified) for value in (b"PRIVATE_FINANCE", b"private-stock", b"private-tenant", b"SECRET_PASSWORD", str(tmp_path).encode()))
    assert len(list((tmp_path / gate.EXECUTIONS).iterdir())) == 1


@pytest.mark.parametrize("patch", [
    {"events": True}, {"captures": 8}, {"events": 7}, {"new_actual_posting_effects": 11}, {"new_actual_posted_lines": 24},
    {"final_actual_posting_effects": 16}, {"final_actual_posted_entries": 16}, {"final_actual_posted_lines": 34},
    {"final_total_debit_minor": 384999}, {"final_total_credit_minor": "385000"}, {"returned_quantity_scaled": 14},
    {"receivable_minor": 1}, {"refund_liability_minor": 1}, {"original_consumptions_unchanged": 1},
    {"incremental_gl_fifo_layer_history_equal": False}, {"raw_financial_rows": "SECRET_PASSWORD"},
    {"final_account_minor_balances": {**gate.EXPECTED_ACCOUNTS, "INVENTORY": 31999}},
    {"oracle_source_sha256": "f" * 64}, {"input_sha256": "e" * 64},
    {"observations": True}, {"retained_replay_observations": 1}, {"final_read_observations": 0},
    {"observation_business_original_rows_equal": False}, {"observation_audit_prefix_original_bytes_equal": False},
    {"observation_audit_chain_valid": False}, {"observation_audit_actions_bound": False},
    {"observation_audit_chronology_valid": False},
    {"observation_audit_appended_events": True}, {"observation_audit_appended_events": 0},
    {"observation_audit_appended_events": 12289}, {"observations_input_sha256": "f" * 64},
])
def test_wrong_cohort_typed_totals_or_extra_data_never_becomes_a_published_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, patch: dict[str, Any]) -> None:
    family(tmp_path)
    simulated_reader(monkeypatch, patch=patch)
    with pytest.raises(gate.CustomerPartialReturnOriginalRefusal):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=False)


@pytest.mark.parametrize("change", ["unknown", "missing", "capture_drift", "packet_drift", "tenant_swap", "boolean_version", "missing_table", "extra_table", "duplicate_key", "fraction", "restore_drift"])
def test_missing_extra_malformed_or_unjoined_originals_refuse_before_any_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    root = family(tmp_path, restore=change == "restore_drift")
    if change == "unknown":
        (root / "unknown.json").write_bytes(b"private")
    elif change == "missing":
        (root / gate.CAPTURES[-1]).unlink()
    elif change == "packet_drift":
        packet = gate._decode((root / gate.PACKET).read_bytes())
        packet["captures"][-1]["finance_accounts"] = ["unjoined-private-original"]
        (root / gate.PACKET).write_bytes(gate._encode(packet))
    elif change == "restore_drift":
        value = gate._decode((root / gate.RESTORE).read_bytes())
        value["capture"]["finance_accounts"] = ["unjoined-restored-private-original"]
        (root / gate.RESTORE).write_bytes(gate._encode(value))
    else:
        path = root / gate.CAPTURES[-1]
        value = gate._decode(path.read_bytes())
        if change == "capture_drift":
            value["tables"]["finance_accounts"] = ["unjoined-private-original"]
        elif change == "tenant_swap":
            value["tenant_id"] = "foreign"
        elif change == "boolean_version":
            value["history_version"] = True
        elif change == "missing_table":
            value["tables"].pop("finance_accounts")
        elif change == "extra_table":
            value["tables"]["unowned"] = []
        original = gate._encode(value)
        if change == "duplicate_key":
            original = original.replace(b'"history_version":8', b'"history_version":8,"history_version":8')
        elif change == "fraction":
            original = original.replace(b'"history_version":8', b'"history_version":8.0')
        path.write_bytes(original)
    monkeypatch.setattr(gate.subprocess, "run", lambda *_args, **_options: pytest.fail("Malformed original reached a reader"))
    with pytest.raises(ValueError):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=change == "restore_drift")


@pytest.mark.parametrize("which", ["I.json", "IO.json", "I.stdout", "IO.stderr", "I.result.json", "reader-custody.json", "capture", "packet", "restore"])
def test_late_mutation_or_deletion_of_either_proof_stream_receipt_or_input_refuses_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, which: str) -> None:
    verified = execute(tmp_path, monkeypatch, restore=True)
    execution = next((tmp_path / gate.EXECUTIONS).iterdir())
    path = {"capture": tmp_path / gate.FAMILY / gate.CAPTURES[4], "packet": tmp_path / gate.FAMILY / gate.PACKET,
            "restore": tmp_path / gate.FAMILY / gate.RESTORE}.get(which, execution / which)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        gate.require_customer_partial_return_original_binding(tmp_path, verified)
    path.unlink()
    with pytest.raises(ValueError):
        gate.require_customer_partial_return_original_binding(tmp_path, verified)


def test_source_drift_before_or_after_reader_refuses_binding_without_editing_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "pinned-reader.py"
    source.write_bytes(gate.READER.read_bytes())
    monkeypatch.setattr(gate, "READER", source)
    verified = execute(tmp_path, monkeypatch)
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        gate.require_customer_partial_return_original_binding(tmp_path, verified)


def test_i_io_semantically_equal_but_byte_different_outputs_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    family(tmp_path)
    def drift(argv: list[str], _options: dict[str, Any]) -> None:
        output = Path(argv[argv.index("--output") + 1])
        if "-O" in argv:
            output.write_bytes(output.read_bytes() + b"\n")
    simulated_reader(monkeypatch, mutate=drift)
    with pytest.raises(ValueError):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=False)


def test_first_mode_output_changed_after_second_execution_cannot_evade_final_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    family(tmp_path)
    def drift(argv: list[str], _options: dict[str, Any]) -> None:
        if "-O" in argv:
            first = Path(argv[argv.index("--output") + 1]).with_name("I.json")
            first.write_bytes(first.read_bytes() + b"\n")
    simulated_reader(monkeypatch, mutate=drift)
    with pytest.raises(ValueError):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=False)


def test_original_input_changed_between_modes_is_refused_and_never_refreshed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = family(tmp_path)
    original = (root / gate.CAPTURES[1]).read_bytes()
    def drift(_argv: list[str], _options: dict[str, Any]) -> None:
        (root / gate.CAPTURES[1]).write_bytes(original + b"\n")
    simulated_reader(monkeypatch, mutate=drift)
    with pytest.raises(ValueError):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=False)
    assert (root / gate.CAPTURES[1]).read_bytes() == original + b"\n"


def test_successful_reader_stdout_is_private_and_disqualifies_unexpected_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    family(tmp_path)
    simulated_reader(monkeypatch, mutate=lambda _argv, options: options["stdout"].write(b"SECRET_PASSWORD"))
    with pytest.raises(ValueError):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=False)
    execution = next((tmp_path / gate.EXECUTIONS).iterdir())
    assert (execution / "I.stdout").read_bytes() == b"SECRET_PASSWORD"


@pytest.mark.parametrize("kind", ["is_symlink", "is_junction"])
def test_classified_linked_input_and_execution_storage_refuses_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    verified = execute(tmp_path, monkeypatch)
    target = tmp_path / gate.FAMILY / gate.CAPTURES[0]
    original = getattr(Path, kind, lambda _: False)
    monkeypatch.setattr(Path, kind, lambda path: path == target or original(path), raising=False)
    with pytest.raises(ValueError):
        gate.require_customer_partial_return_original_binding(tmp_path, verified)


def test_extra_execution_original_or_malformed_public_projection_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    verified = execute(tmp_path, monkeypatch)
    for patch in ({"raw_financial_rows": "SECRET_PASSWORD"}, {"final_actual_posting_effects": True}, {"restored": 0}):
        with pytest.raises(ValueError):
            gate.require_customer_partial_return_original_binding(tmp_path, {**verified, **patch})
    execution = next((tmp_path / gate.EXECUTIONS).iterdir())
    (execution / "unclassified-original.json").write_bytes(b"private")
    with pytest.raises(ValueError):
        gate.require_customer_partial_return_original_binding(tmp_path, verified)


def test_fresh_execution_family_cannot_be_reused_or_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    execute(tmp_path, monkeypatch)
    before = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(ValueError):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=False)
    assert {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


def test_actual_isolated_reader_refuses_unposted_opaque_packet_and_retains_original_stdout(tmp_path: Path) -> None:
    root = family(tmp_path)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(ValueError):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=False)
    execution = next((tmp_path / gate.EXECUTIONS).iterdir())
    assert (execution / "I.stdout").read_bytes().splitlines() == [b"Independent posted-cycle qualification refused."]
    assert not (execution / "IO.result.json").exists()
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before


@pytest.mark.parametrize("change", ["missing_folder", "extra", "missing", "schema", "kind", "version", "source", "plan", "unjoined", "tables"])
def test_observation_original_family_and_exact_sidecar_join_refuse_before_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    family(tmp_path)
    folder = tmp_path / gate.OBSERVATIONS
    path = folder / gate.OBSERVATION_FILES[0][0]
    if change == "missing_folder":
        folder.rename(tmp_path / "different-observation-root")
    elif change == "extra":
        (folder / "unknown.json").write_bytes(b"private")
    elif change == "missing":
        path.unlink()
    else:
        value = gate._decode(path.read_bytes())
        if change == "schema":
            value["secret"] = "private-extra"
        elif change == "kind":
            value["kind"] = "FinalRead"
        elif change == "version":
            value["history_version"] = True
        elif change == "source":
            value["source_order_id"] = "foreign"
        elif change == "plan":
            value["posted_plan_id"] = "foreign"
        elif change == "tables":
            value["tables"].pop(gate.TABLES[0])
        else:
            value["tables"]["finance_entry_lines"] = ["unjoined-original"]
        path.write_bytes(gate._encode(value))
    monkeypatch.setattr(gate.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("No reader after malformed original join"))
    with pytest.raises((ValueError, FileNotFoundError)):
        gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=False)
    assert not (tmp_path / gate.EXECUTIONS).exists()


@pytest.mark.parametrize("name", [item[0] for item in gate.OBSERVATION_FILES] + [gate.OBSERVATIONS_PACKET])
def test_late_observation_bytes_drift_blocks_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    verified = execute(tmp_path, monkeypatch)
    path = tmp_path / gate.OBSERVATIONS / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        gate.require_customer_partial_return_original_binding(tmp_path, verified)


def test_restore_is_bound_to_full_final_observation_including_new_audit_originals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    family(tmp_path, restore=True)
    folder = tmp_path / gate.OBSERVATIONS
    final_path = folder / "final-observation.json"
    final = gate._decode(final_path.read_bytes())
    final["tables"]["domain_audit_events"].append('{"later_private_audit":"preserved"}')
    final["tables"]["domain_audit_events"].sort()
    final_path.write_bytes(gate._encode(final))
    packet_path = folder / gate.OBSERVATIONS_PACKET
    packet = gate._decode(packet_path.read_bytes())
    packet["observations"][-1] = final
    packet_path.write_bytes(gate._encode(packet))
    restored_path = tmp_path / gate.FAMILY / gate.RESTORE
    restored = gate._decode(restored_path.read_bytes())
    with pytest.raises(ValueError):
        gate._family(tmp_path, require_restore=True)
    restored["capture"] = final["tables"]
    restored_path.write_bytes(gate._encode(restored))
    simulated_reader(monkeypatch)
    verified = gate.verify_customer_partial_return_original_rows(tmp_path, require_restore=True)
    assert verified["restore_uses_final_observation"] is True and verified["restored_rows"] == 2
