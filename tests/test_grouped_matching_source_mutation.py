from reconforge.benchmark.grouped_matching_source_mutation import (
    run_source_mutation_campaign,
    verify_source_mutation_campaign,
)


def test_targeted_grouped_matching_source_mutations_are_killed() -> None:
    result = run_source_mutation_campaign()
    verify_source_mutation_campaign(result)
    assert result.mutants == result.killed == 3
    assert result.survivors == ()
