"""Independent file-only checks over one byte-exact actual synthetic native export."""

import ast
import hashlib
import json
import runpy
import subprocess
import sys
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / ".github/scripts/verify_intercompany_cashflow_oracle.py"
ORIGINAL = ROOT / "tests/fixtures/intercompany-source-cashflow-native-v1.json"
SHA = "00afc06b175e4fd3958624c058db8f28acd798b4d4a852cd7cc968de2fd2cb3b"
api = runpy.run_path(str(HELPER))


def fixture():
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    return api["parse"](raw)


def reseal(proof, key):
    proof[key] = api["digest"]({name: value for name, value in proof.items() if name != key})


def test_actual_original_derives_operating_and_separate_exchange_effect():
    result = api["verify"](fixture())
    assert result["opening_minor"] == result["operating_net_minor"] == 0
    assert result["closing_minor"] == result["fx_on_cash_minor"] == 101
    assert result["books"]["seller"]["fx_on_cash_minor"] == -45
    assert result["books"]["buyer"]["fx_on_cash_minor"] == 146
    assert result["native_effects"] == 7 and result["native_lines"] == 18
    assert result["whole_company_cash_balance_proven"] is False and result["legal_qualification_assessed"] is False


@pytest.mark.parametrize("optimized", [False, True])
def test_standalone_isolated_original_and_fresh_output_are_byte_exact(tmp_path: Path, optimized: bool):
    output = tmp_path / "proof.json"
    args = [sys.executable, "-I", *(["-O"] if optimized else []), str(HELPER), str(ORIGINAL), "--sha256", SHA, "--output", str(output)]
    accepted = subprocess.run(args, capture_output=True, text=True, check=False)
    assert accepted.returncode == 0, accepted.stderr
    before = output.read_bytes()
    rejected = subprocess.run(args, capture_output=True, text=True, check=False)
    assert rejected.returncode != 0 and output.read_bytes() == before
    result = json.loads(before)
    assert result["original_sha256"] == SHA and result["original_bytes"] == 388945


@pytest.mark.parametrize("optimized", [False, True])
def test_external_raw_anchor_refuses_modified_bytes_before_parsing(tmp_path: Path, optimized: bool):
    path = tmp_path / "drift.json"
    path.write_bytes(ORIGINAL.read_bytes() + b" ")
    output = tmp_path / "unexpected.json"
    result = subprocess.run([sys.executable, "-I", *(["-O"] if optimized else []), str(HELPER), str(path),
        "--sha256", SHA, "--output", str(output)], capture_output=True, text=True, check=False)
    assert result.returncode != 0 and "raw SHA before parse" in result.stderr and not output.exists()


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"amount":1.0}', b'{"amount":NaN}', b'{"amount":Infinity}'])
def test_ambiguous_or_floating_json_is_refused(raw: bytes):
    with pytest.raises(ValueError):
        api["parse"](raw)


@pytest.mark.parametrize("value,expected", [(Fraction(1, 2), 1), (Fraction(-1, 2), -1),
    (Fraction(499999999999999999999999, 10**24), 0), (Fraction(500000000000000000000001, 10**24), 1)])
def test_exact_half_up_and_near_half_use_fraction(value, expected):
    assert api["half_up"](value) == expected


def test_stdlib_import_closure_has_no_runtime_or_application_dependency():
    allowed = {"__future__", "argparse", "hashlib", "json", "re", "fractions", "pathlib", "typing"}
    for node in ast.walk(ast.parse(HELPER.read_text())):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in allowed for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module and node.module.split(".")[0] in allowed
        assert not isinstance(node, ast.Assert)


@pytest.mark.parametrize("attack,label", [
    ("tenant", "tenant custody"), ("opening_unknown", "explicit known source opening"),
    ("opening_nonzero", "explicit known source opening"), ("missing_effect", "stage effects"),
    ("duplicate_report_effect", "complete report source_effect_ids"), ("cash_total", "independent group"),
    ("per_book_cash_total", "independent original Cash equation"), ("bool_zero", "bounded exact integer"),
    ("phase_actor", "three original human phases"), ("native_line", "actual native line bytes"),
    ("native_line_omission", "complete native entry lines"), ("native_status", "actual posted original native effect"),
    ("command_actor", "command actor/body/ACK"), ("command_ack", "command actor/body/ACK"),
    ("unknown_original_table", "tenant custody"), ("output_scope", "declared source opening"),
    ("orphan_dimension", "dimension population"), ("duplicate_dimension", "dimension population"),
    ("orphan_line", "line population"),
    ("review_actor", "actual original review row"), ("orphan_review", "review and command population"),
    ("orphan_command", "review and command population"), ("native_header", "native header snapshot"),
    ("source_columns", "source hierarchy columns"), ("source_identity", "source row identity"),
    ("link_actor", "owner link bijection"),
])
def test_rehashed_mutations_reach_independent_membership_or_amount_refusal(attack: str, label: str):
    proof = fixture()
    if attack == "tenant":
        proof["original_rows"]["effects"][0]["tenant_id"] = "other-tenant"
    elif attack.startswith("opening_"):
        proof["opening"]["basis" if attack == "opening_unknown" else "seller_minor"] = "unknown" if attack == "opening_unknown" else 1
    elif attack == "missing_effect":
        proof["stages"][0]["native_effects"].pop()
    elif attack == "duplicate_report_effect":
        proof["report"]["source_effect_ids"].append(proof["report"]["source_effect_ids"][0])
    elif attack == "cash_total":
        proof["cashflow"]["closing_minor"] = proof["cashflow"]["fx_on_cash_minor"] = 0
    elif attack == "per_book_cash_total":
        proof["cashflow"]["books"]["seller"]["closing_minor"] += 1
    elif attack == "bool_zero":
        proof["cashflow"]["operating_net_minor"] = False
    elif attack == "phase_actor":
        proof["stages"][0]["phases"][1]["actor_id"] = proof["stages"][0]["phases"][0]["actor_id"]
    elif attack == "native_line":
        proof["original_rows"]["lines"][0]["debit_minor"] += 1
    elif attack == "native_line_omission":
        proof["original_rows"]["lines"].pop()
    elif attack == "native_status":
        proof["original_rows"]["entries"][0]["status"] = "Draft"
    elif attack == "command_actor":
        proof["original_rows"]["commands"][0]["actor_id"] = "stranger"
    elif attack == "command_ack":
        proof["original_rows"]["commands"][0]["response_json"]["id"] = "other-original-plan"
    elif attack == "unknown_original_table":
        proof["original_rows"]["uncovered"] = []
    elif attack == "output_scope":
        proof["cashflow"]["scope"] = "whole-company"
    elif attack in {"orphan_dimension", "duplicate_dimension"}:
        dimensions = proof["original_rows"]["dimensions"]
        row = {"tenant_id": proof["qualified_scope"]["tenant_id"],
            "entry_line_id": "unknown" if attack == "orphan_dimension" else proof["original_rows"]["lines"][0]["id"],
            "dimension_id": "synthetic-extra-dimension", "dimension_value_id": "synthetic-extra-value"}
        dimensions.extend([row] if attack == "orphan_dimension" else [row, deepcopy(row)])
    elif attack == "orphan_line":
        row = deepcopy(proof["original_rows"]["lines"][0])
        row.update(id="unknown-line", entry_id="unknown-entry")
        proof["original_rows"]["lines"].append(row)
    elif attack == "review_actor":
        proof["original_rows"]["reviews"][0]["reviewer_actor_id"] = "other-human"
    elif attack in {"orphan_review", "orphan_command"}:
        rows = proof["original_rows"]["reviews" if attack == "orphan_review" else "commands"]
        row = deepcopy(rows[0])
        row["plan_id"] = "unknown-plan"
        rows.append(row)
    elif attack == "native_header":
        proof["original_rows"]["entries"][0]["posting_date"] = "2026-10-30"
    elif attack == "source_columns":
        proof["original_rows"]["source"][0]["workspace_id"] = "other-workspace"
    elif attack == "source_identity":
        proof["original_rows"]["source"][0]["id"] = "other-native-source"
    elif attack == "link_actor":
        proof["original_rows"]["links"][0]["posted_actor_id"] = "other-human"
    reseal(proof["report"], "report_digest")
    proof["cashflow"]["report_digest"] = proof["report"]["report_digest"]
    reseal(proof["cashflow"], "cashflow_digest")
    reseal(proof, "evidence_digest")
    with pytest.raises(ValueError, match=label):
        api["verify"](proof)


def test_balanced_rehashed_native_cash_mutation_reaches_independent_settlement_math():
    proof = fixture()
    stage = proof["stages"][1]
    plan = stage["plan"]
    entry = next(row for row in plan["entries"] if row["book"] == "seller")
    cash_id = proof["source"]["native_accounts"]["seller"]["cash"]["id"]
    party_id = proof["source"]["native_accounts"]["seller"]["party"]["id"]
    for row in entry["snapshot"]["lines"]:
        if row["account_id"] == cash_id:
            row["debit_minor"] += 1
        if row["account_id"] == party_id:
            row["credit_minor"] += 1
    assert sum(row["debit_minor"] - row["credit_minor"] for row in entry["snapshot"]["lines"]) == 0
    entry["validation_digest"] = api["digest"](entry["snapshot"])
    effect_id = plan["posting_effect_ids"]["seller"]
    effect = next(row for row in stage["native_effects"] if row["id"] == effect_id)
    effect.update(snapshot=deepcopy(entry["snapshot"]), validation_digest=entry["validation_digest"])
    raw_effect = next(row for row in proof["original_rows"]["effects"] if row["id"] == effect_id)
    raw_effect.update(snapshot_json=deepcopy(entry["snapshot"]), validation_digest=entry["validation_digest"])
    next(row for row in proof["original_rows"]["entries"] if row["id"] == entry["entry_id"])["validation_digest"] = entry["validation_digest"]
    for row in proof["original_rows"]["lines"]:
        if row["entry_id"] == entry["entry_id"]:
            original = next(member for member in entry["snapshot"]["lines"] if member["line_number"] == row["line_number"])
            row.update(debit_minor=original["debit_minor"], credit_minor=original["credit_minor"])
    plan["plan_digest"] = api["digest"]({key: value for key, value in plan.items() if key not in api["MUTABLE"]})
    next(row for row in proof["original_rows"]["plans"] if row["id"] == plan["id"])["payload"] = {
        key: value for key, value in plan.items() if key not in api["MUTABLE"] - {"plan_digest"}}
    for phase in stage["phases"]:
        phase["metadata_json"]["plan_digest"] = plan["plan_digest"]
        next(row for row in proof["original_rows"]["audit"] if row["id"] == phase["audit_event_id"])["metadata_json"] = deepcopy(phase["metadata_json"])
        next(row for row in proof["original_rows"]["outbox"] if row["event_id"] == phase["outbox_event_id"])["payload"] = {**phase["metadata_json"], "audit_event_id": phase["audit_event_id"]}
    for command in proof["original_rows"]["commands"]:
        if command["plan_id"] == plan["id"]:
            command["response_json"]["plan_digest"] = plan["plan_digest"]
    reseal(proof, "evidence_digest")
    with pytest.raises(ValueError, match="original settlement Cash business amount"):
        api["verify"](proof)


def test_cli_reads_at_most_budget_plus_one_before_hash_or_parse(tmp_path: Path, monkeypatch):
    from io import BytesIO

    reads = []
    class BoundedStream(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert size == 129
            return super().read(size)
    original = tmp_path / "oversized.json"
    output = tmp_path / "unexpected.json"
    original_open = Path.open
    def open_bound(path, *args, **kwargs):
        return BoundedStream(b"x" * 400) if path == original else original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", open_bound)
    monkeypatch.setitem(api["main"].__globals__, "MAX_BYTES", 128)
    monkeypatch.setattr(sys, "argv", [str(HELPER), str(original), "--sha256", "0" * 64, "--output", str(output)])
    with pytest.raises(ValueError, match="byte budget before hash/parse"):
        api["main"]()
    assert reads == [129] and not output.exists()
