"""Adversarial independent checks over byte-exact synthetic native history."""

import ast
import hashlib
import json
import runpy
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/verify_accrual_deferral_cycle_oracle.py"
FIXTURE = ROOT / "tests/fixtures/accrual-deferral-native-v1.json"
TRUSTED_SHA = "4f0bc0d798fd7d788d59c8743a8c17b3617153deef69128dcc16962f0aa7872b"
ORACLE = runpy.run_path(str(SCRIPT))


def original():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == TRUSTED_SHA
    return json.loads(raw)


def reseal(proof):
    proof["evidence_digest"] = ORACLE["digest"]({key: value for key, value in proof.items() if key != "evidence_digest"})


@pytest.mark.parametrize("optimized", (False, True))
def test_original_native_six_effects_and_cli_isolation(optimized, tmp_path):
    result = subprocess.run([sys.executable, "-I", *(["-O"] if optimized else []), str(SCRIPT), "--evidence", str(FIXTURE),
        "--expected-evidence-sha256", TRUSTED_SHA, "--output", str(tmp_path / "oracle.json")], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    verdict = json.loads((tmp_path / "oracle.json").read_text())
    assert verdict["accepted"] and verdict["native_effects"] == 6
    assert verdict["native_balances"] == {"PREPAID": 0, "EXPENSE": 10001, "CASH": -10001}
    assert not verdict["audit_chain_recomputed"] and not verdict["performance_comparison_accepted"]


def test_independent_source_has_only_stdlib_imports_and_duplicate_json_is_refused():
    imports = {node.module.split(".")[0] for node in ast.walk(ast.parse(SCRIPT.read_text())) if isinstance(node, ast.ImportFrom) and node.module}
    imports.update(alias.name.split(".")[0] for node in ast.walk(ast.parse(SCRIPT.read_text())) if isinstance(node, ast.Import) for alias in node.names)
    assert imports <= sys.stdlib_module_names | {"__future__"}
    with pytest.raises(ValueError, match="Duplicate"):
        json.loads('{"amount_minor":1,"amount_minor":2}', object_pairs_hook=ORACLE["unique_pairs"])


@pytest.mark.parametrize("optimized", (False, True))
def test_actual_raw_byte_drift_cannot_replace_trusted_native_export(optimized, tmp_path):
    drift = tmp_path / "drift.json"
    drift.write_bytes(FIXTURE.read_bytes() + b" ")
    result = subprocess.run([sys.executable, "-I", *(["-O"] if optimized else []), str(SCRIPT), "--evidence", str(drift),
        "--expected-evidence-sha256", TRUSTED_SHA, "--output", str(tmp_path / "oracle.json")], capture_output=True, text=True, check=False)
    assert result.returncode != 0 and "trusted original byte anchor" in result.stderr
    assert not (tmp_path / "oracle.json").exists()


@pytest.mark.parametrize("population", ("account_pins", "calendar_pins", "phases", "commands", "native_effects", "claims"))
def test_each_raw_native_population_rejects_another_tenant_even_after_outer_reseal(population):
    proof = original()
    proof[population][0]["tenant_id"] = "other-tenant"
    reseal(proof)
    with pytest.raises(ValueError, match="tenant"):
        ORACLE["verify"](proof)


@pytest.mark.parametrize("mutation", ("amount", "allocation", "account_pin", "calendar_pin", "head_tenant", "missing_event", "event_sequence",
    "head_state", "phase_actor", "foreign_phase", "command_response", "native_balance", "inverse_lines", "inverse_original", "qualified_scope", "duplicate_effect"))
def test_independent_native_source_effect_claim_and_scope_mutations_are_refused(mutation):
    proof = original()
    source = proof["source"]
    if mutation == "amount":
        source["request"]["amount_minor"] += 1
        source["source_digest"] = ORACLE["digest"]({key: value for key, value in source.items() if key not in {"plans", "claims", "cancelled", "source_digest"}})
    elif mutation == "allocation":
        source["request"]["tranches"][0]["amount_minor"] += 1
        source["source_digest"] = ORACLE["digest"]({key: value for key, value in source.items() if key not in {"plans", "claims", "cancelled", "source_digest"}})
    elif mutation == "account_pin":
        proof["account_pins"][0]["chart_id"] = "unreviewed-chart"
    elif mutation == "calendar_pin":
        proof["calendar_pins"][0]["start_date"] = "2026-09-01"
    elif mutation == "head_tenant":
        source["claims"][0]["tenant_id"] = "other-tenant"
    elif mutation == "missing_event":
        proof["claims"].pop()
    elif mutation == "event_sequence":
        proof["claims"][1]["sequence"] += 1
    elif mutation == "head_state":
        source["claims"][0]["state"] = "Available"
    elif mutation == "phase_actor":
        row = next(row for row in proof["phases"] if row["operation"] == "review")
        row["actor_id"] = "maker"
    elif mutation == "foreign_phase":
        proof["phases"][0]["plan_id"] = "foreign-plan"
    elif mutation == "command_response":
        proof["commands"][0]["response_json"]["plan_digest"] = "0" * 64
    elif mutation == "native_balance":
        effect = proof["native_effects"][0]
        effect["snapshot"]["lines"][0]["debit_minor"] += 1
        effect["validation_digest"] = ORACLE["digest"](effect["snapshot"])
    elif mutation in {"inverse_lines", "inverse_original"}:
        plan = next(plan for plan in source["plans"] if plan["kind"] == "reverse")
        if mutation == "inverse_lines":
            plan["equation"]["lines"][0]["credit_minor"] += 1
        else:
            plan["equation"]["original_posting_effect_id"] = "different-original-effect"
        plan["plan_digest"] = ORACLE["digest"]({key: value for key, value in plan.items() if key not in
            {"phase", "status", "reviewer_actor_id", "posted_actor_id", "posting_effect_id", "plan_digest"}})
    elif mutation == "qualified_scope":
        proof["qualified_scope"]["legal_entity_id"] = "other-entity"
    else:
        proof["native_effects"].append(deepcopy(proof["native_effects"][0]))
    reseal(proof)
    with pytest.raises((ValueError, KeyError)):
        ORACLE["verify"](proof)
