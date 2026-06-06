"""DB-backed account reconciliation lifecycle foundations."""

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
    ensure_account,
    ensure_platform_schema,
    ensure_workspace,
    normalize_key,
    normalize_text,
    platform_id,
    read_local_records,
    require_permission,
    rows_to_dicts,
    to_float,
)
from reconforge.workflow import WorkflowRepositoryError, WorkflowService, WorkflowServiceError

ACCOUNT_STATUSES = {"Draft", "Prepared", "In Review", "Reviewed", "Complete", "Needs Follow-up", "Accepted Risk"}


@dataclass(frozen=True)
class ImportTrialBalanceResult:
    """Result from importing local trial-balance rows."""

    source_path: Path
    imported_rows: int
    reconciliation_records: int


class AccountReconciliationService:
    """Service for local DB-backed account reconciliation records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

    def import_trial_balance(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        default_entity: str = "local",
        actor_label: str = "local-cli",
    ) -> ImportTrialBalanceResult:
        """Import CSV/JSON trial-balance rows and create draft reconciliation records."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.prepare")
        source_path, records = read_local_records(input_path)
        if not records:
            raise PlatformError("Trial balance input did not contain any records.")
        workspace_id = ensure_workspace(self.connection, workspace)
        source_checksum = checksum_file(source_path)
        now = utc_now_text()
        imported = 0
        rec_count = 0
        try:
            for index, record in enumerate(records, start=1):
                period_name = normalize_key(record.get("period") or record.get("period_name"), default=default_period)
                entity_code = normalize_key(record.get("entity") or record.get("entity_code"), default=default_entity)
                account_code = normalize_key(record.get("account_code") or record.get("account") or record.get("account_number"), default="")
                if not account_code:
                    raise PlatformError("Trial balance rows require account_code.")
                account_name = normalize_text(record.get("account_name") or record.get("name"), default=account_code)
                balance = to_float(record.get("balance") or record.get("amount") or record.get("ending_balance"))
                currency = normalize_key(record.get("currency"), default="LOCAL")
                ensure_account(self.connection, workspace_id=workspace_id, account_code=account_code, account_name=account_name)
                row_id = platform_id("TB", workspace_id, period_name, entity_code, account_code, source_checksum, index)
                self.connection.execute(
                    """
                    INSERT INTO trial_balance_rows (
                        id, workspace_id, period_name, entity_code, account_code, account_name,
                        balance, currency, source_path, source_row_number, imported_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, period_name, entity_code, account_code, source_path, source_row_number)
                    DO UPDATE SET
                        account_name = excluded.account_name,
                        balance = excluded.balance,
                        currency = excluded.currency,
                        imported_at = excluded.imported_at
                    """,
                    (
                        row_id,
                        workspace_id,
                        period_name,
                        entity_code,
                        account_code,
                        account_name,
                        balance,
                        currency,
                        source_path.name,
                        index,
                        now,
                    ),
                )
                imported += 1
                self._upsert_record_from_trial_balance(
                    workspace_id=workspace_id,
                    period_name=period_name,
                    entity_code=entity_code,
                    account_code=account_code,
                    account_name=account_name,
                    balance=balance,
                    actor_label=actor_label,
                )
                rec_count += 1
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to import trial balance records.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="account_reconciliation",
            object_id="trial_balance_import",
            action="trial_balance_imported",
            metadata={"source_file": source_path.name, "imported_rows": imported, "records": rec_count},
        )
        return ImportTrialBalanceResult(source_path=source_path, imported_rows=imported, reconciliation_records=rec_count)

    def create_template(
        self,
        *,
        account_code: str,
        name: str = "",
        workspace: str = "default",
        risk_rating: str = "medium",
        materiality_threshold: float = 0.0,
        required_evidence: str = "",
        owner: str = "",
        reviewer: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update an account reconciliation template."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.prepare")
        workspace_id = ensure_workspace(self.connection, workspace)
        code = normalize_key(account_code, default="")
        if not code:
            raise PlatformError("Account code is required.")
        template_id = platform_id("ART", workspace_id, code)
        now = utc_now_text()
        template_name = normalize_text(name, default=f"{code} reconciliation")
        try:
            self.connection.execute(
                """
                INSERT INTO account_reconciliation_templates (
                    id, workspace_id, account_code, name, risk_rating, materiality_threshold,
                    required_evidence, owner, reviewer, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, account_code)
                DO UPDATE SET
                    name = excluded.name,
                    risk_rating = excluded.risk_rating,
                    materiality_threshold = excluded.materiality_threshold,
                    required_evidence = excluded.required_evidence,
                    owner = excluded.owner,
                    reviewer = excluded.reviewer,
                    updated_at = excluded.updated_at
                """,
                (
                    template_id,
                    workspace_id,
                    code,
                    template_name,
                    normalize_key(risk_rating, default="medium").lower(),
                    materiality_threshold,
                    required_evidence,
                    owner,
                    reviewer,
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save account reconciliation template.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="account_reconciliation_template",
            object_id=template_id,
            action="account_template_saved",
            metadata={"account_code": code, "risk_rating": risk_rating},
        )
        return self.get_template(template_id)

    def create_reconciliation(
        self,
        *,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str = "",
        workspace: str = "default",
        balance: float = 0.0,
        owner: str = "",
        preparer: str = "",
        reviewer: str = "",
        risk_rating: str = "medium",
        materiality_threshold: float = 0.0,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update one draft account reconciliation record."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.prepare")
        workspace_id = ensure_workspace(self.connection, workspace)
        return self._upsert_record(
            workspace_id=workspace_id,
            period_name=period_name,
            entity_code=entity_code,
            account_code=account_code,
            account_name=account_name or account_code,
            balance=balance,
            owner=owner,
            preparer=preparer,
            reviewer=reviewer,
            risk_rating=risk_rating,
            materiality_threshold=materiality_threshold,
            actor_label=actor_label,
        )

    def prepare(
        self,
        *,
        reconciliation_id: str | None = None,
        workspace: str = "default",
        period_name: str = "current",
        entity_code: str = "local",
        account_code: str = "",
        preparer: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Mark a reconciliation prepared."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.prepare")
        record = self._record_by_id_or_keys(
            reconciliation_id=reconciliation_id,
            workspace=workspace,
            period_name=period_name,
            entity_code=entity_code,
            account_code=account_code,
        )
        actor = normalize_text(preparer, default=actor_label)
        return self._transition_record(record["id"], "Prepared", actor_label=actor, field_updates={"preparer": actor, "prepared_at": utc_now_text()})

    def submit(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        """Submit a prepared reconciliation for review."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.prepare")
        return self._transition_record(reconciliation_id, "In Review", actor_label=actor_label, field_updates={"submitted_at": utc_now_text()})

    def review(self, reconciliation_id: str, *, reviewer: str = "", actor_label: str = "local-cli") -> dict[str, Any]:
        """Review a submitted reconciliation with SoD enforced by workflow history."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.review")
        record = self.get_reconciliation(reconciliation_id)
        actual_reviewer = normalize_text(reviewer, default=actor_label)
        if normalize_text(record.get("preparer")).lower() == actual_reviewer.lower() and actual_reviewer:
            raise PlatformError("Separation of duties conflict: preparer and reviewer must be different.")
        return self._transition_record(
            reconciliation_id,
            "Reviewed",
            actor_label=actual_reviewer,
            field_updates={"reviewer": actual_reviewer, "reviewed_at": utc_now_text()},
        )

    def complete(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        """Complete a reviewed account reconciliation."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.complete")
        return self._transition_record(reconciliation_id, "Complete", actor_label=actor_label, field_updates={"completed_at": utc_now_text()})

    def roll_forward(
        self,
        *,
        from_period: str,
        to_period: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> int:
        """Create draft reconciliations for a new period from the previous period."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.prepare")
        workspace_id = ensure_workspace(self.connection, workspace)
        rows = self.connection.execute(
            """
            SELECT * FROM account_reconciliation_records
            WHERE workspace_id = ? AND period_name = ?
            ORDER BY entity_code, account_code
            """,
            (workspace_id, from_period),
        ).fetchall()
        count = 0
        for row in rows:
            self._upsert_record(
                workspace_id=workspace_id,
                period_name=to_period,
                entity_code=str(row["entity_code"]),
                account_code=str(row["account_code"]),
                account_name=str(row["account_name"]),
                balance=0.0,
                owner=str(row["owner"]),
                preparer="",
                reviewer=str(row["reviewer"]),
                risk_rating=str(row["risk_rating"]),
                materiality_threshold=float(row["materiality_threshold"]),
                actor_label=actor_label,
            )
            count += 1
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="account_reconciliation",
            object_id="roll_forward",
            action="account_reconciliations_rolled_forward",
            metadata={"from_period": from_period, "to_period": to_period, "count": count},
        )
        return count

    def list_reconciliations(
        self,
        *,
        status: str = "",
        owner: str = "",
        period_name: str = "",
        entity_code: str = "",
        risk_rating: str = "",
    ) -> list[dict[str, Any]]:
        """List reconciliation records with queue filters."""

        rows = self.connection.execute(
            """
            SELECT * FROM account_reconciliation_records
            WHERE (? = '' OR status = ?)
              AND (? = '' OR owner = ?)
              AND (? = '' OR period_name = ?)
              AND (? = '' OR entity_code = ?)
              AND (? = '' OR risk_rating = ?)
            ORDER BY period_name, entity_code, risk_rating DESC, account_code
            """,
            (status, status, owner, owner, period_name, period_name, entity_code, entity_code, risk_rating, risk_rating),
        ).fetchall()
        return rows_to_dicts(rows)

    def get_reconciliation(self, reconciliation_id: str) -> dict[str, Any]:
        """Get one reconciliation record."""

        row = self.connection.execute(
            "SELECT * FROM account_reconciliation_records WHERE id = ?",
            (reconciliation_id,),
        ).fetchone()
        if row is None:
            raise PlatformError("Account reconciliation record not found.")
        record = dict(row)
        record["items"] = rows_to_dicts(
            self.connection.execute(
                "SELECT * FROM account_reconciliation_items WHERE reconciliation_id = ? ORDER BY created_at, id",
                (reconciliation_id,),
            ).fetchall(),
        )
        return record

    def get_template(self, template_id: str) -> dict[str, Any]:
        """Get one reconciliation template."""

        row = self.connection.execute("SELECT * FROM account_reconciliation_templates WHERE id = ?", (template_id,)).fetchone()
        if row is None:
            raise PlatformError("Account reconciliation template not found.")
        return dict(row)

    def _upsert_record_from_trial_balance(
        self,
        *,
        workspace_id: str,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str,
        balance: float,
        actor_label: str,
    ) -> dict[str, Any]:
        template = self.connection.execute(
            """
            SELECT * FROM account_reconciliation_templates
            WHERE workspace_id = ? AND account_code = ?
            """,
            (workspace_id, account_code),
        ).fetchone()
        return self._upsert_record(
            workspace_id=workspace_id,
            period_name=period_name,
            entity_code=entity_code,
            account_code=account_code,
            account_name=account_name,
            balance=balance,
            owner=str(template["owner"]) if template is not None else "",
            preparer="",
            reviewer=str(template["reviewer"]) if template is not None else "",
            risk_rating=str(template["risk_rating"]) if template is not None else "medium",
            materiality_threshold=float(template["materiality_threshold"]) if template is not None else 0.0,
            template_id=str(template["id"]) if template is not None else None,
            actor_label=actor_label,
        )

    def _upsert_record(
        self,
        *,
        workspace_id: str,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str,
        balance: float,
        owner: str,
        preparer: str,
        reviewer: str,
        risk_rating: str,
        materiality_threshold: float,
        actor_label: str,
        template_id: str | None = None,
    ) -> dict[str, Any]:
        period = normalize_key(period_name, default="current")
        entity = normalize_key(entity_code, default="local")
        code = normalize_key(account_code, default="")
        if not code:
            raise PlatformError("Account code is required.")
        rec_id = platform_id("AR", workspace_id, period, entity, code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO account_reconciliation_records (
                    id, workspace_id, period_name, entity_code, account_code, account_name,
                    template_id, status, balance, materiality_threshold, risk_rating,
                    owner, preparer, reviewer, aging_days, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(workspace_id, period_name, entity_code, account_code)
                DO UPDATE SET
                    account_name = excluded.account_name,
                    template_id = COALESCE(excluded.template_id, account_reconciliation_records.template_id),
                    balance = excluded.balance,
                    materiality_threshold = excluded.materiality_threshold,
                    risk_rating = excluded.risk_rating,
                    owner = CASE WHEN excluded.owner != '' THEN excluded.owner ELSE account_reconciliation_records.owner END,
                    reviewer = CASE WHEN excluded.reviewer != '' THEN excluded.reviewer ELSE account_reconciliation_records.reviewer END,
                    updated_at = excluded.updated_at
                """,
                (
                    rec_id,
                    workspace_id,
                    period,
                    entity,
                    code,
                    normalize_text(account_name, default=code),
                    template_id,
                    balance,
                    materiality_threshold,
                    normalize_key(risk_rating, default="medium").lower(),
                    owner,
                    preparer,
                    reviewer,
                    now,
                    now,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save account reconciliation record.") from exc
        self._ensure_workflow_object(rec_id)
        self._upsert_balance_item(rec_id, balance=balance, materiality_threshold=materiality_threshold)
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="account_reconciliation",
            object_id=rec_id,
            action="account_reconciliation_saved",
            metadata={"period": period, "entity": entity, "account_code": code},
        )
        return self.get_reconciliation(rec_id)

    def _upsert_balance_item(self, reconciliation_id: str, *, balance: float, materiality_threshold: float) -> None:
        item_id = platform_id("ARI", reconciliation_id, "balance_support")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO account_reconciliation_items (
                    id, reconciliation_id, item_type, description, amount, status, evidence_required, created_at
                )
                VALUES (?, ?, 'balance_support', 'Trial-balance balance support', ?, 'Open', ?, ?)
                """,
                (item_id, reconciliation_id, balance, int(abs(balance) >= materiality_threshold if materiality_threshold else abs(balance) > 0), now),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save reconciliation item.") from exc

    def _ensure_workflow_object(self, reconciliation_id: str) -> None:
        service = WorkflowService(self.connection)
        try:
            service.initialize_object(object_type="reconciliation", object_id=reconciliation_id, status="Draft")
        except WorkflowServiceError as exc:
            if "already exists" not in str(exc).lower():
                raise PlatformError(str(exc)) from exc

    def _transition_record(
        self,
        reconciliation_id: str,
        to_status: str,
        *,
        actor_label: str,
        field_updates: dict[str, Any],
    ) -> dict[str, Any]:
        if to_status not in ACCOUNT_STATUSES:
            raise PlatformError("Unsupported account reconciliation status.")
        try:
            workflow_object = WorkflowService(self.connection).perform_transition(
                object_type="reconciliation",
                object_id=reconciliation_id,
                to_status=to_status,
                actor_label=actor_label,
                reason="Account reconciliation lifecycle update",
            )
        except (WorkflowRepositoryError, WorkflowServiceError) as exc:
            raise PlatformError(str(exc)) from exc
        updated_at = utc_now_text()
        try:
            self.connection.execute(
                """
                UPDATE account_reconciliation_records
                SET status = ?,
                    updated_at = ?,
                    preparer = COALESCE(?, preparer),
                    prepared_at = COALESCE(?, prepared_at),
                    submitted_at = COALESCE(?, submitted_at),
                    reviewer = COALESCE(?, reviewer),
                    reviewed_at = COALESCE(?, reviewed_at),
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (
                    workflow_object.status,
                    updated_at,
                    field_updates.get("preparer"),
                    field_updates.get("prepared_at"),
                    field_updates.get("submitted_at"),
                    field_updates.get("reviewer"),
                    field_updates.get("reviewed_at"),
                    field_updates.get("completed_at"),
                    reconciliation_id,
                ),
            )
            self.connection.commit()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to update account reconciliation status.") from exc
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="account_reconciliation",
            object_id=reconciliation_id,
            action="account_reconciliation_transitioned",
            metadata={"to_status": to_status},
        )
        return self.get_reconciliation(reconciliation_id)

    def _record_by_id_or_keys(
        self,
        *,
        reconciliation_id: str | None,
        workspace: str,
        period_name: str,
        entity_code: str,
        account_code: str,
    ) -> dict[str, Any]:
        if reconciliation_id:
            return self.get_reconciliation(reconciliation_id)
        workspace_id = ensure_workspace(self.connection, workspace)
        rec_id = platform_id("AR", workspace_id, period_name, entity_code, account_code)
        return self.get_reconciliation(rec_id)
