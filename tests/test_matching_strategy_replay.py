from __future__ import annotations

import json
from pathlib import Path

from reconforge.benchmark.matching_strategy_replay import (
    MatchingStrategyReplayProfile,
    run_matching_strategy_replay_profile,
    run_postgres_domain_diverse_worker_parity_profile,
    run_postgres_worker_matching_parity_profile,
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


def test_postgres_worker_projection_matches_direct_strategy_digests() -> None:
    profile = run_postgres_worker_matching_parity_profile()
    assert profile.profile_id == "postgres-worker-strategy-parity-v1"
    assert profile.parity_count == 8
    assert len(profile.profile_digest) == 64
    assert all(item.parity_verified for item in profile.observations)
    assert all(item.permutation_invariant for item in profile.observations)


def test_postgres_domain_diverse_worker_projection_matches_direct_strategy_digests() -> None:
    profile = run_postgres_domain_diverse_worker_parity_profile()
    assert profile.profile_id == "postgres-worker-domain-diverse-parity-v1"
    assert profile.parity_count == 6
    assert [item.mode for item in profile.observations] == [
        "domain-one-to-many",
        "domain-many-to-one",
        "domain-many-to-many",
        "domain-portfolio-net",
        "domain-fx-many-to-many",
        "domain-portfolio-partial",
    ]
    assert len(profile.profile_digest) == 64
    assert all(item.parity_verified for item in profile.observations)
    assert all(item.permutation_invariant for item in profile.observations)


def test_postgres_domain_diverse_worker_parity_is_repeatable() -> None:
    assert (
        run_postgres_domain_diverse_worker_parity_profile().to_payload()
        == run_postgres_domain_diverse_worker_parity_profile().to_payload()
    )


def test_postgres_domain_diverse_worker_parity_artifact_is_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include docs/execution/benchmarks/postgres-worker-domain-diverse-parity-v1.json" in manifest
    assert "include docs/adr/0620-postgres-worker-domain-diverse-parity.md" in manifest


def test_postgres_domain_diverse_worker_parity_artifact_matches_profile() -> None:
    artifact = json.loads(
        Path("docs/execution/benchmarks/postgres-worker-domain-diverse-parity-v1.json").read_text(encoding="utf-8")
    )
    assert artifact == run_postgres_domain_diverse_worker_parity_profile().to_payload()
