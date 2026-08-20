from reconforge.benchmark.grouped_matching_mutation import (
    run_grouped_matching_mutation_campaign,
    verify_mutation_campaign,
)


def test_grouped_matching_mutation_campaign_kills_critical_mutants() -> None:
    result = run_grouped_matching_mutation_campaign()
    verify_mutation_campaign(result)
    assert result.killed == 3
    assert result.kill_ratio == 1
