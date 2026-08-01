"""Tenant-bound PostgreSQL adapter for deterministic journal controls."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconforge.application.journals import JournalImportResult
from reconforge.domain.journal_controls import JournalPolicyError, evaluate_journal_policies, journal_threshold
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.io.persisted import PersistedJsonError, encode_postgres_outbox_payload
from reconforge.platform.common import (
    PlatformError,
    normalize_key,
    normalize_text,
    parse_financial_amount,
    platform_id,
    read_local_record_document,
    to_bool,
)


class PostgresJournalControlError(RuntimeError):
    """Safe PostgreSQL journal persistence failure."""


def _row(row: Any, names: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return {name: row[name] for name in names}
    return dict(zip(names, row, strict=True))


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


class PostgresJournalControlRepository:
    """Implement journal-control persistence under one validated tenant scope."""

    _ENTRY_COLUMNS = (
        "id",
        "workspace_id",
        "journal_id",
        "period_name",
        "entity_code",
        "posting_date",
        "account_code",
        "amount",
        "amount_decimal",
        "currency",
        "reference",
        "approver",
        "is_manual",
        "source_path",
        "imported_at",
    )
    _EXCEPTION_COLUMNS = (
        "id",
        "journal_entry_id",
        "policy_code",
        "risk_rating",
        "description",
        "status",
        "created_at",
        "journal_id",
        "period_name",
        "entity_code",
        "account_code",
        "amount",
        "amount_decimal",
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
        except JournalPolicyError as exc:
            raise PostgresJournalControlError("Stored journal policy input is invalid.") from exc
        except (PlatformError, PostgresJournalControlError):
            raise
        except Exception as exc:
            raise PostgresJournalControlError("PostgreSQL journal operation failed.") from exc

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, normalize_key(workspace)),
        ).fetchone()
        if row is None:
            raise PostgresJournalControlError("Journal workspace was not found for this tenant.")
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _outbox(
        self, *, event_id: str, event_type: str, aggregate_type: str, aggregate_id: str, payload: dict[str, Any]
    ) -> None:
        try:
            payload_text = encode_postgres_outbox_payload(payload).text
        except PersistedJsonError as exc:
            raise PostgresJournalControlError("Journal outbox payload is invalid.") from exc
        self.connection.execute(
            """
            INSERT INTO reconforge.outbox_events
                (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
            VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb))
            ON CONFLICT (tenant_id,event_id) DO NOTHING
            """,
            (self.tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload_text),
        )

    def import_journals(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        default_entity: str = "local",
        actor_label: str = "local-cli",
    ) -> JournalImportResult:
        document = read_local_record_document(input_path)
        if not document.records:
            raise PlatformError("Journal input did not contain any records.")
        source = document.source_path
        metadata = {
            "source_file": source.name,
            "source_checksum_sha256": document.checksum_sha256,
            "source_size_bytes": document.size_bytes,
            "ingress_profile": document.profile_id,
        }
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            now = utc_now_text()
            for index, record in enumerate(document.records, start=1):
                journal_id = normalize_key(
                    record.get("journal_id") or record.get("id") or record.get("entry_id"), default=""
                )
                if not journal_id:
                    journal_id = platform_id("JREF", document.checksum_sha256, index)
                entry_id = platform_id("JRN", workspace_id, journal_id)
                amount = parse_financial_amount(record.get("amount"), field=f"journal row {index} amount")
                amount_text = _decimal_text(amount)
                self.connection.execute(
                    """
                    INSERT INTO reconforge.journal_entries
                        (tenant_id,id,workspace_id,journal_id,period_name,entity_code,posting_date,
                         account_code,amount,amount_decimal,currency,reference,approver,is_manual,
                         source_path,imported_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id,workspace_id,journal_id) DO UPDATE SET
                        period_name=excluded.period_name,entity_code=excluded.entity_code,
                        posting_date=excluded.posting_date,account_code=excluded.account_code,
                        amount=excluded.amount,amount_decimal=excluded.amount_decimal,
                        currency=excluded.currency,reference=excluded.reference,
                        approver=excluded.approver,is_manual=excluded.is_manual,
                        source_path=excluded.source_path,imported_at=excluded.imported_at
                    """,
                    (
                        self.tenant_id,
                        entry_id,
                        workspace_id,
                        journal_id,
                        normalize_key(record.get("period") or record.get("period_name"), default=default_period),
                        normalize_key(record.get("entity") or record.get("entity_code"), default=default_entity),
                        normalize_key(record.get("posting_date") or record.get("date"), default=""),
                        normalize_key(record.get("account_code") or record.get("account"), default="UNKNOWN"),
                        amount_text,
                        amount_text,
                        normalize_key(record.get("currency"), default="LOCAL"),
                        normalize_text(record.get("reference") or record.get("ref")),
                        normalize_text(record.get("approver") or record.get("approved_by")),
                        to_bool(record.get("is_manual") or record.get("manual")),
                        source.name,
                        now,
                    ),
                )
            self._outbox(
                event_id=platform_id("OB", self.tenant_id, workspace_id, "journal_import", document.checksum_sha256),
                event_type="journal.imported",
                aggregate_type="journal_import",
                aggregate_id=document.checksum_sha256,
                payload={
                    "tenant_id": self.tenant_id,
                    "workspace_id": workspace_id,
                    **metadata,
                    "imported_rows": len(document.records),
                },
            )
            PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                actor_label=actor_label,
                object_type="journal",
                object_id="import",
                action="journals_imported",
                metadata={**metadata, "imported_rows": len(document.records)},
            )
        return JournalImportResult(source_path=source, imported_rows=len(document.records))

    def policy_run(
        self,
        *,
        workspace: str = "default",
        period_name: str = "",
        period_end: str = "",
        high_value_threshold: object = Decimal("100000"),
        high_risk_accounts: str = "",
        actor_label: str = "local-cli",
    ) -> int:
        try:
            threshold = journal_threshold(high_value_threshold)
        except JournalPolicyError as exc:
            raise PlatformError(str(exc)) from exc
        high_risk = {item.strip() for item in high_risk_accounts.split(",") if item.strip()}
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            query = (
                "SELECT id,workspace_id,journal_id,period_name,entity_code,posting_date,account_code,"
                "amount,amount_decimal,currency,reference,approver,is_manual,source_path,imported_at "
                "FROM reconforge.journal_entries WHERE tenant_id=%s AND workspace_id=%s"
            )
            params: tuple[Any, ...] = (self.tenant_id, workspace_id)
            if period_name:
                query += " AND period_name=%s"
                params += (period_name,)
            query += " ORDER BY period_name,journal_id"
            rows = [_row(item, self._ENTRY_COLUMNS) for item in self.connection.execute(query, params).fetchall()]
            count = 0
            for row in rows:
                for policy_code, risk_rating, description in evaluate_journal_policies(
                    row, period_end=period_end, high_value_threshold=threshold, high_risk_accounts=high_risk
                ):
                    exception_id = platform_id("JEX", row["id"], policy_code)
                    created_at = utc_now_text()
                    self.connection.execute(
                        """
                        INSERT INTO reconforge.journal_exceptions
                            (tenant_id,id,workspace_id,journal_entry_id,policy_code,risk_rating,description,status,created_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'Open',%s)
                        ON CONFLICT (tenant_id,journal_entry_id,policy_code) DO UPDATE SET
                            risk_rating=excluded.risk_rating,description=excluded.description,status='Open'
                        """,
                        (
                            self.tenant_id,
                            exception_id,
                            workspace_id,
                            row["id"],
                            policy_code,
                            risk_rating,
                            description,
                            created_at,
                        ),
                    )
                    self.connection.execute(
                        """
                        INSERT INTO reconforge.control_exceptions
                            (tenant_id,id,workspace_id,source_type,source_id,period_name,entity_code,
                             account_code,risk_rating,description,status,created_at,updated_at)
                        VALUES (%s,%s,%s,'journal',%s,%s,%s,%s,%s,%s,'Open',%s,%s)
                        ON CONFLICT (tenant_id,source_type,source_id) DO UPDATE SET
                            risk_rating=excluded.risk_rating,description=excluded.description,status='Open',
                            updated_at=excluded.updated_at
                        """,
                        (
                            self.tenant_id,
                            platform_id("EXC", "journal", exception_id),
                            workspace_id,
                            exception_id,
                            row["period_name"],
                            row["entity_code"],
                            row["account_code"],
                            risk_rating,
                            description,
                            created_at,
                            created_at,
                        ),
                    )
                    count += 1
            event_id = platform_id(
                "OBX", self.tenant_id, "journal_policy_run", workspace_id, period_name, utc_now_text()
            )
            self._outbox(
                event_id=event_id,
                event_type="journal.policies_run",
                aggregate_type="journal_policy_run",
                aggregate_id=platform_id("JPR", workspace_id, period_name),
                payload={
                    "tenant_id": self.tenant_id,
                    "workspace_id": workspace_id,
                    "period": period_name,
                    "exception_count": count,
                },
            )
            PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                actor_label=actor_label,
                object_type="journal",
                object_id="policy_run",
                action="journal_policies_run",
                metadata={"period": period_name, "exception_count": count, "high_value_threshold": str(threshold)},
            )
        return count

    def exceptions(self, *, period_name: str = "") -> list[dict[str, Any]]:
        with self._transaction():
            query = (
                "SELECT exception.id,exception.journal_entry_id,exception.policy_code,exception.risk_rating,"
                "exception.description,exception.status,exception.created_at,entry.journal_id,entry.period_name,"
                "entry.entity_code,entry.account_code,entry.amount,entry.amount_decimal "
                "FROM reconforge.journal_exceptions exception JOIN reconforge.journal_entries entry "
                "ON entry.tenant_id=exception.tenant_id AND entry.id=exception.journal_entry_id "
                "WHERE exception.tenant_id=%s"
            )
            params: tuple[Any, ...] = (self.tenant_id,)
            if period_name:
                query += " AND entry.period_name=%s"
                params += (period_name,)
            query += " ORDER BY exception.created_at DESC,exception.id"
            return [_row(item, self._EXCEPTION_COLUMNS) for item in self.connection.execute(query, params).fetchall()]

    def report(self) -> dict[str, Any]:
        with self._transaction():
            row = self.connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM reconforge.journal_entries WHERE tenant_id=%s),
                    COUNT(*),
                    COUNT(*) FILTER (WHERE lower(risk_rating) IN ('high','critical'))
                FROM reconforge.journal_exceptions WHERE tenant_id=%s
                """,
                (self.tenant_id, self.tenant_id),
            ).fetchone()
            if row is None:
                raise PostgresJournalControlError("PostgreSQL journal report returned no row.")
            return {
                "journal_entries": int(row[0] or 0),
                "journal_exceptions": int(row[1] or 0),
                "high_risk_exceptions": int(row[2] or 0),
            }


POSTGRES_JOURNAL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.journal_entries (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL, workspace_id TEXT NOT NULL, journal_id TEXT NOT NULL,
    period_name TEXT NOT NULL, entity_code TEXT NOT NULL, posting_date TEXT NOT NULL,
    account_code TEXT NOT NULL, amount NUMERIC NOT NULL, amount_decimal TEXT NOT NULL,
    currency TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '', approver TEXT NOT NULL DEFAULT '',
    is_manual BOOLEAN NOT NULL DEFAULT FALSE, source_path TEXT NOT NULL, imported_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,workspace_id,journal_id),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.journal_exceptions (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    journal_entry_id TEXT NOT NULL, policy_code TEXT NOT NULL, risk_rating TEXT NOT NULL,
    description TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,journal_entry_id,policy_code),
    FOREIGN KEY (tenant_id,journal_entry_id) REFERENCES reconforge.journal_entries(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.control_exceptions (
    tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
    id TEXT NOT NULL, workspace_id TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
    period_name TEXT NOT NULL, entity_code TEXT NOT NULL, account_code TEXT NOT NULL,
    risk_rating TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,source_type,source_id),
    FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_postgres_journal_policy ON reconforge.journal_entries(tenant_id,workspace_id,period_name,account_code);
CREATE INDEX IF NOT EXISTS idx_postgres_control_exception_queue ON reconforge.control_exceptions(tenant_id,workspace_id,status,risk_rating);
DO $reconforge$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['journal_entries','journal_exceptions','control_exceptions'] LOOP
    EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY', table_name);
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
      EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
    END IF;
  END LOOP;
END $reconforge$;
"""


def install_postgres_journal_schema(connection: Any) -> None:
    """Install additive tenant-scoped journal tables."""

    connection.execute(POSTGRES_JOURNAL_SCHEMA_SQL)
