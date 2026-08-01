"""Application boundary for deterministic consolidation translation artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from reconforge.domain.consolidation import (
    ConsolidationError,
    ConsolidationRequest,
    ConsolidationTranslationResult,
    translate_consolidation,
)


@dataclass(frozen=True)
class ConsolidationArtifactReceipt:
    """Immutable artifact identity and byte-integrity evidence."""

    run_id: str
    result_digest: str
    object_key: str
    sha256: str
    size_bytes: int
    content: bytes


@dataclass(frozen=True)
class StoredConsolidationResult:
    """Calculated result paired with its immutable storage receipt."""

    result: ConsolidationTranslationResult
    receipt: ConsolidationArtifactReceipt


class ConsolidationResultRepositoryProtocol(Protocol):
    """Immutable artifact port for consolidation results."""

    def save(
        self,
        result: ConsolidationTranslationResult,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> ConsolidationArtifactReceipt: ...

    def load(
        self,
        run_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> ConsolidationTranslationResult: ...


class ConsolidationApplicationService:
    """Calculate, persist, and replay-verify one bounded consolidation result."""

    def __init__(self, repository: ConsolidationResultRepositoryProtocol | None = None) -> None:
        self.repository = repository

    @staticmethod
    def calculate(request: ConsolidationRequest) -> ConsolidationTranslationResult:
        return translate_consolidation(request)

    def calculate_and_store(
        self,
        request: ConsolidationRequest,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> StoredConsolidationResult:
        if self.repository is None:
            raise ConsolidationError("Consolidation result repository is not configured.")
        result = self.calculate(request)
        receipt = self.repository.save(
            result,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
        )
        return StoredConsolidationResult(result=result, receipt=receipt)

    def load_and_verify(
        self,
        run_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> ConsolidationTranslationResult:
        if self.repository is None:
            raise ConsolidationError("Consolidation result repository is not configured.")
        return self.repository.load(run_id, tenant_id=tenant_id, workspace_id=workspace_id)
