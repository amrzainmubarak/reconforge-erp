"""Independent financial generator oracle and invalid resource-profile refusal."""
import pytest

from reconforge.benchmark.enterprise_financial import amount_minor, expected_totals


def test_deterministic_financial_profile_has_exact_independent_totals() -> None:
    amounts = [amount_minor("enterprise-v1", index) for index in range(100)]
    assert all(type(value) is int and 0 < value <= 1000000 for value in amounts)
    assert amounts == [amount_minor("enterprise-v1", index) for index in range(100)]
    assert amounts != [amount_minor("enterprise-v2", index) for index in range(100)]
    assert expected_totals("enterprise-v1", 100) == {key: str(sum(amounts)) for key in
        ("debit_minor", "credit_minor", "cash_minor", "equity_minor")}
    assert sum(amounts[:50]) + sum(amounts[50:]) == sum(amounts)


@pytest.mark.parametrize("count", [0, -1, True, 1.5, 1000001])
def test_invalid_financial_profile_does_not_start_work(count: int) -> None:
    with pytest.raises(ValueError):
        expected_totals("enterprise-v1", count)
