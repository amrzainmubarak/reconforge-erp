"""Backend-neutral contract for an atomic product-sale source owner."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.stock_sales import StockOrder


class StockSalesRepositoryProtocol(Protocol):
    def create(self, request: StockOrder, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def act(self, identifier: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]: ...
    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def list(self, *, actor: PostingActor) -> dict[str, Any]: ...
    def options(self, *, actor: PostingActor) -> dict[str, Any]: ...


class StockSalesApplicationService:
    def __init__(self, repository: StockSalesRepositoryProtocol) -> None:
        self.repository = repository

    def create(self, request: StockOrder, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create(request, command_id=command_id, actor=actor)

    def act(self, identifier: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        return self.repository.act(identifier, operation, expected_version=expected_version,
            command_id=command_id, reason=reason, parameters=parameters, actor=actor)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(identifier, actor=actor)

    def list(self, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.list(actor=actor)

    def options(self, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.options(actor=actor)
