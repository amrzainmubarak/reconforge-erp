"""Independent synthetic journals, adversarial downloaded proof and isolated CLI."""
import copy
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/verify_intercompany_cycle_oracle.py"
SPEC = importlib.util.spec_from_file_location("independent_ic_oracle", SCRIPT)
assert SPEC and SPEC.loader
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


def packets() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    policy = {"currency_code": "USD", "currency_precision": 2, "currency_rounding_policy": "ROUND_HALF_UP",
              "currency_registry_version": "synthetic-v1", "currency_registry_digest": "a" * 64}
    request = {"workspace_id": "work", "organization_id": "org", "seller_entity_id": "A", "buyer_entity_id": "B", "adjustment_entity_id": "G",
               "amount_minor": "10001", "receivable_account_code": "AR", "payable_account_code": "AP", "revenue_account_code": "INCOME",
               "expense_account_code": "EXPENSE", "cash_account_code": "CASH"}
    source = {"id": "source", "monetary_policy": policy, "request": request, "preparer_actor_id": "maker"}
    source["source_digest"] = oracle.sha(oracle.canonical(source))
    journals = [({"seller": [("AR", 10001, 0), ("INCOME", 0, 10001)], "buyer": [("EXPENSE", 10001, 0), ("AP", 0, 10001)]}, 0, 0),
                ({"seller": [("CASH", 3000, 0), ("AR", 0, 3000)], "buyer": [("AP", 3000, 0), ("CASH", 0, 3000)]}, 0, 3000),
                ({"adjustment": [("INCOME", 10001, 0), ("EXPENSE", 0, 10001), ("AP", 7001, 0), ("AR", 0, 7001)]}, 3000, 0)]
    proofs = []
    accounts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stage, (books, settled, cash) in enumerate(journals):
        plan_id = f"IC1-{stage:032x}"
        amount = max(sum(row[1] for row in rows) for rows in books.values())
        plan: dict[str, Any] = {"id": plan_id, "source_id": "source", "source_digest": source["source_digest"], "kind": ("recognize", "settle", "eliminate")[stage],
            "sequence": stage, "workspace_id": "work", "organization_id": "org", "seller_entity_id": "A", "buyer_entity_id": "B", "adjustment_entity_id": "G",
            "currency_code": "USD", "currency_precision": 2, "period_id": "period", "posting_date": f"2026-10-0{stage + 3}", "preparer_actor_id": "maker", "amount_minor": str(amount),
            "equation": {"kind": ("recognize", "settle", "eliminate")[stage], "original_minor": "10001", "settled_before_minor": str(settled), "settlement_minor": str(cash),
                         "outstanding_before_minor": str(10001 - settled), "amount_minor": str(amount), "books": {}}, "entries": []}
        raws, natives = [], []
        for book, rows in books.items():
            entity = {"seller": "A", "buyer": "B", "adjustment": "G"}[book]
            entry_id, effect_id = f"entry-{stage}-{book}", f"effect-{stage}-{book}"
            lines = [{"line_number": number, "account_id": "account-" + account, "debit_minor": str(debit), "credit_minor": str(credit), "dimensions": {}}
                     for number, (account, debit, credit) in enumerate(rows, 1)]
            snapshot = {"entry": {"id": entry_id, "legal_entity_id": entity, "entry_number": plan_id.upper() + {"seller": "-A", "buyer": "-B", "adjustment": "-G"}[book],
                                  "workspace_id": "work", "organization_id": "org", "preparer_actor_id": "maker",
                                  "period_id": "period", "posting_date": plan["posting_date"], "source_type": "Manual", "reverses_posting_id": None, **policy}, "lines": lines}
            raw = oracle.canonical(snapshot)
            digest = oracle.sha(raw)
            plan["entries"].append({"book": book, "entry_id": entry_id, "snapshot": snapshot, "validation_digest": digest})
            plan["equation"]["books"][book] = [{"account_code": account, "debit_minor": str(debit), "credit_minor": str(credit)} for account, debit, credit in rows]
            raws.append(raw)
            natives.append({"id": effect_id, "entry_id": entry_id, "validation_digest": digest, "snapshot": snapshot, "posted_actor_id": "poster",
                            "audit_event_id": f"native-audit-{stage}-{book}", "outbox_event_id": f"native-outbox-{stage}-{book}"})
            for number, (account, debit, credit) in enumerate(rows, 1):
                accounts[account].append({"effect_id": effect_id, "entry_id": entry_id, "line_number": number, "legal_entity_id": entity,
                                          "debit_minor": str(debit), "credit_minor": str(credit)})
        canonical = oracle.canonical(plan)
        plan.update(plan_digest=oracle.sha(canonical), phase=2, status="Posted", reviewer_actor_id="checker", posted_actor_id="poster",
                    posting_effect_ids={entry["book"]: effect["id"] for entry, effect in zip(plan["entries"], natives, strict=True)})
        proofs.append({"schema_version": "intercompany-native-evidence-v1", "source": copy.deepcopy(source), "plan": plan,
                       "canonical_source_json": oracle.canonical({k: v for k, v in source.items() if k != "source_digest"}), "canonical_plan_json": canonical,
                       "canonical_snapshot_jsons": raws, "native_effects": natives,
                       "phases": [{"action": "intercompany_operation_" + action, "actor_id": actor, "audit_event_id": f"audit-{stage}-{index}", "outbox_event_id": f"outbox-{stage}-{index}"}
                                  for index, (action, actor) in enumerate(zip(("prepared", "reviewed", "posted"), ("maker", "checker", "poster"), strict=True))]})
    report: dict[str, Any] = {"schema_version": "intercompany-native-group-report-v1", "reporting_scope": "explicit-three-book-management", "workspace_id": "work", "organization_id": "org",
        "source_digest": source["source_digest"], "adjustment_plan_digest": proofs[-1]["plan"]["plan_digest"], "effect_count": 5, "currency_policy": policy,
        "trial_balance": [{"account_code": code, "account_id": "account-" + code, "closing": {"balance_minor": "0"}, "postings": lines} for code, lines in sorted(accounts.items())],
        "income_statement": {"income_minor": "0", "expense_minor": "0", "result_minor": "0"}, "cash_net_movements": {"opening_minor": "0", "activity_minor": "0", "closing_minor": "0"},
        "balance_sheet": {"assets_minor": "0", "liabilities_minor": "0", "equity_minor": "0", "accumulated_unclosed_result_minor": "0", "balanced": True}}
    report.update(period_id="period", period_start="2026-10-01", period_end="2026-10-31", as_of_date="2026-10-05")
    classification = {"AR": ("Asset", "CurrentAsset", False), "CASH": ("Asset", "CurrentAsset", True), "AP": ("Liability", "CurrentLiability", False),
                      "INCOME": ("Income", "Income", False), "EXPENSE": ("Expense", "Expense", False)}
    parties = []
    for entity in ("A", "B", "G"):
        positions = {}
        trial = []
        effects: set[str] = set()
        for code, lines in sorted(accounts.items()):
            contributed = [line for line in lines if line["legal_entity_id"] == entity]
            if not contributed:
                continue
            dr, cr = sum(int(line["debit_minor"]) for line in contributed), sum(int(line["credit_minor"]) for line in contributed)
            positions[code] = dr - cr
            effect_count = {line["effect_id"] for line in contributed}
            effects.update(effect_count)
            kind, section, is_cash = classification[code]
            def position(debit: int, credit: int) -> dict[str, str]:
                return {"debit_minor": str(debit), "credit_minor": str(credit), "balance_minor": str(debit - credit),
                        "debit_balance_minor": str(max(debit - credit, 0)), "credit_balance_minor": str(max(credit - debit, 0))}
            trial.append({"account_code": code, "account_id": "account-" + code, "account_type": kind, "section": section, "is_cash": is_cash,
                          "opening": position(0, 0), "activity": position(dr, cr), "closing": position(dr, cr),
                          "postings": [{k: v for k, v in line.items() if k != "legal_entity_id"} | {"phase": "activity"} for line in contributed]})
        income, expense, cash = -positions.get("INCOME", 0), positions.get("EXPENSE", 0), positions.get("CASH", 0)
        party = {"contract_version": "financial-reporting-v1", "legal_entity_id": entity, "map_id": "map-" + entity,
                 **{k: report[k] for k in ("workspace_id", "organization_id", "period_id", "period_start", "period_end", "as_of_date", "currency_policy")},
                 "effect_count": len(effects), "trial_balance": {"accounts": trial},
                 "income_statement": {"income_minor": str(income), "expense_minor": str(expense), "result_minor": str(income - expense)},
                 "balance_sheet": {"assets_minor": str(positions.get("AR", 0) + cash), "liabilities_minor": str(-positions.get("AP", 0)), "equity_minor": "0",
                                   "accumulated_unclosed_result_minor": str(income - expense), "balanced": True},
                 "cash_movements": {"opening_minor": "0", "activity_minor": str(cash), "closing_minor": str(cash)}}
        party["report_digest"] = oracle.sha(oracle.canonical(party))
        parties.append(party)
    report["entity_reports"] = parties
    report["report_digest"] = oracle.sha(oracle.canonical(report))
    return proofs, report


def test_independent_original_partial_and_group_journals_are_exact() -> None:
    proofs, report = packets()
    result = oracle.verify(proofs, report)
    assert (result["original_minor"], result["cash_minor"], result["residual_minor"], result["group_debit_minor"]) == ("10001", "3000", "7001", "17002")
    assert result["original_party_balances_minor"]["A:AR"] == "7001"
    assert result["original_party_balances_minor"]["B:AP"] == "-7001"
    assert len(result["native_effects"]) == 5 and not result["external_attestation"]


@pytest.mark.parametrize("attack", ["half_pair", "same_human", "runtime_effect", "native_money", "group_line", "noncanonical", "duplicate_report_line", "duplicate_empty_account", "party_position", "party_effect"])
def test_financial_or_population_tampering_is_rejected(attack: str) -> None:
    proofs, report = packets()
    if attack == "half_pair":
        proofs[0]["native_effects"].pop()
    elif attack == "same_human":
        proofs[1]["plan"]["posted_actor_id"] = "checker"
    elif attack == "runtime_effect":
        proofs[2]["plan"]["posting_effect_ids"]["adjustment"] = "invented-unique-effect"
        proofs[2]["native_effects"][0]["id"] = "invented-unique-effect"
    elif attack == "native_money":
        proofs[0]["native_effects"][0]["snapshot"]["lines"][0]["debit_minor"] = "10000"
    elif attack == "group_line":
        report["trial_balance"][0]["postings"][0]["debit_minor"] = "1"
        report["report_digest"] = oracle.sha(oracle.canonical({k: v for k, v in report.items() if k != "report_digest"}))
    elif attack == "noncanonical":
        proofs[0]["source"]["request"]["amount_minor"] = "010001"
    elif attack == "duplicate_report_line":
        report["trial_balance"][0]["postings"].append(copy.deepcopy(report["trial_balance"][0]["postings"][0]))
        report["report_digest"] = oracle.sha(oracle.canonical({k: v for k, v in report.items() if k != "report_digest"}))
    elif attack == "duplicate_empty_account":
        report["trial_balance"].append({**copy.deepcopy(report["trial_balance"][0]), "postings": []})
        report["report_digest"] = oracle.sha(oracle.canonical({k: v for k, v in report.items() if k != "report_digest"}))
    else:
        party = report["entity_reports"][0]
        if attack == "party_position":
            party["balance_sheet"]["assets_minor"] = "10000"
            party["trial_balance"]["accounts"][0]["closing"]["balance_minor"] = "7000"
        else:
            party["trial_balance"]["accounts"][0]["postings"][0]["effect_id"] = "invented-original-party-effect"
        party["report_digest"] = oracle.sha(oracle.canonical({k: v for k, v in party.items() if k != "report_digest"}))
        report["report_digest"] = oracle.sha(oracle.canonical({k: v for k, v in report.items() if k != "report_digest"}))
    with pytest.raises(ValueError):
        oracle.verify(proofs, report)


def test_unique_json_parser_and_boolean_money_refuse_silent_coercion() -> None:
    for raw in ('{"a":1,"a":2}', '{"a":1.0}', '{"a":NaN}'):
        with pytest.raises(ValueError):
            oracle.load(raw)
    with pytest.raises(ValueError):
        oracle.money(True)


@pytest.mark.parametrize("optimized", [False, True])
def test_isolated_cli_binds_original_bytes_and_preserves_existing_output(tmp_path: Path, optimized: bool) -> None:
    proofs, report = packets()
    for name, value in zip(oracle.FILES, [*proofs, report], strict=True):
        (tmp_path / name).write_text(json.dumps(value), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({name: oracle.sha((tmp_path / name).read_bytes()) for name in oracle.FILES}), encoding="utf-8")
    target = tmp_path / "result.json"
    command = [sys.executable, "-I", *(["-O"] if optimized else []), str(SCRIPT), "--proof-directory", str(tmp_path), "--report", str(target), "--manifest", str(manifest), "--trusted-manifest-sha256", oracle.sha(manifest.read_bytes())]
    run = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr
    assert json.loads(target.read_text())["financial_verification"] == "passed"
    original = target.read_bytes()
    assert subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=10).returncode != 0
    assert target.read_bytes() == original
