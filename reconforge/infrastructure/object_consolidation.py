"""Immutable object-storage adapter for consolidation translation results."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping

from reconforge.application.consolidation import ConsolidationArtifactReceipt
from reconforge.application.evidence import EvidenceStorageScope
from reconforge.domain.consolidation import (
    ConsolidationError,
    ConsolidationTranslationResult,
    validate_consolidation_run_id,
    verify_consolidation_result_payload,
)
from reconforge.infrastructure.object_storage import (
    ObjectStorageConflictError,
    ObjectStorageNotFoundError,
    ObjectStorageOperationError,
    ObjectStoreProtocol,
    StoredObject,
)
from reconforge.io.structured import StructuredDocumentError, StructuredDocumentPolicy, parse_json_document

_CONSOLIDATION_ARTIFACT_POLICY = StructuredDocumentPolicy(
    max_file_bytes=64 * 1024 * 1024,
    max_nodes=2_500_000,
    max_depth=32,
    max_collection_items=500_000,
    max_scalar_characters=1_000_000,
    max_yaml_aliases=1,
)


class ObjectStoreConsolidationResultRepository:
    """Store schema-v1 results under tenant/workspace-separated immutable keys."""

    def __init__(self, object_store: ObjectStoreProtocol) -> None:
        self.object_store = object_store

    @staticmethod
    def _name(run_id: str) -> str:
        return f"consolidation/v1/{validate_consolidation_run_id(run_id)}.json"

    @staticmethod
    def _scope(tenant_id: str, workspace_id: str) -> EvidenceStorageScope:
        try:
            return EvidenceStorageScope(tenant_id=tenant_id, workspace_id=workspace_id)
        except ValueError as exc:
            raise ConsolidationError("Consolidation artifact scope is invalid.") from exc

    @staticmethod
    def _content(result: ConsolidationTranslationResult) -> bytes:
        encoded = json.dumps(
            result.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        return (encoded + "\n").encode("ascii")

    @staticmethod
    def _receipt(result: ConsolidationTranslationResult, stored: StoredObject) -> ConsolidationArtifactReceipt:
        return ConsolidationArtifactReceipt(
            run_id=result.run_id,
            result_digest=result.result_digest,
            object_key=stored.key,
            sha256=stored.sha256,
            size_bytes=len(stored.content),
            content=stored.content,
        )

    def save(
        self,
        result: ConsolidationTranslationResult,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> ConsolidationArtifactReceipt:
        if not isinstance(result, ConsolidationTranslationResult):
            raise ConsolidationError("Consolidation result is invalid.")
        scope = self._scope(tenant_id, workspace_id)
        name = self._name(result.run_id)
        content = self._content(result)
        metadata = {
            "artifact-schema": "consolidation-translation-result-v1",
            "request-digest": result.request_digest,
            "result-digest": result.result_digest,
        }
        try:
            stored = self.object_store.put_bytes(
                scope,
                name,
                content,
                content_type="application/vnd.reconforge.consolidation-translation+json",
                metadata=metadata,
            )
        except ObjectStorageConflictError:
            try:
                stored = self.object_store.get_bytes(scope, name)
            except ObjectStorageOperationError as exc:
                raise ConsolidationError("Consolidation artifact conflict could not be verified.") from exc
            if not hmac.compare_digest(stored.content, content):
                raise ConsolidationError(
                    "Consolidation run identity conflicts with different immutable content."
                ) from None
        except (ObjectStorageOperationError, ValueError) as exc:
            raise ConsolidationError("Consolidation artifact could not be stored.") from exc
        if not hmac.compare_digest(stored.sha256, hashlib.sha256(content).hexdigest()):
            raise ConsolidationError("Consolidation artifact storage receipt is invalid.")
        return self._receipt(result, stored)

    def load(
        self,
        run_id: str,
        *,
        tenant_id: str,
        workspace_id: str,
    ) -> ConsolidationTranslationResult:
        scope = self._scope(tenant_id, workspace_id)
        name = self._name(run_id)
        try:
            stored = self.object_store.get_bytes(scope, name)
        except (ObjectStorageNotFoundError, ValueError) as exc:
            raise ConsolidationError("Consolidation artifact is unavailable in the requested scope.") from exc
        except ObjectStorageOperationError as exc:
            raise ConsolidationError("Consolidation artifact integrity verification failed.") from exc
        try:
            text = stored.content.decode("ascii", errors="strict")
            payload = parse_json_document(text, policy=_CONSOLIDATION_ARTIFACT_POLICY)
        except (UnicodeError, StructuredDocumentError) as exc:
            raise ConsolidationError("Consolidation artifact document is invalid.") from exc
        if not isinstance(payload, Mapping):
            raise ConsolidationError("Consolidation artifact document is invalid.")
        result = verify_consolidation_result_payload(payload)
        if result.run_id != run_id:
            raise ConsolidationError("Consolidation artifact run identity is invalid.")
        return result
