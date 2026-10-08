"""Exact receipt HTTP shape does not reinterpret retained source evidence."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from reconforge.api.inventory_receipt_contract import project_receipt_view
from reconforge.api.routes.inventory_receipt_posting import CommitRequest, ReceiptRequest, ReviewRequest
from reconforge.auth import LocalAuthService
from reconforge.domain.inventory_receipt_posting import InventoryReceiptPostingError
from reconforge.infrastructure.sqlite_inventory_receipt_posting import SQLiteInventoryReceiptPostingRepository
from tests.test_sqlite_finance_posting import _actor, _posting_actor
from tests.test_sqlite_inventory_receipt_posting import _fixture, _reviewed


def test_actual_sqlite_receipt_projection_preserves_canonical_source_and_exact_lines(tmp_path: Path):
    _, connection, repository, request = _fixture(tmp_path)
    try:
        plan, review = _reviewed(connection, repository, request)
        value = project_receipt_view({"plan": plan, "review": review, "effect": None})
        assert value["status"] == "Reviewed" and value["total_value_minor"] == "12000"
        assert value["lines"] == [{"account_id": plan["mapping"]["inventory_account_id"], "debit_minor": "12000", "credit_minor": "0"}, {"account_id": plan["mapping"]["receipt_clearing_account_id"], "debit_minor": "0", "credit_minor": "12000"}]
        assert json.loads(value["plan_json"]) == plan
        assert json.loads(value["review_json"]) == review
        corrupt = deepcopy(plan)
        corrupt["source"]["total_value_minor"] += 1
        with pytest.raises(InventoryReceiptPostingError):
            project_receipt_view({"plan": corrupt, "review": review, "effect": None})
        with pytest.raises(ValueError):
            project_receipt_view({"plan": plan, "review": review, "effect": None, "driver_secret": "hidden"})
    finally:
        connection.close()

@pytest.mark.parametrize("value", [12000, 12000.0, True, "012000", "1e3", "0", "-1"])
def test_receipt_api_refuses_coerced_money(value):
    fields = dict(command_id="prepare", receipt_number="REC", posting_date="2026-10-03", period_id="period", item_code="ITEM", location_code="MAIN/STOCK", quantity="10", total_value_minor=value, policy_code="FIFO", organization_code="ORG", entity_code="ENTITY", reason="Explicit")
    with pytest.raises(ValueError):
        ReceiptRequest(**fields)

def test_receipt_api_no_actor_assurance_or_unknown_fields():
    with pytest.raises(ValueError):
        ReviewRequest(command_id="review", expected_plan_digest="a" * 64, reason="Independent", actor_id="other")
    with pytest.raises(ValueError):
        CommitRequest(command_id="commit", expected_review_digest="a" * 64, reason="Explicit", step_up_active=True)


@pytest.mark.parametrize("operation", ["prepare", "review", "commit"])
def test_strict_receipt_replay_binds_original_human_and_keeps_shared_recovery(tmp_path: Path, operation: str):
    _, connection, repository, request = _fixture(tmp_path)
    try:
        LocalAuthService(connection).create_user(
            username="other-checker", password="Synthetic-posting-password-123", role="admin"
        )
        plan, review = _reviewed(connection, repository, request)
        strict = SQLiteInventoryReceiptPostingRepository(connection, strict_command_actor=True)
        with _actor(connection, "checker") as principal:
            effect = strict.commit(
                plan["plan_id"], command_id="strict-commit", expected_review_digest=review["review_digest"],
                reason="Explicit atomic receipt", actor=_posting_actor(principal),
            )

        def replay(owner, actor):
            if operation == "prepare":
                return owner.prepare_receipt(request, command_id="prepare-10", actor=actor)
            if operation == "review":
                return owner.review(
                    plan["plan_id"], command_id="review-10", expected_plan_digest=plan["plan_digest"],
                    reason="Count and cost independently checked", actor=actor,
                )
            return owner.commit(
                plan["plan_id"], command_id="strict-commit", expected_review_digest=review["review_digest"],
                reason="Explicit atomic receipt", actor=actor,
            )

        expected = {"prepare": plan, "review": review, "commit": effect}[operation]
        with _actor(connection, "maker" if operation == "prepare" else "checker") as principal:
            assert replay(strict, _posting_actor(principal)) == expected
        with _actor(connection, "other-checker") as principal:
            actor = _posting_actor(principal)
            before = tuple(connection.iterdump())
            with pytest.raises(InventoryReceiptPostingError) as failure:
                replay(strict, actor)
            assert failure.value.code == "inventory_receipt_command_actor_denied"
            assert tuple(connection.iterdump()) == before
            assert strict.get_plan(plan["plan_id"], actor=actor)["effect"] == effect
            # The inherited adapter remains compatible with authorized shared replay.
            assert replay(repository, actor) == expected
            assert tuple(connection.iterdump()) == before
    finally:
        connection.close()
