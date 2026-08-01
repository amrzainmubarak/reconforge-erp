"""SQLite persistence adapter for deterministic journal controls."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconforge.application.journals import JournalImportResult
from reconforge.domain.journal_controls import JournalPolicyError, evaluate_journal_policies, journal_threshold
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.sqlite_exceptions import SQLiteExceptionQueueRepository
from reconforge.platform.common import (
    PlatformError,
    append_outbox_event,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    parse_financial_amount,
    platform_id,
    read_local_record_document,
    require_permission,
    rows_to_dicts,
    to_bool,
)


class SQLiteJournalControlRepository:
    """Own SQLite transactions and deterministic journal policy persistence."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def import_journals(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        default_entity: str = "local",
        actor_label: str = "local-cli",
    ) -> JournalImportResult:
        require_permission(self.connection, actor_label=actor_label, permission="journals.manage")
        document = read_local_record_document(input_path)
        source_path = document.source_path
        records = document.records
        if not records:
            raise PlatformError("Journal input did not contain any records.")
        workspace_id = ensure_workspace(self.connection, workspace)
        source_checksum = document.checksum_sha256
        source_metadata = {
            "source_file": source_path.name,
            "source_checksum_sha256": source_checksum,
            "source_size_bytes": document.size_bytes,
            "ingress_profile": document.profile_id,
        }
        now = utc_now_text()
        imported = 0
        try:
            for index, record in enumerate(records, start=1):
                journal_id = normalize_key(
                    record.get("journal_id") or record.get("id") or record.get("entry_id"), default=""
                )
                if not journal_id:
                    journal_id = platform_id("JREF", source_checksum, index)
                row_id = platform_id("JRN", workspace_id, journal_id)
                amount = parse_financial_amount(record.get("amount"), field=f"journal row {index} amount")
                self.connection.execute(
                    """
                    INSERT INTO journal_entries (
                        id, workspace_id, journal_id, period_name, entity_code, posting_date,
                        account_code, amount, amount_decimal, currency, reference, approver, is_manual,
                        source_path, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, journal_id) DO UPDATE SET
                        period_name = excluded.period_name, entity_code = excluded.entity_code,
                        posting_date = excluded.posting_date, account_code = excluded.account_code,
                        amount = excluded.amount, amount_decimal = excluded.amount_decimal,
                        currency = excluded.currency, reference = excluded.reference,
                        approver = excluded.approver, is_manual = excluded.is_manual,
                        source_path = excluded.source_path, imported_at = excluded.imported_at
                    """,
                    (
                        row_id,
                        workspace_id,
                        journal_id,
                        normalize_key(record.get("period") or record.get("period_name"), default=default_period),
                        normalize_key(record.get("entity") or record.get("entity_code"), default=default_entity),
                        normalize_key(record.get("posting_date") or record.get("date"), default=""),
                        normalize_key(record.get("account_code") or record.get("account"), default="UNKNOWN"),
                        str(amount),
                        _decimal_text(amount),
                        normalize_key(record.get("currency"), default="LOCAL"),
                        normalize_text(record.get("reference") or record.get("ref")),
                        normalize_text(record.get("approver") or record.get("approved_by")),
                        int(to_bool(record.get("is_manual") or record.get("manual"))),
                        source_path.name,
                        now,
                    ),
                )
                imported += 1
            append_outbox_event(
                self.connection,
                event_id=platform_id("OB", workspace_id, "journal_import", source_checksum),
                event_type="journal.imported",
                aggregate_type="journal_import",
                aggregate_id=source_checksum,
                payload={"workspace_id": workspace_id, **source_metadata, "imported_rows": imported},
            )
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="journal",
                object_id="import",
                action="journals_imported",
                metadata={**source_metadata, "imported_rows": imported},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to import journal entries.") from exc
        return JournalImportResult(source_path=source_path, imported_rows=imported)

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
        require_permission(self.connection, actor_label=actor_label, permission="journals.manage")
        try:
            threshold = journal_threshold(high_value_threshold)
        except JournalPolicyError as exc:
            raise PlatformError(str(exc)) from exc
        workspace_id = ensure_workspace(self.connection, workspace)
        high_risk = {item.strip() for item in high_risk_accounts.split(",") if item.strip()}
        if period_name:
            rows = self.connection.execute(
                "SELECT * FROM journal_entries WHERE workspace_id = ? AND period_name = ? ORDER BY journal_id",
                (workspace_id, period_name),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM journal_entries WHERE workspace_id = ? ORDER BY period_name, journal_id",
                (workspace_id,),
            ).fetchall()
        count = 0
        queue = SQLiteExceptionQueueRepository(self.connection, autocommit=False)
        try:
            for row in rows:
                for policy_code, risk_rating, description in evaluate_journal_policies(
                    row, period_end=period_end, high_value_threshold=threshold, high_risk_accounts=high_risk
                ):
                    exception_id = platform_id("JEX", row["id"], policy_code)
                    self.connection.execute(
                        """
                        INSERT INTO journal_exceptions (
                            id, journal_entry_id, policy_code, risk_rating, description, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, 'Open', ?)
                        ON CONFLICT(journal_entry_id, policy_code) DO UPDATE SET
                            risk_rating = excluded.risk_rating, description = excluded.description, status = 'Open'
                        """,
                        (exception_id, row["id"], policy_code, risk_rating, description, utc_now_text()),
                    )
                    queue.upsert_exception(
                        source_type="journal",
                        source_id=exception_id,
                        description=description,
                        workspace=workspace,
                        period_name=str(row["period_name"]),
                        entity_code=str(row["entity_code"]),
                        account_code=str(row["account_code"]),
                        risk_rating=risk_rating,
                        actor_label=actor_label,
                    )
                    count += 1
            append_outbox_event(
                self.connection,
                event_id=platform_id("OBX", "journal_policy_run", workspace_id, period_name, utc_now_text()),
                event_type="journal.policies_run",
                aggregate_type="journal_policy_run",
                aggregate_id=platform_id("JPR", workspace_id, period_name),
                payload={"workspace_id": workspace_id, "period": period_name, "exception_count": count},
            )
            commit_audited(
                self.connection,
                actor_label=actor_label,
                object_type="journal",
                object_id="policy_run",
                action="journal_policies_run",
                metadata={"period": period_name, "exception_count": count, "high_value_threshold": str(threshold)},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to run journal policies.") from exc
        return count

    def exceptions(self, *, period_name: str = "") -> list[dict[str, Any]]:
        query = """
            SELECT journal_exceptions.*, journal_entries.journal_id, journal_entries.period_name,
                   journal_entries.entity_code, journal_entries.account_code, journal_entries.amount,
                   journal_entries.amount_decimal
            FROM journal_exceptions
            JOIN journal_entries ON journal_entries.id = journal_exceptions.journal_entry_id
        """
        params: list[object] = []
        if period_name:
            query += " WHERE journal_entries.period_name = ?"
            params.append(period_name)
        query += " ORDER BY journal_exceptions.created_at DESC"
        return rows_to_dicts(self.connection.execute(query, params).fetchall())

    def report(self) -> dict[str, Any]:
        total = self.connection.execute("SELECT COUNT(*) AS count FROM journal_entries").fetchone()
        exceptions = self.connection.execute("SELECT COUNT(*) AS count FROM journal_exceptions").fetchone()
        high = self.connection.execute(
            "SELECT COUNT(*) AS count FROM journal_exceptions WHERE lower(risk_rating) IN ('high', 'critical')"
        ).fetchone()
        return {
            "journal_entries": int(total["count"] or 0),
            "journal_exceptions": int(exceptions["count"] or 0),
            "high_risk_exceptions": int(high["count"] or 0),
        }


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")
