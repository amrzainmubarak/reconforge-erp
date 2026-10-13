"""Reconcile explicitly selected IC2 reports with original native adjustments.

Translated party membership is a reporting view; native adjustment membership is
actual GL. Their bridge is retained, rather than claiming they are one ledger.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text
from reconforge.domain.intercompany_cashflow import SourceCashOpening, classified_cashflow
from reconforge.domain.intercompany_fx import group_report, signed, translate_book
from reconforge.utils.money import CurrencyRegistryContext

MAX_SOURCES = 16
BOOKS = ("seller", "buyer", "adjustment")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FinancePostingError("intercompany_group_diagnostic_invalid", message)


@dataclass(frozen=True)
class IntercompanyReportPin:
    opening: SourceCashOpening
    elimination_plan_id: str
    elimination_plan_digest: str
    report_digest: str

    def __post_init__(self) -> None:
        for field in ("elimination_plan_id",):
            text(getattr(self, field), field, maximum=160)
        text(self.opening.source_id, "source_id", maximum=160)
        require(self.opening.source_id.startswith("IC2S-"), "Select an original paired-trade source.")
        for value in (self.opening.source_digest, self.opening.origin_plan_digest,
                      self.elimination_plan_digest, self.report_digest):
            require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None,
                    "Every selected original seal must be a canonical SHA256.")


@dataclass(frozen=True)
class IntercompanyDiagnosticSelection:
    pins: tuple[IntercompanyReportPin, ...]

    def __post_init__(self) -> None:
        require(type(self.pins) is tuple and 1 <= len(self.pins) <= MAX_SOURCES,
                "Select between one and sixteen complete original sources.")
        ids = [pin.opening.source_id for pin in self.pins]
        require(len(set(ids)) == len(ids) and ids == sorted(ids),
                "Selected source identities must be unique and in canonical order.")


def _native_membership(proof: Mapping[str, Any], book: str) -> list[dict[str, Any]]:
    source, final = proof["source"], proof["stages"][-1]["plan"]
    accounts = {row["id"]: row["account_code"] for row in source["native_accounts"][book].values()}
    result = []
    for stage in proof["stages"]:
        for entry in stage["plan"]["entries"]:
            if entry["book"] != book:
                continue
            header = entry["snapshot"]["entry"]
            for row in entry["snapshot"]["lines"]:
                item = {"effect_id": stage["plan"]["posting_effect_ids"][book], "entry_id": entry["entry_id"],
                    "line_number": row["line_number"], "account_id": row["account_id"],
                    "account_code": accounts[row["account_id"]], "posting_date": header["posting_date"],
                    "legal_entity_id": header["legal_entity_id"], "debit_minor": row["debit_minor"],
                    "credit_minor": row["credit_minor"]}
                if book != "adjustment":
                    item["income_rate"] = final["command_request"]["income_rates"][book][header["posting_date"]]
                result.append(item)
    # The owner captures this native contribution order, independent of the
    # presentation order of book entries in retained plan JSON.
    return result


def reconcile_intercompany_reports(selection: IntercompanyDiagnosticSelection,
                                  proofs: Sequence[Mapping[str, Any]],
                                  periods: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Existing per-source GL/FX contracts remain the sole runtime calculation."""
    require(len(proofs) == len(selection.pins), "Original selected source coverage differs.")
    first = proofs[0]
    scope = first["qualified_scope"]
    reporting_policy = first["source"]["policies"]["adjustment"]
    adjustment_config = first["source"]["request"]["adjustment"]
    group_journal = first["stages"][-1]["plan"]["entries"][0]["snapshot"]["entry"]["journal_id"]
    registry = first["registry_snapshot"]
    period_by_id = {row["id"]: dict(row) for row in periods}
    require(len(period_by_id) == len(periods), "Observed native periods cannot repeat.")
    required_periods: set[str] = set()
    effects: set[str] = set()
    rows: dict[str, dict[str, Any]] = {}
    members: list[dict[str, Any]] = []
    cash = {key: 0 for key in ("opening_minor", "operating_net_minor", "fx_on_cash_minor", "closing_minor")}
    for pin, proof in zip(selection.pins, proofs, strict=True):
        require(proof["schema_version"] == "intercompany-source-cashflow-evidence-v1"
                and type(proof["evidence_digest"]) is str
                and re.fullmatch("[0-9a-f]{64}", proof["evidence_digest"]) is not None
                and proof["native_execution_proven"] is True and proof["financial_writes"] is False
                and proof["native_role"] == {"rolsuper": False, "rolbypassrls": False},
                "An original ordinary-runtime source capture with an explicit custody seal is required.")
        source, report, stages = proof["source"], proof["report"], proof["stages"]
        final = stages[-1]["plan"]
        require(proof["qualified_scope"] == {"tenant_id": scope["tenant_id"],
                "workspace_id": source["request"]["workspace_id"], "organization_id": source["request"]["organization_id"],
                "legal_entity_ids": {book: source["request"][book]["legal_entity_id"] for book in BOOKS}}
                and all(row["tenant_id"] == scope["tenant_id"] for population in proof["original_rows"].values() for row in population),
                "Qualified original tenant and source hierarchy differ.")
        require(proof["qualified_scope"] == scope and proof["registry_snapshot"] == registry,
                "Selected sources must share the exact qualified books and registry snapshot.")
        require(source["policies"]["adjustment"] == reporting_policy
                and source["native_accounts"]["adjustment"] == first["source"]["native_accounts"]["adjustment"]
                and {key: value for key, value in source["request"]["adjustment"].items() if key != "period_id"}
                == {key: value for key, value in adjustment_config.items() if key != "period_id"}
                and final["entries"][0]["snapshot"]["entry"]["journal_id"] == group_journal,
                "The captured group reporting policy, native journal and account map differ.")
        require(proof["opening"] == asdict(pin.opening)
                and source["id"] == pin.opening.source_id and source["source_digest"] == pin.opening.source_digest
                and (final["id"], final["plan_digest"], report["report_digest"])
                == (pin.elimination_plan_id, pin.elimination_plan_digest, pin.report_digest),
                "An original selected source, elimination or report seal differs.")
        context = CurrencyRegistryContext.from_snapshot(registry)
        derived_cash = classified_cashflow(source, report, stages, opening=pin.opening, context=context)
        require(derived_cash == proof["cashflow"], "The source Cash equation differs from original effects.")
        translations = {book: translate_book(source, book, _native_membership(proof, book),
            closing_rate=final["command_request"]["closing_rates"][book], as_of_date=final["posting_date"], context=context)
            for book in ("seller", "buyer")}
        require(translations == final["equation"]["translations"],
                "Reviewed translations differ from original native contributions and captured rates.")
        adjustment = _native_membership(proof, "adjustment")
        rebuilt = group_report(source, translations, adjustment, plan_digest=final["plan_digest"])
        rebuilt.update(source_effect_ids=derived_cash["source_effect_ids"],
                       native_adjustment_effect_ids=derived_cash["native_adjustment_effect_ids"])
        rebuilt["report_digest"] = digest_payload({key: value for key, value in rebuilt.items() if key != "report_digest"})
        require(rebuilt == report, "The retained report differs from original translated and native adjustment membership.")
        source_effects = set(derived_cash["source_effect_ids"] + derived_cash["native_adjustment_effect_ids"])
        require(not effects.intersection(source_effects), "A native effect is covered by more than one selected source.")
        effects.update(source_effects)
        for stage in stages:
            for entry in stage["plan"]["entries"]:
                header = entry["snapshot"]["entry"]
                period_id = header["period_id"]
                require(stage["plan"]["period_ids"][entry["book"]] == period_id,
                        "The original native header and reviewed book period differ.")
                required_periods.add(period_id)
                observed = period_by_id.get(period_id)
                require(observed is not None and observed["tenant_id"] == scope["tenant_id"]
                        and observed["application_workspace_id"] == scope["workspace_id"]
                        and observed["status"] in {"Open", "Soft Closed", "Closed"}
                        and observed["start_date"] <= header["posting_date"] <= observed["end_date"],
                        "Every original native posting requires its exact observed scoped period.")
        for item in report["trial_balance"]:
            role = item["role"]
            row = rows.setdefault(role, {"role": role, "account_code": adjustment_config["accounts"][role],
                "translated_minor": 0, "native_adjustment_minor": 0, "combined_minor": 0, "source_membership": []})
            translated = sum(value["balance_minor"] for value in item["translated_membership"])
            native = sum(value["debit_minor"] - value["credit_minor"] for value in item["native_adjustment_membership"])
            require(translated + native == item["balance_minor"], "A source reporting bridge does not conserve money.")
            for key, value in (("translated_minor", translated), ("native_adjustment_minor", native),
                               ("combined_minor", item["balance_minor"])):
                row[key] = signed(row[key] + value, "selected group reporting bridge")
            row["source_membership"].append({"source_id": source["id"], "report_digest": report["report_digest"],
                "translated_minor": translated, "native_adjustment_minor": native,
                "combined_minor": item["balance_minor"]})
        for key in cash:
            cash[key] = signed(cash[key] + derived_cash[key], "selected source cash equation")
        members.append({"source_id": source["id"], "source_digest": source["source_digest"],
            "elimination_plan_id": final["id"], "elimination_plan_digest": final["plan_digest"],
            "report_digest": report["report_digest"], "source_evidence_digest": proof["evidence_digest"],
            "source_effect_ids": derived_cash["source_effect_ids"],
            "native_adjustment_effect_ids": derived_cash["native_adjustment_effect_ids"]})
    require(set(period_by_id) == required_periods, "Observed period population is incomplete or unrelated.")
    for column in ("translated_minor", "native_adjustment_minor", "combined_minor"):
        require(sum(row[column] for row in rows.values()) == 0, "The selected original reporting population does not balance.")
    def amount(role: str) -> int:
        return rows.get(role, {}).get("combined_minor", 0)
    income = signed(-sum(amount(role) for role in ("revenue", "realized_gain", "unrealized_gain")), "selected income")
    expense = signed(sum(amount(role) for role in ("expense", "realized_loss", "unrealized_loss")), "selected expense")
    assets, liabilities, equity = amount("receivable") + amount("cash"), -amount("payable"), -amount("cta")
    require(assets == liabilities + equity + income - expense, "The selected reporting balance-sheet equation differs.")
    require(cash["opening_minor"] + cash["operating_net_minor"] + cash["fx_on_cash_minor"] == cash["closing_minor"]
            == amount("cash"), "The selected original Cash equation differs from the reporting bridge.")
    result = {"schema_version": "intercompany-group-diagnostic-v1", "qualified_scope": scope,
        "reporting_policy": reporting_policy, "group_journal_id": group_journal,
        "reporting_scope": "explicit-selected-complete-paired-trade-sources",
        "selection": {"pins": [asdict(pin) for pin in selection.pins]},
        "source_members": members, "trial_balance_bridge": [rows[role] for role in sorted(rows)],
        "income_statement": {"income_minor": income, "expense_minor": expense, "result_minor": income - expense},
        "balance_sheet": {"assets_minor": assets, "liabilities_minor": liabilities, "equity_minor": equity,
            "unclosed_result_minor": income - expense, "balanced": True}, "cash_equation": cash,
        "native_period_observations": [period_by_id[key] for key in sorted(period_by_id)],
        "source_elimination_complete": True, "formal_close_workflow_assessed": False,
        "whole_group_membership_proven": False, "financial_writes": False,
        "limitations": ["Only explicitly selected complete original paired-trade sources are included",
            "Native period status is an observation, not close-task approval or readiness",
            "No whole-group, ownership/NCI, statutory, country-tax or accounting-compliance assertion"]}
    return {**result, "diagnostic_digest": digest_payload(result)}
