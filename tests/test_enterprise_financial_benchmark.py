"""Independent financial generator oracle and invalid resource-profile refusal."""
import pytest

from reconforge.benchmark.enterprise_financial import amount_minor, expected_totals, percentile
from reconforge.benchmark.resource_sampling import ResourceSampler


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


def test_accepted_native_profile_retains_its_independent_integer_oracle() -> None:
    assert expected_totals("enterprise-native-v1", 1000) == {
        "debit_minor": "493671004", "credit_minor": "493671004",
        "cash_minor": "493671004", "equity_minor": "493671004",
    }
    assert percentile([4, 1, 2, 3], .5) == 2
    assert percentile([4, 1, 2, 3], .95) == 4


def test_resource_sampling_preserves_observations_and_redacts_error_text() -> None:
    import threading

    observed = threading.Event()
    def callback() -> dict[str, int]:
        observed.set()
        return {"counter": 42}

    sampler = ResourceSampler(callback)
    sampler.start()
    assert observed.wait(timeout=5)
    report = sampler.stop()
    assert report["status"] == "complete"
    assert report["raw_samples"][0]["counter"] == 42
    assert report["raw_samples"][0]["client_memory"]["process_lifetime_peak_rss_bytes"] > 0
    assert report["thread_still_running"] is False
    with pytest.raises(RuntimeError):
        sampler.start()

    failed = threading.Event()
    def failing_callback() -> dict[str, int]:
        failed.set()
        raise ValueError("postgresql://secret:password@private-host/db")

    errors = ResourceSampler(failing_callback)
    errors.start()
    assert failed.wait(timeout=5)
    result = errors.stop()
    assert result["status"] == "incomplete"
    assert result["errors"][0]["exception_type"] == "ValueError"
    assert "password" not in str(result)
