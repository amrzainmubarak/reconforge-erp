"""RLS-backed PostgreSQL control-plane export and immutable publication."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from reconforge.application.evidence import EvidenceStorageScope
from reconforge.application.scoped_exports import (
    PublishedScopedExport,
    ScopedExportDataset,
    ScopedExportError,
    ScopedExportRepository,
    ScopedExportScope,
    ScopedExportSnapshot,
)
from reconforge.auth.policy import CentralPolicyEngine, PolicyEvaluationContext, audit_policy_decision
from reconforge.infrastructure.object_storage import (
    ObjectStorageConflictError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFoundError,
    ObjectStoreProtocol,
)
from reconforge.infrastructure.postgres import (
    ConnectionFactory,
    PostgresTenantBoundary,
)

_MAX_ROWS_PER_DATASET = 10_000
_MAX_EXPORT_BYTES = 32 * 1024 * 1024
_EXPORT_PERMISSION = "reports.read"

_DATASET_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "branches",
        """SELECT id,organization_id,legal_entity_id,branch_code,name,active,created_at,updated_at
           FROM reconforge.branches ORDER BY id LIMIT %s""",
    ),
    (
        "durable_jobs",
        """SELECT id,version,status,workspace_id,entity_id,input_digest,config_digest,
                  worker_version,total_units,completed_units,retry_count,retry_ceiling,
                  safe_error_code,checkpoint_digest,output_manifest_schema_version,
                  output_manifest_digest,output_manifest_reference,created_at,updated_at
           FROM reconforge.durable_jobs ORDER BY id LIMIT %s""",
    ),
    (
        "evidence_registry",
        """SELECT id,workspace_id,evidence_code,checksum_sha256,provenance_type,
                  redaction_status,evidence_status,storage_backend,storage_tenant_id,
                  storage_key,storage_version_id,content_type,byte_size,retention_until,
                  created_at,updated_at
           FROM reconforge.evidence_application_registry ORDER BY id LIMIT %s""",
    ),
    (
        "fiscal_periods",
        """SELECT id,workspace_id,name,status,start_date,end_date,created_at
           FROM reconforge.domain_periods ORDER BY id LIMIT %s""",
    ),
    (
        "legal_entities",
        """SELECT id,organization_id,entity_code,name,currency_code,active,created_at,updated_at
           FROM reconforge.legal_entities ORDER BY id LIMIT %s""",
    ),
    (
        "organizations",
        """SELECT id,organization_code,name,base_currency,active,application_workspace_id,
                  created_at,updated_at
           FROM reconforge.organizations ORDER BY id LIMIT %s""",
    ),
    (
        "workspaces",
        """SELECT id,name,created_at FROM reconforge.domain_workspaces ORDER BY id LIMIT %s""",
    ),
)


def _export_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ScopedExportError("Export timestamp must be timezone-aware.")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise ScopedExportError("PostgreSQL returned an unsupported export value.")


def _row_payload(row: Any) -> dict[str, object]:
    keys = tuple(str(key) for key in row.keys())  # noqa: SIM118 - driver rows iterate values
    return {key: _export_value(row[key]) for key in keys}


class PostgresScopedExportRepository:
    """Read a bounded deterministic snapshot beneath PostgreSQL RLS."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._boundary = PostgresTenantBoundary(connection_factory)

    def snapshot(self, scope: ScopedExportScope) -> ScopedExportSnapshot:
        datasets: list[ScopedExportDataset] = []
        with self._boundary.transaction(
            scope.tenant_id,
            organization_id=scope.organization_id or None,
            workspace_id=scope.workspace_id,
            legal_entity_id=scope.entity_id or None,
        ) as connection:
            for name, query in _DATASET_QUERIES:
                if name == "evidence_registry" and scope.entity_id:
                    continue
                rows = connection.execute(query, (_MAX_ROWS_PER_DATASET + 1,)).fetchall()
                if len(rows) > _MAX_ROWS_PER_DATASET:
                    raise ScopedExportError(f"Export dataset '{name}' exceeds its row limit.")
                datasets.append(ScopedExportDataset(name=name, rows=tuple(_row_payload(row) for row in rows)))
        return ScopedExportSnapshot(scope=scope, datasets=tuple(datasets))


class PostgresScopedExportPublisher:
    """Authorize, snapshot, and idempotently publish one hierarchy-bound export."""

    def __init__(self, repository: ScopedExportRepository, object_store: ObjectStoreProtocol) -> None:
        if not bool(getattr(object_store, "supports_hierarchical_scope", False)):
            raise ScopedExportError("Enterprise export publication requires hierarchical object storage.")
        self.repository = repository
        self.object_store = object_store

    @staticmethod
    def _authorize(
        scope: ScopedExportScope,
        *,
        policy_context: PolicyEvaluationContext,
        request_id: str,
        surface: str,
    ) -> None:
        """Authorize one snapshot/publication phase against the exact hierarchy."""

        if policy_context.tenant_id != scope.tenant_id:
            raise ScopedExportError("Export policy context does not match the requested tenant.")
        if policy_context.workspace_id != scope.workspace_id:
            raise ScopedExportError("Export policy context does not match the requested workspace.")
        if policy_context.entity_id != (scope.entity_id or None):
            raise ScopedExportError("Export policy context does not match the requested entity.")
        decision = CentralPolicyEngine().evaluate(
            policy_context,
            required_permission=_EXPORT_PERMISSION,
            enforce_sod=False,
            enforce_ownership=False,
        )
        audit_policy_decision(
            decision,
            actor_id=policy_context.user_id,
            required_permissions=frozenset({_EXPORT_PERMISSION}),
            surface=surface,
            request_id=request_id,
            principal_type=policy_context.principal_type,
        )
        if not decision.allowed:
            raise ScopedExportError("Scoped export authorization was denied.")

    def publish(
        self,
        scope: ScopedExportScope,
        *,
        policy_context: PolicyEvaluationContext,
        policy_context_supplier: Callable[[], PolicyEvaluationContext] | None = None,
        request_id: str = "",
    ) -> PublishedScopedExport:
        self._authorize(
            scope,
            policy_context=policy_context,
            request_id=request_id,
            surface="postgres.scoped_export.publish",
        )

        try:
            snapshot = self.repository.snapshot(scope)
        except ScopedExportError:
            raise
        except Exception as exc:
            raise ScopedExportError("Scoped export snapshot failed.") from exc
        content = snapshot.to_bytes()
        if len(content) > _MAX_EXPORT_BYTES:
            raise ScopedExportError("Scoped export exceeds its byte limit.")
        if policy_context_supplier is not None:
            try:
                current_policy_context = policy_context_supplier()
            except Exception as exc:
                raise ScopedExportError("Scoped export authorization recheck failed.") from exc
            self._authorize(
                scope,
                policy_context=current_policy_context,
                request_id=request_id,
                surface="postgres.scoped_export.publish.recheck",
            )
        object_name = f"exports/control-plane/{snapshot.digest}.json"
        storage_scope = EvidenceStorageScope(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            entity_id=scope.entity_id,
        )
        try:
            stored = self.object_store.put_bytes(
                storage_scope,
                object_name,
                content,
                content_type="application/json",
                metadata={"artifact-type": "scoped-control-plane-export", "schema-version": "1"},
            )
        except ObjectStorageConflictError:
            stored = self.object_store.get_bytes(storage_scope, object_name)
        except (ObjectStorageNotFoundError, ObjectStorageIntegrityError):
            raise
        except Exception as exc:
            raise ScopedExportError("Scoped export publication failed.") from exc

        actual_digest = hashlib.sha256(stored.content).hexdigest()
        if stored.content != content or stored.sha256 != actual_digest:
            raise ObjectStorageIntegrityError("Published export bytes do not match the scoped snapshot.")
        expected_metadata: Mapping[str, str] = {
            "reconforge-tenant": storage_scope.tenant_id,
            "reconforge-workspace": storage_scope.workspace_id,
            "reconforge-entity": storage_scope.entity_id,
        }
        if any(stored.metadata.get(key, "") != value for key, value in expected_metadata.items()):
            raise ObjectStorageIntegrityError("Published export hierarchy metadata is invalid.")
        return PublishedScopedExport(
            digest=snapshot.digest,
            object_name=object_name,
            byte_size=len(content),
            version_id=stored.version_id or "",
        )
