"""SQLite adapter and deterministic engine for governed matching."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from reconforge.application.matching import (
    LEGACY_RECORD_IDENTITY_POLICY,
    CurrencyPrecisionResolver,
    DeterministicMatchOutput,
    MatchRunResult,
    ReferenceNormalizationRules,
)
from reconforge.audit import AuditLedgerError
from reconforge.domain.models import utc_now_text
from reconforge.io.persisted import (
    PersistedJsonError,
    PersistedJsonObjectDocument,
    decode_sqlite_matching_rule,
    encode_sqlite_matching_lineage,
    encode_sqlite_matching_rule,
)
from reconforge.platform.common import (
    PlatformError,
    append_outbox_event,
    audit,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    read_local_record_document,
    require_permission,
    rows_to_dicts,
)
from reconforge.reconciliation.deterministic_engine import (
    _JSON_RECORD_BASIS,
    DeterministicMatchingEngine,
    _coerce_confidence,
    _decimal_text,
    _matching_input_policy,
    _matching_record_identity_policy,
    _non_negative_amount,
    _parse_amount,
    _parse_reference_normalization_rules,
)
from reconforge.reconciliation.deterministic_engine import (
    MATCHING_CANDIDATE_POLICY as MATCHING_CANDIDATE_POLICY,
)
from reconforge.reconciliation.deterministic_engine import (
    MAX_CANDIDATES_PER_LEFT_RECORD as MAX_CANDIDATES_PER_LEFT_RECORD,
)
from reconforge.reconciliation.deterministic_engine import (
    MAX_TOTAL_CANDIDATE_EVALUATIONS as MAX_TOTAL_CANDIDATE_EVALUATIONS,
)
from reconforge.reconciliation.deterministic_engine import (
    _AmountRangePartition as _AmountRangePartition,
)
from reconforge.reconciliation.deterministic_engine import (
    _decimal_range_bounds as _decimal_range_bounds,
)
from reconforge.reconciliation.matching import (
    INTERNAL_LINEAGE_COLUMNS,
    RECORD_IDENTITY_POLICY,
    SOURCE_POSITION_COLUMN,
    SOURCE_ROW_BASIS_COLUMN,
    SOURCE_ROW_COLUMN,
)
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    FinancialInputPolicy,
)


class SQLiteMatchingRepository:
    """Indexed candidate-generation matching engine."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        currency_precision_resolver: CurrencyPrecisionResolver | None = None,
    ) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self.currency_precision_resolver: CurrencyPrecisionResolver = (
            currency_precision_resolver or self._sqlite_currency_precision
        )
        self.engine = DeterministicMatchingEngine(
            self.currency_precision_resolver,
            max_candidates_per_left_record=MAX_CANDIDATES_PER_LEFT_RECORD,
            max_total_candidate_evaluations=MAX_TOTAL_CANDIDATE_EVALUATIONS,
        )
        self._match_result_columns: set[str] | None = None

    def _sqlite_currency_precision(self, currency_code: str) -> tuple[int | None, str | None]:
        row = self.connection.execute(
            "SELECT minor_units, active FROM currencies WHERE code = ?", (currency_code,)
        ).fetchone()
        if row is None:
            return None, "UNKNOWN_CURRENCY"
        if not bool(row["active"]):
            return None, "INACTIVE_CURRENCY"
        return int(row["minor_units"]), None

    @staticmethod
    def _json_text(value: object) -> str:
        """Serialize deterministic JSON for explainability metadata."""

        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise PlatformError("Matching lineage is invalid.")
        try:
            return encode_sqlite_matching_lineage(value).text
        except PersistedJsonError as exc:
            raise PlatformError("Matching lineage is invalid.") from exc

    @staticmethod
    def _matching_rule_document(
        value: object,
        *,
        producer: bool = False,
    ) -> PersistedJsonObjectDocument:
        try:
            if producer:
                if not isinstance(value, Mapping):
                    raise PersistedJsonError("persisted_json_object_required")
                return encode_sqlite_matching_rule(value)
            return decode_sqlite_matching_rule(value)
        except PersistedJsonError as exc:
            message = "Matching rule is invalid." if producer else "Stored matching rule is invalid."
            raise PlatformError(message) from exc

    @staticmethod
    def _records_with_source_locations(
        records: list[dict[str, Any]],
        *,
        source_name: str,
    ) -> list[dict[str, Any]]:
        """Attach trusted file positions after removing user-supplied internal lineage keys."""

        suffix = Path(source_name).suffix.casefold()
        basis = "tabular-header-offset-v1" if suffix == ".csv" else _JSON_RECORD_BASIS
        located: list[dict[str, Any]] = []
        for position, record in enumerate(records, start=1):
            clean = {str(key): value for key, value in record.items() if str(key) not in INTERNAL_LINEAGE_COLUMNS}
            clean[SOURCE_POSITION_COLUMN] = position
            clean[SOURCE_ROW_COLUMN] = position + 1 if suffix == ".csv" else None
            clean[SOURCE_ROW_BASIS_COLUMN] = basis
            located.append(clean)
        return located

    def _match_results_columns(self) -> set[str]:
        """Return cached table columns for the local match_results table."""

        if self._match_result_columns is None:
            rows = self.connection.execute("PRAGMA table_info(match_results)").fetchall()
            self._match_result_columns = {str(row["name"]) for row in rows}
        return self._match_result_columns

    def _ensure_match_result_columns(self) -> None:
        """Ensure optional explainability columns exist on legacy match_result tables."""

        columns = self._match_results_columns()
        migration_sql: list[str] = []
        if "lineage_json" not in columns:
            migration_sql.append("ALTER TABLE match_results ADD COLUMN lineage_json TEXT NOT NULL DEFAULT '{}'")
        if "reason_code" not in columns:
            migration_sql.append("ALTER TABLE match_results ADD COLUMN reason_code TEXT NOT NULL DEFAULT ''")
        for migration in migration_sql:
            self.connection.execute(migration)
        if migration_sql:
            self._match_result_columns = None
            self._match_result_columns = self._match_results_columns()

    def run(
        self,
        *,
        left_path: Path | str,
        right_path: Path | str,
        workspace: str = "default",
        name: str = "local-match-job",
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
        actor_label: str = "local-cli",
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
    ) -> MatchRunResult:
        """Run deterministic local matching without a full cross product where possible."""

        financial_input_policy = _matching_input_policy(financial_input_policy)
        record_identity_policy = _matching_record_identity_policy(record_identity_policy)
        require_permission(self.connection, actor_label=actor_label, permission="match.run")
        left_document = read_local_record_document(left_path)
        right_document = read_local_record_document(right_path)
        return self._run_records(
            left_records=left_document.records,
            right_records=right_document.records,
            workspace=workspace,
            name=name,
            left_source=left_document.source_path.name,
            right_source=right_document.source_path.name,
            left_id_field=left_id_field,
            right_id_field=right_id_field,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_fields,
            amount_tolerance=amount_tolerance,
            date_window_days=date_window_days,
            allow_many_to_one=allow_many_to_one,
            allow_one_to_many=allow_one_to_many,
            allow_many_to_many=allow_many_to_many,
            reference_normalization_rules=reference_normalization_rules,
            idempotency_key=idempotency_key,
            actor_label=actor_label,
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
        )

    def benchmark(self, *, rows: int, workspace: str = "default", actor_label: str = "local-cli") -> MatchRunResult:
        """Run a synthetic local benchmark job and persist summary results."""

        require_permission(self.connection, actor_label=actor_label, permission="match.run")
        if rows < 1 or rows > 250000:
            raise PlatformError("Benchmark rows must be between 1 and 250000.")
        left_records = [
            {"id": f"L-{index}", "reference": f"REF-{index}", "amount": index * 10, "date": "2026-01-15"}
            for index in range(rows)
        ]
        right_records = [
            {"id": f"R-{index}", "reference": f"REF-{index}", "amount": index * 10, "date": "2026-01-15"}
            for index in range(rows)
        ]
        return self._run_records(
            left_records=left_records,
            right_records=right_records,
            workspace=workspace,
            name=f"synthetic-benchmark-{rows}",
            left_source="synthetic-left",
            right_source="synthetic-right",
            left_id_field="id",
            right_id_field="id",
            amount_field="amount",
            date_field="date",
            reference_field="reference",
            exact_fields="",
            amount_tolerance=Decimal("0"),
            date_window_days=0,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
            idempotency_key=None,
            actor_label=actor_label,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            record_identity_policy=RECORD_IDENTITY_POLICY,
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """Return one match job status."""

        row = self.connection.execute("SELECT * FROM match_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise PlatformError("Match job not found.")
        payload = dict(row)
        self._matching_rule_document(payload.get("rule_json", ""))
        counts = self.connection.execute(
            """
            SELECT
                COUNT(CASE WHEN left_id <> '' THEN 1 END) AS result_count,
                SUM(CASE WHEN status = 'Matched' THEN 1 ELSE 0 END) AS matched_count
            FROM match_results
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        payload["result_count"] = int(counts["result_count"] or 0)
        payload["matched_count"] = int(counts["matched_count"] or 0)
        return payload

    def results(self, job_id: str, *, status: str = "") -> list[dict[str, Any]]:
        """List match results for one job."""

        if status:
            rows = self.connection.execute(
                "SELECT * FROM match_results WHERE job_id = ? AND status = ? ORDER BY confidence DESC, left_id, right_id, match_type",
                (job_id, status),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM match_results WHERE job_id = ? ORDER BY confidence DESC, left_id, right_id, match_type",
                (job_id,),
            ).fetchall()
        return rows_to_dicts(rows)

    def list_jobs(self) -> list[dict[str, Any]]:
        """List match jobs."""

        jobs = rows_to_dicts(self.connection.execute("SELECT * FROM match_jobs ORDER BY created_at DESC").fetchall())
        for job in jobs:
            self._matching_rule_document(job.get("rule_json", ""))
        return jobs

    def match_records(
        self,
        *,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        left_id_field: str = "id",
        right_id_field: str = "id",
        amount_field: str = "amount",
        date_field: str = "date",
        reference_field: str = "reference",
        exact_fields: str = "",
        amount_tolerance: object = Decimal("0"),
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        allow_one_to_many: bool = False,
        allow_many_to_many: bool = False,
        reference_normalization_rules: Mapping[str, object] | ReferenceNormalizationRules | None = None,
        financial_input_policy: FinancialInputPolicy = STRICT_FINANCIAL_INPUT_POLICY,
        record_identity_policy: str = LEGACY_RECORD_IDENTITY_POLICY,
        _source_locations_trusted: bool = False,
    ) -> DeterministicMatchOutput:
        return self.engine.match_records(
            left_records=left_records,
            right_records=right_records,
            left_id_field=left_id_field,
            right_id_field=right_id_field,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_fields,
            amount_tolerance=amount_tolerance,
            date_window_days=date_window_days,
            allow_many_to_one=allow_many_to_one,
            allow_one_to_many=allow_one_to_many,
            allow_many_to_many=allow_many_to_many,
            reference_normalization_rules=reference_normalization_rules,
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
            _source_locations_trusted=_source_locations_trusted,
        )

    def _run_records(
        self,
        *,
        left_records: list[dict[str, Any]],
        right_records: list[dict[str, Any]],
        workspace: str,
        name: str,
        left_source: str,
        right_source: str,
        left_id_field: str,
        right_id_field: str,
        amount_field: str,
        date_field: str,
        reference_field: str,
        exact_fields: str,
        amount_tolerance: object,
        date_window_days: int,
        allow_many_to_one: bool,
        allow_one_to_many: bool,
        allow_many_to_many: bool,
        reference_normalization_rules: Mapping[str, object] | None = None,
        idempotency_key: str | None,
        actor_label: str,
        financial_input_policy: FinancialInputPolicy,
        record_identity_policy: str,
    ) -> MatchRunResult:
        financial_input_policy = _matching_input_policy(financial_input_policy)
        record_identity_policy = _matching_record_identity_policy(record_identity_policy)
        workspace_id = ensure_workspace(self.connection, workspace)
        created_at = utc_now_text()
        self._ensure_match_result_columns()
        job_id = (
            platform_id("MJ", workspace_id, name, left_source, right_source, "idempotency", idempotency_key)
            if idempotency_key
            else platform_id("MJ", workspace_id, name, left_source, right_source, created_at)
        )
        if idempotency_key:
            existing = self.connection.execute(
                "SELECT id, rule_json FROM match_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if existing is not None:
                try:
                    existing_rule = self._matching_rule_document(existing["rule_json"]).payload
                except PlatformError as exc:
                    raise PlatformError("Existing idempotent match rule is invalid.") from exc
                existing_policy = _matching_input_policy(
                    existing_rule.get(
                        "financial_input_policy",
                        LEGACY_FINANCIAL_INPUT_POLICY,
                    )
                )
                if existing_policy != financial_input_policy:
                    raise PlatformError("Idempotency key is bound to a different financial input policy.")
                existing_identity_policy = str(
                    existing_rule.get(
                        "record_identity_policy",
                        LEGACY_RECORD_IDENTITY_POLICY,
                    )
                )
                if existing_identity_policy != record_identity_policy:
                    raise PlatformError("Idempotency key is bound to a different record identity policy.")
                counts = self.connection.execute(
                    """
                    SELECT
                        COUNT(CASE WHEN left_id <> '' THEN 1 END) AS result_count,
                        COUNT(CASE WHEN status = 'Matched' THEN 1 END) AS matched_count
                    FROM match_results
                    WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
                return MatchRunResult(
                    job_id=job_id,
                    result_count=int(counts["result_count"] or 0),
                    matched_count=int(counts["matched_count"] or 0),
                    financial_input_policy=existing_policy,
                    record_identity_policy=existing_identity_policy,
                )
        exact_field_list = [field.strip() for field in exact_fields.split(",") if field.strip()]
        tolerance = _non_negative_amount(
            amount_tolerance,
            field="match amount tolerance",
            input_policy=financial_input_policy,
        )
        rule: dict[str, object] = {
            "amount_field": amount_field,
            "date_field": date_field,
            "reference_field": reference_field,
            "exact_fields": exact_field_list,
            "amount_tolerance": _decimal_text(tolerance),
            "date_window_days": date_window_days,
            "allow_many_to_one": allow_many_to_one,
            "allow_one_to_many": allow_one_to_many,
            "allow_many_to_many": allow_many_to_many,
            "financial_input_policy": financial_input_policy,
            "record_identity_policy": record_identity_policy,
        }
        try:
            normalization_rules = _parse_reference_normalization_rules(reference_normalization_rules)
            rule["reference_normalization_rules"] = asdict(normalization_rules)
            rule_json = self._matching_rule_document(rule, producer=True).text
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                """
                INSERT INTO match_jobs (
                    id, workspace_id, name, left_source, right_source, status,
                    rule_json, created_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, 'Running', ?, ?, ?)
                """,
                (
                    job_id,
                    workspace_id,
                    name,
                    left_source,
                    right_source,
                    rule_json,
                    actor_label,
                    created_at,
                ),
            )
            self.connection.execute(
                "INSERT INTO match_rules (id, job_id, rule_name, rule_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (platform_id("MR", job_id, "primary"), job_id, "primary", rule_json, created_at),
            )
            located_left_records = self._records_with_source_locations(
                left_records,
                source_name=left_source,
            )
            located_right_records = self._records_with_source_locations(
                right_records,
                source_name=right_source,
            )
            output = self.match_records(
                left_records=located_left_records,
                right_records=located_right_records,
                left_id_field=left_id_field,
                right_id_field=right_id_field,
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
                exact_fields=",".join(exact_field_list),
                amount_tolerance=tolerance,
                date_window_days=date_window_days,
                allow_many_to_one=allow_many_to_one,
                allow_one_to_many=allow_one_to_many,
                allow_many_to_many=allow_many_to_many,
                reference_normalization_rules=normalization_rules,
                financial_input_policy=financial_input_policy,
                record_identity_policy=record_identity_policy,
                _source_locations_trusted=True,
            )
            result_count = 0
            matched_count = 0
            exception_count = len(output.exceptions)
            for result in output.results:
                left_id = str(result.get("left_id", ""))
                right_id = str(result.get("right_id", ""))
                date_difference_days = result.get("date_difference_days")
                if date_difference_days is not None and not isinstance(date_difference_days, int):
                    raise PlatformError("Invalid date_difference_days value produced by matching engine.")
                self._insert_result(
                    job_id=job_id,
                    left_id=left_id,
                    right_id=right_id,
                    match_type=str(result.get("match_type")),
                    confidence=_coerce_confidence(result.get("confidence", 0)),
                    explanation=str(result.get("explanation", "")),
                    amount_difference=(
                        _parse_amount(
                            result.get("amount_difference", "0"),
                            input_policy=financial_input_policy,
                        )
                        or Decimal("0")
                    ),
                    date_difference_days=date_difference_days,
                    status=str(result.get("status", "Unmatched")),
                    reason_code=str(result.get("reason_code", "")),
                    lineage=result.get("lineage", {}),
                )
                if left_id:
                    result_count += 1
                if result.get("status") == "Matched":
                    matched_count += 1
            self.connection.execute(
                "UPDATE match_jobs SET status = 'Complete', completed_at = ? WHERE id = ?",
                (utc_now_text(), job_id),
            )
            audit(
                self.connection,
                actor_label=actor_label,
                object_type="match_job",
                object_id=job_id,
                action="match_job_completed",
                metadata={
                    "result_count": result_count,
                    "matched_count": matched_count,
                    "exception_count": exception_count,
                    "financial_input_policy": financial_input_policy,
                    "record_identity_policy": record_identity_policy,
                },
            )
            append_outbox_event(
                self.connection,
                event_id=platform_id("OB", job_id, "match_job_completed"),
                event_type="match_job.completed",
                aggregate_type="match_job",
                aggregate_id=job_id,
                payload={
                    "job_id": job_id,
                    "result_count": result_count,
                    "matched_count": matched_count,
                    "exception_count": exception_count,
                    "financial_input_policy": financial_input_policy,
                    "record_identity_policy": record_identity_policy,
                },
            )
            self.connection.commit()
        except (sqlite3.DatabaseError, AuditLedgerError, PlatformError) as exc:
            self.connection.rollback()
            if isinstance(exc, PlatformError):
                raise
            raise PlatformError("Unable to complete the match job; all results were rolled back.") from exc
        return MatchRunResult(
            job_id=job_id,
            result_count=result_count,
            matched_count=matched_count,
            financial_input_policy=financial_input_policy,
            record_identity_policy=record_identity_policy,
        )

    def _insert_result(
        self,
        *,
        job_id: str,
        left_id: str,
        right_id: str,
        match_type: str,
        confidence: Decimal,
        explanation: str,
        amount_difference: Decimal,
        date_difference_days: int | None,
        status: str,
        reason_code: str = "",
        lineage: dict[str, object] | None = None,
    ) -> None:
        result_id = platform_id("MRSLT", job_id, left_id, right_id, match_type)
        columns = [
            "id",
            "job_id",
            "left_id",
            "right_id",
            "match_type",
            "confidence",
            "explanation",
            "amount_difference",
            "amount_difference_decimal",
            "date_difference_days",
            "status",
            "created_at",
        ]
        values = [
            result_id,
            job_id,
            left_id,
            right_id,
            match_type,
            _decimal_text(confidence),
            explanation,
            str(amount_difference),
            _decimal_text(amount_difference),
            date_difference_days if date_difference_days is not None else -1,
            status,
            utc_now_text(),
        ]
        if "reason_code" in self._match_results_columns():
            columns.append("reason_code")
            values.append(reason_code)
        if "lineage_json" in self._match_results_columns():
            columns.append("lineage_json")
            values.append(self._json_text(lineage or {}))
        column_sql = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(values))
        insert_sql = f"""
            INSERT OR IGNORE INTO match_results (
                {column_sql}
            ) VALUES ({placeholders})
        """
        self.connection.execute(insert_sql, values)
