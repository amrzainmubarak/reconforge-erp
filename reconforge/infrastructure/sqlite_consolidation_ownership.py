"""SQLite persistence for approved, effective-dated consolidation ownership masters."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from reconforge.auth.rbac import same_actor
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_lifecycle import ConsolidationOwnershipInterest
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)
from reconforge.platform.inventory_values import clean_text, code

OWNERSHIP_READ_PERMISSION = "finance_core.read"
OWNERSHIP_MANAGE_PERMISSION = "finance_core.manage"


class SQLiteConsolidationOwnershipRepository:
    """Persist immutable ownership revisions and resolve them by reporting date."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        table = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='consolidation_ownership_interests'"
        ).fetchone()
        if table is None:
            raise PlatformError("Consolidation ownership schema is unavailable. Run 'reconforge db migrate' first.")

    def _actor(self, actor_label: str, permission: str) -> str:
        user = require_permission(self.connection, actor_label=actor_label, permission=permission)
        return user.username if user is not None else clean_text(actor_label, "Actor label")

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        return dict(zip(row.keys(), tuple(row), strict=True))

    def _rows(self, *, workspace_id: str, group_code: str, subsidiary: str | None = None) -> list[sqlite3.Row]:
        query = (
            "SELECT * FROM consolidation_ownership_interests "
            "WHERE workspace_id=? AND group_code=?"
        )
        parameters: list[object] = [workspace_id, group_code]
        if subsidiary is not None:
            query += " AND subsidiary_entity_code=?"
            parameters.append(subsidiary)
        query += " ORDER BY subsidiary_entity_code, effective_from, interest_id"
        return list(self.connection.execute(query, parameters).fetchall())

    @staticmethod
    def _validate_non_overlapping(rows: Sequence[sqlite3.Row], interest: ConsolidationOwnershipInterest) -> None:
        for row in rows:
            existing_from = str(row["effective_from"])
            existing_to = str(row["effective_to"])
            candidate_to = interest.effective_to
            if (not existing_to or interest.effective_from <= existing_to) and (
                not candidate_to or existing_from <= candidate_to
            ):
                raise PlatformError("Ownership effective-date intervals overlap for the subsidiary entity.")

    def save_interest(
        self,
        interest: ConsolidationOwnershipInterest,
        *,
        group_code: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label, OWNERSHIP_MANAGE_PERMISSION)
        if not isinstance(interest, ConsolidationOwnershipInterest):
            raise PlatformError("An approved consolidation ownership interest is required.")
        if not same_actor(interest.prepared_by, actor):
            raise PlatformError("The authenticated preparer must match the ownership preparer.")
        workspace_id = ensure_workspace(self.connection, clean_text(workspace, "Workspace name"))
        group = code(group_code, "Consolidation group code")
        identifier = platform_id("COI", workspace_id, group, interest.interest_id)
        existing = self.connection.execute(
            "SELECT * FROM consolidation_ownership_interests WHERE id=?", (identifier,)
        ).fetchone()
        material = {
            "interest_id": interest.interest_id,
            "parent_entity_code": interest.parent_entity_code,
            "subsidiary_entity_code": interest.subsidiary_entity_code,
            "direct_ownership_percentage": str(interest.direct_ownership_percentage),
            "effective_from": interest.effective_from,
            "effective_to": interest.effective_to,
            "version": interest.version,
            "source_digest": interest.source_digest,
            "prepared_by": interest.prepared_by,
            "approved_by": interest.approved_by,
            "approved_at": interest.approved_at,
        }
        if existing is not None:
            if any(str(existing[key]) != str(value) for key, value in material.items()):
                raise PlatformError("Ownership interest identifier conflicts with an immutable revision.")
            return self._public(existing)
        self._validate_non_overlapping(
            self._rows(
                workspace_id=workspace_id,
                group_code=group,
                subsidiary=interest.subsidiary_entity_code,
            ),
            interest,
        )
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO consolidation_ownership_interests(
                    id,workspace_id,group_code,interest_id,parent_entity_code,
                    subsidiary_entity_code,direct_ownership_percentage,effective_from,
                    effective_to,version,source_digest,prepared_by,approved_by,approved_at,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    identifier,
                    workspace_id,
                    group,
                    interest.interest_id,
                    interest.parent_entity_code,
                    interest.subsidiary_entity_code,
                    str(interest.direct_ownership_percentage),
                    interest.effective_from,
                    interest.effective_to,
                    interest.version,
                    interest.source_digest,
                    interest.prepared_by,
                    interest.approved_by,
                    interest.approved_at,
                    now,
                ),
            )
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="consolidation_ownership_interest",
                object_id=identifier,
                action="consolidation_ownership_interest_created",
                metadata={"group_code": group, "interest_id": interest.interest_id},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to persist the consolidation ownership interest.") from exc
        return self.get_interest(interest.interest_id, group_code=group, workspace=workspace, actor_label=actor)

    def get_interest(
        self,
        interest_id: str,
        *,
        group_code: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        self._actor(actor_label, OWNERSHIP_READ_PERMISSION)
        workspace_id = ensure_workspace(self.connection, clean_text(workspace, "Workspace name"))
        identifier = platform_id("COI", workspace_id, code(group_code, "Consolidation group code"), clean_text(interest_id, "Interest ID"))
        row = self.connection.execute(
            "SELECT * FROM consolidation_ownership_interests WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise PlatformError("Consolidation ownership interest was not found.")
        return self._public(row)

    def resolve_effective(
        self,
        *,
        group_code: str,
        reporting_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> tuple[ConsolidationOwnershipInterest, ...]:
        self._actor(actor_label, OWNERSHIP_READ_PERMISSION)
        workspace_id = ensure_workspace(self.connection, clean_text(workspace, "Workspace name"))
        group = code(group_code, "Consolidation group code")
        rows = self._rows(workspace_id=workspace_id, group_code=group)
        interests: list[ConsolidationOwnershipInterest] = []
        try:
            for row in rows:
                interest = ConsolidationOwnershipInterest(
                    interest_id=str(row["interest_id"]),
                    parent_entity_code=str(row["parent_entity_code"]),
                    subsidiary_entity_code=str(row["subsidiary_entity_code"]),
                    direct_ownership_percentage=Decimal(str(row["direct_ownership_percentage"])),
                    effective_from=str(row["effective_from"]),
                    effective_to=str(row["effective_to"]),
                    version=str(row["version"]),
                    source_digest=str(row["source_digest"]),
                    prepared_by=str(row["prepared_by"]),
                    approved_by=str(row["approved_by"]),
                    approved_at=str(row["approved_at"]),
                )
                if interest.is_effective(reporting_date):
                    interests.append(interest)
        except (ConsolidationError, ValueError) as exc:
            raise PlatformError("Persisted consolidation ownership failed deterministic replay.") from exc
        if not interests:
            raise PlatformError("No effective consolidation ownership interests were found.")
        by_subsidiary = {item.subsidiary_entity_code for item in interests}
        if len(by_subsidiary) != len(interests):
            raise PlatformError("More than one effective ownership interest exists for a subsidiary.")
        return tuple(interests)
