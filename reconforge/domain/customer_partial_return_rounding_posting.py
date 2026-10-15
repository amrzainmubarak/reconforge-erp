"""Nonzero-only v2 correction proposals over the original FinancePosting pins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reconforge.domain.customer_partial_return_posting import (
    PartialReturnAccountRoles,
    PartialReturnPostingIntent,
    _line,
    _policy_payload,
    _require,
    _role_lines,
    _scope_payload,
)
from reconforge.domain.customer_partial_return_rounding import (
    ALLOCATION_POLICY,
    RemainingReturnPlan,
    verify_remaining_return_plan,
)
from reconforge.domain.finance_posting import canonical_json, digest_payload


@dataclass(frozen=True, slots=True)
class RemainingPostingContract:
    """An immutable derivation, not a submitted/reviewed/postable ledger entry."""

    plan: RemainingReturnPlan
    roles: PartialReturnAccountRoles
    intent: PartialReturnPostingIntent

    def __post_init__(self) -> None:
        self.payload()

    def payload(self) -> dict[str, Any]:
        plan, roles, intent = self.plan, self.roles, self.intent
        verify_remaining_return_plan(plan)
        _require(type(roles) is PartialReturnAccountRoles and type(intent) is PartialReturnPostingIntent)
        source = plan.source
        role_payload, requested = roles.payload(), intent.payload()
        _require(roles.scope == source.scope and roles.source_fingerprint == source.fingerprint)
        _require(canonical_json(_policy_payload(roles.currency_policy)) == canonical_json(_policy_payload(source.currency_policy)))
        revenue_snapshot, cogs_snapshot = source.original_revenue.snapshot(), source.original_cogs.snapshot()
        ar, revenue = _role_lines(revenue_snapshot, debit_account=roles.receivable_account_id, credit_account=roles.revenue_account_id)
        cogs, inventory = _role_lines(cogs_snapshot, debit_account=roles.cogs_account_id, credit_account=roles.inventory_account_id)
        _require(ar["debit_minor"] == source.gross_minor and plan.credit_minor <= source.gross_minor
            and plan.cogs_restored_minor <= cogs["debit_minor"]
            and plan.receivable_released_minor + plan.refund_entitlement_delta_minor == plan.credit_minor)
        for snapshot in (revenue_snapshot, cogs_snapshot):
            _require(canonical_json({key: snapshot["entry"][key] for key in _policy_payload(source.currency_policy)})
                == canonical_json(_policy_payload(source.currency_policy)))
            _require(all(snapshot["entry"][key] == getattr(source.scope, key)
                for key in ("workspace_id", "organization_id", "legal_entity_id")))
        revenue_lines = []
        if plan.credit_minor:
            revenue_lines.append(_line(1, revenue, debit=plan.credit_minor, reason=requested["reason"]))
            if plan.receivable_released_minor:
                revenue_lines.append(_line(len(revenue_lines) + 1, ar, credit=plan.receivable_released_minor, reason=requested["reason"]))
            if plan.refund_entitlement_delta_minor:
                revenue_lines.append(_line(len(revenue_lines) + 1, {**ar, "account_id": roles.refund_liability_account_id},
                    credit=plan.refund_entitlement_delta_minor, reason=requested["reason"]))
        cost_lines = []
        if plan.cogs_restored_minor:
            cost_lines = [_line(1, inventory, debit=plan.cogs_restored_minor, reason=requested["reason"]),
                          _line(2, cogs, credit=plan.cogs_restored_minor, reason=requested["reason"])]
        common = {"schema_version": "customer-partial-return-correction-template-v2", "allocation_policy": ALLOCATION_POLICY,
            "source_fingerprint": plan.source_fingerprint, "history_fingerprint": plan.history_fingerprint,
            "plan_fingerprint": plan.fingerprint, "account_roles_fingerprint": digest_payload(role_payload),
            "scope": _scope_payload(source.scope), "currency_policy": _policy_payload(source.currency_policy),
            "posting_intent": requested, "portions": plan.payload()["portions"], "reverses_posting_id": None,
            "requires_native_participant": True, "requires_current_authorization": True,
            "requires_three_person_approval": True, "postable": False}
        templates = []
        for purpose, evidence, snapshot, lines in (
            ("RevenueCredit", source.original_revenue, revenue_snapshot, revenue_lines),
            ("CostRestoration", source.original_cogs, cogs_snapshot, cost_lines),
        ):
            if not lines:
                continue
            templates.append({**common, "purpose": purpose, "original_posting_effect_id": evidence.posting_effect_id,
                "original_entry_id": evidence.entry_id, "original_validation_digest": evidence.validation_digest,
                "journal_id": snapshot["entry"]["journal_id"], "lines": lines})
        return {"schema_version": "customer-partial-return-posting-contract-v2", "allocation_policy": ALLOCATION_POLICY,
                "postable": False, "templates": templates}


def build_remaining_posting_contract(plan: RemainingReturnPlan, *, roles: PartialReturnAccountRoles,
                                     intent: PartialReturnPostingIntent) -> RemainingPostingContract:
    return RemainingPostingContract(plan, roles, intent)
