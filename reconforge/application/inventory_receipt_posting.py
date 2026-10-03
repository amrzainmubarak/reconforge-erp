"""Complete reviewed source commands; each adapter owns its atomic boundary."""
from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.inventory_receipt_posting import (
    ReceiptEffect,
    ReceiptPlan,
    ReceiptPlanView,
    ReceiptPreparation,
    ReceiptReversalPreparation,
    ReceiptReview,
)


class InventoryReceiptFinanceParticipantProtocol(Protocol):
    """Exact-owner-bound source reader/writer, never a caller posting capability."""

    def materialize_draft(self, plan_id: str, *, expected_review_digest: str, actor: PostingActor) -> str: ...
    def seal_and_post(self, plan_id: str, *, expected_review_digest: str, actor: PostingActor) -> dict[str, Any]: ...


class InventoryReceiptPostingRepositoryProtocol(Protocol):
    def prepare_receipt(self, request: ReceiptPreparation, *, command_id: str, actor: PostingActor) -> ReceiptPlan: ...
    def prepare_reversal(self, request: ReceiptReversalPreparation, *, command_id: str, actor: PostingActor) -> ReceiptPlan: ...
    def review(self, plan_id: str, *, command_id: str, expected_plan_digest: str, reason: str, actor: PostingActor) -> ReceiptReview: ...
    def commit(self, plan_id: str, *, command_id: str, expected_review_digest: str, reason: str, actor: PostingActor) -> ReceiptEffect: ...
    def get_plan(self, plan_id: str, *, actor: PostingActor) -> ReceiptPlanView: ...
    def get_effect(self, plan_id: str, *, actor: PostingActor) -> ReceiptEffect: ...


class InventoryReceiptPostingApplicationService:
    def __init__(self, repository: InventoryReceiptPostingRepositoryProtocol) -> None:
        self.repository = repository

    def prepare_receipt(self, request: ReceiptPreparation, *, command_id: str, actor: PostingActor) -> ReceiptPlan:
        return self.repository.prepare_receipt(request, command_id=command_id, actor=actor)

    def prepare_reversal(self, request: ReceiptReversalPreparation, *, command_id: str, actor: PostingActor) -> ReceiptPlan:
        return self.repository.prepare_reversal(request, command_id=command_id, actor=actor)

    def review(self, plan_id: str, *, command_id: str, expected_plan_digest: str, reason: str, actor: PostingActor) -> ReceiptReview:
        return self.repository.review(plan_id, command_id=command_id, expected_plan_digest=expected_plan_digest, reason=reason, actor=actor)

    def commit(self, plan_id: str, *, command_id: str, expected_review_digest: str, reason: str, actor: PostingActor) -> ReceiptEffect:
        return self.repository.commit(plan_id, command_id=command_id, expected_review_digest=expected_review_digest, reason=reason, actor=actor)

    def get_plan(self, plan_id: str, *, actor: PostingActor) -> ReceiptPlanView:
        return self.repository.get_plan(plan_id, actor=actor)

    def get_effect(self, plan_id: str, *, actor: PostingActor) -> ReceiptEffect:
        return self.repository.get_effect(plan_id, actor=actor)
