"""Tenant-bound PostgreSQL adapter for control testing."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from reconforge.application.controls import ControlLibraryImportResult
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import (
    PlatformError,
    normalize_key,
    normalize_text,
    platform_id,
    read_local_record_document,
)


class PostgresControlTestingError(RuntimeError):
    """Safe PostgreSQL control-testing persistence failure."""


def _dict_row(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {column: row[column] for column in columns}
    return dict(zip(columns, row, strict=True))


class PostgresControlTestingRepository:
    """Implement the complete control-testing contract under one tenant."""

    _PLAN_COLUMNS = (
        "id",
        "workspace_id",
        "control_id",
        "period_name",
        "status",
        "planned_by",
        "sample_size",
        "created_at",
        "updated_at",
    )
    _LIST_COLUMNS = _PLAN_COLUMNS + ("control_code", "name", "owner", "frequency", "risk_rating")
    _RESULT_COLUMNS = (
        "id",
        "test_plan_id",
        "result_status",
        "effectiveness_status",
        "tested_by",
        "note",
        "evidence_id",
        "created_at",
        "updated_at",
    )
    _REMEDIATION_COLUMNS = (
        "id",
        "source_type",
        "source_id",
        "owner",
        "status",
        "target_date",
        "action_plan",
        "created_at",
        "updated_at",
    )

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresControlTestingError):
            raise
        except Exception as exc:
            raise PostgresControlTestingError("PostgreSQL control-testing operation failed.") from exc

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, normalize_key(workspace)),
        ).fetchone()
        if row is None:
            raise PostgresControlTestingError("Control-testing workspace was not found for this tenant.")
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _event(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        event_type: str,
        metadata: dict[str, Any],
    ) -> None:
        try:
            payload = encode_postgres_outbox_payload(
                {"tenant_id": self.tenant_id, "object_type": object_type, "object_id": object_id, **metadata}
            ).text
        except PersistedJsonError as exc:
            raise PostgresControlTestingError("Control-testing outbox payload is invalid.") from exc
        self.connection.execute(
            """
            INSERT INTO reconforge.outbox_events
                (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload,status,available_at,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,'Pending',now(),now())
            """,
            (
                self.tenant_id,
                platform_id("OBX", self.tenant_id, event_type, object_id, utc_now_text()),
                event_type,
                object_type,
                object_id,
                payload,
            ),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )

    def import_library(
        self, input_path: Path | str, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> ControlLibraryImportResult:
        document = read_local_record_document(input_path)
        if not document.records:
            raise PlatformError("Control library input did not contain any records.")
        now = utc_now_text()
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            for index, record in enumerate(document.records, start=1):
                code = normalize_key(
                    record.get("control_code") or record.get("id") or record.get("control_id"), default=""
                )
                if not code:
                    code = platform_id("CTRLREF", document.checksum_sha256, index)
                self.connection.execute(
                    """
                    INSERT INTO reconforge.control_library
                        (tenant_id,id,workspace_id,control_code,name,owner,frequency,description,risk_rating,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id,workspace_id,control_code) DO UPDATE SET
                        name=excluded.name,owner=excluded.owner,frequency=excluded.frequency,
                        description=excluded.description,risk_rating=excluded.risk_rating,updated_at=excluded.updated_at
                    """,
                    (
                        self.tenant_id,
                        platform_id("CTRL", workspace_id, code),
                        workspace_id,
                        code,
                        normalize_text(record.get("name") or record.get("control_name"), default=code),
                        normalize_text(record.get("owner")),
                        normalize_text(record.get("frequency"), default="monthly"),
                        normalize_text(record.get("description")),
                        normalize_key(record.get("risk_rating"), default="medium").lower(),
                        now,
                        now,
                    ),
                )
            metadata = {
                "source_file": document.source_path.name,
                "source_checksum_sha256": document.checksum_sha256,
                "source_size_bytes": document.size_bytes,
                "ingress_profile": document.profile_id,
                "imported_rows": len(document.records),
                "workspace_id": workspace_id,
            }
            self._event(
                actor_label=actor_label,
                object_type="control_library",
                object_id="import",
                action="control_library_imported",
                event_type="controls.library_imported",
                metadata=metadata,
            )
        return ControlLibraryImportResult(source_path=document.source_path, imported_rows=len(document.records))

    def plan_tests(
        self,
        *,
        period_name: str,
        workspace: str = "default",
        sample_size: int = 0,
        actor_label: str = "local-cli",
    ) -> int:
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            controls = self.connection.execute(
                "SELECT id FROM reconforge.control_library WHERE tenant_id=%s AND workspace_id=%s ORDER BY control_code",
                (self.tenant_id, workspace_id),
            ).fetchall()
            now = utc_now_text()
            for row in controls:
                control_id = str(row["id"] if isinstance(row, Mapping) else row[0])
                self.connection.execute(
                    """
                    INSERT INTO reconforge.control_test_plans
                        (tenant_id,id,workspace_id,control_id,period_name,status,planned_by,sample_size,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,'Planned',%s,%s,%s,%s)
                    ON CONFLICT (tenant_id,control_id,period_name) DO UPDATE SET
                        status='Planned',planned_by=excluded.planned_by,sample_size=excluded.sample_size,
                        updated_at=excluded.updated_at
                    """,
                    (
                        self.tenant_id,
                        platform_id("CTP", control_id, period_name),
                        workspace_id,
                        control_id,
                        period_name,
                        actor_label,
                        sample_size,
                        now,
                        now,
                    ),
                )
            count = len(controls)
            self._event(
                actor_label=actor_label,
                object_type="control_test_plan",
                object_id=period_name,
                action="control_tests_planned",
                event_type="controls.tests_planned",
                metadata={"period": period_name, "plan_count": count, "workspace_id": workspace_id},
            )
        return count

    def record_result(
        self,
        *,
        plan_id: str,
        result_status: str,
        effectiveness_status: str,
        note: str = "",
        evidence_id: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT plan.id,plan.workspace_id,plan.period_name,control.control_code,control.risk_rating
                FROM reconforge.control_test_plans plan JOIN reconforge.control_library control
                  ON control.tenant_id=plan.tenant_id AND control.id=plan.control_id
                WHERE plan.tenant_id=%s AND plan.id=%s
                """,
                (self.tenant_id, plan_id),
            ).fetchone()
            if row is None:
                raise PostgresControlTestingError("Control test plan not found.")
            plan = _dict_row(row, ("id", "workspace_id", "period_name", "control_code", "risk_rating"))
            now = utc_now_text()
            result_id = platform_id("CTR", plan_id, now)
            effectiveness = normalize_key(effectiveness_status, default="Unknown")
            self.connection.execute(
                """
                INSERT INTO reconforge.control_test_results
                    (tenant_id,id,test_plan_id,result_status,effectiveness_status,tested_by,note,evidence_id,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    self.tenant_id,
                    result_id,
                    plan_id,
                    normalize_key(result_status, default="Completed"),
                    effectiveness,
                    actor_label,
                    note,
                    evidence_id,
                    now,
                    now,
                ),
            )
            self.connection.execute(
                "UPDATE reconforge.control_test_plans SET status='Tested',updated_at=%s WHERE tenant_id=%s AND id=%s",
                (now, self.tenant_id, plan_id),
            )
            if effectiveness.lower() not in {"effective", "passed", "pass"}:
                self.connection.execute(
                    """
                    INSERT INTO reconforge.control_exceptions
                        (tenant_id,id,workspace_id,source_type,source_id,period_name,entity_code,account_code,
                         risk_rating,description,status,created_at,updated_at)
                    VALUES (%s,%s,%s,'control_test',%s,%s,'',%s,%s,%s,'Open',%s,%s)
                    ON CONFLICT (tenant_id,source_type,source_id) DO UPDATE SET
                        risk_rating=excluded.risk_rating,description=excluded.description,status='Open',updated_at=excluded.updated_at
                    """,
                    (
                        self.tenant_id,
                        platform_id("EXC", "control_test", result_id),
                        plan["workspace_id"],
                        result_id,
                        plan["period_name"],
                        plan["control_code"],
                        plan["risk_rating"],
                        "Control test result is not marked effective.",
                        now,
                        now,
                    ),
                )
            self._event(
                actor_label=actor_label,
                object_type="control_test_result",
                object_id=result_id,
                action="control_test_result_recorded",
                event_type="controls.result_recorded",
                metadata={"plan_id": plan_id, "effectiveness_status": effectiveness_status},
            )
            stored = self.connection.execute(
                "SELECT id,test_plan_id,result_status,effectiveness_status,tested_by,note,evidence_id,created_at,updated_at "
                "FROM reconforge.control_test_results WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, result_id),
            ).fetchone()
            if stored is None:
                raise PostgresControlTestingError("Unable to read the recorded control test result.")
            result = _dict_row(stored, self._RESULT_COLUMNS)
        return result

    def remediation(
        self,
        *,
        source_type: str,
        source_id: str,
        action_plan: str,
        owner: str = "",
        target_date: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        if not normalize_text(action_plan):
            raise PlatformError("Remediation action plan is required.")
        remediation_id = platform_id("REM", source_type, source_id)
        now = utc_now_text()
        with self._transaction():
            self.connection.execute(
                """
                INSERT INTO reconforge.remediation_plans
                    (tenant_id,id,source_type,source_id,owner,status,target_date,action_plan,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,'Open',%s,%s,%s,%s)
                ON CONFLICT (tenant_id,id) DO UPDATE SET owner=excluded.owner,target_date=excluded.target_date,
                    action_plan=excluded.action_plan,updated_at=excluded.updated_at
                """,
                (self.tenant_id, remediation_id, source_type, source_id, owner, target_date, action_plan, now, now),
            )
            self._event(
                actor_label=actor_label,
                object_type="remediation_plan",
                object_id=remediation_id,
                action="remediation_plan_saved",
                event_type="controls.remediation_saved",
                metadata={"source_type": source_type, "source_id": source_id},
            )
            stored = self.connection.execute(
                "SELECT id,source_type,source_id,owner,status,target_date,action_plan,created_at,updated_at "
                "FROM reconforge.remediation_plans WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, remediation_id),
            ).fetchone()
            if stored is None:
                raise PostgresControlTestingError("Unable to read the saved remediation plan.")
            result = _dict_row(stored, self._REMEDIATION_COLUMNS)
        return result

    def report(self) -> dict[str, Any]:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM reconforge.control_library WHERE tenant_id=%s),
                  (SELECT COUNT(*) FROM reconforge.control_test_plans WHERE tenant_id=%s),
                  COUNT(*),
                  COUNT(*) FILTER (WHERE lower(effectiveness_status) NOT IN ('effective','passed','pass'))
                FROM reconforge.control_test_results WHERE tenant_id=%s
                """,
                (self.tenant_id, self.tenant_id, self.tenant_id),
            ).fetchone()
            if row is None:
                raise PostgresControlTestingError("PostgreSQL control-testing report returned no row.")
            return {
                "controls": int(row[0] or 0),
                "test_plans": int(row[1] or 0),
                "test_results": int(row[2] or 0),
                "ineffective_results": int(row[3] or 0),
            }

    def list_plans(self, *, period_name: str = "") -> list[dict[str, Any]]:
        with self._transaction():
            query = (
                "SELECT plan.id,plan.workspace_id,plan.control_id,plan.period_name,plan.status,plan.planned_by,"
                "plan.sample_size,plan.created_at,plan.updated_at,control.control_code,control.name,control.owner,"
                "control.frequency,control.risk_rating FROM reconforge.control_test_plans plan "
                "JOIN reconforge.control_library control ON control.tenant_id=plan.tenant_id AND control.id=plan.control_id "
                "WHERE plan.tenant_id=%s"
            )
            params: tuple[Any, ...] = (self.tenant_id,)
            if period_name:
                query += " AND plan.period_name=%s"
                params += (period_name,)
            query += " ORDER BY plan.period_name DESC,control.control_code"
            return [_dict_row(row, self._LIST_COLUMNS) for row in self.connection.execute(query, params).fetchall()]

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        with self._transaction():
            row = self.connection.execute(
                "SELECT id,workspace_id,control_id,period_name,status,planned_by,sample_size,created_at,updated_at "
                "FROM reconforge.control_test_plans WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, plan_id),
            ).fetchone()
            if row is None:
                raise PostgresControlTestingError("Control test plan not found.")
            return _dict_row(row, self._PLAN_COLUMNS)


POSTGRES_CONTROL_TESTING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.control_library (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, control_code TEXT NOT NULL,
 name TEXT NOT NULL, owner TEXT NOT NULL DEFAULT '', frequency TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', risk_rating TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,control_code),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.control_test_plans (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL, control_id TEXT NOT NULL,
 period_name TEXT NOT NULL, status TEXT NOT NULL, planned_by TEXT NOT NULL, sample_size INTEGER NOT NULL CHECK (sample_size >= 0),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,control_id,period_name),
 FOREIGN KEY (tenant_id,control_id) REFERENCES reconforge.control_library(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.control_test_results (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, test_plan_id TEXT NOT NULL, result_status TEXT NOT NULL,
 effectiveness_status TEXT NOT NULL, tested_by TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', evidence_id TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (tenant_id,id),
 FOREIGN KEY (tenant_id,test_plan_id) REFERENCES reconforge.control_test_plans(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.remediation_plans (
 tenant_id TEXT NOT NULL, id TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
 owner TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, target_date TEXT NOT NULL DEFAULT '', action_plan TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (tenant_id,id)
);
CREATE INDEX IF NOT EXISTS idx_postgres_control_plans ON reconforge.control_test_plans(tenant_id,workspace_id,period_name,status);
CREATE INDEX IF NOT EXISTS idx_postgres_control_results ON reconforge.control_test_results(tenant_id,test_plan_id,effectiveness_status);
DO $reconforge$
DECLARE table_name text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['control_library','control_test_plans','control_test_results','remediation_plans'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY', table_name);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY', table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
  END IF;
 END LOOP;
END $reconforge$;
"""


def install_postgres_control_testing_schema(connection: Any) -> None:
    """Install additive tenant-scoped control-testing tables."""

    connection.execute(POSTGRES_CONTROL_TESTING_SCHEMA_SQL)
