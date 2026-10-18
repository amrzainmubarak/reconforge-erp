"""Independent actual-native export and adversarial source/AR/GL custody."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/verify_project_time_billing_cycle_oracle.py"
ORIGINAL = Path(__file__).resolve().parent / "fixtures/project-time-billing-native-v1.json"
ORIGINAL_SHA = "ae8ad36684f809cfc9588bebb786e173daa99360fa239b01b92c09921358eac6"
spec = importlib.util.spec_from_file_location("project_billing_independent_oracle", SCRIPT)
assert spec is not None and spec.loader is not None
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def original() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    return json.loads(raw)


def test_actual_native_export_reproduces_independent_minute_prices_ar_and_cash() -> None:
    proof = oracle.verify(original())
    assert proof["accepted_cycle"] is True
    assert proof["amount_minor"] == proof["collected_minor"] == 6236
    assert proof["outstanding_minor"] == 0 and proof["original_time_entries"] == 2 and proof["native_effects"] == 3
    assert sorted(proof["project_minor"].values()) == [2535, 3701]
    assert proof["native_balances"] == {"AR": 0, "CASH": 6236, "REVENUE": -6236}
    assert (
        proof["audit_chain_recomputed"]
        is proof["current_sql_authority_proven"]
        is proof["performance_comparison_accepted"]
        is False
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "foreign_tenant",
        "foreign_scope",
        "duplicate_effect",
        "missing_effect",
        "duplicate_line",
        "extra_dimension",
        "native_amount",
        "native_account",
        "native_currency",
        "native_status",
        "source_actor",
        "source_view",
        "collection_view",
        "unknown_source_version",
        "raw_price",
        "source_time",
        "ar_status",
        "ar_date",
        "ar_owner",
        "ar_quantity",
        "ar_allocation",
        "receipt_owner",
        "receipt_actor",
        "claim_missing",
        "claim_actor",
        "claim_head",
        "duplicate_claim",
        "audit_parent",
        "outbox_payload",
        "command_response",
        "command_actor",
        "project_value",
        "account_classification",
        "fractional_minor",
        "boolean_minor",
        "registry",
        "foreign_customer",
        "period",
        "journal",
    ],
)
def test_independent_verifier_refuses_source_and_native_conservation_tamper(tamper: str) -> None:
    value = original()
    raw = value["original_rows"]
    p = next(row for row in raw["plans"] if row["kind"] == "Invoice")
    if tamper == "foreign_tenant":
        raw["effects"][0]["tenant_id"] = "foreign"
    elif tamper == "foreign_scope":
        raw["effects"][0]["legal_entity_id"] = "foreign"
    elif tamper == "duplicate_effect":
        raw["effects"].append(copy.deepcopy(raw["effects"][0]))
    elif tamper == "missing_effect":
        raw["effects"].pop()
    elif tamper == "duplicate_line":
        raw["entry_lines"].append(copy.deepcopy(raw["entry_lines"][0]))
    elif tamper == "extra_dimension":
        raw["entry_dimensions"].append({**raw["entry_dimensions"][0], "dimension_id": "foreign"})
    elif tamper == "native_amount":
        raw["entry_lines"][0]["debit_minor"] += 1
    elif tamper == "native_account":
        raw["entry_lines"][0]["account_id"] = raw["account_pins"][1]["account_id"]
    elif tamper == "native_currency":
        raw["entry_lines"][0]["currency_code"] = "EUR"
    elif tamper == "native_status":
        raw["entries"][0]["status"] = "Draft"
    elif tamper == "source_actor":
        p["poster_id"] = p["reviewer_id"]
    elif tamper == "source_view":
        value["invoice"]["phase"] = 1
    elif tamper == "collection_view":
        value["collections"][0]["amount_minor"] += 1
    elif tamper == "unknown_source_version":
        p["payload"]["schema_version"] = "unsupported"
    elif tamper == "raw_price":
        raw["prices"][0]["hourly_price_minor"] += 1
    elif tamper == "source_time":
        raw["times"][0]["lines"][0]["end_minute"] += 1
    elif tamper == "ar_status":
        raw["ar_invoices"][0]["status"] = "Submitted"
    elif tamper == "ar_date":
        raw["ar_invoices"][0]["invoice_date"] = "2026-10-03"
    elif tamper == "ar_owner":
        raw["ar_invoices"][0]["pb_owner_id"] = "foreign"
    elif tamper == "ar_quantity":
        raw["ar_lines"][0]["quantity"] = "2"
    elif tamper == "ar_allocation":
        raw["ar_allocations"][0]["amount_minor"] += 1
    elif tamper == "receipt_owner":
        raw["ar_receipts"][0]["pb_owner_id"] = "foreign"
    elif tamper == "receipt_actor":
        raw["ar_receipts"][0]["posted_by"] = "foreign"
    elif tamper == "claim_missing":
        raw["time_claims"].pop()
    elif tamper == "claim_actor":
        raw["claim_events"][0]["actor_id"] = "foreign"
    elif tamper == "claim_head":
        raw["claim_heads"][0]["state"] = "Released"
    elif tamper == "duplicate_claim":
        raw["claim_events"].append(copy.deepcopy(raw["claim_events"][0]))
    elif tamper == "audit_parent":
        raw["audits"][0]["object_id"] = "foreign"
    elif tamper == "outbox_payload":
        raw["outbox"][0]["payload"]["audit_event_id"] = "foreign"
    elif tamper == "command_response":
        raw["commands"][0]["response_json"]["amount_minor"] += 1
    elif tamper == "command_actor":
        raw["commands"][0]["actor_id"] = "foreign"
    elif tamper == "project_value":
        raw["projects"][0]["value_id"] = "foreign"
    elif tamper == "account_classification":
        raw["accounts"][0]["account_type"] = "Expense"
    elif tamper == "fractional_minor":
        raw["entry_lines"][0]["debit_minor"] = 1.1
    elif tamper == "boolean_minor":
        raw["entry_lines"][0]["debit_minor"] = True
    elif tamper == "registry":
        value["registry_snapshot"]["registry_version"] = "foreign"
    elif tamper == "foreign_customer":
        raw["customers"][0]["customer_code"] = "FOREIGN"
    elif tamper == "period":
        raw["periods"][0]["end_date"] = "2026-10-02"
    elif tamper == "journal":
        raw["journals"][0]["chart_id"] = "foreign"
    with pytest.raises((ValueError, KeyError, StopIteration, TypeError)):
        oracle.verify(value)


def test_balanced_rehashed_native_amount_change_still_fails_independent_business_oracle() -> None:
    value = original()
    raw = value["original_rows"]
    source = next(row for row in raw["plans"] if row["kind"] == "Invoice")
    snapshot = source["payload"]["snapshot"]
    snapshot["lines"][0]["debit_minor"] += 1
    snapshot["lines"][1]["credit_minor"] += 1
    new = oracle.digest(snapshot)
    source["payload"]["validation_digest"] = new
    source["payload"]["plan_digest"] = oracle.digest({k: v for k, v in source["payload"].items() if k != "plan_digest"})
    for line in raw["entry_lines"]:
        if line["entry_id"] == source["entry_id"]:
            if line["line_number"] == 1:
                line["debit_minor"] += 1
            if line["line_number"] == 2:
                line["credit_minor"] += 1
    entry = next(row for row in raw["entries"] if row["id"] == source["entry_id"])
    entry["validation_digest"] = new
    entry["total_debit_minor"] += 1
    entry["total_credit_minor"] += 1
    effect = next(row for row in raw["effects"] if row["id"] == source["effect_id"])
    effect["validation_digest"] = new
    effect["snapshot_json"] = copy.deepcopy(snapshot)
    value["invoice"].update(copy.deepcopy(source["payload"]))
    public = next(row for row in value["native_effects"] if row["id"] == effect["id"])
    public["validation_digest"] = new
    public["snapshot"] = copy.deepcopy(snapshot)
    for audit in raw["audits"]:
        if audit["object_id"] == source["id"]:
            audit["metadata_json"]["source_digest"] = source["payload"]["plan_digest"]
        elif audit["id"] == effect["audit_event_id"]:
            audit["metadata_json"]["content_digest"] = new
    for event in raw["outbox"]:
        if event["aggregate_id"] == source["id"]:
            event["payload"]["source_digest"] = source["payload"]["plan_digest"]
        elif event["event_id"] == effect["outbox_event_id"]:
            event["payload"]["content_digest"] = new
    with pytest.raises(ValueError, match="Independent original GL amount/account/Project differs"):
        oracle.verify(value)


def test_oracle_import_closure_is_standard_library_only() -> None:
    tree = ast.parse(SCRIPT.read_text())
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports == {"__future__", "argparse", "hashlib", "json", "re", "datetime", "fractions", "pathlib", "typing"}


def cli(path: Path, output: Path, sha: str, *, optimized: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            *(["-O"] if optimized else []),
            str(SCRIPT),
            "--evidence",
            str(path),
            "--expected-evidence-sha256",
            sha,
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_actual_native_original_is_identical_under_isolated_and_optimized_cli(tmp_path: Path) -> None:
    outputs = []
    for optimized in (False, True):
        path = tmp_path / ("IO.json" if optimized else "I.json")
        completed = cli(ORIGINAL, path, ORIGINAL_SHA, optimized=optimized)
        assert completed.returncode == 0, completed.stderr
        outputs.append(path.read_bytes())
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["raw_export_anchor"] is True


@pytest.mark.parametrize(
    "mutation", ["duplicate_member", "float", "nonfinite", "coordinated_tenant", "wrong_raw_sha", "existing_output"]
)
@pytest.mark.parametrize("optimized", [False, True])
def test_standalone_requires_trusted_original_raw_custody_and_fresh_output(
    tmp_path: Path, mutation: str, optimized: bool
) -> None:
    raw = ORIGINAL.read_bytes()
    sha = ORIGINAL_SHA
    if mutation == "duplicate_member":
        raw = b'{"schema_version":"duplicate",' + raw[1:]
    elif mutation == "float":
        raw = raw.replace(b'"amount_minor":6236', b'"amount_minor":6236.0', 1)
    elif mutation == "nonfinite":
        raw = b'{"untrusted":NaN,' + raw[1:]
    elif mutation == "coordinated_tenant":
        raw = raw.replace(original()["qualified_scope"]["tenant_id"].encode(), b"foreign-original-source")
    elif mutation == "wrong_raw_sha":
        sha = "0" * 64
    if mutation in {"duplicate_member", "float", "nonfinite"}:
        sha = hashlib.sha256(raw).hexdigest()
    source, output = tmp_path / "source.json", tmp_path / "proof.json"
    source.write_bytes(raw)
    if mutation == "existing_output":
        output.write_bytes(b"original retained bytes")
    completed = cli(source, output, sha, optimized=optimized)
    assert completed.returncode != 0
    assert not output.exists() or output.read_bytes() == b"original retained bytes"


def test_proof_created_after_freshness_check_cannot_be_overwritten(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "proof.json"
    target.write_bytes(b"separately created retained proof")
    exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: False if path == target else exists(path))
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--evidence", str(ORIGINAL), "--expected-evidence-sha256", ORIGINAL_SHA, "--output", str(target)],
    )
    with pytest.raises(FileExistsError):
        oracle.main()
    assert target.read_bytes() == b"separately created retained proof"
