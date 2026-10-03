"""Closed API projections with exact evidence and browser-safe money strings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_balances import AMOUNT_FIELDS, POLICY_FIELDS, verify_posted_balances
from reconforge.domain.finance_posting import (
    PROVENANCE_FIELDS,
    canonical_json,
    validation_digest,
)

API_POSTING_CONTRACT = "finance-posting-api-v1"
EFFECT_FIELDS = frozenset({
    "id", "workspace_id", "organization_id", "legal_entity_id", "entry_id",
    "source_kind", "source_id", "purpose", "reverses_effect_id",
    "validation_digest", "validation_contract_version", "currency_code",
    "currency_precision", "currency_rounding_policy", "currency_registry_version",
    "currency_registry_digest", "posted_actor_id", "posted_at", "reason",
    "audit_event_id", "outbox_event_id",
})


def _minor(value: Any) -> str:
    if type(value) is not int:
        raise ValueError("Posting amounts must be exact integer minor units.")
    return str(value)


def _snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    # Verification also rejects unknown snapshot fields and noncanonical lines.
    digest = validation_digest(value)
    lines = [{
        "line_number": row["line_number"], "account_id": row["account_id"],
        "description": row["description"], "dimensions": row["dimensions"],
        "debit_minor": _minor(row["debit_minor"]),
        "credit_minor": _minor(row["credit_minor"]),
    } for row in value["lines"]]
    return {
        "api_contract_version": API_POSTING_CONTRACT,
        "snapshot_json": canonical_json(value),
        "snapshot_digest": digest,
        "entry": dict(value["entry"]),
        "lines": lines,
    }


def project_posting_preview(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{key: value[key] for key in ("entry_id", "status", *PROVENANCE_FIELDS, "current_content_digest")},
        **_snapshot(value["snapshot"]),
    }


def project_posting_effect(value: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: value[key] for key in sorted(EFFECT_FIELDS)}
    snapshot = _snapshot(value["snapshot"])
    if snapshot["snapshot_digest"] != result["validation_digest"]:
        raise ValueError("Posting effect does not match its retained validation digest.")
    return {**result, **snapshot}


def project_posting_reversal(value: Mapping[str, Any]) -> dict[str, Any]:
    if value["status"] != "Draft":
        raise ValueError("Prepared reversal must remain an independently reviewable Draft.")
    return {"api_contract_version": API_POSTING_CONTRACT, **{
        key: value[key] for key in ("entry_id", "entry_number", "status", "reverses_posting_id", "preparer_actor_id")
    }}


def project_posted_trial_balance(value: Mapping[str, Any]) -> dict[str, Any]:
    totals = value["totals"]
    balances = value["balance_totals"]
    for aggregate in (totals, balances):
        _minor(aggregate["debit_minor"])
        _minor(aggregate["credit_minor"])
        if type(aggregate["balanced"]) is not bool or aggregate["balanced"] != (aggregate["debit_minor"] == aggregate["credit_minor"]):
            raise ValueError("Posted trial balance has invalid exact totals.")
    account_ids: set[str] = set()
    posting_lines: set[tuple[str, int]] = set()
    effect_ids: set[str] = set()
    debit_turnover = credit_turnover = debit_balances = credit_balances = 0
    for account in value["accounts"]:
        account_id = account["account_id"]
        if account_id in account_ids:
            raise ValueError("Posted trial balance contains duplicate accounts.")
        account_ids.add(account_id)
        debit = credit = 0
        for line in account["postings"]:
            _minor(line["debit_minor"])
            _minor(line["credit_minor"])
            if min(line["debit_minor"], line["credit_minor"]) < 0 or (line["debit_minor"] > 0 and line["credit_minor"] > 0):
                raise ValueError("Posted trial balance has invalid contributing amounts.")
            key = (line["effect_id"], line["line_number"])
            if key in posting_lines:
                raise ValueError("Posted trial balance repeats a contributing line.")
            posting_lines.add(key)
            effect_ids.add(line["effect_id"])
            debit += line["debit_minor"]
            credit += line["credit_minor"]
        expected = {
            "debit_minor": debit, "credit_minor": credit, "balance_minor": debit - credit,
            "debit_balance_minor": max(debit - credit, 0), "credit_balance_minor": max(credit - debit, 0),
        }
        if any(_minor(account[key]) != str(amount) for key, amount in expected.items()):
            raise ValueError("Posted account balances do not match their contributing evidence.")
        debit_turnover += debit
        credit_turnover += credit
        debit_balances += expected["debit_balance_minor"]
        credit_balances += expected["credit_balance_minor"]
    if (
        type(value["effect_count"]) is not int or value["effect_count"] != len(effect_ids)
        or (totals["debit_minor"], totals["credit_minor"]) != (debit_turnover, credit_turnover)
        or (balances["debit_minor"], balances["credit_minor"]) != (debit_balances, credit_balances)
    ):
        raise ValueError("Posted trial balance aggregates do not match their contributing evidence.")
    policy = value["currency_policy"]
    return {
        "api_contract_version": API_POSTING_CONTRACT,
        "balance_scope": "selected-period-net-activity",
        **{key: value[key] for key in ("workspace_id", "organization_code", "entity_code", "period_id", "effect_count")},
        "currency_policy": None if policy is None else {key: policy[key] for key in (
            "currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest",
        )},
        "accounts": [{
            "account_id": account["account_id"],
            **{key: _minor(account[key]) for key in ("debit_minor", "credit_minor", "balance_minor", "debit_balance_minor", "credit_balance_minor")},
            "postings": [{
                **{key: line[key] for key in ("effect_id", "entry_id", "line_number")},
                **{key: _minor(line[key]) for key in ("debit_minor", "credit_minor")},
            } for line in account["postings"]],
        } for account in value["accounts"]],
        "turnover_totals": {
            "debit_minor": _minor(totals["debit_minor"]),
            "credit_minor": _minor(totals["credit_minor"]),
            "balanced": totals["balanced"],
        },
        "balance_totals": {
            "debit_minor": _minor(balances["debit_minor"]),
            "credit_minor": _minor(balances["credit_minor"]),
            "balanced": balances["balanced"],
        },
    }


def project_posted_balances(value: Mapping[str, Any]) -> dict[str, Any]:
    verify_posted_balances(value)
    return {
        "api_contract_version": API_POSTING_CONTRACT,
        **{key: value[key] for key in (
            "contract_version", "balance_scope", "workspace_id", "organization_id", "legal_entity_id", "organization_code",
            "entity_code", "period_id", "period_start", "period_end", "as_of_date", "report_digest",
        )},
        "report_json": canonical_json(value),
        "currency_policy": None if value["currency_policy"] is None else {key: value["currency_policy"][key] for key in POLICY_FIELDS},
        "accounts": [{
            "account_id": account["account_id"],
            **{phase: {key: _minor(account[phase][key]) for key in AMOUNT_FIELDS} for phase in ("opening", "activity", "closing")},
            "postings": [{
                **{key: line[key] for key in ("effect_id", "entry_id", "period_id", "posting_date", "phase", "line_number")},
                **{key: _minor(line[key]) for key in ("debit_minor", "credit_minor")},
            } for line in account["postings"]],
        } for account in value["accounts"]],
        "totals": {phase: {
            "effect_count": totals["effect_count"],
            **{kind: {
                "debit_minor": _minor(totals[kind]["debit_minor"]), "credit_minor": _minor(totals[kind]["credit_minor"]),
                "balanced": totals[kind]["balanced"],
            } for kind in ("turnover_totals", "balance_totals")},
        } for phase, totals in value["totals"].items()},
    }
