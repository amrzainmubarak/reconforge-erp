"""Tenant-scoped PostgreSQL control-journal persistence for consolidation close.

This adapter deliberately persists the verified worksheet and lifecycle effects as
canonical JSONB.  It is a control ledger boundary; it is not an ERP write-back or
statutory consolidation posting engine.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_lifecycle import (
    ConsolidationWorksheetResult,
    verify_consolidation_worksheet_payload,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.platform.common import PlatformError, normalize_text, platform_id

POSTGRES_CONSOLIDATION_CLOSE_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_periods (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, group_code TEXT NOT NULL,
 period_name TEXT NOT NULL, reporting_currency TEXT NOT NULL, period_start_date DATE NOT NULL,
 period_end_date DATE NOT NULL, reporting_date DATE NOT NULL, status TEXT NOT NULL DEFAULT 'Open',
 row_version INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,workspace_id,group_code,period_name), CHECK (status IN ('Open','Locked')),
 CHECK (period_start_date<=reporting_date AND reporting_date<=period_end_date)
);
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_runs (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, period_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 run_number TEXT NOT NULL, worksheet_payload JSONB NOT NULL, worksheet_digest TEXT NOT NULL,
 journal_digest TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Prepared', row_version INTEGER NOT NULL DEFAULT 1,
 prepared_by TEXT NOT NULL, approved_by TEXT, posted_by TEXT, reversal_requested_by TEXT, reversed_by TEXT,
 prepared_at TIMESTAMPTZ NOT NULL DEFAULT now(), approved_at TIMESTAMPTZ, posted_at TIMESTAMPTZ,
 reversal_requested_at TIMESTAMPTZ, reversed_at TIMESTAMPTZ, reasons JSONB NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,period_id,run_number),
 CHECK (status IN ('Prepared','Approved','Posted','ReversalPrepared','Reversed'))
);
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_effects (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, run_id TEXT NOT NULL, effect_type TEXT NOT NULL,
 actor TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), effect_digest TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,run_id,effect_type)
);
CREATE TABLE IF NOT EXISTS reconforge.consolidation_close_period_events (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, period_id TEXT NOT NULL, action TEXT NOT NULL,
 actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE INDEX IF NOT EXISTS consolidation_close_runs_scope_idx ON reconforge.consolidation_close_runs(tenant_id,workspace_id,status);
ALTER TABLE reconforge.consolidation_close_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_periods FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_effects ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_effects FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_period_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.consolidation_close_period_events FORCE ROW LEVEL SECURITY;
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['consolidation_close_periods','consolidation_close_runs','consolidation_close_effects','consolidation_close_period_events'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON reconforge.%I', t);
 EXECUTE format('CREATE POLICY tenant_isolation ON reconforge.%I USING (tenant_id=current_setting(''app.tenant_id'',true)) WITH CHECK (tenant_id=current_setting(''app.tenant_id'',true))', t);
 END LOOP; END $$;
"""


class PostgresConsolidationCloseRepository:
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @staticmethod
    def _actor(value: str) -> str:
        actor = normalize_text(value, default="")
        if not actor:
            raise PlatformError("Consolidation actor is required.")
        return actor

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)

    def _scope(self) -> None:
        set_local_tenant_scope(self.connection, self.tenant_id)

    def create_period(
        self,
        *,
        group_code: str,
        period_id: str,
        reporting_currency: str,
        period_start_date: str,
        period_end_date: str,
        reporting_date: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        workspace = normalize_text(workspace, default="default")
        group_code = normalize_text(group_code, default="")
        period_id = normalize_text(period_id, default="")
        if not group_code or not period_id or not reporting_currency:
            raise PlatformError("Consolidation period fields are required.")
        identifier = platform_id("PGCCP", self.tenant_id, workspace, group_code, period_id)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, identifier),
            ).fetchone()
            if row:
                return dict(row)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_periods(tenant_id,id,workspace_id,group_code,period_name,reporting_currency,period_start_date,period_end_date,reporting_date,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.tenant_id,
                    identifier,
                    workspace,
                    group_code,
                    period_id,
                    reporting_currency,
                    period_start_date,
                    period_end_date,
                    reporting_date,
                    actor,
                ),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, identifier),
                ).fetchone()
            )

    def prepare_run(
        self,
        *,
        run_number: str,
        worksheet: ConsolidationWorksheetResult,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        if not isinstance(worksheet, ConsolidationWorksheetResult):
            raise PlatformError("A verified consolidation worksheet is required.")
        try:
            verified = verify_consolidation_worksheet_payload(worksheet.to_dict())
        except ConsolidationError as exc:
            raise PlatformError("Consolidation worksheet replay failed before persistence.") from exc
        if verified.prepared_by != actor or verified.posting_effect != "none":
            raise PlatformError("Worksheet preparation policy rejected the actor or posting effect.")
        period_id = platform_id("PGCCP", self.tenant_id, workspace, verified.group_code, verified.period_id)
        run_id = platform_id("PGCGR", self.tenant_id, workspace, verified.group_code, verified.period_id, run_number)
        payload = verified.to_dict()
        digest = hashlib.sha256(self._json(payload).encode()).hexdigest()
        with self.connection.transaction():
            self._scope()
            period = self.connection.execute(
                "SELECT status FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, period_id),
            ).fetchone()
            if not period:
                raise PlatformError("Consolidation period does not exist.")
            if str(period[0]) == "Locked":
                raise PlatformError("A locked consolidation period cannot accept a new run.")
            existing = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, run_id),
            ).fetchone()
            if existing:
                return dict(existing)
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_runs(tenant_id,id,period_id,workspace_id,run_number,worksheet_payload,worksheet_digest,journal_digest,prepared_by) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
                (
                    self.tenant_id,
                    run_id,
                    period_id,
                    workspace,
                    run_number,
                    self._json(payload),
                    digest,
                    verified.result_digest,
                    actor,
                ),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, run_id),
                ).fetchone()
            )

    def _transition(
        self,
        run_id: str,
        expected_version: int,
        from_status: str,
        to_status: str,
        reason: str,
        actor_label: str,
        actor_field: str,
        effect_kind: str | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(actor_label)
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s FOR UPDATE",
                (self.tenant_id, run_id),
            ).fetchone()
            if not row or row["status"] != from_status or int(row["row_version"]) != expected_version:
                raise PlatformError("Consolidation run changed concurrently or has an invalid state.")
            if (
                actor == row["prepared_by"]
                or actor == row["approved_by"]
                or (actor_field in {"reversed_by"} and actor == row["posted_by"])
            ):
                raise PlatformError("Maker-checker actor separation rejected the transition.")
            if effect_kind:
                effect_id = platform_id("PGCCE", self.tenant_id, run_id, effect_kind)
                effect_digest = hashlib.sha256(f"{run_id}:{effect_kind}".encode()).hexdigest()
                self.connection.execute(
                    "INSERT INTO reconforge.consolidation_close_effects(tenant_id,id,run_id,effect_type,actor,effect_digest) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (self.tenant_id, effect_id, run_id, effect_kind, actor, effect_digest),
                )
            self.connection.execute(
                f"UPDATE reconforge.consolidation_close_runs SET status=%s,row_version=row_version+1,{actor_field}=%s,reasons=jsonb_set(reasons,%s,to_jsonb(%s::text),true) WHERE tenant_id=%s AND id=%s",  # nosec B608
                (to_status, actor, "{" + to_status.lower() + "_reason}", reason, self.tenant_id, run_id),
            )
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, run_id),
                ).fetchone()
            )

    def approve_run(
        self, run_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._transition(run_id, expected_version, "Prepared", "Approved", reason, actor_label, "approved_by")

    def post_run(
        self, run_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._transition(
            run_id, expected_version, "Approved", "Posted", reason, actor_label, "posted_by", effect_kind="Posting"
        )

    def request_reversal(
        self, run_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._transition(
            run_id, expected_version, "Posted", "ReversalPrepared", reason, actor_label, "reversal_requested_by"
        )

    def approve_reversal(
        self, run_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._transition(
            run_id,
            expected_version,
            "ReversalPrepared",
            "Reversed",
            reason,
            actor_label,
            "reversed_by",
            effect_kind="Reversal",
        )

    def _effect(self, run_id: str, kind: str, actor_label: str) -> None:
        with self.connection.transaction():
            self._scope()
            effect_id = platform_id("PGCCE", self.tenant_id, run_id, kind)
            digest = hashlib.sha256(f"{run_id}:{kind}".encode()).hexdigest()
            self.connection.execute(
                "INSERT INTO reconforge.consolidation_close_effects(tenant_id,id,run_id,effect_type,actor,effect_digest) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (self.tenant_id, effect_id, run_id, kind, self._actor(actor_label), digest),
            )

    def lock_period(
        self, period_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._period_transition(period_id, expected_version, "Open", "Locked", actor_label)

    def reopen_period(
        self, period_id: str, *, expected_version: int, reason: str, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        return self._period_transition(period_id, expected_version, "Locked", "Open", actor_label)

    def _period_transition(
        self, period_id: str, expected_version: int, old: str, new: str, actor_label: str
    ) -> dict[str, Any]:
        with self.connection.transaction():
            self._scope()
            updated = self.connection.execute(
                "UPDATE reconforge.consolidation_close_periods SET status=%s,row_version=row_version+1,updated_at=now() WHERE tenant_id=%s AND id=%s AND status=%s AND row_version=%s",
                (new, self.tenant_id, period_id, old, expected_version),
            )
            if updated.rowcount != 1:
                raise PlatformError("Consolidation period changed concurrently or has an invalid state.")
            return dict(
                self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                    (self.tenant_id, period_id),
                ).fetchone()
            )

    def get_period(self, period_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, period_id),
            ).fetchone()
            return dict(row) if row else (_ for _ in ()).throw(PlatformError("Consolidation period not found."))

    def list_periods(
        self, *, workspace: str = "default", limit: int = 500, offset: int = 0, actor_label: str = "local-cli"
    ) -> list[dict[str, Any]]:
        with self.connection.transaction():
            self._scope()
            return [
                dict(r)
                for r in self.connection.execute(
                    "SELECT * FROM reconforge.consolidation_close_periods WHERE tenant_id=%s AND workspace_id=%s ORDER BY period_name LIMIT %s OFFSET %s",
                    (self.tenant_id, workspace, limit, offset),
                ).fetchall()
            ]

    def get_run(self, run_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        with self.connection.transaction():
            self._scope()
            row = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, run_id),
            ).fetchone()
            return dict(row) if row else (_ for _ in ()).throw(PlatformError("Consolidation run not found."))

    def list_runs(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        with self.connection.transaction():
            self._scope()
            rows = self.connection.execute(
                "SELECT * FROM reconforge.consolidation_close_runs WHERE tenant_id=%s AND workspace_id=%s AND (%s='' OR status=%s) ORDER BY run_number LIMIT %s OFFSET %s",
                (self.tenant_id, workspace, status, status, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> Any:
        from reconforge.application.consolidation_close import ConsolidationCloseSummary

        rows = self.list_periods(workspace=workspace)
        runs = self.list_runs(workspace=workspace)
        return ConsolidationCloseSummary(
            workspace=workspace,
            periods=len(rows),
            locked_periods=sum(r["status"] == "Locked" for r in rows),
            prepared_runs=sum(r["status"] == "Prepared" for r in runs),
            approved_runs=sum(r["status"] == "Approved" for r in runs),
            posted_runs=sum(r["status"] == "Posted" for r in runs),
            reversal_prepared_runs=sum(r["status"] == "ReversalPrepared" for r in runs),
            reversed_runs=sum(r["status"] == "Reversed" for r in runs),
        )
