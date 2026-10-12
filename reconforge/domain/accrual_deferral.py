"""AD1 source voucher and schedule equations over the existing native ledger.

Schedule allocation uses the existing exact Hamilton allocator. Currency
interpretation remains the retained canonical finance currency policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, NoReturn

from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import FinancePostingError, digest_payload, text, validation_digest
from reconforge.domain.landed_cost import allocate_minor
from reconforge.domain.operational_fx_tax import canonical_day
from reconforge.domain.procurement_partial import ProcurementPartialError
from reconforge.platform.inventory_values import code
from reconforge.utils.money import CurrencyRegistryContext

CONTRACT = "accrual-deferral-source-v1"
ALLOCATION_POLICY = "native-hamilton-stable-id-v1"
MAX_MINOR = 9_000_000_000_000_000_000
MAX_TRANCHES = 36
MAX_DIMENSIONS = 8
SourceMode = Literal["new_prepaid_voucher", "attach_paid_expense", "attach_prepaid_voucher", "expense_accrual"]
Operation = Literal["source", "release", "accrue", "reverse"]
MODES = frozenset(("new_prepaid_voucher", "attach_paid_expense", "attach_prepaid_voucher", "expense_accrual"))


def fail(message: str, error: str = "accrual_deferral_invalid") -> NoReturn:
    raise FinancePostingError(error, message)


def minor(value: object, field: str, *, zero: bool = False) -> int:
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_MINOR:
        fail(f"{field} requires bounded exact integer minor units.")
    return value


def identity(value: object, field: str, *, maximum: int = 160) -> str:
    result = text(value, field, maximum=maximum)
    if result != value:
        fail(f"{field} must be retained in canonical form.")
    return result


@dataclass(frozen=True)
class ScheduleAccounts:
    prepaid: str
    expense: str
    accrued_liability: str
    cash: str

    def payload(self) -> dict[str, str]:
        result = asdict(self)
        if len(set(result.values())) != 4 or any(code(value, role) != value for role, value in result.items()):
            fail("Four distinct canonical prepaid asset, expense, accrued liability and cash asset accounts are required.")
        return result


@dataclass(frozen=True)
class ScheduleTranche:
    id: str
    period_id: str
    posting_date: str
    weight: int
    reversal_period_id: str | None = None
    reversal_date: str | None = None

    def payload(self, mode: str) -> dict[str, Any]:
        posting_date = canonical_day(self.posting_date, "tranche posting_date")
        result = {"id": identity(self.id, "tranche id", maximum=40),
                  "period_id": identity(self.period_id, "period_id"),
                  "posting_date": posting_date,
                  "weight": minor(self.weight, "tranche weight")}
        if mode == "expense_accrual":
            period = identity(self.reversal_period_id, "reversal_period_id")
            day = canonical_day(self.reversal_date, "tranche reversal_date")
            if day <= posting_date or period == self.period_id:
                fail("Accrual tranches require a later explicit reversal date in a different fiscal period.")
            result.update(reversal_period_id=period, reversal_date=day)
        elif self.reversal_period_id is not None or self.reversal_date is not None:
            fail("Prepaid schedule tranches do not carry automatic accrual reversal periods.")
        return result


@dataclass(frozen=True)
class AccrualDeferralPreparation:
    workspace_id: str
    organization_id: str
    legal_entity_id: str
    organization_code: str
    entity_code: str
    reference: str
    mode: SourceMode
    currency_code: str
    amount_minor: int
    journal_code: str
    period_id: str
    posting_date: str
    accounts: ScheduleAccounts
    tranches: tuple[ScheduleTranche, ...]
    reason: str
    original_effect_id: str | None = None

    def payload(self) -> dict[str, Any]:
        if self.mode not in MODES:
            fail("Select an explicit new voucher, paid-original attachment, prepaid-original attachment or expense accrual.")
        result: dict[str, Any] = {"schema_version": CONTRACT, "mode": self.mode}
        for field in ("workspace_id", "organization_id", "legal_entity_id", "reference", "period_id", "reason"):
            result[field] = identity(getattr(self, field), field, maximum=500 if field == "reason" else 160)
        for field in ("organization_code", "entity_code", "currency_code", "journal_code"):
            value = getattr(self, field)
            if code(value, field) != value:
                fail(f"{field} must be a canonical native code.")
            result[field] = value
        result["posting_date"] = canonical_day(self.posting_date, "source posting_date")
        result["amount_minor"] = minor(self.amount_minor, "source amount")
        if not isinstance(self.tranches, tuple) or not 1 <= len(self.tranches) <= MAX_TRANCHES:
            fail("A schedule contains one to 36 explicit fiscal-period tranches.")
        tranches = [item.payload(self.mode) for item in self.tranches]
        if len({item["id"] for item in tranches}) != len(tranches) or len({item["period_id"] for item in tranches}) != len(tranches):
            fail("Each retained tranche and fiscal period must be unique.")
        tranches.sort(key=lambda item: (item["posting_date"], item["id"]))
        if any(item["posting_date"] < result["posting_date"] for item in tranches):
            fail("A tranche cannot precede its retained source voucher or estimate date.")
        result["accounts"] = self.accounts.payload()
        result["tranches"] = allocated_tranches(result["amount_minor"], tranches)
        result["allocation_policy"] = ALLOCATION_POLICY
        if self.mode.startswith("attach_"):
            result["original_effect_id"] = identity(self.original_effect_id, "original_effect_id")
        elif self.original_effect_id is not None:
            fail("New vouchers and estimates must not silently attach another original effect.")
        else:
            result["original_effect_id"] = None
        return result


def allocated_tranches(amount: int, tranches: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Allocate once by stable source IDs; this is not a currency conversion."""
    minor(amount, "source amount")
    try:
        allocations = allocate_minor(amount, tuple((item["id"], item["weight"]) for item in tranches))
    except (KeyError, TypeError, ProcurementPartialError) as exc:
        raise FinancePostingError("accrual_deferral_allocation_invalid", "Retained tranche weights are invalid.") from exc
    if any(value == 0 for value in allocations.values()):
        fail("Every tranche must receive a positive allocation; retain fewer tranches or different reviewed weights.")
    result = [{**item, "amount_minor": allocations[item["id"]]} for item in tranches]
    if sum(item["amount_minor"] for item in result) != amount:
        fail("Schedule allocations must conserve the original voucher exactly.")
    return result


def captured_policy(currency: str, context: CurrencyRegistryContext) -> dict[str, Any]:
    policy = FinanceCurrencyPolicy.capture(currency, context)
    if policy.rounding_policy != "ROUND_HALF_UP":
        fail("AD1 requires the existing retained ROUND_HALF_UP functional currency policy.", "accrual_deferral_policy_unsupported")
    return {"currency_code": policy.currency_code, **policy.metadata()}


def line(account: str, debit: int, credit: int, dimensions: Mapping[str, str] | None = None) -> dict[str, Any]:
    minor(debit, "line debit", zero=True)
    minor(credit, "line credit", zero=True)
    if bool(debit) == bool(credit):
        fail("Each native schedule line requires exactly one nonzero side.")
    if code(account, "account code") != account:
        fail("Schedule lines require canonical captured account codes.")
    return {"account_code": account, "debit_minor": debit, "credit_minor": credit,
            "dimensions": captured_dimensions(dimensions or {})}


def captured_dimensions(values: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(values, Mapping) or len(values) > MAX_DIMENSIONS:
        fail("Each original native AD1 line supports at most eight exact dimension references.")
    return dict(sorted((identity(key, "dimension_id"), identity(value, "dimension_value_id")) for key, value in values.items()))


def attach_original(request: Mapping[str, Any], effect: Mapping[str, Any],
                    reviewed_entry: Mapping[str, Any], account_ids: Mapping[str, str],
                    context: CurrencyRegistryContext) -> dict[str, Any]:
    """Accept only an exact, approved, ordinary two-line paid original voucher.

    Adapters additionally verify live audit/outbox evidence and the absence of
    other source ownership, reversal or an active original-effect claim.
    """
    if request["mode"] not in {"attach_paid_expense", "attach_prepaid_voucher"}:
        fail("Original attachment must be an explicit source mode.")
    snapshot = effect["snapshot"]
    digest = validation_digest(snapshot)
    entry = snapshot["entry"]
    if (effect["id"] != request["original_effect_id"] or effect["source_kind"] != "Manual"
            or effect.get("reverses_effect_id") is not None or digest != effect["validation_digest"]
            or entry["source_type"] != "Manual" or entry["reverses_posting_id"] is not None
            or entry["posting_date"] > request["posting_date"]):
        fail("Attachment requires the exact unreversed approved original paid voucher.")
    if any(entry[field] != request[field] for field in ("workspace_id", "organization_id", "legal_entity_id", "currency_code")):
        fail("An attached voucher must retain the same native entity scope and functional currency.")
    policy = captured_policy(request["currency_code"], context)
    if any(entry[field] != value for field, value in policy.items()):
        fail("An attached voucher must retain the exact current workspace-bound original monetary policy.")
    if (reviewed_entry.get("id") != effect["entry_id"] or reviewed_entry.get("status") != "Validated"
            or reviewed_entry.get("validation_digest") != digest
            or reviewed_entry.get("validation_contract_version") != snapshot["schema_version"]
            or reviewed_entry.get("preparer_actor_id") != entry["preparer_actor_id"]):
        fail("An attachment requires retained native entry review provenance matching the exact original snapshot.")
    actors = [entry["preparer_actor_id"], reviewed_entry.get("validator_actor_id"), effect.get("posted_actor_id")]
    if any(not isinstance(actor, str) or not actor for actor in actors) or len(set(actors)) != 3:
        fail("An attached original voucher must retain three distinct authenticated human actors.")
    debit_role = "expense" if request["mode"] == "attach_paid_expense" else "prepaid"
    rows = snapshot["lines"]
    amount = minor(request["amount_minor"], "original voucher amount")
    debit = [row for row in rows if row["account_id"] == account_ids[debit_role]
             and row["debit_minor"] == amount and row["credit_minor"] == 0]
    cash = [row for row in rows if row["account_id"] == account_ids["cash"]
            and row["credit_minor"] == amount and row["debit_minor"] == 0]
    if len(rows) != 2 or len(debit) != 1 or len(cash) != 1 or debit[0] is cash[0]:
        fail("An attached original must be the exact two-line paid expense or prepaid cash voucher; complex or other source-owned vouchers require their original module.")
    return {"original_effect_id": effect["id"], "original_entry_id": effect["entry_id"],
            "original_validation_digest": digest, "original_snapshot": snapshot,
            "original_actor_ids": actors, "original_review": {field: reviewed_entry[field] for field in
                ("id", "status", "preparer_actor_id", "validator_actor_id", "validation_digest", "validation_contract_version")},
            "basis_dimensions": captured_dimensions(debit[0]["dimensions"]),
            "original_cash_dimensions": captured_dimensions(cash[0]["dimensions"])}


def source_equation(request: Mapping[str, Any], context: CurrencyRegistryContext,
                    attached: Mapping[str, Any] | None = None) -> dict[str, Any]:
    amount = minor(request["amount_minor"], "source amount")
    accounts = request["accounts"]
    dimensions = attached["basis_dimensions"] if attached is not None else {}
    mode = request["mode"]
    if mode not in MODES or mode.startswith("attach_") != (attached is not None):
        fail("Source effect membership must match the declared voucher or attachment mode.")
    if mode == "new_prepaid_voucher":
        rows = [line(accounts["prepaid"], amount, 0), line(accounts["cash"], 0, amount)]
    elif mode == "attach_paid_expense":
        rows = [line(accounts["prepaid"], amount, 0, dimensions), line(accounts["expense"], 0, amount, dimensions)]
    else:
        rows = []
    return {"schema_version": CONTRACT, "operation": "source", "mode": mode,
            "policy": captured_policy(request["currency_code"], context), "lines": rows,
            "cash_changed_minor": -amount if mode == "new_prepaid_voucher" else 0,
            "native_effect_required": bool(rows), "external_original_membership": dict(attached or {}),
            "allocated_minor": amount, "allocation_policy": request["allocation_policy"],
            "tranches": request["tranches"]}


def tranche_equation(source: Mapping[str, Any], tranche_id: str) -> dict[str, Any]:
    request, equation = source["request"], source["equation"]
    tranche_id = identity(tranche_id, "tranche_id", maximum=40)
    selected = [item for item in request["tranches"] if item["id"] == tranche_id]
    if len(selected) != 1 or source["phase"] != 2:
        fail("A tranche requires one exact retained schedule and an approved posted source voucher or estimate.")
    tranche, accounts = selected[0], request["accounts"]
    amount = minor(tranche["amount_minor"], "tranche amount")
    accrue = request["mode"] == "expense_accrual"
    dimensions = equation["external_original_membership"].get("basis_dimensions", {})
    rows = [line(accounts["expense"], amount, 0, dimensions),
            line(accounts["accrued_liability"] if accrue else accounts["prepaid"], 0, amount, dimensions)]
    return {"schema_version": CONTRACT, "operation": "accrue" if accrue else "release", "tranche_id": tranche_id,
            "period_id": tranche["period_id"], "posting_date": tranche["posting_date"],
            "amount_minor": amount, "lines": rows, "policy": equation["policy"], "cash_changed_minor": 0,
            "native_effect_required": True}


def reversal_equation(original: Mapping[str, Any]) -> dict[str, Any]:
    if (original["phase"] != 2 or original["kind"] not in {"release", "accrue"}
            or not original.get("posting_effect_id") or not original.get("plan_digest")):
        fail("Only an exact posted tranche effect may be reversed through its schedule owner.")
    retained = original["equation"]
    rows = [line(row["account_code"], row["credit_minor"], row["debit_minor"], row["dimensions"])
            for row in retained["lines"]]
    return {"schema_version": CONTRACT, "operation": "reverse", "original_plan_id": original["id"],
            "original_plan_digest": original["plan_digest"], "original_posting_effect_id": original["posting_effect_id"],
            "original_kind": original["kind"], "tranche_id": retained["tranche_id"],
            "amount_minor": retained["amount_minor"], "policy": retained["policy"], "lines": rows,
            "cash_changed_minor": 0, "native_effect_required": True}


def sealed_equation(equation: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(equation)
    result["equation_digest"] = digest_payload(result)
    return result
