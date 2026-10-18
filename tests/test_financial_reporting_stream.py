"""Independent exact oracle for large streamed reports and retained scope."""

from copy import deepcopy

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.financial_reporting_stream import StreamingFinancialReport
from tests.test_finance_balances import effect
from tests.test_financial_reporting import classification


def fold() -> StreamingFinancialReport:
    mapping = classification()
    mapping["accounts"][1]["account_id"] = effect("E", "2026-10-02", "oct")["snapshot"]["lines"][1]["account_id"]
    return StreamingFinancialReport(mapping, {
        "id": "FRS1-test", "workspace_id": "w", "organization_id": "o", "legal_entity_id": "le",
        "period_id": "oct", "organization_code": "SYN", "entity_code": "EG01",
        "period_start": "2026-10-01", "period_end": "2026-10-31", "as_of_date": "2026-10-20",
        "source_snapshot": "1:2:", "captured_at": "2026-10-21T00:00:00Z",
    })


def test_stream_exceeds_old_evidence_caps_with_constant_account_memory_and_independent_exact_oracle() -> None:
    stream = fold()
    expected = 0
    for ordinal in range(12_001):
        value = 9_007_199_254_740_993 + ordinal
        stream.consume(effect(f"E{ordinal:08d}", "2026-10-02", "oct", amount=value))
        expected += value
        assert len(stream.accounts) == 2
    result = stream.finish()
    assert result["effect_count"] == 12_001
    assert result["line_count"] == 24_002
    assert result["balance_sheet"]["assets_minor"] == expected
    assert result["balance_sheet"]["equity_minor"] == expected
    assert result["cash_movements"]["inflow_minor"] == expected
    assert result["trial_balance"]["totals"]["closing"]["turnover_totals"]["debit_minor"] == expected


@pytest.mark.parametrize("change", ["unordered", "duplicate", "unmapped", "scope", "float", "digest", "period", "policy"])
def test_stream_refuses_invalid_native_affinity_and_exactness(change: str) -> None:
    stream = fold()
    first = effect("A", "2026-10-02", "oct")
    stream.consume(first)
    value = deepcopy(effect("B", "2026-10-02", "oct"))
    if change == "unordered":
        value["id"] = "0"
    elif change == "duplicate":
        value = first
    elif change == "unmapped":
        value["snapshot"]["lines"][0]["account_id"] = "missing"
    elif change == "scope":
        value["legal_entity_id"] = "other"
    elif change == "float":
        value["snapshot"]["lines"][0]["debit_minor"] = 100.0
    elif change == "digest":
        value["validation_digest"] = "f" * 64
    elif change == "period":
        value["snapshot"]["entry"]["period_id"] = "overlap"
    else:
        value["currency_registry_digest"] = "f" * 64
    with pytest.raises(FinancePostingError):
        stream.consume(value)


def test_empty_and_reversal_summary_do_not_infer_missing_currency() -> None:
    assert fold().finish()["currency_policy"] is None
    stream = fold()
    stream.consume(effect("A", "2026-09-30", "sep", amount=901))
    stream.consume(effect("B", "2026-10-02", "oct", amount=901, inverse=True))
    value = stream.finish()
    assert value["balance_sheet"]["assets_minor"] == 0
    assert value["cash_movements"]["opening_minor"] == value["cash_movements"]["outflow_minor"] == 901
