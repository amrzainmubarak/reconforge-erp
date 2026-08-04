"""SQLite persistence for governed consolidation journals and period state."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from reconforge.application.consolidation_close import ConsolidationCloseSummary, build_translation_evidence
from reconforge.auth.rbac import same_actor
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_close_bundle import build_consolidation_close_bundle
from reconforge.domain.consolidation_lifecycle import (
    ConsolidationWorksheetResult,
    verify_consolidation_worksheet_payload,
)
from reconforge.domain.consolidation_statement import build_management_statement_package
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.sqlite_approvals import SQLiteApprovalRepository
from reconforge.io.persisted import (
    PersistedJsonError,
    decode_consolidation_worksheet,
    encode_consolidation_worksheet,
)
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)
from reconforge.platform.inventory_values import (
    MAX_AMOUNT_MINOR,
    choice,
    clean_text,
    code,
    document_number,
    iso_date,
    page,
)
from reconforge.utils.money import CurrencyRegistry, InvalidAmountError, Money

CONSOLIDATION_READ_PERMISSION = "finance_core.read"
CONSOLIDATION_PREPARE_PERMISSION = "finance_core.manage"
CONSOLIDATION_APPROVE_PERMISSION = "finance_core.validate"
CONSOLIDATION_RUN_STATUSES = ("Prepared", "Approved", "Posted", "ReversalPrepared", "Reversed")
MAX_PERSISTED_JOURNAL_LINES = 10_000


class JournalLineMaterial(TypedDict):
    account_type: str
    amount_decimal: str
    amount_minor: int
    currency_code: str
    elimination_id: str
    entity_code: str
    group_account_code: str
    source_digest: str
    source_line_id: str
    source_reference: str


class EffectLineMaterial(TypedDict):
    amount_minor: int
    currency_code: str
    run_line_id: str


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _positive_version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PlatformError("Expected version must be a positive integer.")
    return value


class SQLiteConsolidationCloseRepository:
    """Persist exact consolidation effects without writing to a source ERP."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        expected = {
            "consolidation_close_periods",
            "consolidation_period_events",
            "consolidation_runs",
            "consolidation_run_lines",
            "consolidation_effects",
            "consolidation_effect_lines",
        }
        try:
            existing = {
                str(row["name"])
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to inspect the local consolidation schema.") from exc
        if not expected <= existing:
            raise PlatformError("Consolidation close schema is unavailable. Run 'reconforge db migrate' first.")

    def _actor(self, actor_label: str, permission: str) -> str:
        user = require_permission(self.connection, actor_label=actor_label, permission=permission)
        return user.username if user is not None else clean_text(actor_label, "Actor label")

    def _currency(self, currency_code: str) -> dict[str, Any]:
        selected = code(currency_code, "Reporting currency")
        row = self.connection.execute(
            "SELECT code,minor_units,active FROM currencies WHERE code=?",
            (selected,),
        ).fetchone()
        if row is None or not bool(row["active"]):
            raise PlatformError("Consolidation requires an active local reporting currency.")
        try:
            registry_minor_units = CurrencyRegistry.get_precision(selected)
        except InvalidAmountError as exc:
            raise PlatformError("Consolidation reporting currency is absent from the runtime registry.") from exc
        if int(row["minor_units"]) != registry_minor_units:
            raise PlatformError("Local and runtime currency precision policies do not match.")
        return dict(row)

    @staticmethod
    def _dates(start: str, end: str, reporting: str) -> tuple[str, str, str]:
        start_date = iso_date(start, "Consolidation period start")
        end_date = iso_date(end, "Consolidation period end")
        reporting_date = iso_date(reporting, "Consolidation reporting date")
        if start_date is None or end_date is None or reporting_date is None:
            raise PlatformError("Consolidation dates are required.")
        if start_date > end_date or not start_date <= reporting_date <= end_date:
            raise PlatformError("Consolidation dates must form one ordered period containing the reporting date.")
        return start_date.isoformat(), end_date.isoformat(), reporting_date.isoformat()

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
        actor = self._actor(actor_label, CONSOLIDATION_PREPARE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, clean_text(workspace, "Workspace name"))
        group = code(group_code, "Consolidation group code")
        period_name = document_number(period_id, "Consolidation period ID")
        currency = self._currency(reporting_currency)
        start, end, reporting = self._dates(period_start_date, period_end_date, reporting_date)
        identifier = platform_id("CCP", workspace_id, group, period_name)
        existing = self.connection.execute(
            "SELECT * FROM consolidation_close_periods WHERE id=?",
            (identifier,),
        ).fetchone()
        if existing is not None:
            expected = (group, period_name, str(currency["code"]), start, end, reporting)
            actual = tuple(
                str(existing[key])
                for key in (
                    "group_code",
                    "period_name",
                    "reporting_currency",
                    "period_start_date",
                    "period_end_date",
                    "reporting_date",
                )
            )
            if actual != expected:
                raise PlatformError("Consolidation period identifier conflicts with existing financial policy.")
            return self._public_period(existing)
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO consolidation_close_periods(
                    id,workspace_id,group_code,period_name,reporting_currency,
                    period_start_date,period_end_date,reporting_date,status,row_version,
                    created_by,created_at
                ) VALUES(?,?,?,?,?,?,?,?,'Open',1,?,?)
                """,
                (identifier, workspace_id, group, period_name, currency["code"], start, end, reporting, actor, now),
            )
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="consolidation_close_period",
                object_id=identifier,
                action="consolidation_period_created",
                metadata={"group_code": group, "period_id": period_name, "status": "Open"},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to create the consolidation period.") from exc
        return self._public_period(self._period(identifier))

    def _worksheet_lines(
        self,
        worksheet: ConsolidationWorksheetResult,
    ) -> tuple[list[JournalLineMaterial], str]:
        lines: list[JournalLineMaterial] = []
        for elimination in worksheet.eliminations:
            for line in elimination.lines:
                if line.amount.currency != worksheet.reporting_currency:
                    raise PlatformError("Consolidation journal lines must use the worksheet reporting currency.")
                minor = line.amount.to_minor_units()
                if minor == 0 or abs(minor) > MAX_AMOUNT_MINOR:
                    raise PlatformError("Consolidation journal line exceeds the supported local amount range.")
                amount = str(line.amount.to_canonical_dict()["amount"])
                lines.append(
                    {
                        "account_type": line.account_type,
                        "amount_decimal": amount,
                        "amount_minor": minor,
                        "currency_code": line.amount.currency,
                        "elimination_id": elimination.elimination_id,
                        "entity_code": line.entity_code,
                        "group_account_code": line.group_account_code,
                        "source_digest": line.source_digest,
                        "source_line_id": line.line_id,
                        "source_reference": line.source_reference,
                    }
                )
        lines.sort(key=lambda item: (str(item["elimination_id"]), str(item["source_line_id"])))
        if not 2 <= len(lines) <= MAX_PERSISTED_JOURNAL_LINES:
            raise PlatformError(
                f"Persisted consolidation journals require between 2 and {MAX_PERSISTED_JOURNAL_LINES} lines."
            )
        if sum(line["amount_minor"] for line in lines) != 0:
            raise PlatformError("Persisted consolidation journal lines must balance exactly in minor units.")
        material: dict[str, object] = {
            "schema_version": 1,
            "worksheet_result_digest": worksheet.result_digest,
            "lines": lines,
        }
        return lines, _digest(material)

    def prepare_run(
        self,
        *,
        run_number: str,
        worksheet: ConsolidationWorksheetResult,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label, CONSOLIDATION_PREPARE_PERMISSION)
        if not isinstance(worksheet, ConsolidationWorksheetResult):
            raise PlatformError("A verified consolidation worksheet is required.")
        try:
            verified = verify_consolidation_worksheet_payload(worksheet.to_dict())
        except ConsolidationError as exc:
            raise PlatformError("Consolidation worksheet replay failed before persistence.") from exc
        if not same_actor(verified.prepared_by, actor):
            raise PlatformError("The authenticated preparer must match the worksheet preparer.")
        if verified.posting_effect != "none":
            raise PlatformError("Only a non-posting worksheet may enter the governed journal lifecycle.")
        workspace_id = ensure_workspace(self.connection, clean_text(workspace, "Workspace name"))
        period_identifier = platform_id("CCP", workspace_id, verified.group_code, verified.period_id)
        period = self._period(period_identifier)
        if period["status"] == "Locked":
            raise PlatformError("A locked consolidation period cannot accept a new run.")
        expected_period = (
            verified.group_code,
            verified.period_id,
            verified.reporting_currency,
            verified.period_start_date,
            verified.period_end_date,
            verified.reporting_date,
        )
        actual_period = tuple(
            str(period[key])
            for key in (
                "group_code",
                "period_name",
                "reporting_currency",
                "period_start_date",
                "period_end_date",
                "reporting_date",
            )
        )
        if actual_period != expected_period:
            raise PlatformError("Worksheet scope does not match the governed consolidation period.")
        self._currency(verified.reporting_currency)
        number = document_number(run_number, "Consolidation run number")
        lines, journal_digest = self._worksheet_lines(verified)
        try:
            encoded = encode_consolidation_worksheet(verified.to_dict())
        except PersistedJsonError as exc:
            raise PlatformError("Consolidation worksheet exceeds the bounded persistence profile.") from exc
        run_id = platform_id("CGR", workspace_id, verified.group_code, verified.period_id, number)
        existing = self.connection.execute("SELECT * FROM consolidation_runs WHERE id=?", (run_id,)).fetchone()
        if existing is not None:
            if (
                str(existing["worksheet_result_digest"]) != verified.result_digest
                or str(existing["worksheet_payload_digest"]) != encoded.checksum_sha256
                or str(existing["journal_digest"]) != journal_digest
            ):
                raise PlatformError("Consolidation run number conflicts with a different immutable worksheet.")
            return self._public_run(self._verified_run(run_id), include_details=True)
        now = utc_now_text()
        if now < verified.prepared_at:
            raise PlatformError("A consolidation run cannot persist a worksheet prepared in the future.")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO consolidation_runs(
                    id,period_id,workspace_id,run_number,worksheet_id,worksheet_request_digest,
                    worksheet_result_digest,translation_result_digest,worksheet_payload,
                    worksheet_payload_digest,reporting_currency,journal_line_count,journal_digest,
                    status,row_version,prepared_by,prepared_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'Prepared',1,?,?)
                """,
                (
                    run_id,
                    period_identifier,
                    workspace_id,
                    number,
                    verified.worksheet_id,
                    verified.request_digest,
                    verified.result_digest,
                    verified.translation_result_digest,
                    encoded.text,
                    encoded.checksum_sha256,
                    verified.reporting_currency,
                    len(lines),
                    journal_digest,
                    actor,
                    now,
                ),
            )
            for ordinal, line in enumerate(lines, 1):
                self.connection.execute(
                    """
                    INSERT INTO consolidation_run_lines(
                        id,run_id,ordinal,elimination_id,source_line_id,entity_code,
                        group_account_code,account_type,amount_decimal,amount_minor,currency_code,
                        source_reference,source_digest
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        platform_id("CGL", run_id, ordinal),
                        run_id,
                        ordinal,
                        line["elimination_id"],
                        line["source_line_id"],
                        line["entity_code"],
                        line["group_account_code"],
                        line["account_type"],
                        line["amount_decimal"],
                        line["amount_minor"],
                        line["currency_code"],
                        line["source_reference"],
                        line["source_digest"],
                    ),
                )
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="consolidation_run",
                object_id=run_id,
                action="consolidation_run_prepared",
                metadata={"run_number": number, "status": "Prepared", "journal_lines": len(lines)},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to persist the consolidation run atomically.") from exc
        return self._public_run(self._verified_run(run_id), include_details=True)

    def approve_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self._transition(
            run_id,
            from_status="Prepared",
            to_status="Approved",
            expected_version=expected_version,
            reason=reason,
            actor_label=actor_label,
            actor_column="approved_by",
            timestamp_column="approved_at",
            reason_column="approval_reason",
            action="consolidation_run_approved",
        )

    def post_run(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label, CONSOLIDATION_APPROVE_PERMISSION)
        reason_text = clean_text(reason, "Consolidation posting reason", maximum=500)
        version = _positive_version(expected_version)
        identifier = clean_text(run_id, "Consolidation run ID")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            run = self._verified_run(identifier)
            self._assert_run_state(run, "Approved", version)
            self._assert_period_open(str(run["period_id"]))
            if same_actor(actor, str(run["prepared_by"])) or same_actor(actor, str(run["approved_by"])):
                raise PlatformError("Posting requires an actor independent of preparation and approval.")
            self._create_effect(run, effect_type="Posting", actor=actor)
            now = utc_now_text()
            updated = self.connection.execute(
                """
                UPDATE consolidation_runs
                SET status='Posted',row_version=row_version+1,posted_by=?,posted_at=?,posting_reason=?
                WHERE id=? AND status='Approved' AND row_version=?
                """,
                (actor, now, reason_text, identifier, version),
            )
            if updated.rowcount != 1:
                raise PlatformError("Consolidation run changed concurrently before posting.")
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="consolidation_run",
                object_id=identifier,
                action="consolidation_run_posted",
                metadata={"status": "Posted", "version": version + 1, "scope": "consolidation-control-ledger"},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to post the consolidation run atomically.") from exc
        return self._public_run(self._verified_run(identifier), include_details=True)

    def prepare_certification(
        self,
        run_id: str,
        *,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Prepare workflow certification metadata for a posted close run."""

        actor = self._actor(actor_label, CONSOLIDATION_PREPARE_PERMISSION)
        run = self._verified_run(clean_text(run_id, "Consolidation run ID"))
        if str(run["status"]) not in {"Posted", "Reversed"}:
            raise PlatformError("Only a posted or reversed consolidation run can be certified.")
        require_permission(self.connection, actor_label=actor, permission="approval.submit")
        period = self._period(str(run["period_id"]))
        return SQLiteApprovalRepository(self.connection).prepare_certification(
            object_type="consolidation_close_run",
            object_id=str(run["id"]),
            period_name=str(period["period_name"]),
            entity_code=str(period["group_code"]),
            note=note,
            actor_label=actor,
        )

    def review_certification(
        self,
        run_id: str,
        *,
        note: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Review posted-close certification metadata with maker-checker SoD."""

        actor = self._actor(actor_label, CONSOLIDATION_APPROVE_PERMISSION)
        run = self._verified_run(clean_text(run_id, "Consolidation run ID"))
        if str(run["status"]) not in {"Posted", "Reversed"}:
            raise PlatformError("Only a posted or reversed consolidation run can be certified.")
        require_permission(self.connection, actor_label=actor, permission="approval.approve")
        return SQLiteApprovalRepository(self.connection).review_certification(
            object_type="consolidation_close_run",
            object_id=str(run["id"]),
            note=note,
            actor_label=actor,
        )

    def get_certification(self, run_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        """Read certification metadata only after replay-validating its run."""

        self._actor(actor_label, CONSOLIDATION_READ_PERMISSION)
        identifier = clean_text(run_id, "Consolidation run ID")
        self._verified_run(identifier)
        row = self.connection.execute(
            "SELECT * FROM certification_records WHERE object_type=? AND object_id=?",
            ("consolidation_close_run", identifier),
        ).fetchone()
        if row is None:
            raise PlatformError("Consolidation certification metadata not found.")
        return dict(row)

    def request_reversal(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self._transition(
            run_id,
            from_status="Posted",
            to_status="ReversalPrepared",
            expected_version=expected_version,
            reason=reason,
            actor_label=actor_label,
            actor_column="reversal_requested_by",
            timestamp_column="reversal_requested_at",
            reason_column="reversal_request_reason",
            action="consolidation_reversal_prepared",
            permission=CONSOLIDATION_PREPARE_PERMISSION,
        )

    def approve_reversal(
        self,
        run_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label, CONSOLIDATION_APPROVE_PERMISSION)
        reason_text = clean_text(reason, "Consolidation reversal approval reason", maximum=500)
        version = _positive_version(expected_version)
        identifier = clean_text(run_id, "Consolidation run ID")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            run = self._verified_run(identifier)
            self._assert_run_state(run, "ReversalPrepared", version)
            self._assert_period_open(str(run["period_id"]))
            if same_actor(actor, str(run["reversal_requested_by"])) or same_actor(actor, str(run["posted_by"])):
                raise PlatformError("Reversal approval requires an actor independent of request and posting.")
            self._create_effect(run, effect_type="Reversal", actor=actor)
            now = utc_now_text()
            updated = self.connection.execute(
                """
                UPDATE consolidation_runs
                SET status='Reversed',row_version=row_version+1,reversed_by=?,reversed_at=?,reversal_reason=?
                WHERE id=? AND status='ReversalPrepared' AND row_version=?
                """,
                (actor, now, reason_text, identifier, version),
            )
            if updated.rowcount != 1:
                raise PlatformError("Consolidation run changed concurrently before reversal.")
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="consolidation_run",
                object_id=identifier,
                action="consolidation_run_reversed",
                metadata={"status": "Reversed", "version": version + 1},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to reverse the consolidation run atomically.") from exc
        return self._public_run(self._verified_run(identifier), include_details=True)

    def _transition(
        self,
        run_id: str,
        *,
        from_status: str,
        to_status: str,
        expected_version: int,
        reason: str,
        actor_label: str,
        actor_column: str,
        timestamp_column: str,
        reason_column: str,
        action: str,
        permission: str = CONSOLIDATION_APPROVE_PERMISSION,
    ) -> dict[str, Any]:
        actor = self._actor(actor_label, permission)
        reason_text = clean_text(reason, "Consolidation lifecycle reason", maximum=500)
        version = _positive_version(expected_version)
        identifier = clean_text(run_id, "Consolidation run ID")
        transition_queries = {
            (
                "approved_by",
                "approved_at",
                "approval_reason",
            ): """
                UPDATE consolidation_runs
                SET status=?,row_version=row_version+1,
                    approved_by=?,approved_at=?,approval_reason=?
                WHERE id=? AND status=? AND row_version=?
            """,
            (
                "reversal_requested_by",
                "reversal_requested_at",
                "reversal_request_reason",
            ): """
                UPDATE consolidation_runs
                SET status=?,row_version=row_version+1,
                    reversal_requested_by=?,reversal_requested_at=?,reversal_request_reason=?
                WHERE id=? AND status=? AND row_version=?
            """,
        }
        query = transition_queries.get((actor_column, timestamp_column, reason_column))
        if query is None:
            raise PlatformError("Unsupported consolidation lifecycle transition metadata.")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            run = self._verified_run(identifier)
            self._assert_run_state(run, from_status, version)
            self._assert_period_open(str(run["period_id"]))
            if to_status == "Approved" and same_actor(actor, str(run["prepared_by"])):
                raise PlatformError("Segregation of duties prevents approving your own consolidation run.")
            now = utc_now_text()
            updated = self.connection.execute(
                query,
                (to_status, actor, now, reason_text, identifier, from_status, version),
            )
            if updated.rowcount != 1:
                raise PlatformError("Consolidation run changed concurrently.")
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="consolidation_run",
                object_id=identifier,
                action=action,
                metadata={"status": to_status, "version": version + 1},
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to advance the consolidation lifecycle atomically.") from exc
        return self._public_run(self._verified_run(identifier), include_details=True)

    def _create_effect(self, run: Mapping[str, Any], *, effect_type: str, actor: str) -> None:
        selected = choice(effect_type, "Consolidation effect type", ("Posting", "Reversal"))
        run_id = str(run["id"])
        rows = self.connection.execute(
            "SELECT * FROM consolidation_run_lines WHERE run_id=? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
        if len(rows) != int(run["journal_line_count"]):
            raise PlatformError("Consolidation run line count changed before effect creation.")
        source_effect_id = ""
        if selected == "Reversal":
            source = self.connection.execute(
                "SELECT id FROM consolidation_effects WHERE run_id=? AND effect_type='Posting' AND status='Committed'",
                (run_id,),
            ).fetchone()
            if source is None:
                raise PlatformError("A committed posting effect is required before reversal.")
            source_effect_id = str(source["id"])
        sign = 1 if selected == "Posting" else -1
        material_lines: list[EffectLineMaterial] = [
            {
                "amount_minor": sign * int(row["amount_minor"]),
                "currency_code": str(row["currency_code"]),
                "run_line_id": str(row["id"]),
            }
            for row in rows
        ]
        effect_id = platform_id("CGE", run_id, selected)
        effect_digest = _digest(
            {
                "effect_type": selected,
                "lines": material_lines,
                "run_id": run_id,
                "schema_version": 1,
                "source_effect_id": source_effect_id,
            }
        )
        now = utc_now_text()
        self.connection.execute(
            """
            INSERT INTO consolidation_effects(
                id,run_id,effect_type,source_effect_id,status,line_count,effect_digest,created_by,created_at
            ) VALUES(?,?,?,?, 'Building',?,?,?,?)
            """,
            (effect_id, run_id, selected, source_effect_id, len(rows), effect_digest, actor, now),
        )
        for ordinal, (row, material) in enumerate(zip(rows, material_lines, strict=True), 1):
            amount_minor = material["amount_minor"]
            amount = Money.from_minor_units(amount_minor, str(row["currency_code"]))
            self.connection.execute(
                """
                INSERT INTO consolidation_effect_lines(
                    id,effect_id,run_line_id,ordinal,amount_decimal,amount_minor,currency_code
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    platform_id("CEL", effect_id, ordinal),
                    effect_id,
                    row["id"],
                    ordinal,
                    amount.to_canonical_dict()["amount"],
                    amount_minor,
                    row["currency_code"],
                ),
            )
        updated = self.connection.execute(
            "UPDATE consolidation_effects SET status='Committed' WHERE id=? AND status='Building'",
            (effect_id,),
        )
        if updated.rowcount != 1:
            raise PlatformError("Consolidation effect could not be committed.")

    def lock_period(
        self,
        period_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label, CONSOLIDATION_APPROVE_PERMISSION)
        reason_text = clean_text(reason, "Consolidation lock reason", maximum=500)
        version = _positive_version(expected_version)
        identifier = clean_text(period_id, "Consolidation period ID")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            period = self._period(identifier)
            if period["status"] not in {"Open", "Reopened"} or int(period["row_version"]) != version:
                raise PlatformError("Consolidation period is not at the expected lockable version.")
            now = utc_now_text()
            self.connection.execute(
                """
                INSERT INTO consolidation_period_events(
                    id,period_id,event_sequence,from_status,to_status,actor_label,occurred_at,reason
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    platform_id("CPE", identifier, version + 1),
                    identifier,
                    version + 1,
                    str(period["status"]),
                    "Locked",
                    actor,
                    now,
                    reason_text,
                ),
            )
            updated = self.connection.execute(
                """
                UPDATE consolidation_close_periods
                SET status='Locked',row_version=row_version+1,locked_by=?,locked_at=?,lock_reason=?
                WHERE id=? AND status IN ('Open','Reopened') AND row_version=?
                """,
                (actor, now, reason_text, identifier, version),
            )
            if updated.rowcount != 1:
                raise PlatformError("Consolidation period changed concurrently before lock.")
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="consolidation_close_period",
                object_id=identifier,
                action="consolidation_period_locked",
                metadata={
                    "occurred_at": now,
                    "reason": reason_text,
                    "status": "Locked",
                    "version": version + 1,
                },
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to lock the consolidation period atomically.") from exc
        return self._public_period(self._period(identifier))

    def reopen_period(
        self,
        period_id: str,
        *,
        expected_version: int,
        reason: str,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        actor = self._actor(actor_label, CONSOLIDATION_APPROVE_PERMISSION)
        reason_text = clean_text(reason, "Consolidation reopen reason", maximum=500)
        version = _positive_version(expected_version)
        identifier = clean_text(period_id, "Consolidation period ID")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            period = self._period(identifier)
            if period["status"] != "Locked" or int(period["row_version"]) != version:
                raise PlatformError("Consolidation period is not at the expected locked version.")
            if same_actor(actor, str(period["locked_by"])):
                raise PlatformError("Reopening requires an actor independent of the period locker.")
            now = utc_now_text()
            self.connection.execute(
                """
                INSERT INTO consolidation_period_events(
                    id,period_id,event_sequence,from_status,to_status,actor_label,occurred_at,reason
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    platform_id("CPE", identifier, version + 1),
                    identifier,
                    version + 1,
                    "Locked",
                    "Reopened",
                    actor,
                    now,
                    reason_text,
                ),
            )
            updated = self.connection.execute(
                """
                UPDATE consolidation_close_periods
                SET status='Reopened',row_version=row_version+1,
                    reopened_by=?,reopened_at=?,reopen_reason=?
                WHERE id=? AND status='Locked' AND row_version=?
                """,
                (actor, now, reason_text, identifier, version),
            )
            if updated.rowcount != 1:
                raise PlatformError("Consolidation period changed concurrently before reopen.")
            commit_audited(
                self.connection,
                actor_label=actor,
                object_type="consolidation_close_period",
                object_id=identifier,
                action="consolidation_period_reopened",
                metadata={
                    "occurred_at": now,
                    "reason": reason_text,
                    "status": "Reopened",
                    "version": version + 1,
                },
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to reopen the consolidation period atomically.") from exc
        return self._public_period(self._period(identifier))

    def get_period(self, period_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        self._actor(actor_label, CONSOLIDATION_READ_PERMISSION)
        return self._public_period(self._period(clean_text(period_id, "Consolidation period ID")))

    def list_periods(
        self,
        *,
        workspace: str = "default",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        self._actor(actor_label, CONSOLIDATION_READ_PERMISSION)
        workspace_id = self._workspace_id(workspace)
        limit, offset = page(limit, offset)
        rows = self.connection.execute(
            """
            SELECT * FROM consolidation_close_periods
            WHERE workspace_id=? ORDER BY period_end_date DESC,group_code,period_name LIMIT ? OFFSET ?
            """,
            (workspace_id, limit, offset),
        ).fetchall()
        return [self._public_period(row) for row in rows]

    def get_run(self, run_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        self._actor(actor_label, CONSOLIDATION_READ_PERMISSION)
        return self._public_run(self._verified_run(clean_text(run_id, "Consolidation run ID")), include_details=True)

    def list_runs(
        self,
        *,
        workspace: str = "default",
        status: str = "",
        limit: int = 500,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        self._actor(actor_label, CONSOLIDATION_READ_PERMISSION)
        workspace_id = self._workspace_id(workspace)
        selected = choice(status, "Consolidation run status", CONSOLIDATION_RUN_STATUSES) if status else ""
        limit, offset = page(limit, offset)
        rows = self.connection.execute(
            """
            SELECT * FROM consolidation_runs
            WHERE workspace_id=? AND (?='' OR status=?)
            ORDER BY prepared_at DESC,run_number,id LIMIT ? OFFSET ?
            """,
            (workspace_id, selected, selected, limit, offset),
        ).fetchall()
        return [self._public_run(self._verified_run(str(row["id"])), include_details=False) for row in rows]

    def summary(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> ConsolidationCloseSummary:
        self._actor(actor_label, CONSOLIDATION_READ_PERMISSION)
        workspace_id = self._workspace_id(workspace)
        row = self.connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM consolidation_close_periods WHERE workspace_id=?) periods,
              (SELECT COUNT(*) FROM consolidation_close_periods WHERE workspace_id=? AND status='Locked') locked,
              (SELECT COUNT(*) FROM consolidation_runs WHERE workspace_id=? AND status='Prepared') prepared,
              (SELECT COUNT(*) FROM consolidation_runs WHERE workspace_id=? AND status='Approved') approved,
              (SELECT COUNT(*) FROM consolidation_runs WHERE workspace_id=? AND status='Posted') posted,
              (SELECT COUNT(*) FROM consolidation_runs WHERE workspace_id=? AND status='ReversalPrepared') reversal_prepared,
              (SELECT COUNT(*) FROM consolidation_runs WHERE workspace_id=? AND status='Reversed') reversed
            """,
            (workspace_id,) * 7,
        ).fetchone()
        if row is None:
            raise PlatformError("Unable to calculate the consolidation close summary.")
        return ConsolidationCloseSummary(
            workspace=clean_text(workspace, "Workspace name"),
            periods=int(row["periods"]),
            locked_periods=int(row["locked"]),
            prepared_runs=int(row["prepared"]),
            approved_runs=int(row["approved"]),
            posted_runs=int(row["posted"]),
            reversal_prepared_runs=int(row["reversal_prepared"]),
            reversed_runs=int(row["reversed"]),
        )

    def _period(self, period_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM consolidation_close_periods WHERE id=?",
            (period_id,),
        ).fetchone()
        if row is None:
            raise PlatformError("Consolidation period not found.")
        return row

    def _assert_period_open(self, period_id: str) -> None:
        if str(self._period(period_id)["status"]) == "Locked":
            raise PlatformError("The consolidation period is locked; reopen it before lifecycle changes.")

    def _workspace_id(self, workspace: str) -> str:
        name = clean_text(workspace, "Workspace name")
        row = self.connection.execute("SELECT id FROM workspaces WHERE name=?", (name,)).fetchone()
        if row is None:
            raise PlatformError("Workspace not found.")
        return str(row["id"])

    @staticmethod
    def _assert_run_state(run: Mapping[str, Any], status: str, version: int) -> None:
        if str(run["status"]) != status or int(run["row_version"]) != version:
            raise PlatformError(f"Consolidation run is not at expected {status} version {version}.")

    def _verified_run(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM consolidation_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise PlatformError("Consolidation run not found.")
        record = dict(row)
        try:
            document = decode_consolidation_worksheet(record["worksheet_payload"])
            worksheet = verify_consolidation_worksheet_payload(document.payload)
        except (PersistedJsonError, ConsolidationError, InvalidAmountError) as exc:
            raise PlatformError("Persisted consolidation worksheet failed bounded replay verification.") from exc
        if not hmac.compare_digest(document.checksum_sha256, str(record["worksheet_payload_digest"])):
            raise PlatformError("Persisted consolidation worksheet checksum mismatch.")
        expected = (
            worksheet.worksheet_id,
            worksheet.request_digest,
            worksheet.result_digest,
            worksheet.translation_result_digest,
            worksheet.reporting_currency,
        )
        actual = tuple(
            str(record[key])
            for key in (
                "worksheet_id",
                "worksheet_request_digest",
                "worksheet_result_digest",
                "translation_result_digest",
                "reporting_currency",
            )
        )
        if actual != expected:
            raise PlatformError("Persisted consolidation run header does not match its replayed worksheet.")
        rows = self.connection.execute(
            "SELECT * FROM consolidation_run_lines WHERE run_id=? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
        line_material: list[JournalLineMaterial] = [
            {
                "account_type": str(item["account_type"]),
                "amount_decimal": str(item["amount_decimal"]),
                "amount_minor": int(item["amount_minor"]),
                "currency_code": str(item["currency_code"]),
                "elimination_id": str(item["elimination_id"]),
                "entity_code": str(item["entity_code"]),
                "group_account_code": str(item["group_account_code"]),
                "source_digest": str(item["source_digest"]),
                "source_line_id": str(item["source_line_id"]),
                "source_reference": str(item["source_reference"]),
            }
            for item in rows
        ]
        expected_lines, expected_journal = self._worksheet_lines(worksheet)
        if (
            line_material != expected_lines
            or len(rows) != int(record["journal_line_count"])
            or sum(int(item["amount_minor"]) for item in rows) != 0
            or not hmac.compare_digest(expected_journal, str(record["journal_digest"]))
        ):
            raise PlatformError("Persisted consolidation journal failed balance or digest verification.")
        effects = self._verified_effects(run_id, rows)
        if not same_actor(str(record["prepared_by"]), worksheet.prepared_by):
            raise PlatformError("Persisted consolidation preparer does not match the worksheet preparer.")
        if str(record["prepared_at"]) < worksheet.prepared_at:
            raise PlatformError("Persisted consolidation run predates its worksheet preparation.")
        for effect in effects:
            effect_type = str(effect["effect_type"])
            expected_actor = str(record["posted_by"] if effect_type == "Posting" else record["reversed_by"])
            expected_at = str(record["posted_at"] if effect_type == "Posting" else record["reversed_at"])
            if not same_actor(str(effect["created_by"]), expected_actor) or str(effect["created_at"]) > expected_at:
                raise PlatformError("Persisted consolidation effect attribution is inconsistent.")
        record["worksheet"] = worksheet.to_dict()
        record["translation_evidence"] = build_translation_evidence(worksheet.request.translation_result).to_dict()
        record["management_statement"] = build_management_statement_package(worksheet).to_dict()
        record["journal_lines"] = [dict(item) for item in rows]
        record["effects"] = effects
        record["close_bundle"] = build_consolidation_close_bundle(record).to_dict()
        return record

    def _verified_effects(self, run_id: str, run_lines: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
        effects = self.connection.execute(
            "SELECT * FROM consolidation_effects WHERE run_id=? ORDER BY effect_type",
            (run_id,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        run_by_id = {str(row["id"]): row for row in run_lines}
        for effect in effects:
            if str(effect["status"]) != "Committed":
                raise PlatformError("Persisted consolidation effect is incomplete.")
            lines = self.connection.execute(
                "SELECT * FROM consolidation_effect_lines WHERE effect_id=? ORDER BY ordinal",
                (effect["id"],),
            ).fetchall()
            material: list[dict[str, object]] = []
            sign = 1 if effect["effect_type"] == "Posting" else -1
            for line in lines:
                source = run_by_id.get(str(line["run_line_id"]))
                expected_amount = Money.from_minor_units(
                    int(line["amount_minor"]),
                    str(line["currency_code"]),
                ).to_canonical_dict()["amount"]
                if (
                    source is None
                    or int(line["amount_minor"]) != sign * int(source["amount_minor"])
                    or str(line["currency_code"]) != str(source["currency_code"])
                    or str(line["amount_decimal"]) != expected_amount
                    or int(line["ordinal"]) != int(source["ordinal"])
                ):
                    raise PlatformError("Persisted consolidation effect does not reproduce its run lines.")
                material.append(
                    {
                        "amount_minor": int(line["amount_minor"]),
                        "currency_code": str(line["currency_code"]),
                        "run_line_id": str(line["run_line_id"]),
                    }
                )
            expected_digest = _digest(
                {
                    "effect_type": str(effect["effect_type"]),
                    "lines": material,
                    "run_id": run_id,
                    "schema_version": 1,
                    "source_effect_id": str(effect["source_effect_id"]),
                }
            )
            if (
                len(lines) != int(effect["line_count"])
                or sum(int(line["amount_minor"]) for line in lines) != 0
                or not hmac.compare_digest(expected_digest, str(effect["effect_digest"]))
            ):
                raise PlatformError("Persisted consolidation effect failed balance or digest verification.")
            item = dict(effect)
            item["lines"] = [dict(line) for line in lines]
            result.append(item)
        run_status = self.connection.execute(
            "SELECT status FROM consolidation_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if run_status is None:
            raise PlatformError("Consolidation run disappeared during effect verification.")
        status = str(run_status["status"])
        effect_types = {str(item["effect_type"]) for item in effects}
        expected_effect_types = {
            "Prepared": set(),
            "Approved": set(),
            "Posted": {"Posting"},
            "ReversalPrepared": {"Posting"},
            "Reversed": {"Posting", "Reversal"},
        }[status]
        if effect_types != expected_effect_types:
            raise PlatformError("Persisted consolidation effects do not match the governed run state.")
        return result

    @staticmethod
    def _public_period(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
        return dict(row)

    @staticmethod
    def _public_run(row: Mapping[str, Any], *, include_details: bool) -> dict[str, Any]:
        hidden = {"worksheet_payload"}
        if not include_details:
            hidden |= {"worksheet", "journal_lines", "effects", "management_statement"}
        return {key: value for key, value in row.items() if key not in hidden}


def verify_consolidation_close_integrity(connection: sqlite3.Connection) -> None:
    """Replay every persisted worksheet and period event without authorization side effects."""

    repository = SQLiteConsolidationCloseRepository(connection)
    period_rows = connection.execute(
        "SELECT * FROM consolidation_close_periods ORDER BY workspace_id,period_start_date,id"
    ).fetchall()
    for period in period_rows:
        period_id = str(period["id"])
        events = connection.execute(
            "SELECT * FROM consolidation_period_events WHERE period_id=? ORDER BY event_sequence,id",
            (period_id,),
        ).fetchall()
        status = "Open"
        version = 1
        locked_by = locked_at = lock_reason = ""
        reopened_by = reopened_at = reopen_reason = ""
        for event in events:
            if (
                int(event["event_sequence"]) != version + 1
                or str(event["from_status"]) != status
                or str(event["to_status"]) not in {"Locked", "Reopened"}
            ):
                raise PlatformError("Persisted consolidation period event sequence is invalid.")
            status = str(event["to_status"])
            version += 1
            if status == "Locked":
                locked_by = str(event["actor_label"])
                locked_at = str(event["occurred_at"])
                lock_reason = str(event["reason"])
            else:
                reopened_by = str(event["actor_label"])
                reopened_at = str(event["occurred_at"])
                reopen_reason = str(event["reason"])
        expected = (
            status,
            version,
            locked_by,
            locked_at,
            lock_reason,
            reopened_by,
            reopened_at,
            reopen_reason,
        )
        actual = (
            str(period["status"]),
            int(period["row_version"]),
            str(period["locked_by"]),
            str(period["locked_at"]),
            str(period["lock_reason"]),
            str(period["reopened_by"]),
            str(period["reopened_at"]),
            str(period["reopen_reason"]),
        )
        if actual != expected:
            raise PlatformError("Persisted consolidation period does not replay from its immutable events.")

        runs = connection.execute(
            "SELECT id,prepared_at FROM consolidation_runs WHERE period_id=? ORDER BY prepared_at,id",
            (period_id,),
        ).fetchall()
        for run in runs:
            state_at_preparation = "Open"
            for event in events:
                if str(event["occurred_at"]) < str(run["prepared_at"]):
                    state_at_preparation = str(event["to_status"])
            if state_at_preparation == "Locked":
                raise PlatformError("Persisted consolidation run was prepared while its period was locked.")
            repository._verified_run(str(run["id"]))
