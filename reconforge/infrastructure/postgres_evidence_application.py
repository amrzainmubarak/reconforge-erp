"""Contract-compatible tenant/workspace PostgreSQL evidence registry."""

from __future__ import annotations

import hashlib
import mimetypes
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from reconforge.application.evidence import (
    LOCAL_STORAGE_BACKEND,
    OBJECT_STORAGE_BACKEND,
    EvidenceObjectStore,
    EvidenceVerification,
    HierarchicalEvidenceObjectStore,
)
from reconforge.db.exporter import checksum_file, resolve_input_file
from reconforge.infrastructure.object_storage import ObjectStorageScope
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError, normalize_key, normalize_text, platform_id

_DIRECTIONS = ("up", "down", "both")
_STATUSES = ("Available", "Quarantined", "Superseded")
_MAX_DEPTH = 8
_MAX_PAGE = 1_000
_MAX_NODES = 10_000

POSTGRES_EVIDENCE_APPLICATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.evidence_application_registry (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,evidence_code TEXT NOT NULL,
 source_path TEXT NOT NULL,checksum_sha256 TEXT NOT NULL,provenance_type TEXT NOT NULL,
 redaction_status TEXT NOT NULL,evidence_status TEXT NOT NULL DEFAULT 'Available'
 CHECK(evidence_status IN('Available','Quarantined','Superseded')),
 storage_backend TEXT NOT NULL DEFAULT 'local-filesystem'
 CHECK(storage_backend IN('local-filesystem','s3-compatible-object-storage')),
 storage_tenant_id TEXT NOT NULL DEFAULT '',storage_key TEXT NOT NULL DEFAULT '',
 storage_version_id TEXT NOT NULL DEFAULT '',content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
 byte_size BIGINT NOT NULL DEFAULT 0 CHECK(byte_size>=0),retention_until TIMESTAMPTZ,
 registered_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,workspace_id,evidence_code),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 CHECK(checksum_sha256 ~ '^[0-9a-f]{64}$'),
 CHECK((storage_backend='local-filesystem' AND storage_tenant_id='' AND storage_key='') OR
       (storage_backend='s3-compatible-object-storage' AND storage_tenant_id<>'' AND storage_key<>''))
);
CREATE TABLE IF NOT EXISTS reconforge.evidence_application_links (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,evidence_id TEXT NOT NULL,
 object_type TEXT NOT NULL,object_id TEXT NOT NULL,link_type TEXT NOT NULL DEFAULT 'support',
 created_by TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,evidence_id,object_type,object_id,link_type),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY(tenant_id,evidence_id) REFERENCES reconforge.evidence_application_registry(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS reconforge.evidence_application_requirements (
 tenant_id TEXT NOT NULL,id TEXT NOT NULL,workspace_id TEXT NOT NULL,object_type TEXT NOT NULL,
 object_id TEXT NOT NULL,requirement_code TEXT NOT NULL,description TEXT NOT NULL,
 required_status TEXT NOT NULL DEFAULT 'Required',created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 row_version BIGINT NOT NULL DEFAULT 1 CHECK(row_version>0),PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,workspace_id,object_type,object_id,requirement_code),
 FOREIGN KEY(tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS evidence_application_status_idx ON reconforge.evidence_application_registry
 (tenant_id,workspace_id,evidence_status,created_at DESC,id);
CREATE INDEX IF NOT EXISTS evidence_application_object_idx ON reconforge.evidence_application_links
 (tenant_id,workspace_id,object_type,object_id,evidence_id);

CREATE OR REPLACE FUNCTION reconforge.evidence_application_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='evidence_application_registry' THEN
  IF TG_OP='UPDATE' AND (NEW.workspace_id,NEW.evidence_code,NEW.source_path,NEW.checksum_sha256,
   NEW.storage_backend,NEW.storage_tenant_id,NEW.storage_key,NEW.storage_version_id,NEW.created_at)
   IS DISTINCT FROM (OLD.workspace_id,OLD.evidence_code,OLD.source_path,OLD.checksum_sha256,
   OLD.storage_backend,OLD.storage_tenant_id,OLD.storage_key,OLD.storage_version_id,OLD.created_at)
  THEN RAISE EXCEPTION 'evidence artifact identity is immutable'; END IF;
  IF TG_OP='DELETE' THEN RAISE EXCEPTION 'evidence records are append-only; supersede instead'; END IF;
 END IF;
 IF TG_TABLE_NAME='evidence_application_links' AND TG_OP IN('UPDATE','DELETE') THEN
  RAISE EXCEPTION 'evidence links are append-only';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS evidence_application_registry_guard ON reconforge.evidence_application_registry;
CREATE TRIGGER evidence_application_registry_guard BEFORE UPDATE OR DELETE ON reconforge.evidence_application_registry
 FOR EACH ROW EXECUTE FUNCTION reconforge.evidence_application_guard();
DROP TRIGGER IF EXISTS evidence_application_links_guard ON reconforge.evidence_application_links;
CREATE TRIGGER evidence_application_links_guard BEFORE UPDATE OR DELETE ON reconforge.evidence_application_links
 FOR EACH ROW EXECUTE FUNCTION reconforge.evidence_application_guard();

DO $rls$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['evidence_application_registry','evidence_application_links',
  'evidence_application_requirements'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY',table_name);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I',table_name);
  IF NOT EXISTS (
   SELECT 1 FROM pg_policies
   WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope'
  ) THEN
   EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))',table_name);
  END IF;
 END LOOP;
END $rls$;
"""


class PostgresEvidenceApplicationError(RuntimeError):
    """Safe persistence failure for the application evidence aggregate."""


def _choice(value: object, field: str, choices: tuple[str, ...]) -> str:
    raw = normalize_text(value, default="")
    for choice in choices:
        if raw.casefold() == choice.casefold():
            return choice
    raise PlatformError(f"{field} must be one of: {', '.join(choices)}.")


def _redacted(record: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(record)
    for field in (
        "source_path",
        "checksum_sha256",
        "storage_tenant_id",
        "storage_key",
        "storage_version_id",
        "content_type",
        "byte_size",
        "retention_until",
    ):
        if field in result:
            result[field] = "***redacted***"
    return result


class PostgresEvidenceRegistryRepository:
    """Implement the complete EvidenceRegistry Application port for one tenant."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresEvidenceApplicationError):
            raise
        except Exception as exc:
            raise PostgresEvidenceApplicationError("PostgreSQL evidence-registry operation failed.") from exc

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, normalize_text(workspace, default="default")),
        ).fetchone()
        if row is None:
            raise PlatformError("Workspace was not found for this tenant.")
        return str(row["id"])

    def _event(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        version: object,
        metadata: Mapping[str, object],
        emit_outbox: bool = True,
    ) -> None:
        actor = normalize_text(actor_label, default="local-cli")
        audit = PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=dict(metadata),
        )
        if not emit_outbox:
            return
        payload = {
            "audit_event_id": audit.id,
            "object_type": object_type,
            "object_id": object_id,
            "action": action,
            **dict(metadata),
        }
        try:
            encoded = encode_postgres_outbox_payload(payload).text
        except PersistedJsonError as exc:
            raise PlatformError("Unable to encode evidence-registry event.") from exc
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events(tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
            VALUES(%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT(tenant_id,event_id) DO NOTHING""",
            (self.tenant_id, platform_id("OBX", action, object_id, version), action, object_type, object_id, encoded),
        )

    def _record(self, evidence_id: str, *, lock: bool = False) -> dict[str, Any]:
        query = "SELECT * FROM reconforge.evidence_application_registry WHERE tenant_id=%s AND id=%s"
        if lock:
            query += " FOR UPDATE"
        row = self.connection.execute(query, (self.tenant_id, normalize_text(evidence_id, default=""))).fetchone()
        if row is None:
            raise PlatformError("Evidence record not found.")
        return dict(row)

    def _links(self, evidence_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT * FROM reconforge.evidence_application_links
            WHERE tenant_id=%s AND evidence_id=%s ORDER BY created_at,id LIMIT 10000""",
            (self.tenant_id, evidence_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _insert_link(
        self,
        *,
        evidence: Mapping[str, Any],
        object_type: str,
        object_id: str,
        link_type: str,
        actor_label: str,
    ) -> dict[str, Any]:
        target_type = normalize_key(object_type, default="")
        target_id = normalize_key(object_id, default="")
        selected_type = normalize_key(link_type, default="support")
        if not target_type or not target_id:
            raise PlatformError("Evidence link needs object type and object id.")
        link_id = platform_id("EVL", evidence["id"], target_type, target_id, selected_type)
        row = self.connection.execute(
            """INSERT INTO reconforge.evidence_application_links(
            tenant_id,id,workspace_id,evidence_id,object_type,object_id,link_type,created_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(tenant_id,evidence_id,object_type,object_id,link_type) DO NOTHING
            RETURNING *""",
            (
                self.tenant_id,
                link_id,
                evidence["workspace_id"],
                evidence["id"],
                target_type,
                target_id,
                selected_type,
                normalize_text(actor_label, default="local-cli"),
            ),
        ).fetchone()
        if row is None:
            row = self.connection.execute(
                "SELECT * FROM reconforge.evidence_application_links WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, link_id),
            ).fetchone()
        if row is None:
            raise PlatformError("Unable to link evidence.")
        return dict(row)

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
        resolved = resolve_input_file(source_path)
        content: bytes | None = None
        checksum = checksum_file(resolved)
        backend = LOCAL_STORAGE_BACKEND
        storage_tenant = ""
        storage_key = ""
        storage_version = ""
        selected_content_type = "application/octet-stream"
        byte_size = 0
        if object_store is None:
            if storage_tenant_id or storage_object_name or retention_until is not None:
                raise PlatformError("Object-storage options require an explicitly configured object store.")
        else:
            content = resolved.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            backend = OBJECT_STORAGE_BACKEND
            byte_size = len(content)
            storage_tenant = validate_tenant_id(storage_tenant_id or self.tenant_id)
            if storage_tenant != self.tenant_id:
                raise PlatformError("Object storage tenant must match the repository tenant.")
            selected_content_type = (
                content_type.strip() or mimetypes.guess_type(resolved.name)[0] or selected_content_type
            )
        status = _choice(evidence_status, "Evidence status", _STATUSES)
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            code = normalize_key(evidence_code, default=resolved.name)
            evidence_id = platform_id("EVDREG", workspace_id, code)
            if object_store is not None:
                storage_key = (
                    storage_object_name.strip() or f"evidence/{evidence_id}/{checksum}{resolved.suffix.lower()}"
                )
            existing = self.connection.execute(
                """SELECT * FROM reconforge.evidence_application_registry
                WHERE tenant_id=%s AND workspace_id=%s AND evidence_code=%s FOR UPDATE""",
                (self.tenant_id, workspace_id, code),
            ).fetchone()
            if existing is not None:
                current = dict(existing)
                identity = (checksum, str(resolved), backend, storage_tenant, storage_key)
                persisted = tuple(
                    str(current[field] or "")
                    for field in (
                        "checksum_sha256",
                        "source_path",
                        "storage_backend",
                        "storage_tenant_id",
                        "storage_key",
                    )
                )
                if tuple(str(value or "") for value in identity) != persisted:
                    raise PlatformError("Evidence code already identifies a different immutable artifact.")
                self.connection.execute(
                    """UPDATE reconforge.evidence_application_registry SET provenance_type=%s,
                    redaction_status=%s,evidence_status=%s,content_type=%s,byte_size=%s,
                    retention_until=%s,registered_by=%s,updated_at=now(),row_version=row_version+1
                    WHERE tenant_id=%s AND id=%s RETURNING row_version""",
                    (
                        normalize_key(provenance_type, default="local-file"),
                        normalize_key(redaction_status, default="unknown"),
                        status,
                        selected_content_type,
                        byte_size,
                        retention_until,
                        normalize_text(actor_label, default="local-cli"),
                        self.tenant_id,
                        evidence_id,
                    ),
                ).fetchone()
            else:
                if object_store is not None and content is not None:
                    try:
                        storage_scope = ObjectStorageScope(
                            tenant_id=storage_tenant,
                            workspace_id=workspace_id,
                        )
                        hierarchical = bool(
                            getattr(object_store, "supports_hierarchical_scope", False)
                        )
                        if hierarchical:
                            stored = cast(
                                HierarchicalEvidenceObjectStore, object_store
                            ).put_bytes(
                                storage_scope,
                                storage_key,
                                content,
                                content_type=selected_content_type,
                                metadata={"evidence-id": evidence_id, "source-name": resolved.name},
                                retention_until=retention_until,
                            )
                        else:
                            stored = object_store.put_bytes(
                                storage_tenant,
                                storage_key,
                                content,
                                content_type=selected_content_type,
                                metadata={"evidence-id": evidence_id, "source-name": resolved.name},
                                retention_until=retention_until,
                            )
                    except Exception as exc:
                        raise PlatformError("Unable to store evidence artifact in configured object storage.") from exc
                    actual = hashlib.sha256(stored.content).hexdigest()
                    if stored.sha256 != actual or actual != checksum:
                        raise PlatformError("Stored evidence checksum did not match the source content.")
                    if str(stored.metadata.get("reconforge-tenant", storage_tenant)) != storage_tenant:
                        raise PlatformError("Object storage returned an unexpected tenant scope.")
                    if hierarchical and str(
                        stored.metadata.get("reconforge-workspace", "")
                    ) != storage_scope.workspace_id:
                        raise PlatformError("Object storage returned an unexpected workspace scope.")
                    storage_version = stored.version_id or ""
                self.connection.execute(
                    """INSERT INTO reconforge.evidence_application_registry(
                    tenant_id,id,workspace_id,evidence_code,source_path,checksum_sha256,provenance_type,
                    redaction_status,evidence_status,storage_backend,storage_tenant_id,storage_key,
                    storage_version_id,content_type,byte_size,retention_until,registered_by)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        self.tenant_id,
                        evidence_id,
                        workspace_id,
                        code,
                        str(resolved),
                        checksum,
                        normalize_key(provenance_type, default="local-file"),
                        normalize_key(redaction_status, default="unknown"),
                        status,
                        backend,
                        storage_tenant,
                        storage_key,
                        storage_version,
                        selected_content_type,
                        byte_size,
                        retention_until,
                        normalize_text(actor_label, default="local-cli"),
                    ),
                )
            record = self._record(evidence_id)
            if object_type and object_id:
                link = self._insert_link(
                    evidence=record,
                    object_type=object_type,
                    object_id=object_id,
                    link_type=link_type,
                    actor_label=actor_label,
                )
                self._event(
                    actor_label=actor_label,
                    object_type="evidence_link",
                    object_id=str(link["id"]),
                    action="evidence_linked",
                    version=link["created_at"],
                    metadata={
                        "evidence_id": evidence_id,
                        "target_type": link["object_type"],
                        "target_id": link["object_id"],
                    },
                )
            self._event(
                actor_label=actor_label,
                object_type="evidence",
                object_id=evidence_id,
                action="evidence_registered",
                version=record["row_version"],
                metadata={
                    "evidence_code": code,
                    "storage_backend": backend,
                    "source_file": resolved.name,
                    "byte_size": byte_size,
                },
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
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            target_type = normalize_key(object_type, default="")
            target_id = normalize_key(object_id, default="")
            code = normalize_key(requirement_code, default="")
            if not target_type or not target_id or not code:
                raise PlatformError("Evidence requirement needs object type, object id, and requirement code.")
            requirement_id = platform_id("EVREQ", workspace_id, target_type, target_id, code)
            row = self.connection.execute(
                """INSERT INTO reconforge.evidence_application_requirements(
                tenant_id,id,workspace_id,object_type,object_id,requirement_code,description,
                required_status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(tenant_id,workspace_id,object_type,object_id,requirement_code)
                DO UPDATE SET description=EXCLUDED.description,required_status=EXCLUDED.required_status,
                updated_at=now(),row_version=reconforge.evidence_application_requirements.row_version+1
                RETURNING *""",
                (
                    self.tenant_id,
                    requirement_id,
                    workspace_id,
                    target_type,
                    target_id,
                    code,
                    normalize_text(description, default=""),
                    normalize_text(required_status, default="Required"),
                    normalize_text(actor_label, default="local-cli"),
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Unable to save evidence requirement.")
            result = dict(row)
            self._event(
                actor_label=actor_label,
                object_type="evidence_requirement",
                object_id=requirement_id,
                action="evidence_requirement_saved",
                version=result["row_version"],
                metadata={"target_type": target_type, "target_id": target_id, "requirement_code": code},
                emit_outbox=False,
            )
            return result

    def link(
        self,
        evidence_id: str,
        *,
        object_type: str,
        object_id: str,
        link_type: str = "support",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            evidence = self._record(evidence_id, lock=True)
            link = self._insert_link(
                evidence=evidence,
                object_type=object_type,
                object_id=object_id,
                link_type=link_type,
                actor_label=actor_label,
            )
            self._event(
                actor_label=actor_label,
                object_type="evidence_link",
                object_id=str(link["id"]),
                action="evidence_linked",
                version=link["created_at"],
                metadata={
                    "evidence_id": evidence_id,
                    "target_type": link["object_type"],
                    "target_id": link["object_id"],
                },
                emit_outbox=False,
            )
            return link

    def verify(
        self,
        evidence_id: str,
        *,
        actor_label: str = "local-cli",
        object_store: EvidenceObjectStore | None = None,
    ) -> EvidenceVerification:
        with self._transaction():
            evidence = self._record(evidence_id, lock=True)
            expected = str(evidence["checksum_sha256"])
            if evidence["storage_backend"] == OBJECT_STORAGE_BACKEND:
                if object_store is None:
                    raise PlatformError(
                        "This evidence requires its configured object-storage provider for verification."
                    )
                try:
                    storage_scope = ObjectStorageScope(
                        tenant_id=str(evidence["storage_tenant_id"]),
                        workspace_id=str(evidence["workspace_id"]),
                    )
                    if bool(getattr(object_store, "supports_hierarchical_scope", False)):
                        stored = cast(
                            HierarchicalEvidenceObjectStore, object_store
                        ).get_bytes(storage_scope, str(evidence["storage_key"]))
                    else:
                        stored = object_store.get_bytes(
                            storage_scope.tenant_id, str(evidence["storage_key"])
                        )
                    actual = hashlib.sha256(stored.content).hexdigest()
                except PlatformError:
                    raise
                except Exception as exc:
                    raise PlatformError("Unable to read evidence from configured object storage.") from exc
                if actual != stored.sha256:
                    raise PlatformError("Object-storage content checksum verification failed.")
            else:
                try:
                    actual = checksum_file(Path(str(evidence["source_path"])))
                except OSError as exc:
                    raise PlatformError("Evidence file could not be read for checksum verification.") from exc
            ok = expected == actual
            self._event(
                actor_label=actor_label,
                object_type="evidence",
                object_id=evidence_id,
                action="evidence_checksum_verified",
                version=platform_id("VERIFY", evidence_id, actual),
                metadata={"evidence_id": evidence_id, "ok": ok},
            )
            return EvidenceVerification(evidence_id, ok, expected, actual)

    def coverage(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, Any]:
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            rows = self.connection.execute(
                """SELECT r.object_type,r.object_id,COUNT(r.id) AS requirement_count,
                COUNT(DISTINCT l.evidence_id) AS linked_evidence_count
                FROM reconforge.evidence_application_requirements r
                LEFT JOIN reconforge.evidence_application_links l ON l.tenant_id=r.tenant_id
                 AND l.workspace_id=r.workspace_id AND l.object_type=r.object_type AND l.object_id=r.object_id
                WHERE r.tenant_id=%s AND r.workspace_id=%s GROUP BY r.object_type,r.object_id
                ORDER BY r.object_type,r.object_id LIMIT 10000""",
                (self.tenant_id, workspace_id),
            ).fetchall()
            objects = [dict(row) for row in rows]
            covered = sum(1 for row in objects if int(row["linked_evidence_count"]) > 0)
            return {
                "workspace_id": workspace_id,
                "object_count": len(objects),
                "requirement_count": sum(int(row["requirement_count"]) for row in objects),
                "covered_object_count": covered,
                "coverage_pct": round((covered / len(objects)) * 100, 2) if objects else 100.0,
                "objects": objects,
            }

    def list_evidence(self, *, status: str = "") -> list[dict[str, Any]]:
        with self._transaction():
            params: tuple[object, ...] = (self.tenant_id,)
            query = "SELECT * FROM reconforge.evidence_application_registry WHERE tenant_id=%s"
            if status:
                query += " AND evidence_status=%s"
                params = (self.tenant_id, _choice(status, "Evidence status", _STATUSES))
            query += " ORDER BY created_at DESC,id LIMIT 10000"
            return [dict(row) for row in self.connection.execute(query, params).fetchall()]

    def get(self, evidence_id: str) -> dict[str, Any]:
        with self._transaction():
            result = self._record(evidence_id)
            result["links"] = self._links(str(result["id"]))
            return result

    def drill_down(
        self,
        evidence_id: str,
        *,
        direction: str = "both",
        max_depth: int = 2,
        include_sensitive: bool = False,
        limit: int = 250,
        offset: int = 0,
        actor_label: str = "",
    ) -> dict[str, Any]:
        selected_direction = _choice(direction, "Evidence drill-down direction", _DIRECTIONS)
        if not 1 <= int(max_depth) <= _MAX_DEPTH:
            raise PlatformError("Evidence drill-down depth must be between 1 and 8.")
        if not 1 <= int(limit) <= _MAX_PAGE:
            raise PlatformError("Evidence drill-down limit must be between 1 and 1000.")
        if not 0 <= int(offset) <= 10_000_000:
            raise PlatformError("Evidence drill-down offset must be between 0 and 10000000.")
        with self._transaction():
            root = self._record(evidence_id)
            root_id = str(root["id"])
            nodes: dict[str, dict[str, Any]] = {
                root_id: {
                    "node_type": "evidence",
                    "id": root_id,
                    "record": root if include_sensitive else _redacted(root),
                    "depth": 0,
                }
            }
            edges: dict[tuple[str, ...], dict[str, Any]] = {}
            queue: deque[tuple[str, int]] = deque([(root_id, 0)])
            visited = {root_id}
            while queue:
                current, depth = queue.popleft()
                if depth >= int(max_depth):
                    continue
                for link in self._links(current):
                    object_node = f"object:{link['object_type']}:{link['object_id']}"
                    if object_node not in nodes:
                        if len(nodes) >= _MAX_NODES:
                            raise PlatformError("Evidence drill-down graph exceeds the 10000-node safety ceiling.")
                        nodes[object_node] = {
                            "node_type": "governed_object",
                            "id": object_node,
                            "object_type": link["object_type"],
                            "object_id": link["object_id"],
                            "depth": depth + 1,
                        }
                    edge = {
                        "from": current,
                        "to": object_node,
                        "relationship": "evidence:linked-object",
                        "direction": "down",
                        "link_type": link["link_type"],
                        "object_link_id": link["id"],
                        "depth": depth + 1,
                    }
                    edges[(str(edge["from"]), str(edge["to"]), str(edge["object_link_id"]))] = edge
                    if selected_direction == "down":
                        continue
                    peers = self.connection.execute(
                        """SELECT * FROM reconforge.evidence_application_links WHERE tenant_id=%s
                        AND workspace_id=%s AND object_type=%s AND object_id=%s
                        ORDER BY evidence_id,created_at,id LIMIT 10000""",
                        (self.tenant_id, link["workspace_id"], link["object_type"], link["object_id"]),
                    ).fetchall()
                    for peer_link in peers:
                        peer = dict(peer_link)
                        peer_id = str(peer["evidence_id"])
                        if peer_id == current:
                            continue
                        up = {
                            "from": object_node,
                            "to": peer_id,
                            "relationship": "object:linked-evidence",
                            "direction": "up",
                            "link_type": peer["link_type"],
                            "object_link_id": peer["id"],
                            "depth": depth + 1,
                        }
                        edges[(str(up["from"]), str(up["to"]), str(up["object_link_id"]))] = up
                        if peer_id not in visited:
                            if len(nodes) >= _MAX_NODES:
                                raise PlatformError("Evidence drill-down graph exceeds the 10000-node safety ceiling.")
                            visited.add(peer_id)
                            peer_record = self._record(peer_id)
                            nodes[peer_id] = {
                                "node_type": "evidence",
                                "id": peer_id,
                                "record": peer_record if include_sensitive else _redacted(peer_record),
                                "depth": depth + 1,
                            }
                            queue.append((peer_id, depth + 1))
            ordered_nodes = sorted(nodes.values(), key=lambda node: (int(node["depth"]), str(node["id"])))
            ordered_edges = sorted(
                edges.values(),
                key=lambda edge: (int(edge["depth"]), str(edge["from"]), str(edge["to"]), str(edge["object_link_id"])),
            )
            page_nodes = ordered_nodes[int(offset) : int(offset) + int(limit)]
            page_ids = {str(node["id"]) for node in page_nodes}
            page_edges = [
                edge for edge in ordered_edges if str(edge["from"]) in page_ids or str(edge["to"]) in page_ids
            ]
            next_offset = int(offset) + len(page_nodes)
            result = {
                "evidence_id": root_id,
                "direction": selected_direction,
                "max_depth": int(max_depth),
                "include_sensitive": bool(include_sensitive),
                "nodes": page_nodes,
                "edges": page_edges,
                "nodes_count": len(ordered_nodes),
                "edges_count": len(ordered_edges),
                "pagination": {
                    "limit": int(limit),
                    "offset": int(offset),
                    "returned_nodes": len(page_nodes),
                    "returned_incident_edges": len(page_edges),
                    "next_offset": next_offset if next_offset < len(ordered_nodes) else None,
                    "edge_scope": "incident-to-returned-nodes",
                },
            }
            if actor_label:
                self._event(
                    actor_label=actor_label,
                    object_type="evidence",
                    object_id=root_id,
                    action="evidence_drill_down_viewed",
                    version=platform_id("VIEW", root_id, selected_direction, max_depth, limit, offset),
                    metadata={
                        "direction": selected_direction,
                        "max_depth": int(max_depth),
                        "include_sensitive": bool(include_sensitive),
                        "limit": int(limit),
                        "offset": int(offset),
                        "returned_nodes": len(page_nodes),
                    },
                    emit_outbox=False,
                )
            return result
