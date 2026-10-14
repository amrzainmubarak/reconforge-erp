"""Unapproved, source-pinned CR2 correction templates for the existing ledger.

This finite contract handles untaxed functional-currency merchandise only.
It does not open periods, authenticate account pins, approve, post, or create
full financial inverses. Native ownership and three-person governance remain
mandatory before an adapter can create or post any financial entry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, NoReturn, cast

from reconforge.domain.customer_partial_returns import (
    MAX_CONSUMPTIONS,
    PartialReturnPlan,
    PartialReturnScope,
    verify_partial_return_plan,
)
from reconforge.domain.customer_returns import MAX_MINOR
from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import (
    FinancePostingError,
    canonical_json,
    digest_payload,
    make_entry_snapshot,
    text,
    validation_digest,
)

TEMPLATE_VERSION = "customer-partial-return-correction-template-v1"
CONTRACT_VERSION = "customer-partial-return-posting-contract-v1"
_SCOPE_FIELDS = ("tenant_id", "workspace_id", "organization_id", "legal_entity_id", "item_id", "location_id", "uom_id")
_ROLE_FIELDS = ("receivable_account_id", "revenue_account_id", "inventory_account_id", "cogs_account_id", "refund_liability_account_id")


def _refuse() -> NoReturn:
    raise FinancePostingError("customer_partial_return_posting_invalid", "Original partial-return correction contract refused.")


def _require(value: bool) -> None:
    if not value:
        _refuse()


def _identifier(value: object, field: str, *, maximum: int = 160) -> str:
    _require(type(value) is str)
    normalized = text(value, field, maximum=maximum)
    _require(normalized == value)
    return normalized


def _fingerprint(value: object) -> str:
    value = _identifier(value, "content fingerprint")
    _require(len(value) == 64 and all(character in "0123456789abcdef" for character in value))
    return value


def _minor(value: object, *, positive: bool = False) -> int:
    _require(type(value) is int and (1 if positive else 0) <= value <= MAX_MINOR)
    return cast(int, value)


def _scope_payload(scope: PartialReturnScope) -> dict[str, str]:
    _require(type(scope) is PartialReturnScope)
    return {name: _identifier(getattr(scope, name), name) for name in _SCOPE_FIELDS}


def _policy_payload(policy: FinanceCurrencyPolicy) -> dict[str, Any]:
    _require(type(policy) is FinanceCurrencyPolicy and type(policy.precision) is int and 0 <= policy.precision <= 8)
    _require(policy.rounding_policy == "ROUND_HALF_UP")
    _identifier(policy.registry_version, "currency registry version")
    return {"currency_code": _identifier(policy.currency_code, "currency"), **policy.metadata(),
            "currency_registry_digest": _fingerprint(policy.registry_digest)}


@dataclass(frozen=True)
class PartialReturnPostingIntent:
    """Requested period and date; their openness and authorization are unproven."""

    period_id: str
    posting_date: str
    reason: str

    def __post_init__(self) -> None:
        self.payload()

    def payload(self) -> dict[str, str]:
        value = {"period_id": _identifier(self.period_id, "period"),
                 "posting_date": _identifier(self.posting_date, "posting date"),
                 "reason": _identifier(self.reason, "reason", maximum=500)}
        try:
            _require(date.fromisoformat(value["posting_date"]).isoformat() == value["posting_date"])
        except ValueError:
            _refuse()
        return value


@dataclass(frozen=True)
class PartialReturnAccountRoles:
    """Native-supplied source/chart pins; this class cannot prove their DB ownership."""

    scope: PartialReturnScope
    source_fingerprint: str
    currency_policy: FinanceCurrencyPolicy
    receivable_account_id: str
    revenue_account_id: str
    inventory_account_id: str
    cogs_account_id: str
    refund_liability_account_id: str
    refund_liability_account_type: str

    def __post_init__(self) -> None:
        self.payload()

    def payload(self) -> dict[str, Any]:
        accounts = {name: _identifier(getattr(self, name), name) for name in _ROLE_FIELDS}
        _require(len(set(accounts.values())) == len(accounts))
        _require(type(self.refund_liability_account_type) is str and self.refund_liability_account_type == "Liability")
        return {"scope": _scope_payload(self.scope), "source_fingerprint": _fingerprint(self.source_fingerprint),
                "currency_policy": _policy_payload(self.currency_policy), "accounts": accounts,
                "refund_liability_account_type": self.refund_liability_account_type}


def _json_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _require(key not in result)
        result[key] = value
    return result


def _json_number(_: str) -> NoReturn:
    _refuse()


def _decode(value: str) -> dict[str, Any]:
    _require(type(value) is str)
    try:
        _require(len(value.encode("utf8")) <= 2_097_152)
        result = json.loads(value, object_pairs_hook=_json_pairs, parse_float=_json_number, parse_constant=_json_number)
        _require(type(result) is dict and canonical_json(result) == value)
    except (ValueError, RecursionError):
        _refuse()
    return result


def _line(number: int, original: dict[str, Any], *, debit: int = 0, credit: int = 0,
          reason: str) -> dict[str, Any]:
    _minor(debit)
    _minor(credit)
    _require((debit > 0) != (credit > 0))
    return {"line_number": number, "account_id": original["account_id"], "description": reason,
            "debit_minor": debit, "credit_minor": credit, "dimensions": dict(original["dimensions"])}


def _typed_lines(payload: dict[str, Any]) -> None:
    # Existing Core validates its typed lines and retained policy. Temporary
    # labels exist only in this validator; no financial entry/ID is emitted.
    header = {**payload["currency_policy"],
              **{name: payload["scope"][name] for name in ("workspace_id", "organization_id", "legal_entity_id")},
              "id": "CR2-content-validation", "entry_number": "CR2-content-validation",
              "journal_id": payload["journal_id"], "period_id": payload["posting_intent"]["period_id"],
              "posting_date": payload["posting_intent"]["posting_date"], "description": payload["posting_intent"]["reason"],
              "external_reference": payload["plan_fingerprint"], "source_type": "Manual",
              "preparer_actor_id": None, "reverses_posting_id": None}
    normalized = make_entry_snapshot(header, payload["lines"])
    _require(canonical_json(normalized["lines"]) == canonical_json(payload["lines"]))


def _nested_template(payload: dict[str, Any]) -> None:
    scope, policy, intent, portions, lines = (payload[key] for key in
        ("scope", "currency_policy", "posting_intent", "portions", "lines"))
    _require(type(scope) is dict and set(scope) == set(_SCOPE_FIELDS))
    for key in _SCOPE_FIELDS:
        _identifier(scope[key], key)
    policy_fields = {"currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest"}
    _require(type(policy) is dict and set(policy) == policy_fields)
    captured = FinanceCurrencyPolicy(_identifier(policy["currency_code"], "currency"), _minor(policy["currency_precision"]),
        _identifier(policy["currency_rounding_policy"], "rounding"), _identifier(policy["currency_registry_version"], "registry version"),
        _fingerprint(policy["currency_registry_digest"]))
    _require(canonical_json(_policy_payload(captured)) == canonical_json(policy))
    _require(type(intent) is dict and set(intent) == {"period_id", "posting_date", "reason"})
    _require(PartialReturnPostingIntent(**intent).payload() == intent)
    _require(type(portions) is list and 1 <= len(portions) <= MAX_CONSUMPTIONS)
    portion_fields = {"position", "original_consumption_id", "original_valuation_line_id", "cost_layer_id",
                      "offset_quantity_scaled", "quantity_scaled", "value_minor"}
    seen_consumptions: set[str] = set()
    seen_layers: set[str] = set()
    previous = 0
    for portion in portions:
        _require(type(portion) is dict and set(portion) == portion_fields)
        position = _minor(portion["position"], positive=True)
        _require(previous < position <= MAX_CONSUMPTIONS and (previous == 0 or position == previous + 1))
        previous = position
        for field in ("original_consumption_id", "original_valuation_line_id", "cost_layer_id"):
            _identifier(portion[field], field)
        _require(portion["original_consumption_id"] not in seen_consumptions and portion["cost_layer_id"] not in seen_layers)
        seen_consumptions.add(portion["original_consumption_id"])
        seen_layers.add(portion["cost_layer_id"])
        _minor(portion["offset_quantity_scaled"])
        _minor(portion["quantity_scaled"], positive=True)
        _minor(portion["value_minor"], positive=True)
    _require(type(lines) is list and len(lines) in ({2, 3} if payload["purpose"] == "RevenueCredit" else {2}))
    _require(all(type(line) is dict for line in lines))
    _typed_lines(payload)
    _require([line["line_number"] for line in lines] == list(range(1, len(lines) + 1)))
    _require(len({line["account_id"] for line in lines}) == len(lines))
    for line in lines:
        _minor(line["debit_minor"])
        _minor(line["credit_minor"])
        _require(line["description"] == intent["reason"])
    _require(lines[0]["debit_minor"] > 0 and all(line["credit_minor"] > 0 for line in lines[1:]))
    if payload["purpose"] == "CostRestoration":
        _require(sum(portion["value_minor"] for portion in portions) == lines[0]["debit_minor"])


@dataclass(frozen=True)
class PartialReturnCorrectionTemplate:
    """Immutable content proposal; it contains no reviewed or posted entry."""

    template_json: str

    def __post_init__(self) -> None:
        self.payload()

    def payload(self) -> dict[str, Any]:
        result = _decode(self.template_json)
        _require(set(result) == {"schema_version", "purpose", "source_fingerprint", "history_fingerprint", "plan_fingerprint",
            "account_roles_fingerprint", "original_posting_effect_id", "original_entry_id", "original_validation_digest",
            "scope", "currency_policy", "journal_id", "posting_intent", "lines", "portions",
            "reverses_posting_id", "requires_native_participant", "requires_current_authorization",
            "requires_three_person_approval", "postable"})
        _require(result["schema_version"] == TEMPLATE_VERSION and type(result["purpose"]) is str
            and result["purpose"] in {"RevenueCredit", "CostRestoration"})
        for key in ("source_fingerprint", "history_fingerprint", "plan_fingerprint", "account_roles_fingerprint", "original_validation_digest"):
            _fingerprint(result[key])
        for key in ("original_posting_effect_id", "original_entry_id", "journal_id"):
            _identifier(result[key], key)
        _require(result["reverses_posting_id"] is None and result["postable"] is False
            and all(result[key] is True for key in ("requires_native_participant", "requires_current_authorization", "requires_three_person_approval")))
        _nested_template(result)
        return result

    @property
    def fingerprint(self) -> str:
        return digest_payload(self.payload())


@dataclass(frozen=True)
class PartialReturnPostingContract:
    """Two content-only corrections; native participant admission is still required."""

    revenue_credit: PartialReturnCorrectionTemplate
    cost_restoration: PartialReturnCorrectionTemplate

    def __post_init__(self) -> None:
        self.payload()

    def payload(self) -> dict[str, Any]:
        _require(type(self.revenue_credit) is type(self.cost_restoration) is PartialReturnCorrectionTemplate)
        revenue, cost = self.revenue_credit.payload(), self.cost_restoration.payload()
        _require(revenue["purpose"] == "RevenueCredit" and cost["purpose"] == "CostRestoration")
        common = ("source_fingerprint", "history_fingerprint", "plan_fingerprint", "account_roles_fingerprint",
                  "scope", "currency_policy", "posting_intent", "portions")
        _require(all(canonical_json(revenue[key]) == canonical_json(cost[key]) for key in common))
        _require(revenue["original_posting_effect_id"] != cost["original_posting_effect_id"]
                 and revenue["original_entry_id"] != cost["original_entry_id"])
        return {"schema_version": CONTRACT_VERSION, "postable": False,
                "templates": [revenue, cost]}

    @property
    def fingerprint(self) -> str:
        return digest_payload(self.payload())


def _role_lines(snapshot: dict[str, Any], *, debit_account: str, credit_account: str) -> tuple[dict[str, Any], dict[str, Any]]:
    validation_digest(snapshot)
    _require(len(snapshot["lines"]) == 2)
    debit, credit = snapshot["lines"]
    _require(debit["line_number"] == 1 and credit["line_number"] == 2
        and debit["account_id"] == debit_account and credit["account_id"] == credit_account
        and debit["credit_minor"] == credit["debit_minor"] == 0
        and _minor(debit["debit_minor"], positive=True) == _minor(credit["credit_minor"], positive=True))
    return debit, credit


def build_partial_return_posting_contract(plan: PartialReturnPlan, *, roles: PartialReturnAccountRoles,
                                         intent: PartialReturnPostingIntent) -> PartialReturnPostingContract:
    """Validate pins and derive exact corrections; never approve or post them."""
    verify_partial_return_plan(plan)
    _require(type(roles) is PartialReturnAccountRoles and type(intent) is PartialReturnPostingIntent)
    source = plan.source
    role_payload, requested = roles.payload(), intent.payload()
    _require(roles.scope == source.scope and roles.source_fingerprint == plan.source_fingerprint)
    _require(canonical_json(_policy_payload(roles.currency_policy)) == canonical_json(_policy_payload(source.currency_policy)))
    credit, cost = _minor(plan.credit_minor, positive=True), _minor(plan.cogs_restored_minor, positive=True)
    release = _minor(plan.receivable_released_minor)
    refund = _minor(plan.refund_entitlement_delta_minor)
    _require(release + refund == credit)
    revenue_original, cost_original = source.original_revenue.snapshot(), source.original_cogs.snapshot()
    ar, revenue = _role_lines(revenue_original, debit_account=roles.receivable_account_id, credit_account=roles.revenue_account_id)
    cogs, inventory = _role_lines(cost_original, debit_account=roles.cogs_account_id, credit_account=roles.inventory_account_id)
    _require(ar["debit_minor"] == source.gross_minor and credit <= source.gross_minor and cost <= cogs["debit_minor"])
    for snapshot in (revenue_original, cost_original):
        _require(canonical_json({key: snapshot["entry"][key] for key in _policy_payload(source.currency_policy)})
                 == canonical_json(_policy_payload(source.currency_policy)))
        _require(all(snapshot["entry"][key] == getattr(source.scope, key)
                     for key in ("workspace_id", "organization_id", "legal_entity_id")))
    revenue_lines = [_line(1, revenue, debit=credit, reason=requested["reason"])]
    if release:
        revenue_lines.append(_line(len(revenue_lines) + 1, ar, credit=release, reason=requested["reason"]))
    if refund:
        revenue_lines.append(_line(len(revenue_lines) + 1, {**ar, "account_id": roles.refund_liability_account_id},
                                   credit=refund, reason=requested["reason"]))
    cost_lines = [_line(1, inventory, debit=cost, reason=requested["reason"]),
                  _line(2, cogs, credit=cost, reason=requested["reason"])]
    plan_payload = plan.payload()
    common = {"schema_version": TEMPLATE_VERSION, "source_fingerprint": plan.source_fingerprint,
              "history_fingerprint": plan.history_fingerprint, "plan_fingerprint": plan.fingerprint,
              "account_roles_fingerprint": digest_payload(role_payload), "scope": _scope_payload(source.scope),
              "currency_policy": _policy_payload(source.currency_policy), "posting_intent": requested,
              "portions": plan_payload["portions"], "reverses_posting_id": None,
              "requires_native_participant": True, "requires_current_authorization": True,
              "requires_three_person_approval": True, "postable": False}
    templates = []
    for purpose, evidence, snapshot, lines in (
            ("RevenueCredit", source.original_revenue, revenue_original, revenue_lines),
            ("CostRestoration", source.original_cogs, cost_original, cost_lines)):
        templates.append(PartialReturnCorrectionTemplate(canonical_json({**common, "purpose": purpose,
            "original_posting_effect_id": evidence.posting_effect_id, "original_entry_id": evidence.entry_id,
            "original_validation_digest": evidence.validation_digest, "journal_id": snapshot["entry"]["journal_id"], "lines": lines})))
    return PartialReturnPostingContract(templates[0], templates[1])


def verify_partial_return_posting_contract(contract: PartialReturnPostingContract, plan: PartialReturnPlan,
                                          roles: PartialReturnAccountRoles, intent: PartialReturnPostingIntent) -> None:
    """Refuse balanced-but-wrong proposals by recomputing from original pins."""
    _require(type(contract) is PartialReturnPostingContract)
    expected = build_partial_return_posting_contract(plan, roles=roles, intent=intent)
    _require(canonical_json(contract.payload()) == canonical_json(expected.payload()))
