"""Complete PostgreSQL adapter for the deterministic Matching Application port."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from reconforge.application.matching import (
    LEGACY_RECORD_IDENTITY_POLICY,
    DeterministicMatchOutput,
    MatchRunResult,
    ReferenceNormalizationRules,
)
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationNotFoundError,
    PostgresReconciliationRepository,
)
from reconforge.platform.common import PlatformError, read_local_record_document
from reconforge.reconciliation.deterministic_engine import DeterministicMatchingEngine
from reconforge.reconciliation.matching import (
    INTERNAL_LINEAGE_COLUMNS,
    RECORD_IDENTITY_POLICY,
    SOURCE_POSITION_COLUMN,
    SOURCE_ROW_BASIS_COLUMN,
    SOURCE_ROW_COLUMN,
)
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY, FinancialInputPolicy

POSTGRES_MATCHING_APPLICATION_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS reconforge.matching_run_workspaces (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,run_id),
    FOREIGN KEY (tenant_id,run_id)
        REFERENCES reconforge.reconciliation_runs(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,workspace_id)
        REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS matching_run_workspaces_scope_idx
ON reconforge.matching_run_workspaces(tenant_id,workspace_id,created_at DESC,run_id);
ALTER TABLE reconforge.matching_run_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.matching_run_workspaces FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON reconforge.matching_run_workspaces;
DO $rls$ BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM pg_policies WHERE schemaname='reconforge'
  AND tablename='matching_run_workspaces' AND policyname='tenant_scope'
 ) THEN
  CREATE POLICY tenant_isolation ON reconforge.matching_run_workspaces
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
 END IF;
END $rls$;
"""


class PostgresMatchingError(RuntimeError):
    """Safe failure at the tenant-scoped Matching adapter boundary."""


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda item: format(item, "f") if isinstance(item, Decimal) else str(item),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise PlatformError("Matching configuration is not deterministically serializable.") from exc


def _text(value: object, label: str, *, maximum: int = 255) -> str:
    result = " ".join(str(value or "").strip().split())
    if not result or len(result) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in result):
        raise PlatformError(f"{label} is invalid or exceeds {maximum} characters.")
    return result


def _located_records(records: list[dict[str, Any]], source_name: str) -> list[dict[str, Any]]:
    suffix = Path(source_name).suffix.casefold()
    basis = "tabular-header-offset-v1" if suffix == ".csv" else "json-record-position-v1"
    located = []
    for position, record in enumerate(records, start=1):
        clean = {str(key): value for key, value in record.items() if str(key) not in INTERNAL_LINEAGE_COLUMNS}
        clean[SOURCE_POSITION_COLUMN] = position
        clean[SOURCE_ROW_COLUMN] = position + 1 if suffix == ".csv" else None
        clean[SOURCE_ROW_BASIS_COLUMN] = basis
        located.append(clean)
    return located


def _source_identity_map(output: DeterministicMatchOutput) -> dict[str, dict[int, tuple[str, str]]]:
    mapped: dict[str, dict[int, tuple[str, str]]] = {"Left": {}, "Right": {}}
    for result in output.results:
        lineage = result.get("lineage")
        if not isinstance(lineage, Mapping):
            continue
        for side, id_key, lineage_key in (
            ("Left", "left_id", "left_record"),
            ("Right", "right_id", "right_record"),
        ):
            source_id = str(result.get(id_key, ""))
            record_lineage = lineage.get(lineage_key)
            if not source_id or not isinstance(record_lineage, Mapping):
                continue
            location = record_lineage.get("source_location")
            position = location.get("position") if isinstance(location, Mapping) else None
            fingerprint = str(record_lineage.get("record_fingerprint", ""))
            if isinstance(position, int) and position > 0 and fingerprint:
                existing = mapped[side].get(position)
                if existing is not None and existing != (source_id, fingerprint):
                    raise PlatformError("Matching engine returned conflicting source lineage.")
                mapped[side][position] = (source_id, fingerprint)
    return mapped


class PostgresMatchingRepository:
    """Execute one engine and persist its complete explainable result in PostgreSQL."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self.persistence = PostgresReconciliationRepository(connection)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except (PlatformError, PostgresMatchingError):
            raise
        except Exception as exc:
            raise PostgresMatchingError("PostgreSQL Matching operation failed.") from exc

    def _workspace_id(self, workspace: str) -> str:
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, _text(workspace, "Workspace name")),
        ).fetchone()
        if row is None:
            raise PostgresMatchingError("Matching workspace was not found for this tenant.")
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _currency_precision(self, currency_code: str) -> tuple[int | None, str | None]:
        code = str(currency_code).strip().upper()
        if not code:
            return None, None
        row = self.connection.execute(
            "SELECT minor_units,active FROM reconforge.currencies WHERE tenant_id=%s AND code=%s",
            (self.tenant_id, code),
        ).fetchone()
        if row is None:
            return None, "UNKNOWN_CURRENCY"
        minor_units = row["minor_units"] if isinstance(row, Mapping) else row[0]
        active = row["active"] if isinstance(row, Mapping) else row[1]
        return (int(minor_units), None) if bool(active) else (None, "INACTIVE_CURRENCY")

    def _engine(self) -> DeterministicMatchingEngine:
        return DeterministicMatchingEngine(self._currency_precision)

    def _run_link(self, run_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT workspace_id FROM reconforge.matching_run_workspaces WHERE tenant_id=%s AND run_id=%s",
            (self.tenant_id, run_id),
        ).fetchone()
        if row is None:
            raise PlatformError("Match job not found.")
        return self.persistence.get_run(tenant_id=self.tenant_id, run_id=run_id)

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
        left_document = read_local_record_document(left_path)
        right_document = read_local_record_document(right_path)
        return self._run_records(
            left_records=_located_records(left_document.records, left_document.source_path.name),
            right_records=_located_records(right_document.records, right_document.source_path.name),
            workspace=workspace,
            name=name,
            left_source=left_document.source_path.name,
            right_source=right_document.source_path.name,
            left_checksum=left_document.checksum_sha256,
            right_checksum=right_document.checksum_sha256,
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
        if isinstance(rows, bool) or not 1 <= rows <= 250_000:
            raise PlatformError("Benchmark rows must be between 1 and 250000.")
        left = [
            {"id": f"L-{index}", "reference": f"REF-{index}", "amount": index * 10, "date": "2026-01-15"}
            for index in range(rows)
        ]
        right = [
            {"id": f"R-{index}", "reference": f"REF-{index}", "amount": index * 10, "date": "2026-01-15"}
            for index in range(rows)
        ]
        payload_hash = hashlib.sha256(_canonical_json({"rows": rows}).encode()).hexdigest()
        return self._run_records(
            left_records=_located_records(left, "synthetic-left.json"),
            right_records=_located_records(right, "synthetic-right.json"),
            workspace=workspace,
            name=f"synthetic-benchmark-{rows}",
            left_source="synthetic-left",
            right_source="synthetic-right",
            left_checksum=payload_hash,
            right_checksum=payload_hash,
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
            reference_normalization_rules=None,
            idempotency_key=None,
            actor_label=actor_label,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            record_identity_policy=RECORD_IDENTITY_POLICY,
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
        left_checksum: str,
        right_checksum: str,
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
        reference_normalization_rules: Mapping[str, object] | None,
        idempotency_key: str | None,
        actor_label: str,
        financial_input_policy: FinancialInputPolicy,
        record_identity_policy: str,
    ) -> MatchRunResult:
        rule: dict[str, object] = {
            "left_id_field": left_id_field,
            "right_id_field": right_id_field,
            "amount_field": amount_field,
            "date_field": date_field,
            "reference_field": reference_field,
            "exact_fields": [field.strip() for field in exact_fields.split(",") if field.strip()],
            "amount_tolerance": str(amount_tolerance),
            "date_window_days": date_window_days,
            "allow_many_to_one": allow_many_to_one,
            "allow_one_to_many": allow_one_to_many,
            "allow_many_to_many": allow_many_to_many,
            "reference_normalization_rules": dict(reference_normalization_rules or {}),
            "financial_input_policy": financial_input_policy,
            "record_identity_policy": record_identity_policy,
        }
        fingerprint = hashlib.sha256(
            _canonical_json(
                {"workspace": workspace, "left": left_checksum, "right": right_checksum, "rule": rule}
            ).encode()
        ).hexdigest()
        run_id = (
            "match-"
            + hashlib.sha256(
                _canonical_json(
                    {
                        "tenant": self.tenant_id,
                        "workspace": workspace,
                        "name": name,
                        "fingerprint": fingerprint,
                        "idempotency": idempotency_key or uuid4().hex,
                    }
                ).encode()
            ).hexdigest()[:48]
        )
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            created = self.persistence.create_run(
                tenant_id=self.tenant_id,
                run_id=run_id,
                name=_text(name, "Match job name"),
                left_source=left_source,
                right_source=right_source,
                algorithm_version="deterministic-matching-engine-v1",
                rule=rule,
                input_hash=fingerprint,
                idempotency_key=idempotency_key,
                actor_id=actor_label,
            )
            actual_run_id = str(created["id"])
            self.connection.execute(
                "INSERT INTO reconforge.matching_run_workspaces(tenant_id,run_id,workspace_id) VALUES (%s,%s,%s) ON CONFLICT(tenant_id,run_id) DO NOTHING",
                (self.tenant_id, actual_run_id, workspace_id),
            )
            if created["status"] == "Complete":
                return MatchRunResult(
                    job_id=actual_run_id,
                    result_count=int(created["result_count"]),
                    matched_count=int(created["matched_count"]),
                    financial_input_policy=financial_input_policy,
                    record_identity_policy=record_identity_policy,
                )
            output = self._engine().match_records(
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
                _source_locations_trusted=True,
            )
            identities = _source_identity_map(output)
            self._register_inputs(
                actual_run_id,
                "Left",
                left_records,
                identities["Left"],
                amount_field,
                date_field,
                reference_field,
                allow_one_to_many or allow_many_to_many,
            )
            self._register_inputs(
                actual_run_id,
                "Right",
                right_records,
                identities["Right"],
                amount_field,
                date_field,
                reference_field,
                allow_many_to_one or allow_many_to_many,
            )
            for result in output.results:
                self.persistence.append_result(
                    tenant_id=self.tenant_id,
                    run_id=actual_run_id,
                    left_id=str(result.get("left_id", "")),
                    right_id=str(result.get("right_id", "")),
                    match_type=str(result.get("match_type", "deterministic")),
                    confidence=result.get("confidence", "0"),
                    explanation=str(result.get("explanation", "Matching result.")),
                    amount_difference=result.get("amount_difference", "0"),
                    date_difference_days=result.get("date_difference_days")
                    if isinstance(result.get("date_difference_days"), int)
                    else None,
                    status=str(result.get("status", "Unmatched")),
                    reason_code=str(result.get("reason_code", "")),
                    lineage=result.get("lineage") if isinstance(result.get("lineage"), Mapping) else {},
                )
            for exception in output.exceptions:
                self.persistence.append_exception(
                    tenant_id=self.tenant_id,
                    run_id=actual_run_id,
                    exception_type=str(exception["exception_type"]),
                    source_side=str(exception["source_side"]),
                    source_id=str(exception["source_id"]),
                    title=str(exception["title"]),
                    explanation=str(exception["explanation"]),
                    severity=str(exception["severity"]),
                    risk_score=exception["risk_score"],
                    reason_code=str(exception["reason_code"]),
                    evidence=exception.get("evidence") if isinstance(exception.get("evidence"), Mapping) else {},
                )
            completed = self.persistence.complete_run(
                tenant_id=self.tenant_id,
                run_id=actual_run_id,
                actor_id=actor_label,
            )
            return MatchRunResult(
                job_id=actual_run_id,
                result_count=int(completed["result_count"]),
                matched_count=int(completed["matched_count"]),
                financial_input_policy=financial_input_policy,
                record_identity_policy=record_identity_policy,
            )

    def _register_inputs(
        self,
        run_id: str,
        side: str,
        records: list[dict[str, Any]],
        identities: dict[int, tuple[str, str]],
        amount_field: str,
        date_field: str,
        reference_field: str,
        allow_multiple: bool,
    ) -> None:
        if len(identities) != len(records):
            raise PlatformError("Matching engine did not return complete source lineage.")
        for position, record in enumerate(records, start=1):
            source_id, fingerprint = identities[position]
            raw_amount = record.get(amount_field)
            try:
                parsed_amount = Decimal(str(raw_amount).strip())
                amount: object | None = parsed_amount if parsed_amount.is_finite() else None
            except (InvalidOperation, ValueError, TypeError):
                amount = None
            raw_date = str(record.get(date_field, "") or "")
            try:
                date_value: object | None = date.fromisoformat(raw_date).isoformat()
            except ValueError:
                date_value = None
            raw_currency = str(record.get("currency", record.get("currency_code", "")) or "").strip().upper()
            currency = raw_currency if len(raw_currency) == 3 and raw_currency.isalpha() else ""
            attributes = {str(key): value for key, value in record.items() if str(key) not in INTERNAL_LINEAGE_COLUMNS}
            self.persistence.register_input(
                tenant_id=self.tenant_id,
                run_id=run_id,
                side=side,
                source_id=source_id,
                record_hash=fingerprint,
                amount=amount,
                amount_original="" if raw_amount is None else str(raw_amount),
                currency_code=currency,
                date_original=raw_date,
                date_value=date_value,
                reference_original=str(record.get(reference_field, "") or ""),
                attributes=attributes,
                valid=bool(record.get("valid", True)) and amount is not None,
                allowed_uses=1_000 if allow_multiple else 1,
            )

    def job_status(self, job_id: str) -> dict[str, Any]:
        with self._transaction():
            try:
                return self._run_link(job_id)
            except PostgresReconciliationNotFoundError as exc:
                raise PlatformError("Match job not found.") from exc

    def results(self, job_id: str, *, status: str = "") -> list[dict[str, Any]]:
        with self._transaction():
            self._run_link(job_id)
            rows = self.persistence.list_results(tenant_id=self.tenant_id, run_id=job_id)
            return [row for row in rows if not status or str(row["status"]) == status]

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._transaction():
            rows = self.connection.execute(
                "SELECT run_id FROM reconforge.matching_run_workspaces WHERE tenant_id=%s ORDER BY created_at DESC,run_id DESC",
                (self.tenant_id,),
            ).fetchall()
            return [
                self.persistence.get_run_metadata(
                    tenant_id=self.tenant_id, run_id=str(row["run_id"] if isinstance(row, Mapping) else row[0])
                )
                for row in rows
            ]

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
        with self._transaction():
            return self._engine().match_records(
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
