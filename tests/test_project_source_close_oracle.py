"""File-only adversarial derivative checks; observed periods here are synthetic."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from reconforge.application.accrual_deferral_evidence import evidence_digest, evidence_size
from reconforge.domain.project_source_reconciliation import diagnose_project_source_close
from tests.test_project_source_close import original, periods, selected

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/verify_project_source_reconciliation.py"
spec = importlib.util.spec_from_file_location("project_close_independent", SCRIPT)
assert spec is not None and spec.loader is not None
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def envelope():
    source = original()
    observed = periods(source)
    value = {"schema_version": "project-source-close-evidence-v1", "diagnostic": diagnose_project_source_close(selected(source), source, observed),
             "source_evidence": source, "source_original_sha256": evidence_digest(source), "source_original_bytes": evidence_size(source),
             "native_periods": observed, "native_execution_proven": True, "financial_writes": False,
             "private_personnel_reads": False, "audit_chain_recomputed": False, "performance_comparison_accepted": False}
    return {**value, "evidence_digest": evidence_digest(value)}


def reseal(proof):
    proof["diagnostic"]["diagnostic_digest"] = oracle.sha({k: v for k, v in proof["diagnostic"].items() if k != "diagnostic_digest"})
    proof["evidence_digest"] = oracle.sha({k: v for k, v in proof.items() if k != "evidence_digest"})


def test_independent_original_math_claims_and_separate_selected_obligations():
    result = oracle.verify_close(envelope())
    assert result["source_obligations_settled"] is True
    assert result["project_totals"]["source_margin_minor"] == "1267"
    assert result["whole_approved_time_count"] == 2 and result["source_effect_count"] == 6
    assert result["formal_close_workflow_assessed"] is False and result["current_sql_authority_proven"] is False


@pytest.mark.parametrize("name,raw_sha,effects,settled", [
    ("partial", "93f813a7a88c7d39950181e8c5c99597b1fb206493a32bd76d7bf5e0c5a29462", 4, False),
    ("final", "fdd5987ae6f52efe835ef08e03396f37236a521e939c431bbf07d44f23e3f37b", 6, True),
])
def test_actual_original_native_partial_and_final_obligations_are_independently_reconstructed(name, raw_sha, effects, settled):
    raw = (ROOT / f"tests/fixtures/project_source_close_{name}_native_v1.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == raw_sha
    result = oracle.verify_close(json.loads(raw))
    assert result["source_effect_count"] == effects and result["source_obligations_settled"] is settled
    if not settled:
        assert result["whole_source_obligations"]["wage_liability_minor"] == "1501"
        assert result["whole_source_obligations"]["ar_outstanding_minor"] == "5236"


@pytest.mark.parametrize("attack", ["money", "source_hash", "source_bytes", "source_report", "claim", "claim_extra", "period", "period_extra",
                                  "native_period", "period_field", "findings", "settled_bool", "full_close", "statutory_bool", "private", "effect", "extra_envelope"])
def test_resealed_derived_wrong_membership_or_unsupported_claim_refused(attack):
    proof = envelope()
    diagnostic = proof["diagnostic"]
    if attack == "money":
        diagnostic["whole_source_obligations"]["collected_minor"] = "0"
    elif attack == "source_hash":
        proof["source_original_sha256"] = "0" * 64
    elif attack == "source_bytes":
        proof["source_original_bytes"] += 1
    elif attack == "source_report":
        diagnostic["source_report_digest"] = "0" * 64
    elif attack == "claim":
        diagnostic["whole_time_claims"][0]["wage_claim"]["owner_id"] = "HC1-FOREIGN"
    elif attack == "claim_extra":
        diagnostic["whole_time_claims"].append(copy.deepcopy(diagnostic["whole_time_claims"][0]))
    elif attack == "period":
        diagnostic["observed_native_periods"][0]["tenant_id"] = "foreign"
    elif attack == "period_extra":
        diagnostic["observed_native_periods"].append({**diagnostic["observed_native_periods"][0], "id": "extra"})
    elif attack == "period_field":
        proof["native_periods"][0]["employee_id"] = "private-field-not-in-native-projection"
    elif attack == "native_period":
        proof["native_periods"] = []
    elif attack == "findings":
        diagnostic["findings"] = ["selected_invoice_receivable_outstanding"]
    elif attack == "settled_bool":
        diagnostic["source_obligations_settled"] = 1
    elif attack == "full_close":
        diagnostic["limitations"]["formal_close_workflow_assessed"] = True
    elif attack == "statutory_bool":
        diagnostic["limitations"]["country_statutory_packs"] = False
    elif attack == "private":
        proof["private_personnel_reads"] = True
    elif attack == "effect":
        proof["source_evidence"]["original_rows"]["effects"].pop()
        proof["source_evidence"]["evidence_digest"] = oracle.sha({k: v for k, v in proof["source_evidence"].items() if k != "evidence_digest"})
        proof["source_original_sha256"] = oracle.sha(proof["source_evidence"])
        proof["source_original_bytes"] = len(oracle.canonical(proof["source_evidence"]))
    else:
        proof["unrelated_rows"] = []
    reseal(proof)
    with pytest.raises((ValueError, KeyError)):
        oracle.verify_close(proof)


@pytest.mark.parametrize("optimized", [False, True])
def test_close_standalone_trusted_raw_pin_original_source_and_normal_optimized(tmp_path, optimized):
    raw = oracle.canonical(envelope())
    source = tmp_path / "original.json"
    source.write_bytes(raw)
    output = tmp_path / "verified.json"
    args = [sys.executable, "-I", *(["-O"] if optimized else []), str(SCRIPT), "--kind", "close",
            "--evidence", str(source), "--expected-sha256", hashlib.sha256(raw).hexdigest(), "--output", str(output)]
    run = subprocess.run(args, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr.decode()
    assert json.loads(output.read_bytes())["raw_export_anchor"] is True
    tampered = json.loads(raw)
    tampered["diagnostic"]["source_obligations_settled"] = False
    source.write_bytes(oracle.canonical(tampered))
    refused_output = tmp_path / "must-not-exist.json"
    args[-1] = str(refused_output)
    refused = subprocess.run(args, capture_output=True, timeout=20)
    assert refused.returncode != 0 and not refused_output.exists()
