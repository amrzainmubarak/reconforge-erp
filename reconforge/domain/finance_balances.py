"""Verified business-date opening, movement and closing posting balances."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from reconforge.domain.finance_posting import (
    MAX_SNAPSHOT_BYTES,
    FinancePostingError,
    canonical_json,
    digest_payload,
    text,
    validation_digest,
)

BALANCES_CONTRACT = "finance-posted-balances-v1"
MAX_BALANCE_EFFECTS = 1000
MAX_BALANCE_LINES = 10000
POLICY_FIELDS = (
    "currency_code", "currency_precision", "currency_rounding_policy",
    "currency_registry_version", "currency_registry_digest",
)
AMOUNT_FIELDS = ("debit_minor", "credit_minor", "balance_minor", "debit_balance_minor", "credit_balance_minor")


def collect_balance_effects(effects: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Stop incremental verified-snapshot loading as soon as a budget is exceeded."""
    retained: list[Mapping[str, Any]] = []
    line_count = snapshot_bytes = 0
    for effect in effects:
        line_count += len(effect["snapshot"]["lines"])
        snapshot_bytes += len(canonical_json(effect["snapshot"]).encode("utf-8"))
        if len(retained) >= MAX_BALANCE_EFFECTS or line_count > MAX_BALANCE_LINES or snapshot_bytes > MAX_SNAPSHOT_BYTES:
            raise FinancePostingError("posting_balance_limit", "The bounded balance report exceeds its verified evidence budget.")
        retained.append(effect)
    return retained


def business_date(value: object) -> str:
    if not isinstance(value, str):
        raise FinancePostingError("posting_date_invalid", "A canonical YYYY-MM-DD business date is required.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise FinancePostingError("posting_date_invalid", "A canonical YYYY-MM-DD business date is required.") from exc
    if parsed.isoformat() != value:
        raise FinancePostingError("posting_date_invalid", "A canonical YYYY-MM-DD business date is required.")
    return value


def balance_window(start_date: object, end_date: object, as_of_date: object) -> tuple[str, str, str]:
    start, end, cutoff = (business_date(value) for value in (start_date, end_date, as_of_date))
    if not start <= cutoff <= end:
        raise FinancePostingError("posting_date_invalid", "The as-of business date must fall within the selected period.")
    return start, end, cutoff


def _amounts(debit: int, credit: int) -> dict[str, int]:
    return {
        "debit_minor": debit, "credit_minor": credit, "balance_minor": debit - credit,
        "debit_balance_minor": max(debit - credit, 0), "credit_balance_minor": max(credit - debit, 0),
    }


def _identifier(value: object, field: str) -> str:
    cleaned = text(value, field)
    if cleaned != value:
        raise FinancePostingError("posting_evidence_invalid", "Posted balance evidence must retain canonical identifiers.")
    return cleaned


def build_posted_balances(
    *, workspace_id: str, organization_code: str, entity_code: str, organization_id: str, legal_entity_id: str, period_id: str,
    period_start: str, period_end: str, as_of_date: str,
    effects: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Consume independently verified effects; never infer unposted or missing history.

    Opening is all retained posting activity before the selected period starts;
    activity spans its start through the inclusive cutoff, and closing adds both.
    This is a business-date view of currently recorded immutable effects, rather
    than a historical knowledge-time view or statutory fiscal close.
    """
    start, end, cutoff = balance_window(period_start, period_end, as_of_date)
    if len(effects) > MAX_BALANCE_EFFECTS:
        raise FinancePostingError("posting_balance_limit", "The bounded balance report exceeds its effect limit.")
    scope = {key: text(value, key) for key, value in (
        ("workspace_id", workspace_id), ("organization_code", organization_code),
        ("entity_code", entity_code), ("organization_id", organization_id), ("legal_entity_id", legal_entity_id), ("period_id", period_id),
    )}
    accounts: dict[str, dict[str, Any]] = {}
    policy: dict[str, Any] | None = None
    effect_ids: set[str] = set()
    phase_effects: dict[str, set[str]] = {"opening": set(), "activity": set()}
    line_count = 0
    for effect in sorted(effects, key=lambda item: item["id"]):
        snapshot = effect["snapshot"]
        header = snapshot["entry"]
        effect_id = text(effect["id"], "effect_id")
        if (
            effect_id in effect_ids or effect["entry_id"] != header["id"]
            or effect["workspace_id"] != scope["workspace_id"] or header["workspace_id"] != scope["workspace_id"]
            or any(effect[key] != scope[key] or header[key] != scope[key] for key in ("organization_id", "legal_entity_id"))
            or effect["validation_digest"] != validation_digest(snapshot)
        ):
            raise FinancePostingError("posting_evidence_invalid", "Balance evidence contains duplicate or mismatched effects.")
        effect_ids.add(effect_id)
        posting_date = business_date(header["posting_date"])
        if posting_date > cutoff:
            raise FinancePostingError("posting_evidence_invalid", "Balance evidence exceeds the selected business-date cutoff.")
        selected = {key: effect[key] for key in POLICY_FIELDS}
        if any(selected[key] != header[key] for key in POLICY_FIELDS) or (policy is not None and selected != policy):
            raise FinancePostingError("posting_policy_mismatch", "Opening and closing require compatible retained currency policies.")
        policy = selected
        phase = "opening" if posting_date < start else "activity"
        # An overlapping alternate period must not silently contribute activity.
        if phase == "activity" and header["period_id"] != scope["period_id"]:
            raise FinancePostingError("posting_period_ambiguous", "A contributing posting belongs to another overlapping fiscal period.")
        phase_effects[phase].add(effect_id)
        line_count += len(snapshot["lines"])
        if line_count > MAX_BALANCE_LINES:
            raise FinancePostingError("posting_balance_limit", "The bounded balance report exceeds its line limit.")
        for line in snapshot["lines"]:
            account = accounts.setdefault(line["account_id"], {
                "account_id": line["account_id"], "opening": _amounts(0, 0),
                "activity": _amounts(0, 0), "postings": [],
            })
            movement = account[phase]
            account[phase] = _amounts(movement["debit_minor"] + line["debit_minor"], movement["credit_minor"] + line["credit_minor"])
            account["postings"].append({
                "effect_id": effect_id, "entry_id": effect["entry_id"], "period_id": header["period_id"],
                "posting_date": posting_date, "phase": phase, "line_number": line["line_number"],
                "debit_minor": line["debit_minor"], "credit_minor": line["credit_minor"],
            })
    for account in accounts.values():
        account["closing"] = _amounts(
            account["opening"]["debit_minor"] + account["activity"]["debit_minor"],
            account["opening"]["credit_minor"] + account["activity"]["credit_minor"],
        )
    totals = {}
    for phase in ("opening", "activity", "closing"):
        debit = sum(account[phase]["debit_minor"] for account in accounts.values())
        credit = sum(account[phase]["credit_minor"] for account in accounts.values())
        net_debit = sum(account[phase]["debit_balance_minor"] for account in accounts.values())
        net_credit = sum(account[phase]["credit_balance_minor"] for account in accounts.values())
        totals[phase] = {
            "effect_count": len(effect_ids) if phase == "closing" else len(phase_effects[phase]),
            "turnover_totals": {"debit_minor": debit, "credit_minor": credit, "balanced": debit == credit},
            "balance_totals": {"debit_minor": net_debit, "credit_minor": net_credit, "balanced": net_debit == net_credit},
        }
    result = {
        "contract_version": BALANCES_CONTRACT, "balance_scope": "recorded-postings-business-date-as-of",
        **scope, "period_start": start, "period_end": end, "as_of_date": cutoff,
        "currency_policy": policy, "accounts": [accounts[key] for key in sorted(accounts)], "totals": totals,
    }
    return {**result, "report_digest": digest_payload(result)}


def verify_posted_balances(value: Mapping[str, Any]) -> None:
    """Verify closed report arithmetic, evidence affinity and exact digest."""
    try:
        _verify_posted_balances(value)
    except FinancePostingError:
        raise
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
        raise FinancePostingError("posting_evidence_invalid", "Posted balances contain malformed evidence.") from exc


def _verify_posted_balances(value: Mapping[str, Any]) -> None:
    fields = {
        "contract_version", "balance_scope", "workspace_id", "organization_code", "entity_code", "organization_id",
        "legal_entity_id", "period_id", "period_start", "period_end", "as_of_date", "currency_policy", "accounts", "totals", "report_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields or value["contract_version"] != BALANCES_CONTRACT or value["balance_scope"] != "recorded-postings-business-date-as-of":
        raise FinancePostingError("posting_evidence_invalid", "Posted balances require the closed versioned report contract.")
    for field in ("workspace_id", "organization_code", "entity_code", "organization_id", "legal_entity_id", "period_id"):
        _identifier(value[field], field)
    if not isinstance(value["accounts"], list) or len(value["accounts"]) > MAX_BALANCE_LINES or not isinstance(value["totals"], Mapping):
        raise FinancePostingError("posting_evidence_invalid", "Posted balances require bounded accounts and exact totals.")
    start, _, cutoff = balance_window(value["period_start"], value["period_end"], value["as_of_date"])
    if value["report_digest"] != digest_payload({key: item for key, item in value.items() if key != "report_digest"}):
        raise FinancePostingError("posting_evidence_invalid", "Posted balance report digest does not match its retained content.")
    seen_accounts: set[str] = set()
    seen_lines: set[tuple[str, int]] = set()
    effects: dict[str, tuple[str, str, str, str]] = {}
    effect_amounts: dict[str, list[int]] = {}
    phase_effects: dict[str, set[str]] = {"opening": set(), "activity": set()}
    aggregates = {phase: [0, 0, 0, 0] for phase in ("opening", "activity", "closing")}
    for account in value["accounts"]:
        if not isinstance(account, Mapping) or not isinstance(account.get("postings"), list) or not account["postings"] or len(account["postings"]) > MAX_BALANCE_LINES:
            raise FinancePostingError("posting_evidence_invalid", "Posted balance accounts require bounded contributions.")
        if set(account) != {"account_id", "opening", "activity", "closing", "postings"} or account["account_id"] in seen_accounts:
            raise FinancePostingError("posting_evidence_invalid", "Posted balance accounts must be unique and closed.")
        seen_accounts.add(_identifier(account["account_id"], "account_id"))
        expected = {phase: [0, 0] for phase in ("opening", "activity")}
        for line in account["postings"]:
            if set(line) != {"effect_id", "entry_id", "period_id", "posting_date", "phase", "line_number", "debit_minor", "credit_minor"}:
                raise FinancePostingError("posting_evidence_invalid", "Posted balance contributions must be closed.")
            debit, credit, number = line["debit_minor"], line["credit_minor"], line["line_number"]
            if any(type(item) is not int for item in (debit, credit, number)) or number < 1 or min(debit, credit) < 0 or (debit == 0) == (credit == 0):
                raise FinancePostingError("posting_evidence_invalid", "Posted balance contributions require exact positive minor units.")
            posting_date = business_date(line["posting_date"])
            phase = "opening" if posting_date < start else "activity"
            if posting_date > cutoff or line["phase"] != phase or (phase == "activity" and line["period_id"] != value["period_id"]):
                raise FinancePostingError("posting_evidence_invalid", "Posted balance contributions do not match their date window.")
            effect_id = _identifier(line["effect_id"], "effect_id")
            affinity = (_identifier(line["entry_id"], "entry_id"), _identifier(line["period_id"], "period_id"), posting_date, phase)
            if (effect_id, number) in seen_lines or (effect_id in effects and effects[effect_id] != affinity):
                raise FinancePostingError("posting_evidence_invalid", "Posted balance contributions repeat or disagree about their source.")
            effects[effect_id] = affinity
            seen_lines.add((effect_id, number))
            phase_effects[phase].add(effect_id)
            expected[phase][0] += debit
            expected[phase][1] += credit
            amounts = effect_amounts.setdefault(effect_id, [0, 0])
            amounts[0] += debit
            amounts[1] += credit
        expected["closing"] = [expected["opening"][i] + expected["activity"][i] for i in (0, 1)]
        for phase, sums in expected.items():
            retained = account[phase]
            calculated = _amounts(*sums)
            if set(retained) != set(AMOUNT_FIELDS) or any(type(retained[key]) is not int or retained[key] != calculated[key] for key in AMOUNT_FIELDS):
                raise FinancePostingError("posting_evidence_invalid", "Opening, movement or closing differs from its contributing evidence.")
            for index, key in enumerate(("debit_minor", "credit_minor", "debit_balance_minor", "credit_balance_minor")):
                aggregates[phase][index] += calculated[key]
    if len(effects) > MAX_BALANCE_EFFECTS or len(seen_lines) > MAX_BALANCE_LINES or any(debit != credit for debit, credit in effect_amounts.values()):
        raise FinancePostingError("posting_evidence_invalid", "Posted balance contributions exceed limits or contain incomplete effects.")
    if set(value["totals"]) != set(aggregates):
        raise FinancePostingError("posting_evidence_invalid", "Posted balance totals require all three phases.")
    for phase, amounts in aggregates.items():
        expected_totals = {
            "effect_count": len(effects) if phase == "closing" else len(phase_effects[phase]),
            "turnover_totals": {"debit_minor": amounts[0], "credit_minor": amounts[1], "balanced": amounts[0] == amounts[1]},
            "balance_totals": {"debit_minor": amounts[2], "credit_minor": amounts[3], "balanced": amounts[2] == amounts[3]},
        }
        retained_totals = value["totals"][phase]
        if type(retained_totals.get("effect_count")) is not int or retained_totals != expected_totals:
            raise FinancePostingError("posting_evidence_invalid", "Posted balance totals do not match their contributing evidence.")
        for aggregate in ("turnover_totals", "balance_totals"):
            if type(retained_totals[aggregate]["balanced"]) is not bool or any(type(retained_totals[aggregate][key]) is not int for key in ("debit_minor", "credit_minor")):
                raise FinancePostingError("posting_evidence_invalid", "Posted balance totals require exact integers and boolean status.")
    policy = value["currency_policy"]
    if (not effects and policy is not None) or (effects and (not isinstance(policy, Mapping) or set(policy) != set(POLICY_FIELDS))):
        raise FinancePostingError("posting_policy_unverified", "Posted balances require retained policy or an explicitly empty report.")
    if policy is not None:
        currency, precision, rounding, version, digest = (policy[key] for key in POLICY_FIELDS)
        if (
            not isinstance(currency, str) or len(currency) != 3 or any(letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for letter in currency)
            or type(precision) is not int or not 0 <= precision <= 8 or rounding != "ROUND_HALF_UP"
            or text(version, "currency_registry_version") != version
            or not isinstance(digest, str) or len(digest) != 64 or any(letter not in "0123456789abcdef" for letter in digest)
        ):
            raise FinancePostingError("posting_policy_unverified", "Posted balances contain an invalid retained monetary policy.")
