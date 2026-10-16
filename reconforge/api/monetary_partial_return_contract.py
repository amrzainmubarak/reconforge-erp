"""Version-three partial return DTOs with explicit transaction/functional legs."""

from collections.abc import Mapping
from typing import Any

from reconforge.api.monetary_public_contract import (
    BALANCE,
    SCOPE,
    balance_fields,
    calendar,
    closed,
    digest,
    integer,
    minor,
    paired_policies,
    require,
    scope_of,
    text,
)

MONETARY_FIELDS = frozenset({
    "transaction_net_minor", "transaction_tax_minor", "transaction_credit_minor", "functional_net_minor", "functional_tax_minor",
    "functional_credit_minor", "functional_cost_minor", "transaction_receivable_released_minor", "functional_receivable_released_minor",
    "transaction_refund_delta_minor", "functional_refund_delta_minor", "transaction_refund_minor", "functional_refund_released_minor",
    "functional_cash_minor", "functional_fx_gain_minor", "functional_fx_loss_minor", "functional_alignment_gain_minor",
    "functional_alignment_loss_minor", "functional_turnover_minor",
})
PLAN_FIELDS = SCOPE | frozenset({
    "schema_version", "id", "source_id", "source_order_id", "invoice_id", "operation", "status", "phase", "quantity_scaled",
    "quantity_precision", "period_id", "posting_date", "reason", "source_fingerprint", "history_fingerprint", "expected_history_version",
    "plan_digest", "allocation_policy", "transaction_policy", "functional_policy", "monetary", "entries", "movement_id", "original_id",
    "preparer_actor_id", "reviewer_actor_id", "posted_actor_id", "cancelled_actor_id",
})
BALANCE_FIELDS = BALANCE | SCOPE | frozenset({
    "source_id", "source_order_id", "invoice_id", "source_fingerprint", "transaction_policy", "functional_policy", "quantity_precision",
    "original_quantity_scaled", "returned_quantity_scaled", "remaining_quantity_scaled",
})
ENTRY_FIELDS = frozenset({"purpose", "entry_id", "posting_effect_id", "validation_digest"})
PREFIXES = {"Return": "CR3", "Refund": "CRF3", "ReverseReturn": "CR3R", "ReverseRefund": "CRF3R"}


def _identifier(value: Any, prefix: str) -> None:
    text(value)
    require(value.startswith(prefix + "-") and len(value) == len(prefix) + 33
            and all(character in "0123456789abcdef" for character in value[len(prefix) + 1:]))


def project_monetary_partial_plan(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    row = closed(value, PLAN_FIELDS)
    scope_of(row, scope)
    require(row["schema_version"] == "customer-partial-return-monetary-v3"
            and type(row["operation"]) is str and row["operation"] in PREFIXES
            and row["allocation_policy"] == "remaining-dual-currency-v1")
    operation = row["operation"]
    _identifier(row["id"], PREFIXES[operation])
    for key in ("source_id", "source_order_id", "invoice_id", "period_id", "preparer_actor_id"):
        text(row[key])
    text(row["reason"], maximum=500)
    for key in ("reviewer_actor_id", "posted_actor_id", "cancelled_actor_id", "movement_id"):
        text(row[key], nullable=True)
    calendar(row["posting_date"])
    for key in ("source_fingerprint", "history_fingerprint", "plan_digest"):
        digest(row[key])
    integer(row["quantity_precision"], maximum=6)
    integer(row["expected_history_version"], maximum=255)
    integer(row["phase"], maximum=3)
    phase = row["phase"]
    require(row["status"] == ("Prepared", "Reviewed", "Posted", "Cancelled")[phase])
    row["transaction_policy"], row["functional_policy"] = paired_policies(row["transaction_policy"], row["functional_policy"])
    identity = row["transaction_policy"]["currency_code"] == row["functional_policy"]["currency_code"]
    is_return = operation in {"Return", "ReverseReturn"}
    quantity = minor(row["quantity_scaled"], positive=is_return)
    if not is_return:
        require(quantity == 0)
    if operation == "Return":
        require(row["original_id"] is None)
    else:
        _identifier(row["original_id"], "CRF3" if operation == "ReverseRefund" else "CR3")
        require(row["original_id"] != row["id"])
    require((row["movement_id"] is not None) == (phase == 2 and is_return))
    require((row["posted_actor_id"] is not None) == (phase == 2)
            and (row["cancelled_actor_id"] is not None) == (phase == 3))
    if phase in (1, 2):
        require(row["reviewer_actor_id"] is not None)
    if phase == 0:
        require(row["reviewer_actor_id"] is None)
    if row["reviewer_actor_id"] is not None:
        require(row["reviewer_actor_id"] != row["preparer_actor_id"])
    if phase == 2:
        require(row["posted_actor_id"] not in (row["preparer_actor_id"], row["reviewer_actor_id"]))
    amounts = closed(row["monetary"], MONETARY_FIELDS)
    numbers = {key: minor(item) for key, item in amounts.items()}
    require(numbers["functional_fx_gain_minor"] == 0 or numbers["functional_fx_loss_minor"] == 0)
    require(numbers["functional_alignment_gain_minor"] == 0 or numbers["functional_alignment_loss_minor"] == 0)
    if is_return:
        for key in ("transaction_refund_minor", "functional_refund_released_minor", "functional_cash_minor", "functional_fx_gain_minor", "functional_fx_loss_minor"):
            require(numbers[key] == 0)
        for prefix in ("transaction", "functional"):
            require(numbers[prefix + "_credit_minor"] == numbers[prefix + "_net_minor"] + numbers[prefix + "_tax_minor"])
        require(numbers["transaction_credit_minor"] == numbers["transaction_receivable_released_minor"] + numbers["transaction_refund_delta_minor"])
        for first, second in (("transaction_receivable_released_minor", "functional_receivable_released_minor"),
                              ("transaction_refund_delta_minor", "functional_refund_delta_minor")):
            require(numbers[first] != 0 or numbers[second] == 0)
        turnover = numbers["functional_credit_minor"] + numbers["functional_alignment_loss_minor"]
        require(turnover == numbers["functional_receivable_released_minor"] + numbers["functional_refund_delta_minor"] + numbers["functional_alignment_gain_minor"])
        require(numbers["functional_turnover_minor"] == turnover + numbers["functional_cost_minor"])
        stem = "Reverse" if operation == "ReverseReturn" else ""
        purposes = ([stem + "MerchandiseCredit"] if turnover else []) + ([stem + "CostRestoration"] if numbers["functional_cost_minor"] else [])
    else:
        allowed = {"transaction_refund_minor", "functional_refund_released_minor", "functional_cash_minor", "functional_fx_gain_minor", "functional_fx_loss_minor", "functional_turnover_minor"}
        require(all(value == 0 for key, value in numbers.items() if key not in allowed)
                and numbers["transaction_refund_minor"] > 0)
        turnover = numbers["functional_refund_released_minor"] + numbers["functional_fx_loss_minor"]
        require(turnover == numbers["functional_cash_minor"] + numbers["functional_fx_gain_minor"]
                and numbers["functional_turnover_minor"] == turnover)
        purposes = (["ReverseRefund" if operation == "ReverseRefund" else "Refund"] if turnover else [])
    if identity:
        pairs = (("transaction_net_minor", "functional_net_minor"), ("transaction_tax_minor", "functional_tax_minor"),
                 ("transaction_credit_minor", "functional_credit_minor"), ("transaction_receivable_released_minor", "functional_receivable_released_minor"),
                 ("transaction_refund_delta_minor", "functional_refund_delta_minor"), ("transaction_refund_minor", "functional_refund_released_minor"))
        require(all(numbers[first] == numbers[second] for first, second in pairs))
        require(all(numbers[key] == 0 for key in ("functional_fx_gain_minor", "functional_fx_loss_minor", "functional_alignment_gain_minor", "functional_alignment_loss_minor")))
        if not is_return:
            require(numbers["functional_cash_minor"] == numbers["transaction_refund_minor"])
    entries = row["entries"]
    require(type(entries) is list and len(entries) == len(purposes))
    checked = []
    for entry, purpose in zip(entries, purposes, strict=True):
        item = closed(entry, ENTRY_FIELDS)
        require(item["purpose"] == purpose)
        text(item["entry_id"])
        text(item["posting_effect_id"], nullable=True)
        digest(item["validation_digest"])
        require((item["posting_effect_id"] is not None) == (phase == 2))
        checked.append(item)
    require(len({item["entry_id"] for item in checked}) == len(checked))
    require(len({item["posting_effect_id"] for item in checked if item["posting_effect_id"] is not None}) == len(checked) if phase == 2 else True)
    row["entries"], row["monetary"] = checked, amounts
    return row


def project_monetary_partial_balance(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    row = closed(value, BALANCE_FIELDS)
    scope_of(row, scope)
    require(row["schema_version"] == "customer-partial-return-monetary-balance-v3")
    for key in ("source_id", "source_order_id", "invoice_id"):
        text(row[key])
    digest(row["source_fingerprint"])
    integer(row["quantity_precision"], maximum=6)
    original = minor(row["original_quantity_scaled"], positive=True)
    returned, remaining = minor(row["returned_quantity_scaled"]), minor(row["remaining_quantity_scaled"])
    require(returned + remaining == original)
    row["transaction_policy"], row["functional_policy"] = paired_policies(row["transaction_policy"], row["functional_policy"])
    balance_fields(row, identity=row["transaction_policy"]["currency_code"] == row["functional_policy"]["currency_code"])
    return row


def project_monetary_partial_response(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    require(type(value) is dict and len(value) == 1)
    if "plan" in value:
        return {"plan": project_monetary_partial_plan(value["plan"], scope)}
    if "balance" in value:
        return {"balance": project_monetary_partial_balance(value["balance"], scope)}
    require(set(value) == {"plans"} and type(value["plans"]) is list and len(value["plans"]) <= 200)
    plans = [project_monetary_partial_plan(item, scope) for item in value["plans"]]
    require(len({item["id"] for item in plans}) == len(plans))
    return {"plans": plans}
