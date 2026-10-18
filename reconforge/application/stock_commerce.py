"""Commercial parent commands; native stock, AR and GL remain their owners."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.stock_commerce import CommercialOrder


class StockCommerceRepositoryProtocol(Protocol):
    def create(self, order: CommercialOrder, *, command_id: str, actor: PostingActor) -> dict[str, Any]: ...
    def act(self, identifier: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]: ...
    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]: ...
    def list(self, *, after: str, limit: int, actor: PostingActor) -> dict[str, Any]: ...
    def catalog(self, *, prefix: str, after: str, limit: int, actor: PostingActor) -> dict[str, Any]: ...


class StockCommerceApplicationService:
    def __init__(self, repository: StockCommerceRepositoryProtocol) -> None:
        self.repository = repository

    def create(self, order: CommercialOrder, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.create(order, command_id=command_id, actor=actor)

    def act(self, identifier: str, operation: str, *, expected_version: int, command_id: str,
            reason: str, parameters: Mapping[str, Any], actor: PostingActor) -> dict[str, Any]:
        return self.repository.act(identifier, operation, expected_version=expected_version, command_id=command_id,
            reason=reason, parameters=parameters, actor=actor)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(identifier, actor=actor)

    def list(self, *, after: str = "", limit: int = 50, actor: PostingActor) -> dict[str, Any]:
        return self.repository.list(after=after, limit=limit, actor=actor)

    def catalog(self, *, prefix: str = "", after: str = "", limit: int = 50, actor: PostingActor) -> dict[str, Any]:
        return self.repository.catalog(prefix=prefix, after=after, limit=limit, actor=actor)
