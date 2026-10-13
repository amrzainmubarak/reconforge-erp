"""File-only adversarial checks against a retained actual public native export."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/verify_project_source_reconciliation.py"
GOLDEN = ROOT / "tests/fixtures/project_source_reconciliation_original_golden_v2.json"
RAW_SHA = "b69a7a4a0d736e026c44593687310483c90758ce2fd7dc669eb7c0309394583a"
spec = importlib.util.spec_from_file_location("project_source_independent", SCRIPT)
assert spec is not None and spec.loader is not None
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def original():
    raw = GOLDEN.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RAW_SHA
    return json.loads(raw)


def reseal(proof):
    report = proof["report"]
    report["report_digest"] = oracle.sha({k: v for k, v in report.items() if k != "report_digest"})
    proof["evidence_digest"] = oracle.sha({k: v for k, v in proof.items() if k != "evidence_digest"})


def test_original_public_native_export_fraction_cash_and_source_ownership():
    result = oracle.verify(original())
    assert result["project_totals"]["source_margin_minor"] == "1267"
    assert result["source_effect_count"] == 6 and result["whole_approved_time_count"] == 2
    assert result["private_earnings_formula_recomputed"] is False and result["per_project_cash_allocated"] is False


@pytest.mark.parametrize(
    "attack",
    [
        "tenant",
        "scope",
        "selected",
        "cost",
        "revenue",
        "whole_cash",
        "unknown_cost",
        "unknown_line",
        "missing_line",
        "duplicate_line",
        "dimension",
        "duplicate_dimension",
        "detached_dimension",
        "account_role",
        "entry_status",
        "effect",
        "native_ack",
        "ack_scope",
        "request_digest",
        "audit",
        "outbox",
        "missing_time",
        "duplicate_time",
        "time_overlap",
        "claim_owner",
        "claim_sequence",
        "post_consumed_release",
        "minute",
        "hourly",
        "bool_money",
        "incomplete_phase",
        "ar_owner",
        "receipt",
        "allocation",
        "private",
        "extra_journal",
        "extra_account",
        "extra_project",
        "price_approver",
        "price_policy",
        "price_digest",
        "price_dimension",
        "price_effective",
        "display_policy",
        "coverage_claim",
    ],
)
def test_rehashed_adversarial_original_source_refused(attack):
    proof = copy.deepcopy(original())
    raw = proof["original_rows"]
    if attack == "tenant":
        raw["entries"][0]["tenant_id"] = "foreign"
    elif attack == "scope":
        raw["payruns"][0]["legal_entity_id"] = "foreign"
    elif attack == "selected":
        proof["selection"]["invoice_id"] = "PB1-other"
    elif attack == "cost":
        proof["report"]["project_totals"]["wage_cost_minor"] = "0"
    elif attack == "revenue":
        proof["report"]["project_totals"]["revenue_minor"] = "0"
    elif attack == "whole_cash":
        proof["report"]["whole_source_settlement"]["wage_paid_minor"] = "0"
    elif attack == "unknown_cost":
        raw["project_ledger"].append(dict(raw["project_ledger"][0], id="foreign", entry_id="foreign"))
    elif attack == "unknown_line":
        raw["entry_lines"].append(dict(raw["entry_lines"][0], id="foreign", entry_id="foreign"))
    elif attack == "missing_line":
        raw["entry_lines"].pop()
    elif attack == "duplicate_line":
        raw["entry_lines"].append(raw["entry_lines"][0])
    elif attack == "dimension":
        raw["entry_dimensions"][0]["dimension_value_id"] = "foreign"
    elif attack == "duplicate_dimension":
        raw["entry_dimensions"].append(raw["entry_dimensions"][0])
    elif attack == "detached_dimension":
        raw["entry_dimensions"].append(dict(raw["entry_dimensions"][0], entry_line_id="foreign"))
    elif attack == "account_role":
        raw["accounts"][0]["account_type"] = "Expense"
    elif attack == "entry_status":
        raw["entries"][0]["status"] = "Draft"
    elif attack == "effect":
        raw["effects"][0]["source_id"] = "foreign"
    elif attack == "native_ack":
        raw["native_post_commands"][0]["result_json"]["posted_actor_id"] = "foreign"
    elif attack == "ack_scope":
        raw["native_post_commands"][0]["legal_entity_id"] = "foreign"
    elif attack == "request_digest":
        raw["native_post_commands"][0]["request_digest"] = "0" * 64
    elif attack == "audit":
        raw["audits"][0]["actor_user_id"] = "foreign"
    elif attack == "outbox":
        raw["outbox"][0]["payload"]["audit_event_id"] = "foreign"
    elif attack == "missing_time":
        raw["times"].pop()
    elif attack == "duplicate_time":
        raw["times"].append(raw["times"][0])
    elif attack == "time_overlap":
        raw["times"][0]["lines"].append(raw["times"][0]["lines"][0])
    elif attack == "claim_owner":
        raw["hc_claim_heads"][0]["payrun_id"] = "foreign"
    elif attack == "claim_sequence":
        raw["pb_claim_events"][0]["sequence"] = True
    elif attack == "post_consumed_release":
        event = dict(raw["hc_claim_events"][1], id="foreign", operation="Release", sequence=3)
        raw["hc_claim_events"].append(event)
        raw["hc_claim_heads"][0]["sequence"] = 3
    elif attack in ("minute", "hourly"):
        invoice = next(p for p in raw["plans"] if p["kind"] == "Invoice")
        invoice["payload"]["calculation"]["sources"][0]["minutes" if attack == "minute" else "hourly_price_minor"] += 1
        payload = invoice["payload"]
        payload["plan_digest"] = oracle.sha({k: v for k, v in payload.items() if k != "plan_digest"})
    elif attack == "bool_money":
        raw["entry_lines"][0]["debit_minor"] = True
    elif attack == "incomplete_phase":
        raw["payments"][0]["phase"] = 1
    elif attack == "ar_owner":
        raw["ar_invoice"]["pb_owner_id"] = "foreign"
    elif attack == "receipt":
        raw["ar_receipts"][0]["amount_minor"] += 1
    elif attack == "allocation":
        raw["ar_allocations"][0]["invoice_id"] = "foreign"
    elif attack == "private":
        raw["times"][0]["employee_id"] = "private"
    elif attack == "extra_journal":
        raw["journals"].append(dict(raw["journals"][0], id="unreferenced"))
    elif attack == "extra_account":
        raw["accounts"].append(dict(raw["accounts"][0], id="unreferenced", account_code="UNREFERENCED"))
    elif attack == "extra_project":
        raw["projects"].append(dict(raw["projects"][0], id="unreferenced"))
    elif attack == "price_approver":
        raw["prices"][0]["approver_id"] = raw["prices"][0]["preparer_id"]
    elif attack in ("price_policy", "price_digest", "price_dimension", "price_effective"):
        price = raw["prices"][0]
        if attack == "price_policy":
            price["source_json"]["monetary_policy"]["currency_code"] = "EUR"
        elif attack == "price_digest":
            price["source_digest"] = "0" * 64
        elif attack == "price_dimension":
            price["source_json"]["value_id"] = "foreign"
        else:
            price["valid_through"] = price["source_json"]["valid_through"] = "2026-09-01"
        if attack != "price_digest":
            price["source_digest"] = oracle.sha(price["source_json"])
    elif attack == "display_policy":
        proof["report"]["currency_policy"]["currency_code"] = "EUR"
    elif attack == "coverage_claim":
        proof["report"]["limitations"]["private_earnings_digest_recomputed"] = True
    reseal(proof)
    with pytest.raises((ValueError, KeyError, TypeError)):
        oracle.verify(proof)


@pytest.mark.parametrize("optimized", [False, True])
def test_isolated_cli_original_and_coordinated_tenant_drift_raw_anchor(tmp_path, optimized):
    output = tmp_path / "proof.json"
    flags = ["-I", "-O"] if optimized else ["-I"]
    run = subprocess.run(
        [
            sys.executable,
            *flags,
            str(SCRIPT),
            "--evidence",
            str(GOLDEN),
            "--expected-sha256",
            RAW_SHA,
            "--output",
            str(output),
        ],
        capture_output=True,
        check=False,
    )
    assert run.returncode == 0 and json.loads(output.read_text())["raw_export_anchor"] is True
    proof = original()
    encoded = oracle.canonical(proof).replace(
        proof["original_rows"]["qualified_scope"]["tenant_id"].encode(), b"coordinated-foreign"
    )
    drift = tmp_path / "drift.json"
    drift.write_bytes(encoded)
    fresh = tmp_path / "refused.json"
    run = subprocess.run(
        [
            sys.executable,
            *flags,
            str(SCRIPT),
            "--evidence",
            str(drift),
            "--expected-sha256",
            RAW_SHA,
            "--output",
            str(fresh),
        ],
        capture_output=True,
        check=False,
    )
    assert run.returncode != 0 and not fresh.exists()


def test_json_duplicate_float_and_atomic_retained_output_refusal(tmp_path):
    with pytest.raises(ValueError):
        oracle.pairs([("a", 1), ("a", 2)])
    output = tmp_path / "retained.json"
    output.write_bytes(b"original")
    run = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "--evidence",
            str(GOLDEN),
            "--expected-sha256",
            RAW_SHA,
            "--output",
            str(output),
        ],
        capture_output=True,
        check=False,
    )
    assert run.returncode != 0 and output.read_bytes() == b"original"
