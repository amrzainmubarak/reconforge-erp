"""PostgreSQL unit-of-work adapter for the local domain backbone."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Literal

from reconforge.audit.events import (
    GENESIS_AUDIT_HASH,
    AuditLedgerError,
    AuditVerificationIssue,
    AuditVerificationResult,
)
from reconforge.domain.audit_chain import calculate_audit_event_hash
from reconforge.domain.models import (
    DEFAULT_LOCAL_FIRST_NOTE,
    AuditEventReference,
    Period,
    Workspace,
    utc_now_text,
)
from reconforge.domain.protocols import (
    AuditEventRepositoryProtocol,
    DomainUnitOfWorkProtocol,
    PeriodRepositoryProtocol,
    WorkspaceRepositoryProtocol,
)
from reconforge.infrastructure.postgres import ConnectionFactory, set_local_tenant_scope, validate_tenant_id
from reconforge.io.persisted import PersistedJsonError, decode_audit_metadata, encode_audit_metadata


class PostgresDomainUnitOfWorkError(RuntimeError):
    """Safe failure for PostgreSQL local-domain transaction ownership."""


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _required_text(value: str, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise AuditLedgerError(f"Audit event {label} is required.")
    return cleaned


def _metadata_text(metadata: dict[str, Any] | None) -> str:
    try:
        return encode_audit_metadata(metadata).text
    except PersistedJsonError as exc:
        raise AuditLedgerError("Audit event metadata must be JSON-serializable.") from exc


class PostgresWorkspaceRepository(WorkspaceRepositoryProtocol):
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = tenant_id

    def create(self, *, name: str, local_first_note: str | None = None) -> Workspace:
        workspace = Workspace(name=name, local_first_note=local_first_note or DEFAULT_LOCAL_FIRST_NOTE)
        self.connection.execute(
            """
            INSERT INTO reconforge.domain_workspaces
                (tenant_id, id, name, local_first_note, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (self.tenant_id, workspace.id, workspace.name, workspace.local_first_note, workspace.created_at),
        )
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        row = self.connection.execute(
            "SELECT id, name, local_first_note, created_at FROM reconforge.domain_workspaces "
            "WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, workspace_id),
        ).fetchone()
        return None if row is None else self._decode(row)

    def list(self) -> list[Workspace]:
        rows = self.connection.execute(
            "SELECT id, name, local_first_note, created_at FROM reconforge.domain_workspaces "
            "WHERE tenant_id=%s ORDER BY created_at, id",
            (self.tenant_id,),
        ).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row: Any) -> Workspace:
        return Workspace(
            id=str(_row_value(row, "id", 0)),
            name=str(_row_value(row, "name", 1)),
            local_first_note=str(_row_value(row, "local_first_note", 2)),
            created_at=str(_row_value(row, "created_at", 3)),
        )


class PostgresPeriodRepository(PeriodRepositoryProtocol):
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = tenant_id

    def create(
        self,
        *,
        workspace_id: str,
        name: str,
        start_date: str,
        end_date: str,
        status: str = "Open",
    ) -> Period:
        period = Period(
            workspace_id=workspace_id,
            name=name,
            start_date=start_date,
            end_date=end_date,
            status=status,
        )
        self.connection.execute(
            """
            INSERT INTO reconforge.domain_periods
                (tenant_id, id, workspace_id, name, start_date, end_date, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                self.tenant_id,
                period.id,
                period.workspace_id,
                period.name,
                period.start_date,
                period.end_date,
                period.status,
                period.created_at,
            ),
        )
        return period

    def get(self, period_id: str) -> Period | None:
        row = self.connection.execute(
            "SELECT id, workspace_id, name, start_date, end_date, status, created_at "
            "FROM reconforge.domain_periods WHERE tenant_id=%s AND id=%s",
            (self.tenant_id, period_id),
        ).fetchone()
        return None if row is None else self._decode(row)

    def list(self, *, workspace_id: str | None = None) -> list[Period]:
        query = (
            "SELECT id, workspace_id, name, start_date, end_date, status, created_at "
            "FROM reconforge.domain_periods WHERE tenant_id=%s"
        )
        parameters: tuple[object, ...] = (self.tenant_id,)
        if workspace_id is not None:
            query += " AND workspace_id=%s"
            parameters += (workspace_id,)
        query += " ORDER BY start_date, id"
        return [self._decode(row) for row in self.connection.execute(query, parameters).fetchall()]

    @staticmethod
    def _decode(row: Any) -> Period:
        return Period(
            id=str(_row_value(row, "id", 0)),
            workspace_id=str(_row_value(row, "workspace_id", 1)),
            name=str(_row_value(row, "name", 2)),
            start_date=str(_row_value(row, "start_date", 3)),
            end_date=str(_row_value(row, "end_date", 4)),
            status=str(_row_value(row, "status", 5)),
            created_at=str(_row_value(row, "created_at", 6)),
        )


class PostgresAuditEventRepository(AuditEventRepositoryProtocol):
    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = tenant_id

    def append(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        actor_user_id: str | None = None,
        before_hash: str | None = None,
        after_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEventReference:
        actor = _required_text(actor_label, "actor_label")
        target_type = _required_text(object_type, "object_type")
        target_id = _required_text(object_id, "object_id")
        event_action = _required_text(action, "action")
        metadata_json = _metadata_text(metadata)
        event_id = f"AE-{uuid.uuid4().hex}"
        created_at = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO reconforge.domain_audit_ledger_state
                    (tenant_id, last_sequence, last_event_hash, updated_at)
                VALUES (%s, 0, %s, %s) ON CONFLICT (tenant_id) DO NOTHING
                """,
                (self.tenant_id, GENESIS_AUDIT_HASH, created_at),
            )
            state = self.connection.execute(
                "SELECT last_sequence, last_event_hash FROM reconforge.domain_audit_ledger_state "
                "WHERE tenant_id=%s FOR UPDATE",
                (self.tenant_id,),
            ).fetchone()
            if state is None:
                raise AuditLedgerError("Audit ledger is not initialized.")
            sequence = int(_row_value(state, "last_sequence", 0)) + 1
            previous_hash = str(_row_value(state, "last_event_hash", 1))
            event_hash = calculate_audit_event_hash(
                event_id=event_id,
                sequence=sequence,
                previous_hash=previous_hash,
                actor_user_id=actor_user_id,
                actor_label=actor,
                object_type=target_type,
                object_id=target_id,
                action=event_action,
                before_hash=before_hash,
                after_hash=after_hash,
                metadata_json=metadata_json,
                created_at=created_at,
            )
            self.connection.execute(
                """
                INSERT INTO reconforge.domain_audit_events
                    (tenant_id, id, sequence, previous_hash, event_hash, actor_user_id,
                     actor_label, object_type, object_id, action, before_hash, after_hash,
                     metadata_json, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),%s)
                """,
                (
                    self.tenant_id,
                    event_id,
                    sequence,
                    previous_hash,
                    event_hash,
                    actor_user_id,
                    actor,
                    target_type,
                    target_id,
                    event_action,
                    before_hash,
                    after_hash,
                    metadata_json,
                    created_at,
                ),
            )
            self.connection.execute(
                "UPDATE reconforge.domain_audit_ledger_state "
                "SET last_sequence=%s, last_event_hash=%s, updated_at=%s WHERE tenant_id=%s",
                (sequence, event_hash, created_at, self.tenant_id),
            )
        except AuditLedgerError:
            raise
        except Exception as exc:
            raise AuditLedgerError("Unable to append audit event.") from exc
        return AuditEventReference(
            id=event_id,
            sequence=sequence,
            previous_hash=previous_hash,
            event_hash=event_hash,
            actor_user_id=actor_user_id,
            actor_label=actor,
            object_type=target_type,
            object_id=target_id,
            action=event_action,
            before_hash=before_hash,
            after_hash=after_hash,
            metadata=decode_audit_metadata(metadata_json).payload,
            created_at=created_at,
        )

    def list(self, *, limit: int | None = None) -> list[AuditEventReference]:
        if limit is not None and limit < 1:
            raise AuditLedgerError("Audit event limit must be greater than zero.")
        query = "SELECT id, sequence, previous_hash, event_hash, actor_user_id, actor_label, object_type, object_id, action, before_hash, after_hash, metadata_json::text, created_at FROM reconforge.domain_audit_events WHERE tenant_id=%s ORDER BY sequence"
        parameters: tuple[object, ...] = (self.tenant_id,)
        if limit is not None:
            query += " LIMIT %s"
            parameters += (limit,)
        return [self._decode(row) for row in self.connection.execute(query, parameters).fetchall()]

    @staticmethod
    def _decode(row: Any) -> AuditEventReference:
        try:
            metadata = decode_audit_metadata(str(_row_value(row, "metadata_json", 11))).payload
        except PersistedJsonError as exc:
            raise AuditLedgerError("Stored audit event metadata is invalid.") from exc
        return AuditEventReference(
            id=str(_row_value(row, "id", 0)),
            sequence=int(_row_value(row, "sequence", 1)),
            previous_hash=str(_row_value(row, "previous_hash", 2)),
            event_hash=str(_row_value(row, "event_hash", 3)),
            actor_user_id=(
                None if _row_value(row, "actor_user_id", 4) is None else str(_row_value(row, "actor_user_id", 4))
            ),
            actor_label=str(_row_value(row, "actor_label", 5)),
            object_type=str(_row_value(row, "object_type", 6)),
            object_id=str(_row_value(row, "object_id", 7)),
            action=str(_row_value(row, "action", 8)),
            before_hash=(None if _row_value(row, "before_hash", 9) is None else str(_row_value(row, "before_hash", 9))),
            after_hash=(None if _row_value(row, "after_hash", 10) is None else str(_row_value(row, "after_hash", 10))),
            metadata=metadata,
            created_at=str(_row_value(row, "created_at", 12)),
        )

    def verify(self) -> AuditVerificationResult:
        events = self.list()
        issues: list[AuditVerificationIssue] = []
        expected_sequence = 1
        expected_previous = GENESIS_AUDIT_HASH
        for event in events:
            if event.sequence != expected_sequence:
                issues.append(AuditVerificationIssue(event.sequence, "Audit event sequence is not contiguous."))
            if event.previous_hash != expected_previous:
                issues.append(
                    AuditVerificationIssue(event.sequence, "Audit event previous hash does not match ledger head.")
                )
            metadata_json = _metadata_text(event.metadata)
            expected_hash = calculate_audit_event_hash(
                event_id=event.id,
                sequence=event.sequence,
                previous_hash=event.previous_hash,
                actor_user_id=event.actor_user_id,
                actor_label=event.actor_label,
                object_type=event.object_type,
                object_id=event.object_id,
                action=event.action,
                before_hash=event.before_hash,
                after_hash=event.after_hash,
                metadata_json=metadata_json,
                created_at=event.created_at,
            )
            if not hmac.compare_digest(event.event_hash, expected_hash):
                issues.append(AuditVerificationIssue(event.sequence, "Audit event hash does not match row content."))
            expected_previous = event.event_hash
            expected_sequence += 1
        state = self.connection.execute(
            "SELECT last_sequence, last_event_hash FROM reconforge.domain_audit_ledger_state WHERE tenant_id=%s",
            (self.tenant_id,),
        ).fetchone()
        if state is None:
            if events:
                issues.append(AuditVerificationIssue(None, "Audit ledger state row is missing."))
        elif int(_row_value(state, "last_sequence", 0)) != len(events):
            issues.append(AuditVerificationIssue(None, "Audit ledger state sequence does not match event count."))
        elif str(_row_value(state, "last_event_hash", 1)) != expected_previous:
            issues.append(AuditVerificationIssue(None, "Audit ledger state hash does not match final event hash."))
        return AuditVerificationResult(not issues, len(events), issues, expected_previous)


class PostgresDomainUnitOfWork(DomainUnitOfWorkProtocol):
    """Own one PostgreSQL connection and transaction for a tenant-bound use case."""

    def __init__(self, connection_factory: ConnectionFactory, tenant_id: str) -> None:
        self._factory = connection_factory
        self._tenant_id = validate_tenant_id(tenant_id)
        self._connection: Any | None = None
        self._transaction: Any | None = None
        self._active = False
        self._committed = False
        self.workspaces: WorkspaceRepositoryProtocol
        self.periods: PeriodRepositoryProtocol
        self.audit_events: AuditEventRepositoryProtocol

    def __enter__(self) -> PostgresDomainUnitOfWork:
        if self._active:
            raise PostgresDomainUnitOfWorkError("PostgreSQL unit of work is already active.")
        connection = self._factory.connect()
        transaction = connection.transaction()
        try:
            transaction.__enter__()
            set_local_tenant_scope(connection, self._tenant_id)
        except Exception as exc:
            connection.close()
            raise PostgresDomainUnitOfWorkError("Unable to begin PostgreSQL unit of work.") from exc
        self._connection = connection
        self._transaction = transaction
        self.workspaces = PostgresWorkspaceRepository(connection, self._tenant_id)
        self.periods = PostgresPeriodRepository(connection, self._tenant_id)
        self.audit_events = PostgresAuditEventRepository(connection, self._tenant_id)
        self._active = True
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if self._active:
            if exc_type is not None or not self._committed:
                self.rollback()
            else:
                self._finish(None, None, None)
        return False

    def _finish(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        transaction, connection = self._transaction, self._connection
        self._active = False
        self._transaction = None
        self._connection = None
        try:
            if transaction is not None:
                transaction.__exit__(exc_type, exc_value, traceback)
        finally:
            if connection is not None:
                connection.close()

    def commit(self) -> None:
        if not self._active:
            raise PostgresDomainUnitOfWorkError("PostgreSQL unit of work is not active.")
        self._committed = True
        try:
            self._finish(None, None, None)
        except Exception as exc:
            self._committed = False
            raise PostgresDomainUnitOfWorkError("Unable to commit PostgreSQL unit of work.") from exc

    def rollback(self) -> None:
        if not self._active:
            return
        marker = PostgresDomainUnitOfWorkError("PostgreSQL unit of work rolled back.")
        self._committed = False
        self._finish(type(marker), marker, marker.__traceback__)


POSTGRES_DOMAIN_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.domain_workspaces (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL, name TEXT NOT NULL,
    local_first_note TEXT NOT NULL DEFAULT 'Local-first workspace. Data remains in user-selected local paths.',
    created_at TEXT NOT NULL DEFAULT (now()::text),
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS reconforge.domain_periods (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    name TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id, id) ON DELETE RESTRICT,
    CHECK (end_date >= start_date)
);
CREATE TABLE IF NOT EXISTS reconforge.domain_audit_ledger_state (
    tenant_id TEXT PRIMARY KEY REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    last_sequence BIGINT NOT NULL CHECK (last_sequence >= 0),
    last_event_hash TEXT NOT NULL CHECK (last_event_hash ~ '^[0-9a-f]{64}$'), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconforge.domain_audit_events (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, sequence BIGINT NOT NULL CHECK (sequence > 0),
    previous_hash TEXT NOT NULL CHECK (previous_hash ~ '^[0-9a-f]{64}$'),
    event_hash TEXT NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'), actor_user_id TEXT,
    actor_label TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL,
    action TEXT NOT NULL, before_hash TEXT, after_hash TEXT, metadata_json JSONB NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY (tenant_id, id), UNIQUE (tenant_id, sequence),
    FOREIGN KEY (tenant_id) REFERENCES reconforge.tenants(id) ON DELETE RESTRICT
);
CREATE OR REPLACE FUNCTION reconforge.reject_domain_audit_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Domain audit events are append-only'; END; $$;
DROP TRIGGER IF EXISTS domain_audit_events_immutable ON reconforge.domain_audit_events;
CREATE TRIGGER domain_audit_events_immutable BEFORE UPDATE OR DELETE ON reconforge.domain_audit_events
FOR EACH ROW EXECUTE FUNCTION reconforge.reject_domain_audit_mutation();
ALTER TABLE reconforge.domain_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.domain_workspaces FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.domain_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.domain_periods FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.domain_audit_ledger_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.domain_audit_ledger_state FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.domain_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.domain_audit_events FORCE ROW LEVEL SECURITY;
DO $reconforge$ DECLARE table_name TEXT; BEGIN
  FOREACH table_name IN ARRAY ARRAY['domain_workspaces','domain_periods','domain_audit_ledger_state','domain_audit_events'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
      EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
    END IF;
  END LOOP;
END $reconforge$;
"""


def install_postgres_domain_schema(connection: Any) -> None:
    connection.execute(POSTGRES_DOMAIN_SCHEMA_SQL)
