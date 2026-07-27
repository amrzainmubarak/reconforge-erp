"""DB-backed evidence registry and coverage helpers."""

from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from reconforge.db.exporter import checksum_file, resolve_input_file
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.object_storage import StoredObject
from reconforge.infrastructure.postgres import normalize_scope_id
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    platform_id,
    require_permission,
    rows_to_dicts,
)


@dataclass(frozen=True)
class EvidenceVerification:
    """Checksum verification result for one evidence object."""

    evidence_id: str
    ok: bool
    expected_sha256: str
    actual_sha256: str


class EvidenceObjectStore(Protocol):
    """Minimal object-storage contract required by the evidence registry."""

    def put_bytes(
        self,
        tenant_id: str,
        object_name: str,
        content: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: dict[str, object] | None = None,
        retention_until: datetime | None = None,
    ) -> StoredObject:
        """Store one tenant-scoped artifact."""

    def get_bytes(self, tenant_id: str, object_name: str) -> StoredObject:
        """Read one tenant-scoped artifact and verify provider metadata."""


LOCAL_STORAGE_BACKEND = "local-filesystem"
OBJECT_STORAGE_BACKEND = "s3-compatible-object-storage"
_OBJECT_STORAGE_COLUMNS = {
    "storage_backend",
    "storage_tenant_id",
    "storage_key",
    "storage_version_id",
    "content_type",
    "byte_size",
    "retention_until",
}


class EvidenceRegistryService:
    """Local checksum/provenance evidence registry.

    Evidence integrity here is a checksum aid only. It is not a signature
    workflow or non-repudiation control.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def _storage_columns_available(self) -> bool:
        """Return whether the additive object-storage migration is present."""

        columns = {
            str(row["name"]) for row in self.connection.execute("PRAGMA table_info(evidence_registry)").fetchall()
        }
        return columns >= _OBJECT_STORAGE_COLUMNS

    def register(
        self,
        source_path: Path | str,
        *,
        evidence_code: str = "",
        workspace: str = "default",
        provenance_type: str = "local-file",
        redaction_status: str = "unknown",
        evidence_status: str = "Available",
        object_type: str = "",
        object_id: str = "",
        link_type: str = "support",
        actor_label: str = "local-cli",
        object_store: EvidenceObjectStore | None = None,
        storage_tenant_id: str = "",
        storage_object_name: str = "",
        content_type: str = "",
        retention_until: datetime | None = None,
    ) -> dict[str, Any]:
        """Register evidence locally or in an explicit S3-compatible object store.

        Local filesystem registration remains the default. When ``object_store``
        is supplied, the bytes are uploaded and the DB row is committed only
        after the provider returns a verified object reference. The local path
        remains provenance metadata; verification reads the object store and
        never silently falls back to that path.
        """

        require_permission(self.connection, actor_label=actor_label, permission="evidence.manage")
        resolved = resolve_input_file(source_path)
        workspace_id = ensure_workspace(self.connection, workspace)
        code = normalize_key(evidence_code, default=resolved.name)
        evidence_id = platform_id("EVDREG", workspace_id, code)
        storage_columns_available = self._storage_columns_available()
        if object_store is not None and not storage_columns_available:
            raise PlatformError("Evidence object storage requires the latest database migration.")
        if object_store is None and (storage_tenant_id or storage_object_name or retention_until is not None):
            raise PlatformError("Object-storage options require an explicitly configured object store.")

        storage_backend = LOCAL_STORAGE_BACKEND
        storage_tenant = ""
        storage_key = ""
        storage_version_id = ""
        stored_content_type = "application/octet-stream"
        byte_size = 0
        stored_retention_until = ""
        if object_store is None:
            checksum = checksum_file(resolved)
        else:
            try:
                content = resolved.read_bytes()
                checksum = hashlib.sha256(content).hexdigest()
                storage_tenant = normalize_scope_id(storage_tenant_id or workspace_id)
                stored_content_type = (
                    content_type.strip() or mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
                )
                storage_key = (
                    storage_object_name.strip() or f"evidence/{evidence_id}/{checksum}{resolved.suffix.lower()}"
                )
                stored = object_store.put_bytes(
                    storage_tenant,
                    storage_key,
                    content,
                    content_type=stored_content_type,
                    metadata={"evidence-id": evidence_id, "source-name": resolved.name},
                    retention_until=retention_until,
                )
                actual_checksum = hashlib.sha256(stored.content).hexdigest()
                if actual_checksum != checksum or stored.sha256 != actual_checksum:
                    raise PlatformError("Stored evidence checksum did not match the source content.")
                returned_tenant = str(stored.metadata.get("reconforge-tenant", storage_tenant))
                if returned_tenant != storage_tenant:
                    raise PlatformError("Object storage returned an unexpected tenant scope.")
                storage_backend = OBJECT_STORAGE_BACKEND
                storage_version_id = stored.version_id or ""
                byte_size = len(content)
                stored_retention_until = retention_until.isoformat() if retention_until is not None else ""
            except PlatformError:
                raise
            except Exception as exc:
                raise PlatformError("Unable to store evidence artifact in configured object storage.") from exc
        now = utc_now_text()
        try:
            if storage_columns_available:
                self.connection.execute(
                    """
                    INSERT INTO evidence_registry (
                        id, workspace_id, evidence_code, source_path, checksum_sha256,
                        provenance_type, redaction_status, evidence_status, storage_backend,
                        storage_tenant_id, storage_key, storage_version_id, content_type,
                        byte_size, retention_until, registered_by, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, evidence_code)
                    DO UPDATE SET
                        source_path = excluded.source_path,
                        checksum_sha256 = excluded.checksum_sha256,
                        provenance_type = excluded.provenance_type,
                        redaction_status = excluded.redaction_status,
                        evidence_status = excluded.evidence_status,
                        storage_backend = excluded.storage_backend,
                        storage_tenant_id = excluded.storage_tenant_id,
                        storage_key = excluded.storage_key,
                        storage_version_id = excluded.storage_version_id,
                        content_type = excluded.content_type,
                        byte_size = excluded.byte_size,
                        retention_until = excluded.retention_until,
                        registered_by = excluded.registered_by,
                        updated_at = excluded.updated_at
                    """,
                    (
                        evidence_id,
                        workspace_id,
                        code,
                        str(resolved),
                        checksum,
                        normalize_key(provenance_type, default="local-file"),
                        normalize_key(redaction_status, default="unknown"),
                        normalize_key(evidence_status, default="Available"),
                        storage_backend,
                        storage_tenant,
                        storage_key,
                        storage_version_id,
                        stored_content_type,
                        byte_size,
                        stored_retention_until,
                        actor_label,
                        now,
                        now,
                    ),
                )
            else:
                self.connection.execute(
                    """
                    INSERT INTO evidence_registry (
                        id, workspace_id, evidence_code, source_path, checksum_sha256,
                        provenance_type, redaction_status, evidence_status, registered_by,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, evidence_code)
                    DO UPDATE SET
                        source_path = excluded.source_path,
                        checksum_sha256 = excluded.checksum_sha256,
                        provenance_type = excluded.provenance_type,
                        redaction_status = excluded.redaction_status,
                        evidence_status = excluded.evidence_status,
                        registered_by = excluded.registered_by,
                        updated_at = excluded.updated_at
                    """,
                    (
                        evidence_id,
                        workspace_id,
                        code,
                        str(resolved),
                        checksum,
                        normalize_key(provenance_type, default="local-file"),
                        normalize_key(redaction_status, default="unknown"),
                        normalize_key(evidence_status, default="Available"),
                        actor_label,
                        now,
                        now,
                    ),
                )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to register evidence.") from exc
        if object_type and object_id:
            link = self._insert_link(
                evidence_id,
                object_type=object_type,
                object_id=object_id,
                link_type=link_type,
            )
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="evidence_link",
                object_id=link["id"],
                action="evidence_linked",
                metadata={"evidence_id": evidence_id, "target_type": object_type, "target_id": object_id},
                emit_outbox=True,
                outbox_event_type="evidence_linked",
                outbox_payload={"evidence_id": evidence_id, "target_type": object_type, "target_id": object_id},
            )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="evidence",
            object_id=evidence_id,
            action="evidence_registered",
            metadata={
                "evidence_code": code,
                "source_file": resolved.name,
                "redaction_status": redaction_status,
                "storage_backend": storage_backend,
                "storage_key": storage_key,
                "byte_size": byte_size,
            },
            emit_outbox=True,
            outbox_event_type="evidence_registered",
            outbox_payload={"evidence_id": evidence_id},
        )
        return self.get(evidence_id)

    def requirement(
        self,
        *,
        object_type: str,
        object_id: str,
        requirement_code: str,
        description: str,
        workspace: str = "default",
        required_status: str = "Required",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update an evidence requirement."""

        require_permission(self.connection, actor_label=actor_label, permission="evidence.manage")
        workspace_id = ensure_workspace(self.connection, workspace)
        target_type = normalize_key(object_type, default="")
        target_id = normalize_key(object_id, default="")
        code = normalize_key(requirement_code, default="")
        if not target_type or not target_id or not code:
            raise PlatformError("Evidence requirement needs object type, object id, and requirement code.")
        requirement_id = platform_id("EVREQ", workspace_id, target_type, target_id, code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO evidence_requirements (
                    id, workspace_id, object_type, object_id, requirement_code,
                    description, required_status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, object_type, object_id, requirement_code)
                DO UPDATE SET
                    description = excluded.description,
                    required_status = excluded.required_status
                """,
                (
                    requirement_id,
                    workspace_id,
                    target_type,
                    target_id,
                    code,
                    normalize_text(description),
                    required_status,
                    now,
                ),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save evidence requirement.") from exc
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="evidence_requirement",
            object_id=requirement_id,
            action="evidence_requirement_saved",
            metadata={"target_type": target_type, "target_id": target_id, "requirement_code": code},
        )
        return dict(
            self.connection.execute("SELECT * FROM evidence_requirements WHERE id = ?", (requirement_id,)).fetchone(),
        )

    def link(
        self,
        evidence_id: str,
        *,
        object_type: str,
        object_id: str,
        link_type: str = "support",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Link evidence to a reconciliation, control, close task, approval, or other object."""

        require_permission(self.connection, actor_label=actor_label, permission="evidence.manage")
        self.get(evidence_id)
        link = self._insert_link(evidence_id, object_type=object_type, object_id=object_id, link_type=link_type)
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="evidence_link",
            object_id=link["id"],
            action="evidence_linked",
            metadata={"evidence_id": evidence_id, "target_type": object_type, "target_id": object_id},
        )
        return link

    def _insert_link(
        self,
        evidence_id: str,
        *,
        object_type: str,
        object_id: str,
        link_type: str,
    ) -> dict[str, Any]:
        """Insert a link without committing; the caller owns audit and transaction finalization."""

        target_type = normalize_key(object_type, default="")
        target_id = normalize_key(object_id, default="")
        if not target_type or not target_id:
            raise PlatformError("Evidence link needs object type and object id.")
        link_id = platform_id("EVL", evidence_id, target_type, target_id, link_type)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO evidence_links (
                    id, evidence_id, object_type, object_id, link_type, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (link_id, evidence_id, target_type, target_id, normalize_key(link_type, default="support"), now),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to link evidence.") from exc
        return {"id": link_id, "evidence_id": evidence_id, "object_type": target_type, "object_id": target_id}

    def verify(
        self,
        evidence_id: str,
        *,
        actor_label: str = "local-cli",
        object_store: EvidenceObjectStore | None = None,
    ) -> EvidenceVerification:
        """Verify evidence checksum against its configured storage backend."""

        require_permission(self.connection, actor_label=actor_label, permission="evidence.read")
        evidence = self.get(evidence_id)
        expected = str(evidence["checksum_sha256"])
        storage_backend = str(evidence.get("storage_backend") or LOCAL_STORAGE_BACKEND)
        if storage_backend == OBJECT_STORAGE_BACKEND:
            if object_store is None:
                raise PlatformError("This evidence requires its configured object-storage provider for verification.")
            storage_tenant = str(evidence.get("storage_tenant_id") or "")
            storage_key = str(evidence.get("storage_key") or "")
            if not storage_tenant or not storage_key:
                raise PlatformError("Object-backed evidence is missing its storage reference.")
            try:
                stored = object_store.get_bytes(storage_tenant, storage_key)
                actual = hashlib.sha256(stored.content).hexdigest()
                if actual != stored.sha256:
                    raise PlatformError("Object-storage content checksum verification failed.")
            except PlatformError:
                raise
            except Exception as exc:
                raise PlatformError("Unable to read evidence from configured object storage.") from exc
        else:
            try:
                actual = checksum_file(Path(str(evidence["source_path"])))
            except OSError as exc:
                raise PlatformError("Evidence file could not be read for checksum verification.") from exc
        ok = expected == actual
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="evidence",
            object_id=evidence_id,
            action="evidence_checksum_verified",
            metadata={"ok": ok, "source_file": Path(str(evidence["source_path"])).name},
            emit_outbox=True,
            outbox_event_type="evidence_checksum_verified",
            outbox_payload={"evidence_id": evidence_id, "ok": ok},
        )
        return EvidenceVerification(evidence_id=evidence_id, ok=ok, expected_sha256=expected, actual_sha256=actual)

    def coverage(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]:
        """Return evidence coverage by object and overall."""

        require_permission(self.connection, actor_label=actor_label, permission="evidence.read")
        workspace_id = ensure_workspace(self.connection, workspace)
        rows = self.connection.execute(
            """
            SELECT
                requirement.object_type,
                requirement.object_id,
                COUNT(requirement.id) AS requirement_count,
                COUNT(DISTINCT link.evidence_id) AS linked_evidence_count
            FROM evidence_requirements requirement
            LEFT JOIN evidence_links link
                ON link.object_type = requirement.object_type
               AND link.object_id = requirement.object_id
            WHERE requirement.workspace_id = ?
            GROUP BY requirement.object_type, requirement.object_id
            ORDER BY requirement.object_type, requirement.object_id
            """,
            (workspace_id,),
        ).fetchall()
        objects = rows_to_dicts(rows)
        requirement_total = sum(int(row["requirement_count"]) for row in objects)
        covered = sum(1 for row in objects if int(row["linked_evidence_count"]) > 0)
        coverage_pct = round((covered / len(objects)) * 100, 2) if objects else 100.0
        return {
            "workspace_id": workspace_id,
            "object_count": len(objects),
            "requirement_count": requirement_total,
            "covered_object_count": covered,
            "coverage_pct": coverage_pct,
            "objects": objects,
        }

    def list_evidence(self, *, status: str = "") -> list[dict[str, Any]]:
        """List evidence registry rows."""

        if status:
            rows = self.connection.execute(
                "SELECT * FROM evidence_registry WHERE evidence_status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM evidence_registry ORDER BY created_at DESC").fetchall()
        return rows_to_dicts(rows)

    def get(self, evidence_id: str) -> dict[str, Any]:
        """Read one evidence registry row."""

        row = self.connection.execute("SELECT * FROM evidence_registry WHERE id = ?", (evidence_id,)).fetchone()
        if row is None:
            raise PlatformError("Evidence record not found.")
        evidence = dict(row)
        evidence["links"] = rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM evidence_links WHERE evidence_id = ? ORDER BY created_at", (evidence_id,)
            ).fetchall(),
        )
        return evidence
