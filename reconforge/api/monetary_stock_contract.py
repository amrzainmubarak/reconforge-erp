"""Closed Stock v2 DTOs; transaction and functional amounts stay distinct."""

from collections.abc import Mapping
from typing import Any

from reconforge.api.monetary_public_contract import (
    BALANCE,
    SCOPE,
    MonetaryResponseError,
    balance_fields,
    calendar,
    closed,
    digest,
    integer,
    minor,
    policy,
    rate,
    require,
    scope_of,
    text,
)
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_fx_tax import TaxComponent
from reconforge.domain.sales_revenue import SalesLine
from reconforge.platform.inventory_values import quantity_to_scaled

STOCK_FIELDS = SCOPE | frozenset({
    "schema_version", "id", "number", "status", "row_version", "source_digest", "customer_code", "customer_reference", "item_code",
    "warehouse_code", "location_code", "quantity", "quantity_scaled", "quantity_precision", "unit_price_minor", "discount_basis_points",
    "net_unit_price_minor", "transaction_net_minor", "description", "order_date", "transaction_policy", "functional_policy", "created_by",
    "approved_by", "issue_preparer_id", "issue_reviewer_id", "issue_digest", "functional_cogs_minor", "cogs_entry_id", "cogs_effect_id",
    "movement_id", "valuation_id", "cost_admission_policy", "monetary_origin", "balance", "collection", "events",
})
ORIGIN_FIELDS = frozenset({
    "schema_version", "id", "fx_source_id", "recognition_plan_id", "invoice_id", "source_digest", "country_code", "transaction_class",
    "original_rate", "transaction_net_minor", "transaction_tax_minor", "transaction_gross_minor", "functional_net_minor", "functional_tax_minor",
    "functional_gross_minor", "tax_components", "receivable_account_code", "revenue_account_code", "cash_account_code",
    "refund_liability_account_code", "gain_account_code", "loss_account_code", "journal_code", "period_id", "invoice_number", "invoice_date",
    "due_date", "preparer_actor_id", "reviewer_actor_id", "posted_actor_id", "entry_id", "posting_effect_id",
})
TAX_FIELDS = frozenset({
    "policy_id", "country_code", "transaction_class", "effective_from", "effective_to", "rate", "account_code", "source", "version",
    "policy_digest", "transaction_tax_minor", "functional_tax_minor",
})
COLLECTION_FIELDS = frozenset({
    "id", "sequence", "status", "plan_digest", "amount_minor", "functional_cash_minor", "functional_receivable_released_minor",
    "functional_fx_gain_minor", "functional_fx_loss_minor", "settlement_rate", "receipt_number", "receipt_date", "period_id",
    "preparer_actor_id", "reviewer_actor_id", "posted_actor_id", "entry_id", "posting_effect_id", "receipt_id",
})
EVENT_FIELDS = frozenset({"version", "actor_id", "operation", "reason", "status", "audit_event_id"})
_FIRST = (("create", "Draft"), ("submit", "Submitted"), ("approve", "Approved"), ("reserve", "Reserved"),
          ("prepare-issue", "IssuePrepared"), ("review-issue", "IssueReviewed"), ("deliver", "Delivered"),
          ("prepare-invoice", "InvoicePrepared"), ("review-invoice", "InvoiceReviewed"), ("invoice", "Invoiced"))


def _origin(value: Any, row: Mapping[str, Any], identity: bool) -> dict[str, Any]:
    origin = closed(value, ORIGIN_FIELDS)
    require(origin["schema_version"] == "stock-monetary-origin-v1")
    for key in ORIGIN_FIELDS - {"schema_version", "original_rate", "tax_components", "reviewer_actor_id", "posted_actor_id", "posting_effect_id"}:
        if not key.endswith("_minor"):
            text(origin[key], maximum=200)
    for key in ("reviewer_actor_id", "posted_actor_id", "posting_effect_id"):
        text(origin[key], nullable=True)
    digest(origin["source_digest"])
    calendar(origin["invoice_date"])
    calendar(origin["due_date"])
    require(origin["due_date"] >= origin["invoice_date"] >= row["order_date"])
    require(len(origin["country_code"]) == 2 and all("A" <= character <= "Z" for character in origin["country_code"]))
    origin["original_rate"] = rate(origin["original_rate"], day=origin["invoice_date"], identity=identity)
    amounts = {key: minor(origin[key]) for key in ORIGIN_FIELDS if key.endswith("_minor")}
    require(amounts["transaction_net_minor"] == minor(row["transaction_net_minor"], positive=True)
            and amounts["functional_net_minor"] > 0)
    for prefix in ("transaction", "functional"):
        require(amounts[prefix + "_gross_minor"] == amounts[prefix + "_net_minor"] + amounts[prefix + "_tax_minor"])
    if identity:
        require(all(amounts["transaction_" + key] == amounts["functional_" + key] for key in ("net_minor", "tax_minor", "gross_minor")))
    components = origin["tax_components"]
    require(type(components) is list and len(components) <= 8)
    checked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for component in components:
        tax = closed(component, TAX_FIELDS)
        try:
            declaration = {key: tax[key] for key in TAX_FIELDS - {"policy_digest", "transaction_tax_minor", "functional_tax_minor"}}
            require(TaxComponent(**declaration).payload(day=origin["invoice_date"], country=origin["country_code"],
                    transaction_class=origin["transaction_class"]) == {key: tax[key] for key in TAX_FIELDS - {"transaction_tax_minor", "functional_tax_minor"}})
        except (FinancePostingError, TypeError, ValueError) as exc:
            raise MonetaryResponseError("The captured tax declaration could not be verified.") from exc
        require(tax["policy_id"] not in seen)
        seen.add(tax["policy_id"])
        minor(tax["transaction_tax_minor"])
        minor(tax["functional_tax_minor"])
        if identity:
            require(tax["transaction_tax_minor"] == tax["functional_tax_minor"])
        checked.append(tax)
    require(sum(minor(tax["transaction_tax_minor"]) for tax in checked) == amounts["transaction_tax_minor"]
            and sum(minor(tax["functional_tax_minor"]) for tax in checked) == amounts["functional_tax_minor"])
    origin["tax_components"] = checked
    reviewer, poster = origin["reviewer_actor_id"], origin["posted_actor_id"]
    require(reviewer is None or reviewer != origin["preparer_actor_id"])
    require((poster is None) == (origin["posting_effect_id"] is None))
    if poster is not None:
        require(reviewer is not None and poster not in (reviewer, origin["preparer_actor_id"]))
    return origin


def _collection(value: Any, identity: bool) -> dict[str, Any]:
    row = closed(value, COLLECTION_FIELDS)
    for key in ("id", "receipt_number", "period_id", "preparer_actor_id"):
        text(row[key])
    for key in ("reviewer_actor_id", "posted_actor_id", "entry_id", "posting_effect_id", "receipt_id"):
        text(row[key], nullable=True)
    integer(row["sequence"], maximum=256, minimum=1)
    digest(row["plan_digest"])
    calendar(row["receipt_date"])
    row["settlement_rate"] = rate(row["settlement_rate"], day=row["receipt_date"], identity=identity)
    amounts = {key: minor(row[key], positive=key == "amount_minor") for key in COLLECTION_FIELDS if key.endswith("_minor")}
    require(amounts["functional_fx_gain_minor"] == 0 or amounts["functional_fx_loss_minor"] == 0)
    turnover = amounts["functional_cash_minor"] + amounts["functional_fx_loss_minor"]
    require(turnover == amounts["functional_receivable_released_minor"] + amounts["functional_fx_gain_minor"])
    require((row["entry_id"] is None) == (turnover == 0))
    require(row["status"] in ("Prepared", "Reviewed", "Posted"))
    reviewed, posted = row["status"] != "Prepared", row["status"] == "Posted"
    require((row["reviewer_actor_id"] is not None) == reviewed and (row["posted_actor_id"] is not None) == posted)
    require((row["posting_effect_id"] is not None) == (posted and turnover > 0))
    require((row["receipt_id"] is not None) == posted)
    if reviewed:
        require(row["reviewer_actor_id"] != row["preparer_actor_id"])
    if posted:
        require(row["posted_actor_id"] not in (row["preparer_actor_id"], row["reviewer_actor_id"]))
    return row


def project_monetary_stock(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    row = closed(value, STOCK_FIELDS)
    scope_of(row, scope)
    require(row["schema_version"] == "stock-sales-monetary-v2")
    for key in ("id", "number", "customer_code", "customer_reference", "item_code", "warehouse_code", "location_code", "quantity", "created_by"):
        text(row[key])
    text(row["description"], maximum=500)
    calendar(row["order_date"])
    digest(row["source_digest"])
    digest(row["issue_digest"], nullable=True)
    integer(row["row_version"], maximum=1024, minimum=1)
    integer(row["quantity_precision"], maximum=6)
    integer(row["discount_basis_points"], maximum=9999)
    for key in ("quantity_scaled", "unit_price_minor", "net_unit_price_minor", "transaction_net_minor"):
        minor(row[key], positive=True)
    try:
        require(quantity_to_scaled(row["quantity"], row["quantity_precision"]) == minor(row["quantity_scaled"]))
        quote = SalesLine(row["description"], row["quantity"], minor(row["unit_price_minor"], positive=True), row["discount_basis_points"]).priced()
        require(str(quote["unit_price_minor"]) == row["net_unit_price_minor"]
                and str(quote["line_total_minor"]) == row["transaction_net_minor"])
    except (FinancePostingError, TypeError, ValueError) as exc:
        raise MonetaryResponseError("The original stock quantity could not be verified.") from exc
    row["transaction_policy"], row["functional_policy"] = policy(row["transaction_policy"]), policy(row["functional_policy"])
    identity = row["transaction_policy"]["currency_code"] == row["functional_policy"]["currency_code"]
    for key in ("approved_by", "issue_preparer_id", "issue_reviewer_id", "cogs_entry_id", "cogs_effect_id", "movement_id", "valuation_id"):
        text(row[key], nullable=True)
    require(row["cost_admission_policy"] in (None, "partial-return-restituted-v1"))
    events = row["events"]
    require(type(events) is list and len(events) == row["row_version"])
    checked: list[dict[str, Any]] = []
    for index, item in enumerate(events):
        event = closed(item, EVENT_FIELDS)
        integer(event["version"], maximum=1024, minimum=1)
        require(event["version"] == index + 1)
        for key in ("actor_id", "operation", "status", "audit_event_id"):
            text(event[key])
        text(event["reason"], maximum=500)
        if event["operation"] == "cancel":
            require(index == len(events) - 1 and index > 0 and checked[-1]["status"] in {"Draft", "Submitted", "Approved", "Reserved", "IssuePrepared", "IssueReviewed"}
                    and event["status"] == "Cancelled")
        elif index < len(_FIRST):
            require((event["operation"], event["status"]) == _FIRST[index])
        elif event["operation"] == "prepare-collection":
            require(checked[-1]["status"] in {"Invoiced", "Paid"} and event["status"] == "CollectionPrepared")
        elif event["operation"] == "review-collection":
            require(checked[-1]["status"] == "CollectionPrepared" and event["status"] == "CollectionReviewed"
                    and event["actor_id"] != checked[-1]["actor_id"])
        else:
            require(event["operation"] == "collect" and checked[-1]["status"] == "CollectionReviewed"
                    and event["status"] in {"Invoiced", "Paid"} and event["actor_id"] not in (checked[-1]["actor_id"], checked[-2]["actor_id"]))
        checked.append(event)
    require(row["status"] == checked[-1]["status"])
    row["events"] = checked
    by_operation = {event["operation"]: event for event in checked}
    require(row["created_by"] == checked[0]["actor_id"]
            and row["approved_by"] == (by_operation["approve"]["actor_id"] if "approve" in by_operation else None))
    if row["approved_by"] is not None:
        require(row["approved_by"] != row["created_by"])
    issued = any(event["operation"] == "prepare-issue" for event in checked)
    delivered = any(event["operation"] == "deliver" for event in checked)
    require((row["issue_digest"] is not None) == issued and (row["issue_preparer_id"] is not None) == issued)
    require((row["functional_cogs_minor"] is not None) == issued)
    require(row["issue_preparer_id"] == (by_operation["prepare-issue"]["actor_id"] if issued else None)
            and row["issue_reviewer_id"] == (by_operation["review-issue"]["actor_id"] if "review-issue" in by_operation else None))
    if row["issue_reviewer_id"] is not None:
        require(row["issue_reviewer_id"] != row["issue_preparer_id"])
    if delivered:
        require(by_operation["deliver"]["actor_id"] not in (row["issue_preparer_id"], row["issue_reviewer_id"]))
    if issued:
        cost = minor(row["functional_cogs_minor"])
        require(cost > 0 or row["cost_admission_policy"] == "partial-return-restituted-v1")
        require((row["cogs_entry_id"] is not None) == (cost > 0)
                and (row["cogs_effect_id"] is not None) == (delivered and cost > 0))
    else:
        require(all(row[key] is None for key in ("cogs_entry_id", "cogs_effect_id", "cost_admission_policy")))
    require((row["movement_id"] is not None) == delivered and (row["valuation_id"] is not None) == delivered)
    invoicing = any(event["operation"] == "prepare-invoice" for event in checked)
    recognized = any(event["operation"] == "invoice" for event in checked)
    require((row["monetary_origin"] is not None) == invoicing and (row["balance"] is not None) == recognized)
    if invoicing:
        row["monetary_origin"] = _origin(row["monetary_origin"], row, identity)
        require(row["monetary_origin"]["preparer_actor_id"] == by_operation["prepare-invoice"]["actor_id"]
                and row["monetary_origin"]["reviewer_actor_id"] == (by_operation["review-invoice"]["actor_id"] if "review-invoice" in by_operation else None)
                and row["monetary_origin"]["posted_actor_id"] == (by_operation["invoice"]["actor_id"] if recognized else None))
    if recognized:
        row["balance"] = closed(row["balance"], BALANCE)
        require(row["balance"]["schema_version"] == "stock-monetary-balance-v1")
        balance_fields(row["balance"])
        origin = row["monetary_origin"]
        require(row["balance"]["transaction_original_gross_minor"] == origin["transaction_gross_minor"]
                and row["balance"]["functional_original_gross_minor"] == origin["functional_gross_minor"])
    if row["collection"] is not None:
        require(recognized)
        row["collection"] = _collection(row["collection"], identity)
        require(row["collection"]["preparer_actor_id"] == by_operation["prepare-collection"]["actor_id"])
        if row["collection"]["status"] != "Prepared":
            require(row["collection"]["reviewer_actor_id"] == by_operation["review-collection"]["actor_id"])
        if row["collection"]["status"] == "Posted":
            require(row["collection"]["posted_actor_id"] == by_operation["collect"]["actor_id"])
        else:
            require(row["balance"]["active_plan_id"] == row["collection"]["id"])
    return row


def project_monetary_stock_response(value: Any, scope: Mapping[str, Any], *, listing: bool = False) -> dict[str, Any]:
    if not listing:
        return project_monetary_stock(value, scope)
    row = closed(value, frozenset({"orders"}))
    require(type(row["orders"]) is list and len(row["orders"]) <= 100)
    row["orders"] = [project_monetary_stock(item, scope) for item in row["orders"]]
    require(len({item["id"] for item in row["orders"]}) == len(row["orders"]))
    return row


def project_monetary_stock_options(value: Any) -> dict[str, Any]:
    specifications = {
        "customers": (100, frozenset({"customer_code", "name", "currency_code"})),
        "periods": (50, frozenset({"id", "name", "start_date", "end_date"})),
        "journals": (100, frozenset({"journal_code", "name", "currency_code"})),
        "accounts": (200, frozenset({"account_code", "name", "account_type", "chart_id"})),
        "items": (100, frozenset({"item_code", "name", "uom_code", "decimal_places"})),
        "warehouses": (100, frozenset({"warehouse_code", "name"})),
        "locations": (200, frozenset({"warehouse_code", "location_code", "name"})),
        "policies": (100, frozenset({"policy_code", "name", "journal_code"})),
    }
    row = closed(value, frozenset(specifications))
    for key, (maximum, fields) in specifications.items():
        require(type(row[key]) is list and len(row[key]) <= maximum)
        checked: list[dict[str, Any]] = []
        for original in row[key]:
            item = closed(original, fields)
            for field in fields - {"decimal_places"}:
                text(item[field], maximum=500)
            if key == "items":
                integer(item["decimal_places"], maximum=6)
            if key == "accounts":
                require(item["account_type"] in {"Asset", "Income", "Expense", "Liability"})
            if key in {"customers", "journals"}:
                code = item["currency_code"]
                require(len(code) == 3 and all("A" <= character <= "Z" for character in code))
            if key == "periods":
                calendar(item["start_date"])
                calendar(item["end_date"])
                require(item["start_date"] <= item["end_date"])
            checked.append(item)
        row[key] = checked
    return row
