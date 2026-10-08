"""Closed receipt evidence projection with exact integer strings for browsers."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_posting import canonical_json
from reconforge.domain.inventory_receipt_posting import verify_effect, verify_plan, verify_review

API_VERSION = "inventory-receipt-api-v1"

def project_receipt_view(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {"plan", "review", "effect"}:
        raise ValueError("Receipt view must contain exactly plan, review and effect.")
    plan = verify_plan(value["plan"])
    review = None if value["review"] is None else verify_review(value["review"], plan)
    effect = None
    if value["effect"] is not None:
        if review is None:
            raise ValueError("Receipt effect requires retained independent review.")
        effect = verify_effect(value["effect"], plan, review)
    source = plan["source"]
    return {
        "api_contract_version": API_VERSION, "plan_id": plan["plan_id"],
        "operation": plan["operation"], "status": "Committed" if effect else "Reviewed" if review else "Prepared",
        "scope": dict(plan["scope"]), "number": source["number"], "posting_date": source["posting_date"],
        "period_id": source["period_id"], "quantity": source["quantity_text"],
        "total_value_minor": str(source["total_value_minor"]), "currency_code": plan["currency_policy"]["currency_code"],
        "currency_precision": plan["currency_policy"]["currency_precision"],
        "preparer_id": plan["preparer"]["user_id"], "reviewer_id": review["reviewer"]["user_id"] if review else None,
        "plan_digest": plan["plan_digest"], "review_digest": review["review_digest"] if review else None,
        "effect_id": effect["effect_id"] if effect else None, "effect_digest": effect["effect_digest"] if effect else None,
        "movement_id": effect["movement_id"] if effect else None, "entry_id": effect["entry_id"] if effect else None,
        "cost_layer_id": effect["cost_layer_id"] if effect else None,
        "lines": [{"account_id": line["account_id"], "debit_minor": str(line["debit_minor"]),
                   "credit_minor": str(line["credit_minor"])} for line in plan["finance_snapshot"]["lines"]],
        "plan_json": canonical_json(plan), "review_json": canonical_json(review) if review else None,
        "effect_json": canonical_json(effect) if effect else None,
    }
