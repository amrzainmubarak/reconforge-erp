"""Scalable deterministic matching foundations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    audit,
    date_diff_days,
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


@dataclass(frozen=True)
class MatchRunResult:
    """Result from one deterministic match job."""

    job_id: str
    result_count: int
    matched_count: int


class MatchingService:
    """Indexed candidate-generation matching engine."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection

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
        amount_tolerance: float = 0.0,
        date_window_days: int = 0,
        allow_many_to_one: bool = False,
        actor_label: str = "local-cli",
    ) -> MatchRunResult:
        """Run deterministic local matching without a full cross product where possible."""

        require_permission(self.connection, actor_label=actor_label, permission="match.run")
        left_source, left_records = read_local_records(left_path)
        right_source, right_records = read_local_records(right_path)
        return self._run_records(
            left_records=left_records,
            right_records=right_records,
            workspace=workspace,
            name=name,
            left_source=left_source.name,
            right_source=right_source.name,
            left_id_field=left_id_field,
            right_id_field=right_id_field,
            amount_field=amount_field,
            date_field=date_field,
            reference_field=reference_field,
            exact_fields=exact_fields,
            amount_tolerance=amount_tolerance,
            date_window_days=date_window_days,
            allow_many_to_one=allow_many_to_one,
            actor_label=actor_label,
        )

    def benchmark(self, *, rows: int, workspace: str = "default", actor_label: str = "local-cli") -> MatchRunResult:
        """Run a synthetic local benchmark job and persist summary results."""

        require_permission(self.connection, actor_label=actor_label, permission="match.run")
        if rows < 1 or rows > 250000:
            raise PlatformError("Benchmark rows must be between 1 and 250000.")
        left_records = [
            {"id": f"L-{index}", "reference": f"REF-{index}", "amount": index * 10.0, "date": "2026-01-15"}
            for index in range(rows)
        ]
        right_records = [
            {"id": f"R-{index}", "reference": f"REF-{index}", "amount": index * 10.0, "date": "2026-01-15"}
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
            amount_tolerance=0.0,
            date_window_days=0,
            allow_many_to_one=False,
            actor_label=actor_label,
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """Return one match job status."""

        row = self.connection.execute("SELECT * FROM match_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise PlatformError("Match job not found.")
        payload = dict(row)
        counts = self.connection.execute(
            """
            SELECT
                COUNT(*) AS result_count,
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
                "SELECT * FROM match_results WHERE job_id = ? AND status = ? ORDER BY confidence DESC, left_id",
                (job_id, status),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM match_results WHERE job_id = ? ORDER BY confidence DESC, left_id",
                (job_id,),
            ).fetchall()
        return rows_to_dicts(rows)

    def list_jobs(self) -> list[dict[str, Any]]:
        """List match jobs."""

        return rows_to_dicts(self.connection.execute("SELECT * FROM match_jobs ORDER BY created_at DESC").fetchall())

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
        amount_tolerance: float,
        date_window_days: int,
        allow_many_to_one: bool,
        actor_label: str,
    ) -> MatchRunResult:
        workspace_id = ensure_workspace(self.connection, workspace)
        created_at = utc_now_text()
        job_id = platform_id("MJ", workspace_id, name, left_source, right_source, created_at)
        exact_field_list = [field.strip() for field in exact_fields.split(",") if field.strip()]
        rule: dict[str, object] = {
            "amount_field": amount_field,
            "date_field": date_field,
            "reference_field": reference_field,
            "exact_fields": exact_field_list,
            "amount_tolerance": amount_tolerance,
            "date_window_days": date_window_days,
            "allow_many_to_one": allow_many_to_one,
        }
        self.connection.execute(
            """
            INSERT INTO match_jobs (
                id, workspace_id, name, left_source, right_source, status,
                rule_json, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, 'Running', ?, ?, ?)
            """,
            (job_id, workspace_id, name, left_source, right_source, json.dumps(rule, sort_keys=True), actor_label, created_at),
        )
        self.connection.execute(
            "INSERT INTO match_rules (id, job_id, rule_name, rule_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (platform_id("MR", job_id, "primary"), job_id, "primary", json.dumps(rule, sort_keys=True), created_at),
        )
        right_index = self._build_right_index(
            right_records,
            right_id_field=right_id_field,
            amount_field=amount_field,
            reference_field=reference_field,
            exact_fields=exact_field_list,
        )
        used_right: set[str] = set()
        result_count = 0
        matched_count = 0
        for index, left in enumerate(left_records, start=1):
            left_id = normalize_key(left.get(left_id_field), default=f"L-{index}")
            candidates = self._candidates(left, right_index, amount_field=amount_field, reference_field=reference_field, exact_fields=exact_field_list)
            best = self._best_candidate(
                left,
                candidates,
                right_id_field=right_id_field,
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
                exact_fields=exact_field_list,
                amount_tolerance=amount_tolerance,
                date_window_days=date_window_days,
                used_right=used_right,
                allow_many_to_one=allow_many_to_one,
            )
            if best is None:
                self._insert_result(
                    job_id=job_id,
                    left_id=left_id,
                    right_id="",
                    match_type="unmatched",
                    confidence=0.0,
                    explanation="No indexed candidate met the configured rules.",
                    amount_difference=0.0,
                    date_difference_days=0,
                    status="Unmatched",
                )
            else:
                right, confidence, explanation = best
                right_id = normalize_key(right.get(right_id_field), default="")
                used_right.add(right_id)
                amount_difference = round(to_float(left.get(amount_field)) - to_float(right.get(amount_field)), 2)
                self._insert_result(
                    job_id=job_id,
                    left_id=left_id,
                    right_id=right_id,
                    match_type="deterministic",
                    confidence=confidence,
                    explanation=explanation,
                    amount_difference=amount_difference,
                    date_difference_days=date_diff_days(left.get(date_field), right.get(date_field)),
                    status="Matched",
                )
                matched_count += 1
            result_count += 1
        self.connection.execute(
            "UPDATE match_jobs SET status = 'Complete', completed_at = ? WHERE id = ?",
            (utc_now_text(), job_id),
        )
        self.connection.commit()
        audit(
            self.connection,
            actor_label=actor_label,
            object_type="match_job",
            object_id=job_id,
            action="match_job_completed",
            metadata={"result_count": result_count, "matched_count": matched_count},
        )
        return MatchRunResult(job_id=job_id, result_count=result_count, matched_count=matched_count)

    def _build_right_index(
        self,
        right_records: list[dict[str, Any]],
        *,
        right_id_field: str,
        amount_field: str,
        reference_field: str,
        exact_fields: list[str],
    ) -> dict[str, dict[str, list[dict[str, Any]]]]:
        indexes: dict[str, dict[str, list[dict[str, Any]]]] = {"reference": {}, "amount": {}, "exact": {}}
        for index, record in enumerate(right_records, start=1):
            record.setdefault(right_id_field, f"R-{index}")
            reference = normalize_text(record.get(reference_field))
            if reference:
                indexes["reference"].setdefault(reference, []).append(record)
            amount_bucket = str(round(to_float(record.get(amount_field)), 2))
            indexes["amount"].setdefault(amount_bucket, []).append(record)
            if exact_fields:
                key = self._exact_key(record, exact_fields)
                indexes["exact"].setdefault(key, []).append(record)
        return indexes

    def _candidates(
        self,
        left: dict[str, Any],
        right_index: dict[str, dict[str, list[dict[str, Any]]]],
        *,
        amount_field: str,
        reference_field: str,
        exact_fields: list[str],
    ) -> list[dict[str, Any]]:
        reference = normalize_text(left.get(reference_field))
        if reference and reference in right_index["reference"]:
            return right_index["reference"][reference]
        if exact_fields:
            key = self._exact_key(left, exact_fields)
            if key in right_index["exact"]:
                return right_index["exact"][key]
        amount_bucket = str(round(to_float(left.get(amount_field)), 2))
        return right_index["amount"].get(amount_bucket, [])

    def _best_candidate(
        self,
        left: dict[str, Any],
        candidates: list[dict[str, Any]],
        *,
        right_id_field: str,
        amount_field: str,
        date_field: str,
        reference_field: str,
        exact_fields: list[str],
        amount_tolerance: float,
        date_window_days: int,
        used_right: set[str],
        allow_many_to_one: bool,
    ) -> tuple[dict[str, Any], float, str] | None:
        best: tuple[dict[str, Any], float, str] | None = None
        for candidate in candidates:
            right_id = normalize_key(candidate.get(right_id_field), default="")
            if right_id in used_right and not allow_many_to_one:
                continue
            confidence, parts = self._score_candidate(
                left,
                candidate,
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
                exact_fields=exact_fields,
                amount_tolerance=amount_tolerance,
                date_window_days=date_window_days,
            )
            if confidence < 0.65:
                continue
            explanation = "; ".join(parts)
            if best is None or confidence > best[1]:
                best = (candidate, confidence, explanation)
        return best

    def _score_candidate(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
        *,
        amount_field: str,
        date_field: str,
        reference_field: str,
        exact_fields: list[str],
        amount_tolerance: float,
        date_window_days: int,
    ) -> tuple[float, list[str]]:
        score = 0.0
        parts: list[str] = []
        if normalize_text(left.get(reference_field)) and normalize_text(left.get(reference_field)) == normalize_text(right.get(reference_field)):
            score += 0.45
            parts.append("reference matched")
        amount_diff = abs(to_float(left.get(amount_field)) - to_float(right.get(amount_field)))
        if amount_diff <= amount_tolerance:
            score += 0.30
            parts.append(f"amount within tolerance ({amount_diff:.2f})")
        day_diff = date_diff_days(left.get(date_field), right.get(date_field))
        if day_diff <= date_window_days:
            score += 0.15
            parts.append(f"date within window ({day_diff} days)")
        if exact_fields and self._exact_key(left, exact_fields) == self._exact_key(right, exact_fields):
            score += 0.10
            parts.append("exact key fields matched")
        return round(min(score, 1.0), 2), parts

    def _insert_result(
        self,
        *,
        job_id: str,
        left_id: str,
        right_id: str,
        match_type: str,
        confidence: float,
        explanation: str,
        amount_difference: float,
        date_difference_days: int,
        status: str,
    ) -> None:
        result_id = platform_id("MRSLT", job_id, left_id, right_id, match_type)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO match_results (
                id, job_id, left_id, right_id, match_type, confidence, explanation,
                amount_difference, date_difference_days, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result_id,
                job_id,
                left_id,
                right_id,
                match_type,
                confidence,
                explanation,
                amount_difference,
                date_difference_days,
                status,
                utc_now_text(),
            ),
        )

    @staticmethod
    def _exact_key(record: dict[str, Any], fields: list[str]) -> str:
        return "|".join(normalize_text(record.get(field)).lower() for field in fields)
