"""Application boundary for scoped PostgreSQL exception review."""

from __future__ import annotations

from typing import Any, Protocol

from reconforge.domain.exception_review import (
    ExceptionReviewAssignment,
    ExceptionReviewHistoryPage,
    ExceptionReviewListPage,
    ExceptionReviewQuery,
    ExceptionReviewScope,
    ExceptionReviewTransition,
)


class ExceptionReviewRepositoryProtocol(Protocol):
    """Port implemented by the PostgreSQL exception-queue adapter."""

    def list_for_review(
        self,
        scope: ExceptionReviewScope,
        query: ExceptionReviewQuery,
    ) -> list[dict[str, Any]]: ...

    def list_page_for_review(
        self,
        scope: ExceptionReviewScope,
        query: ExceptionReviewQuery,
        page: ExceptionReviewListPage,
    ) -> dict[str, Any]: ...

    def get_for_review(
        self,
        scope: ExceptionReviewScope,
        exception_id: str,
        history_page: ExceptionReviewHistoryPage,
    ) -> dict[str, Any]: ...

    def assign_for_review(
        self,
        scope: ExceptionReviewScope,
        command: ExceptionReviewAssignment,
    ) -> dict[str, Any]: ...

    def transition_for_review(
        self,
        scope: ExceptionReviewScope,
        command: ExceptionReviewTransition,
    ) -> dict[str, Any]: ...


class ExceptionReviewApplicationService:
    """Coordinate typed review commands without coupling callers to SQL."""

    def __init__(self, repository: ExceptionReviewRepositoryProtocol) -> None:
        self.repository = repository

    def list(self, scope: ExceptionReviewScope, query: ExceptionReviewQuery) -> list[dict[str, Any]]:
        return self.repository.list_for_review(scope, query)

    def list_page(
        self,
        scope: ExceptionReviewScope,
        query: ExceptionReviewQuery,
        page: ExceptionReviewListPage,
    ) -> dict[str, Any]:
        return self.repository.list_page_for_review(scope, query, page)

    def get(
        self,
        scope: ExceptionReviewScope,
        exception_id: str,
        history_page: ExceptionReviewHistoryPage | None = None,
    ) -> dict[str, Any]:
        return self.repository.get_for_review(
            scope,
            exception_id,
            history_page or ExceptionReviewHistoryPage(),
        )

    def assign(self, scope: ExceptionReviewScope, command: ExceptionReviewAssignment) -> dict[str, Any]:
        return self.repository.assign_for_review(scope, command)

    def transition(self, scope: ExceptionReviewScope, command: ExceptionReviewTransition) -> dict[str, Any]:
        return self.repository.transition_for_review(scope, command)


__all__ = ["ExceptionReviewApplicationService", "ExceptionReviewRepositoryProtocol"]
