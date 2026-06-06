"""DB-backed evidence registry and coverage helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reconforge.db.exporter import checksum_file, resolve_input_file
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    audit,
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


class EvidenceRegistryService:
    """Local checksum/provenance evidence registry.

    Evidence integrity here is a checksum aid only. It is not a signature
    workflow or non-repudiation control.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

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
    ) -> dict[str, Any]:
        """Register a local evidence object and optionally link it to a workflow object."""

        require_permission(self.connection, actor_label=actor_label, permission="evidence.manage")
        resolved = resolve_input_file(source_path)
        workspace_id = ensure_workspace(self.connection, workspace)
        code = normalize_key(evidence_code, default=resolved.name)
        evidence_id = platform_id("EVDREG", workspace_id, code)
        checksum = checksum_file(resolved)
        now = utc_now_text()
        try:
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
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to register evidence.") from exc
        if object_type and object_id:
            self.link(evidence_id, object_type=object_type, object_id=object_id, link_type=link_type, actor_label=actor_label)
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="evidence",
            object_id=evidence_id,
            action="evidence_registered",
            metadata={"evidence_code": code, "source_file": resolved.name, "redaction_status": redaction_status},
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
                (requirement_id, workspace_id, target_type, target_id, code, normalize_text(description), required_status, now),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save evidence requirement.") from exc
        audit(
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
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to link evidence.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="evidence_link",
            object_id=link_id,
            action="evidence_linked",
            metadata={"evidence_id": evidence_id, "target_type": target_type, "target_id": target_id},
        )
        return {"id": link_id, "evidence_id": evidence_id, "object_type": target_type, "object_id": target_id}

    def verify(self, evidence_id: str, *, actor_label: str = "local-cli") -> EvidenceVerification:
        """Verify evidence checksum against the current local file."""

        require_permission(self.connection, actor_label=actor_label, permission="evidence.read")
        evidence = self.get(evidence_id)
        expected = str(evidence["checksum_sha256"])
        try:
            actual = checksum_file(Path(str(evidence["source_path"])))
        except OSError as exc:
            raise PlatformError("Evidence file could not be read for checksum verification.") from exc
        ok = expected == actual
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="evidence",
            object_id=evidence_id,
            action="evidence_checksum_verified",
            metadata={"ok": ok, "source_file": Path(str(evidence["source_path"])).name},
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
            self.connection.execute("SELECT * FROM evidence_links WHERE evidence_id = ? ORDER BY created_at", (evidence_id,)).fetchall(),
        )
        return evidence
