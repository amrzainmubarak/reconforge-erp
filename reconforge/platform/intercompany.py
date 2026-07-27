"""Intercompany workflow foundations for exported local data."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconforge.domain.models import utc_now_text
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
)
from reconforge.platform.exceptions import ExceptionQueueService


@dataclass(frozen=True)
class IntercompanyImportResult:
    """Intercompany import result."""

    source_path: Path
    imported_rows: int


class IntercompanyService:
    """Local intercompany matching and case workflow."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def import_transactions(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        actor_label: str = "local-cli",
    ) -> IntercompanyImportResult:
        """Import local intercompany transactions."""

        require_permission(self.connection, actor_label=actor_label, permission="intercompany.manage")
        document = read_local_record_document(input_path)
        source_path = document.source_path
        records = document.records
        if not records:
            raise PlatformError("Intercompany input did not contain any records.")
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
                transaction_id = normalize_key(record.get("transaction_id") or record.get("id"), default="")
                if not transaction_id:
                    transaction_id = platform_id("ICREF", source_checksum, index)
                row_id = platform_id("IC", workspace_id, transaction_id)
                amount = _amount(record.get("amount"), field=f"intercompany row {index} amount")
                self.connection.execute(
                    """
                    INSERT INTO intercompany_transactions (
                        id, workspace_id, transaction_id, period_name, entity_code,
                        counterparty_code, posting_date, amount, amount_decimal, currency, reference,
                        source_path, imported_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, transaction_id)
                    DO UPDATE SET
                        period_name = excluded.period_name,
                        entity_code = excluded.entity_code,
                        counterparty_code = excluded.counterparty_code,
                        posting_date = excluded.posting_date,
                        amount = excluded.amount,
                        amount_decimal = excluded.amount_decimal,
                        currency = excluded.currency,
                        reference = excluded.reference,
                        source_path = excluded.source_path,
                        imported_at = excluded.imported_at
                    """,
                    (
                        row_id,
                        workspace_id,
                        transaction_id,
                        normalize_key(record.get("period") or record.get("period_name"), default=default_period),
                        normalize_key(record.get("entity") or record.get("entity_code"), default="local"),
                        normalize_key(record.get("counterparty") or record.get("counterparty_code"), default="unknown"),
                        normalize_key(record.get("posting_date") or record.get("date"), default=""),
                        str(amount),
                        _decimal_text(amount),
                        normalize_key(record.get("currency"), default="LOCAL"),
                        normalize_text(record.get("reference") or record.get("ref")),
                        source_path.name,
                        now,
                    ),
                )
                imported += 1
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to import intercompany transactions.") from exc
        append_outbox_event(
            self.connection,
            event_id=platform_id("OBX", "intercompany_import", workspace_id, source_checksum),
            event_type="intercompany.imported",
            aggregate_type="intercompany_import",
            aggregate_id=source_checksum,
            payload={"workspace_id": workspace_id, **source_metadata, "imported_rows": imported},
        )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="intercompany",
            object_id="import",
            action="intercompany_imported",
            metadata={**source_metadata, "imported_rows": imported},
        )
        return IntercompanyImportResult(source_path=source_path, imported_rows=imported)

    def match(
        self,
        *,
        workspace: str = "default",
        period_name: str = "",
        tolerance: object = Decimal("0.01"),
        actor_label: str = "local-cli",
    ) -> int:
        """Create intercompany cases for imbalances and unmatched counterparty rows."""

        require_permission(self.connection, actor_label=actor_label, permission="intercompany.manage")
        tolerance_amount = _non_negative_amount(tolerance, field="intercompany tolerance")
        workspace_id = ensure_workspace(self.connection, workspace)
        if period_name:
            rows = self.connection.execute(
                "SELECT * FROM intercompany_transactions WHERE workspace_id = ? AND period_name = ? ORDER BY reference, entity_code",
                (workspace_id, period_name),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM intercompany_transactions WHERE workspace_id = ? ORDER BY period_name, reference, entity_code",
                (workspace_id,),
            ).fetchall()
        grouped: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
        for row in rows:
            key = (str(row["period_name"]), str(row["reference"]), str(row["currency"]))
            grouped.setdefault(key, []).append(row)
        queue = ExceptionQueueService(self.connection, autocommit=False)
        case_count = 0
        now = utc_now_text()
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
                "ICC", workspace_id, period, str(first["entity_code"]), str(first["counterparty_code"]), reference
            )
            status = "Open"
            try:
                self.connection.execute(
                    """
                    INSERT INTO intercompany_cases (
                        id, workspace_id, period_name, entity_code, counterparty_code,
                        reference, imbalance_amount, imbalance_amount_decimal, currency, status, settlement_status,
                        aging_days, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Open', 0, ?, ?)
                    ON CONFLICT(workspace_id, period_name, entity_code, counterparty_code, reference)
                    DO UPDATE SET
                        imbalance_amount = excluded.imbalance_amount,
                        imbalance_amount_decimal = excluded.imbalance_amount_decimal,
                        currency = excluded.currency,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        case_id,
                        workspace_id,
                        period,
                        str(first["entity_code"]),
                        str(first["counterparty_code"]),
                        reference,
                        str(imbalance),
                        _decimal_text(imbalance),
                        currency,
                        status,
                        now,
                        now,
                    ),
                )
            except sqlite3.DatabaseError as exc:
                raise PlatformError("Unable to save intercompany case.") from exc
            queue.upsert_exception(
                source_type="intercompany",
                source_id=case_id,
                description="Intercompany reference has unmatched or imbalanced counterparty amounts.",
                workspace=workspace,
                period_name=period,
                entity_code=str(first["entity_code"]),
                risk_rating="high" if abs(imbalance) > tolerance_amount else "medium",
                actor_label=actor_label,
            )
            case_count += 1
        append_outbox_event(
            self.connection,
            event_id=platform_id("OBX", "intercompany_match", workspace_id, period_name, now),
            event_type="intercompany.matched",
            aggregate_type="intercompany_match",
            aggregate_id=platform_id("ICM", workspace_id, period_name),
            payload={"workspace_id": workspace_id, "period": period_name, "case_count": case_count},
        )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="intercompany",
            object_id="match",
            action="intercompany_matched",
            metadata={"period": period_name, "case_count": case_count, "tolerance": str(tolerance_amount)},
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
        """Update intercompany settlement status metadata."""

        require_permission(self.connection, actor_label=actor_label, permission="intercompany.manage")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                UPDATE intercompany_cases
                SET settlement_status = ?, dispute_owner = ?, evidence_note = ?, status = 'Resolved', updated_at = ?
                WHERE id = ?
                """,
                (normalize_key(settlement_status, default="Settled"), dispute_owner, evidence_note, now, case_id),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to update intercompany case.") from exc
        append_outbox_event(
            self.connection,
            event_id=platform_id("OBX", "intercompany_settle", case_id, now),
            event_type="intercompany.case_settled",
            aggregate_type="intercompany_case",
            aggregate_id=case_id,
            payload={"case_id": case_id, "settlement_status": settlement_status},
        )
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="intercompany_case",
            object_id=case_id,
            action="intercompany_case_settled",
            metadata={"settlement_status": settlement_status},
        )
        return self.get_case(case_id)

    def cases(self, *, status: str = "") -> list[dict[str, Any]]:
        """List intercompany cases."""

        if status:
            rows = self.connection.execute(
                "SELECT * FROM intercompany_cases WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM intercompany_cases ORDER BY created_at DESC").fetchall()
        return rows_to_dicts(rows)

    def get_case(self, case_id: str) -> dict[str, Any]:
        """Read one intercompany case."""

        row = self.connection.execute("SELECT * FROM intercompany_cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise PlatformError("Intercompany case not found.")
        return dict(row)


def _amount(value: object, *, field: str) -> Decimal:
    return parse_financial_amount(value, field=field)


def _non_negative_amount(value: object, *, field: str) -> Decimal:
    parsed = _amount(value, field=field)
    if parsed < 0:
        raise PlatformError(f"Financial amount in field '{field}' cannot be negative.")
    return parsed


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")
