"""Offline forged-proof regressions for the independently executable FX oracle."""
from __future__ import annotations

import copy
import hashlib
import json
import runpy
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/verify_operational_fx_cycle_oracle.py"
ORACLE = runpy.run_path(str(SCRIPT))
ERROR = ORACLE["VerificationError"]


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def seal(proof: dict) -> None:
    """Repair every hash after a forgery; arithmetic/native bindings must refuse."""
    source, plan = proof["source"], proof["plan"]
    native_source = ORACLE["money_projection"]({key: source[key] for key in ORACLE["SOURCE_FIELDS"]})
    proof["canonical_source_json"] = canonical(native_source)
    source["source_digest"] = hashlib.sha256(proof["canonical_source_json"].encode()).hexdigest()
    plan["source_digest"] = source["source_digest"]
    proof["canonical_snapshot_json"] = canonical(ORACLE["money_projection"](plan["snapshot"]))
    plan["validation_digest"] = hashlib.sha256(proof["canonical_snapshot_json"].encode()).hexdigest()
    proof["native_effect"]["validation_digest"] = plan["validation_digest"]
    native_plan = ORACLE["money_projection"]({key: plan[key] for key in ORACLE["PLAN_FIELDS"]})
    proof["canonical_plan_json"] = canonical(native_plan)
    plan["plan_digest"] = hashlib.sha256(proof["canonical_plan_json"].encode()).hexdigest()


def fixture_proofs() -> list[dict]:
    """Explicit hand-calculated journals; no production domain/repository imports."""
    tax = {"rate": "0.14", "source": "Browser reviewed synthetic tax", "version": "2026-v1", "policy_id": "BROWSER-SYNTHETIC-TAX",
           "account_code": "TAX", "country_code": "EG", "effective_to": "2026-12-31", "effective_from": "2026-01-01",
           "policy_digest": "a" * 64, "transaction_class": "synthetic-service"}
    request = {"taxes": [tax], "net_minor": "10001", "country_code": "EG", "transaction_class": "synthetic-service", "invoice_number": "BROWSER-FX",
               "original_rate": {"rate": "1.25", "source": "Browser original spot", "effective_at": "2026-10-01T12:00:00Z"},
               "foreign_currency_code": "EUR", "reason": "Synthetic original", "period_id": "period", "posting_date": "2026-10-01"}
    policy = {"currency_code": "EUR", "currency_precision": 2, "currency_registry_digest": "b" * 64,
              "currency_registry_version": "synthetic-v1", "currency_rounding_policy": "ROUND_HALF_UP"}
    lines = [[("AR", 14251, 0), ("REVENUE", 0, 12501), ("TAX", 0, 1750)],
             [("CASH", 5200, 0), ("AR", 0, 5000), ("GAIN", 0, 200)],
             [("AR", 740, 0), ("UGAIN", 0, 740)], [("AR", 0, 740), ("UGAIN", 740, 0)],
             [("CASH", 8881, 0), ("AR", 0, 9251), ("LOSS", 370, 0)]]
    monetary_lines = [[{"account_code": code, "debit_minor": str(debit), "credit_minor": str(credit)} for code, debit, credit in rows] for rows in lines]
    source = {"id": "FX-fixture", "invoice_id": "ARINV-fixture", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
              "preparer_actor_id": "erp-maker", "schema_version": "operational-fx-source-v1", "request": request,
              "foreign_policy": policy, "functional_policy": {**policy, "currency_code": "USD"}, "foreign_gross_minor": "11401",
              "foreign_net_minor": "10001", "foreign_tax_minor": "1400", "functional_gross_minor": "14251", "functional_net_minor": "12501",
              "functional_allocation_policy": "converted-cumulative-prefix-v1", "tax_components": [{**tax, "foreign_tax_minor": "1400", "functional_tax_minor": "1750"}],
              "lines": monetary_lines[0], "source_digest": ""}
    proofs = []
    for index, (kind, burden) in enumerate(zip(ORACLE["KINDS"], [14251, 5200, 740, 740, 9251], strict=True)):
        date = f"2026-10-0{index + 1}"
        reason = request["reason"] if index == 0 else "Synthetic valuation" if index in (2, 3) else "Synthetic settlement"
        command = {"kind": kind, **request} if index == 0 else {"kind": kind, "source_id": source["id"], "reason": reason, "period_id": "period", "posting_date": date}
        equation = {"lines": monetary_lines[index]}
        if index in (1, 4):
            rate = {"rate": "1.3" if index == 1 else "1.2", "source": "Browser settlement spot", "effective_at": f"{date}T12:00:00Z"}
            command.update(foreign_minor="4000" if index == 1 else "7401", settlement_rate=rate)
            equation.update(amount_minor=str(burden), foreign_minor=command["foreign_minor"], settlement_rate=rate, realized_fx_minor="200" if index == 1 else "-370",
                            foreign_before_minor="0" if index == 1 else "4000", foreign_after_minor="4000" if index == 1 else "11401",
                            historical_before_minor="0" if index == 1 else "5000", historical_after_minor="5000" if index == 1 else "14251",
                            functional_cash_minor="5200" if index == 1 else "8881", historical_release_minor="5000" if index == 1 else "9251")
        elif index == 2:
            rate = {"rate": "1.35", "source": "Browser closing spot", "effective_at": "2026-10-03T23:00:00Z"}
            command.update(closing_rate=rate, unrealized_gain_account_code="UGAIN", unrealized_loss_account_code="ULOSS")
            equation.update(amount_minor="740", closing_rate=rate, unrealized_fx_minor="740", foreign_before_minor="4000", historical_before_minor="5000",
                            valued_outstanding_minor="9991", foreign_outstanding_minor="7401", historical_outstanding_minor="9251",
                            unrealized_gain_account_code="UGAIN", unrealized_loss_account_code="ULOSS")
        elif index == 3:
            original = proofs[2]["plan"]
            command["original_revaluation_id"] = original["id"]
            equation.update(amount_minor="740", unrealized_fx_minor="-740", original_plan_digest=original["plan_digest"], original_revaluation_id=original["id"],
                            original_equation_digest=hashlib.sha256(canonical(ORACLE["money_projection"](original["equation"])).encode()).hexdigest(), original_posting_effect_id=original["posting_effect_id"])
        phases = [{"action": action, "actor_id": actor, "audit_event_id": f"AE-{index}-{phase}", "outbox_event_id": f"OBX-{index}-{phase}"}
                  for phase, (action, actor) in enumerate(zip(ORACLE["PHASE_ACTIONS"], ORACLE["PHASE_ACTORS"], strict=True))]
        entry = {**source["functional_policy"], "id": f"GLE-{index}", "entry_number": f"FX1-{index}", "description": reason, "journal_id": "JOURNAL",
                 "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "period_id": "period", "posting_date": date,
                 "preparer_actor_id": "erp-maker", "source_type": "Generated" if index == 3 else "Manual", "reverses_posting_id": "PST-2" if index == 3 else None,
                 "external_reference": "PST-2" if index == 3 else f"FX:{source['id']}:{kind}"}
        snapshot = {"schema_version": "finance-entry-review-v1", "entry": entry,
                    "lines": [{"account_id": f"ACC-{code}", "debit_minor": debit, "credit_minor": credit, "dimensions": {}, "description": reason, "line_number": number}
                              for number, (code, debit, credit) in enumerate(lines[index], 1)]}
        plan = {"id": f"FX1-{index}", "kind": kind, "reason": reason, "entry_id": entry["id"], "equation": equation, "sequence": index, "snapshot": snapshot,
                "period_id": "period", "posting_date": date, "amount_minor": str(burden), "currency_code": "USD", "currency_precision": 2,
                "source_id": source["id"], "source_digest": "", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
                "preparer_actor_id": "erp-maker", "command_request": command, "schema_version": "operational-fx-plan-v2" if index in (2, 3) else "operational-fx-plan-v1",
                "plan_digest": "", "validation_digest": "", "status": "Posted", "phase": 2, "reviewer_actor_id": "erp-checker", "posting_effect_id": f"PST-{index}",
                "receipt_id": f"ARRCT-{index}" if index in (1, 4) else None}
        proof = {"schema_version": "operational-fx-native-evidence-v1", "source": copy.deepcopy(source), "plan": plan, "phases": phases,
                 "native_effect": {"id": f"PST-{index}", "entry_id": entry["id"], "validation_digest": "", "posted_actor_id": "erp-poster",
                                   "audit_event_id": phases[-1]["audit_event_id"], "outbox_event_id": phases[-1]["outbox_event_id"]},
                 "totals": {"debit_minor": str(burden), "credit_minor": str(burden)}}
        seal(proof)
        proofs.append(proof)
    return proofs


def fixture_report(proofs: list[dict]) -> dict:
    population = {key: {"rows": rows, "sha256": "a" * 64} for key, rows in {
        "operational_fx_sources": 1, "operational_fx_plans": 5, "operational_fx_reviews": 5, "operational_fx_links": 5,
        "operational_fx_commands": 15, "finance_posting_effects": 5, "finance_entry_lines": 13, "ar_invoices": 1,
        "ar_receipts": 2, "ar_receipt_allocations": 2, "identity_users": 6}.items()}
    effects = {"source_id": proofs[0]["source"]["id"], "invoice_id": proofs[0]["source"]["invoice_id"], "native_invoice_status": "Paid", "source_plans": 5,
               "native_posting_effects": 5, "unrealized_fx_minor": ["740", "-740"], "foreign_currency": "EUR", "functional_currency": "USD",
               "foreign_gross_minor": "11401", "functional_gross_minor": "14251", "foreign_receipts_minor": ["4000", "7401"], "historical_releases_minor": ["5000", "9251"],
               "realized_fx_minor": ["200", "-370"], "account_balances_minor": {"AR": "0", "REVENUE": "-12501", "TAX": "-1750", "CASH": "14081", "GAIN": "-200", "LOSS": "370", "UGAIN": "0"}}
    snapshot = {"tables": population, "objects": {"functions": {"count": 1, "sha256": "a" * 64}}, "head": "0131_pg_fx_revaluation", "forced_rls_financial_tables": 45}
    report = {"status": "passed", "scenario": "operational-fx-tax", "source_commit": "a" * 40, "source_commit_after": "a" * 40,
              "source_sha256": "b" * 64, "built_web_sha256": "c" * 64, "tracked_status_before": "", "tracked_status_after": "", "role_privileges": [False, False],
              "revision": "0131_pg_fx_revaluation", "browser_counts": {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 0}, "persisted_effects": effects,
              "native_restore": {"status": "passed", "verified_effects": copy.deepcopy(effects), "tamper_refusals": 3, "dump_sha256": "d" * 64,
                                 "snapshot": snapshot, "probe_checkpoint": copy.deepcopy(snapshot)}}
    report.update(dict.fromkeys(("source_unchanged", "built_web_unchanged", "tracked_clean_before", "tracked_clean_after", "owned_container_removed", "owned_https_process_stopped"), True))
    return report


def fixture_manifest(proofs: list[dict], report: dict) -> dict:
    return {"status": "passed", "source_commit": report["source_commit"],
            "report_sha256": hashlib.sha256(json.dumps(report).encode()).hexdigest(),
            "native_effects": [{"kind": proof["plan"]["kind"], "plan_id": proof["plan"]["id"], "entry_id": proof["plan"]["entry_id"],
                                "effect_id": proof["native_effect"]["id"], "amount_minor": int(proof["plan"]["amount_minor"]),
                                "file_sha256": hashlib.sha256(json.dumps(proof).encode()).hexdigest()} for proof in proofs]}


def test_explicit_integer_fixture_and_original_native_inverse_pass() -> None:
    proofs = fixture_proofs()
    verified = ORACLE["verify_proofs"](proofs)
    report = fixture_report(proofs)
    ORACLE["verify_report"](report, verified, fixture_manifest(proofs, report))
    assert verified["account_balances_minor"]["AR"] == verified["account_balances_minor"]["UGAIN"] == 0
    assert verified["unique_audit_events"] == verified["unique_outbox_events"] == 20


@pytest.mark.parametrize("value,expected", [(Fraction(5, 2), 3), (Fraction(-5, 2), -3), (Fraction(249, 100), 2)])
def test_independent_rounding_has_exact_positive_and_negative_ties(value: Fraction, expected: int) -> None:
    assert ORACLE["half_up"](value) == expected
    assert ORACLE["convert"](123, "2", 3, 2) == 25


@pytest.mark.parametrize("attack,message", [
    ("public_projection", "Canonical seal/projection"), ("balanced_money", "rational journal"),
    ("closing_position", "Closing residual"), ("inverse_source", "Original inverse linkage"),
    ("native_account", "account identity"), ("inverse_dimension", "snapshot amount/line/dimensions"),
    ("self_review", "human phase"), ("duplicate_effect", "Duplicate/missing effect"),
    ("float_money", "canonical integer"),
])
def test_rehashed_forged_financial_proof_is_rejected(attack: str, message: str) -> None:
    proofs = fixture_proofs()
    proof = proofs[2]
    if attack == "public_projection":
        proof["plan"]["reason"] = "Changed public reason"
    elif attack == "balanced_money":
        proof["plan"]["equation"]["lines"][0]["debit_minor"] = "741"
        proof["plan"]["equation"]["lines"][1]["credit_minor"] = "741"
        seal(proof)
    elif attack == "closing_position":
        proof["plan"]["equation"]["valued_outstanding_minor"] = "9992"
        seal(proof)
    elif attack == "inverse_source":
        proof = proofs[3]
        proof["plan"]["snapshot"]["entry"].update(reverses_posting_id="PST-1", external_reference="PST-1")
        seal(proof)
    elif attack == "native_account":
        proof["plan"]["snapshot"]["lines"][0]["account_id"] = "ACC-substituted-AR"
        seal(proof)
    elif attack == "inverse_dimension":
        proof = proofs[3]
        proof["plan"]["snapshot"]["lines"][0]["dimensions"] = {"cost_center": "different"}
        seal(proof)
    elif attack == "self_review":
        proof["phases"][1]["actor_id"] = "erp-maker"
    elif attack == "duplicate_effect":
        proofs[4]["plan"]["posting_effect_id"] = proofs[4]["native_effect"]["id"] = "PST-1"
    else:
        proof["plan"]["equation"]["lines"][0]["debit_minor"] = 740.0
    with pytest.raises(ERROR, match=message):
        ORACLE["verify_proofs"](proofs)


@pytest.mark.parametrize("attack,message", [("cash", "native GL/AR"), ("restored_population", "population differs"),
    ("financial_checkpoint", "retained financial"), ("tamper_count", "restore oracle/barriers"), ("skipped", "Browser outcomes")])
def test_report_cannot_replace_the_actual_financial_or_restore_population(attack: str, message: str) -> None:
    proofs = fixture_proofs()
    report = fixture_report(proofs)
    manifest = fixture_manifest(proofs, report)
    if attack == "cash":
        report["persisted_effects"]["account_balances_minor"]["CASH"] = "14082"
    elif attack == "restored_population":
        for key in ("snapshot", "probe_checkpoint"):
            report["native_restore"][key]["tables"]["operational_fx_plans"]["rows"] = 4
    elif attack == "financial_checkpoint":
        report["native_restore"]["probe_checkpoint"]["tables"]["finance_posting_effects"]["sha256"] = "f" * 64
    elif attack == "tamper_count":
        report["native_restore"]["tamper_refusals"] = 2
    else:
        report["browser_counts"]["skipped"] = 1
    with pytest.raises(ERROR, match=message):
        ORACLE["verify_report"](report, ORACLE["verify_proofs"](proofs), manifest)


def test_post_restore_authentication_allows_only_identity_digest_with_same_population() -> None:
    proofs = fixture_proofs()
    report = fixture_report(proofs)
    manifest = fixture_manifest(proofs, report)
    report["native_restore"]["probe_checkpoint"]["tables"]["identity_users"]["sha256"] = "f" * 64
    ORACLE["verify_report"](report, ORACLE["verify_proofs"](proofs), manifest)
    report["native_restore"]["probe_checkpoint"]["tables"]["identity_users"]["rows"] = 5
    with pytest.raises(ERROR, match="retained financial"):
        ORACLE["verify_report"](report, ORACLE["verify_proofs"](proofs), manifest)


def test_unique_substituted_runtime_effect_cannot_escape_trusted_original_membership() -> None:
    proofs = fixture_proofs()
    report = fixture_report(proofs)
    manifest = fixture_manifest(proofs, report)
    manifest_blob = json.dumps(manifest).encode()
    original_plan_digest = proofs[4]["plan"]["plan_digest"]
    proofs[4]["plan"]["posting_effect_id"] = proofs[4]["native_effect"]["id"] = "PST-unique-invented-unposted"
    # Runtime-only IDs are absent from the sealed plan: old arithmetic/seal checks pass.
    verified = ORACLE["verify_proofs"](proofs)
    assert proofs[4]["plan"]["plan_digest"] == original_plan_digest
    assert len({proof["native_effect"]["id"] for proof in proofs}) == 5
    with pytest.raises(ERROR, match="Native effect identities differ"):
        ORACLE["verify_report"](report, verified, manifest)
    with pytest.raises(ERROR, match="trusted retained membership"):
        ORACLE["verify_membership"]([json.dumps(proof).encode() for proof in proofs], json.dumps(report).encode(),
                                   manifest_blob, hashlib.sha256(manifest_blob).hexdigest())


@pytest.mark.parametrize("attack,message", [("manifest", "manifest SHA256"), ("report", "Runtime report differs")])
def test_changing_manifest_or_runtime_report_cannot_replace_the_explicit_trust_anchor(attack: str, message: str) -> None:
    proofs = fixture_proofs()
    report = fixture_report(proofs)
    manifest = fixture_manifest(proofs, report)
    trusted_sha256 = hashlib.sha256(json.dumps(manifest).encode()).hexdigest()
    if attack == "manifest":
        manifest["native_effects"][4]["effect_id"] = "PST-forged"
    else:
        report["persisted_effects"]["native_posting_effects"] = 6
    with pytest.raises(ERROR, match=message):
        ORACLE["verify_membership"]([json.dumps(proof).encode() for proof in proofs], json.dumps(report).encode(),
                                   json.dumps(manifest).encode(), trusted_sha256)


def test_duplicate_json_key_is_rejected_even_if_a_hash_could_be_recomputed() -> None:
    with pytest.raises(ERROR, match="Duplicate JSON key"):
        ORACLE["decode"]('{"debit_minor":740,"debit_minor":741}')


@pytest.mark.parametrize("optimized", [False, True])
def test_standalone_cli_keeps_financial_checks_under_python_optimization(tmp_path: Path, optimized: bool) -> None:
    proofs = fixture_proofs()
    for index, proof in enumerate(proofs):
        (tmp_path / f"fx-proof-{index}.json").write_text(json.dumps(proof), encoding="utf-8")
    report = fixture_report(proofs)
    (tmp_path / "cycle.json").write_text(json.dumps(report), encoding="utf-8")
    manifest_blob = json.dumps(fixture_manifest(proofs, report)).encode()
    (tmp_path / "manifest.json").write_bytes(manifest_blob)
    command = [sys.executable, *(["-O"] if optimized else []), str(SCRIPT), "--proof-directory", str(tmp_path), "--cycle-report", str(tmp_path / "cycle.json"),
               "--proof-manifest", str(tmp_path / "manifest.json"), "--proof-manifest-sha256", hashlib.sha256(manifest_blob).hexdigest()]
    positive = tmp_path / "positive.json"
    run = subprocess.run([*command, "--report", str(positive)], check=False, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(positive.read_text())["status"] == "passed"
    proofs[2]["plan"]["equation"]["valued_outstanding_minor"] = "9992"
    seal(proofs[2])
    (tmp_path / "fx-proof-2.json").write_text(json.dumps(proofs[2]), encoding="utf-8")
    negative = tmp_path / "negative.json"
    run = subprocess.run([*command, "--report", str(negative)], check=False, capture_output=True, text=True)
    assert run.returncode == 1
    assert json.loads(negative.read_text())["status"] == "failed"
    before = negative.read_bytes()
    run = subprocess.run([*command, "--report", str(negative)], check=False, capture_output=True, text=True)
    assert run.returncode != 0 and negative.read_bytes() == before
