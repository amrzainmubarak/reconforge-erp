"""Actual native posting evidence is unchanged by batched reads."""

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from tests.test_postgres_finance_posting import (
    CHECKER,
    SCOPE,
    posting_database,
    reviewed,
)
from tests.test_postgres_finance_scope import finance_database, isolated_postgres_migration_dsn

__all__ = ["posting_database", "finance_database", "isolated_postgres_migration_dsn"]


def test_live_batched_evidence_preserves_order_scope_and_original_content(posting_database: dict) -> None:
    db = posting_database
    effects = []
    for index in range(3):
        entry_id, digest = reviewed(db, f"BATCH-POST-{index}")
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            posting = PostgresFinancePostingRepository(connection, "finance_scope")
            effects.append(posting.post(
                entry_id, command_id=f"batch-post-{index}", expected_validation_digest=digest,
                reason="Independent exact synthetic batch", actor=CHECKER,
            ))
    ids = [effect["id"] for effect in reversed(effects)]
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        original = [posting.get_effect(identifier, actor=CHECKER) for identifier in ids]
        assert posting.get_effects_batch(ids, actor=CHECKER) == original
        assert list(posting.iter_verified_posting_effects(effect_ids=iter(ids), actor=CHECKER, batch_size=2)) == original
        with pytest.raises(FinancePostingError, match="absent or outside"):
            posting.get_effects_batch([*ids, "missing-effect"], actor=CHECKER)
