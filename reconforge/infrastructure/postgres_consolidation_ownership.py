"""Tenant-scoped PostgreSQL persistence for approved consolidation ownership masters."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_lifecycle import ConsolidationOwnershipInterest
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.platform.common import PlatformError, normalize_text, platform_id

POSTGRES_CONSOLIDATION_OWNERSHIP_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_ownership_interests (
 tenant_id TEXT NOT NULL,
 id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,
 group_code TEXT NOT NULL,
 interest_id TEXT NOT NULL,
 parent_entity_code TEXT NOT NULL,
 subsidiary_entity_code TEXT NOT NULL,
 direct_ownership_percentage NUMERIC NOT NULL,
 effective_from DATE NOT NULL,
 effective_to DATE,
 version TEXT NOT NULL,
 source_digest TEXT NOT NULL CHECK (length(source_digest)=64),
 prepared_by TEXT NOT NULL,
 approved_by TEXT NOT NULL,
 approved_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,workspace_id,group_code,interest_id),
 CHECK (parent_entity_code<>subsidiary_entity_code),
 CHECK (direct_ownership_percentage>0 AND direct_ownership_percentage<=1),
 CHECK (effective_to IS NULL OR effective_from<=effective_to),
 CHECK (prepared_by<>approved_by)
);
CREATE INDEX IF NOT EXISTS consolidation_ownership_scope_idx
 ON reconforge.consolidation_ownership_interests
 (tenant_id,workspace_id,group_code,subsidiary_entity_code,effective_from,effective_to);
CREATE OR REPLACE FUNCTION reconforge.consolidation_ownership_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' THEN RAISE EXCEPTION 'consolidation ownership interests are immutable'; END IF;
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'consolidation ownership interests cannot be deleted'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS consolidation_ownership_immutable ON reconforge.consolidation_ownership_interests;
CREATE TRIGGER consolidation_ownership_immutable BEFORE UPDATE OR DELETE
 ON reconforge.consolidation_ownership_interests FOR EACH ROW
 EXECUTE FUNCTION reconforge.consolidation_ownership_immutable_guard();
ALTER TABLE reconforge.consolidation_ownership_interests ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_ownership_interests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON reconforge.consolidation_ownership_interests;
CREATE POLICY tenant_isolation ON reconforge.consolidation_ownership_interests
 USING (tenant_id=current_setting('app.tenant_id',true))
 WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
"""


class PostgresConsolidationOwnershipError(RuntimeError):
    """Safe PostgreSQL ownership persistence failure."""


class PostgresConsolidationOwnershipRepository:
    """Persist immutable ownership revisions for one tenant."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    def _actor(self, actor_label: str) -> str:
        actor = normalize_text(actor_label, default="local-cli")
        if not actor:
            raise PlatformError("Ownership actor is required.")
        return actor

    def _rows(self, *, workspace_id: str, group_code: str, subsidiary: str) -> list[Any]:
        return list(
            self.connection.execute(
                """
                SELECT effective_from::text, COALESCE(effective_to::text,'')
                FROM reconforge.consolidation_ownership_interests
                WHERE tenant_id=%s AND workspace_id=%s AND group_code=%s AND subsidiary_entity_code=%s
                ORDER BY effective_from, interest_id
                FOR UPDATE
                """,
                (self.tenant_id, workspace_id, group_code, subsidiary),
            ).fetchall()
        )

    @staticmethod
    def _validate_non_overlapping(rows: Sequence[Any], interest: ConsolidationOwnershipInterest) -> None:
        for row in rows:
            existing_from, existing_to = str(row[0]), str(row[1])
            if (not existing_to or interest.effective_from <= existing_to) and (
                not interest.effective_to or existing_from <= interest.effective_to
            ):
                raise PlatformError("Ownership effective-date intervals overlap for the subsidiary entity.")

    @staticmethod
    def _from_row(row: Any) -> ConsolidationOwnershipInterest:
        try:
            return ConsolidationOwnershipInterest(
                interest_id=str(row["interest_id"]),
                parent_entity_code=str(row["parent_entity_code"]),
                subsidiary_entity_code=str(row["subsidiary_entity_code"]),
                direct_ownership_percentage=Decimal(str(row["direct_ownership_percentage"])),
                effective_from=str(row["effective_from"]),
                effective_to=str(row["effective_to"] or ""),
                version=str(row["version"]),
                source_digest=str(row["source_digest"]),
                prepared_by=str(row["prepared_by"]),
                approved_by=str(row["approved_by"]),
                approved_at=str(row["approved_at"]),
            )
        except (ConsolidationError, ValueError) as exc:
            raise PlatformError("Persisted PostgreSQL ownership failed deterministic replay.") from exc

    def save_interest(
        self,
        interest: ConsolidationOwnershipInterest,
        *,
        group_code: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        if not isinstance(interest, ConsolidationOwnershipInterest):
            raise PlatformError("An approved consolidation ownership interest is required.")
        actor = self._actor(actor_label)
        if actor != interest.prepared_by:
            raise PlatformError("The authenticated preparer must match the ownership preparer.")
        workspace_id, group = normalize_text(workspace, default=""), normalize_text(group_code, default="")
        if not workspace_id or not group:
            raise PlatformError("Ownership workspace and group are required.")
        identifier = platform_id("PGCOI", self.tenant_id, workspace_id, group, interest.interest_id)
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                existing = self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_ownership_interests WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, identifier),
                ).fetchone()
                if existing is not None:
                    replay = self._from_row(existing)
                    if replay != interest:
                        raise PlatformError("Ownership interest identifier conflicts with an immutable revision.")
                    return dict(existing)
                self._validate_non_overlapping(
                    self._rows(workspace_id=workspace_id, group_code=group, subsidiary=interest.subsidiary_entity_code),
                    interest,
                )
                self.connection.execute(
                    """
                    INSERT INTO reconforge.consolidation_ownership_interests(
                      tenant_id,id,workspace_id,group_code,interest_id,parent_entity_code,
                      subsidiary_entity_code,direct_ownership_percentage,effective_from,effective_to,
                      version,source_digest,prepared_by,approved_by,approved_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        self.tenant_id, identifier, workspace_id, group, interest.interest_id,
                        interest.parent_entity_code, interest.subsidiary_entity_code,
                        interest.direct_ownership_percentage, interest.effective_from,
                        interest.effective_to or None, interest.version, interest.source_digest,
                        interest.prepared_by, interest.approved_by, interest.approved_at,
                    ),
                )
                PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                    actor_label=actor,
                    object_type="consolidation_ownership_interest",
                    object_id=identifier,
                    action="consolidation_ownership_interest_created",
                    metadata={"workspace": workspace_id, "group_code": group, "interest_id": interest.interest_id},
                )
                return {"id": identifier, "tenant_id": self.tenant_id, "workspace_id": workspace_id, "group_code": group, "interest_id": interest.interest_id}
        except (PlatformError, PostgresConsolidationOwnershipError):
            raise
        except Exception as exc:
            raise PostgresConsolidationOwnershipError("PostgreSQL ownership operation failed.") from exc

    def resolve_effective(
        self,
        *,
        group_code: str,
        reporting_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> tuple[ConsolidationOwnershipInterest, ...]:
        self._actor(actor_label)
        workspace_id, group = normalize_text(workspace, default=""), normalize_text(group_code, default="")
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                rows = self.connection.execute(
                    """
                    SELECT * FROM reconforge.consolidation_ownership_interests
                    WHERE tenant_id=%s AND workspace_id=%s AND group_code=%s
                      AND effective_from<=%s::date AND (effective_to IS NULL OR effective_to>=%s::date)
                    ORDER BY subsidiary_entity_code, effective_from, interest_id
                    """,
                    (self.tenant_id, workspace_id, group, reporting_date, reporting_date),
                ).fetchall()
                interests = tuple(self._from_row(row) for row in rows)
                if not interests:
                    raise PlatformError("No effective consolidation ownership interests were found.")
                if len({item.subsidiary_entity_code for item in interests}) != len(interests):
                    raise PlatformError("More than one effective ownership interest exists for a subsidiary.")
                return interests
        except (PlatformError, PostgresConsolidationOwnershipError):
            raise
        except Exception as exc:
            raise PostgresConsolidationOwnershipError("PostgreSQL ownership operation failed.") from exc
