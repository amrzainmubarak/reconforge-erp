"""Verification batching rejects unsafe requests before opening database reads."""

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository


def test_empty_verification_still_requires_read_authority() -> None:
    repository = PostgresFinancePostingRepository(object(), "batch_scope")
    actor = PostingActor("no-read", "no-read", frozenset())
    with pytest.raises(FinancePostingError):
        repository.get_effects_batch([], actor=actor)
    with pytest.raises(FinancePostingError):
        list(repository.iter_verified_posting_effects(effect_ids=[], actor=actor))


@pytest.mark.parametrize("identifiers", [["same", "same"], ["effect"] * 201, "effect", [""]])
def test_unsafe_batch_refused_before_database_access(identifiers: list[str] | str) -> None:
    repository = PostgresFinancePostingRepository(object(), "batch_scope")
    actor = PostingActor("reader", "reader", frozenset({"finance_core.read"}))
    with pytest.raises(FinancePostingError):
        repository.get_effects_batch(identifiers, actor=actor)  # type: ignore[arg-type]


@pytest.mark.parametrize("size", [0, 201, True, 1.5])
def test_unbounded_or_noninteger_stream_refused(size: int) -> None:
    repository = PostgresFinancePostingRepository(object(), "batch_scope")
    actor = PostingActor("reader", "reader", frozenset({"finance_core.read"}))
    with pytest.raises(FinancePostingError, match="batch size"):
        list(repository.iter_verified_posting_effects(effect_ids=[], actor=actor, batch_size=size))
