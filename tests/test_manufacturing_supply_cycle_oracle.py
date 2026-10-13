"""Independent file-only checks over byte-exact original bounded native supply rows."""
import ast
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
SCRIPT = ROOT / ".github/scripts/verify_manufacturing_supply_cycle_oracle.py"
FIXTURE = ROOT / "tests/fixtures/manufacturing_supply_original_golden.json"
ORIGINAL_SHA = "9f49c6c5c523a0f0d7e65a457c727fc741bcec367cd3d6b98ce6098f90476590"
spec = importlib.util.spec_from_file_location("independent_msp_oracle", SCRIPT)
assert spec is not None and spec.loader is not None
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def proof() -> dict[str, Any]:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    return json.loads(raw)


def test_original_native_bom_net_fifo_src_ap_budget_material_expense_qc_fg_and_complete_gl() -> None:
    result = oracle.verify_proof(proof())
    assert result["net_quantities"] == {
        "ITEM": {"uom_code": "EA", "quantity_precision": 0, "gross_scaled": "2", "starting_scaled": "1", "onhand_scaled": "1", "shortage_scaled": "1"},
        "MATERIAL": {"uom_code": "KG", "quantity_precision": 3, "gross_scaled": "3000", "starting_scaled": "500", "onhand_scaled": "500", "shortage_scaled": "2500"}}
    assert tuple(result[key] for key in ("issued_material_minor", "claimed_expense_minor", "total_cost_minor", "finished_cost_minor", "abnormal_loss_minor", "remaining_wip_minor")) == ("2700", "900", "3600", "3240", "360", "0")
    assert result["native_positions_minor"] == {"ACCRUAL": "-3000", "AP": "-1450", "CLEARING": "-1250", "FG": "3240", "INVENTORY": "0", "LABOR": "1400", "OVERHEAD": "700", "SCRAP": "360", "WIP": "0"}
    assert result["sourcing"]["received_minor"] == result["sourcing"]["consumed_minor"] == "1450"
    assert result["sourcing"]["source_reserved_minor"] == "0"
    assert (result["quantity_claims"], result["quantity_releases"], result["supply_commands"], result["posting_effects"], result["balanced_turnover_minor"]) == (5, 5, 29, 13, "14350")
    assert len(result["original_effect_ids"]) == 13 and len(result["excluded_independently_verified_ap_effect_ids"]) == 2
    assert result["external_attestation"] is False and result["performance_accepted"] is False


def test_oracle_and_its_captured_companions_import_only_stdlib() -> None:
    allowed = {"__future__", "argparse", "copy", "hashlib", "importlib", "json", "re", "collections", "fractions", "pathlib", "typing"}
    for path in (SCRIPT, SCRIPT.with_name("verify_manufacturing_v2_cycle_oracle.py"), SCRIPT.with_name("verify_procurement_sourcing_oracle.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] in allowed for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module and node.module.split(".")[0] in allowed
    assert "from fractions import Fraction" in SCRIPT.read_text(encoding="utf-8")


@pytest.mark.parametrize("table,field", [("manufacturing_supply_requirements", "gross_quantity_scaled"),
    ("manufacturing_supply_stock_claims", "quantity_scaled"), ("procurement_partial_invoices", "total_minor"),
    ("budget_envelopes", "consumed_minor"), ("inventory_cost_layers", "original_value_minor")])
@pytest.mark.parametrize("token", [True, 1.0])
def test_native_integer_tokens_cannot_be_replaced_by_equal_float_or_boolean(table: str, field: str, token: Any) -> None:
    value = proof()
    original = value["populations"][table][0][field]
    value["populations"][table][0][field] = float(original) if type(token) is float else token
    with pytest.raises(ValueError, match="Original bounded integer"):
        oracle.verify_proof(value)


def test_rehashed_coverage_cannot_shift_original_onhand_to_more_shortage_while_conserving_gross() -> None:
    value = proof()
    row = value["populations"]["manufacturing_supply_requirements"][0]
    row["onhand_reserved_scaled"] -= 1
    row["shortage_quantity_scaled"] += 1
    row["coverage_json"]["onhand_reserved_scaled"] -= 1
    row["coverage_json"]["shortage_quantity_scaled"] += 1
    row["coverage_digest"] = oracle.sha(row["coverage_json"])
    with pytest.raises(ValueError, match="Independent original starting-stock"):
        oracle.verify_proof(value)


def test_rehashed_bom_cannot_change_original_scaled_demand_without_actual_original_stock() -> None:
    value = proof()
    tables = value["populations"]
    bom, plan = tables["manufacturing_execution_boms"][0], tables["manufacturing_supply_plans"][0]
    bom["payload"]["components"][0]["quantity_scaled"] += 1
    bom["source_digest"] = oracle.sha(bom["payload"])
    plan["payload"]["bom_digest"] = bom["source_digest"]
    plan["source_digest"] = oracle.sha(plan["payload"])
    with pytest.raises(ValueError, match="Original exact BOM scaling"):
        oracle.verify_proof(value)


@pytest.mark.parametrize("table", ["inventory_quantity_source_guards", "inventory_quantity_source_releases", "manufacturing_supply_stock_releases"])
def test_original_quantity_custody_cannot_omit_its_guard_or_handoff_release(table: str) -> None:
    value = proof()
    value["populations"][table].pop()
    with pytest.raises(ValueError, match="guard/release membership"):
        oracle.verify_proof(value)


@pytest.mark.parametrize("table,field", [("inventory_items", "organization_id"), ("inventory_units_of_measure", "decimal_places"),
    ("inventory_warehouses", "legal_entity_id"), ("inventory_quantity_source_guards", "inventory_account_id")])
def test_original_native_master_metadata_cannot_reinterpret_scoped_guarded_units(table: str, field: str) -> None:
    value = proof()
    guard = value["populations"]["inventory_quantity_source_guards"][0]
    identifier = guard[{"inventory_items": "item_id", "inventory_units_of_measure": "uom_id", "inventory_warehouses": "warehouse_id", "inventory_quantity_source_guards": "id"}[table]]
    row = next(part for part in value["populations"][table] if part["id"] == identifier)
    row[field] = 6 if field == "decimal_places" else None if field in {"organization_id", "legal_entity_id"} else "FOREIGN-ACCOUNT"
    with pytest.raises(ValueError, match="master tuple"):
        oracle.verify_proof(value)


def test_original_historical_ack_cannot_claim_terminal_releases_before_native_handoff() -> None:
    value = proof()
    row = next(row for row in value["populations"]["manufacturing_supply_commands"] if row["operation"] == "approve")
    row["response_json"]["source"]["stock_claims"][0]["state"] = "HandedOff"
    with pytest.raises(ValueError, match="historical supply ACK"):
        oracle.verify_proof(value)


def test_original_procurement_claim_cannot_duplicate_an_already_claimed_net_requirement() -> None:
    value = proof()
    row = copy.deepcopy(value["populations"]["manufacturing_supply_procurement_claims"][0])
    row["id"] += "-DUPLICATE"
    row["payload"]["id"] = row["id"]
    row["source_digest"] = oracle.sha(row["payload"])
    value["populations"]["manufacturing_supply_procurement_claims"].append(row)
    with pytest.raises(ValueError, match="procurement duplicates"):
        oracle.verify_proof(value)


def test_rehashed_original_budget_cannot_consume_more_than_actual_native_ap() -> None:
    value = proof()
    value["populations"]["budget_envelopes"][0]["consumed_minor"] += 1
    with pytest.raises(ValueError, match="budget envelope"):
        oracle.verify_proof(value)


def test_original_ap_native_journal_line_cannot_differ_from_its_unchanged_posting_snapshot() -> None:
    value = proof()
    tables = value["populations"]
    effect_id = tables["procurement_partial_invoices"][0]["accrual_effect_id"]
    entry_id = next(row["entry_id"] for row in tables["finance_posting_effects"] if row["id"] == effect_id)
    row = next(row for row in tables["finance_entry_lines"] if row["entry_id"] == entry_id and row["debit_minor"] > 0)
    row["debit_minor"] += 1
    with pytest.raises(ValueError, match="entire AP/production GL"):
        oracle.verify_proof(value)


def test_original_fifo_cannot_consume_the_same_component_layer_twice_instead_of_starting_and_received_stock() -> None:
    value = proof()
    rows = value["populations"]["inventory_layer_consumptions"]
    pair = [row for row in rows if row["quantity_scaled"] == 1]
    assert len(pair) == 2
    pair[0]["cost_layer_id"] = pair[1]["cost_layer_id"]
    with pytest.raises(ValueError):
        oracle.verify_proof(value)


def test_independent_companion_cannot_change_after_the_original_source_capture() -> None:
    value = proof()
    value["capture"]["source_files_sha256"][".github/scripts/verify_procurement_sourcing_oracle.py"] = "0" * 64
    with pytest.raises(ValueError, match="companion source digest"):
        oracle.verify_proof(value)


@pytest.mark.parametrize("optimized", [False, True])
def test_file_only_cli_verifies_actual_original_bytes_in_isolated_and_optimized_python(tmp_path: Path, optimized: bool) -> None:
    output = tmp_path / "result.json"
    flags = ["-I", "-O"] if optimized else ["-I"]
    completed = subprocess.run([sys.executable, *flags, str(SCRIPT), "--proof", str(FIXTURE), "--proof-sha256", ORIGINAL_SHA, "--output", str(output)],
        cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(output.read_bytes())["original_proof_sha256"] == ORIGINAL_SHA
    altered = tmp_path / "altered.json"
    altered.write_bytes(FIXTURE.read_bytes() + b" ")
    refused = tmp_path / "refused.json"
    completed = subprocess.run([sys.executable, *flags, str(SCRIPT), "--proof", str(altered), "--proof-sha256", ORIGINAL_SHA, "--output", str(refused)],
        cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert completed.returncode != 0 and not refused.exists()
    # Existing outputs are immutable even after an actual success.
    completed = subprocess.run([sys.executable, *flags, str(SCRIPT), "--proof", str(FIXTURE), "--proof-sha256", ORIGINAL_SHA, "--output", str(output)],
        cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert completed.returncode != 0


def test_duplicate_original_json_member_is_refused_even_with_matching_external_bytes(tmp_path: Path) -> None:
    raw = FIXTURE.read_bytes().replace(b'"schema_version": "manufacturing-supply-proof-v1"', b'"schema_version": "manufacturing-supply-proof-v1", "schema_version": "manufacturing-supply-proof-v1"')
    assert raw != FIXTURE.read_bytes()
    proof_file, result = tmp_path / "duplicate.json", tmp_path / "refused.json"
    proof_file.write_bytes(raw)
    completed = subprocess.run([sys.executable, "-I", str(SCRIPT), "--proof", str(proof_file), "--proof-sha256", hashlib.sha256(raw).hexdigest(), "--output", str(result)],
        cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert completed.returncode != 0 and "Duplicate original JSON member" in completed.stderr and not result.exists()
