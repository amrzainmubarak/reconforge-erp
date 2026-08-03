from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.benchmark.postgres_outbox_scale import PostgresOutboxScaleProfile, default_profile


def test_postgres_outbox_scale_profile_declares_bounded_delivery_shape() -> None:
    profile = default_profile()
    assert profile.profile_id == "postgres-outbox-load/64-events-v1"
    assert profile.workers == 4
    assert profile.events == 64
    assert profile.batch_size == 8


def test_postgres_outbox_scale_profile_is_packaged_and_documented() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "MANIFEST.in").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/postgres_outbox_scale.py" in manifest
    assert "include tests/test_postgres_outbox_scale.py" in manifest
    assert (root / "docs/adr/0298-postgres-outbox-bounded-multi-worker-profile.md").is_file()


@pytest.mark.parametrize("kwargs", [{"workers": 0}, {"events": 0}, {"batch_size": 0}, {"lease_seconds": 0}])
def test_postgres_outbox_scale_profile_rejects_invalid_shape(kwargs: dict[str, int]) -> None:
    values = {"profile_id": "invalid", "workers": 2, "events": 2, "batch_size": 1, "lease_seconds": 1}
    values.update(kwargs)
    with pytest.raises(ValueError):
        PostgresOutboxScaleProfile(**values)
