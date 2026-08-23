from __future__ import annotations

from pathlib import Path

from reconforge.benchmark.matching_strategy_replay import (
    MatchingStrategyReplayProfile,
    run_matching_strategy_replay_profile,
)
from reconforge.db import connect, run_migrations
from reconforge.platform.matching import MatchingService


def test_registry_replay_profile_covers_every_published_strategy(tmp_path: Path) -> None:
    database = tmp_path / "matching-strategy-replay.db"
    run_migrations(database)
    connection = connect(database, require_exists=True)
    try:
        profile = run_matching_strategy_replay_profile(MatchingService(connection))
    finally:
        connection.close()

    assert profile.profile_id == "matching-strategy-registry-replay-v1"
    assert profile.strategy_count == 7
    assert len(profile.profile_digest) == 64
    assert all(item.permutation_invariant for item in profile.observations)
    assert all(item.envelope_replay_verified for item in profile.observations)
    assert [item.strategy_id for item in profile.observations] == sorted(item.strategy_id for item in profile.observations)
    assert profile.to_payload()["synthetic_only"] is True


def test_registry_replay_profile_is_repeatable(tmp_path: Path) -> None:
    profiles: list[MatchingStrategyReplayProfile] = []
    for index in range(2):
        database = tmp_path / f"matching-strategy-replay-{index}.db"
        run_migrations(database)
        connection = connect(database, require_exists=True)
        try:
            profiles.append(run_matching_strategy_replay_profile(MatchingService(connection)))
        finally:
            connection.close()
    assert profiles[0].to_payload() == profiles[1].to_payload()
