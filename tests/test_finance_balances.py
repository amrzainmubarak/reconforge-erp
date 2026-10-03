"""Independent financial answers for exact business-date opening and closing."""

from copy import deepcopy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reconforge.api.finance_posting_contract import project_posted_balances
from reconforge.domain.finance_balances import build_posted_balances, collect_balance_effects, verify_posted_balances
from reconforge.domain.finance_posting import FinancePostingError, digest_payload, validation_digest
from tests.test_finance_posting_domain import snapshot


def effect(identifier, posting_date, period, *, amount=100, inverse=False, cash="cash"):
    value = snapshot()
    value["entry"].update(id=identifier, entry_number=identifier, period_id=period, posting_date=posting_date)
    value["lines"][0].update(account_id=cash, debit_minor=0 if inverse else amount, credit_minor=amount if inverse else 0)
    value["lines"][1].update(debit_minor=amount if inverse else 0, credit_minor=0 if inverse else amount)
    return {
        "id": identifier, "entry_id": identifier, "snapshot": value, "validation_digest": validation_digest(value),
        **{key: value["entry"][key] for key in (
            "workspace_id", "organization_id", "legal_entity_id", "currency_code", "currency_precision",
            "currency_rounding_policy", "currency_registry_version", "currency_registry_digest",
        )},
    }


def report(effects):
    return build_posted_balances(
        workspace_id="w", organization_code="SYN", entity_code="EG01", organization_id="o", legal_entity_id="le",
        period_id="oct", period_start="2026-10-01", period_end="2026-10-31", as_of_date="2026-10-20", effects=effects,
    )


def test_opening_cross_period_reversal_and_later_current_movement_are_distinct():
    result = report([effect("original", "2026-09-01", "sep", amount=1000), effect("reverse", "2026-10-05", "oct", amount=1000, inverse=True), effect("new", "2026-10-20", "oct", amount=300)])
    cash = next(row for row in result["accounts"] if row["account_id"] == "cash")
    assert (cash["opening"]["balance_minor"], cash["activity"]["balance_minor"], cash["closing"]["balance_minor"]) == (1000, -700, 300)
    assert result["totals"]["opening"]["balance_totals"]["debit_minor"] == 1000
    assert result["totals"]["activity"]["balance_totals"]["debit_minor"] == 700
    assert result["totals"]["closing"]["balance_totals"]["debit_minor"] == 300
    assert result["totals"]["closing"]["turnover_totals"]["debit_minor"] == 2300
    verify_posted_balances(result)


@given(st.integers(min_value=1, max_value=9_223_372_036_854_775_807))
def test_full_reversal_zero_closing_and_permutations_preserve_exact_digest(amount):
    original, inverse = effect("original", "2026-09-30", "sep", amount=amount), effect("reverse", "2026-10-01", "oct", amount=amount, inverse=True)
    result = report([original, inverse])
    assert report([inverse, original]) == result
    assert result["totals"]["closing"]["balance_totals"] == {"debit_minor": 0, "credit_minor": 0, "balanced": True}
    assert result["totals"]["closing"]["turnover_totals"]["debit_minor"] == amount * 2
    verify_posted_balances(result)


def test_api_large_minor_units_and_empty_report_do_not_infer_policy():
    result = report([effect("large", "2026-10-02", "oct", amount=9007199254740993)])
    projected = project_posted_balances(result)
    assert projected["totals"]["closing"]["balance_totals"]["debit_minor"] == "9007199254740993"
    assert "9007199254740993" in projected["report_json"]
    empty = report([])
    assert empty["currency_policy"] is None and empty["totals"]["closing"]["effect_count"] == 0
    verify_posted_balances(empty)


@pytest.mark.parametrize("change", ["duplicate", "other_period", "future", "policy", "scope", "header"])
def test_mismatched_contributing_evidence_fails_closed(change):
    first = effect("first", "2026-09-30", "sep")
    second = effect("second", "2026-10-05", "oct")
    if change == "duplicate":
        second = first
    elif change in {"other_period", "future", "header"}:
        key, value = {"other_period": ("period_id", "overlap"), "future": ("posting_date", "2026-10-21"), "header": ("description", "changed")}[change]
        second["snapshot"]["entry"][key] = value
        if change != "header":
            second["validation_digest"] = validation_digest(second["snapshot"])
    elif change == "policy":
        second["snapshot"]["entry"]["currency_registry_version"] = "v2"
        second["currency_registry_version"] = "v2"
        second["validation_digest"] = validation_digest(second["snapshot"])
    else:
        second["organization_id"] = "other"
    with pytest.raises(FinancePostingError):
        report([first, second])


@pytest.mark.parametrize("change", ["closing", "phase", "duplicate_line", "totals_bool", "total", "digest", "affinity", "extra"])
def test_projection_rejects_arithmetic_and_lineage_corruption_even_with_a_new_digest(change):
    result = deepcopy(report([effect("original", "2026-09-30", "sep")]))
    row = result["accounts"][0]
    if change == "closing":
        row["closing"]["balance_minor"] += 1
    elif change == "phase":
        row["postings"][0]["phase"] = "activity"
    elif change == "duplicate_line":
        row["postings"].append(deepcopy(row["postings"][0]))
    elif change == "totals_bool":
        result["totals"]["closing"]["effect_count"] = True
    elif change == "total":
        result["totals"]["closing"]["balance_totals"]["debit_minor"] += 1
    elif change == "affinity":
        row["postings"][0]["entry_id"] = "borrowed"
    elif change == "extra":
        result["private_source"] = "do not expose"
    if change != "digest":
        result["report_digest"] = digest_payload({key: value for key, value in result.items() if key != "report_digest"})
    else:
        result["report_digest"] = "0" * 64
    with pytest.raises(FinancePostingError):
        project_posted_balances(result)


@pytest.mark.parametrize("change", ["bool_precision", "rounding", "digest", "currency", "version", "workspace", "entity", "accounts", "postings", "totals"])
def test_projection_refuses_malformed_policy_scope_and_containers(change):
    result = report([effect("first", "2026-10-02", "oct")])
    if change in {"bool_precision", "rounding", "digest", "currency", "version"}:
        field, value = {
            "bool_precision": ("currency_precision", True), "rounding": ("currency_rounding_policy", "ROUND_DOWN"),
            "digest": ("currency_registry_digest", "invalid"), "currency": ("currency_code", "usd"),
            "version": ("currency_registry_version", ""),
        }[change]
        result["currency_policy"][field] = value
    elif change == "workspace":
        result["workspace_id"] = None
    elif change == "entity":
        result["entity_code"] = ""
    elif change == "postings":
        result["accounts"][0]["postings"] = None
    else:
        result[change] = None
    result["report_digest"] = digest_payload({key: value for key, value in result.items() if key != "report_digest"})
    with pytest.raises(FinancePostingError):
        project_posted_balances(result)


def test_incremental_effect_collection_stops_loading_on_line_or_byte_budget(monkeypatch):
    import reconforge.domain.finance_balances as balances

    calls = []
    def supplied():
        for index in range(30):
            calls.append(index)
            yield effect(str(index), "2026-10-02", "oct")

    monkeypatch.setattr(balances, "MAX_BALANCE_LINES", 4)
    with pytest.raises(FinancePostingError, match="evidence budget"):
        collect_balance_effects(supplied())
    assert calls == [0, 1, 2]
    calls.clear()
    monkeypatch.setattr(balances, "MAX_BALANCE_LINES", 10000)
    monkeypatch.setattr(balances, "MAX_SNAPSHOT_BYTES", 1)
    with pytest.raises(FinancePostingError, match="evidence budget"):
        collect_balance_effects(supplied())
    assert calls == [0]


@pytest.mark.parametrize("field", ["account_id", "effect_id", "entry_id", "period_id", "empty_account"])
def test_projection_refuses_noncanonical_nested_identity_and_empty_accounts(field):
    result = report([effect("first", "2026-09-02", "sep")])
    if field == "account_id":
        result["accounts"][0][field] += " "
    elif field == "empty_account":
        empty = deepcopy(result["accounts"][0])
        empty["account_id"] = "noncontributing"
        empty["postings"] = []
        for phase in ("opening", "activity", "closing"):
            empty[phase] = {key: 0 for key in empty[phase]}
        result["accounts"].append(empty)
    else:
        for account in result["accounts"]:
            account["postings"][0][field] += " "
    result["report_digest"] = digest_payload({key: value for key, value in result.items() if key != "report_digest"})
    with pytest.raises(FinancePostingError):
        project_posted_balances(result)
