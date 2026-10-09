"""Independent exact entitlements and acquisition/disposal accounting oracles."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.fixed_assets import accounting_lines, cumulative_depreciation, eligible_months


@pytest.mark.parametrize("cost,salvage,life", [(10000, 1000, 3), (101, 0, 7), (9007199254740993, 999, 1200)])
def test_cumulative_entitlement_matches_independent_decimal_oracle(cost: int, salvage: int, life: int) -> None:
    previous = 0
    with localcontext() as context:
        context.prec = 60
        for month in range(life + 1):
            oracle = int((Decimal(cost - salvage) * Decimal(month) / Decimal(life)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            actual = cumulative_depreciation(cost, salvage, life, month)
            assert actual == oracle
            assert actual >= previous
            previous = actual
    assert previous == cost - salvage


@pytest.mark.parametrize("cost,salvage,life,months", [(100, 100, 3, 0), (100, -1, 3, 0), (True, 0, 3, 0), (100, 0, 0, 0), (100, 0, 3, 4), (100, 0, 3, True)])
def test_invalid_exact_bases_are_refused(cost: int, salvage: int, life: int, months: int) -> None:
    with pytest.raises(FinancePostingError):
        cumulative_depreciation(cost, salvage, life, months)


@pytest.mark.parametrize("proceeds", [0, 4000, 7000, 9000])
def test_disposal_equation_releases_historical_cost_and_accumulation(proceeds: int) -> None:
    asset = {"cost_minor": 10000, "salvage_minor": 1000, **{key + "_account_code": key.upper()
             for key in ("asset", "accumulated", "expense", "cash", "gain", "loss")}}
    lines = accounting_lines(asset, "dispose", accumulated=3000, proceeds=proceeds)
    by_account = {row["account_code"]: int(row["debit_minor"]) - int(row["credit_minor"]) for row in lines}
    assert sum(by_account.values()) == 0
    assert by_account["ASSET"] == -10000
    assert by_account["ACCUMULATED"] == 3000
    assert by_account.get("CASH", 0) == proceeds
    assert by_account.get("LOSS", 0) == max(7000 - proceeds, 0)
    assert by_account.get("GAIN", 0) == -max(proceeds - 7000, 0)


def test_completed_service_months_and_catchup_are_exact() -> None:
    assert eligible_months("2026-01-15", "2026-01", "2026-02-01", 36) == 1
    assert eligible_months("2026-01-15", "2026-09", "2026-10-01", 36) == 9
    assert eligible_months("2026-01-15", "2029-01", "2029-02-01", 36) == 36
    for month, posted in (("2026-01", "2026-01-31"), ("2025-12", "2026-02-01"), ("2026-13", "2027-02-01")):
        with pytest.raises(FinancePostingError):
            eligible_months("2026-01-15", month, posted, 36)
