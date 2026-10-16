"""Reserved monetary corrections cannot post or reverse through generic GL calls."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure import postgres_finance_posting as posting
from reconforge.infrastructure import source_participant_admission as admission

KIND: admission.ParticipantKind = "customer-partial-return-monetary"
MODULE = "reconforge.infrastructure.postgres_monetary_customer_partial_returns"
PREFIXES = ("CR3-", "CRF3-", "CR3R-", "CRF3R-")
ACTOR = PostingActor("human", "human", frozenset({"finance_core.post", "finance_core.manage", "finance_core.reverse"}), step_up_active=True)


class _DenyingOwner:
    def __init__(self) -> None:
        self.admissions: list[tuple[object, ...]] = []

    def admits(self, *args: object) -> bool:
        self.admissions.append(args)
        return False

    def admits_reversal(self, *args: object) -> bool:
        self.admissions.append(args)
        return False


class _NoDatabase:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Unadmitted source accessed the database: {name}")


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("identity_field", ["id", "entry_number"])
@pytest.mark.parametrize("operation", ["post", "reversal"])
@pytest.mark.parametrize("owner_mode", ["unavailable", "wrong-type", "denied"])
def test_generic_gl_refuses_monetary_namespace_before_financial_work(
    monkeypatch: pytest.MonkeyPatch, prefix: str, identity_field: str, operation: str, owner_mode: str,
) -> None:
    repository = object.__new__(posting.PostgresFinancePostingRepository)
    connection = _NoDatabase()
    repository.connection = connection
    repository.tenant_id = "tenant"
    monkeypatch.setattr(repository, "_transaction", lambda **_kwargs: nullcontext())
    source = {"id": "entry", "entry_number": "GENERIC"}
    # Both identity channels are guarded case-insensitively, including a
    # misleading ordinary entry number with a reserved source identity.
    source[identity_field] = prefix.lower() + "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(posting, "posting_entry", lambda *_args: source)
    monkeypatch.setattr(repository, "_get_effect", lambda _identifier: {"id": "effect", "source_kind": "Manual", "entry_id": source["id"]})
    resolved: list[str] = []

    def resolve(kind: str) -> type[_DenyingOwner] | None:
        resolved.append(kind)
        return None if owner_mode == "unavailable" else _DenyingOwner

    monkeypatch.setattr(posting, "source_participant_type", resolve)
    owner: object = _DenyingOwner() if owner_mode == "denied" else object()
    with pytest.raises(FinancePostingError) as refusal:
        if operation == "post":
            repository.post("entry", command_id="command", expected_validation_digest="a" * 64,
                            reason="Attempt reserved correction", actor=ACTOR, _source_owner=owner)
        else:
            repository.prepare_reversal("effect", command_id="command", entry_number="CR3R-REVIEWED-INVERSE",
                period_id="period", posting_date="2026-10-15", reason="Attempt reserved inverse", actor=ACTOR, _source_owner=owner)
    assert refusal.value.code == "posting_source_unsupported"
    assert resolved == [KIND]
    if isinstance(owner, _DenyingOwner):
        expected = ((connection, "tenant", source["id"]) if operation == "post" else
                    (connection, "tenant", source["id"], "effect", "CR3R-REVIEWED-INVERSE"))
        assert owner.admissions == [expected]


def test_monetary_participant_factory_has_one_fixed_module_and_class(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def load(name: str) -> SimpleNamespace:
        calls.append(name)
        return SimpleNamespace(_MonetaryCustomerReturnPostingParticipant=_DenyingOwner)

    monkeypatch.setattr(admission, "import_module", load)
    assert admission.source_participant_type(KIND) is _DenyingOwner
    assert calls == [MODULE]


def test_uninstalled_monetary_owner_remains_inadmissible(monkeypatch: pytest.MonkeyPatch) -> None:
    def absent(name: str) -> Any:
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(admission, "import_module", absent)
    assert admission.source_participant_type(KIND) is None


def test_missing_nested_dependency_is_not_silently_treated_as_an_uninstalled_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_dependency(_name: str) -> Any:
        raise ModuleNotFoundError(name="missing_dependency")

    monkeypatch.setattr(admission, "import_module", missing_dependency)
    with pytest.raises(ModuleNotFoundError) as failure:
        admission.source_participant_type(KIND)
    assert failure.value.name == "missing_dependency"