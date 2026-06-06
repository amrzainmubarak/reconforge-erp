"""Journal controls expansion with deterministic local policies."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reconforge.db.exporter import checksum_file
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    audit,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    parse_date,
    platform_id,
    read_local_records,
    require_permission,
    rows_to_dicts,
    to_bool,
    to_float,
)
from reconforge.platform.exceptions import ExceptionQueueService


@dataclass(frozen=True)
class JournalImportResult:
    """Journal import result."""

    source_path: Path
    imported_rows: int


class JournalControlService:
    """Import journals and run deterministic policy checks."""

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
        """Import local CSV/JSON journal entries."""

        require_permission(self.connection, actor_label=actor_label, permission="journals.manage")
        source_path, records = read_local_records(input_path)
        if not records:
            raise PlatformError("Journal input did not contain any records.")
        workspace_id = ensure_workspace(self.connection, workspace)
        source_checksum = checksum_file(source_path)
        now = utc_now_text()
        imported = 0
        try:
            for index, record in enumerate(records, start=1):
                journal_id = normalize_key(record.get("journal_id") or record.get("id") or record.get("entry_id"), default="")
                if not journal_id:
                    journal_id = platform_id("JREF", source_checksum, index)
                row_id = platform_id("JRN", workspace_id, journal_id)
                self.connection.execute(
                    """
                    INSERT INTO journal_entries (
                        id, workspace_id, journal_id, period_name, entity_code, posting_date,
                        account_code, amount, currency, reference, approver, is_manual,
                        source_path, imported_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, journal_id)
                    DO UPDATE SET
                        period_name = excluded.period_name,
                        entity_code = excluded.entity_code,
                        posting_date = excluded.posting_date,
                        account_code = excluded.account_code,
                        amount = excluded.amount,
                        currency = excluded.currency,
                        reference = excluded.reference,
                        approver = excluded.approver,
                        is_manual = excluded.is_manual,
                        source_path = excluded.source_path,
                        imported_at = excluded.imported_at
                    """,
                    (
                        row_id,
                        workspace_id,
                        journal_id,
                        normalize_key(record.get("period") or record.get("period_name"), default=default_period),
                        normalize_key(record.get("entity") or record.get("entity_code"), default=default_entity),
                        normalize_key(record.get("posting_date") or record.get("date"), default=""),
                        normalize_key(record.get("account_code") or record.get("account"), default="UNKNOWN"),
                        to_float(record.get("amount")),
                        normalize_key(record.get("currency"), default="LOCAL"),
                        normalize_text(record.get("reference") or record.get("ref")),
                        normalize_text(record.get("approver") or record.get("approved_by")),
                        int(to_bool(record.get("is_manual") or record.get("manual"))),
                        source_path.name,
                        now,
                    ),
                )
                imported += 1
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to import journal entries.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="journal",
            object_id="import",
            action="journals_imported",
            metadata={"source_file": source_path.name, "imported_rows": imported},
        )
        return JournalImportResult(source_path=source_path, imported_rows=imported)

    def policy_run(
        self,
        *,
        workspace: str = "default",
        period_name: str = "",
        period_end: str = "",
        high_value_threshold: float = 100000.0,
        high_risk_accounts: str = "",
        actor_label: str = "local-cli",
    ) -> int:
        """Run deterministic journal policies and push exceptions to the unified queue."""

        require_permission(self.connection, actor_label=actor_label, permission="journals.manage")
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
        queue = ExceptionQueueService(self.connection)
        for row in rows:
            policies = self._policies_for_row(
                row,
                period_end=period_end,
                high_value_threshold=high_value_threshold,
                high_risk_accounts=high_risk,
            )
            for policy_code, risk_rating, description in policies:
                exception_id = platform_id("JEX", row["id"], policy_code)
                now = utc_now_text()
                self.connection.execute(
                    """
                    INSERT INTO journal_exceptions (
                        id, journal_entry_id, policy_code, risk_rating, description, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, 'Open', ?)
                    ON CONFLICT(journal_entry_id, policy_code)
                    DO UPDATE SET
                        risk_rating = excluded.risk_rating,
                        description = excluded.description,
                        status = 'Open'
                    """,
                    (exception_id, row["id"], policy_code, risk_rating, description, now),
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
        self.connection.commit()
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="journal",
            object_id="policy_run",
            action="journal_policies_run",
            metadata={"period": period_name, "exception_count": count},
        )
        return count

    def exceptions(self, *, period_name: str = "") -> list[dict[str, Any]]:
        """List journal policy exceptions."""

        query = """
            SELECT journal_exceptions.*, journal_entries.journal_id, journal_entries.period_name,
                   journal_entries.entity_code, journal_entries.account_code, journal_entries.amount
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
        """Return a compact journal controls report payload."""

        total = self.connection.execute("SELECT COUNT(*) AS count FROM journal_entries").fetchone()
        exceptions = self.connection.execute("SELECT COUNT(*) AS count FROM journal_exceptions").fetchone()
        high = self.connection.execute(
            "SELECT COUNT(*) AS count FROM journal_exceptions WHERE lower(risk_rating) IN ('high', 'critical')",
        ).fetchone()
        return {
            "journal_entries": int(total["count"] or 0),
            "journal_exceptions": int(exceptions["count"] or 0),
            "high_risk_exceptions": int(high["count"] or 0),
        }

    def _policies_for_row(
        self,
        row: sqlite3.Row,
        *,
        period_end: str,
        high_value_threshold: float,
        high_risk_accounts: set[str],
    ) -> list[tuple[str, str, str]]:
        policies: list[tuple[str, str, str]] = []
        posting_date = parse_date(row["posting_date"])
        period_end_date = parse_date(period_end)
        if bool(row["is_manual"]):
            policies.append(("MANUAL_JOURNAL", "medium", "Manual journal entry requires documented review."))
        if period_end_date is not None and posting_date is not None and posting_date > period_end_date:
            policies.append(("POST_PERIOD", "high", "Journal posting date is after the configured period end."))
        if posting_date is not None and posting_date.weekday() >= 5:
            policies.append(("WEEKEND_POSTING", "medium", "Journal was posted on a weekend date."))
        if not normalize_text(row["reference"]):
            policies.append(("MISSING_REFERENCE", "medium", "Journal is missing a source reference."))
        if not normalize_text(row["approver"]):
            policies.append(("MISSING_APPROVER", "high", "Journal is missing approver evidence/reference."))
        if abs(float(row["amount"])) >= high_value_threshold:
            policies.append(("HIGH_VALUE", "high", "Journal amount exceeds the configured high-value threshold."))
        if str(row["account_code"]) in high_risk_accounts:
            policies.append(("HIGH_RISK_ACCOUNT", "high", "Journal uses a configured high-risk account."))
        return policies
