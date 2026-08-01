"""SQLite persistence adapter for account reconciliation lifecycles."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconforge.application.accounts import ImportTrialBalanceResult
from reconforge.auth.rbac import same_actor
from reconforge.db.connection import DatabaseError
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    append_outbox_event,
    commit_audited,
    ensure_account,
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
from reconforge.workflow import WorkflowRepositoryError, WorkflowService, WorkflowServiceError

ACCOUNT_STATUSES = {"Draft", "Prepared", "In Review", "Reviewed", "Complete", "Needs Follow-up", "Accepted Risk"}


class SQLiteAccountReconciliationRepository:
    """Own local account-reconciliation persistence and policy effects."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        try:
            decimal_schema = connection.execute(
                "SELECT 1 FROM pragma_table_info('account_reconciliation_records') WHERE name = 'balance_decimal'",
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise DatabaseError("Unable to read the account reconciliation schema.") from exc
        if decimal_schema is None:
            raise DatabaseError(
                "Account reconciliation Decimal columns are not initialized. Run 'reconforge db migrate' first."
            )
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
        document = read_local_record_document(input_path)
        source_path = document.source_path
        records = document.records
        if not records:
            raise PlatformError("Trial balance input did not contain any records.")
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
        rec_count = 0
        try:
            for index, record in enumerate(records, start=1):
                period_name = normalize_key(record.get("period") or record.get("period_name"), default=default_period)
                entity_code = normalize_key(record.get("entity") or record.get("entity_code"), default=default_entity)
                account_code = normalize_key(
                    record.get("account_code") or record.get("account") or record.get("account_number"), default=""
                )
                if not account_code:
                    raise PlatformError("Trial balance rows require account_code.")
                account_name = normalize_text(record.get("account_name") or record.get("name"), default=account_code)
                raw_balance = _first_present(record, ("balance", "amount", "ending_balance"))
                balance = _amount(raw_balance, field=f"trial balance row {index} balance")
                currency = _currency(record.get("currency"))
                ensure_account(
                    self.connection, workspace_id=workspace_id, account_code=account_code, account_name=account_name
                )
                row_id = platform_id("TB", workspace_id, period_name, entity_code, account_code, source_checksum, index)
                self.connection.execute(
                    """
                    INSERT INTO trial_balance_rows (
                        id, workspace_id, period_name, entity_code, account_code, account_name,
                        balance, balance_decimal, currency, source_path, source_row_number, imported_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id, period_name, entity_code, account_code, source_path, source_row_number)
                    DO UPDATE SET
                        account_name = excluded.account_name,
                        balance = excluded.balance,
                        balance_decimal = excluded.balance_decimal,
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
                        str(balance),
                        _decimal_text(balance),
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
                    currency_code=currency,
                    actor_label=actor_label,
                    finalize=False,
                )
                rec_count += 1
            _finalize_account_event(
                self.connection,
                event_id=platform_id("OBX", "account_trial_balance_import", workspace_id, source_checksum),
                event_type="accounts.trial_balance_imported",
                aggregate_type="account_reconciliation_import",
                aggregate_id=platform_id("ARIMP", workspace_id, source_checksum),
                payload={"workspace_id": workspace_id, **source_metadata, "imported_rows": imported},
                actor_label=actor_label,
                object_type="account_reconciliation",
                object_id="trial_balance_import",
                action="trial_balance_imported",
                metadata={**source_metadata, "imported_rows": imported, "records": rec_count},
            )
        except (PlatformError, sqlite3.DatabaseError):
            self.connection.rollback()
            raise
        return ImportTrialBalanceResult(
            source_path=source_path, imported_rows=imported, reconciliation_records=rec_count
        )

    def create_template(
        self,
        *,
        account_code: str,
        name: str = "",
        workspace: str = "default",
        risk_rating: str = "medium",
        materiality_threshold: object = Decimal("0"),
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
        threshold = _non_negative_amount(materiality_threshold, field="materiality threshold")
        try:
            self.connection.execute(
                """
                INSERT INTO account_reconciliation_templates (
                    id, workspace_id, account_code, name, risk_rating, materiality_threshold,
                    materiality_threshold_decimal,
                    required_evidence, owner, reviewer, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, account_code)
                DO UPDATE SET
                    name = excluded.name,
                    risk_rating = excluded.risk_rating,
                    materiality_threshold = excluded.materiality_threshold,
                    materiality_threshold_decimal = excluded.materiality_threshold_decimal,
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
                    str(threshold),
                    _decimal_text(threshold),
                    required_evidence,
                    owner,
                    reviewer,
                    now,
                    now,
                ),
            )
            _finalize_account_event(
                self.connection,
                event_id=platform_id("OBX", "account_template", template_id, "saved"),
                event_type="accounts.template.saved",
                aggregate_type="account_reconciliation_template",
                aggregate_id=template_id,
                payload={"template_id": template_id, "account_code": code},
                actor_label=actor_label,
                object_type="account_reconciliation_template",
                object_id=template_id,
                action="account_template_saved",
                metadata={"account_code": code, "risk_rating": risk_rating},
            )
        except (PlatformError, sqlite3.DatabaseError):
            self.connection.rollback()
            raise
        return self.get_template(template_id)

    def create_reconciliation(
        self,
        *,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str = "",
        workspace: str = "default",
        balance: object = Decimal("0"),
        owner: str = "",
        preparer: str = "",
        reviewer: str = "",
        risk_rating: str = "medium",
        materiality_threshold: object = Decimal("0"),
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
            currency_code="LOCAL",
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
        return self._transition_record(
            record["id"],
            "Prepared",
            actor_label=actor,
            field_updates={"preparer": actor, "prepared_at": utc_now_text()},
        )

    def submit(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        """Submit a prepared reconciliation for review."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.prepare")
        return self._transition_record(
            reconciliation_id, "In Review", actor_label=actor_label, field_updates={"submitted_at": utc_now_text()}
        )

    def review(self, reconciliation_id: str, *, reviewer: str = "", actor_label: str = "local-cli") -> dict[str, Any]:
        """Review a submitted reconciliation with SoD enforced by workflow history."""

        require_permission(self.connection, actor_label=actor_label, permission="accounts.review")
        record = self.get_reconciliation(reconciliation_id)
        actual_reviewer = normalize_text(reviewer, default=actor_label)
        if same_actor(record.get("preparer"), actual_reviewer):
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
        return self._transition_record(
            reconciliation_id, "Complete", actor_label=actor_label, field_updates={"completed_at": utc_now_text()}
        )

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
                balance=Decimal("0"),
                owner=str(row["owner"]),
                preparer="",
                reviewer=str(row["reviewer"]),
                risk_rating=str(row["risk_rating"]),
                materiality_threshold=str(row["materiality_threshold_decimal"]),
                currency_code=str(row["currency_code"]),
                actor_label=actor_label,
                finalize=False,
            )
            count += 1
        _finalize_account_event(
            self.connection,
            event_id=platform_id("OBX", "account_roll_forward", workspace_id, from_period, to_period),
            event_type="accounts.reconciliations.rolled_forward",
            aggregate_type="account_reconciliation_roll_forward",
            aggregate_id=platform_id("ARF", workspace_id, from_period, to_period),
            payload={"workspace_id": workspace_id, "from_period": from_period, "to_period": to_period, "count": count},
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
            (
                status,
                status,
                owner,
                owner,
                period_name,
                period_name,
                entity_code,
                entity_code,
                risk_rating,
                risk_rating,
            ),
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

        row = self.connection.execute(
            "SELECT * FROM account_reconciliation_templates WHERE id = ?", (template_id,)
        ).fetchone()
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
        balance: Decimal,
        currency_code: str,
        actor_label: str,
        finalize: bool,
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
            materiality_threshold=(str(template["materiality_threshold_decimal"]) if template is not None else "0"),
            currency_code=currency_code,
            template_id=str(template["id"]) if template is not None else None,
            actor_label=actor_label,
            finalize=finalize,
        )

    def _upsert_record(
        self,
        *,
        workspace_id: str,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str,
        balance: object,
        owner: str,
        preparer: str,
        reviewer: str,
        risk_rating: str,
        materiality_threshold: object,
        currency_code: str,
        actor_label: str,
        template_id: str | None = None,
        finalize: bool = True,
    ) -> dict[str, Any]:
        period = normalize_key(period_name, default="current")
        entity = normalize_key(entity_code, default="local")
        code = normalize_key(account_code, default="")
        if not code:
            raise PlatformError("Account code is required.")
        parsed_balance = _amount(balance, field="reconciliation balance")
        parsed_threshold = _non_negative_amount(materiality_threshold, field="materiality threshold")
        currency = _currency(currency_code)
        rec_id = platform_id("AR", workspace_id, period, entity, code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO account_reconciliation_records (
                    id, workspace_id, period_name, entity_code, account_code, account_name,
                    template_id, status, balance, balance_decimal, materiality_threshold,
                    materiality_threshold_decimal, currency_code, risk_rating,
                    owner, preparer, reviewer, aging_days, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(workspace_id, period_name, entity_code, account_code)
                DO UPDATE SET
                    account_name = excluded.account_name,
                    template_id = COALESCE(excluded.template_id, account_reconciliation_records.template_id),
                    balance = excluded.balance,
                    balance_decimal = excluded.balance_decimal,
                    materiality_threshold = excluded.materiality_threshold,
                    materiality_threshold_decimal = excluded.materiality_threshold_decimal,
                    currency_code = excluded.currency_code,
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
                    str(parsed_balance),
                    _decimal_text(parsed_balance),
                    str(parsed_threshold),
                    _decimal_text(parsed_threshold),
                    currency,
                    normalize_key(risk_rating, default="medium").lower(),
                    owner,
                    preparer,
                    reviewer,
                    now,
                    now,
                ),
            )
            self._ensure_workflow_object(rec_id)
            self._upsert_balance_item(rec_id, balance=parsed_balance, materiality_threshold=parsed_threshold)
            if finalize:
                _finalize_account_event(
                    self.connection,
                    event_id=platform_id("OBX", "account_reconciliation", rec_id, "saved"),
                    event_type="accounts.reconciliation.saved",
                    aggregate_type="account_reconciliation",
                    aggregate_id=rec_id,
                    payload={"reconciliation_id": rec_id, "period": period, "entity": entity, "account_code": code},
                    actor_label=actor_label,
                    object_type="account_reconciliation",
                    object_id=rec_id,
                    action="account_reconciliation_saved",
                    metadata={"period": period, "entity": entity, "account_code": code},
                )
        except (PlatformError, sqlite3.DatabaseError):
            self.connection.rollback()
            raise
        return self.get_reconciliation(rec_id)

    def _upsert_balance_item(self, reconciliation_id: str, *, balance: Decimal, materiality_threshold: Decimal) -> None:
        item_id = platform_id("ARI", reconciliation_id, "balance_support")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO account_reconciliation_items (
                    id, reconciliation_id, item_type, description, amount, amount_decimal, status, evidence_required, created_at
                )
                VALUES (?, ?, 'balance_support', 'Trial-balance balance support', ?, ?, 'Open', ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET
                    amount = excluded.amount,
                    amount_decimal = excluded.amount_decimal,
                    evidence_required = excluded.evidence_required
                """,
                (
                    item_id,
                    reconciliation_id,
                    str(balance),
                    _decimal_text(balance),
                    int(abs(balance) >= materiality_threshold if materiality_threshold else abs(balance) > 0),
                    now,
                ),
            )
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to save reconciliation item.") from exc

    def _ensure_workflow_object(self, reconciliation_id: str) -> None:
        service = WorkflowService(self.connection, autocommit=False)
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
            workflow_object = WorkflowService(self.connection, autocommit=False).perform_transition(
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
            _finalize_account_event(
                self.connection,
                event_id=platform_id("OBX", "account_reconciliation", reconciliation_id, "transitioned", to_status),
                event_type="accounts.reconciliation.transitioned",
                aggregate_type="account_reconciliation",
                aggregate_id=reconciliation_id,
                payload={"reconciliation_id": reconciliation_id, "to_status": to_status, "actor": actor_label},
                actor_label=actor_label,
                object_type="account_reconciliation",
                object_id=reconciliation_id,
                action="account_reconciliation_transitioned",
                metadata={"to_status": to_status},
            )
        except (PlatformError, sqlite3.DatabaseError):
            self.connection.rollback()
            raise
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


def _first_present(record: dict[str, Any], fields: tuple[str, ...]) -> object:
    """Return the first supplied amount field without treating zero as missing."""

    for field in fields:
        value = record.get(field)
        if value is not None and (not isinstance(value, str) or value.strip()):
            return value
    return None


def _amount(value: object, *, field: str) -> Decimal:
    return parse_financial_amount(value, field=field)


def _non_negative_amount(value: object, *, field: str) -> Decimal:
    parsed = _amount(value, field=field)
    if parsed < 0:
        raise PlatformError(f"Financial amount in field '{field}' cannot be negative.")
    return parsed


def _currency(value: object) -> str:
    code = normalize_key(value, default="LOCAL").upper()
    if not 3 <= len(code) <= 12 or not code.isalpha():
        raise PlatformError("Currency code must be alphabetic and between 3 and 12 characters.")
    return code


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _finalize_account_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    actor_label: str,
    object_type: str,
    object_id: str,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append account outbox/audit evidence and commit the caller transaction."""

    try:
        append_outbox_event(
            connection,
            event_id=event_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        commit_audited(
            connection,
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )
    except (PlatformError, sqlite3.DatabaseError):
        connection.rollback()
        raise
