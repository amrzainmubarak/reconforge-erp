"""File-only adversarial checks over a byte-exact actual two-source native export."""

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
HELPER = ROOT / ".github/scripts/verify_intercompany_group_diagnostic.py"
ORIGINAL = ROOT / "tests/fixtures/intercompany-group-diagnostic-native-v1.json"
SHA = "843a87f664c5128bff62204073d5fb6330913701da627d8ed0d6fb34be204360"
api = runpy.run_path(str(HELPER))


def fixture():
    raw = ORIGINAL.read_bytes()
    assert len(raw) == 788853 and hashlib.sha256(raw).hexdigest() == SHA
    return api["cash_oracle"]()["parse"](raw)


def reseal(value, field):
    value[field] = api["digest"]({key: item for key, item in value.items() if key != field})


def test_two_actual_original_sources_reconcile_reporting_cash_separately_from_native_adjustment():
    result = api["verify"](fixture())
    cash = next(row for row in result["trial_balance_bridge"] if row["role"] == "cash")
    assert result["sources"] == 2 and result["native_effects"] == 14
    assert cash["translated_minor"] == cash["combined_minor"] == 202 and cash["native_adjustment_minor"] == 0
    assert result["cash_equation"]["fx_on_cash_minor"] == 202
    assert result["income_statement"]["result_minor"] == 784 and result["balance_sheet"]["equity_minor"] == -582
    assert result["current_authority_recomputed"] is result["formal_close_workflow_assessed"] is False


@pytest.mark.parametrize("optimized", [False, True])
def test_fresh_isolated_cli_verifies_exact_original_bytes_and_refuses_output_overwrite(tmp_path, optimized):
    output = tmp_path / "proof.json"
    command = [sys.executable, "-I", *(["-O"] if optimized else []), str(HELPER), str(ORIGINAL), "--sha256", SHA, "--output", str(output)]
    result = subprocess.run(command, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    before = output.read_bytes()
    assert json.loads(before)["original_sha256"] == SHA
    assert subprocess.run(command, capture_output=True, check=False).returncode != 0
    assert output.read_bytes() == before


@pytest.mark.parametrize("optimized", [False, True])
def test_external_raw_anchor_is_required_before_parse(tmp_path, optimized):
    path, output = tmp_path / "drift.json", tmp_path / "unexpected.json"
    path.write_bytes(ORIGINAL.read_bytes() + b" ")
    result = subprocess.run([sys.executable, "-I", *(["-O"] if optimized else []), str(HELPER), str(path),
                             "--sha256", SHA, "--output", str(output)], capture_output=True, check=False)
    assert result.returncode != 0 and b"raw SHA before parse" in result.stderr and not output.exists()


@pytest.mark.parametrize("attack,label", [
    ("source_omission", "bounded exact selection"), ("duplicate_source", "unique canonically"),
    ("pin", "original selected report"), ("period_extra", "complete observed period"),
    ("period_missing", "scoped observed native period"), ("period_tenant", "scoped observed native period"),
    ("period_workspace", "scoped observed native period"), ("period_date", "scoped observed native period"),
    ("close_claim", "selected diagnostic scope"), ("whole_group_claim", "selected diagnostic scope"),
    ("financial_write_claim", "finite original native qualification"),
    ("balanced_bridge", "independent selected original bridge"), ("cash_equation", "independent selected original Cash"),
    ("source_columns", "original source hierarchy"), ("native_effect", "actual posted original native effect"),
    ("bool_money", "exact bounded integer"),
])
def test_rehashed_mutations_reach_independent_source_or_bridge_refusal(attack, label):
    proof = fixture()
    report = proof["diagnostic"]
    if attack == "source_omission":
        proof["source_captures"].pop()
    elif attack == "duplicate_source":
        proof["selection"]["pins"][1] = deepcopy(proof["selection"]["pins"][0])
        report["selection"] = deepcopy(proof["selection"])
    elif attack == "pin":
        proof["selection"]["pins"][0]["report_digest"] = "0" * 64
        report["selection"] = deepcopy(proof["selection"])
    elif attack.startswith("period_"):
        periods = proof["native_periods"]
        if attack == "period_extra":
            periods.append({**periods[0], "id": "unrelated"})
        elif attack == "period_missing":
            periods.clear()
        else:
            periods[0].update({"period_tenant": {"tenant_id": "foreign"},
                "period_workspace": {"application_workspace_id": "foreign"},
                "period_date": {"end_date": "2026-10-02"}}[attack])
        report["native_period_observations"] = deepcopy(periods)
    elif attack == "close_claim":
        report["formal_close_workflow_assessed"] = True
    elif attack == "whole_group_claim":
        report["whole_group_membership_proven"] = True
    elif attack == "financial_write_claim":
        proof["financial_writes"] = True
    elif attack == "balanced_bridge":
        rows = {row["role"]: row for row in report["trial_balance_bridge"]}
        for role, change in (("cash", 1), ("cta", -1)):
            rows[role]["translated_minor"] += change
            rows[role]["native_adjustment_minor"] -= change
        assert all(sum(row[column] for row in rows.values()) == 0 for column in
                   ("translated_minor", "native_adjustment_minor", "combined_minor"))
    elif attack == "cash_equation":
        report["cash_equation"]["operating_net_minor"] += 1
        report["cash_equation"]["fx_on_cash_minor"] -= 1
    elif attack == "bool_money":
        next(row for row in report["trial_balance_bridge"] if row["role"] == "expense")["combined_minor"] = False
    else:
        capture = proof["source_captures"][0]
        if attack == "source_columns":
            capture["original_rows"]["source"][0]["organization_id"] = "foreign"
        if attack == "native_effect":
            capture["original_rows"]["effects"][0]["posted_actor_id"] = "foreign"
        reseal(capture, "evidence_digest")
    reseal(report, "diagnostic_digest")
    reseal(proof, "evidence_digest")
    with pytest.raises(ValueError, match=label):
        api["verify"](proof)


def test_runtime_imports_are_stdlib_only_and_cash_helper_is_pinned_before_execution():
    allowed = {"__future__", "argparse", "hashlib", "json", "re", "runpy", "pathlib", "typing"}
    for node in ast.walk(ast.parse(HELPER.read_text())):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module.split(".")[0] in allowed
        assert not isinstance(node, ast.Assert)
    assert hashlib.sha256(HELPER.with_name("verify_intercompany_cashflow_oracle.py").read_bytes()).hexdigest() == api["CASHFLOW_HELPER_SHA256"]
