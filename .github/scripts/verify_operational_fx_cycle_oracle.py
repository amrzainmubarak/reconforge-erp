"""Offline independent rational oracle for the five-stage synthetic FX browser fixture.

Requires only the Python standard library. Reads fx-proof-0..4.json plus the
actual browser/restore report and a previously retained proof manifest, whose
trusted SHA256 must be supplied separately. Never imports ReconForge or contacts
a database. Membership is bound to that explicit trust anchor; hashes do not
provide an external attestation of the manifest's origin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

KINDS = ("recognize", "settle", "revalue", "reverse_revaluation", "settle")
SOURCE_FIELDS = frozenset(["foreign_gross_minor", "foreign_net_minor", "foreign_policy", "foreign_tax_minor", "functional_allocation_policy", "functional_gross_minor", "functional_net_minor", "functional_policy", "id", "invoice_id", "legal_entity_id", "lines", "organization_id", "preparer_actor_id", "request", "schema_version", "tax_components", "workspace_id"])
PLAN_FIELDS = frozenset(["amount_minor", "command_request", "currency_code", "currency_precision", "entry_id", "equation", "id", "kind", "legal_entity_id", "organization_id", "period_id", "posting_date", "preparer_actor_id", "reason", "schema_version", "sequence", "snapshot", "source_digest", "source_id", "workspace_id"])
PLAN_RUNTIME_FIELDS = frozenset(["plan_digest", "validation_digest", "phase", "status", "reviewer_actor_id", "posting_effect_id", "receipt_id"])
POLICY_FIELDS = ("currency_code", "currency_precision", "currency_registry_digest", "currency_registry_version", "currency_rounding_policy")
PHASE_ACTIONS = ("operational_fx_prepared", "operational_fx_reviewed", "operational_fx_posted", "finance_entry_posted")
PHASE_ACTORS = ("erp-maker", "erp-checker", "erp-poster", "erp-poster")


class VerificationError(ValueError):
    """The supplied fixture/evidence does not satisfy the independent contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise VerificationError(f"Non-finite JSON number: {value}")


def decode(value: str | bytes) -> Any:
    return json.loads(value, object_pairs_hook=unique_object, parse_constant=reject_constant)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def integer(value: Any) -> int:
    require(type(value) is int or isinstance(value, str) and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) is not None,
            "Minor units require a canonical integer, never bool/float")
    return int(value)


def half_up(value: Fraction) -> int:
    """Independent integer quotient/remainder rounding, including negative ties."""
    sign = -1 if value < 0 else 1
    quotient, remainder = divmod(abs(value.numerator), value.denominator)
    return sign * (quotient + (2 * remainder >= value.denominator))


def money_projection(value: Any) -> Any:
    """The wire exports minor units as strings; sealed native JSON uses integers."""
    if isinstance(value, dict):
        return {key: integer(item) if key.endswith("_minor") else money_projection(item) for key, item in value.items()}
    if isinstance(value, list):
        return [money_projection(item) for item in value]
    return value


def convert(amount: int, rate: str, foreign_precision: int = 2, functional_precision: int = 2) -> int:
    require(isinstance(rate, str) and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", rate) is not None and Fraction(rate) > 0,
            "A positive retained decimal rate is required")
    return half_up(Fraction(amount) * Fraction(rate) * Fraction(10 ** functional_precision, 10 ** foreign_precision))


def journal(lines: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
    result = [(line["account_code"], integer(line["debit_minor"]), integer(line["credit_minor"])) for line in lines]
    require(all(isinstance(code, str) and code and debit >= 0 and credit >= 0 and (debit > 0) != (credit > 0)
                for code, debit, credit in result), "Invalid financial line")
    require(len({row[0] for row in result}) == len(result), "Duplicate fixture account line")
    return result


def rational_oracle(source: dict[str, Any]) -> dict[str, Any]:
    request = source["request"]
    require(request["net_minor"] == "10001" and request["foreign_currency_code"] == "EUR"
            and request["country_code"] == "EG" and request["transaction_class"] == "synthetic-service"
            and request["invoice_number"] == "BROWSER-FX", "Different synthetic fixture source")
    require(request["original_rate"] == {"rate": "1.25", "source": "Browser original spot", "effective_at": "2026-10-01T12:00:00Z"},
            "Original historical rate provenance differs")
    require(len(request["taxes"]) == 1, "Exactly one retained synthetic tax component is required")
    tax_policy = request["taxes"][0]
    require(tax_policy["rate"] == "0.14" and tax_policy["country_code"] == request["country_code"]
            and tax_policy["transaction_class"] == request["transaction_class"] and tax_policy["policy_id"] == "BROWSER-SYNTHETIC-TAX"
            and tax_policy["version"] == "2026-v1" and tax_policy["effective_from"] == "2026-01-01"
            and tax_policy["effective_to"] == "2026-12-31" and tax_policy["account_code"] == "TAX"
            and re.fullmatch(r"[a-f0-9]{64}", tax_policy["policy_digest"]) is not None, "Effective synthetic tax policy differs")
    foreign, functional = source["foreign_policy"], source["functional_policy"]
    require(foreign["currency_code"] == "EUR" and functional["currency_code"] == "USD"
            and type(foreign["currency_precision"]) is int and type(functional["currency_precision"]) is int
            and foreign["currency_precision"] == functional["currency_precision"] == 2
            and foreign["currency_rounding_policy"] == functional["currency_rounding_policy"] == "ROUND_HALF_UP"
            and foreign["currency_registry_digest"] == functional["currency_registry_digest"]
            and re.fullmatch(r"[a-f0-9]{64}", functional["currency_registry_digest"]) is not None
            and foreign["currency_registry_version"] == functional["currency_registry_version"]
            and functional["currency_registry_version"], "Original currency precision/rounding/registry differs")
    net = integer(request["net_minor"])
    tax = half_up(Fraction(net) * Fraction(tax_policy["rate"]))
    gross = net + tax
    original_rate = request["original_rate"]["rate"]
    functional_net, functional_gross = convert(net, original_rate), convert(gross, original_rate)
    functional_tax = functional_gross - functional_net
    require(all(integer(source[key]) == expected for key, expected in {
        "foreign_net_minor": net, "foreign_tax_minor": tax, "foreign_gross_minor": gross,
        "functional_net_minor": functional_net, "functional_gross_minor": functional_gross}.items()), "Original rational source oracle differs")
    require(source["tax_components"] == [{**tax_policy, "foreign_tax_minor": str(tax), "functional_tax_minor": str(functional_tax)}]
            and source["functional_allocation_policy"] == "converted-cumulative-prefix-v1", "Original cumulative tax provenance differs")
    first_foreign, second_foreign = 4000, gross - 4000
    first_release = convert(first_foreign, original_rate)
    second_release = functional_gross - first_release
    first_cash, second_cash = convert(first_foreign, "1.3"), convert(second_foreign, "1.2")
    closing = convert(second_foreign, "1.35")
    delta = closing - second_release
    lines = [
        [("AR", functional_gross, 0), ("REVENUE", 0, functional_net), ("TAX", 0, functional_tax)],
        [("CASH", first_cash, 0), ("AR", 0, first_release), ("GAIN", 0, first_cash - first_release)],
        [("AR", delta, 0), ("UGAIN", 0, delta)],
        [("AR", 0, delta), ("UGAIN", delta, 0)],
        [("CASH", second_cash, 0), ("AR", 0, second_release), ("LOSS", second_release - second_cash, 0)],
    ]
    return {"lines": lines, "burdens": [functional_gross, first_cash, delta, delta, second_release],
            "foreign_gross": gross, "functional_gross": functional_gross, "foreign_receipts": [first_foreign, second_foreign],
            "historical_releases": [first_release, second_release], "realized": [first_cash - first_release, second_cash - second_release],
            "closing": closing, "delta": delta}


def verify_proofs(proofs: list[dict[str, Any]]) -> dict[str, Any]:
    require(len(proofs) == 5, "Exactly five proofs are required")
    source = proofs[0]["source"]
    require(set(source) == SOURCE_FIELDS | {"source_digest"} and source["schema_version"] == "operational-fx-source-v1", "Source projection fields differ")
    oracle = rational_oracle(source)
    require(journal(source["lines"]) == oracle["lines"][0], "Original source journal differs")
    accounts: dict[str, str] = {}
    identities: dict[str, set[str]] = {key: set() for key in ("plan", "entry", "effect", "audit", "outbox", "receipt")}
    balances: dict[str, int] = {}
    summaries = []
    for index, proof in enumerate(proofs):
        plan, native = proof["plan"], proof["native_effect"]
        require(proof["schema_version"] == "operational-fx-native-evidence-v1" and proof["source"] == source,
                "Source/evidence identity changed between stages")
        require(set(plan) == PLAN_FIELDS | PLAN_RUNTIME_FIELDS, "Plan projection fields differ")
        for key, expected, document in (
            ("canonical_source_json", source["source_digest"], {key: source[key] for key in SOURCE_FIELDS}),
            ("canonical_plan_json", plan["plan_digest"], {key: plan[key] for key in PLAN_FIELDS}),
            ("canonical_snapshot_json", plan["validation_digest"], plan["snapshot"]),
        ):
            require(isinstance(proof[key], str) and proof[key] == canonical(decode(proof[key]))
                    and digest(proof[key]) == expected and proof[key] == canonical(money_projection(document)), f"Canonical seal/projection mismatch: {key}")
        require(plan["kind"] == KINDS[index] and type(plan["sequence"]) is int and plan["sequence"] == index
                and type(plan["phase"]) is int and plan["phase"] == 2 and plan["status"] == "Posted"
                and plan["schema_version"] == ("operational-fx-plan-v2" if index in (2, 3) else "operational-fx-plan-v1"), "Incomplete or unordered native plans")
        require(plan["source_id"] == source["id"] and plan["source_digest"] == source["source_digest"]
                and plan["currency_code"] == "USD" and type(plan["currency_precision"]) is int and plan["currency_precision"] == 2,
                "Plan source/currency policy mismatch")
        require(plan["preparer_actor_id"] == source["preparer_actor_id"] == "erp-maker" and plan["reviewer_actor_id"] == "erp-checker"
                and native["posted_actor_id"] == "erp-poster", "Three distinct humans are absent")
        command = plan["command_request"]
        require(command["kind"] == plan["kind"] and command["posting_date"] == plan["posting_date"] == f"2026-10-0{index + 1}"
                and command["reason"] == plan["reason"] and command["period_id"] == plan["period_id"], "Retained command/date mismatch")
        require(command == {"kind": "recognize", **source["request"]} if index == 0 else command["source_id"] == source["id"], "Retained command source mismatch")
        actual_lines = journal(plan["equation"]["lines"])
        require(actual_lines == oracle["lines"][index] and integer(plan["amount_minor"]) == oracle["burdens"][index], "Independent rational journal/turnover differs")
        require(proof["totals"] == {"debit_minor": str(oracle["burdens"][index]), "credit_minor": str(oracle["burdens"][index])}, "Native debit/credit totals differ")
        snapshot = plan["snapshot"]
        entry = snapshot["entry"]
        require(snapshot["schema_version"] == "finance-entry-review-v1" and entry["id"] == plan["entry_id"] == native["entry_id"]
                and entry["entry_number"] == plan["id"].upper() and entry["posting_date"] == plan["posting_date"]
                and entry["period_id"] == plan["period_id"] and entry["preparer_actor_id"] == "erp-maker"
                and entry["journal_id"] == proofs[0]["plan"]["snapshot"]["entry"]["journal_id"]
                and entry["description"] == (proofs[2]["plan"]["reason"] if index == 3 else plan["reason"]), "Native snapshot header differs")
        require(type(entry["currency_precision"]) is int and all(entry[key] == source["functional_policy"][key] for key in POLICY_FIELDS), "Native original currency policy changed")
        for key in ("workspace_id", "organization_id", "legal_entity_id"):
            require(entry[key] == plan[key] == source[key], "Native tenant/entity scope changed")
        require(entry["source_type"] == ("Generated" if index == 3 else "Manual"), "Native source type differs")
        original_effect = proofs[2]["native_effect"]["id"]
        require(entry["reverses_posting_id"] == (original_effect if index == 3 else None)
                and entry["external_reference"] == (original_effect if index == 3 else f"FX:{source['id']}:{plan['kind']}"), "Original inverse linkage differs")
        require(len(snapshot["lines"]) == len(actual_lines), "Native snapshot line population differs")
        for number, (line, (code, debit, credit)) in enumerate(zip(snapshot["lines"], actual_lines, strict=True), 1):
            require(type(line["line_number"]) is int and line["line_number"] == number and integer(line["debit_minor"]) == debit
                    and integer(line["credit_minor"]) == credit and line["dimensions"] == {}, "Native snapshot amount/line/dimensions differ")
            require(isinstance(line["account_id"], str) and line["account_id"], "Missing native account")
            accounts.setdefault(code, line["account_id"])
            require(accounts[code] == line["account_id"] and len(set(accounts.values())) == len(accounts), "Native account identity changed")
            balances[code] = balances.get(code, 0) + debit - credit
        phases = proof["phases"]
        require([phase["actor_id"] for phase in phases] == list(PHASE_ACTORS)
                and [phase["action"] for phase in phases] == list(PHASE_ACTIONS), "Native human phase evidence differs")
        require(native["id"] == plan["posting_effect_id"] and native["validation_digest"] == plan["validation_digest"]
                and native["audit_event_id"] == phases[-1]["audit_event_id"] and native["outbox_event_id"] == phases[-1]["outbox_event_id"], "Native effect seal/phase linkage differs")
        for label, value in (("plan", plan["id"]), ("entry", plan["entry_id"]), ("effect", native["id"]),
                             *((label, phase[f"{label}_event_id"]) for phase in phases for label in ("audit", "outbox"))):
            require(isinstance(value, str) and value and value not in identities[label], f"Duplicate/missing {label} identity")
            identities[label].add(value)
        if index in (1, 4):
            receipt = plan["receipt_id"]
            require(isinstance(receipt, str) and receipt and receipt not in identities["receipt"], "Duplicate/missing receipt identity")
            identities["receipt"].add(receipt)
        else:
            require(plan["receipt_id"] is None, "Valuation/recognition mutated native receipts")
        summaries.append({"kind": plan["kind"], "plan_id": plan["id"], "entry_id": plan["entry_id"], "effect_id": native["id"], "amount_minor": oracle["burdens"][index]})
    first, closing, inverse, last = (proofs[index]["plan"] for index in (1, 2, 3, 4))
    for plan, position, foreign_before, historical_before in ((first, 0, 0, 0), (last, 1, 4000, 5000)):
        equation, command = plan["equation"], plan["command_request"]
        require(command["settlement_rate"] == {"rate": "1.3" if position == 0 else "1.2", "source": "Browser settlement spot",
                "effective_at": "2026-10-02T12:00:00Z" if position == 0 else "2026-10-05T12:00:00Z"}
                and equation["settlement_rate"] == command["settlement_rate"], "Settlement historical rate provenance differs")
        expected = {"foreign_minor": oracle["foreign_receipts"][position], "historical_release_minor": oracle["historical_releases"][position],
                    "foreign_before_minor": foreign_before, "historical_before_minor": historical_before, "realized_fx_minor": oracle["realized"][position],
                    "foreign_after_minor": foreign_before + oracle["foreign_receipts"][position],
                    "historical_after_minor": historical_before + oracle["historical_releases"][position],
                    "functional_cash_minor": convert(oracle["foreign_receipts"][position], command["settlement_rate"]["rate"]), "amount_minor": integer(plan["amount_minor"])}
        require(integer(command["foreign_minor"]) == expected["foreign_minor"] and all(integer(equation[key]) == value for key, value in expected.items()), "Cumulative settlement rational equation differs")
    require(closing["command_request"]["closing_rate"] == {"rate": "1.35", "source": "Browser closing spot", "effective_at": "2026-10-03T23:00:00Z"}
            and closing["equation"]["closing_rate"] == closing["command_request"]["closing_rate"], "Closing historical rate provenance differs")
    require(closing["equation"]["unrealized_gain_account_code"] == closing["command_request"]["unrealized_gain_account_code"] == "UGAIN"
            and closing["equation"]["unrealized_loss_account_code"] == closing["command_request"]["unrealized_loss_account_code"] == "ULOSS", "Closing gain/loss account provenance differs")
    require(all(integer(closing["equation"][key]) == value for key, value in {
        "amount_minor": oracle["delta"], "unrealized_fx_minor": oracle["delta"], "foreign_before_minor": 4000, "historical_before_minor": 5000,
        "foreign_outstanding_minor": oracle["foreign_receipts"][1], "historical_outstanding_minor": oracle["historical_releases"][1], "valued_outstanding_minor": oracle["closing"]}.items()), "Closing residual rational equation differs")
    require(inverse["command_request"]["original_revaluation_id"] == inverse["equation"]["original_revaluation_id"] == closing["id"]
            and inverse["equation"]["original_plan_digest"] == closing["plan_digest"]
            and inverse["equation"]["original_equation_digest"] == digest(canonical(money_projection(closing["equation"])))
            and inverse["equation"]["original_posting_effect_id"] == closing["posting_effect_id"]
            and integer(inverse["equation"]["unrealized_fx_minor"]) == -oracle["delta"], "Original valuation inverse provenance differs")
    for original, reversed_line in zip(closing["snapshot"]["lines"], inverse["snapshot"]["lines"], strict=True):
        require(reversed_line == {**original, "debit_minor": original["credit_minor"], "credit_minor": original["debit_minor"]}, "Native inverse changed original account/dimension/description")
    require(sum(balances.values()) == balances["AR"] == balances["UGAIN"] == 0, "Final AR/unrealized/GL conservation differs")
    return {"native_effects": summaries, "unique_audit_events": len(identities["audit"]), "unique_outbox_events": len(identities["outbox"]),
            "account_balances_minor": balances, "source_id": source["id"], "invoice_id": source["invoice_id"],
            "foreign_gross_minor": oracle["foreign_gross"], "functional_gross_minor": oracle["functional_gross"],
            "foreign_receipts_minor": oracle["foreign_receipts"], "historical_releases_minor": oracle["historical_releases"],
            "realized_fx_minor": oracle["realized"], "closing_value_minor": oracle["closing"], "unrealized_difference_minor": oracle["delta"]}


def verify_membership(proof_blobs: list[bytes], report_blob: bytes, manifest_blob: bytes, trusted_sha256: str) -> dict[str, Any]:
    require(re.fullmatch(r"[a-f0-9]{64}", trusted_sha256) is not None and digest(manifest_blob) == trusted_sha256,
            "Trusted proof manifest SHA256 differs")
    manifest = decode(manifest_blob)
    require(manifest["status"] == "passed" and len(proof_blobs) == len(manifest["native_effects"]) == 5
            and [effect["kind"] for effect in manifest["native_effects"]] == list(KINDS), "Trusted proof manifest population differs")
    require(digest(report_blob) == manifest["report_sha256"] and decode(report_blob)["source_commit"] == manifest["source_commit"],
            "Runtime report differs from the trusted proof manifest")
    for blob, effect in zip(proof_blobs, manifest["native_effects"], strict=True):
        require(digest(blob) == effect["file_sha256"], "Downloaded proof differs from the trusted retained membership")
    return manifest


def verify_report(report: dict[str, Any], oracle: dict[str, Any], manifest: dict[str, Any]) -> None:
    require(manifest["status"] == "passed" and manifest["source_commit"] == report["source_commit"]
            and [{key: effect[key] for key in ("kind", "plan_id", "entry_id", "effect_id", "amount_minor")}
                 for effect in manifest["native_effects"]] == oracle["native_effects"], "Native effect identities differ from trusted retained membership")
    require(report["status"] == "passed" and report["scenario"] == "operational-fx-tax"
            and all(report[key] is True for key in ("source_unchanged", "built_web_unchanged", "tracked_clean_before", "tracked_clean_after", "owned_container_removed", "owned_https_process_stopped")), "Actual runtime acceptance closure incomplete")
    require(re.fullmatch(r"[a-f0-9]{40}", report["source_commit"]) is not None and report["source_commit"] == report["source_commit_after"]
            and all(re.fullmatch(r"[a-f0-9]{64}", report[key]) is not None for key in ("source_sha256", "built_web_sha256"))
            and report["tracked_status_before"] == report["tracked_status_after"] == "" and report["role_privileges"] == [False, False]
            and all(type(flag) is bool for flag in report["role_privileges"]), "Runtime source/isolation binding differs")
    require(all(type(report["browser_counts"][key]) is int and report["browser_counts"][key] == expected
                for key, expected in {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 0}.items()), "Browser outcomes are incomplete")
    expected = {"source_id": oracle["source_id"], "invoice_id": oracle["invoice_id"], "native_invoice_status": "Paid", "source_plans": 5,
                "native_posting_effects": 5, "unrealized_fx_minor": [str(oracle["unrealized_difference_minor"]), str(-oracle["unrealized_difference_minor"])],
                "foreign_currency": "EUR", "functional_currency": "USD", "foreign_gross_minor": str(oracle["foreign_gross_minor"]),
                "functional_gross_minor": str(oracle["functional_gross_minor"]), "foreign_receipts_minor": list(map(str, oracle["foreign_receipts_minor"])),
                "historical_releases_minor": list(map(str, oracle["historical_releases_minor"])), "realized_fx_minor": list(map(str, oracle["realized_fx_minor"])),
                "account_balances_minor": {key: str(value) for key, value in oracle["account_balances_minor"].items()}}
    require(report["persisted_effects"] == expected, "Actual native GL/AR differs from the independent rational oracle")
    restore = report["native_restore"]
    require(restore["status"] == "passed" and restore["verified_effects"] == expected and type(restore["tamper_refusals"]) is int
            and restore["tamper_refusals"] == 3 and re.fullmatch(r"[a-f0-9]{64}", restore["dump_sha256"]) is not None, "Populated restore oracle/barriers differ")
    snapshot, checkpoint = restore["snapshot"], restore["probe_checkpoint"]
    require(snapshot["head"] == checkpoint["head"] == report["revision"] == "0131_pg_fx_revaluation"
            and snapshot["objects"] == checkpoint["objects"] and snapshot["forced_rls_financial_tables"] == checkpoint["forced_rls_financial_tables"]
            and snapshot["forced_rls_financial_tables"] >= 45 and set(snapshot["tables"]) == set(checkpoint["tables"]), "Restored schema/RLS/catalog changed")
    for table, population in snapshot["tables"].items():
        require(population == checkpoint["tables"][table] or table == "identity_users"
                and population["rows"] == checkpoint["tables"][table]["rows"], "Post-restore probes changed retained financial evidence")
    for table, rows in {"operational_fx_sources": 1, "operational_fx_plans": 5, "operational_fx_reviews": 5, "operational_fx_links": 5,
                        "operational_fx_commands": 15, "finance_posting_effects": 5, "finance_entry_lines": 13,
                        "ar_invoices": 1, "ar_receipts": 2, "ar_receipt_allocations": 2}.items():
        require(type(snapshot["tables"][table]["rows"]) is int and snapshot["tables"][table]["rows"] == rows, f"Restored population differs: {table}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof-directory", required=True, type=Path)
    parser.add_argument("--cycle-report", type=Path, help="Defaults to proof-directory/../report.json")
    parser.add_argument("--proof-manifest", required=True, type=Path, help="Previously retained accepted proof hashes and native effect identities")
    parser.add_argument("--proof-manifest-sha256", required=True, help="Trusted manifest hash obtained separately from accepted evidence")
    parser.add_argument("--report", required=True, type=Path, help="Fresh output path; existing files are refused")
    args = parser.parse_args(argv)
    require(not args.report.exists(), "Output report already exists; preserve previous evidence")
    result: dict[str, Any] = {"status": "failed", "verifier_sha256": digest(Path(__file__).read_bytes()),
                              "oracle": "stdlib Fraction; independent integer half-up rounding; five-stage synthetic EUR/USD fixture"}
    try:
        directory = args.proof_directory.resolve()
        cycle_path = (args.cycle_report or directory.parent / "report.json").resolve()
        manifest_path = args.proof_manifest.resolve()
        result["command"] = [sys.executable, *(["-" + "O" * sys.flags.optimize] if sys.flags.optimize else []), str(Path(__file__).resolve()),
                             "--proof-directory", str(directory), "--cycle-report", str(cycle_path), "--proof-manifest", str(manifest_path),
                             "--proof-manifest-sha256", args.proof_manifest_sha256, "--report", str(args.report.resolve())]
        result["python_version"] = sys.version
        require({path.name for path in directory.glob("fx-proof-[0-9]*.json")} == {f"fx-proof-{index}.json" for index in range(5)}, "Exactly five numbered downloaded proofs are required")
        paths = [directory / f"fx-proof-{index}.json" for index in range(5)] + [cycle_path, manifest_path]
        require(all(path.stat().st_size <= 8 * 1024 * 1024 for path in paths), "Evidence file exceeds the offline bound")
        blobs = [path.read_bytes() for path in paths]
        result["inputs"] = [{"path": str(path), "sha256": digest(blob)} for path, blob in zip(paths, blobs, strict=True)]
        manifest = verify_membership(blobs[:5], blobs[5], blobs[6], args.proof_manifest_sha256)
        result["proof_manifest_sha256"] = args.proof_manifest_sha256
        proofs = [decode(blob) for blob in blobs[:5]]
        report = decode(blobs[5])
        oracle = verify_proofs(proofs)
        verify_report(report, oracle, manifest)
        mobile = directory / "fx-proof-ar-mobile.json"
        if mobile.exists():
            require(mobile.stat().st_size <= 8 * 1024 * 1024, "Arabic evidence file exceeds the offline bound")
            mobile_blob = mobile.read_bytes()
            require(decode(mobile_blob) == proofs[4], "Arabic mobile proof differs from the final retained evidence")
            result["inputs"].append({"path": str(mobile), "sha256": digest(mobile_blob)})
        result.update(status="passed", source_commit=report["source_commit"], source_sha256=report["source_sha256"], built_web_sha256=report["built_web_sha256"],
                      report_sha256=digest(blobs[5]), restored_table_count=len(report["native_restore"]["snapshot"]["tables"]),
                      dump_sha256=report["native_restore"]["dump_sha256"], **oracle)
    except (VerificationError, KeyError, TypeError, ValueError, OSError) as exc:
        result["error"] = str(exc)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(args.report.resolve()), "report_sha256": digest(args.report.read_bytes()), "error": result.get("error")}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
