"""Planned pure AD1 fixtures; these values are not native execution evidence."""

from typing import Any

from reconforge.domain.accrual_deferral import (
    AccrualDeferralPreparation,
    ScheduleAccounts,
    ScheduleTranche,
    SourceMode,
    captured_policy,
    source_equation,
)
from reconforge.domain.finance_posting import make_entry_snapshot, validation_digest
from reconforge.utils.money import CurrencyRegistryContext


def preparation(mode: SourceMode = "new_prepaid_voucher", amount: int = 10001) -> AccrualDeferralPreparation:
    return AccrualDeferralPreparation("work", "org", "entity", "ORG", "ENTITY", "AD1-PREPAID-1", mode,
        "USD", amount, "AD1_NATIVE", "p0", "2026-10-01", ScheduleAccounts("PREPAID", "EXPENSE", "ACCRUAL", "CASH"),
        tuple(ScheduleTranche(f"T{index}", f"p{index}", f"2026-{month:02}-28", 1,
            f"p{index + 1}" if mode == "expense_accrual" else None,
            f"2026-{month + 1:02}-01" if mode == "expense_accrual" else None)
            for index, month in ((1, 10), (2, 11), (3, 12)))
        if mode != "expense_accrual" else (
            ScheduleTranche("T1", "p1", "2026-10-28", 1, "p2", "2026-11-01"),
            ScheduleTranche("T2", "p2", "2026-11-28", 1, "p3", "2026-12-01"),
            ScheduleTranche("T3", "p3", "2026-12-28", 1, "p4", "2027-01-01")),
        "Reviewed exact service-period support", "original-effect" if mode.startswith("attach_") else None)


def planned_source() -> tuple[dict[str, Any], CurrencyRegistryContext]:
    context = CurrencyRegistryContext.from_installed()
    request = preparation().payload()
    return {"id": "AD1-" + "a" * 32, "phase": 2, "request": request,
            "equation": source_equation(request, context)}, context


def paid_original(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    context = CurrencyRegistryContext.from_installed()
    policy = captured_policy(request["currency_code"], context)
    entry = {"id": "ordinary-entry", "workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
        "journal_id": "native-journal", "period_id": "p0", "entry_number": "PAID-ORIGINAL-1", "posting_date": "2026-09-30",
        "description": "Original reviewed service voucher", "external_reference": "original-supplier-document",
        "source_type": "Manual", "preparer_actor_id": "original-maker", "reverses_posting_id": None, **policy}
    roles = {name: name + "-account" for name in ("expense", "prepaid", "cash", "accrued_liability")}
    debit = "expense" if request["mode"] == "attach_paid_expense" else "prepaid"
    rows = [{"line_number": 1, "account_id": roles[debit], "description": "Original service basis",
        "debit_minor": request["amount_minor"], "credit_minor": 0, "dimensions": {"project-id": "original-project"}},
        {"line_number": 2, "account_id": roles["cash"], "description": "Original paid cash",
        "debit_minor": 0, "credit_minor": request["amount_minor"], "dimensions": {"branch-id": "original-branch"}}]
    snapshot = make_entry_snapshot(entry, rows)
    digest = validation_digest(snapshot)
    effect = {"id": "original-effect", "entry_id": entry["id"], "source_kind": "Manual", "snapshot": snapshot,
        "validation_digest": digest, "posted_actor_id": "original-poster", "reverses_effect_id": None}
    review = {**entry, "status": "Validated", "validator_actor_id": "original-reviewer",
        "validation_digest": digest, "validation_contract_version": snapshot["schema_version"]}
    return effect, review, roles
