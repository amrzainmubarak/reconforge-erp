"""Adversarial external-oracle checks over an original synthetic native export."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.verify_people_project_payroll_oracle import pairs, verify

FIXTURE = Path(__file__).parent / "fixtures" / "people-project-payroll-native-v1.json"
ORACLE = Path(__file__).parent / "verify_people_project_payroll_oracle.py"
TRUSTED_SHA = "d07fbb594180c4e033cd4898bd9ebd53585ed831459c5157b77a23028edcf936"


def original() -> dict[str, Any]:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == TRUSTED_SHA
    return json.loads(raw, object_pairs_hook=pairs)


def test_original_native_export_has_exact_independent_wage_conservation() -> None:
    result = verify(original())
    assert result["gross_minor"] == result["settled_minor"] == 2501
    assert sorted(result["project_minor"].values()) == [1233, 1268]
    assert result["balances"] == {"LABOR": 2501, "WAGES": 0, "CASH": -2501}
    assert result["native_effects"] == 3 and result["statutory_country_packs"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "rate",
        "interval",
        "overlap",
        "currency",
        "time_scope",
        "time_digest",
        "time_approval",
        "duplicate_time",
        "employee_gross",
        "project_allocation",
        "source_digest",
        "source_scope",
        "source_sod",
        "duplicate_effect",
        "missing_effect",
        "native_digest",
        "native_header",
        "native_account",
        "native_amount",
        "native_dimension",
        "employee_payment",
        "claim_owner",
        "claim_digest",
        "missing_claim",
        "budget_amount",
        "budget_owner",
        "balance",
    ],
)
def test_independent_oracle_refuses_source_and_native_mutations(mutation: str) -> None:
    proof = copy.deepcopy(original())
    parent = proof["payrun"]
    if mutation == "rate":
        proof["times"][0]["hourly_rate_minor"] += 1
    elif mutation == "interval":
        proof["times"][0]["lines"][0]["end_minute"] += 1
    elif mutation == "overlap":
        proof["times"][0]["lines"][1]["start_minute"] = 0
    elif mutation == "currency":
        proof["times"][0]["currency_code"] = "EUR"
    elif mutation == "time_scope":
        proof["times"][0]["workspace_id"] = "foreign"
    elif mutation == "time_digest":
        proof["times"][0]["source_digest"] = "0" * 64
    elif mutation == "time_approval":
        proof["times"][0]["approver_id"] = proof["times"][0]["submitter_id"]
    elif mutation == "duplicate_time":
        proof["times"].append(copy.deepcopy(proof["times"][0]))
    elif mutation == "employee_gross":
        parent["private"]["employees"][0]["gross_minor"] += 1
    elif mutation == "project_allocation":
        parent["project_minor"][next(iter(parent["project_minor"]))] += 1
    elif mutation == "source_digest":
        parent["plan_digest"] = "0" * 64
    elif mutation == "source_scope":
        proof["payments"][0]["legal_entity_id"] = "foreign"
    elif mutation == "source_sod":
        proof["payments"][0]["posted_actor_id"] = proof["payments"][0]["reviewer_id"]
    elif mutation == "duplicate_effect":
        proof["native_effects"].append(copy.deepcopy(proof["native_effects"][0]))
    elif mutation == "missing_effect":
        proof["native_effects"].pop()
    elif mutation == "native_digest":
        proof["native_effects"][0]["validation_digest"] = "0" * 64
    elif mutation == "native_header":
        proof["native_effects"][0]["snapshot"]["entry"]["external_reference"] = "HC1-foreign"
    elif mutation == "native_account":
        proof["native_effects"][0]["snapshot"]["lines"][0]["account_id"] = "foreign"
    elif mutation == "native_amount":
        proof["native_effects"][0]["snapshot"]["lines"][0]["debit_minor"] += 1
    elif mutation == "native_dimension":
        proof["native_effects"][0]["snapshot"]["lines"][0]["dimensions"] = {}
    elif mutation == "employee_payment":
        proof["payments"][0]["private"]["employees_minor"][
            next(iter(proof["payments"][0]["private"]["employees_minor"]))
        ] += 1
    elif mutation == "claim_owner":
        proof["claims"][0]["payrun_id"] = "HC1-foreign"
    elif mutation == "claim_digest":
        proof["claims"][0]["source_digest"] = "0" * 64
    elif mutation == "missing_claim":
        proof["claims"].pop()
    elif mutation == "budget_amount":
        proof["observed_budget"]["consumed_minor"] = "2502"
    elif mutation == "budget_owner":
        proof["budget_events"][0]["source_reference"] = "HC1-foreign"
    elif mutation == "balance":
        proof["observed_native_balances"]["LABOR"] += 1
    with pytest.raises((ValueError, KeyError)):
        verify(proof)


@pytest.mark.parametrize("optimized", [False, True])
def test_standalone_normal_and_optimized_no_app_oracle(tmp_path: Path, optimized: bool) -> None:
    output = tmp_path / "proof.json"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            *(["-O"] if optimized else []),
            str(ORACLE),
            "--evidence",
            str(FIXTURE),
            "--expected-evidence-sha256",
            TRUSTED_SHA,
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    parsed = json.loads(output.read_bytes())
    assert (
        parsed["accepted"] is True
        and parsed["raw_export_anchor"] is True
        and parsed["raw_evidence_sha256"] == TRUSTED_SHA
    )


@pytest.mark.parametrize("optimized", [False, True])
def test_coordinated_foreign_scope_cannot_replace_the_original_raw_anchor(tmp_path: Path, optimized: bool) -> None:
    proof = original()
    proof["payrun"]["workspace_id"] = "foreign"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(proof), encoding="utf-8")
    output = tmp_path / "proof.json"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            *(["-O"] if optimized else []),
            str(ORACLE),
            "--evidence",
            str(changed),
            "--expected-evidence-sha256",
            TRUSTED_SHA,
            "--output",
            str(output),
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0 and not output.exists()
    assert b"trusted raw anchor" in result.stderr


def test_oracle_imports_only_standard_library_and_refuses_duplicate_json() -> None:
    modules = {
        node.module.split(".")[0]
        for node in ast.walk(ast.parse(ORACLE.read_text()))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    modules |= {
        alias.name.split(".")[0]
        for node in ast.walk(ast.parse(ORACLE.read_text()))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert modules <= {"__future__", "argparse", "hashlib", "json", "fractions", "pathlib", "typing"}
    with pytest.raises(ValueError, match="Duplicate"):
        json.loads('{"wages":1,"wages":2}', object_pairs_hook=pairs)
