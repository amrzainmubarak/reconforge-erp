"""Independent file-only checks over byte-exact original synthetic native exports."""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/verify_manufacturing_v2_cycle_oracle.py"
spec = importlib.util.spec_from_file_location("independent_me2_oracle", SCRIPT)
assert spec is not None and spec.loader is not None
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
FIXTURE = ROOT / "tests/fixtures/manufacturing_v2_original_golden.json"
HOLD = ROOT / "tests/fixtures/manufacturing_v2_original_quality_hold.json"
FINAL_SHA = "3d421672eecd1b67724e91791eb2d7e9d83aec0ceecd337d89ae6ffa74748cb9"


def proof() -> dict[str, Any]:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FINAL_SHA
    return json.loads(raw)


def test_actual_original_material_expense_quality_and_native_gl_conserve_without_application_imports() -> None:
    value = oracle.verify_proof(proof())
    assert (value["issued_material_minor"], value["claimed_expense_minor"], value["total_cost_minor"]) == ("2900", "900", "3800")
    assert (value["finished_cost_minor"], value["abnormal_loss_minor"], value["remaining_wip_minor"]) == ("3420", "380", "0")
    assert value["native_positions_minor"]["LABOR"] == "1400" and value["native_positions_minor"]["OVERHEAD"] == "700"
    assert value["posting_effects"] == 9 and value["balanced_turnover_minor"] == "25933"
    assert value["performance_accepted"] is False and value["external_attestation"] is False
    assert "reconforge" not in SCRIPT.read_text(encoding="utf-8").split("import", 1)[-1].split("def require", 1)[0]


def test_actual_quality_hold_is_wip_and_has_no_native_saleable_finished_stock() -> None:
    value = oracle.verify_proof(json.loads(HOLD.read_bytes()))
    assert (value["held_quantity_scaled"], value["held_cost_minor"], value["remaining_wip_minor"]) == ("4", "1520", "3800")
    assert (value["finished_quantity_scaled"], value["finished_cost_minor"], value["abnormal_loss_minor"]) == ("0", "0", "0")
    assert value["posting_effects"] == 6


@pytest.mark.parametrize("table,key", [
    ("inventory_cost_layers", "original_value_minor"), ("inventory_cost_layers", "remaining_quantity_scaled"),
    ("finance_entries", "total_debit_minor"), ("manufacturing_execution_v2_cost_claims", "amount_minor"),
])
@pytest.mark.parametrize("malformed", [True, 1.0])
def test_exact_native_bigint_tokens_cannot_be_replaced_by_equal_python_numbers(table: str, key: str, malformed: Any) -> None:
    value = proof()
    original = value["populations"][table][0][key]
    value["populations"][table][0][key] = float(original) if type(malformed) is float else malformed
    with pytest.raises(ValueError, match="Exact bounded"):
        oracle.verify_proof(value)


@pytest.mark.parametrize("table,key", [
    ("inventory_cost_layers", "item_id"), ("inventory_cost_layers", "uom_id"),
    ("inventory_cost_layers", "workspace_id"), ("inventory_layer_consumptions", "valuation_line_id"),
    ("inventory_layer_consumptions", "workspace_id"),
])
def test_source_owned_native_fifo_custody_cannot_be_detached(table: str, key: str) -> None:
    value = proof()
    value["populations"][table][0][key] = "FOREIGN-ORIGINAL"
    with pytest.raises((ValueError, KeyError)):
        oracle.verify_proof(value)


def test_full_historical_ack_cannot_claim_a_different_cost_or_phase() -> None:
    value = proof()
    command = value["populations"]["manufacturing_execution_v2_commands"][0]
    command["response_json"]["phase"] = 999
    command["response_json"]["wip_minor"] = 999999999
    with pytest.raises(ValueError, match="historical"):
        oracle.verify_proof(value)


@pytest.mark.parametrize("field", ["id", "order_id", "production_id"])
def test_rehashed_inspection_payload_identity_cannot_hide_behind_native_projection_fields(field: str) -> None:
    value = proof()
    rows = value["populations"]
    row = rows["manufacturing_execution_v2_inspections"][0]
    row["payload"][field] = "ME2-FOREIGN-SOURCE"
    row["source_digest"] = oracle.sha(row["payload"])
    for command in rows["manufacturing_execution_v2_commands"]:
        if command["object_id"] == row["id"]:
            command["response_json"]["source_digest"] = row["source_digest"]
            command["response_json"][field] = row[field]
    for event in rows["manufacturing_execution_v2_events"]:
        if event["object_id"] == row["id"]:
            event["metadata"]["source_digest"] = row["source_digest"]
            audit = next(part for part in rows["domain_audit_events"] if part["id"] == event["audit_event_id"])
            message = next(part for part in rows["outbox_events"] if part["event_id"] == event["outbox_event_id"])
            audit["metadata_json"] = copy.deepcopy(event["metadata"])
            message["payload"] = {**event["metadata"], "audit_event_id": audit["id"]}
    with pytest.raises(ValueError, match="source seal|inspection source"):
        oracle.verify_proof(value)


def test_orphan_command_and_event_bijection_is_not_original_source_membership() -> None:
    value = proof()
    for table in ("manufacturing_execution_v2_commands", "manufacturing_execution_v2_events"):
        orphan = copy.deepcopy(value["populations"][table][0])
        orphan["object_id"] = "ME2-ORPHAN-OWNER"
        value["populations"][table].append(orphan)
    with pytest.raises(ValueError, match="Orphan"):
        oracle.verify_proof(value)


def test_positive_cost_claim_cannot_exist_without_the_exact_finance_ownership_directory() -> None:
    value = proof()
    value["populations"]["financial_effect_ownership_guards"].pop()
    with pytest.raises(ValueError, match="claim/directory"):
        oracle.verify_proof(value)


def test_an_unbacked_expense_claim_is_refused_even_if_its_local_payload_is_rehashed() -> None:
    value = proof()
    row = value["populations"]["manufacturing_execution_v2_cost_claims"][0]
    row["amount_minor"] += 1
    row["payload"]["amount_minor"] += 1
    parent = value["populations"]["manufacturing_execution_v2_orders"][0]
    parent["payload"]["claims"] = [row["payload"] if entry["effect_id"] == row["effect_id"] else entry for entry in parent["payload"]["claims"]]
    parent["source_digest"] = oracle.sha(parent["payload"])
    with pytest.raises(ValueError, match="rate/time capacity"):
        oracle.verify_proof(value)


def test_actual_posted_expense_eligibility_cannot_be_relabelled_as_generated() -> None:
    value = proof()
    effect = next(row for row in value["populations"]["finance_posting_effects"] if row["source_kind"] == "Manual" and row["snapshot_json"]["entry"]["entry_number"] == "LABOR-SOURCE")
    effect["source_kind"] = "Generated"
    with pytest.raises(ValueError, match="original posted expense"):
        oracle.verify_proof(value)


def test_hidden_quality_output_is_refused_before_any_posted_inspection() -> None:
    value = json.loads(HOLD.read_bytes())
    row = copy.deepcopy(value["populations"]["inventory_cost_layers"][0])
    row["id"] = "DETACHED-FG-LAYER"
    value["populations"]["inventory_cost_layers"].append(row)
    with pytest.raises(ValueError, match="detached native stock"):
        oracle.verify_proof(value)


@pytest.mark.parametrize("optimized", [False, True])
def test_portable_cli_requires_the_external_original_raw_proof_bytes(tmp_path: Path, optimized: bool) -> None:
    output = tmp_path / "oracle.json"
    flags = ["-I", "-O"] if optimized else ["-I"]
    result = subprocess.run([sys.executable, *flags, str(SCRIPT), "--proof", str(FIXTURE), "--proof-sha256", FINAL_SHA,
        "--output", str(output)], cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_bytes())["original_proof_sha256"] == FINAL_SHA
    altered = tmp_path / "altered.json"
    altered.write_bytes(FIXTURE.read_bytes() + b" ")
    refused = tmp_path / "refused.json"
    result = subprocess.run([sys.executable, *flags, str(SCRIPT), "--proof", str(altered), "--proof-sha256", FINAL_SHA,
        "--output", str(refused)], cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and not refused.exists()
