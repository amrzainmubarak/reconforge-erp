"""Independent financial generator oracle and invalid resource-profile refusal."""
from typing import Any

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


@pytest.mark.parametrize("profile_cpu", [False, True])
def test_posting_phase_profile_preserves_failure_boundaries_without_collecting_secrets(profile_cpu: bool) -> None:
    from contextlib import contextmanager

    from reconforge.benchmark.enterprise_posting_profile import PostingProfile

    class Connection:
        def execute(self, statement: str, parameters: tuple[str, ...]) -> str:
            if statement == "FAIL":
                raise ValueError("secret-password private-dsn")
            return parameters[0]

    class Runtime:
        @contextmanager
        def actor(self, username: str):
            yield Connection(), "secret-auth", "secret-actor"
            raise RuntimeError("secret-commit-error")

    profile = PostingProfile(profile_cpu=profile_cpu)
    with pytest.raises(RuntimeError, match="secret-commit"), profile.actor(Runtime(), "secret-user", 3, "post") as (connection, _, _actor):
        assert connection.execute("SELECT private-column", ("secret-parameter",)) == "secret-parameter"
        with pytest.raises(ValueError):
            connection.execute("FAIL", ("secret-parameter",))
    report = profile.report()
    assert len(report["raw_phase_observations"]) == 3
    assert report["phase_totals"]["post.transaction_exit"]["failures"] == 1
    assert sum(row["calls"] for row in report["statement_templates"]) == 2
    assert sum(row["failures"] for row in report["statement_templates"]) == 1
    assert "secret-" not in str(report) and "private-" not in str(report)
    assert report["function_profile"]["enabled"] is profile_cpu
    assert bool(report["function_profile"]["functions"]) is profile_cpu
    assert all(row["thread_cpu_seconds"] >= 0 for row in report["raw_phase_observations"])


def test_function_discovery_ceiling_preserves_business_work_without_profiling_later_cycles() -> None:
    from contextlib import contextmanager

    from reconforge.benchmark.enterprise_posting_profile import PostingProfile

    class Runtime:
        @contextmanager
        def actor(self, username: str):
            yield object(), object(), object()

    profile = PostingProfile(profile_cpu=True)
    with profile.actor(Runtime(), "human", 32, "post"):
        assert sum(range(1000)) == 499500
    report = profile.report()
    assert len(report["raw_phase_observations"]) == 3
    assert report["function_profile"]["functions"] == []


def test_snapshot_comparison_keeps_failed_raw_samples_without_false_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    import reconforge.benchmark.enterprise_snapshot as benchmark
    from reconforge.domain.finance_posting import HEADER_FIELDS, make_entry_snapshot, validation_digest

    entry = {key: "fixture" for key in HEADER_FIELDS}
    entry.update(currency_precision=2, currency_rounding_policy="ROUND_HALF_UP", currency_registry_digest="a" * 64,
                 posting_date="2026-10-10", reverses_posting_id=None)
    snapshot = make_entry_snapshot(entry, [
        {"line_number": 1, "account_id": "cash", "description": "", "debit_minor": 37, "credit_minor": 0, "dimensions": {}},
        {"line_number": 2, "account_id": "equity", "description": "", "debit_minor": 0, "credit_minor": 37, "dimensions": {"D": "V"}},
    ])
    calls = 0

    def optimized(*_args: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("secret-private-dsn")
        return snapshot

    monkeypatch.setattr(benchmark, "legacy_snapshot", lambda *_args: snapshot)
    monkeypatch.setattr(benchmark, "posting_snapshot", optimized)
    report: dict[str, Any] = {}
    with pytest.raises(RuntimeError, match="secret"):
        benchmark.measure_snapshot_reads(object(), "tenant", {}, expected_line_count=2, expected_total_minor=37,
            expected_validation_digest=validation_digest(snapshot), repetitions=3, evidence_sink=report)
    assert report["status"] == "failed"
    assert report["samples"]["per_line_baseline"][0]["status"] == "complete"
    assert report["samples"]["per_line_baseline"][0]["debit_minor"] == "37"
    assert report["samples"]["joined_snapshot"][0]["failure"] == {"exception_type": "RuntimeError"}
    assert report["samples"]["joined_snapshot"][0]["seconds"] >= 0
    assert "measured_speedup" not in report and "secret" not in str(report)


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


@pytest.mark.parametrize("fail_in", ["second_baseline_request", "first_batch_request"])
def test_failed_verified_reads_retain_completed_samples_and_independent_money_oracle(monkeypatch: pytest.MonkeyPatch, fail_in: str) -> None:
    import hashlib

    import reconforge.benchmark.enterprise_financial as benchmark
    from reconforge.domain.finance_posting import canonical_json

    # Independent fixed arithmetic oracle, unrelated to production posting/pricing.
    amounts = {"ONE": 37, "TWO": 45}
    effects = {identifier: {"id": identifier, "snapshot": {"lines": [
        {"account_id": "CASH", "debit_minor": value, "credit_minor": 0},
        {"account_id": "EQUITY", "debit_minor": 0, "credit_minor": value},
    ]}} for identifier, value in amounts.items()}

    class InstrumentedReads:
        def __init__(self, connection: Any, tenant: str) -> None:
            self.single_calls = self.batch_calls = 0

        def get_effect(self, identifier: str, *, actor: Any) -> dict[str, Any]:
            self.single_calls += 1
            if fail_in == "second_baseline_request" and self.single_calls == 3:
                raise RuntimeError("postgresql://private:password@localhost/db")
            return effects[identifier]

        def get_effects_batch(self, identifiers: list[str], *, actor: Any) -> list[dict[str, Any]]:
            self.batch_calls += 1
            if fail_in == "first_batch_request" and self.batch_calls == 2:
                raise RuntimeError("postgresql://private:password@localhost/db")
            return [effects[identifier] for identifier in identifiers]

    monkeypatch.setattr(benchmark, "PostgresFinancePostingRepository", InstrumentedReads)
    profile: dict[str, Any] = {"count": 2, "expected": {"debit_minor": "82", "credit_minor": "82"}}
    with pytest.raises(RuntimeError, match="private"):
        benchmark.measure_verified_reads(object(), "tenant", ["ONE", "TWO"], object(), repetitions=2, evidence_sink=profile)
    assert profile["status"] == "failed" and profile["failure"] == {"exception_type": "RuntimeError"}
    assert "password" not in str(profile) and "private" not in str(profile)
    assert profile["count"] == 2 and profile["expected"] == {"debit_minor": "82", "credit_minor": "82"}
    baseline = profile["samples"]["per_effect_baseline"][0]
    digest = hashlib.sha256()
    digest.update(canonical_json(effects["ONE"]).encode())
    if fail_in == "second_baseline_request":
        assert baseline["status"] == "failed" and baseline["effects"] == 1
        assert baseline["debit_minor"] == baseline["credit_minor"] == "37"
        assert len(baseline["raw_request_latency_seconds"]) == 1
        assert baseline["failed_request"]["page_index"] == 1
        assert baseline["effects_digest"] == digest.hexdigest()
        assert profile["samples"]["bounded_batch"] == []
    else:
        digest.update(canonical_json(effects["TWO"]).encode())
        assert baseline["status"] == "complete" and baseline["effects"] == 2
        assert baseline["debit_minor"] == baseline["credit_minor"] == "82"
        assert len(baseline["raw_request_latency_seconds"]) == 2
        assert baseline["effects_digest"] == digest.hexdigest()
        batch = profile["samples"]["bounded_batch"][0]
        assert batch["status"] == "failed" and batch["effects"] == 0
        assert batch["debit_minor"] == batch["credit_minor"] == "0"
        assert batch["raw_request_latency_seconds"] == [] and batch["request_latency_seconds"] is None
    assert "measured_speedup" not in profile and "median_seconds_optimized" not in profile
