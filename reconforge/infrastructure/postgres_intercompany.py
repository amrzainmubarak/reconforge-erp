"""Tenant-bound PostgreSQL adapter for exact intercompany workflows."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconforge.application.intercompany import IntercompanyImportResult
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
)


class PostgresIntercompanyError(RuntimeError):
    """Safe PostgreSQL intercompany persistence failure."""


def _row(value: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {column: value[column] for column in columns}
    return dict(zip(columns, value, strict=True))


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _amount(value: object, *, field: str) -> Decimal:
    return parse_financial_amount(value, field=field)


def _non_negative_amount(value: object, *, field: str) -> Decimal:
    parsed = _amount(value, field=field)
    if parsed < 0:
        raise PlatformError(f"Financial amount in field '{field}' cannot be negative.")
    return parsed


class PostgresIntercompanyRepository:
    """Implement the complete intercompany contract under one tenant."""

    _TRANSACTION_COLUMNS = (
        "id",
        "workspace_id",
        "transaction_id",
        "period_name",
        "entity_code",
        "counterparty_code",
        "posting_date",
        "amount",
        "amount_decimal",
        "currency",
        "reference",
        "source_path",
        "imported_at",
    )
    _CASE_COLUMNS = (
        "id",
        "workspace_id",
        "period_name",
        "entity_code",
        "counterparty_code",
        "reference",
        "imbalance_amount",
        "imbalance_amount_decimal",
        "currency",
        "status",
        "dispute_owner",
        "settlement_status",
        "aging_days",
        "evidence_note",
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
        except (PlatformError, PostgresIntercompanyError):
            raise
        except Exception as exc:
            raise PostgresIntercompanyError("PostgreSQL intercompany operation failed.") from exc

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, normalize_key(workspace)),
        ).fetchone()
        if row is None:
            raise PostgresIntercompanyError("Intercompany workspace was not found for this tenant.")
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _outbox(
        self,
        *,
        event_id: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            payload_text = encode_postgres_outbox_payload(payload).text
        except PersistedJsonError as exc:
            raise PostgresIntercompanyError("Intercompany outbox payload is invalid.") from exc
        self.connection.execute(
            """
            INSERT INTO reconforge.outbox_events
                (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
            VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb))
            ON CONFLICT (tenant_id,event_id) DO NOTHING
            """,
            (self.tenant_id, event_id, event_type, aggregate_type, aggregate_id, payload_text),
        )

    def import_transactions(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        actor_label: str = "local-cli",
    ) -> IntercompanyImportResult:
        document = read_local_record_document(input_path)
        if not document.records:
            raise PlatformError("Intercompany input did not contain any records.")
        metadata = {
            "source_file": document.source_path.name,
            "source_checksum_sha256": document.checksum_sha256,
            "source_size_bytes": document.size_bytes,
            "ingress_profile": document.profile_id,
        }
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            now = utc_now_text()
            for index, record in enumerate(document.records, start=1):
                transaction_id = normalize_key(record.get("transaction_id") or record.get("id"), default="")
                if not transaction_id:
                    transaction_id = platform_id("ICREF", document.checksum_sha256, index)
                amount = _amount(record.get("amount"), field=f"intercompany row {index} amount")
                amount_text = _decimal_text(amount)
                self.connection.execute(
                    """
                    INSERT INTO reconforge.intercompany_transactions
                        (tenant_id,id,workspace_id,transaction_id,period_name,entity_code,
                         counterparty_code,posting_date,amount,amount_decimal,currency,reference,
                         source_path,imported_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (tenant_id,workspace_id,transaction_id) DO UPDATE SET
                        period_name=excluded.period_name,entity_code=excluded.entity_code,
                        counterparty_code=excluded.counterparty_code,posting_date=excluded.posting_date,
                        amount=excluded.amount,amount_decimal=excluded.amount_decimal,
                        currency=excluded.currency,reference=excluded.reference,
                        source_path=excluded.source_path,imported_at=excluded.imported_at
                    """,
                    (
                        self.tenant_id,
                        platform_id("IC", workspace_id, transaction_id),
                        workspace_id,
                        transaction_id,
                        normalize_key(record.get("period") or record.get("period_name"), default=default_period),
                        normalize_key(record.get("entity") or record.get("entity_code"), default="local"),
                        normalize_key(
                            record.get("counterparty") or record.get("counterparty_code"),
                            default="unknown",
                        ),
                        normalize_key(record.get("posting_date") or record.get("date"), default=""),
                        amount_text,
                        amount_text,
                        normalize_key(record.get("currency"), default="LOCAL"),
                        normalize_text(record.get("reference") or record.get("ref")),
                        document.source_path.name,
                        now,
                    ),
                )
            imported = len(document.records)
            self._outbox(
                event_id=platform_id("OBX", "intercompany_import", workspace_id, document.checksum_sha256),
                event_type="intercompany.imported",
                aggregate_type="intercompany_import",
                aggregate_id=document.checksum_sha256,
                payload={
                    "tenant_id": self.tenant_id,
                    "workspace_id": workspace_id,
                    **metadata,
                    "imported_rows": imported,
                },
            )
            PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                actor_label=actor_label,
                object_type="intercompany",
                object_id="import",
                action="intercompany_imported",
                metadata={**metadata, "imported_rows": imported},
            )
        return IntercompanyImportResult(document.source_path, imported)

    def match(
        self,
        *,
        workspace: str = "default",
        period_name: str = "",
        tolerance: object = Decimal("0.01"),
        actor_label: str = "local-cli",
    ) -> int:
        tolerance_amount = _non_negative_amount(tolerance, field="intercompany tolerance")
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            query = (
                "SELECT id,workspace_id,transaction_id,period_name,entity_code,counterparty_code,"
                "posting_date,amount,amount_decimal,currency,reference,source_path,imported_at "
                "FROM reconforge.intercompany_transactions WHERE tenant_id=%s AND workspace_id=%s"
            )
            params: tuple[Any, ...] = (self.tenant_id, workspace_id)
            if period_name:
                query += " AND period_name=%s"
                params += (period_name,)
            query += " ORDER BY period_name,reference,entity_code,transaction_id"
            rows = [_row(item, self._TRANSACTION_COLUMNS) for item in self.connection.execute(query, params).fetchall()]
            grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
            for row in rows:
                grouped.setdefault((str(row["period_name"]), str(row["reference"]), str(row["currency"])), []).append(
                    row
                )
            now = utc_now_text()
            case_count = 0
            for (period, reference, currency), group in grouped.items():
                if not reference:
                    continue
                imbalance = sum(
                    (_amount(row["amount_decimal"], field="intercompany amount") for row in group),
                    Decimal("0"),
                )
                if abs(imbalance) <= tolerance_amount and len(group) >= 2:
                    continue
                first = group[0]
                case_id = platform_id(
                    "ICC",
                    workspace_id,
                    period,
                    str(first["entity_code"]),
                    str(first["counterparty_code"]),
                    reference,
                )
                imbalance_text = _decimal_text(imbalance)
                self.connection.execute(
                    """
                    INSERT INTO reconforge.intercompany_cases
                        (tenant_id,id,workspace_id,period_name,entity_code,counterparty_code,
                         reference,imbalance_amount,imbalance_amount_decimal,currency,status,
                         settlement_status,aging_days,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Open','Open',0,%s,%s)
                    ON CONFLICT (tenant_id,workspace_id,period_name,entity_code,counterparty_code,reference)
                    DO UPDATE SET imbalance_amount=excluded.imbalance_amount,
                        imbalance_amount_decimal=excluded.imbalance_amount_decimal,
                        currency=excluded.currency,status='Open',updated_at=excluded.updated_at
                    """,
                    (
                        self.tenant_id,
                        case_id,
                        workspace_id,
                        period,
                        first["entity_code"],
                        first["counterparty_code"],
                        reference,
                        imbalance_text,
                        imbalance_text,
                        currency,
                        now,
                        now,
                    ),
                )
                self.connection.execute(
                    """
                    INSERT INTO reconforge.control_exceptions
                        (tenant_id,id,workspace_id,source_type,source_id,period_name,entity_code,
                         account_code,risk_rating,description,status,created_at,updated_at)
                    VALUES (%s,%s,%s,'intercompany',%s,%s,%s,'',%s,%s,'Open',%s,%s)
                    ON CONFLICT (tenant_id,source_type,source_id) DO UPDATE SET
                        risk_rating=excluded.risk_rating,description=excluded.description,
                        status='Open',updated_at=excluded.updated_at
                    """,
                    (
                        self.tenant_id,
                        platform_id("EXC", "intercompany", case_id),
                        workspace_id,
                        case_id,
                        period,
                        first["entity_code"],
                        "high" if abs(imbalance) > tolerance_amount else "medium",
                        "Intercompany reference has unmatched or imbalanced counterparty amounts.",
                        now,
                        now,
                    ),
                )
                case_count += 1
            self._outbox(
                event_id=platform_id("OBX", "intercompany_match", workspace_id, period_name, now),
                event_type="intercompany.matched",
                aggregate_type="intercompany_match",
                aggregate_id=platform_id("ICM", workspace_id, period_name),
                payload={
                    "tenant_id": self.tenant_id,
                    "workspace_id": workspace_id,
                    "period": period_name,
                    "case_count": case_count,
                },
            )
            PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                actor_label=actor_label,
                object_type="intercompany",
                object_id="match",
                action="intercompany_matched",
                metadata={
                    "period": period_name,
                    "case_count": case_count,
                    "tolerance": str(tolerance_amount),
                },
            )
        return case_count

    def settle(
        self,
        case_id: str,
        *,
        settlement_status: str = "Settled",
        dispute_owner: str = "",
        evidence_note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        now = utc_now_text()
        normalized_status = normalize_key(settlement_status, default="Settled")
        with self._transaction():
            cursor = self.connection.execute(
                "UPDATE reconforge.intercompany_cases SET settlement_status=%s,dispute_owner=%s,"
                "evidence_note=%s,status='Resolved',updated_at=%s WHERE tenant_id=%s AND id=%s",
                (normalized_status, dispute_owner, evidence_note, now, self.tenant_id, case_id),
            )
            if cursor.rowcount != 1:
                raise PlatformError("Intercompany case not found.")
            self._outbox(
                event_id=platform_id("OBX", "intercompany_settle", case_id, now),
                event_type="intercompany.case_settled",
                aggregate_type="intercompany_case",
                aggregate_id=case_id,
                payload={
                    "tenant_id": self.tenant_id,
                    "case_id": case_id,
                    "settlement_status": normalized_status,
                },
            )
            PostgresAuditEventRepository(self.connection, self.tenant_id).append(
                actor_label=actor_label,
                object_type="intercompany_case",
                object_id=case_id,
                action="intercompany_case_settled",
                metadata={"settlement_status": normalized_status},
            )
            row = self.connection.execute(
                "SELECT id,workspace_id,period_name,entity_code,counterparty_code,reference,"
                "imbalance_amount,imbalance_amount_decimal,currency,status,dispute_owner,"
                "settlement_status,aging_days,evidence_note,created_at,updated_at "
                "FROM reconforge.intercompany_cases WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, case_id),
            ).fetchone()
            if row is None:
                raise PostgresIntercompanyError("Unable to read the settled intercompany case.")
            result = _row(row, self._CASE_COLUMNS)
        return result

    def cases(self, *, status: str = "") -> list[dict[str, Any]]:
        with self._transaction():
            query = (
                "SELECT id,workspace_id,period_name,entity_code,counterparty_code,reference,"
                "imbalance_amount,imbalance_amount_decimal,currency,status,dispute_owner,"
                "settlement_status,aging_days,evidence_note,created_at,updated_at "
                "FROM reconforge.intercompany_cases WHERE tenant_id=%s"
            )
            params: tuple[Any, ...] = (self.tenant_id,)
            if status:
                query += " AND status=%s"
                params += (status,)
            query += " ORDER BY created_at DESC,id"
            return [_row(item, self._CASE_COLUMNS) for item in self.connection.execute(query, params).fetchall()]

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self._transaction():
            row = self.connection.execute(
                "SELECT id,workspace_id,period_name,entity_code,counterparty_code,reference,"
                "imbalance_amount,imbalance_amount_decimal,currency,status,dispute_owner,"
                "settlement_status,aging_days,evidence_note,created_at,updated_at "
                "FROM reconforge.intercompany_cases WHERE tenant_id=%s AND id=%s",
                (self.tenant_id, case_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Intercompany case not found.")
            return _row(row, self._CASE_COLUMNS)


POSTGRES_INTERCOMPANY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.intercompany_transactions (
 tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
 id TEXT NOT NULL, workspace_id TEXT NOT NULL, transaction_id TEXT NOT NULL,
 period_name TEXT NOT NULL, entity_code TEXT NOT NULL, counterparty_code TEXT NOT NULL,
 posting_date TEXT NOT NULL, amount NUMERIC NOT NULL, amount_decimal TEXT NOT NULL,
 currency TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '', source_path TEXT NOT NULL,
 imported_at TEXT NOT NULL, PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,workspace_id,transaction_id),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.intercompany_cases (
 tenant_id TEXT NOT NULL REFERENCES reconforge.tenants(id) ON DELETE CASCADE,
 id TEXT NOT NULL, workspace_id TEXT NOT NULL, period_name TEXT NOT NULL,
 entity_code TEXT NOT NULL, counterparty_code TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '',
 imbalance_amount NUMERIC NOT NULL DEFAULT 0, imbalance_amount_decimal TEXT NOT NULL,
 currency TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, dispute_owner TEXT NOT NULL DEFAULT '',
 settlement_status TEXT NOT NULL DEFAULT 'Open', aging_days INTEGER NOT NULL DEFAULT 0 CHECK (aging_days >= 0),
 evidence_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (tenant_id,id),
 UNIQUE (tenant_id,workspace_id,period_name,entity_code,counterparty_code,reference),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_postgres_intercompany_transactions
 ON reconforge.intercompany_transactions(tenant_id,workspace_id,period_name,currency,reference);
CREATE INDEX IF NOT EXISTS idx_postgres_intercompany_cases
 ON reconforge.intercompany_cases(tenant_id,workspace_id,status,period_name,currency,reference);
DO $reconforge$
DECLARE table_name text;
BEGIN
 FOREACH table_name IN ARRAY ARRAY['intercompany_transactions','intercompany_cases'] LOOP
  EXECUTE format('ALTER TABLE reconforge.%I ENABLE ROW LEVEL SECURITY', table_name);
  EXECUTE format('ALTER TABLE reconforge.%I FORCE ROW LEVEL SECURITY', table_name);
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename=table_name AND policyname='tenant_scope') THEN
   EXECUTE format('CREATE POLICY tenant_scope ON reconforge.%I USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', table_name);
  END IF;
 END LOOP;
END $reconforge$;
"""


def install_postgres_intercompany_schema(connection: Any) -> None:
    """Install additive tenant-scoped intercompany tables."""

    connection.execute(POSTGRES_INTERCOMPANY_SCHEMA_SQL)
