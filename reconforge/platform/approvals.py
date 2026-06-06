"""Approval and certification metadata workflows."""

from __future__ import annotations

import sqlite3
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    audit,
    ensure_platform_schema,
    normalize_key,
    normalize_text,
    platform_id,
    require_permission,
    rows_to_dicts,
)


class ApprovalService:
    """Local approval requests and certification metadata.

    These records are workflow metadata only. They are not legal signatures,
    audit opinions, or compliance certifications.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def submit(
        self,
        *,
        object_type: str,
        object_id: str,
        title: str,
        assigned_to: str,
        requested_by: str = "",
        reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Submit a local approval request."""

        require_permission(self.connection, actor_label=actor_label, permission="approval.submit")
        requester = normalize_text(requested_by, default=actor_label)
        target_type = normalize_key(object_type, default="")
        target_id = normalize_key(object_id, default="")
        if not target_type or not target_id:
            raise PlatformError("Approval object type and id are required.")
        approval_id = platform_id("APR", target_type, target_id, title, assigned_to)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO approval_requests (
                    id, object_type, object_id, title, requested_by, assigned_to,
                    status, reason, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'Submitted', ?, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET
                    assigned_to = excluded.assigned_to,
                    status = 'Submitted',
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (
                    approval_id,
                    target_type,
                    target_id,
                    normalize_text(title, default=f"{target_type} approval"),
                    requester,
                    normalize_text(assigned_to),
                    reason,
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to submit approval request.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="approval_request",
            object_id=approval_id,
            action="approval_submitted",
            metadata={"target_type": target_type, "target_id": target_id, "assigned_to": assigned_to},
        )
        return self.get(approval_id)

    def approve(
        self,
        approval_id: str,
        *,
        actor_label: str = "local-cli",
        reason: str = "",
        override_reason: str = "",
    ) -> dict[str, Any]:
        """Approve a local request, enforcing basic SoD unless an override reason is supplied."""

        return self._decide(approval_id, status="Approved", actor_label=actor_label, reason=reason, override_reason=override_reason)

    def reject(self, approval_id: str, *, actor_label: str = "local-cli", reason: str) -> dict[str, Any]:
        """Reject a local request with a required reason."""

        if not normalize_text(reason):
            raise PlatformError("Rejection reason is required.")
        return self._decide(approval_id, status="Rejected", actor_label=actor_label, reason=reason, override_reason="")

    def prepare_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        period_name: str = "",
        entity_code: str = "",
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Prepare certification workflow metadata for review."""

        require_permission(self.connection, actor_label=actor_label, permission="approval.submit")
        return self._upsert_certification(
            object_type=object_type,
            object_id=object_id,
            status="Prepared",
            period_name=period_name,
            entity_code=entity_code,
            prepared_by=actor_label,
            reviewed_by="",
            note=note,
            actor_label=actor_label,
            action="certification_prepared",
        )

    def review_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Review certification workflow metadata."""

        require_permission(self.connection, actor_label=actor_label, permission="approval.approve")
        existing = self._certification_by_object(object_type, object_id)
        if normalize_text(existing.get("prepared_by")).lower() == normalize_text(actor_label).lower() and actor_label:
            raise PlatformError("Separation of duties conflict: preparer and reviewer must be different.")
        return self._upsert_certification(
            object_type=object_type,
            object_id=object_id,
            status="Reviewed",
            period_name=str(existing.get("period_name", "")),
            entity_code=str(existing.get("entity_code", "")),
            prepared_by=str(existing.get("prepared_by", "")),
            reviewed_by=actor_label,
            note=note or str(existing.get("note", "")),
            actor_label=actor_label,
            action="certification_reviewed",
        )

    def list_requests(self, *, status: str = "") -> list[dict[str, Any]]:
        """List approval requests."""

        if status:
            rows = self.connection.execute(
                "SELECT * FROM approval_requests WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM approval_requests ORDER BY created_at DESC").fetchall()
        return rows_to_dicts(rows)

    def list_certifications(self) -> list[dict[str, Any]]:
        """List certification metadata records."""

        return rows_to_dicts(self.connection.execute("SELECT * FROM certification_records ORDER BY updated_at DESC").fetchall())

    def get(self, approval_id: str) -> dict[str, Any]:
        """Read one approval request."""

        row = self.connection.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            raise PlatformError("Approval request not found.")
        return dict(row)

    def _decide(
        self,
        approval_id: str,
        *,
        status: str,
        actor_label: str,
        reason: str,
        override_reason: str,
    ) -> dict[str, Any]:
        require_permission(self.connection, actor_label=actor_label, permission="approval.approve")
        current = self.get(approval_id)
        requester = normalize_text(current.get("requested_by")).lower()
        actor = normalize_text(actor_label).lower()
        if requester and requester == actor and not normalize_text(override_reason):
            raise PlatformError("Approval SoD override reason is required when requester and approver are the same.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                UPDATE approval_requests
                SET status = ?, decision_reason = ?, override_reason = ?, decided_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, reason, override_reason, actor_label, now, approval_id),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to update approval request.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="approval_request",
            object_id=approval_id,
            action=f"approval_{status.lower()}",
            metadata={"status": status, "override_used": bool(override_reason), "reason_required": status == "Rejected"},
        )
        return self.get(approval_id)

    def _upsert_certification(
        self,
        *,
        object_type: str,
        object_id: str,
        status: str,
        period_name: str,
        entity_code: str,
        prepared_by: str,
        reviewed_by: str,
        note: str,
        actor_label: str,
        action: str,
    ) -> dict[str, Any]:
        target_type = normalize_key(object_type, default="")
        target_id = normalize_key(object_id, default="")
        if not target_type or not target_id:
            raise PlatformError("Certification object type and id are required.")
        certification_id = platform_id("CERT", target_type, target_id)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO certification_records (
                    id, object_type, object_id, period_name, entity_code, status,
                    prepared_by, reviewed_by, note, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(object_type, object_id)
                DO UPDATE SET
                    period_name = excluded.period_name,
                    entity_code = excluded.entity_code,
                    status = excluded.status,
                    prepared_by = excluded.prepared_by,
                    reviewed_by = excluded.reviewed_by,
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (certification_id, target_type, target_id, period_name, entity_code, status, prepared_by, reviewed_by, note, now, now),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to update certification metadata.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="certification_metadata",
            object_id=certification_id,
            action=action,
            metadata={"target_type": target_type, "target_id": target_id, "status": status},
        )
        return self._certification_by_object(target_type, target_id)

    def _certification_by_object(self, object_type: str, object_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM certification_records WHERE object_type = ? AND object_id = ?",
            (object_type, object_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Certification metadata not found.")
        return dict(row)
