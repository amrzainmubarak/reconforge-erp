"""Governed same-entity transfer and independently reviewed exact inverse."""
from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_posting import PostingActor
from reconforge.domain.inventory_transfer import TransferInversePreparation, TransferPreparation
from reconforge.ports.inventory_transfer import InventoryTransferRepository


class InventoryTransferService:
    def __init__(self, repository: InventoryTransferRepository) -> None:
        self.repository = repository

    def create(self, request: TransferPreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request.payload()
        return self.repository.create(request, command_id=command_id, actor=actor)

    def create_inverse(self, request: TransferInversePreparation, *, command_id: str, actor: PostingActor) -> dict[str, Any]:
        request.payload()
        return self.repository.create_inverse(request, command_id=command_id, actor=actor)

    def act(self, identifier: str, operation: str, *, expected_digest: str, expected_version: int,
            command_id: str, reason: str, actor: PostingActor) -> dict[str, Any]:
        return self.repository.act(identifier, operation, expected_digest=expected_digest, expected_version=expected_version,
            command_id=command_id, reason=reason, actor=actor)

    def get(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.get(identifier, actor=actor)

    def evidence(self, identifier: str, *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.evidence(identifier, actor=actor)

    def list_transfers(self, scope: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.list_transfers(scope, actor=actor)

    def command_receipt(self, identifier: str, command_id: str, response: Mapping[str, Any], *, actor: PostingActor) -> dict[str, Any]:
        return self.repository.command_receipt(identifier, command_id, response, actor=actor)
