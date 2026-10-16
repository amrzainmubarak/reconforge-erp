"""Repository contention translation occurs after its atomic owner boundary.

These pure boundary tests do not claim PostgreSQL locking or financial proof.
The native monetary security cases exercise real competing transactions.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_monetary_customer_partial_returns import (
    PostgresMonetaryCustomerPartialReturnsRepository,
)


class AtomicOwner:
    def __init__(self) -> None:
        self.effects: list[str] = []
        self.attempts = 0
        self.exiting_errors: list[Exception] = []

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.attempts += 1
        before = list(self.effects)
        try:
            yield
        except Exception as exc:
            self.exiting_errors.append(exc)
            self.effects[:] = before
            raise


def repository(monkeypatch: pytest.MonkeyPatch) -> tuple[PostgresMonetaryCustomerPartialReturnsRepository, AtomicOwner]:
    value = object.__new__(PostgresMonetaryCustomerPartialReturnsRepository)
    owner = AtomicOwner()
    monkeypatch.setattr(value, "owner", owner, raising=False)
    return value, owner


def test_lock_timeout_becomes_retryable_only_after_rollback_without_automatic_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    value, owner = repository(monkeypatch)
    failure = psycopg.errors.LockNotAvailable("Owned command lock timeout")
    with pytest.raises(FinancePostingError) as refused, value._transaction():
        owner.effects.append("uncommitted effect")
        raise failure

    assert refused.value.code == "monetary_return_retryable_conflict"
    assert refused.value.__cause__ is failure and failure.sqlstate == "55P03"
    assert owner.exiting_errors == [failure]
    assert owner.effects == [] and owner.attempts == 1

    # The caller explicitly starts another atomic command after the refusal.
    with value._transaction():
        owner.effects.append("explicit retry effect")
    assert owner.effects == ["explicit retry effect"] and owner.attempts == 2


@pytest.mark.parametrize("failure", [
    psycopg.errors.QueryCanceled("Statement deadline"),
    psycopg.errors.InsufficientPrivilege("Current authority withdrawn"),
    psycopg.errors.CheckViolation("Native owner refused"),
    psycopg.errors.DeadlockDetected("Distinct transaction failure"),
    FinancePostingError("monetary_return_state_conflict", "Pending owner differs"),
    RuntimeError("Owned injected interruption"),
])
def test_non_lock_failures_keep_their_exact_identity_after_rollback(
    monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    value, owner = repository(monkeypatch)
    with pytest.raises(type(failure)) as refused, value._transaction():
        owner.effects.append("uncommitted effect")
        raise failure
    assert refused.value is failure
    assert owner.exiting_errors == [failure]
    assert owner.effects == [] and owner.attempts == 1
