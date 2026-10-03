"""Exact content, maker/checker and full-reversal rules without storage."""

from copy import deepcopy
from typing import Any

import pytest

from reconforge.domain.finance_posting import (
    FinancePostingError,
    PostingActor,
    canonical_json,
    make_entry_snapshot,
    require_full_reversal,
    require_reviewed,
    validation_digest,
)


def snapshot() -> dict[str, Any]:
    entry = dict(
        id="e",
        workspace_id="w",
        organization_id="o",
        legal_entity_id="le",
        journal_id="j",
        period_id="p",
        entry_number="ENTRY",
        posting_date="2026-10-03",
        description="Retained review",
        external_reference="",
        source_type="Manual",
        currency_code="EGP",
        currency_precision=2,
        currency_rounding_policy="ROUND_HALF_UP",
        currency_registry_version="v1",
        currency_registry_digest="a" * 64,
        preparer_actor_id="maker",
        reverses_posting_id=None,
    )
    return make_entry_snapshot(
        entry,
        [
            dict(
                line_number=1,
                account_id="cash",
                description="",
                debit_minor=9007199254740993,
                credit_minor=0,
                dimensions={"branch": "hq"},
            ),
            dict(
                line_number=2,
                account_id="capital",
                description="",
                debit_minor=0,
                credit_minor=9007199254740993,
                dimensions={"branch": "hq"},
            ),
        ],
    )


def test_exact_large_integer_evidence_and_permuted_storage_order() -> None:
    original = snapshot()
    assert "9007199254740993" in canonical_json(original)
    assert validation_digest(original) == validation_digest(
        make_entry_snapshot(original["entry"], list(reversed(original["lines"])))
    )
    changed = deepcopy(original)
    changed["lines"][0]["description"] = "Reviewed content changed"
    assert validation_digest(changed) != validation_digest(original)


@pytest.mark.parametrize("bad", [True, 1.0, "1", None, -1, 9223372036854775808])
def test_no_money_coercion_or_overflow(bad: object) -> None:
    value = snapshot()
    value["lines"][0]["debit_minor"] = bad
    with pytest.raises(FinancePostingError):
        validation_digest(value)


@pytest.mark.parametrize(
    "part,bad", [("entry", None), ("lines", None), ("lines", [None]), ("schema_version", "future")]
)
def test_malformed_snapshot_fails_with_typed_error(part: str, bad: object) -> None:
    value = snapshot()
    value[part] = bad
    with pytest.raises(FinancePostingError):
        validation_digest(value)


def test_unbalanced_and_unknown_fields_are_not_reviewable() -> None:
    value = snapshot()
    value["lines"][0]["debit_minor"] -= 1
    with pytest.raises(FinancePostingError, match="balance"):
        validation_digest(value)
    value = snapshot()
    value["entry"]["unknown"] = "not sealed"
    with pytest.raises(FinancePostingError, match="canonical"):
        validation_digest(value)


def test_full_reversal_retains_policy_scope_and_dimension_multiset() -> None:
    original = snapshot()
    inverse = deepcopy(original)
    inverse["entry"].update(id="reverse", entry_number="REV", reverses_posting_id="posting")
    for line in inverse["lines"]:
        line["debit_minor"], line["credit_minor"] = line["credit_minor"], line["debit_minor"]
    require_full_reversal(original, inverse)
    for part, key, new in (
        ("entry", "currency_precision", 3),
        ("entry", "legal_entity_id", "sibling"),
        ("line", "dimensions", {"branch": "other"}),
    ):
        changed = deepcopy(inverse)
        (changed["entry"] if part == "entry" else changed["lines"][0])[key] = new
        with pytest.raises(FinancePostingError):
            require_full_reversal(original, changed)


def test_reviewed_posting_requires_stable_human_independent_identity() -> None:
    value = snapshot()
    digest = validation_digest(value)
    entry = {
        **value["entry"],
        "status": "Validated",
        "validator_actor_id": "checker",
        "validation_digest": digest,
        "validation_contract_version": value["schema_version"],
    }
    checker = PostingActor("checker", "reviewer", frozenset({"finance_core.post"}), step_up_active=True)
    assert require_reviewed(entry, value, checker) == digest
    for actor in (
        PostingActor("maker", "renamed maker", checker.permissions, step_up_active=True),
        PostingActor("robot", "robot", checker.permissions, "service_account", True),
        PostingActor("checker", "reviewer", checker.permissions),
    ):
        with pytest.raises(FinancePostingError):
            require_reviewed(entry, value, actor)
    entry["validator_actor_id"] = None
    with pytest.raises(FinancePostingError, match="legacy provenance"):
        require_reviewed(entry, value, checker)
